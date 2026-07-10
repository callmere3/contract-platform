"""
Эндпоинты работы с шаблонами и деревом папок.

Всё проверяется через Swagger UI (http://<сервер>:8000/docs).

  Папки:
    GET  /folders?parent_id=          — содержимое папки: подпапки + шаблоны
                                         (parent_id не передан = корень)
    POST /folders                     — создать папку (name, parent_id)

  Шаблоны:
    POST /templates                   — загрузить НОВЫЙ шаблон в папку
    PUT  /templates/{id}/file         — заменить файл у СУЩЕСТВУЮЩЕГО шаблона
    GET  /templates/{id}/fields       — какие поля нужно заполнить
    POST /templates/{id}/generate     — сгенерировать документ
"""
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.context_builder import build_context, find_missing_variables
from app.db import get_session
from app.generation import render_document, scan_placeholders
from app.models import Template, TemplateField, TemplateFolder, folder_path
from app.storage import get_file, put_file
from app.template_analysis import analyze_template, fields_to_dict

folders_router = APIRouter(prefix="/folders", tags=["folders"])
templates_router = APIRouter(prefix="/templates", tags=["templates"])


# =====================================================================
# ПАПКИ — навигация по дереву произвольной глубины
# =====================================================================

@folders_router.get("")
def browse_folder(
    parent_id: uuid.UUID | None = None,
    db: Session = Depends(get_session),
) -> dict:
    """
    Содержимое папки: список подпапок и список шаблонов в ней.
    Без parent_id — содержимое корня (напр. РУ / КЗ).

    Фронтенд вызывает это на каждый клик по папке — так строится
    навигация любой глубины без знания структуры заранее.
    """
    subfolders = (
        db.query(TemplateFolder)
        .filter(TemplateFolder.parent_id == parent_id)
        .order_by(TemplateFolder.name)
        .all()
    )
    templates = (
        db.query(Template)
        .filter(Template.folder_id == parent_id)
        .order_by(Template.name)
        .all()
        if parent_id is not None
        else []
        # у шаблонов в корне быть не должно, но проверка не помешает
    )

    breadcrumb = []
    if parent_id is not None:
        current = db.get(TemplateFolder, parent_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Папка не найдена")
        breadcrumb = folder_path(current)

    return {
        "breadcrumb": breadcrumb,
        "folders": [{"id": str(f.id), "name": f.name} for f in subfolders],
        "templates": [
            {"id": str(t.id), "name": t.name, "doc_type": t.doc_type}
            for t in templates
        ],
    }


@folders_router.post("")
def create_folder(
    name: str = Form(...),
    parent_id: uuid.UUID | None = Form(None),
    db: Session = Depends(get_session),
) -> dict:
    """Создаёт папку. parent_id не задан — папка верхнего уровня."""
    folder = TemplateFolder(name=name, parent_id=parent_id)
    db.add(folder)
    db.commit()
    return {"id": str(folder.id), "name": name, "parent_id": str(parent_id) if parent_id else None}


# =====================================================================
# ШАБЛОНЫ
# =====================================================================

@templates_router.post("")
def upload_template(
    name: str = Form(...),
    folder_id: uuid.UUID = Form(...),
    doc_type: str | None = Form(None),   # 'contract' | 'appendix' | 'act' | None
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """Загружает шаблон в указанную папку, сканирует метки."""
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Ожидается файл .docx")

    if db.get(TemplateFolder, folder_id) is None:
        raise HTTPException(status_code=404, detail="Папка не найдена")

    content = file.file.read()

    try:
        placeholders = scan_placeholders(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать шаблон: {exc}")

    template_id = uuid.uuid4()
    # ключ в MinIO НЕ зависит от пути в дереве папок — так переименование
    # или перенос папки не требует переноса файла в хранилище
    storage_key = f"templates/{template_id}.docx"
    put_file(storage_key, content)

    template = Template(
        id=template_id,
        name=name,
        storage_key=storage_key,
        folder_id=folder_id,
        doc_type=doc_type,
    )
    template.fields = [TemplateField(placeholder=p, maps_to="manual") for p in placeholders]

    db.add(template)
    db.commit()

    return {
        "id": str(template_id),
        "name": name,
        "doc_type": doc_type,
        "fields_found": placeholders,
    }


@templates_router.put("/{template_id}/file")
def replace_template_file(
    template_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Заменяет docx-файл у СУЩЕСТВУЮЩЕГО шаблона, не создавая новый.

    Используется, когда в шаблон внесли правки (поправили формулировку,
    добавили метку) и нужно обновить его на сервере — id, папка, doc_type
    и все ссылки на него (напр. из истории сгенерированных документов
    на будущих этапах) остаются прежними.

    storage_key строится из template_id и поэтому не меняется — новый
    файл просто перезаписывает старый по тому же пути в MinIO, старый
    файл нигде не остаётся.

    Метки пересканируются заново: старые template_fields удаляются,
    вместо них создаются новые под обновлённую разметку. version
    увеличивается — пригодится, если понадобится история изменений.
    """
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Ожидается файл .docx")

    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    content = file.file.read()

    try:
        placeholders = scan_placeholders(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать шаблон: {exc}")

    # тот же storage_key, что и был — файл в MinIO перезаписывается на месте
    put_file(template.storage_key, content)

    # старые метки больше не актуальны — пересобираем список заново
    template.fields = [TemplateField(placeholder=p, maps_to="manual") for p in placeholders]
    template.version += 1

    db.add(template)
    db.commit()

    return {
        "id": str(template.id),
        "name": template.name,
        "version": template.version,
        "fields_found": placeholders,
    }


@templates_router.get("/{template_id}/fields")
def get_template_fields(template_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Описание полей формы: тип, группа, подпись, подсказка.

    Типы анализируются прямо из разметки шаблона (см. template_analysis),
    поэтому форма перестраивается сама при изменении шаблона:
      list   — таблица с добавлением строк (треки, клипы, исполнители)
      flag   — галочка (edo, has_videoclip)
      choice — выпадающий список (release_type)
      text   — обычное поле ввода

    Вычисляемые метки (contract, profanity_note, term_end...) не показываются —
    их считает context_builder. Вместо них добавлены виртуальные поля, из
    которых эти значения собираются (день/месяц договора, список исполнителей).
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    docx_bytes = get_file(template.storage_key)
    form_fields = fields_to_dict(analyze_template(docx_bytes))

    return {
        "id": str(template.id),
        "name": template.name,
        "doc_type": template.doc_type,
        "path": folder_path(template.folder),
        "fields": form_fields,
    }


@templates_router.post("/{template_id}/generate")
def generate_document(
    template_id: uuid.UUID,
    data: dict,
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Генерирует документ по данным формы.

    Тело запроса — «сырые» данные формы. Они проходят через build_context(),
    который добавляет вычисляемые поля: номер договора собирается из
    дня/месяца и инициалов ФИО, сноски — из галочек НЛ и списка исполнителей.

    Перед рендерингом проверяем, что все метки шаблона заполнены, иначе
    docxtpl молча подставит пустые строки и в договоре будет
    «Дата рождения: » без значения.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    docx_bytes = get_file(template.storage_key)

    try:
        context = build_context(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # флаги приходят из формы как есть — build_context их не трогает
    template_vars = set(scan_placeholders(docx_bytes))

    # Необязательные метки: законно бывают пустыми.
    # nickname — если у контрагента нет псевдонима (условие его скроет)
    # release_* — если релиз это сингл
    optional = {"nickname", "release_label", "release_name", "release_year"}
    missing = [
        m for m in find_missing_variables(template_vars, context)
        if m not in optional
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Не заполнены обязательные поля: {', '.join(missing)}",
        )

    result_bytes = render_document(docx_bytes, context)

    return StreamingResponse(
        io.BytesIO(result_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="document.docx"'},
    )
