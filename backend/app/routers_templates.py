"""
Эндпоинты работы с шаблонами и деревом папок.

Всё проверяется через Swagger UI (http://<сервер>:8000/docs).

  Папки:
    GET  /folders?parent_id=          — содержимое папки: подпапки + шаблоны
                                         (parent_id не передан = корень)
    POST /folders                     — создать папку (name, parent_id)
    PUT  /folders/{id}                — переименовать папку (name)

  Шаблоны:
    POST   /templates                   — загрузить НОВЫЙ шаблон в папку
    PUT    /templates/{id}/file         — заменить файл у СУЩЕСТВУЮЩЕГО шаблона
    PATCH  /templates/{id}               — переименовать шаблон (только name)
    DELETE /templates/{id}              — удалить шаблон (файл + запись в БД)
    GET    /templates/{id}/fields       — какие поля нужно заполнить
    POST   /templates/{id}/generate     — сгенерировать документ
                                           (?format=docx|pdf, по умолчанию docx)
"""
import io
import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.context_builder import build_context, find_missing_variables
from app.db import get_session
from app.generation import fix_tables_for_pdf, render_document, scan_placeholders
from app.models import Template, TemplateField, TemplateFolder, folder_path
from app.storage import delete_file, get_file, put_file
from app.tags import CONTRAGENT_TYPES, CONTRACT_FAMILIES, COUNTRIES, normalize_optional_tag
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
            {
                "id": str(t.id),
                "name": t.name,
                "doc_type": t.doc_type,
                "country": t.country,
                "contragent_type": t.contragent_type,
                "contract_family": t.contract_family,
            }
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


@folders_router.put("/{folder_id}")
def rename_folder(
    folder_id: uuid.UUID,
    name: str = Form(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Переименовывает папку. Только смена name — id, parent_id, содержимое
    (подпапки, шаблоны) не трогаются.

    Безопасно в любой момент: storage_key шаблонов не зависит от пути
    в дереве папок (см. models.py), так что переименование папки не
    требует переноса файлов в MinIO — просто меняется одна колонка.
    """
    folder = db.get(TemplateFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Папка не найдена")
    folder.name = name
    db.commit()
    return {"id": str(folder.id), "name": folder.name}


# =====================================================================
# ШАБЛОНЫ
# =====================================================================

@templates_router.post("")
def upload_template(
    name: str = Form(...),
    folder_id: uuid.UUID = Form(...),
    doc_type: str | None = Form(None),   # 'contract' | 'appendix' | 'act' | None
    country: str | None = Form(None),           # 'РУ' | 'КЗ'
    contragent_type: str | None = Form(None),   # 'СГ' | 'ИП' | 'ООО'
    contract_family: str | None = Form(None),   # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Загружает шаблон в указанную папку, сканирует метки.

    country/contragent_type/contract_family — теги для подбора документов
    через контрагента (см. GET /contragents/{id}/templates). Необязательны
    здесь же при загрузке (можно дозаполнить позже через PATCH) — но если
    переданы, валидируются и нормализуются к каноническому регистру
    (см. app/tags.py), иначе 400 с понятной ошибкой сразу при загрузке,
    а не тихое несовпадение при подборе документов позже.
    """
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Ожидается файл .docx")

    if db.get(TemplateFolder, folder_id) is None:
        raise HTTPException(status_code=404, detail="Папка не найдена")

    country = normalize_optional_tag(country, COUNTRIES, "country")
    contragent_type = normalize_optional_tag(contragent_type, CONTRAGENT_TYPES, "contragent_type")
    contract_family = normalize_optional_tag(contract_family, CONTRACT_FAMILIES, "contract_family")

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
        country=country,
        contragent_type=contragent_type,
        contract_family=contract_family,
    )
    template.fields = [TemplateField(placeholder=p, maps_to="manual") for p in placeholders]

    db.add(template)
    db.commit()

    return {
        "id": str(template_id),
        "name": name,
        "doc_type": doc_type,
        "country": country,
        "contragent_type": contragent_type,
        "contract_family": contract_family,
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


@templates_router.patch("/{template_id}")
def update_template(
    template_id: uuid.UUID,
    name: str = Form(...),
    country: str | None = Form(None),
    contragent_type: str | None = Form(None),
    contract_family: str | None = Form(None),
    db: Session = Depends(get_session),
) -> dict:
    """
    Обновляет метаданные шаблона: название и/или теги подбора документов.
    id, folder_id, doc_type, storage_key, version, template_fields не трогает.

    PATCH, а не PUT: PUT /templates/{id}/file уже занят под замену файла
    (другая семантика — там меняется содержимое, тут только метаданные).

    Семантика тегов — "если поле передано, значит его и правим":
      - параметр НЕ передан в форме (Form(None) -> None)  -> не трогаем,
        значение в БД остаётся прежним;
      - передана пустая строка                             -> тег очищается
        (снова None) — способ явно снять уже проставленный тег;
      - передано непустое значение                          -> валидируется
        и нормализуется (см. app/tags.py), 400 при недопустимом значении.
    Так один и тот же вызов годится и для простого переименования (только
    name), и для дозаполнения/правки тегов у уже загруженного шаблона —
    включая исходные 8 шаблонов, которым теги проставлялись вручную через
    SQL при миграции.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    template.name = name
    if country is not None:
        template.country = normalize_optional_tag(country, COUNTRIES, "country")
    if contragent_type is not None:
        template.contragent_type = normalize_optional_tag(
            contragent_type, CONTRAGENT_TYPES, "contragent_type"
        )
    if contract_family is not None:
        template.contract_family = normalize_optional_tag(
            contract_family, CONTRACT_FAMILIES, "contract_family"
        )

    db.commit()
    return {
        "id": str(template.id),
        "name": template.name,
        "country": template.country,
        "contragent_type": template.contragent_type,
        "contract_family": template.contract_family,
    }


@templates_router.delete("/{template_id}")
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Удаляет шаблон: файл из MinIO по storage_key + запись в БД. Связанные
    template_fields удаляются каскадно (см. cascade="all, delete-orphan"
    в models.py). Папку, где лежал шаблон, не трогает — удаляется только
    сам шаблон, соседние шаблоны и подпапки не затрагиваются.

    Пока нет таблицы generated_documents (появится на этапе 5-6), нет и
    проверки «а не генерировали ли из этого шаблона документы» — когда
    она появится, здесь нужно будет решить, что делать со старыми
    ссылками (например, запрещать удаление или предупреждать).
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    delete_file(template.storage_key)
    db.delete(template)
    db.commit()

    return {"id": str(template_id), "deleted": True}


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

    Для отдельных Приложения/Акта (template.doc_type) contract и date —
    НЕ вычисляемые, а обычные поля ввода (номер и дата уже существующего
    договора вводятся вручную, пока нет базы контрагентов) — см.
    LINKED_DOC_TYPES в template_analysis.py.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    docx_bytes = get_file(template.storage_key)
    form_fields = fields_to_dict(
        analyze_template(docx_bytes, doc_type=template.doc_type),
        doc_type=template.doc_type,
    )

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
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Генерирует документ по данным формы. format=docx (по умолчанию) или
    format=pdf — во втором случае готовый docx дополнительно прогоняется
    через отдельный сервис-конвертер (LibreOffice headless, см. converter/),
    сам docx при этом нигде не сохраняется отдельно — PDF получают "на
    лету", один запрос — один результат.

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
        context = build_context(data, doc_type=template.doc_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # флаги приходят из формы как есть — build_context их не трогает
    template_vars = set(scan_placeholders(docx_bytes))

    # Необязательные метки: законно бывают пустыми.
    # nickname — если у контрагента нет псевдонима (условие его скроет)
    # release_* — если релиз это сингл
    optional = {"nickname", "release_label", "release_name", "release_year"}
    # smm/smm_text (сумма на SMM, п.2.1.2 в СГ_аванс) печатаются только
    # под {%p if marketing %} — если чекбокс «Маркетинговая кампания» не
    # нажат, весь пункт в документ не попадает, и поле не должно
    # требоваться. Если нажат — сумма обязательна, как и раньше.
    if not context.get("marketing"):
        optional = optional | {"smm", "smm_text"}
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

    if format == "docx":
        return StreamingResponse(
            io.BytesIO(result_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="document.docx"'},
        )

    # format == "pdf" — отдаём docx на конвертацию отдельному сервису.
    # fix_tables_for_pdf() чинит известный баг LibreOffice-конвертации:
    # если суммарная ширина столбцов таблицы (треки/исполнители/клипы)
    # больше печатной ширины страницы, LibreOffice сжимает столбцы
    # непропорционально (текст может схлопнуться до одной буквы на
    # строку), тогда как Word такое переполнение просто визуально терпит.
    # На .docx-версию (ветка выше) это не влияет — там и так всё корректно.
    try:
        pdf_source_bytes = fix_tables_for_pdf(result_bytes)
    except Exception:
        # Если чинилка упала на каком-то нестандартном шаблоне — лучше
        # отдать PDF с потенциально кривой таблицей, чем не отдать вообще
        # ничего. Точечно эту ошибку не проглатываем молча: имеет смысл
        # смотреть логи api, если это начнёт происходить часто.
        pdf_source_bytes = result_bytes

    # Таймаут больше, чем у самого soffice внутри converter (60с) — с
    # запасом на сетевые накладные расходы внутри docker-сети, не потому
    # что конвертация реально может идти дольше.
    try:
        response = httpx.post(
            f"{settings.converter_url}/convert",
            files={"file": ("document.docx", pdf_source_bytes,
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            timeout=70,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Сервис конвертации в PDF недоступен: {exc}",
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось сконвертировать документ в PDF: {response.text[:300]}",
        )

    return StreamingResponse(
        io.BytesIO(response.content),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="document.pdf"'},
    )
