"""
Отчёты партнёров — загрузка файлов площадок (ML Finance).

  GET    /partner-reports                  — список загруженных отчётов
  POST   /partner-reports/preview          — разобрать файл БЕЗ записи
  POST   /partner-reports                  — сохранить разобранный отчёт
  DELETE /partner-reports/{id}             — удалить отчёт вместе со строками
  GET    /partner-reports/{id}/rows        — строки отчёта
  GET    /partner-reports/rules/{partner}  — правило разбора партнёра
  PUT    /partner-reports/rules/{partner}  — сохранить правило

ЗАГРУЗКА В ДВА ШАГА: «разобрать» → «сохранить», как у номенклатуры. Человек
сначала видит, что получилось из его файла — какие колонки нашлись, какие
суммы вышли, сколько строк не опознано, — и только потом это ложится в базу.
Отчёт площадки приходит раз в квартал, и залить его вслепую значит узнать об
ошибке через три месяца.

ПРАВИЛО РАЗБОРА ЖИВЁТ У ПАРТНЁРА, А НЕ У ФАЙЛА: формат отчёта — свойство
площадки. Настроили один раз по образцу — дальше файлы того же партнёра
читаются сами. Это и просил владелец: «к каждому партнёру загрузить образец,
на основе которого сделаем правила обработки».

ПРЕДПРОСМОТР НЕ ТРЕБУЕТ ПРАВИЛА. Файл можно бросить в окно и без настройки:
сервер прочитает шапку, предложит соответствие по названиям колонок
(suggest_mapping) и покажет, что получится. Правило после этого сохраняется
одной кнопкой — то есть образец и есть первый загруженный файл.

ЧЕГО ЗДЕСЬ НЕТ: расчёта роялти. Отчёт приводится к единому виду (артикул,
количество, сумма авторских, сумма смежных) и складывается в базу; кому и
сколько из этих сумм причитается — следующий шаг, он живёт в правах на треки.
"""
import hashlib
import io
import json
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import (
    Partner,
    PartnerPayment,
    PartnerReport,
    PartnerReportRow,
    PartnerReportRule,
    PartnerTrackAlias,
    Track,
    User,
)
from app.partner_reports import (
    column_values,
    currency_factor,
    period_from_column,
    ATTR_FIELDS,
    MAPPABLE_FIELDS,
    FIELDS,
    sku_configured,
    FIELD_LABELS,
    artist_tokens,
    find_period,
    normalize_name,
    mapping_columns,
    match_builtin,
    normalize_header,
    parse_report,
    period_label,
    pick_track,
    report_region,
    read_columns,
    read_head,
    rubles,
    search_word,
    sheet_names,
    suggest_mapping,
)
from app.roles import CAN_MANAGE_PARTNER_REPORTS, CAN_VIEW_PARTNER_REPORTS
from app.payments_import import parse_currency_note
from app.routers_payments import payment_numbers
from app.routers_templates import _content_disposition

partner_reports_router = APIRouter(
    prefix="/partner-reports",
    tags=["partner-reports"],
    dependencies=[Depends(require_role(*CAN_VIEW_PARTNER_REPORTS))],
)

# Сколько строк файла показываем в предпросмотре. ПЯТЬ (просьба владельца
# 18.09.2026, было двадцать): предпросмотр отвечает на один вопрос — верно ли
# поняты колонки, — и пяти строк для этого хватает, а экран остаётся коротким.
# Строки без трека приходят отдельным списком и показываются по кнопке целиком.
PREVIEW_ROWS = 5
# Строки, к которым не нашлось трека, показываем ВСЕ (до этого предела) — даже
# если они лежат в середине файла, за пределами первой сотни. Иначе кнопка
# «показать строки без артикула» показывала бы не строки без артикула, а те из
# них, что случайно попали в начало.
UNMATCHED_PREVIEW = 300
# Предел на файл — защита от «прислали не то», а не норматив.
#
# Был 300 000 и отсекал три четверти настоящих отчётов (сверено с папкой
# поступлений за 2 кв. 2026: Believe RU — 584 тыс. строк, Spotify — 494 тыс.,
# ОМА — 1.58 млн, и это один квартал). Прежняя оценка «квартальный отчёт это
# десятки тысяч строк» была снята с единственного знакомого файла — МТС, где
# их 657.
MAX_ROWS = 3_000_000

# Сколько значений кладём в один `IN (...)`. PostgreSQL принимает не больше
# 65 535 параметров на запрос, и на отчёте в полмиллиона строк список артикулов
# упирался в этот предел: приходила ОШИБКА ДРАЙВЕРА, а не долгое ожидание —
# то есть крупный отчёт не загружался вовсе, сколько его ни жди.
SKU_BATCH = 10_000

# ПАРАМЕТРЫ ОТЧЁТА — те же четыре, что в Dista: тип контента, тип и вид
# использования, территория. Они одинаковы для всего файла и дальше уйдут в
# отчёт правообладателю, поэтому хранятся у отчёта снимком, а у правила
# партнёра — значением по умолчанию.
#
# СТРОКИ, А НЕ СПРАВОЧНИК: какие значения бывают, знает площадка, а не мы.
# Любой зафиксированный список разошёлся бы с первым же новым партнёром;
# подсказки в поле собираются по тому, что уже вводили (`/attributes`).
# ОДИН СПИСОК НА ВСЁ: те же четыре имени служат и снимком в шапке отчёта, и
# полями строки, и ключами правила (`ATTR_FIELDS` в `partner_reports`).
# Разойдись они — параметр, взятый из колонки, молча не попал бы в строку.
REPORT_ATTRS = ATTR_FIELDS
ATTR_LABELS = {name: FIELD_LABELS[name] for name in REPORT_ATTRS}
MAX_ATTR_LEN = 120


def _alias_key(title, artist) -> tuple:
    """
    Ключ запомненного сопоставления: нормализованные название и исполнитель.

    Нормализуем тем же кодом, что и подбор по названию: иначе «Тмстс!» и
    «тмстс» стали бы разными ключами, и одно и то же сопоставление
    запоминалось бы дважды — а при следующем отчёте не нашлось бы ни одно.
    """
    return normalize_name(title), " ".join(artist_tokens(artist))


def _tracks_by_sku(db: Session, skus) -> dict:
    """
    Артикул → id трека. ПАЧКАМИ, а не одним списком: см. SKU_BATCH.

    Одним `IN (...)` это работало ровно до первого крупного отчёта — на
    полумиллионе строк запрос упирался в предел параметров PostgreSQL.
    """
    skus = list(skus)
    found: dict = {}
    for start in range(0, len(skus), SKU_BATCH):
        for sku, track_id in db.execute(
            select(Track.sku, Track.id).where(
                Track.sku.in_(skus[start:start + SKU_BATCH])
            )
        ):
            found[sku] = track_id
    return found


def _aliases_for(db: Session, partner_id, rows: list) -> dict:
    """
    Что мы уже запоминали для этой площадки — по строкам этого файла.

    ДВЕ СТРАТЕГИИ, и выбор между ними не про удобство, а про предел параметров
    в запросе. У небольшого отчёта дешевле спросить по его ключам: сопоставлений
    у площадки со временем накопятся тысячи, а в файле строк сотни. У крупного
    наоборот — в отчёте Believe полмиллиона разных названий, списком в запрос
    они не лезут, и проще забрать все сопоставления площадки и отсеять на месте:
    их всё равно на порядки меньше.
    """
    keys = {_alias_key(r.title, r.artist) for r in rows if r.title}
    if not keys:
        return {}
    query = select(PartnerTrackAlias).where(PartnerTrackAlias.partner_id == partner_id)
    if len(keys) <= SKU_BATCH:
        query = query.where(PartnerTrackAlias.title_key.in_({k[0] for k in keys}))
    found = db.execute(query).scalars()
    return {(a.title_key, a.artist_key): a.sku for a in found}


# ПОЗИЦИЯ «ВНЕ КАТАЛОГА» — куда складываются строки, которым в номенклатуре
# ничего не соответствует (просьба владельца 24.09.2026). Раньше такая строка
# лежала совсем без ссылки на трек, и выгрузить по ней что-либо было нельзя:
# «деньги пришли, а на что — неизвестно» жило только числом в списке отчётов.
# Теперь у них общий адрес, и в конце квартала по нему видно всё разом.
#
# ЭТО НАСТОЯЩАЯ СТРОКА В `tracks`, а не признак у строки отчёта: так она
# ведёт себя как любой другой трек — по ней работает и выгрузка, и будущий
# расчёт, и ничего не надо учить исключению.
OUTSIDE_SKU = "0000001"
OUTSIDE_TITLE = "Вне каталога"


def outside_track_id(db: Session):
    """
    Трек-приёмник «вне каталога»; заводится при первой надобности.

    Заводим сами, а не миграцией: позиция служебная, и на стенде, где отчёты
    ещё не грузили, ей взяться неоткуда. Прав (`track_rights`) у неё НЕТ и
    быть не должно — эти деньги пока ничьи, и придумывать им владельца
    значило бы отдать их не тому.
    """
    found = db.scalar(select(Track.id).where(Track.sku == OUTSIDE_SKU))
    if found is not None:
        return found
    track = Track(id=uuid.uuid4(), sku=OUTSIDE_SKU, title=OUTSIDE_TITLE)
    db.add(track)
    db.flush()
    return track.id


def _code_candidates(value: str) -> list:
    """
    Что из ячейки «артикула» может оказаться ISRC или UPC.

    У части площадок своего кода у нас нет, а есть ISRC — и лежит он в одной
    ячейке вместе с UPC: «3617380567893 / DG-A0P-23-16666». Поэтому режем по
    косой черте и с каждого куска снимаем знаки: в каталоге ISRC записан
    сплошняком («DGA0P2316666»).

    Короткие куски отбрасываем: «1», «н/д» и им подобное кодом быть не может,
    а совпасть случайно — вполне.
    """
    parts = [value] if "/" not in value else value.split("/")
    out = []
    for part in parts:
        code = re.sub(r"[^0-9A-Za-z]", "", part).upper()
        if len(code) >= 8 and code not in out:
            out.append(code)
    return out


def _tracks_by_code(db: Session, codes: list) -> dict:
    """
    Код (ISRC/UPC) → (id трека, наш артикул). НЕОДНОЗНАЧНЫЕ НЕ ОТДАЁМ.

    Один ISRC в каталоге встречается у нескольких позиций — у DGA062047234 их
    семнадцать (одна запись в разных альбомах). Выбрать из них наугад значит
    отправить деньги не туда, поэтому такой код просто не считается найденным:
    строка останется неразнесённой, и артикул ей впишет человек.
    """
    found: dict = {}
    codes = [c for c in codes if c]
    for start in range(0, len(codes), SKU_BATCH):
        for code, track_id, sku in db.execute(
            select(Track.code, Track.id, Track.sku).where(
                Track.code.in_(codes[start:start + SKU_BATCH])
            )
        ):
            key = (code or "").upper()
            found[key] = None if key in found else (track_id, sku)
    return {k: v for k, v in found.items() if v is not None}


def _resolve_tracks(db: Session, rows: list, partner_id=None) -> dict:
    """
    Привязать строки отчёта к каталогу: сначала по артикулу, а СТРОКИ БЕЗ
    АРТИКУЛА — по названию и исполнителю (просьба владельца 18.09.2026).

    Зачем второй способ: у площадки код объекта проставлен не всегда. В отчёте
    МТС таких строк шесть, и все шесть на самом деле есть в каталоге — просто
    исполнитель записан иначе («ПОШЛАЯ МОЛЛИ» против «Пошлая Молли», «Slim &
    Константа» против «Slim, Константа»).

    ПОРЯДОК: артикул из файла → ЗАПОМНЕННОЕ СОПОСТАВЛЕНИЕ этой площадки
    (`partner_track_aliases`: человек уже вписывал артикул этому треку) →
    подбор по названию. Решение человека сильнее догадки сервиса, поэтому оно
    и выше подбора.

    ПОДБИРАЕМ ТОЛЬКО ПРИ СИЛЬНОМ СОВПАДЕНИИ: название сходится целиком (с
    точностью до регистра и знаков препинания), исполнитель — по словам, с
    поправкой на инициалы и разделители, и подошёл РОВНО ОДИН трек. На
    названии «Азимут» в каталоге пять разных треков разных артистов —
    подставить любой из них наугад значит отправить чужие деньги.

    Кандидатов ищем по самому длинному слову названия: искать по названию
    целиком нельзя (в отчёте «Тмстс!», в каталоге «Тмстс»), а слово сужает
    список до десятков, дальше решает строгое сравнение.
    """
    by_sku = _tracks_by_sku(db, {r.sku for r in rows if r.sku})

    resolved: dict = {}
    for row in rows:
        if row.sku and row.sku in by_sku:
            row.matched_by = "sku"
            resolved[row.row_num] = by_sku[row.sku]

    # ЗАПОМНЕННЫЕ СОПОСТАВЛЕНИЯ — раньше подбора по названию и даже поверх
    # артикула, которого нет в каталоге: человек уже решал эту задачу для этой
    # площадки, и его решение сильнее любой догадки сервиса.
    aliases = _aliases_for(db, partner_id, rows) if partner_id is not None else {}
    if aliases:
        unresolved = [r for r in rows if r.row_num not in resolved and r.title]
        wanted = {
            aliases[key]
            for key in (_alias_key(r.title, r.artist) for r in unresolved)
            if key in aliases
        }
        by_alias_sku = _tracks_by_sku(db, wanted)
        for row in unresolved:
            sku = aliases.get(_alias_key(row.title, row.artist))
            track_id = by_alias_sku.get(sku) if sku else None
            if track_id is not None:
                row.sku = sku
                row.matched_by = "alias"
                resolved[row.row_num] = track_id

    # ПО КОДУ ПЛОЩАДКИ (ISRC/UPC). Отчёт «101 и К» устроен именно так: нашего
    # артикула в нём нет вовсе, а есть «UPC / ISRC», и по ISRC трек находится
    # точно. Ниже запомненных сопоставлений: там решение человека, а это
    # опознание по коду.
    unresolved = [r for r in rows if r.row_num not in resolved and (r.code or r.sku)]
    if unresolved:
        candidates: dict = {}
        for row in unresolved:
            # Сперва колонка кода площадки, если правило её задало; иначе —
            # то, что стояло в «Артикуле»: у площадки там может лежать её
            # собственный код, который нашим артикулом не оказался.
            for code in _code_candidates(row.code or row.sku):
                candidates.setdefault(code, []).append(row)
        by_code = _tracks_by_code(db, list(candidates))
        for code, waiting in candidates.items():
            hit = by_code.get(code)
            if hit is None:
                continue
            for row in waiting:
                if row.row_num in resolved:
                    continue
                # Артикул ПОДМЕНЯЕМ НА НАШ: строка уезжает в базу, и хранить в
                # ней чужой код значило бы потом искать трек ещё раз.
                row.sku, row.matched_by = hit[1], "code"
                resolved[row.row_num] = hit[0]

    # Строки без артикула — по названию. Одинаковые пары «название +
    # исполнитель» ищем один раз: в отчёте они повторяются по нескольку строк.
    pending = [r for r in rows if r.row_num not in resolved and not r.sku and r.title]
    cache: dict = {}
    for row in pending:
        key = (row.title.lower(), (row.artist or "").lower())
        if key not in cache:
            word = search_word(row.title)
            candidates = []
            if word:
                pattern = "%" + word.replace("%", "").replace("_", "") + "%"
                candidates = db.execute(
                    select(Track.id, Track.sku, Track.title, Track.artist)
                    .where(Track.title.ilike(pattern))
                    .limit(200)
                ).all()
            cache[key] = pick_track(row.title, row.artist, candidates)
        track = cache[key]
        if track is not None:
            row.sku = track.sku
            row.matched_by = "name"
            resolved[row.row_num] = track.id
    return resolved


def _period_from_form(period_from: str, period_to: str) -> tuple:
    """Пара дат периода из формы — с теми же проверками при загрузке и правке."""
    start = _date(period_from, "Начало периода")
    end = _date(period_to, "Конец периода")
    if end < start:
        raise HTTPException(400, "Конец периода раньше начала")
    if (end - start).days > 400:
        raise HTTPException(400, "Период длиннее года — похоже, ошибка в датах")
    return start, end


def _attrs_from_rows(db: Session, report_id) -> dict:
    """
    Какие параметры отчёта взяты из колонки файла: {имя: True/False}.

    Признака в правиле мы не храним: правило живёт у партнёра и с тех пор
    могло смениться, а сами строки — свидетельство того, как отчёт разобрали
    ТОГДА. COUNT по колонке считает только непустые значения — ровно то, что
    нужно, и работает в любой базе (bool_or есть только в PostgreSQL).
    """
    counts = db.execute(
        select(*[func.count(getattr(PartnerReportRow, name)) for name in REPORT_ATTRS])
        .where(PartnerReportRow.report_id == report_id)
    ).one()
    return {name: bool(n) for name, n in zip(REPORT_ATTRS, counts)}


def _per_row_attrs(db: Session, reports: list) -> dict:
    """
    {id отчёта: [параметры из колонки файла]} для списка отчётов.

    Спрашиваем только про параметры, у которых ПУСТОЙ снимок (только они и
    бывают построчными), и через EXISTS: у Believe в отчёте полмиллиона строк,
    и считать их все, как `_attrs_from_rows`, ради «есть хоть одно значение»
    незачем — первая же строка отвечает.
    """
    out: dict = {}
    for report in reports:
        empty = [name for name in REPORT_ATTRS if not getattr(report, name)]
        if not empty:
            continue
        R = PartnerReportRow
        flags = db.execute(select(*[
            select(R.row_num).where(R.report_id == report.id, getattr(R, name).isnot(None))
            .limit(1).exists()
            for name in empty
        ])).one()
        names = [name for name, flag in zip(empty, flags) if flag]
        if names:
            out[str(report.id)] = names
    return out


def _attrs_from_form(values: dict) -> dict:
    """
    Параметры отчёта из формы: лишние пробелы прочь, пусто — это None.

    «Не прислали» и «прислали пусто» здесь ОДНО И ТО ЖЕ: у отчёта параметр
    либо задан, либо нет, и хранить пустую строку значило бы завести второе
    «не заполнено», неотличимое от первого на глаз.
    """
    out = {}
    for name in REPORT_ATTRS:
        text_value = " ".join(str(values.get(name) or "").split())
        if len(text_value) > MAX_ATTR_LEN:
            raise HTTPException(400, f"{ATTR_LABELS[name]}: слишком длинное значение")
        out[name] = text_value or None
    return out


def _manual_skus(raw: str) -> dict:
    """
    Артикулы, вписанные человеком в предпросмотре: {номер строки: артикул}.

    Площадка код проставляет не всегда, а подбор по названию берёт только
    однозначное совпадение — «Азимут» у нас лежит пятью разными треками. То,
    что сервис по-честному отказался угадать, человек вправе указать сам,
    глядя на название и исполнителя.
    """
    if not str(raw or "").strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "manual_skus должен быть корректным JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "manual_skus должен быть объектом")
    out = {}
    for key, value in parsed.items():
        text = str(value or "").strip()
        if not text:
            continue
        try:
            out[int(key)] = text
        except (TypeError, ValueError):
            raise HTTPException(400, f"manual_skus: «{key}» — это не номер строки")
    return out


def _apply_manual(rows: list, manual: dict) -> None:
    """Вписанные руками артикулы — в строки, до привязки к каталогу."""
    for row in rows:
        if row.row_num in manual:
            row.sku = manual[row.row_num]


def _partner_for(db: Session, partner_id: str, content: bytes, filename: str) -> Partner:
    """
    Партнёр запроса — выбранный человеком или узнанный по самому файлу.

    Второе нужно, чтобы отчёт можно было просто бросить в окно: если колонки
    совпали с готовым правилом площадки, мы уже знаем, чей это файл, и
    спрашивать об этом — лишний шаг ради того, что и так известно.

    Имя площадки из правила ищем ТОЧНОЕ: в справочнике рядом живут «МТС»,
    «МТС Авторские» и «МТС Беларусь».
    """
    if str(partner_id or "").strip():
        try:
            chosen = db.get(Partner, uuid.UUID(str(partner_id)))
        except ValueError:
            raise HTTPException(400, "partner_id: это не идентификатор")
        if chosen is None:
            raise HTTPException(404, "Партнёр не найден")
        return chosen

    columns, _ = read_columns(content, filename)
    builtin = match_builtin(columns)
    names = [n.casefold() for n in (builtin or {}).get("partner_names", ())]
    if names:
        rows = db.execute(select(Partner)).scalars().all()
        for row in rows:
            if " ".join((row.name or "").split()).casefold() in names:
                return row
        raise HTTPException(
            400,
            f"Похоже на отчёт «{builtin['name']}», но такой площадки нет "
            "в справочнике партнёров — выберите её сами",
        )
    raise HTTPException(400, "Не удалось определить площадку по файлу — выберите партнёра")


def _preview_row(row, resolved: dict) -> dict:
    """Строка для предпросмотра."""
    return {
        "row": row.row_num,
        "sku": row.sku,
        "title": row.title,
        "artist": row.artist,
        "matched_by": row.matched_by,
        "matched": row.row_num in resolved,
        "quantity": _money(row.quantity),
        "amount_author": _money(row.amount_author),
        "amount_related": _money(row.amount_related),
        # Параметры строки — только те, что правило взяло из колонок файла.
        # У площадок с общими параметрами тут пусто, и таблица предпросмотра
        # этих столбцов не показывает вовсе.
        **{name: getattr(row, name) for name in REPORT_ATTRS},
        "problems": row.problems,
    }


def _date(value: str, label: str) -> date:
    """ISO-дата из формы. Календарь на фронте шлёт «2026-07-01»."""
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise HTTPException(400, f"{label}: «{value}» — это не дата")


def _money(value) -> str | None:
    """Деньги наружу — строкой, как и в остальном ML Finance (float портит 1234.10)."""
    return None if value is None else f"{Decimal(value):.2f}"


def _rule_out(rule: PartnerReportRule | None) -> dict | None:
    if rule is None:
        return None
    return {
        "partner_id": str(rule.partner_id),
        "sample_file": rule.sample_file,
        "sheet": rule.sheet,
        "mapping": rule.mapping or {},
        "vat_rate": _money(rule.vat_rate),
        **{name: getattr(rule, name) for name in REPORT_ATTRS},
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _rate_pending(report: PartnerReport) -> bool:
    """Отчёт в валюте, курс которому ещё не задан: суммы лежат в валюте."""
    return bool(report.currency and report.currency != "RUB" and report.currency_rate is None)


def _apply_rate(db: Session, report: PartnerReport, rate) -> None:
    """
    Поставить отчёту курс к рублю и ПЕРЕСЧИТАТЬ его суммы в базе.

    Строки хранят суммы уже в рублях (или в валюте, пока курса нет), поэтому
    пересчёт — это умножение на отношение нового множителя к прежнему. Итоги
    берутся заново СУММОЙ СТРОК, а не масштабированием округлённых итогов:
    иначе на курсе 83 округление до копеек уводило бы итог на рубли.

    `rate` — текст, как его вписали («83,381152» или «0,012»), либо None:
    вернуть отчёт к суммам в валюте.
    """
    text = str(rate).strip().replace(" ", "").replace(",", ".") if rate not in (None, "") else ""
    try:
        new = currency_factor(text or None)
    except (ValueError, ArithmeticError):
        raise HTTPException(400, f"Курс «{rate}» — это не число больше нуля")
    old = currency_factor(report.currency_rate) if report.currency_rate is not None else Decimal(1)
    ratio = new / old
    if ratio != 1:
        db.execute(
            update(PartnerReportRow)
            .where(PartnerReportRow.report_id == report.id)
            .values(
                amount_author=func.round(PartnerReportRow.amount_author * ratio, 8),
                amount_related=func.round(PartnerReportRow.amount_related * ratio, 8),
            )
        )
        sums = db.execute(
            select(
                func.coalesce(func.sum(PartnerReportRow.amount_author), 0),
                func.coalesce(func.sum(PartnerReportRow.amount_related), 0),
            ).where(PartnerReportRow.report_id == report.id)
        ).one()
        report.total_author = rubles(Decimal(str(sums[0])))
        report.total_related = rubles(Decimal(str(sums[1])))
        # «Вне каталога» — те же строки, что и при загрузке: без трека или на
        # приёмнике. Считаем заново, а не масштабируем округлённое.
        outside = db.scalar(select(Track.id).where(Track.sku == OUTSIDE_SKU))
        missing = PartnerReportRow.track_id.is_(None)
        if outside is not None:
            missing = or_(missing, PartnerReportRow.track_id == outside)
        report.unmatched_amount = rubles(Decimal(str(db.scalar(
            select(
                func.coalesce(
                    func.sum(PartnerReportRow.amount_author + PartnerReportRow.amount_related), 0
                )
            ).where(PartnerReportRow.report_id == report.id, missing)
        ))))
    report.currency_rate = Decimal(text) if text else None


def _sync_payment_actual(db: Session, payment: PartnerPayment | None) -> None:
    """
    ФАКТИЧЕСКИЙ ЗАВОД ПЛАТЕЖА = сумма отчётов, к нему привязанных.

    Так это и работает у владельца: платёж пришёл, к нему подшивают отчёты
    площадки, и «сколько по нему реально завелось» — это их итог. Считаем, а
    не просим ввести: числа уже есть в базе, и переписывать их руками значит
    однажды ошибиться в третьем знаке.

    Одним платежом закрывают несколько отчётов, поэтому именно СУММА, а не
    итог последнего привязанного.

    ЗАОДНО ПРОСТАВЛЯЕТСЯ «ЗАВЕДЕНО» (просьба владельца 24.09.2026). Привязка
    отчёта и ЕСТЬ заведение: после неё в строке стоит, сколько по платежу
    завелось и из чего это сложилось. Отвязали последний — отметка снимается
    вместе с суммой: обе отвечают на один вопрос и расходиться не должны.
    """
    if payment is None:
        return
    rows = db.execute(
        select(
            PartnerReport.total_author, PartnerReport.total_related,
            PartnerReport.currency, PartnerReport.currency_rate,
        ).where(PartnerReport.payment_id == payment.id)
    ).all()
    # Отчёт в валюте БЕЗ КУРСА в завод не входит: его суммы ещё не рубли.
    rows = [
        (author, related) for author, related, currency, rate in rows
        if not (currency and currency != "RUB" and rate is None)
    ]
    if not rows:
        # Отвязали последний отчёт — поля очищаем, а не оставляем прежние:
        # иначе в таблице висели бы сумма и отметка, которым больше нечем
        # объясниться.
        payment.actual_amount = None
        payment.transfer_status = None
        return
    payment.actual_amount = sum(
        ((author or Decimal(0)) + (related or Decimal(0)) for author, related in rows),
        Decimal(0),
    )
    # «Синхра» — не «ещё не заведено», а пометка о характере сделки, и
    # затирать её привязкой нельзя: человек поставил её руками, зная, что это
    # за платёж.
    if payment.transfer_status != "синхра":
        payment.transfer_status = "да"


def _payment_label(occurred_on, partner_name: str | None, number: int | None) -> str | None:
    """
    Как поступление выглядит в списке отчётов: «№3 · МТС · 3 кв. 26».

    НЕ ДАТА (просьба владельца 23.09.2026). Дата платежа ничего не говорит:
    отчётов за месяц несколько, платежи идут вперемешку, и «01.07.2026»
    повторяется у половины строк. Номер же — то, чем человек называет строку
    вслух, глядя в таблицу поступлений, а площадка и квартал позволяют узнать
    её, не открывая соседнюю вкладку.

    Квартал КОРОТКО («3 кв. 26»): столбец узкий, а год в отчётах и так один.
    """
    if occurred_on is None:
        return None
    parts = []
    if number:
        parts.append(f"№{number}")
    if partner_name:
        parts.append(partner_name)
    quarter = (occurred_on.month - 1) // 3 + 1
    parts.append(f"{quarter} кв. {occurred_on.year % 100:02d}")
    return " · ".join(parts)


def _report_out(report: PartnerReport, partner_name: str, payment_date=None,
                payment_label: str | None = None) -> dict:
    return {
        "id": str(report.id),
        "partner_id": str(report.partner_id),
        "partner": partner_name,
        # «BELEIVE DIGITAL RU»: у Believe три отчёта за месяц, и различить их
        # можно только припиской (см. REPORT_REGIONS). Экран показывает ЭТО.
        "region": report_region(partner_name, report.currency),
        "partner_label": " ".join(
            x for x in (partner_name, report_region(partner_name, report.currency)) if x
        ),
        "period": {
            "from": report.period_from.isoformat(),
            "to": report.period_to.isoformat(),
        },
        "period_label": period_label(report.period_from, report.period_to),
        "file_name": report.file_name,
        "sheet": report.sheet,
        "rows_count": report.rows_count,
        "unmatched_count": report.unmatched_count,
        # СУММА, а не только число строк: десять строк по рублю и одна на сто
        # тысяч выглядят одинаково, если считать строки.
        "unmatched_amount": _money(report.unmatched_amount),
        "problem_count": report.problem_count,
        "total_quantity": _money(report.total_quantity),
        "total_author": _money(report.total_author),
        "total_related": _money(report.total_related),
        "total": _money((report.total_author or 0) + (report.total_related or 0)),
        "vat_rate": _money(report.vat_rate),
        "currency": report.currency,
        # Курс строкой как есть (0,012216938 в копейки не округлишь).
        "currency_rate": (
            format(report.currency_rate.normalize(), "f") if report.currency_rate else None
        ),
        "currency_total": _money(report.currency_total),
        # Валютный отчёт без курса: суммы ещё в валюте, а не в рублях.
        "rate_pending": _rate_pending(report),
        "payment_id": str(report.payment_id) if report.payment_id else None,
        # Дата привязанного поступления: в списке отчётов её показывают
        # столбцом, и ходить за ней вторым запросом ради одной ячейки незачем.
        "payment_date": payment_date.isoformat() if payment_date else None,
        # Подпись для столбца «Поступление»: «№3 · МТС · 3 кв. 26».
        "payment_label": payment_label,
        **{name: getattr(report, name) for name in REPORT_ATTRS},
        "uploaded_at": report.uploaded_at.isoformat() if report.uploaded_at else None,
    }


@partner_reports_router.get("")
def list_reports(
    partner_id: uuid.UUID | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    db: Session = Depends(get_session),
) -> dict:
    """
    Загруженные отчёты, свежие сверху.

    Фильтр по периоду — ПЕРЕСЕЧЕНИЕ, а не точное совпадение: у площадок
    периоды разные (месяц, квартал), и «покажи всё за третий квартал» должно
    находить и июльский отчёт МТС.
    """
    query = (
        select(PartnerReport, Partner.name, PartnerPayment.occurred_on,
               PartnerPayment.id, PartnerPayment.partner_id)
        .join(Partner, Partner.id == PartnerReport.partner_id)
        .join(PartnerPayment, PartnerPayment.id == PartnerReport.payment_id, isouter=True)
    )
    if partner_id is not None:
        query = query.where(PartnerReport.partner_id == partner_id)
    if period_from:
        query = query.where(PartnerReport.period_to >= _date(period_from, "period_from"))
    if period_to:
        query = query.where(PartnerReport.period_from <= _date(period_to, "period_to"))

    rows = db.execute(query.order_by(PartnerReport.uploaded_at.desc()).limit(200)).all()
    # Номер поступления и площадка платежа — для подписи в столбце
    # «Поступление». Площадка у платежа СВОЯ: обычно она совпадает с площадкой
    # отчёта (привязка это проверяет), но у строки её могут и не проставить.
    numbers = payment_numbers(db)
    partner_names = {
        pid: name
        for pid, name in db.execute(select(Partner.id, Partner.name))
    }
    reports = [
        _report_out(
            r, name, paid_on,
            _payment_label(paid_on, partner_names.get(pay_partner) or name,
                           numbers.get(pay_id)),
        )
        for r, name, paid_on, pay_id, pay_partner in rows
    ]
    # Какие параметры взяты из колонки файла — у таких в шапке пусто, и
    # список пишет «отчёт» вместо прочерка (просьба владельца 25.09.2026:
    # прочерк у Believe читался как пустая колонка).
    per_row = _per_row_attrs(db, [r for r, *_ in rows])
    for out in reports:
        out["per_row_attributes"] = per_row.get(out["id"], [])
    return {
        "reports": reports,
        # Итог по показанному — чтобы сверять квартал целиком, не складывая
        # строки глазами.
        "totals": {
            "author": f"{sum(Decimal(r['total_author']) for r in reports):.2f}" if reports else "0.00",
            "related": f"{sum(Decimal(r['total_related']) for r in reports):.2f}" if reports else "0.00",
        },
    }


@partner_reports_router.get("/rules/{partner_id}")
def get_rule(partner_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """Правило разбора партнёра — или null, если его ещё не настраивали."""
    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner_id)
    )
    return {"rule": _rule_out(rule), "fields": [
        {"name": f, "label": FIELD_LABELS[f]} for f in FIELDS
    ]}


def _clean_fields(parsed: dict) -> dict:
    """
    Поля правила из присланного JSON: только известные, только «колонка либо
    формула». Общая и для основной таблицы, и для дополнительных (`tables`).
    """
    if not isinstance(parsed, dict):
        raise HTTPException(400, "правило: ожидается объект")
    clean: dict = {}
    for key, spec in parsed.items():
        if key == "tables":
            continue                       # разбирается отдельно, см. вызов
        if key not in MAPPABLE_FIELDS:
            raise HTTPException(400, f"Неизвестное поле правила: «{key}»")
        if not isinstance(spec, dict):
            raise HTTPException(400, f"Поле «{key}»: ожидается объект")
        column = str(spec.get("column") or "").strip()
        formula = str(spec.get("formula") or "").strip()
        # «ЗАПОЛНЯЕТСЯ ПРАВИЛОМ» — осознанный выбор, а не пустое поле: артикул
        # при нём ищут по коду площадки, по названию или вписывают руками.
        # Хранится явным признаком, чтобы «пусто» осталось значить «ниоткуда
        # не берётся», то есть ошибку настройки.
        if key == "sku" and spec.get("auto") and not column and not formula:
            clean[key] = {"auto": True}
            continue
        # У ПАРАМЕТРОВ ФОРМУЛЫ НЕ БЫВАЕТ: формулы считают числа, а тип
        # контента и территория — слова. Либо колонка файла, либо одно
        # значение на весь отчёт (оно живёт не здесь, а рядом с правилом).
        if key in ATTR_FIELDS and formula:
            raise HTTPException(
                400, f"Поле «{FIELD_LABELS[key]}»: формулой не задаётся — только колонкой"
            )
        if column and formula:
            raise HTTPException(
                400, f"Поле «{FIELD_LABELS[key]}»: либо колонка, либо формула, не оба"
            )
        if column:
            clean[key] = {"column": column}
        elif formula:
            clean[key] = {"formula": formula}
    return clean


@partner_reports_router.put(
    "/rules/{partner_id}",
    dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))],
)
def save_rule(
    partner_id: uuid.UUID,
    mapping: str = Form(...),
    vat_rate: str = Form(""),
    sheet: str = Form(""),
    sample_file: str = Form(""),
    content_type: str = Form(""),
    usage_type: str = Form(""),
    usage_kind: str = Form(""),
    territory: str = Form(""),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Сохранить правило разбора для партнёра.

    `mapping` — JSON вида {"sku": {"column": "Артикул"}, "amount_related":
    {"formula": "[Сумма] - [Сумма авт.]"}}. Проверяем здесь только форму
    (известные поля, строковые значения): то, что колонки существуют, покажет
    предпросмотр на настоящем файле, и делать это дважды незачем.
    """
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    try:
        parsed = json.loads(mapping or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "mapping должен быть корректным JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "mapping должен быть объектом")

    clean = _clean_fields(parsed)
    # ВТОРАЯ ТАБЛИЦА ТОГО ЖЕ ЛИСТА — СПИСКОМ ВНУТРИ ПРАВИЛА (`tables`, у
    # Мегафона это отчёт по пакетам под основным). Не отдельной колонкой в
    # базе: правило целиком лежит одним JSON, и так вторая таблица ездит
    # вместе с ним и в сохранённое правило партнёра, и обратно в форму.
    # Настраивают её только в коде (`BUILTIN_RULES`): у формата с двумя
    # шапками руками не разберёшься, а подставить форму не подо что.
    extra = parsed.get("tables")
    if extra is not None:
        if not isinstance(extra, list):
            raise HTTPException(400, "tables: ожидается список правил")
        clean["tables"] = [_clean_fields(t) for t in extra]

    if not sku_configured(clean):
        raise HTTPException(
            400,
            "«%s» обязателен: выберите колонку или «заполняется правилом»"
            % FIELD_LABELS["sku"],
        )

    rate = None
    if str(vat_rate).strip():
        try:
            rate = Decimal(str(vat_rate).replace(",", ".").strip())
        except Exception:
            raise HTTPException(400, f"Ставка НДС: «{vat_rate}» — это не число")
        if rate < 0 or rate > 100:
            raise HTTPException(400, "Ставка НДС должна быть от 0 до 100")

    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner_id)
    )
    if rule is None:
        rule = PartnerReportRule(id=uuid.uuid4(), partner_id=partner_id)
        db.add(rule)
    rule.mapping = clean
    rule.vat_rate = rate
    attrs = _attrs_from_form({
        "content_type": content_type,
        "usage_type": usage_type,
        "usage_kind": usage_kind,
        "territory": territory,
    })
    for name, value in attrs.items():
        setattr(rule, name, value)
    rule.sheet = sheet.strip() or None
    rule.sample_file = sample_file.strip() or rule.sample_file
    rule.updated_at = datetime.now(timezone.utc)

    db.commit()
    log_action(
        db, current_user, "partner_report.rule.save", entity_type="partner",
        entity_id=partner_id,
        meta={"partner": partner.name, "fields": sorted(clean), "vat_rate": str(rate or "")},
    )
    db.commit()
    return {"rule": _rule_out(rule)}


def _read_upload(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm", ".csv", ".txt", ".tsv")):
        raise HTTPException(400, "Ожидается файл .xlsx или текстовый (.csv/.tsv)")
    return file.file.read()


def _fits(mapping: dict, columns: list) -> bool:
    """Все колонки, которые называет правило, есть в шапке файла."""
    keys = {normalize_header(c) for c in columns if c}
    return all(normalize_header(c) in keys for c in mapping_columns(mapping))


def _pick_rule(rule: PartnerReportRule | None, mapping_json: str, columns: list) -> dict:
    """
    Чьё правило применяем — и откуда оно взялось.

    Порядок старшинства: присланное формой (человек как раз его настраивает) →
    сохранённое у партнёра → ГОТОВОЕ ПРАВИЛО ПЛОЩАДКИ, узнанное по колонкам
    файла (`BUILTIN_RULES`) → догадка по названиям колонок.

    Откуда правило взялось, уходит на экран (`source`): человек должен видеть,
    что к его файлу применилось готовое правило МТС, а не набор угаданных
    колонок, — иначе «оно вроде само всё нашло» и проверка формулы
    откладывается до первого неверного платежа.
    """
    if mapping_json.strip():
        try:
            parsed = json.loads(mapping_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "mapping должен быть корректным JSON")
        if parsed:
            return {"mapping": parsed, "source": "form", "name": None, "vat_rate": None}
    # СОХРАНЁННОЕ ПРАВИЛО — ТОЛЬКО ЕСЛИ ОНО ПОДХОДИТ К ФАЙЛУ (баг, найден
    # владельцем 24.09.2026). У Believe файлы с разной шапкой: RU подписан
    # по-английски, KZ и AE — по-русски. После загрузки AE с «запомнить
    # правило» у площадки легло русское правило, и английский файл RU
    # перестал читаться вовсе: «нет колонок», период пустой.
    #
    # Правило партнёра не подходит к файлу → берём встроенное, ЕСЛИ файл им
    # узнан. Не узнан ничем — остаётся правило партнёра, и человек получает
    # внятный отказ «в файле нет колонок: …»: площадка, скорее всего,
    # переименовала колонку, и молча переходить к догадке по названиям
    # значило бы разобрать деньги не теми колонками.
    builtin = match_builtin(columns)
    if rule is not None and rule.mapping and (_fits(rule.mapping, columns) or builtin is None):
        return {"mapping": rule.mapping, "source": "partner", "name": None, "vat_rate": None}
    if builtin is not None:
        return {
            "mapping": builtin["mapping"],
            "source": "builtin",
            "name": builtin["name"],
            "vat_rate": builtin.get("vat_rate"),
        }
    return {"mapping": suggest_mapping(columns), "source": "guess", "name": None, "vat_rate": None}


@partner_reports_router.post(
    "/{report_id}/payment",
    dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))],
)
def link_payment(
    report_id: uuid.UUID,
    payment_id: str = Form(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Привязать отчёт к строке поступления.

    ПЛОЩАДКА СВЕРЯЕТСЯ: отчёт МТС нельзя подшить к платежу от другой
    площадки — это деньги не на тот счёт, и поймать такое потом можно только
    вручную. Если у строки поступления площадка ещё не проставлена (её
    заводят по выписке, а чей платёж, выясняют потом) — проставим её из
    отчёта: это и есть ответ на тот самый вопрос.

    После привязки пересчитывается «сумма фактического завода» платежа — она
    равна сумме привязанных к нему отчётов (см. `_sync_payment_actual`).
    """
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    try:
        payment = db.get(PartnerPayment, uuid.UUID(str(payment_id)))
    except ValueError:
        raise HTTPException(400, "payment_id: это не идентификатор")
    if payment is None:
        raise HTTPException(404, "Поступление не найдено")

    if payment.partner_id is None and payment.partner_name:
        # У строки вписана площадка, которой нет в справочнике (мелкий партнёр
        # по синхронизации). Сверяем по имени: молча подменить её ссылкой на
        # площадку отчёта нельзя — это стёрло бы то, что человек написал, а
        # заодно скрыло бы ошибку, если платёж и правда чужой.
        report_partner = db.get(Partner, report.partner_id)
        written = " ".join(payment.partner_name.split()).casefold()
        expected = " ".join((report_partner.name if report_partner else "").split()).casefold()
        if written != expected:
            raise HTTPException(
                409,
                "Площадки не совпадают: отчёт от «%s», а в поступлении вписано «%s»."
                % (report_partner.name if report_partner else "—", payment.partner_name),
            )
        # Имя совпало — значит, это та же площадка, и теперь у неё есть ссылка.
        payment.partner_id = report.partner_id
        payment.partner_name = None
    elif payment.partner_id is None:
        payment.partner_id = report.partner_id
    elif payment.partner_id != report.partner_id:
        report_partner = db.get(Partner, report.partner_id)
        payment_partner = db.get(Partner, payment.partner_id)
        raise HTTPException(
            409,
            "Площадки не совпадают: отчёт от «%s», а поступление от «%s»."
            % (
                report_partner.name if report_partner else "—",
                payment_partner.name if payment_partner else "—",
            ),
        )

    # СВЕРКА В ВАЛЮТЕ И КУРС САМ (просьба владельца 24.09.2026). Итог отчёта в
    # валюте сверяется с «суммой в валюте» поступления — это независимое число
    # от площадки. Сошлось с точностью до цента — курс ставится так, чтобы
    # фактический завод совпал с заводом: сумма завода / итог в валюте. Не
    # сошлось — привязываем, но курс не трогаем: подгонять его под платёж
    # значило бы спрятать недостачу. Курс потом правится руками в окне отчёта.
    currency_check = None
    if report.currency and report.currency != "RUB" and report.currency_total is not None:
        paid, paid_code = parse_currency_note(payment.currency_amount)
        own = Decimal(report.currency_total).quantize(Decimal("0.01"))
        matches = (
            paid is not None
            and (paid_code in (None, report.currency))
            and abs(paid - own) <= Decimal("0.01")
        )
        currency_check = {
            "currency": report.currency,
            "report": _money(own),
            "payment": _money(paid) if paid is not None else None,
            "payment_currency": paid_code,
            "matches": bool(matches),
            "rate_set": False,
        }
        if matches and payment.transfer_amount and own:
            auto = (Decimal(payment.transfer_amount) / Decimal(report.currency_total)).quantize(
                Decimal("0.0000000001")
            )
            _apply_rate(db, report, format(auto.normalize(), "f"))
            currency_check["rate_set"] = True
            currency_check["rate"] = format(auto.normalize(), "f")

    previous = db.get(PartnerPayment, report.payment_id) if report.payment_id else None
    report.payment_id = payment.id
    db.flush()
    _sync_payment_actual(db, payment)
    # Прежний платёж тоже пересчитываем: отчёт из него ушёл, и его
    # фактический завод больше не включает эти деньги.
    if previous is not None and previous.id != payment.id:
        _sync_payment_actual(db, previous)
    db.commit()

    partner = db.get(Partner, report.partner_id)
    log_action(
        db, current_user, "partner_report.payment.link", entity_type="partner_report",
        entity_id=report.id,
        meta={
            "partner": partner.name if partner else None,
            "period": period_label(report.period_from, report.period_to),
            "payment": payment.occurred_on.isoformat(),
            "currency_check": currency_check,
        },
    )
    db.commit()
    return {
        "currency_check": currency_check,
        "report": _report_out(
            report, partner.name if partner else "", payment.occurred_on,
            _payment_label(payment.occurred_on, partner.name if partner else None,
                           payment_numbers(db).get(payment.id)),
        ),
        "payment_actual": _money(payment.actual_amount),
    }


@partner_reports_router.delete(
    "/{report_id}/payment",
    dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))],
)
def unlink_payment(
    report_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Отвязать отчёт от поступления и пересчитать его фактический завод."""
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    payment = db.get(PartnerPayment, report.payment_id) if report.payment_id else None
    report.payment_id = None
    # ВАЛЮТНЫЙ ОТЧЁТ ВОЗВРАЩАЕТСЯ В ВАЛЮТУ (просьба владельца 24.09.2026):
    # курс брался из того самого поступления, от которого отвязали, и рубли
    # без него объяснить нечем. Привяжут снова — курс поставится заново.
    if report.currency and report.currency != "RUB" and report.currency_rate is not None:
        _apply_rate(db, report, None)
    db.flush()
    _sync_payment_actual(db, payment)
    db.commit()

    partner = db.get(Partner, report.partner_id)
    log_action(
        db, current_user, "partner_report.payment.unlink", entity_type="partner_report",
        entity_id=report.id,
        meta={
            "partner": partner.name if partner else None,
            "period": period_label(report.period_from, report.period_to),
        },
    )
    db.commit()
    return {"report": _report_out(report, partner.name if partner else "")}


@partner_reports_router.get("/attributes")
def attribute_options(db: Session = Depends(get_session)) -> dict:
    """
    Что уже вводили в параметрах отчёта — для подсказок в полях.

    Справочник СЧИТАЕТСЯ ПО ДАННЫМ, а не задан в коде (то же решение, что у
    каталогов в номенклатуре): какие бывают виды использования, знает
    площадка, и любой зафиксированный список разошёлся бы с первым же новым
    партнёром.
    """
    options: dict = {}
    for name in REPORT_ATTRS:
        values = set()
        for model in (PartnerReport, PartnerReportRule):
            column = getattr(model, name)
            values.update(
                v for v in db.scalars(select(column).where(column.isnot(None))) if v
            )
        options[name] = sorted(values)
    return {"options": options, "labels": ATTR_LABELS}


@partner_reports_router.get("/aliases/{partner_id}")
def list_aliases(partner_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Что мы запомнили для этой площадки: «название — исполнитель → артикул».

    Список нужен не для красоты: сопоставление, сделанное по ошибке, иначе
    повторялось бы в каждом следующем отчёте молча. Увидеть и убрать — вот и
    вся его задача.
    """
    rows = db.scalars(
        select(PartnerTrackAlias)
        .where(PartnerTrackAlias.partner_id == partner_id)
        .order_by(PartnerTrackAlias.created_at.desc())
    ).all()
    skus = {a.sku for a in rows}
    known = {
        sku: (title, artist)
        for sku, title, artist in db.execute(
            select(Track.sku, Track.title, Track.artist).where(Track.sku.in_(skus))
        )
    } if skus else {}
    return {
        "aliases": [
            {
                "id": str(a.id),
                "title": a.title,
                "artist": a.artist,
                "sku": a.sku,
                # Что это за трек СЕЙЧАС: каталог живёт своей жизнью, и
                # сопоставление могло указывать на позицию, которой больше нет.
                "track_title": known.get(a.sku, (None, None))[0],
                "track_artist": known.get(a.sku, (None, None))[1],
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


@partner_reports_router.delete(
    "/aliases/{alias_id}",
    dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))],
)
def delete_alias(
    alias_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Забыть сопоставление: в следующем отчёте строка снова будет без артикула."""
    alias = db.get(PartnerTrackAlias, alias_id)
    if alias is None:
        raise HTTPException(404, "Сопоставление не найдено")
    partner = db.get(Partner, alias.partner_id)
    db.delete(alias)
    db.commit()
    forget_all_parsed()
    log_action(
        db, current_user, "partner_report.alias.delete", entity_type="partner",
        entity_id=alias.partner_id,
        meta={
            "partner": partner.name if partner else None,
            "title": alias.title,
            "artist": alias.artist,
            "sku": alias.sku,
        },
    )
    db.commit()
    return {"deleted": alias.sku}


@partner_reports_router.get("/track")
def find_track_by_sku(sku: str = "", db: Session = Depends(get_session)) -> dict:
    """
    Есть ли такой артикул в каталоге — для строки, в которую артикул вписывают
    руками. Отвечает названием и исполнителем: человек вписывает код из
    соседней системы и должен увидеть, ТОТ ли это трек, а не только «найден».
    """
    code = str(sku or "").strip()
    track = db.scalar(select(Track).where(Track.sku == code)) if code else None
    return {
        "sku": code,
        "found": track is not None,
        "title": track.title if track else None,
        "artist": track.artist if track else None,
    }


def _head_info(
    db: Session, partner_id: str, content: bytes, filename: str,
    mapping: str, vat_rate: str, sheet: str, currency_rate: str = "",
) -> dict:
    """
    Всё, что читается по ВЕРХУ файла: площадка, правило, лист, НДС, период и
    параметры. Общее для быстрого `inspect` и полного `preview`.

    Сюда не входит ни одной строки данных — поэтому это доли секунды даже на
    полумиллионном отчёте (замер на проде 24.09.2026, «Зайцев.нет»: шапка
    0,1 с, разбор строк 21 с, привязка к каталогу 12 с).
    """
    # ПАРТНЁРА МОЖНО НЕ ВЫБИРАТЬ: если файл узнан по колонкам, площадка
    # определяется из самого правила (просьба владельца 18.09.2026 — «я могу
    # перетянуть отчёт МТС, и он должен выбраться сам»). Не узнан — тогда да,
    # выбирать: по чужому формату гадать не о чем.
    partner = _partner_for(db, partner_id, content, filename)

    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner.id)
    )
    sheets = sheet_names(content, filename)
    chosen_sheet = sheet.strip() or (rule.sheet if rule else None)

    # ВЕРХ ФАЙЛА ЧИТАЕМ ОДИН РАЗ и переиспользуем: по нему определяются и
    # колонки, и период из шапки. Раньше предпросмотр читал файл ЦЕЛИКОМ трижды
    # (колонки, разбор, период), и на отчёте в полмиллиона строк каждый проход
    # стоил полторы минуты и гигабайт памяти.
    file_head = read_head(content, filename, chosen_sheet)
    # Колонки читаем ДО применения правила: если правила нет, догадка
    # строится как раз по ним.
    columns, header_row = read_columns(content, filename, chosen_sheet, head=file_head)
    chosen = _pick_rule(rule, mapping, columns)
    active_mapping = chosen["mapping"]
    rate = (
        vat_rate.strip()
        or (str(rule.vat_rate) if rule and rule.vat_rate else "")
        or (str(chosen["vat_rate"]) if chosen["vat_rate"] else "")
    )
    # Заготовка параметров узнаётся ПО ФАЙЛУ, даже если колонки разбирает
    # правило партнёра или настройка из формы (см. ниже, "attributes").
    builtin_attrs = (match_builtin(columns) or {}).get("attributes") or {}

    # ПЕРИОД, НАПИСАННЫЙ В САМОМ ФАЙЛЕ: у МТС это строка над шапкой («за
    # период с 1 июля 2026 по 31 июля 2026»). Период — единственное, что
    # человек вводит руками, и ошибиться в нём легче всего: файл за июнь
    # грузят в июле. Это подсказка — форма подставит, а править можно.
    found_period = find_period(file_head, header_row)
    # У Believe периода в шапке нет — он в колонке «месяц отчёта» каждой строки.
    period_spec = (active_mapping or {}).get("period") or {}
    if found_period is None and period_spec.get("column"):
        found_period = period_from_column(file_head, header_row, period_spec["column"])

    # ВАЛЮТА ВИДНА ПО ПЕРВЫМ СТРОКАМ: она одна на весь отчёт, и форма должна
    # спросить курс сразу, а не после разбора полумиллиона строк.
    currency_spec = (active_mapping or {}).get("currency") or {}
    currencies = sorted({
        " ".join(str(v).split()).upper()
        for v in column_values(file_head, header_row, currency_spec["column"])
    }) if currency_spec.get("column") else []
    currency_rate = (currency_rate or "").strip()
    if currency_rate:
        try:
            currency_factor(currency_rate)
        except Exception:
            raise HTTPException(400, f"Курс «{currency_rate}» — это не число больше нуля")
    return {
        "partner": partner,
        "sheet": chosen_sheet,
        "mapping": active_mapping,
        "rate": rate,
        "currency_rate": currency_rate,
        "currencies": currencies,
        "out": {
            "partner": {"id": str(partner.id), "name": partner.name},
            "file_name": filename,
            "sheets": sheets,
            "sheet": chosen_sheet,
            "columns": columns,
            "header_row": header_row + 1,     # человеку — как в Excel
            "mapping": active_mapping,
            "rule_saved": rule is not None,
            # Откуда взялось правило: готовое правило площадки, сохранённое у
            # партнёра, настроенное сейчас руками или догадка по названиям колонок.
            "rule_source": chosen["source"],
            "rule_name": chosen["name"],
            "vat_rate": rate or None,
            # Валюта сумм и курс к рублю. Отчёт не в рублях без курса НЕ
            # ГРУЗИТСЯ (см. create_report): доллары легли бы рублями.
            "currencies": currencies,
            "needs_rate": any(c != "RUB" for c in currencies),
            "currency_rate": currency_rate or None,
            # Параметры отчёта: что запомнено у партнёра — то и подставим, а чего
            # не запомнено, берём из заготовки готового правила площадки (у МТС
            # это «RBT · <не участвует> · Mobile · RU»).
            #
            # ЗАГОТОВКУ ИЩЕМ ОТДЕЛЬНО от того, чьё правило разобрало колонки: у
            # МТС правило партнёра сохранено (колонки настраивали руками), и
            # раньше вместе с ним выигрывали его пустые параметры — поля
            # оставались пустыми, хотя заготовка есть. Правило — про формат файла,
            # заготовка — про площадку, и мешать их не надо.
            "attributes": {
                name: (getattr(rule, name) if rule else None) or builtin_attrs.get(name)
                for name in REPORT_ATTRS
            },
            "attribute_labels": ATTR_LABELS,
            # Какие из четырёх параметров правило берёт ИЗ КОЛОНКИ файла: у таких
            # значение своё в каждой строке, и поле «одно на весь отчёт» для них
            # не показывается — иначе человек правил бы то, что ни на что не
            # влияет.
            "attributes_from_columns": {
                name: ((active_mapping or {}).get(name) or {}).get("column")
                for name in REPORT_ATTRS
                if ((active_mapping or {}).get(name) or {}).get("column")
            },
            "period": (
                {
                    "from": found_period[0].isoformat(),
                    "to": found_period[1].isoformat(),
                    "label": period_label(*found_period),
                }
                if found_period
                else None
            ),
        },
    }


# ------------------------------------------------ общий разбор строк с памятью
#
# ЗАГРУЗКА НЕ ПОВТОРЯЕТ РАБОТУ ПРЕДПРОСМОТРА (просьба владельца 24.09.2026:
# «хочу нажать „Загрузить“, не дожидаясь предпросмотра»). Разбор строк и
# привязка к каталогу — это всё время обработки (у «Зайцев.нет» 21 + 12 с), и
# раньше они делались дважды: в предпросмотре и ещё раз при загрузке. Теперь
# результат запоминается по КЛЮЧУ ИЗ ВСЕГО, ОТ ЧЕГО ОН ЗАВИСИТ: содержимое
# файла, итоговое правило, ставка НДС, лист, вписанные артикулы, площадка.
# Нажали «Загрузить», пока предпросмотр того же файла ещё считается, — загрузка
# ДОЖДЁТСЯ его расчёта, а не запустит второй.
#
# Прежнее правило «файл при загрузке разбирается заново» от этого не
# нарушается по сути: оно было о том, что между предпросмотром и загрузкой
# человек мог поменять правило. Поменял — ключ другой, и разбор честно
# делается заново. Совпало всё — результат тот же самый, пересчитывать его
# незачем.
#
# ПРИВЯЗКА ЗАВИСИТ И ОТ БАЗЫ, не только от файла: от номенклатуры и
# запомненных артикулов площадки. Поэтому память СБРАСЫВАЕТСЯ ЦЕЛИКОМ, как
# только они меняются (`forget_all_parsed`): после загрузки отчёта (она
# запоминает вписанные артикулы), удаления сопоставления, импорта и правки
# номенклатуры. Найдено прогоном: без сброса повторный предпросмотр того же
# файла не видел только что запомненного артикула. Заливку каталога скриптом
# (`ops/import_tracks.py`, отдельный процесс) отсюда не видно — её покрывает
# срок жизни записи.
#
# Память на процесс (uvicorn у нас один), живёт `PARSED_TTL` и держит не больше
# `PARSED_KEEP` файлов: разобранный Believe — это сотни мегабайт.
PARSED_TTL = 600
PARSED_KEEP = 2
_parsed: dict = {}
_parsed_lock = threading.Lock()
# РАЗБОР — ПО ОДНОМУ ЗА РАЗ (замер на проде 24.09.2026). Отчёт Believe RU на
# 596 тыс. строк занимает в памяти ~650 МБ, а у сервера их свободно ~850, и
# подкачки нет. Два таких разбора одновременно — и система убивает процесс
# api целиком, со всеми, кто в нём работает. Второй разбор ждёт первого;
# ГОТОВЫЕ записи памяти при этом выбрасываются перед началом нового, иначе
# они лежали бы рядом с ним.
_parse_gate = threading.Semaphore(1)


# ПАМЯТЬ ОТДАЁТСЯ СИСТЕМЕ (инцидент 25.09.2026). Утром разобрали Believe RU
# на 596 тыс. строк, а в обед процесс api убило системой за нехватку памяти
# (~1 ГБ) — посреди расчёта ведомостей. Причин было две:
# - протухшая запись разбора выбрасывалась ТОЛЬКО когда начинался следующий
#   разбор: предпросмотр без загрузки держал сотни мегабайт хоть до вечера;
# - освобождённое Python отдаёт своему распределителю, а не системе, и
#   процесс после большого отчёта так и оставался толстым.
# Поэтому раз в минуту протухшее выбрасывается фоновой проверкой, а после
# любого выброса и после `forget_all_parsed` зовётся `malloc_trim` (glibc):
# он возвращает системе свободные куски кучи. Не на glibc — просто ничего не
# делает.
def _release_memory() -> None:
    import ctypes
    import gc

    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _evict_expired() -> bool:
    now = time.monotonic()
    with _parsed_lock:
        stale = [k for k, e in _parsed.items() if "value" in e and now - e["at"] > PARSED_TTL]
        for k in stale:
            _parsed.pop(k, None)
    return bool(stale)


# Выброс в `forget_all_parsed` случается посреди запроса, который ещё держит
# разобранные строки у себя, — тогда отдать системе пока нечего. Флаг просит
# фоновую проверку повторить отдачу, когда запрос уже закончится.
_trim_pending = False


def _sweeper() -> None:
    global _trim_pending
    while True:
        time.sleep(60)
        try:
            if _evict_expired() or _trim_pending:
                _trim_pending = False
                _release_memory()
        except Exception:  # noqa: BLE001 — фоновой проверке падать нельзя
            pass


threading.Thread(target=_sweeper, name="parsed-sweeper", daemon=True).start()


def _parsed_key(content: bytes, filename: str, head: dict, manual: dict) -> str:
    rate = head["rate"]
    try:
        rate = format(Decimal(rate).normalize(), "f") if rate else ""
    except Exception:
        pass
    parts = (
        hashlib.sha256(content).hexdigest(),
        (filename or "").lower().rsplit(".", 1)[-1],
        json.dumps(head["mapping"], sort_keys=True, ensure_ascii=False),
        rate,
        head["currency_rate"] or "",
        head["sheet"] or "",
        json.dumps(sorted(manual.items())),
        str(head["partner"].id),
    )
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _parse_and_resolve(db: Session, content: bytes, filename: str, head: dict, manual: dict):
    """
    Разобрать строки и привязать их к каталогу: (ParseResult, {строка: трек}).

    Результат общий для предпросмотра и загрузки — см. комментарий выше.
    Строки после этого НЕ МЕНЯТЬ: тот же объект может читать соседний запрос.
    """
    key = _parsed_key(content, filename, head, manual)
    now = time.monotonic()
    with _parsed_lock:
        for k in [k for k, e in _parsed.items() if now - e["at"] > PARSED_TTL]:
            _parsed.pop(k, None)
        entry = _parsed.get(key)
        owner = entry is None
        if owner:
            entry = {"event": threading.Event(), "at": now}
            _parsed[key] = entry
            # Лишнее выбрасываем, начиная со старых. Недосчитанные тоже можно:
            # их владелец досчитает и отдаст своим, просто без памяти.
            for k in sorted(_parsed, key=lambda k: _parsed[k]["at"])[:-PARSED_KEEP]:
                _parsed.pop(k, None)
    if owner:
        _parse_gate.acquire()
        with _parsed_lock:
            for k in [k for k, e in _parsed.items() if k != key and "value" in e]:
                _parsed.pop(k, None)
        try:
            result = parse_report(
                content, filename, head["mapping"],
                vat_rate=head["rate"] or None, sheet=head["sheet"],
                currency_rate=head["currency_rate"] or None,
            )
            # Артикулы, вписанные руками в предпросмотре, — до привязки к каталогу.
            _apply_manual(result.rows, manual)
            # Привязка к каталогу: по артикулу, а строки без него — по названию
            # и исполнителю (см. _resolve_tracks).
            resolved = (
                {} if result.problems
                else _resolve_tracks(db, result.rows, head["partner"].id)
            )
            for row in result.rows:
                if row.row_num in manual:
                    row.matched_by = "manual"
            entry["value"] = (result, resolved)
        except BaseException as exc:
            entry["error"] = exc
            with _parsed_lock:
                if _parsed.get(key) is entry:
                    _parsed.pop(key, None)
            raise
        finally:
            _parse_gate.release()
            entry["event"].set()
        return entry["value"]
    # Чужой расчёт того же файла уже идёт — ждём его, а не начинаем свой.
    entry["event"].wait(PARSED_TTL)
    if "value" not in entry:
        raise HTTPException(500, "Разбор файла не удался — попробуйте ещё раз")
    return entry["value"]


def forget_all_parsed() -> None:
    """Номенклатура или запомненные артикулы поменялись — привязка устарела."""
    global _trim_pending
    with _parsed_lock:
        _parsed.clear()
    _trim_pending = True


@partner_reports_router.post(
    "/inspect", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def inspect(
    partner_id: str = Form(""),
    file: UploadFile = File(...),
    mapping: str = Form(""),
    vat_rate: str = Form(""),
    sheet: str = Form(""),
    currency_rate: str = Form(""),
    db: Session = Depends(get_session),
) -> dict:
    """
    БЫСТРЫЙ ВЗГЛЯД НА ФАЙЛ — только шапка (просьба владельца 24.09.2026).

    Площадка, правило, период, параметры и НДС — ровно то, что нужно форме,
    чтобы сразу показать кнопку «Загрузить отчёт». Строк не читает, поэтому
    отвечает за доли секунды даже на полумиллионном отчёте. Строки, итоги и
    «нет в номенклатуре» считает следом `preview`.
    """
    content = _read_upload(file)
    return _head_info(db, partner_id, content, file.filename, mapping, vat_rate, sheet, currency_rate)["out"]


@partner_reports_router.post(
    "/preview", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def preview(
    partner_id: str = Form(""),
    file: UploadFile = File(...),
    mapping: str = Form(""),
    vat_rate: str = Form(""),
    sheet: str = Form(""),
    currency_rate: str = Form(""),
    manual_skus: str = Form(""),
    db: Session = Depends(get_session),
) -> dict:
    """
    Разобрать файл БЕЗ записи: что нашлось в шапке, что получилось из строк,
    что не сошлось.

    Шапку ищем по содержимому, а не по номеру строки: у площадок сверху бывает
    описание на несколько строк, и число этих строк меняется от файла к файлу
    (в Dista его приходилось вбивать руками — «пропустить строк сверху»).
    """
    content = _read_upload(file)
    head = _head_info(db, partner_id, content, file.filename, mapping, vat_rate, sheet, currency_rate)
    manual = _manual_skus(manual_skus)

    # Разбираем ВЕСЬ файл, а не первые сто строк: итоги человек сверяет с
    # платежом площадки, а строки без артикула бывают и на пятисотой строке —
    # показать их иначе нечем.
    result, resolved = _parse_and_resolve(db, content, file.filename, head, manual)

    # Начало файла и строки без трека — ДВА РАЗНЫХ СПИСКА, а не один
    # склеенный: первый показывают всегда, второй — по кнопке. Склеенные, они
    # дописывали в конец таблицы строки из середины файла, и выглядело это так,
    # будто отчёт ими заканчивается.
    first_rows = result.rows[:PREVIEW_ROWS]
    missing = [r for r in result.rows if r.row_num not in resolved][:UNMATCHED_PREVIEW]

    totals = result.totals
    return {
        **head["out"],
        "columns": result.columns,
        "header_row": result.header_row + 1,
        "problems": result.problems,
        # Валюты по ВСЕМ строкам, а не только по верху файла.
        "currencies": sorted(result.currencies) or head["out"]["currencies"],
        "needs_rate": any(c != "RUB" for c in result.currencies)
        or head["out"]["needs_rate"],
        # Предупреждения не мешают загрузке, но должны быть видны до неё:
        # сейчас это «файл потерял буквы» (см. _warn_if_lossy).
        "warnings": result.warnings,
        "preview": [_preview_row(r, resolved) for r in first_rows],
        "unmatched_rows": [_preview_row(r, resolved) for r in missing],
        "preview_limited": totals["rows"] > len(first_rows),
        "totals": {
            "rows": totals["rows"],
            "ok_rows": totals["ok_rows"],
            # Строки без артикула и строки с непонятными суммами показываем
            # ЧИСЛОМ до загрузки: по первым деньги придут «ничьи», а вторые
            # лягут нулями, и узнать об этом человек должен заранее.
            "no_sku": totals["no_sku"],
            # Не нашлось трека — это не то же самое, что «нет артикула»: код
            # в файле может быть, а трека с таким кодом в каталоге нет.
            "unmatched": totals["rows"] - len(resolved),
            "matched_by_name": sum(1 for r in result.rows if r.matched_by == "name"),
            "problem_rows": totals["problem_rows"],
            "quantity": _money(totals["quantity"]),
            "amount_author": _money(totals["amount_author"]),
            "amount_related": _money(totals["amount_related"]),
            "total": _money(totals["amount_author"] + totals["amount_related"]),
        },
    }


ROW_COLUMNS = (
    "id", "report_id", "row_num", "sku", "title", "artist",
    "quantity", "amount_author", "amount_related", "track_id",
    # Параметры пишем ТОЛЬКО если правило взяло их из колонок файла. Пусто —
    # значит, у площадки они общие и лежат в шапке отчёта; дублировать снимок
    # в каждую из полумиллиона строк незачем.
    *REPORT_ATTRS,
)


def _store_rows(db: Session, report_id, rows: list, track_by_row: dict) -> None:
    """
    Записать строки отчёта в базу.

    ЧЕРЕЗ `COPY`, А НЕ ОБЪЕКТАМИ ORM. Замерено на проде (23.09.2026): путь
    через `bulk_save_objects` даёт 4 720 строк в секунду — отчёт Believe на 584
    тысячи строк пишется две минуты, а квартал целиком почти полчаса одной
    только записью. `COPY` — это поток байтов прямо в таблицу, без сборки
    объекта на каждую строку, и он быстрее примерно на порядок.

    ФОРМАТ ТЕКСТОВЫЙ, а не двоичный, хотя двоичный ещё быстрее: в нём типы
    должны совпадать точь-в-точь, а Python отдаёт целое как int8, тогда как
    `row_num` у нас int4. Такая ошибка вылезла бы не здесь, а на первом же
    боевом файле.

    На не-PostgreSQL (SQLite в тестовых прогонах) `COPY` не существует, и там
    остаётся прежний путь: он медленный, но в тестах строк единицы.
    """
    if db.get_bind().dialect.name != "postgresql":
        db.bulk_save_objects([
            PartnerReportRow(
                id=uuid.uuid4(),
                report_id=report_id,
                row_num=r.row_num,
                sku=r.sku,
                title=r.title,
                artist=r.artist,
                quantity=r.quantity,
                amount_author=r.amount_author,
                amount_related=r.amount_related,
                track_id=track_by_row.get(r.row_num),
                **{name: getattr(r, name) for name in REPORT_ATTRS},
            )
            for r in rows
        ])
        return

    statement = "COPY partner_report_rows (%s) FROM STDIN" % ", ".join(ROW_COLUMNS)
    # Тот же коннект и та же транзакция, что у сессии: если дальше случится
    # отказ, строки уедут обратно вместе со всем остальным.
    with db.connection().connection.cursor() as cursor:
        with cursor.copy(statement) as copy:
            for r in rows:
                copy.write_row((
                    uuid.uuid4(),
                    report_id,
                    r.row_num,
                    r.sku,
                    r.title,
                    r.artist,
                    r.quantity,
                    r.amount_author,
                    r.amount_related,
                    track_by_row.get(r.row_num),
                    *(getattr(r, name) for name in REPORT_ATTRS),
                ))


@partner_reports_router.post(
    "", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def create_report(
    partner_id: uuid.UUID = Form(...),
    period_from: str = Form(...),
    period_to: str = Form(...),
    file: UploadFile = File(...),
    mapping: str = Form(""),
    vat_rate: str = Form(""),
    sheet: str = Form(""),
    currency_rate: str = Form(""),
    manual_skus: str = Form(""),
    content_type: str = Form(""),
    usage_type: str = Form(""),
    usage_kind: str = Form(""),
    territory: str = Form(""),
    save_rule: bool = Form(False),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Сохранить разобранный отчёт.

    Файл разбирается ЗАНОВО, а не берётся из предпросмотра: между «посмотреть»
    и «сохранить» человек мог поправить правило, а держать разобранное между
    запросами значит завести состояние, которое однажды разойдётся с файлом.

    `save_rule` — заодно запомнить правило партнёру: обычный сценарий первой
    загрузки, когда файл и есть образец.

    ПОЛИТИКА ПО ПРОБЛЕМНЫМ СТРОКАМ (правка 18.09.2026, после первых настоящих
    отчётов): загрузка не отклоняется из-за отдельных строк. В отчёте МТС два
    десятка строк без кода объекта и три итоговые строки в конце — файл,
    который нельзя загрузить из-за них, бесполезен. Поэтому:
      - итоговые строки («Итого», «НДС 22%») отсекаются при разборе;
      - строка без артикула грузится и считается неразнесённой;
      - строка, где сумма не прочиталась, грузится с нулями и считается
        проблемной.
    Все три числа человек видит в предпросмотре ДО загрузки. Отказ остаётся
    только там, где грузить нечего: нет нужных колонок или ни одной строки.
    """
    start, end = _period_from_form(period_from, period_to)

    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    content = _read_upload(file)
    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner_id)
    )
    # Шапка и правило — тем же кодом, что в предпросмотре: иначе ключ разбора
    # разошёлся бы с предпросмотром, и загрузка считала бы всё заново.
    head = _head_info(db, str(partner_id), content, file.filename, mapping, vat_rate, sheet, currency_rate)
    chosen_sheet = head["sheet"]
    active_mapping = head["mapping"]
    rate = head["rate"]
    manual = _manual_skus(manual_skus)

    # Разбор и привязка — общие с предпросмотром (см. _parse_and_resolve): если
    # предпросмотр этого файла ещё считается, ждём его, а не начинаем заново.
    result, resolved = _parse_and_resolve(db, content, file.filename, head, manual)
    # Загрузка запоминает вписанные артикулы — прежняя привязка устарела, а
    # разобранное этого файла больше не нужно и занимает много памяти.
    forget_all_parsed()
    if result.problems:
        raise HTTPException(400, "; ".join(result.problems))
    # ОТЧЁТ В ВАЛЮТЕ МОЖНО ЗАГРУЗИТЬ И БЕЗ КУРСА (правка 24.09.2026): курс
    # подставится сам при привязке к поступлению, если итог в валюте сойдётся
    # с «суммой в валюте» платежа (см. link_payment). До тех пор суммы лежат
    # в валюте, отчёт помечен «курс не задан» и в фактический завод НЕ входит
    # — иначе доллары сложились бы с рублями.
    foreign = sorted(c for c in result.currencies if c != "RUB")
    if len(foreign) > 1:
        raise HTTPException(
            400, "В отчёте несколько валют (%s) — один курс к ним не применить" % ", ".join(foreign)
        )
    if not result.rows:
        raise HTTPException(400, "В файле не нашлось ни одной строки с данными")
    if len(result.rows) > MAX_ROWS:
        raise HTTPException(
            400,
            f"В отчёте {len(result.rows)} строк — это больше {MAX_ROWS}. "
            "Похоже, в файл попал не один квартал.",
        )
    # Копия: ниже словарь дополняется приёмником «Вне каталога», а исходный
    # мог достаться и соседнему запросу.
    track_by_row = dict(resolved)

    totals = result.totals
    attrs = _attrs_from_form({
        "content_type": content_type,
        "usage_type": usage_type,
        "usage_kind": usage_kind,
        "territory": territory,
    })
    # Неразнесённая СУММА: сколько денег пока не на что отнести.
    unmatched_amount = rubles(
        sum(
            (
                r.amount_author + r.amount_related
                for r in result.rows
                if r.row_num not in track_by_row
            ),
            Decimal(0),
        )
    )
    report = PartnerReport(
        id=uuid.uuid4(),
        partner_id=partner_id,
        period_from=start,
        period_to=end,
        file_name=file.filename,
        sheet=chosen_sheet,
        rows_count=len(result.rows),
        unmatched_count=sum(1 for r in result.rows if r.row_num not in track_by_row),
        unmatched_amount=unmatched_amount,
        **attrs,
        problem_count=sum(1 for r in result.rows if r.problems),
        total_quantity=totals["quantity"],
        total_author=totals["amount_author"],
        total_related=totals["amount_related"],
        vat_rate=Decimal(rate) if rate else None,
        # Валюта и курс — снимком, как НДС: отчёт обязан объяснять свои числа.
        currency=", ".join(sorted(result.currencies)) or None,
        currency_rate=(
            Decimal(head["currency_rate"].replace(",", ".").replace(" ", ""))
            if head["currency_rate"] else None
        ),
        # Итог в ИСХОДНОЙ валюте: суммы строк уже умножены на курс (если его
        # дали), поэтому делим обратно — с ним сверяется платёж.
        #
        # ТОЧНЫЙ, А НЕ ОКРУГЛЁННЫЙ ДО ЦЕНТА (баг, найден на Believe KZ
        # 24.09.2026): курс при привязке считается как «завод / итог в
        # валюте», а применяется к точным строкам. От округлённого итога
        # (10 456,59 при точных 10 456,5949) полцента евро на курсе 83 дали
        # 41 копейку расхождения с заводом.
        currency_total=(
            sum((r.amount_author + r.amount_related for r in result.rows), Decimal(0))
            / currency_factor(head["currency_rate"] or None)
            if foreign else None
        ),
        uploaded_by=current_user.id,
    )
    db.add(report)
    db.flush()

    # СТРОКИ БЕЗ ТРЕКА ПРИВЯЗЫВАЕМ К «ВНЕ КАТАЛОГА». Счётчики выше
    # (`unmatched_count` / `unmatched_amount`) посчитаны ДО этого и остаются
    # честными: «нет в номенклатуре» — по-прежнему про то, что не нашлось, а
    # приёмник нужен, чтобы по этим строкам можно было что-то выгрузить.
    if report.unmatched_count:
        outside = outside_track_id(db)
        track_by_row = {
            r.row_num: track_by_row.get(r.row_num) or outside for r in result.rows
        }

    _store_rows(db, report.id, result.rows, track_by_row)

    # ЗАПОМИНАЕМ ВПИСАННОЕ РУКАМИ: в следующем отчёте этой площадки тот же
    # трек приедет уже с артикулом. Запоминаем ТОЛЬКО то, что нашлось в
    # каталоге: код с опечаткой, который ничему не соответствует, повторять из
    # месяца в месяц незачем.
    remembered = 0
    for row in result.rows:
        if row.row_num not in manual or row.row_num not in track_by_row or not row.title:
            continue
        title_key, artist_key = _alias_key(row.title, row.artist)
        alias = db.scalar(
            select(PartnerTrackAlias).where(
                PartnerTrackAlias.partner_id == partner_id,
                PartnerTrackAlias.title_key == title_key,
                PartnerTrackAlias.artist_key == artist_key,
            )
        )
        if alias is None:
            db.add(
                PartnerTrackAlias(
                    id=uuid.uuid4(),
                    partner_id=partner_id,
                    title_key=title_key,
                    artist_key=artist_key,
                    title=row.title,
                    artist=row.artist,
                    sku=row.sku,
                    created_by=current_user.id,
                )
            )
            remembered += 1
        elif alias.sku != row.sku:
            # Человек вписал другой артикул той же строке — значит, прежнее
            # сопоставление было неверным. Верим последнему решению.
            alias.sku = row.sku
            alias.created_by = current_user.id
            remembered += 1

    if save_rule:
        if rule is None:
            rule = PartnerReportRule(id=uuid.uuid4(), partner_id=partner_id)
            db.add(rule)
        rule.mapping = active_mapping
        rule.vat_rate = Decimal(rate) if rate else None
        for name, value in attrs.items():
            setattr(rule, name, value)
        rule.sheet = chosen_sheet
        rule.sample_file = file.filename
        rule.updated_at = datetime.now(timezone.utc)

    db.commit()
    log_action(
        db, current_user, "partner_report.create", entity_type="partner_report",
        entity_id=report.id,
        meta={
            "partner": partner.name,
            "period": period_label(start, end),
            "file": file.filename,
            "rows": report.rows_count,
            "unmatched": report.unmatched_count,
            "unmatched_amount": str(unmatched_amount),
            "matched_by_name": sum(1 for r in result.rows if r.matched_by == "name"),
            "manual_skus": len(manual),
            "remembered": remembered,
            "author": str(report.total_author),
            "related": str(report.total_related),
            "currency": report.currency,
            "currency_rate": head["currency_rate"] or None,
        },
    )
    db.commit()
    return {
        "report": _report_out(report, partner.name),
        # Сколько сопоставлений запомнили — человек должен знать, что его
        # правка теперь будет применяться сама.
        "remembered": remembered,
        # Сколько артикулов подобрано по названию — это стоит увидеть сразу:
        # подбор хоть и строгий, но всё-таки догадка сервиса, а не данные
        # площадки.
        "matched_by_name": sum(1 for r in result.rows if r.matched_by == "name"),
    }


@partner_reports_router.get("/{report_id}/unmatched")
def export_unmatched(report_id: uuid.UUID, db: Session = Depends(get_session)) -> StreamingResponse:
    """
    Строки ВНЕ КАТАЛОГА загруженного отчёта — файлом (просьба владельца
    24.09.2026). Живёт у загруженного отчёта, рядом с суммой «Вне каталога», а
    не в импорте: разбираться с недостающими позициями — отдельная работа,
    к загрузке файла она не относится. Выгружаются ВСЕ такие строки.
    Имя файла — «Вне каталога <площадка>.xlsx».
    """
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    partner = db.get(Partner, report.partner_id)
    outside = db.scalar(select(Track.id).where(Track.sku == OUTSIDE_SKU))
    missing = PartnerReportRow.track_id.is_(None)
    if outside is not None:
        missing = or_(missing, PartnerReportRow.track_id == outside)
    rows = db.scalars(
        select(PartnerReportRow)
        .where(PartnerReportRow.report_id == report_id, missing)
        .order_by(PartnerReportRow.row_num)
    ).all()

    # Пока у валютного отчёта нет курса, суммы в нём — валюта, а не рубли.
    unit = report.currency if _rate_pending(report) else "₽"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Вне каталога"
    ws.append([
        "Строка в файле", "Артикул в отчёте", "Название", "Исполнитель", "Количество",
        f"Авторские, {unit}", f"Смежные, {unit}", f"Итого, {unit}",
        *(ATTR_LABELS[name] for name in REPORT_ATTRS),
    ])
    for r in rows:
        author = r.amount_author or Decimal(0)
        related = r.amount_related or Decimal(0)
        # Суммы — ЧИСЛАМИ, а не строками: в Excel их будут складывать.
        ws.append([
            r.row_num, r.sku or "", r.title or "", r.artist or "", r.quantity,
            author, related, author + related,
            # Параметр строки, а если его нет — параметр отчёта, как на экране.
            *((getattr(r, name) or getattr(report, name) or "") for name in REPORT_ATTRS),
        ])
    ws.freeze_panes = "A2"
    for letter, width in zip("ABCDEFGH", (10, 16, 40, 30, 12, 14, 14, 14)):
        ws.column_dimensions[letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    name = " ".join(((partner.name if partner else "") or "").split())
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(f"Вне каталога {name}.xlsx")},
    )


@partner_reports_router.get("/{report_id}/rows")
def report_rows(
    report_id: uuid.UUID,
    page: int = 1,
    page_size: int = 100,
    unmatched_only: bool = False,
    db: Session = Depends(get_session),
) -> dict:
    """Строки отчёта. `unmatched_only` — только те, чей артикул не в каталоге."""
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")

    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    query = select(PartnerReportRow).where(PartnerReportRow.report_id == report_id)
    # «НЕ ОПОЗНАНО» — ЭТО И ПРИЁМНИК «ВНЕ КАТАЛОГА» ТОЖЕ. Ссылка у таких строк
    # теперь есть, но ведёт она в служебную позицию, а не в настоящий трек:
    # спрашивают-то по-прежнему «что не нашлось».
    outside = db.scalar(select(Track.id).where(Track.sku == OUTSIDE_SKU))
    if unmatched_only:
        query = query.where(
            or_(
                PartnerReportRow.track_id.is_(None),
                PartnerReportRow.track_id == outside,
            )
            if outside is not None
            else PartnerReportRow.track_id.is_(None)
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(PartnerReportRow.row_num)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    # КОД И НАЗВАНИЕ БЕРЁМ ИЗ КАТАЛОГА, а не из файла площадки (просьба
    # владельца 24.09.2026, вид «как в Dista»): в детализации правообладателю
    # трек называется так, как он называется у нас, — площадки пишут его
    # каждая по-своему. Из строки отчёта название берётся только там, где
    # трека нет: иначе у неразнесённой строки не осталось бы ничего, кроме
    # артикула.
    tracks = {}
    # ПРИЁМНИК «ВНЕ КАТАЛОГА» — НЕ ТРЕК (замечание владельца 24.09.2026): его
    # название «Вне каталога» подменяло у строки то, что прислала площадка, и
    # понять, что это за позиция, становилось нечем. Такие строки показываем
    # как в отчёте.
    ids = {r.track_id for r in rows if r.track_id and r.track_id != outside}
    if ids:
        tracks = {
            t.id: t
            for t in db.scalars(select(Track).where(Track.id.in_(ids)))
        }
    # ОТКУДА ПАРАМЕТР: из колонки файла или один на весь отчёт. Правку
    # руками пускаем только во втором случае — у первого значение своё в
    # каждой строке, и «поправить» его одним полем нельзя (просьба владельца
    # 24.09.2026).
    per_row = _attrs_from_rows(db, report_id)
    return {
        "per_row_attributes": per_row,
        "rows": [
            {
                "row": r.row_num,
                "sku": r.sku,
                "code": (tracks.get(r.track_id).code if tracks.get(r.track_id) else None),
                "title": (
                    (tracks.get(r.track_id).title if tracks.get(r.track_id) else None)
                    or r.title
                ),
                "artist": (
                    (tracks.get(r.track_id).artist if tracks.get(r.track_id) else None)
                    or r.artist
                ),
                "quantity": _money(r.quantity),
                "amount_author": _money(r.amount_author),
                "amount_related": _money(r.amount_related),
                "total": _money((r.amount_author or 0) + (r.amount_related or 0)),
                # ПАРАМЕТР СТРОКИ, А ЕСЛИ ЕГО НЕТ — ПАРАМЕТР ОТЧЁТА. У
                # площадок с общим значением в строках пусто (дублировать
                # снимок в полмиллиона строк незачем), но человеку в
                # детализации нужно видеть его у каждой позиции.
                **{
                    name: getattr(r, name) or getattr(report, name)
                    for name in REPORT_ATTRS
                },
                # Приёмник настоящим треком не считается — иначе строка
                # выглядела бы разнесённой, хотя деньги по-прежнему ничьи.
                "matched": r.track_id is not None and r.track_id != outside,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@partner_reports_router.patch(
    "/{report_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def update_report(
    report_id: uuid.UUID,
    period_from: str = Form(...),
    period_to: str = Form(...),
    content_type: str = Form(""),
    usage_type: str = Form(""),
    usage_kind: str = Form(""),
    territory: str = Form(""),
    # None — поле не прислали, курс не трогаем; "" — вернуть суммы в валюту.
    currency_rate: str | None = Form(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Поправить ШАПКУ отчёта: период и четыре параметра.

    ЭТО НЕ ПРАВКА ДАННЫХ. Строки, суммы и привязка к каталогу остаются
    нетронутыми — «исправленный» отчёт, у которого файл говорит одно, а база
    другое, объяснить потом нечем, и это правило в силе. А период и параметры
    в файле НЕ НАПИСАНЫ вовсе (период — подсказка из шапки, параметры —
    настройка площадки), их набирает человек при загрузке, и ошибиться в них
    легче всего. Заставлять из-за опечатки в территории перезаливать
    полумиллионный отчёт незачем (просьба владельца 24.09.2026).

    ПАРАМЕТР, ВЗЯТЫЙ ИЗ КОЛОНКИ ФАЙЛА, ПРАВИТЬ НЕЛЬЗЯ: у него своё значение в
    каждой строке, и одно поле на весь отчёт их не заменит — а если бы
    заменило, мы бы затёрли данные площадки своим значением.
    """
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")

    start, end = _period_from_form(period_from, period_to)
    attrs = _attrs_from_form({
        "content_type": content_type,
        "usage_type": usage_type,
        "usage_kind": usage_kind,
        "territory": territory,
    })
    per_row = _attrs_from_rows(db, report_id)
    for name, from_rows in per_row.items():
        if from_rows and attrs[name] != getattr(report, name):
            raise HTTPException(
                400,
                "«%s» берётся из колонки файла — у каждой строки своё значение, "
                "и поправить его одним полем нельзя" % ATTR_LABELS[name],
            )

    report.period_from, report.period_to = start, end
    for name, value in attrs.items():
        if not per_row[name]:
            setattr(report, name, value)
    # КУРС ПРАВИТСЯ РУКАМИ (просьба владельца 24.09.2026): при привязке он
    # ставится сам, но человек вправе его поменять — и тогда суммы отчёта и
    # фактический завод поступления пересчитываются.
    if currency_rate is not None and report.currency and report.currency != "RUB":
        _apply_rate(db, report, currency_rate)
        db.flush()
        if report.payment_id:
            _sync_payment_actual(db, db.get(PartnerPayment, report.payment_id))
    db.commit()

    partner = db.get(Partner, report.partner_id)
    log_action(
        db, current_user, "partner_report.update", entity_type="partner_report",
        entity_id=report.id,
        meta={
            "partner": partner.name if partner else None,
            "period": period_label(report.period_from, report.period_to),
            **{name: getattr(report, name) for name in REPORT_ATTRS},
            "currency_rate": (
                format(report.currency_rate.normalize(), "f") if report.currency_rate else None
            ),
        },
    )
    db.commit()
    payment = db.get(PartnerPayment, report.payment_id) if report.payment_id else None
    return {
        "report": _report_out(
            report,
            partner.name if partner else "",
            payment.occurred_on if payment else None,
            _payment_label(
                payment.occurred_on if payment else None,
                partner.name if partner else None,
                payment_numbers(db).get(payment.id) if payment else None,
            ),
        )
    }


@partner_reports_router.delete(
    "/{report_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def delete_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Удалить отчёт вместе со строками.

    Правки отчёта нет вовсе — только удалить и загрузить заново, как у
    денежных операций: «исправленный» отчёт, у которого файл говорит одно, а
    база другое, объяснить потом нечем.
    """
    report = db.get(PartnerReport, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    partner = db.get(Partner, report.partner_id)
    # Платёж запоминаем ДО удаления: у отчёта была привязка, и после неё у
    # платежа меняются и фактический завод, и отметка «заведено». Раньше их
    # тут не пересчитывали вовсе — удалили единственный отчёт, а в таблице
    # поступлений оставалась сумма, которой больше нечем объясниться.
    payment = db.get(PartnerPayment, report.payment_id) if report.payment_id else None

    db.execute(delete(PartnerReportRow).where(PartnerReportRow.report_id == report_id))
    db.delete(report)
    db.flush()
    _sync_payment_actual(db, payment)
    db.commit()
    log_action(
        db, current_user, "partner_report.delete", entity_type="partner_report",
        entity_id=report_id,
        meta={
            "partner": partner.name if partner else None,
            "period": period_label(report.period_from, report.period_to),
            "file": report.file_name,
        },
    )
    db.commit()
    return {"deleted": report.file_name}
