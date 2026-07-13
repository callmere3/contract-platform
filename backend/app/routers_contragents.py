"""
Эндпоинты работы с контрагентами (этап 4, база контрагентов).

  POST /contragents                    — создать контрагента (title/contract_number
                                          вычисляются автоматически, см. брейншторм)
  GET  /contragents?q=...              — поиск по title/nickname (ILIKE, регистронезависимо).
                                          Без q — весь список (для стартового экрана/отладки).
  POST /contragents/import             — массовый импорт из .xlsx (обязательна только
                                          колонка "Титл"; дубли по title обновляются,
                                          а не дублируются)
  GET  /contragents/export             — выгрузка всех контрагентов в .xlsx (тот же
                                          формат колонок, что и импорт — файл можно
                                          поправить руками и залить обратно)
  GET  /contragents/{id}               — карточка контрагента целиком
  PATCH /contragents/{id}              — правка карточки (кроме title; пока
                                          только через Swagger, без UI)
  DELETE /contragents/{id}             — удалить контрагента (никнеймы каскадно;
                                          пока только через Swagger, без кнопки в UI)
  GET  /contragents/{id}/templates     — подбор документов, совместимых с контрагентом
                                          по тегам (country/contragent_type/contract_family)
  POST /contragents/{id}/nicknames     — добавить псевдоним контрагенту

ВАЖНО про порядок маршрутов: /import и /export зарегистрированы РАНЬШЕ
/{contragent_id} — иначе FastAPI попытался бы распарсить 'import'/'export'
как uuid.UUID и вернул бы 422 вместо реального обработчика (порядок
регистрации маршрутов в Starlette имеет значение для статических путей
против путей с параметром).
"""
import io
import uuid
from datetime import date as _date
from datetime import datetime as _datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.context_builder import build_contract_number, build_contragent_title, parse_date
from app.db import get_session
from app.models import Contragent, ContragentNickname, Template
from app.tags import (
    COUNTRIES,
    CONTRACT_FAMILIES,
    CONTRAGENT_TYPES,
    normalize_optional_tag,
    normalize_tag,
)

contragents_router = APIRouter(prefix="/contragents", tags=["contragents"])

# Порядок колонок общий для импорта и экспорта (см. брейншторм, раздел
# "Импорт/экспорт (Excel)") — человекочитаемые русские заголовки, файл
# симметричен в обе стороны: экспортировал -> поправил руками -> залил
# обратно тем же импортом.
#
# "Титл" — единственная обязательная колонка (это title контрагента,
# по нему же идёт поиск/дедупликация при импорте). "Название" (ФИО/
# название компании) — необязательная колонка, в отличие от создания
# через UI (POST /contragents), где name обязателен, а title вычисляется
# из него автоматически. При импорте — наоборот: title всегда берётся из
# файла как есть, а name опционален.
EXCEL_COLUMNS = [
    "Титл", "Название", "Никнеймы", "Тип", "Страна",
    "Тип договора", "Номер договора", "Дата договора", "Роялти %",
]


def _contragent_summary(c: Contragent) -> dict:
    """Краткое представление для списков поиска — title крупно, никнеймы мелко (см. брейншторм)."""
    return {
        "id": str(c.id),
        "title": c.title,
        "name": c.name,
        "nicknames": [n.nickname for n in c.nicknames],
        "country": c.country,
        "type": c.type,
        "contract_family": c.contract_family,
    }


def _parse_excel_date(value) -> _date | None:
    """
    Ячейка "Дата договора" — Excel сам отдаёт datetime/date для ячеек с
    форматом даты (openpyxl, data_only=True), но допускаем и текст на
    случай, если колонку сохранили как обычный текст — тогда используем
    тот же parse_date(), что и в остальном проекте (ISO/русский/точечный
    форматы), чтобы не заводить третий парсер дат в одном сервисе.
    """
    if value in (None, ""):
        return None
    if isinstance(value, _datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    parsed = parse_date(str(value))
    if not parsed:
        return None
    day, month, year = parsed
    return _date(int(year), int(month), int(day))


def _parse_percent(value) -> Decimal | None:
    """Ячейка "Роялти %" — число или текст с запятой вместо точки ('12,5')."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", ".").replace("%", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _try_normalize_optional(value, allowed: list[str], field_name: str) -> tuple[str | None, str | None]:
    """
    Как normalize_optional_tag, но не бросает исключение — возвращает
    (значение_или_None, текст_предупреждения_или_None). Импорт работает
    "мягко" (см. брейншторм — "validate loosely, не all-or-nothing"):
    опечатка в одной ячейке одной строки не должна ронять всю загрузку
    файла на сотни контрагентов — теряется только это поле этой строки,
    остальное (включая title/nickname) сохраняется, а причина попадает
    в отчёт по этой строке.
    """
    if value in (None, ""):
        return None, None
    try:
        return normalize_tag(str(value), allowed, field_name), None
    except HTTPException as exc:
        return None, str(exc.detail)


@contragents_router.get("")
def search_contragents(
    q: str | None = None,
    country: str | None = None,
    contragent_type: str | None = None,
    db: Session = Depends(get_session),
) -> dict:
    """
    Поиск по title, name ИЛИ nickname одновременно (см. брейншторм — SQL-
    запрос там же): не важно, по чему совпало, оператор в любом случае
    видит и title, и никнеймы сразу. name добавлен отдельно от title,
    потому что это разные строки (title — вычисленное "Иванов И. И. (СГ)",
    name — сырое "Иванов Иван Иванович") — поиск/проверка дублей по одному
    только title могла не найти уже существующего человека, если искать
    по тому, как его ФИО выглядит целиком.

    country/contragent_type — необязательные фильтры по тегам (точное
    совпадение после нормализации регистра, см. app/tags.py), применяются
    ДОПОЛНИТЕЛЬНО к q, а не вместо него. contract_family сюда намеренно
    не добавлен — фильтр по роялти/авансу не нужен (см. запрос пользователя).

    Без q/фильтров — отдаёт весь список (ограничен 200 записями).
    """
    query = db.query(Contragent)
    if q:
        query = (
            query.outerjoin(
                ContragentNickname, ContragentNickname.contragent_id == Contragent.id
            )
            .filter(
                or_(
                    Contragent.title.ilike(f"%{q}%"),
                    Contragent.name.ilike(f"%{q}%"),
                    ContragentNickname.nickname.ilike(f"%{q}%"),
                )
            )
            .distinct()
        )
    if country:
        query = query.filter(
            Contragent.country == normalize_optional_tag(country, COUNTRIES, "country")
        )
    if contragent_type:
        query = query.filter(
            Contragent.type
            == normalize_optional_tag(contragent_type, CONTRAGENT_TYPES, "contragent_type")
        )
    contragents = query.order_by(Contragent.title).limit(200).all()
    return {"contragents": [_contragent_summary(c) for c in contragents]}


@contragents_router.post("")
def create_contragent(
    name: str = Form(...),
    country: str = Form(...),           # 'РУ' | 'КЗ'
    contragent_type: str = Form(...),   # 'СГ' | 'ИП' | 'ООО'
    contract_family: str = Form(...),   # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'
    contract_date: str = Form(...),     # ISO из <input type="date">, напр. '2026-03-15'
    royalty_percent: float = Form(...),
    nicknames: str | None = Form(None), # через запятую, тот же формат, что и в импорте
    db: Session = Depends(get_session),
) -> dict:
    """
    Создаёт карточку контрагента. title и contract_number вычисляются
    автоматически и НЕ принимаются от клиента — см. брейншторм
    ("title... НЕ показывается и НЕ редактируется в форме создания").

    contract_date фиксируется здесь один раз и дальше только отображается
    при генерации "Договора" — не пересчитывается на лету (см. брейншторм,
    "Почему именно так, а не иначе").

    nicknames — необязательное поле, через запятую (как в импорте/экспорте,
    см. import_contragents), можно оставить пустым и добавить никнейм(ы)
    позже через POST /contragents/{id}/nicknames.

    Мягкая проверка дублей (см. брейншторм) — задача фронтенда: перед
    сабмитом вызвать GET /contragents?q=<name> и показать похожие; сам
    этот эндпоинт ничего не блокирует (жёсткого constraint на title в БД
    нет, см. models.py).

    Это эндпоинт СОЗДАНИЯ ЧЕРЕЗ UI — остальные поля обязательны, как в
    UX-флоу брейншторма ("Новый контрагент"). Массовый импорт с неполными
    записями (только title/nickname) — отдельный эндпоинт (POST
    /contragents/import, шаг 5, работает по другим правилам: title
    берётся из файла как есть, без пересчёта).

    country/contragent_type/contract_family нормализуются к каноническому
    регистру (см. app/tags.py) — без этого 'ру' и 'РУ' в БД считались бы
    разными значениями, и подбор документов по тегам (шаг 4) молча не
    находил бы шаблоны для контрагента, введённого не в том регистре.
    """
    country = normalize_tag(country, COUNTRIES, "country")
    contragent_type = normalize_tag(contragent_type, CONTRAGENT_TYPES, "contragent_type")
    contract_family = normalize_tag(contract_family, CONTRACT_FAMILIES, "contract_family")

    if not (0 <= royalty_percent <= 100):
        raise HTTPException(
            status_code=400,
            detail=f"Роялти должно быть числом от 0 до 100, получено: {royalty_percent}",
        )

    parsed = parse_date(contract_date)
    if not parsed:
        raise HTTPException(
            status_code=400, detail=f"Не удалось распознать дату договора: {contract_date!r}"
        )
    day, month, year_full = parsed

    title = build_contragent_title(name, contragent_type)
    contract_number = build_contract_number(
        day=day,
        month=month,
        year=year_full[-2:],
        full_name=name,
        doc_kind=contragent_type,
    )

    contragent = Contragent(
        name=name,
        title=title,
        country=country,
        type=contragent_type,
        contract_family=contract_family,
        contract_date=_date(int(year_full), int(month), int(day)),
        contract_number=contract_number,
        royalty_percent=royalty_percent,
    )
    db.add(contragent)
    db.flush()   # нужен contragent.id до вставки никнеймов

    nickname_list = (
        [n.strip() for n in nicknames.split(",") if n.strip()] if nicknames else []
    )
    for nick in nickname_list:
        db.add(ContragentNickname(contragent_id=contragent.id, nickname=nick))

    db.commit()

    return {
        "id": str(contragent.id),
        "title": contragent.title,
        "contract_number": contragent.contract_number,
        "contract_date": contragent.contract_date.isoformat(),
        "nicknames": nickname_list,
    }


@contragents_router.post("/import")
def import_contragents(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Массовый импорт контрагентов из .xlsx — одна строка на контрагента
    (см. брейншторм, раздел "Импорт/экспорт (Excel)").

    Обязательна ТОЛЬКО колонка "Титл" (title) — по ней же идёт поиск
    дублей. Остальные колонки, включая "Название" (ФИО/название), могут
    отсутствовать или быть пустыми в конкретной строке, контрагент
    создаётся/обновляется "неполным" (см. GET /contragents/{id}/templates —
    такой контрагент просто не участвует в подборе документов, пока
    карточку не дозаполнят).

    "Титл" и "Номер договора" берутся из файла КАК ЕСТЬ, без пересчёта —
    в отличие от POST /contragents (создание через UI), где title
    вычисляется из name по формуле. Здесь это исторические/юридически
    зафиксированные значения, пересчёт мог бы дать другое число, чем
    реально стоит в бумажном договоре.

    Дубли — точное совпадение "Титл" с уже существующим контрагентом:
    существующая запись ОБНОВЛЯЕТСЯ, вторая не создаётся. При обновлении
    непустая ячейка перезаписывает соответствующее поле, пустая — оставляет
    прежнее значение как есть (не затирает то, что уже было заполнено
    вручную и отсутствует в конкретном файле повторного импорта). Никнеймы
    при непустой ячейке заменяются ПОЛНОСТЬЮ новым набором из ячейки
    (через запятую), а не дополняются.

    Невалидный тег (country/тип/тип договора — опечатка, значения нет
    среди допустимых) не роняет всю строку: поле остаётся пустым, причина
    попадает в "details" по этой строке, остальные поля сохраняются.
    Единственная причина полностью пропустить строку — отсутствие "Титл".
    """
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Ожидается файл .xlsx")

    content = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {exc}")
    ws = wb.active

    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    header = [str(v).strip() if v is not None else "" for v in header_row]
    if "Титл" not in header:
        raise HTTPException(
            status_code=400, detail="В файле нет обязательной колонки «Титл»"
        )
    col_index = {name: i for i, name in enumerate(header)}

    def cell(row: tuple, name: str):
        idx = col_index.get(name)
        return row[idx] if idx is not None and idx < len(row) else None

    created = updated = skipped = 0
    details: list[dict] = []

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row is None or all(v is None for v in row):
            continue   # полностью пустая строка — не считаем ни пропуском, ни ошибкой

        title_raw = cell(row, "Титл")
        title = str(title_raw).strip() if title_raw not in (None, "") else ""
        if not title:
            skipped += 1
            details.append({"row": row_num, "status": "пропущено", "reason": "нет титла (title)"})
            continue

        name_raw = cell(row, "Название")
        name = str(name_raw).strip() if name_raw not in (None, "") else None

        warnings: list[str] = []

        contragent_type, w = _try_normalize_optional(cell(row, "Тип"), CONTRAGENT_TYPES, "Тип")
        if w:
            warnings.append(w)
        country, w = _try_normalize_optional(cell(row, "Страна"), COUNTRIES, "Страна")
        if w:
            warnings.append(w)
        contract_family, w = _try_normalize_optional(
            cell(row, "Тип договора"), CONTRACT_FAMILIES, "Тип договора"
        )
        if w:
            warnings.append(w)

        contract_number_raw = cell(row, "Номер договора")
        contract_number = (
            str(contract_number_raw).strip() if contract_number_raw not in (None, "") else None
        )
        contract_date_val = _parse_excel_date(cell(row, "Дата договора"))
        royalty_percent = _parse_percent(cell(row, "Роялти %"))

        nicknames_raw = cell(row, "Никнеймы")
        nicknames = (
            [n.strip() for n in str(nicknames_raw).split(",") if n.strip()]
            if nicknames_raw not in (None, "")
            else None
        )

        existing = db.query(Contragent).filter(Contragent.title == title).one_or_none()

        if existing is None:
            contragent = Contragent(
                name=name,   # теперь отдельная опциональная колонка "Название", не заглушка
                title=title,
                country=country,
                type=contragent_type,
                contract_family=contract_family,
                contract_date=contract_date_val,
                contract_number=contract_number,
                royalty_percent=royalty_percent,
            )
            db.add(contragent)
            db.flush()   # нужен contragent.id до вставки никнеймов
            for nick in (nicknames or []):
                db.add(ContragentNickname(contragent_id=contragent.id, nickname=nick))
            created += 1
            details.append(
                {"row": row_num, "status": "создано", "title": title, "warnings": warnings}
            )
        else:
            if name is not None:
                existing.name = name
            if country is not None:
                existing.country = country
            if contragent_type is not None:
                existing.type = contragent_type
            if contract_family is not None:
                existing.contract_family = contract_family
            if contract_number is not None:
                existing.contract_number = contract_number
            if contract_date_val is not None:
                existing.contract_date = contract_date_val
            if royalty_percent is not None:
                existing.royalty_percent = royalty_percent
            if nicknames is not None:
                for old_nick in list(existing.nicknames):
                    db.delete(old_nick)
                db.flush()
                for nick in nicknames:
                    db.add(ContragentNickname(contragent_id=existing.id, nickname=nick))
            updated += 1
            details.append(
                {"row": row_num, "status": "обновлено", "title": title, "warnings": warnings}
            )

    db.commit()

    return {"created": created, "updated": updated, "skipped": skipped, "details": details}


@contragents_router.get("/export")
def export_contragents(db: Session = Depends(get_session)) -> StreamingResponse:
    """
    Выгружает всех контрагентов в .xlsx — те же колонки и тот же порядок,
    что ожидает import_contragents(), файл можно поправить руками и залить
    обратно тем же импортом (см. брейншторм — "Экспорт... симметрично
    формату импорта").
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Контрагенты"
    ws.append(EXCEL_COLUMNS)

    contragents = db.query(Contragent).order_by(Contragent.title).all()
    for c in contragents:
        ws.append([
            c.title,
            c.name or "",
            ", ".join(n.nickname for n in c.nicknames),
            c.type or "",
            c.country or "",
            c.contract_family or "",
            c.contract_number or "",
            c.contract_date.isoformat() if c.contract_date else "",
            float(c.royalty_percent) if c.royalty_percent is not None else "",
        ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="contragents_export.xlsx"'},
    )


@contragents_router.get("/{contragent_id}")
def get_contragent(contragent_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """Полная карточка контрагента — для экрана "после выбора контрагента" (см. брейншторм)."""
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    return {
        "id": str(contragent.id),
        "name": contragent.name,
        "title": contragent.title,
        "country": contragent.country,
        "type": contragent.type,
        "contract_family": contragent.contract_family,
        "contract_date": (
            contragent.contract_date.isoformat() if contragent.contract_date else None
        ),
        "contract_number": contragent.contract_number,
        "royalty_percent": (
            float(contragent.royalty_percent) if contragent.royalty_percent is not None else None
        ),
        "nicknames": [n.nickname for n in contragent.nicknames],
    }


@contragents_router.patch("/{contragent_id}")
def update_contragent(
    contragent_id: uuid.UUID,
    title: str | None = Form(None),
    name: str | None = Form(None),
    country: str | None = Form(None),
    contragent_type: str | None = Form(None),
    contract_family: str | None = Form(None),
    contract_date: str | None = Form(None),
    contract_number: str | None = Form(None),
    royalty_percent: str | None = Form(None),
    nicknames: str | None = Form(None),
    db: Session = Depends(get_session),
) -> dict:
    """
    Правит существующую карточку контрагента.

    title теперь МОЖНО редактировать (пересмотрено): изначально title
    исключался из правки по брейншторму (менялся только напрямую в БД).
    Причина пересмотра — реальный кейс: один и тот же человек может иметь
    ДВА отдельных контрагента в базе — один с contract_family=АВАНС,
    другой с РОЯЛТИ (два разных контракта, две карточки). При создании оба
    получают ОДИНАКОВЫЙ title (формула title не зависит от contract_family,
    только от name+type), это ожидаемо и не блокируется (нет unique-
    constraint на title, см. models.py) — но их нужно разделить после
    создания вручную, например "Иванов И. И. (СГ, аванс)" и
    "Иванов И. И. (СГ, роялти)", иначе не различить в поиске/списках.
    title не может быть пустой строкой — это NOT NULL в БД, попытка
    очистить возвращает 400, а не тихо ломает запись.

    Семантика остальных полей — та же, что и в PATCH /templates/{id}:
      - параметр не передан в форме -> не трогаем, значение остаётся как было
      - передана пустая строка -> поле очищается (None)
      - передано непустое значение -> валидируется/парсится и сохраняется

    contract_date/contract_number здесь — независимые "сырые" поля, как
    при импорте (см. import_contragents), НЕ пересчитываются друг из
    друга. Это ручная правка на случай ошибки при вводе, а не обычный
    рабочий путь — в обычном пути contract_date фиксируется один раз при
    создании и дальше не меняется (см. брейншторм).

    nicknames — при непустом значении ПОЛНОСТЬЮ заменяет прежний список
    (через запятую), как и при импорте, а не дополняет его.

    Пока доступно только через Swagger — в интерфейсе кнопки правки
    карточки контрагента ещё нет (осознанное решение, см. контекст проекта).
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    if title is not None:
        stripped_title = title.strip()
        if not stripped_title:
            raise HTTPException(status_code=400, detail="title не может быть пустым")
        contragent.title = stripped_title

    if name is not None:
        contragent.name = name.strip() or None

    if country is not None:
        contragent.country = normalize_optional_tag(country, COUNTRIES, "country")
    if contragent_type is not None:
        contragent.type = normalize_optional_tag(
            contragent_type, CONTRAGENT_TYPES, "contragent_type"
        )
    if contract_family is not None:
        contragent.contract_family = normalize_optional_tag(
            contract_family, CONTRACT_FAMILIES, "contract_family"
        )

    if contract_number is not None:
        contragent.contract_number = contract_number.strip() or None

    if contract_date is not None:
        if not contract_date.strip():
            contragent.contract_date = None
        else:
            parsed = parse_date(contract_date)
            if not parsed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Не удалось распознать дату договора: {contract_date!r}",
                )
            day, month, year_full = parsed
            contragent.contract_date = _date(int(year_full), int(month), int(day))

    if royalty_percent is not None:
        if not royalty_percent.strip():
            contragent.royalty_percent = None
        else:
            value = _parse_percent(royalty_percent)
            if value is None:
                raise HTTPException(
                    status_code=400, detail=f"Не удалось распознать роялти %: {royalty_percent!r}"
                )
            if not (0 <= value <= 100):
                raise HTTPException(
                    status_code=400,
                    detail=f"Роялти должно быть числом от 0 до 100, получено: {value}",
                )
            contragent.royalty_percent = value

    if nicknames is not None:
        for old_nick in list(contragent.nicknames):
            db.delete(old_nick)
        db.flush()
        for nick in [n.strip() for n in nicknames.split(",") if n.strip()]:
            db.add(ContragentNickname(contragent_id=contragent.id, nickname=nick))

    db.commit()

    return {
        "id": str(contragent.id),
        "title": contragent.title,
        "name": contragent.name,
        "country": contragent.country,
        "type": contragent.type,
        "contract_family": contragent.contract_family,
        "contract_date": (
            contragent.contract_date.isoformat() if contragent.contract_date else None
        ),
        "contract_number": contragent.contract_number,
        "royalty_percent": (
            float(contragent.royalty_percent) if contragent.royalty_percent is not None else None
        ),
        "nicknames": [n.nickname for n in contragent.nicknames],
    }


@contragents_router.delete("/{contragent_id}")
def delete_contragent(contragent_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Удаляет контрагента. Никнеймы удаляются каскадно (cascade="all,
    delete-orphan" в models.py + ondelete="CASCADE" на FK в БД).

    Пока нет таблицы generated_documents (см. брейншторм — сознательно не
    делаем), нет и проверки "а генерировали ли уже документы для этого
    контрагента" — удаление ничего, кроме самой карточки и её никнеймов,
    не затрагивает: ранее сгенерированные .docx в MinIO не трогаются,
    шаблоны и их теги тоже.

    Пока доступно только через Swagger — кнопка удаления в самом
    интерфейсе (экран документов контрагента) ещё не добавлена.
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    db.delete(contragent)
    db.commit()

    return {"id": str(contragent_id), "deleted": True}


@contragents_router.get("/{contragent_id}/templates")
def list_contragent_templates(
    contragent_id: uuid.UUID,
    db: Session = Depends(get_session),
) -> dict:
    """
    Подбор документов для контрагента (см. брейншторм, "После выбора
    контрагента: список документов, отфильтрованный по (country,
    contragent_type, contract_family) контрагента").

    Сравнение — строгое равенство трёх тегов, поэтому оно надёжно только
    благодаря нормализации регистра при создании контрагента (см.
    app/tags.py) и при ручном тегировании шаблонов — если где-то закрадётся
    несовпадающий регистр, документ просто не найдётся здесь без явной
    ошибки, это стоит держать в голове при отладке.

    Если у контрагента не заполнены country/type/contract_family
    (например, "неполная" карточка из будущего мягкого импорта, см.
    брейншторм) — возвращает пустой список, а не ошибку: карточка валидна,
    просто пока не участвует в подборе документов.
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    if not (contragent.country and contragent.type and contragent.contract_family):
        return {"contragent_id": str(contragent_id), "templates": []}

    templates = (
        db.query(Template)
        .filter(
            Template.country == contragent.country,
            Template.contragent_type == contragent.type,
            Template.contract_family == contragent.contract_family,
        )
        .order_by(Template.name)
        .all()
    )

    return {
        "contragent_id": str(contragent_id),
        "templates": [
            {"id": str(t.id), "name": t.name, "doc_type": t.doc_type} for t in templates
        ],
    }


@contragents_router.post("/{contragent_id}/nicknames")
def add_nickname(
    contragent_id: uuid.UUID,
    nickname: str = Form(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Добавляет псевдоним контрагенту. Никнеймов может быть несколько —
    на форме генерации они показываются выпадающим списком, не
    свободным текстом (см. брейншторм).
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    nick = ContragentNickname(contragent_id=contragent_id, nickname=nickname)
    db.add(nick)
    db.commit()

    return {"id": str(nick.id), "contragent_id": str(contragent_id), "nickname": nick.nickname}
