"""
Партнёры — справочник площадок и агрегаторов, от которых приходят деньги
(ML Finance).

  GET    /partners            — список с поиском
  POST   /partners            — завести
  PATCH  /partners/{id}       — переименовать
  DELETE /partners/{id}       — удалить
  POST   /partners/import     — импорт из .xlsx
  GET    /partners/export     — выгрузка в .xlsx

У ПАРТНЁРА ОДНО ПОЛЕ — имя. Это не заготовка: он нужен, чтобы поступление
было к кому отнести, а договор, реквизиты и ставки живут в карточках
контрагентов и в самих отчётах. Отсюда и вся простота этого файла —
переименование вместо «редактирования карточки», удаление без проверок на
связи (связывать пока не с чем).

ИМЯ УНИКАЛЬНО БЕЗ УЧЁТА РЕГИСТРА И КРАЙНИХ ПРОБЕЛОВ: справочник, в котором
лежат «Яндекс Музыка», «яндекс музыка» и «Яндекс Музыка », справочником быть
перестаёт. В базе при этом стоит обычный UNIQUE — он ловит только точный
повтор, поэтому проверка живёт здесь, в приложении.

ПОРЯДОК МАРШРУТОВ: `/import` и `/export` зарегистрированы РАНЬШЕ `/{id}` —
иначе FastAPI попробует разобрать «import» как uuid и вернёт 422. Та же
грабля, что у контрагентов и уведомлений.
"""
import io
import uuid

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Partner, User
from app.roles import CAN_IMPORT_PARTNERS, CAN_MANAGE_PARTNERS, CAN_VIEW_PARTNERS

partners_router = APIRouter(
    prefix="/partners",
    tags=["partners"],
    # Право на чтение — на всём роутере; пишущие ручки добавляют своё поверх.
    dependencies=[Depends(require_role(*CAN_VIEW_PARTNERS))],
)

MAX_NAME = 255
MAX_DISTA_ID = 32
# ДВЕ КОЛОНКИ, КОД ПЕРВЫЙ (17.09.2026). Файлы сверки приходят со стороны
# Dista, а там строка начинается с идентификатора; так же устроен и импорт
# контрагентов, где «Dista ID» — первая колонка. Пока порядок был обратный,
# первый же залитый файл встал наоборот: имена уехали в коды, коды в имена.
# Порядок тот же, в каком колонки отдаёт экспорт — файл должен заливаться
# обратно без правки руками.
EXCEL_COLUMNS = ("Dista ID", "Партнёр")
# Шапка узнаётся ПО СОДЕРЖИМОМУ и может стоять где угодно, поэтому распознаём
# подписи обеих колонок: руками пишут то «Партнёр», то «Название».
NAME_HEADERS = {"партнёр", "партнер", "название", "имя"}
CODE_HEADERS = {"dista id", "dista_id", "distaid", "id", "код", "код dista"}


def _normalized(name: str) -> str:
    """Ключ сравнения имён: регистр и крайние пробелы значения не имеют."""
    return " ".join(name.split()).casefold()


def _clean(name: str | None) -> str:
    """Имя из запроса → пригодное для хранения, или 400 с понятной причиной."""
    text = " ".join((name or "").split())
    if not text:
        raise HTTPException(400, "Название партнёра не может быть пустым")
    if len(text) > MAX_NAME:
        raise HTTPException(400, f"Название длиннее {MAX_NAME} символов")
    return text


def _taken(db: Session, name: str, exclude: uuid.UUID | None = None) -> bool:
    """Есть ли уже такой партнёр (без учёта регистра и лишних пробелов)."""
    rows = db.execute(select(Partner.id, Partner.name)).all()
    key = _normalized(name)
    return any(
        _normalized(existing) == key and pid != exclude for pid, existing in rows
    )


def _clean_dista_id(value) -> str | None:
    """
    Код в Dista из запроса или ячейки. Пусто — None: «кода нет» и «код пустая
    строка» должны быть одним и тем же, иначе UNIQUE поймает второй пустой.

    Из Excel код нередко приезжает числом (1234 → «1234.0» при наивном
    приведении), поэтому дробную часть целого числа срезаем явно.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:MAX_DISTA_ID]


def _dista_taken(db: Session, dista_id: str, exclude: uuid.UUID | None = None) -> bool:
    """Занят ли код другим партнёром: связь с Dista — один к одному."""
    rows = db.execute(
        select(Partner.id).where(Partner.dista_id == dista_id)
    ).scalars().all()
    return any(pid != exclude for pid in rows)


def _out(partner: Partner) -> dict:
    return {
        "id": str(partner.id),
        "name": partner.name,
        "dista_id": partner.dista_id,
    }


@partners_router.get("")
def list_partners(
    q: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_session),
) -> dict:
    """
    Список с поиском по имени и коду Dista. Постранично — как у контрагентов, хотя
    партнёров будут десятки: единообразие списков дороже пары сэкономленных
    строк, и экран не придётся переделывать, когда их станет много.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    query = select(Partner)
    if q and q.strip():
        # Ищем и по имени, и по коду Dista: человек, у которого в руках
        # строчка их отчёта, держит чаще код, чем название.
        like = f"%{q.strip()}%"
        query = query.where(or_(Partner.name.ilike(like), Partner.dista_id.ilike(like)))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    partners = db.scalars(
        query.order_by(Partner.name).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "partners": [_out(p) for p in partners],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@partners_router.post(
    "/import", dependencies=[Depends(require_role(*CAN_IMPORT_PARTNERS))]
)
def import_partners(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Импорт из .xlsx: ДВЕ КОЛОНКИ — СНАЧАЛА КОД В DISTA, потом имя партнёра,
    по строке на каждого. Код необязателен: часть площадок живёт у нас и без
    него, но место у него первое — файлы сверки приходят из Dista, а там
    строка начинается с идентификатора.

    Шапка необязательна и узнаётся по содержимому: файл на две колонки
    человек нередко собирает руками, сразу с данных, и пропускать первую
    строку вслепую значит терять первого партнёра. Та же логика, что в
    импорте номенклатуры.

    Файл В ОДНУ КОЛОНКУ читается как СПИСОК ИМЁН, а не кодов: справочник,
    набранный руками, — это имена площадок, кодов у человека под рукой нет.
    Решается это по всему файлу сразу, а не построчно, иначе один и тот же
    столбец читался бы то так, то эдак.

    СОПОСТАВЛЯЕМ СНАЧАЛА ПО КОДУ, потом по имени. Код — то, ради чего он
    здесь и появился: имена площадок расходятся первыми («Яндекс Музыка»
    против «Yandex Music»), а код не меняется. Поэтому строка с известным
    кодом ПЕРЕИМЕНОВЫВАЕТ партнёра, а строка с известным именем и новым кодом
    этот код ему проставляет — так справочник и сверяется с Dista.

    Строка, у которой код занят другим партнёром, пропускается с причиной:
    связь 1:1, и молча перевесить её на другого нельзя.
    """
    if not (file.filename or "").endswith(".xlsx"):
        raise HTTPException(400, "Ожидается файл .xlsx")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.file.read()), data_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")

    partners = db.scalars(select(Partner)).all()
    by_name = {_normalized(p.name): p for p in partners}
    by_code = {p.dista_id: p for p in partners if p.dista_id}

    created: list[str] = []
    updated: list[str] = []
    skipped = 0
    conflicts: list[str] = []

    rows = list(wb.active.iter_rows(values_only=True))
    # Вторая колонка пуста во всём файле — значит, перед нами список имён
    # (см. докстринг), а не кодов.
    names_only = not any(
        len(row) > 1 and str(row[1] or "").strip() for row in rows
    )

    for row in rows:
        if names_only:
            raw_code, raw_name = None, (row[0] if row else None)
        else:
            raw_code = row[0] if row else None
            raw_name = row[1] if len(row) > 1 else None
        name = " ".join(str(raw_name or "").split())
        code = _clean_dista_id(raw_code)
        # Шапку отсекаем ДО проверки на пустое имя: в строке «Dista ID |
        # Партнёр» заполнены обе ячейки, и иначе её код уехал бы в справочник.
        if name.casefold() in NAME_HEADERS or (code or "").casefold() in CODE_HEADERS:
            continue  # шапка, где бы она ни стояла
        if not name:
            continue

        name = name[:MAX_NAME]
        key = _normalized(name)
        existing = by_code.get(code) if code else None
        if existing is None:
            existing = by_name.get(key)

        # Код уже закреплён за КЕМ-ТО ДРУГИМ — это не повод молча перевесить.
        if code and by_code.get(code) not in (None, existing):
            conflicts.append(f"{name}: код {code} уже у «{by_code[code].name}»")
            continue
        # Имя занято другим партнёром (нашли по коду, а имя чужое).
        if existing is not None and by_name.get(key) not in (None, existing):
            conflicts.append(f"{name}: это имя уже у другого партнёра")
            continue

        if existing is None:
            partner = Partner(id=uuid.uuid4(), name=name, dista_id=code)
            db.add(partner)
            by_name[key] = partner
            if code:
                by_code[code] = partner
            created.append(name)
            continue

        changed = False
        if existing.name != name:
            by_name.pop(_normalized(existing.name), None)
            existing.name = name
            by_name[key] = existing
            changed = True
        if code and existing.dista_id != code:
            existing.dista_id = code
            by_code[code] = existing
            changed = True
        if changed:
            updated.append(name)
        else:
            skipped += 1

    if created or updated:
        db.commit()
    # Одна запись на прогон, а не на партнёра: журнал недавно чистили от шума.
    log_action(
        db,
        current_user,
        "partner.import",
        entity_type="partner",
        meta={
            "file": file.filename,
            "created": len(created),
            "updated": len(updated),
            "skipped": skipped,
            "conflicts": len(conflicts),
        },
    )
    db.commit()
    return {
        "created": len(created),
        "updated": len(updated),
        "skipped": skipped,
        "names": created[:50],
        "conflicts": conflicts[:20],
    }


@partners_router.get("/export")
def export_partners(db: Session = Depends(get_session)) -> StreamingResponse:
    """
    Выгрузка в .xlsx — в том же виде, в каком её принимает импорт: код Dista
    первой колонкой, имя второй, шапка первой строкой. Выгрузили, поправили,
    залили обратно.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Партнёры"
    ws.append(list(EXCEL_COLUMNS))
    for name, code in db.execute(
        select(Partner.name, Partner.dista_id).order_by(Partner.name)
    ):
        ws.append([code or "", name])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="partners.xlsx"'},
    )


@partners_router.post("", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNERS))])
def create_partner(
    name: str = Form(...),
    dista_id: str | None = Form(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Завести партнёра. Повтор имени или кода — 409, а не молчаливое согласие."""
    clean = _clean(name)
    if _taken(db, clean):
        raise HTTPException(409, f"Партнёр «{clean}» уже есть")
    code = _clean_dista_id(dista_id)
    if code and _dista_taken(db, code):
        raise HTTPException(409, f"Код Dista «{code}» уже закреплён за другим партнёром")

    partner = Partner(id=uuid.uuid4(), name=clean, dista_id=code)
    db.add(partner)
    db.commit()
    log_action(
        db, current_user, "partner.create", entity_type="partner",
        entity_id=partner.id, meta={"name": clean, "dista_id": code},
    )
    db.commit()
    return _out(partner)


@partners_router.patch(
    "/{partner_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNERS))]
)
def rename_partner(
    partner_id: uuid.UUID,
    name: str = Form(...),
    dista_id: str | None = Form(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Правка партнёра: имя и код в Dista. Больше у него полей нет.

    `dista_id` не передан — код не трогаем; передана пустая строка — код
    очищается. Та же семантика, что у правки контрагента: «не прислали» и
    «прислали пусто» — разные вещи, иначе любое переименование стирало бы
    связь с Dista.
    """
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    clean = _clean(name)
    if _taken(db, clean, exclude=partner_id):
        raise HTTPException(409, f"Партнёр «{clean}» уже есть")

    was = partner.name
    partner.name = clean

    if dista_id is not None:
        code = _clean_dista_id(dista_id)
        if code and _dista_taken(db, code, exclude=partner_id):
            raise HTTPException(409, f"Код Dista «{code}» уже закреплён за другим партнёром")
        partner.dista_id = code

    db.commit()
    log_action(
        db, current_user, "partner.rename", entity_type="partner",
        entity_id=partner.id,
        meta={"was": was, "name": clean, "dista_id": partner.dista_id},
    )
    db.commit()
    return _out(partner)


@partners_router.delete(
    "/{partner_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNERS))]
)
def delete_partner(
    partner_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Удалить.

    Проверок на связи здесь НЕТ, потому что связывать пока не с чем: партнёр
    ни в чём не участвует. Появится поступление с партнёром — здесь встанет
    та же проверка с 409, что у контрагента с операциями, и удаление станет
    невозможным молча.
    """
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    name = partner.name
    db.delete(partner)
    db.commit()
    log_action(
        db, current_user, "partner.delete", entity_type="partner",
        entity_id=partner_id, meta={"name": name},
    )
    db.commit()
    return {"deleted": name}
