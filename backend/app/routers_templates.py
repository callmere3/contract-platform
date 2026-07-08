"""
Эндпоинты этапа 2 — работа с шаблонами и генерация документов.

Всё проверяется через Swagger UI (http://<сервер>:8000/docs) — интерфейса
пока нет, это сознательно (по роадмапу UI идёт этапом 3).

  POST /templates            — загрузить шаблон (.docx), метки просканируются автоматически
  GET  /templates            — список загруженных шаблонов
  GET  /templates/{id}/fields — какие поля нужно заполнить для этого шаблона
  POST /templates/{id}/generate — сгенерировать документ по присланным данным
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.generation import render_document, scan_placeholders
from app.models import Template, TemplateField
from app.storage import get_file, put_file

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("")
def upload_template(
    name: str = Form(...),
    branch: str = Form(...),      # 'РУ' | 'КЗ'
    doc_type: str = Form(...),    # 'договор' | 'приложение' | 'акт'
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """Загружает шаблон, сканирует метки и сохраняет всё в БД + MinIO."""
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Ожидается файл .docx")

    content = file.file.read()

    # сканируем метки ДО сохранения — если файл битый, упадём здесь и не оставим мусор
    try:
        placeholders = scan_placeholders(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать шаблон: {exc}")

    template_id = uuid.uuid4()
    storage_key = f"templates/{template_id}.docx"
    put_file(storage_key, content)

    template = Template(
        id=template_id,
        name=name,
        storage_key=storage_key,
        branch=branch,
        doc_type=doc_type,
    )
    # каждую найденную метку заводим как поле; по умолчанию — ручной ввод
    template.fields = [TemplateField(placeholder=p, maps_to="manual") for p in placeholders]

    db.add(template)
    db.commit()

    return {
        "id": str(template_id),
        "name": name,
        "branch": branch,
        "doc_type": doc_type,
        "fields_found": placeholders,
    }


@router.get("")
def list_templates(db: Session = Depends(get_session)) -> list[dict]:
    """Список всех загруженных шаблонов."""
    templates = db.query(Template).order_by(Template.created_at.desc()).all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "branch": t.branch,
            "doc_type": t.doc_type,
            "fields_count": len(t.fields),
        }
        for t in templates
    ]


@router.get("/{template_id}/fields")
def get_template_fields(template_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """Возвращает список полей шаблона — основа для будущей формы (этап 3)."""
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    return {
        "id": str(template.id),
        "name": template.name,
        "fields": [
            {"placeholder": f.placeholder, "maps_to": f.maps_to} for f in template.fields
        ],
    }


@router.post("/{template_id}/generate")
def generate_document(
    template_id: uuid.UUID,
    data: dict,
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Генерирует документ. В теле запроса — JSON {имя_метки: значение}.
    Возвращает готовый .docx на скачивание.

    На этапе 2 данные приходят прямо в запросе. На этапе 4 часть из них
    будет автоматически подставляться из справочника контрагентов.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    template_bytes = get_file(template.storage_key)
    result_bytes = render_document(template_bytes, data)

    import io
    filename = f"{template.name}_готовый.docx"
    return StreamingResponse(
        io.BytesIO(result_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="document.docx"'},
    )
