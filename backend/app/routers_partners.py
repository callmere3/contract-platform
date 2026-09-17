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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Partner, User
from app.roles import CAN_MANAGE_PARTNERS, CAN_VIEW_PARTNERS

partners_router = APIRouter(
    prefix="/partners",
    tags=["partners"],
    # Право на чтение — на всём роутере; пишущие ручки добавляют своё поверх.
    dependencies=[Depends(require_role(*CAN_VIEW_PARTNERS))],
)

MAX_NAME = 255
EXCEL_COLUMNS = ("Партнёр",)


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


def _out(partner: Partner) -> dict:
    return {"id": str(partner.id), "name": partner.name}


@partners_router.get("")
def list_partners(
    q: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_session),
) -> dict:
    """
    Список с поиском по имени. Постранично — как у контрагентов, хотя
    партнёров будут десятки: единообразие списков дороже пары сэкономленных
    строк, и экран не придётся переделывать, когда их станет много.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    query = select(Partner)
    if q and q.strip():
        query = query.where(Partner.name.ilike(f"%{q.strip()}%"))

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
    "/import", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNERS))]
)
def import_partners(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Импорт из .xlsx: ОДНА КОЛОНКА — имя партнёра, по строке на партнёра.

    Шапка необязательна и узнаётся по содержимому («Партнёр»/«Название»): файл
    из одной колонки человек нередко собирает руками, сразу с данных, и
    пропускать первую строку вслепую значит терять первого партнёра. Та же
    логика, что в импорте номенклатуры.

    Уже известные имена пропускаются, а не задваиваются и не обновляются:
    обновлять у партнёра нечего, кроме самого имени, а имя и есть ключ.
    """
    if not (file.filename or "").endswith(".xlsx"):
        raise HTTPException(400, "Ожидается файл .xlsx")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.file.read()), data_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")

    known = {_normalized(name) for name in db.scalars(select(Partner.name))}
    created: list[str] = []
    skipped = 0

    for row in wb.active.iter_rows(values_only=True):
        raw = row[0] if row else None
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        if text.casefold() in {"партнёр", "партнер", "название", "имя"}:
            continue  # шапка, где бы она ни стояла
        key = _normalized(text)
        if key in known:
            skipped += 1
            continue
        db.add(Partner(id=uuid.uuid4(), name=text[:MAX_NAME]))
        known.add(key)
        created.append(text)

    if created:
        db.commit()
    # Одна запись на прогон, а не на партнёра: журнал недавно чистили от шума.
    log_action(
        db,
        current_user,
        "partner.import",
        entity_type="partner",
        meta={"file": file.filename, "created": len(created), "skipped": skipped},
    )
    db.commit()
    return {"created": len(created), "skipped": skipped, "names": created[:50]}


@partners_router.get("/export")
def export_partners(db: Session = Depends(get_session)) -> StreamingResponse:
    """
    Выгрузка в .xlsx — в том же виде, в каком её принимает импорт: одна
    колонка, шапка первой строкой. Выгрузили, поправили, залили обратно.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Партнёры"
    ws.append(list(EXCEL_COLUMNS))
    for name in db.scalars(select(Partner.name).order_by(Partner.name)):
        ws.append([name])

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
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Завести партнёра. Повтор имени — 409, а не молчаливое согласие."""
    clean = _clean(name)
    if _taken(db, clean):
        raise HTTPException(409, f"Партнёр «{clean}» уже есть")

    partner = Partner(id=uuid.uuid4(), name=clean)
    db.add(partner)
    db.commit()
    log_action(
        db, current_user, "partner.create", entity_type="partner",
        entity_id=partner.id, meta={"name": clean},
    )
    db.commit()
    return _out(partner)


@partners_router.patch(
    "/{partner_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PARTNERS))]
)
def rename_partner(
    partner_id: uuid.UUID,
    name: str = Form(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Переименовать. Единственная правка, какая у партнёра может быть, — больше
    у него полей нет.
    """
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(404, "Партнёр не найден")

    clean = _clean(name)
    if _taken(db, clean, exclude=partner_id):
        raise HTTPException(409, f"Партнёр «{clean}» уже есть")

    was = partner.name
    partner.name = clean
    db.commit()
    log_action(
        db, current_user, "partner.rename", entity_type="partner",
        entity_id=partner.id, meta={"was": was, "name": clean},
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
