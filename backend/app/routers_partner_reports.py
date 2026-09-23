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
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, func, select
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
    FIELDS,
    FIELD_LABELS,
    artist_tokens,
    find_period,
    normalize_name,
    match_builtin,
    parse_report,
    period_label,
    pick_track,
    read_columns,
    read_head,
    rubles,
    search_word,
    sheet_names,
    suggest_mapping,
)
from app.roles import CAN_MANAGE_PARTNER_REPORTS, CAN_VIEW_PARTNER_REPORTS
from app.routers_payments import payment_numbers

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
REPORT_ATTRS = ("content_type", "usage_type", "usage_kind", "territory")
ATTR_LABELS = {
    "content_type": "Тип контента",
    "usage_type": "Тип использования",
    "usage_kind": "Вид использования",
    "territory": "Территория",
}
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


def _sync_payment_actual(db: Session, payment: PartnerPayment | None) -> None:
    """
    ФАКТИЧЕСКИЙ ЗАВОД ПЛАТЕЖА = сумма отчётов, к нему привязанных.

    Так это и работает у владельца: платёж пришёл, к нему подшивают отчёты
    площадки, и «сколько по нему реально завелось» — это их итог. Считаем, а
    не просим ввести: числа уже есть в базе, и переписывать их руками значит
    однажды ошибиться в третьем знаке.

    Одним платежом закрывают несколько отчётов, поэтому именно СУММА, а не
    итог последнего привязанного.
    """
    if payment is None:
        return
    rows = db.execute(
        select(PartnerReport.total_author, PartnerReport.total_related).where(
            PartnerReport.payment_id == payment.id
        )
    ).all()
    if not rows:
        # Отвязали последний отчёт — поле очищаем, а не оставляем прежнее
        # число: иначе в таблице висела бы сумма, которой больше нечем
        # объясниться.
        payment.actual_amount = None
        return
    payment.actual_amount = sum(
        ((author or Decimal(0)) + (related or Decimal(0)) for author, related in rows),
        Decimal(0),
    )


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

    clean: dict = {}
    for key, spec in parsed.items():
        if key not in FIELDS:
            raise HTTPException(400, f"Неизвестное поле правила: «{key}»")
        if not isinstance(spec, dict):
            raise HTTPException(400, f"Поле «{key}»: ожидается объект")
        column = str(spec.get("column") or "").strip()
        formula = str(spec.get("formula") or "").strip()
        if column and formula:
            raise HTTPException(
                400, f"Поле «{FIELD_LABELS[key]}»: либо колонка, либо формула, не оба"
            )
        if column:
            clean[key] = {"column": column}
        elif formula:
            clean[key] = {"formula": formula}
    if "sku" not in clean:
        raise HTTPException(400, "Без колонки с артикулом отчёт не разобрать")

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
    if rule is not None and rule.mapping:
        return {"mapping": rule.mapping, "source": "partner", "name": None, "vat_rate": None}
    builtin = match_builtin(columns)
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
        },
    )
    db.commit()
    return {
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


@partner_reports_router.post(
    "/preview", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNER_REPORTS))]
)
def preview(
    partner_id: str = Form(""),
    file: UploadFile = File(...),
    mapping: str = Form(""),
    vat_rate: str = Form(""),
    sheet: str = Form(""),
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
    # ПАРТНЁРА МОЖНО НЕ ВЫБИРАТЬ: если файл узнан по колонкам, площадка
    # определяется из самого правила (просьба владельца 18.09.2026 — «я могу
    # перетянуть отчёт МТС, и он должен выбраться сам»). Не узнан — тогда да,
    # выбирать: по чужому формату гадать не о чем.
    partner = _partner_for(db, partner_id, content, file.filename)

    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner.id)
    )
    sheets = sheet_names(content, file.filename)
    chosen_sheet = sheet.strip() or (rule.sheet if rule else None)

    # ВЕРХ ФАЙЛА ЧИТАЕМ ОДИН РАЗ и переиспользуем: по нему определяются и
    # колонки, и период из шапки. Раньше предпросмотр читал файл ЦЕЛИКОМ трижды
    # (колонки, разбор, период), и на отчёте в полмиллиона строк каждый проход
    # стоил полторы минуты и гигабайт памяти.
    file_head = read_head(content, file.filename, chosen_sheet)
    # Колонки читаем ДО применения правила: если правила нет, догадка
    # строится как раз по ним.
    columns, _ = read_columns(content, file.filename, chosen_sheet, head=file_head)
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
    manual = _manual_skus(manual_skus)

    # Разбираем ВЕСЬ файл, а не первые сто строк: итоги человек сверяет с
    # платежом площадки, а строки без артикула бывают и на пятисотой строке —
    # показать их иначе нечем.
    result = parse_report(
        content, file.filename, active_mapping,
        vat_rate=rate or None, sheet=chosen_sheet,
    )
    _apply_manual(result.rows, manual)
    # Привязку показываем уже в предпросмотре: человек должен видеть, что
    # артикул подобран по названию, ДО того, как отчёт ляжет в базу.
    resolved = {} if result.problems else _resolve_tracks(db, result.rows, partner.id)
    for row in result.rows:
        if row.row_num in manual:
            row.matched_by = "manual"

    # Начало файла и строки без трека — ДВА РАЗНЫХ СПИСКА, а не один
    # склеенный: первый показывают всегда, второй — по кнопке. Склеенные, они
    # дописывали в конец таблицы строки из середины файла, и выглядело это так,
    # будто отчёт ими заканчивается.
    head = result.rows[:PREVIEW_ROWS]
    missing = [r for r in result.rows if r.row_num not in resolved][:UNMATCHED_PREVIEW]

    totals = result.totals
    # ПЕРИОД, НАПИСАННЫЙ В САМОМ ФАЙЛЕ: у МТС это строка над шапкой («за
    # период с 1 июля 2026 по 31 июля 2026»). Период — единственное, что
    # человек вводит руками, и ошибиться в нём легче всего: файл за июнь
    # грузят в июле. Это подсказка — форма подставит, а править можно.
    found_period = find_period(file_head, result.header_row)
    return {
        "partner": {"id": str(partner.id), "name": partner.name},
        "file_name": file.filename,
        "sheets": sheets,
        "sheet": chosen_sheet,
        "columns": result.columns,
        "header_row": result.header_row + 1,     # человеку — как в Excel
        "mapping": active_mapping,
        "rule_saved": rule is not None,
        # Откуда взялось правило: готовое правило площадки, сохранённое у
        # партнёра, настроенное сейчас руками или догадка по названиям колонок.
        "rule_source": chosen["source"],
        "rule_name": chosen["name"],
        "vat_rate": rate or None,
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
        "period": (
            {
                "from": found_period[0].isoformat(),
                "to": found_period[1].isoformat(),
                "label": period_label(*found_period),
            }
            if found_period
            else None
        ),
        "problems": result.problems,
        # Предупреждения не мешают загрузке, но должны быть видны до неё:
        # сейчас это «файл потерял буквы» (см. _warn_if_lossy).
        "warnings": result.warnings,
        "preview": [_preview_row(r, resolved) for r in head],
        "unmatched_rows": [_preview_row(r, resolved) for r in missing],
        "preview_limited": totals["rows"] > len(head),
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
    start = _date(period_from, "Начало периода")
    end = _date(period_to, "Конец периода")
    if end < start:
        raise HTTPException(400, "Конец периода раньше начала")
    if (end - start).days > 400:
        raise HTTPException(400, "Период длиннее года — похоже, ошибка в датах")

    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    content = _read_upload(file)
    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner_id)
    )
    chosen_sheet = sheet.strip() or (rule.sheet if rule else None)
    columns, _ = read_columns(content, file.filename, chosen_sheet)
    chosen = _pick_rule(rule, mapping, columns)
    active_mapping = chosen["mapping"]
    rate = (
        vat_rate.strip()
        or (str(rule.vat_rate) if rule and rule.vat_rate else "")
        or (str(chosen["vat_rate"]) if chosen["vat_rate"] else "")
    )

    result = parse_report(
        content, file.filename, active_mapping,
        vat_rate=rate or None, sheet=chosen_sheet,
    )
    if result.problems:
        raise HTTPException(400, "; ".join(result.problems))
    if not result.rows:
        raise HTTPException(400, "В файле не нашлось ни одной строки с данными")
    if len(result.rows) > MAX_ROWS:
        raise HTTPException(
            400,
            f"В отчёте {len(result.rows)} строк — это больше {MAX_ROWS}. "
            "Похоже, в файл попал не один квартал.",
        )
    # Артикулы, вписанные руками в предпросмотре, — до привязки к каталогу.
    manual = _manual_skus(manual_skus)
    _apply_manual(result.rows, manual)
    # Привязка к каталогу: по артикулу, а строки без него — по названию и
    # исполнителю (см. _resolve_tracks).
    track_by_row = _resolve_tracks(db, result.rows, partner_id)
    for row in result.rows:
        if row.row_num in manual:
            row.matched_by = "manual"

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
        uploaded_by=current_user.id,
    )
    db.add(report)
    db.flush()

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
    if unmatched_only:
        query = query.where(PartnerReportRow.track_id.is_(None))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(PartnerReportRow.row_num)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "rows": [
            {
                "row": r.row_num,
                "sku": r.sku,
                "title": r.title,
                "artist": r.artist,
                "quantity": _money(r.quantity),
                "amount_author": _money(r.amount_author),
                "amount_related": _money(r.amount_related),
                "matched": r.track_id is not None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
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

    db.execute(delete(PartnerReportRow).where(PartnerReportRow.report_id == report_id))
    db.delete(report)
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
