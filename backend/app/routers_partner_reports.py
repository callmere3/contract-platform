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
    PartnerReport,
    PartnerReportRow,
    PartnerReportRule,
    Track,
    User,
)
from app.partner_reports import (
    FIELDS,
    FIELD_LABELS,
    data_samples,
    match_builtin,
    parse_report,
    period_label,
    pick_track,
    read_columns,
    read_table,
    search_word,
    sheet_names,
    suggest_mapping,
)
from app.roles import CAN_MANAGE_PARTNER_REPORTS, CAN_VIEW_PARTNER_REPORTS

partner_reports_router = APIRouter(
    prefix="/partner-reports",
    tags=["partner-reports"],
    dependencies=[Depends(require_role(*CAN_VIEW_PARTNER_REPORTS))],
)

# Сколько строк показываем в предпросмотре. Больше глазами всё равно не
# смотрят, а браузеру каждая строка — это пять ячеек.
PREVIEW_ROWS = 100
# Строки, к которым не нашлось трека, показываем ВСЕ (до этого предела) — даже
# если они лежат в середине файла, за пределами первой сотни. Иначе кнопка
# «показать строки без артикула» показывала бы не строки без артикула, а те из
# них, что случайно попали в начало.
UNMATCHED_PREVIEW = 300
# Предел на файл. Квартальный отчёт площадки — это десятки тысяч строк;
# миллион означает, что прислали что-то другое или файл склеен из года.
MAX_ROWS = 300_000


def _resolve_tracks(db: Session, rows: list) -> dict:
    """
    Привязать строки отчёта к каталогу: сначала по артикулу, а СТРОКИ БЕЗ
    АРТИКУЛА — по названию и исполнителю (просьба владельца 18.09.2026).

    Зачем второй способ: у площадки код объекта проставлен не всегда. В отчёте
    МТС таких строк шесть, и все шесть на самом деле есть в каталоге — просто
    исполнитель записан иначе («ПОШЛАЯ МОЛЛИ» против «Пошлая Молли», «Slim &
    Константа» против «Slim, Константа»).

    ПОДБИРАЕМ ТОЛЬКО ПРИ СИЛЬНОМ СОВПАДЕНИИ: название сходится целиком (с
    точностью до регистра и знаков препинания), исполнитель — по словам, с
    поправкой на инициалы и разделители, и подошёл РОВНО ОДИН трек. На
    названии «Азимут» в каталоге пять разных треков разных артистов —
    подставить любой из них наугад значит отправить чужие деньги.

    Кандидатов ищем по самому длинному слову названия: искать по названию
    целиком нельзя (в отчёте «Тмстс!», в каталоге «Тмстс»), а слово сужает
    список до десятков, дальше решает строгое сравнение.
    """
    skus = {r.sku for r in rows if r.sku}
    by_sku = {
        sku: track_id
        for sku, track_id in db.execute(
            select(Track.sku, Track.id).where(Track.sku.in_(skus))
        )
    } if skus else {}

    resolved: dict = {}
    for row in rows:
        if row.sku and row.sku in by_sku:
            row.matched_by = "sku"
            resolved[row.row_num] = by_sku[row.sku]

    # Строки без артикула — по названию. Одинаковые пары «название +
    # исполнитель» ищем один раз: в отчёте они повторяются по нескольку строк.
    pending = [r for r in rows if not r.sku and r.title]
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
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _report_out(report: PartnerReport, partner_name: str) -> dict:
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
        "problem_count": report.problem_count,
        "total_quantity": _money(report.total_quantity),
        "total_author": _money(report.total_author),
        "total_related": _money(report.total_related),
        "total": _money((report.total_author or 0) + (report.total_related or 0)),
        "vat_rate": _money(report.vat_rate),
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
    query = select(PartnerReport, Partner.name).join(
        Partner, Partner.id == PartnerReport.partner_id
    )
    if partner_id is not None:
        query = query.where(PartnerReport.partner_id == partner_id)
    if period_from:
        query = query.where(PartnerReport.period_to >= _date(period_from, "period_from"))
    if period_to:
        query = query.where(PartnerReport.period_from <= _date(period_to, "period_to"))

    rows = db.execute(query.order_by(PartnerReport.uploaded_at.desc()).limit(200)).all()
    reports = [_report_out(r, name) for r, name in rows]
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
    partner_id: uuid.UUID = Form(...),
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
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    content = _read_upload(file)
    rule = db.scalar(
        select(PartnerReportRule).where(PartnerReportRule.partner_id == partner_id)
    )
    sheets = sheet_names(content, file.filename)
    chosen_sheet = sheet.strip() or (rule.sheet if rule else None)

    # Колонки читаем ДО применения правила: если правила нет, догадка
    # строится как раз по ним.
    columns, _ = read_columns(content, file.filename, chosen_sheet)
    chosen = _pick_rule(rule, mapping, columns)
    active_mapping = chosen["mapping"]
    rate = (
        vat_rate.strip()
        or (str(rule.vat_rate) if rule and rule.vat_rate else "")
        or (str(chosen["vat_rate"]) if chosen["vat_rate"] else "")
    )
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
    resolved = {} if result.problems else _resolve_tracks(db, result.rows)
    for row in result.rows:
        if row.row_num in manual:
            row.matched_by = "manual"

    # Показываем начало файла И ВСЕ строки, к которым трека не нашлось: именно
    # с ними человеку предстоит работать руками.
    head = result.rows[:PREVIEW_ROWS]
    missing = [r for r in result.rows if r.row_num not in resolved][:UNMATCHED_PREVIEW]
    shown = sorted(
        {r.row_num: r for r in (*head, *missing)}.values(), key=lambda r: r.row_num
    )

    totals = result.totals
    samples = data_samples(
        read_table(content, file.filename, chosen_sheet), result.header_row
    )
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
        # Первые строки файла КАК ЕСТЬ — чтобы было видно сами данные, а не
        # только то, что из них понял сервис.
        "sample_rows": samples,
        "vat_rate": rate or None,
        "problems": result.problems,
        "preview": [
            {
                "row": r.row_num,
                "sku": r.sku,
                "title": r.title,
                "artist": r.artist,
                "matched_by": r.matched_by,
                "matched": r.row_num in resolved,
                "quantity": _money(r.quantity),
                "amount_author": _money(r.amount_author),
                "amount_related": _money(r.amount_related),
                "problems": r.problems,
            }
            for r in shown
        ],
        "preview_limited": totals["rows"] > len(shown),
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
    track_by_row = _resolve_tracks(db, result.rows)
    for row in result.rows:
        if row.row_num in manual:
            row.matched_by = "manual"

    totals = result.totals
    report = PartnerReport(
        id=uuid.uuid4(),
        partner_id=partner_id,
        period_from=start,
        period_to=end,
        file_name=file.filename,
        sheet=chosen_sheet,
        rows_count=len(result.rows),
        unmatched_count=sum(1 for r in result.rows if r.row_num not in track_by_row),
        problem_count=sum(1 for r in result.rows if r.problems),
        total_quantity=totals["quantity"],
        total_author=totals["amount_author"],
        total_related=totals["amount_related"],
        vat_rate=Decimal(rate) if rate else None,
        uploaded_by=current_user.id,
    )
    db.add(report)
    db.flush()

    db.bulk_save_objects([
        PartnerReportRow(
            id=uuid.uuid4(),
            report_id=report.id,
            row_num=r.row_num,
            sku=r.sku,
            title=r.title,
            artist=r.artist,
            quantity=r.quantity,
            amount_author=r.amount_author,
            amount_related=r.amount_related,
            track_id=track_by_row.get(r.row_num),
        )
        for r in result.rows
    ])

    if save_rule:
        if rule is None:
            rule = PartnerReportRule(id=uuid.uuid4(), partner_id=partner_id)
            db.add(rule)
        rule.mapping = active_mapping
        rule.vat_rate = Decimal(rate) if rate else None
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
            "matched_by_name": sum(1 for r in result.rows if r.matched_by == "name"),
            "manual_skus": len(manual),
            "author": str(report.total_author),
            "related": str(report.total_related),
        },
    )
    db.commit()
    return {
        "report": _report_out(report, partner.name),
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
