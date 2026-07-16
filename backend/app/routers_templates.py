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
    GET    /templates/maps-to-options   — допустимые значения maps_to (для UI)
    GET    /templates/{id}/fields       — какие поля нужно заполнить
                                           (?contragent_id=... — автоподстановка
                                           default'ов из карточки контрагента)
    PATCH  /templates/{id}/fields       — настроить источник значения (maps_to)
                                           для полей шаблона (ручной ввод /
                                           автоподстановка из контрагента)
    POST   /templates/{id}/generate     — сгенерировать документ
                                           (?format=docx|pdf, по умолчанию docx;
                                           ?contragent_id=... — только для истории
                                           генерации, на сам документ не влияет)
"""
import io
import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.audit import log_generation
from app.auth import get_current_user, require_role
from app.config import settings
from app.context_builder import build_context, find_missing_variables
from app.db import get_session
from app.generation import fix_tables_for_pdf, render_document, scan_placeholders
from app.models import Contragent, Template, TemplateField, TemplateFolder, User, folder_path
from app.roles import ADMIN, CAN_GENERATE
from app.storage import delete_file, get_file, put_file
from app.tags import (
    CONTRAGENT_MAPPED_FIELDS,
    CONTRAGENT_TYPES,
    CONTRACT_FAMILIES,
    COUNTRIES,
    normalize_maps_to,
    normalize_optional_tag,
)
from app.template_analysis import analyze_template, fields_to_dict

folders_router = APIRouter(prefix="/folders", tags=["folders"])
templates_router = APIRouter(prefix="/templates", tags=["templates"])


# =====================================================================
# ПАПКИ — навигация по дереву произвольной глубины
# =====================================================================

@folders_router.get("", dependencies=[Depends(get_current_user)])
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


@folders_router.post("", dependencies=[Depends(require_role(ADMIN))])
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


@folders_router.put("/{folder_id}", dependencies=[Depends(require_role(ADMIN))])
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

@templates_router.post("", dependencies=[Depends(require_role(ADMIN))])
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


@templates_router.put("/{template_id}/file", dependencies=[Depends(require_role(ADMIN))])
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

    Метки пересканируются заново: список template_fields пересобирается под
    обновлённую разметку, но maps_to уже существующих меток (настроенный
    через PATCH /templates/{id}/fields) сохраняется — переживает правку
    текста шаблона, а не сбрасывается на "Ручной ввод" (см. ниже). Новые
    метки, которых раньше не было, получают maps_to="manual". version
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

    # Метки пересканируются — но настроенный maps_to (см. PATCH
    # /templates/{id}/fields) должен пережить правку шаблона: если метка
    # 'inn' была привязана к contragent.reg_number, а в шаблоне просто
    # поправили формулировку абзаца рядом — 'inn' никуда не делась и
    # связь должна остаться, иначе автоподстановка молча слетит на
    # "Ручной ввод" при каждой правке текста договора, что тяжело заметить.
    old_maps_to = {f.placeholder: f.maps_to for f in template.fields}
    template.fields = [
        TemplateField(placeholder=p, maps_to=old_maps_to.get(p, "manual"))
        for p in placeholders
    ]
    template.version += 1

    db.add(template)
    db.commit()

    return {
        "id": str(template.id),
        "name": template.name,
        "version": template.version,
        "fields_found": placeholders,
    }


@templates_router.patch("/{template_id}", dependencies=[Depends(require_role(ADMIN))])
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


@templates_router.delete("/{template_id}", dependencies=[Depends(require_role(ADMIN))])
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


@templates_router.get("/maps-to-options", dependencies=[Depends(get_current_user)])
def get_maps_to_options() -> dict:
    """
    Список допустимых значений maps_to с человекочитаемыми подписями —
    для выпадающего списка "Источник значения" в модалке редактирования
    шаблона (см. PATCH /templates/{id}/fields). Единственный источник
    правды — CONTRAGENT_MAPPED_FIELDS в app/tags.py, чтобы подписи в UI
    не расходились с тем, что реально проверяет normalize_maps_to().

    Зарегистрирован ДО динамических /{template_id}/... маршрутов по той
    же причине, что и /contragents/import и /export (см. их докстринги) —
    хотя здесь коллизии по факту не случилось бы (другой HTTP-метод и
    другое число сегментов пути), порядок сохранён как общее правило для
    всех статических путей этого роутера, чтобы не полагаться на то, что
    в этот раз повезло.
    """
    return {
        "options": [{"value": "manual", "label": "Ручной ввод"}]
        + [{"value": v, "label": l} for v, l in CONTRAGENT_MAPPED_FIELDS.items()]
    }


@templates_router.patch("/{template_id}/fields", dependencies=[Depends(require_role(ADMIN))])
def update_template_fields(
    template_id: uuid.UUID,
    mapping: dict[str, str],
    db: Session = Depends(get_session),
) -> dict:
    """
    Настраивает источник значения (maps_to) для полей шаблона — один раз,
    при подготовке шаблона админом, а не на каждой генерации документа.

    mapping — {placeholder: maps_to}, напр. {"inn": "contragent.reg_number"}.
    Значения maps_to — см. app/tags.py: CONTRAGENT_MAPPED_FIELDS (плюс
    "manual" — обычный ручной ввод, значение по умолчанию для всех полей).

    Только для меток, которые РЕАЛЬНО есть в текущей разметке шаблона —
    опечатка в имени метки здесь тихо ничего не подставит при генерации
    (см. get_template_fields), поэтому лучше явно вернуть 404 сразу, чем
    дать админу настроить связь для несуществующего поля.

    Не проверяет доступность конкретного контрагентского атрибута для
    ЛЮБОГО контрагента — просто разрешает связь. Например, если контрагент
    "неполный" (без reg_number), поле с maps_to="contragent.reg_number"
    при генерации для НЕГО просто останется пустым — это ожидаемо, не
    ошибка настройки шаблона.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    fields_by_placeholder = {f.placeholder: f for f in template.fields}

    updated = []
    for placeholder, maps_to in mapping.items():
        field = fields_by_placeholder.get(placeholder)
        if field is None:
            raise HTTPException(
                status_code=404,
                detail=f"В шаблоне нет метки {placeholder!r} — нечего связывать",
            )
        field.maps_to = normalize_maps_to(maps_to)
        updated.append({"placeholder": placeholder, "maps_to": field.maps_to})

    db.commit()

    return {"template_id": str(template_id), "updated": updated}


def _resolve_contragent_value(maps_to: str, contragent: Contragent) -> str:
    """
    Достаёт значение из карточки контрагента для maps_to вида
    'contragent.<attr>' (кроме 'contragent.nickname' — см. отдельную
    обработку в get_template_fields, там несколько никнеймов, а не одно
    значение).

    Пустое/незаполненное поле карточки -> "" (пустая строка), а не None —
    так default просто останется пустым и работает как обычный
    незаполненный ручной ввод, а не падает на None.
    """
    if maps_to == "contragent.name":
        return contragent.name or ""
    if maps_to == "contragent.reg_number":
        return contragent.reg_number or ""
    if maps_to == "contragent.royalty_percent":
        # В БД это Numeric(5,2), поэтому str(Decimal("65.00")) даёт "65.00" —
        # а build_context при генерации требует ЦЕЛОЕ (int("65.00") падает,
        # см. _royalty_words в context_builder.py). Без нормализации здесь
        # автоподстановка ломала бы генерацию: форма выглядит заполненной,
        # а "Сформировать" отдаёт 400 на ровном месте.
        # Дробную часть отбрасываем только если она нулевая (65.00 -> "65");
        # 65.50 оставляем как есть — пусть лучше оператор увидит явную
        # ошибку, чем мы молча округлим процент в договоре.
        if contragent.royalty_percent is None:
            return ""
        value = contragent.royalty_percent
        return str(int(value)) if value == value.to_integral_value() else str(value)
    if maps_to == "contragent.contract_number":
        return contragent.contract_number or ""
    return ""


@templates_router.get("/{template_id}/fields", dependencies=[Depends(get_current_user)])
def get_template_fields(
    template_id: uuid.UUID,
    contragent_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_session),
) -> dict:
    """
    Описание полей формы: тип, группа, подпись, подсказка, источник
    значения (maps_to) и, если передан contragent_id — уже подставленный
    default из карточки контрагента для полей с автоподстановкой.

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
    НЕ вычисляемые, а обычные поля ввода (номер уже существующего договора) —
    см. LINKED_DOC_TYPES в template_analysis.py. Именно поэтому 'contract'
    здесь — хороший кандидат на maps_to="contragent.contract_number":
    номер уже есть в карточке контрагента, вводить его второй раз вручную
    для каждого Приложения/Акта не нужно.

    contragent_id — необязателен. Если передан:
      - каждому полю с настроенным maps_to (см. PATCH /templates/{id}/fields)
        подставляется default из соответствующего атрибута контрагента,
        если тот заполнен (пустой атрибут карточки — default остаётся как
        был, ничего не перезаписываем пустотой);
      - поле nickname с maps_to="contragent.nickname" вместо одного default
        получает список "nickname_options" — все никнеймы контрагента —
        для выпадающего списка на фронте (см. app/tags.py, коммент к
        CONTRAGENT_MAPPED_FIELDS про особый случай);
      - поле c_date, если у контрагента уже есть дата договора в карточке,
        получает её вместо сегодняшней и дополнительно помечается
        "locked": true (встроенное правило, не через maps_to — см. ниже
        в коде) — фронт делает его нередактируемым, аналогично тому, как
        уже блокируется "contract" у Приложения/Акта.

    Подставленный default — это ТОЛЬКО предзаполнение обычного
    редактируемого инпута (как и все остальные default'ы в этой форме,
    см. DEFAULT_VALUES/TODAY_DEFAULT_FIELDS в template_analysis.py) —
    оператор может поправить перед генерацией, backend при самой
    генерации (POST .../generate) это никак не проверяет и не
    перезаписывает: единственный источник истины для сгенерированного
    документа — то, что реально пришло в теле запроса на генерацию.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    docx_bytes = get_file(template.storage_key)
    form_fields = fields_to_dict(
        analyze_template(docx_bytes, doc_type=template.doc_type),
        doc_type=template.doc_type,
    )

    maps_to_by_placeholder = {f.placeholder: f.maps_to for f in template.fields}

    contragent = None
    if contragent_id is not None:
        contragent = db.get(Contragent, contragent_id)
        if contragent is None:
            raise HTTPException(status_code=404, detail="Контрагент не найден")

    for item in form_fields:
        maps_to = maps_to_by_placeholder.get(item["name"], "manual")
        item["maps_to"] = maps_to

        # c_date по умолчанию — сегодня (TODAY_DEFAULT_FIELDS в
        # fields_to_dict), но если у контрагента в карточке уже есть дата
        # договора — комбинированный Договор для него уже существует и
        # дата уже зафиксирована (см. докстринг Contragent.contract_date
        # в models.py: "фиксируется один раз... номер в шапке и дата в
        # преамбуле никогда не разъедутся"). Поэтому поле не просто
        # предзаполняется, а БЛОКИРУЕТСЯ для правки — та же логика, что
        # уже применяется к "contract" (номер договора) у Приложения/Акта
        # чуть ниже (maps_to="contragent.contract_number"), только здесь
        # это встроенное правило, а не настраиваемый maps_to: contract_date
        # не входит в CONTRAGENT_MAPPED_FIELDS (app/tags.py) специально —
        # это не то поле, которое admin может переназначить на другой атрибут.
        if item["name"] == "c_date" and contragent is not None and contragent.contract_date:
            item["default"] = contragent.contract_date.isoformat()
            item["locked"] = True
            item["hint"] = "Дата зафиксирована в карточке контрагента и не редактируется здесь."

        if contragent is None or maps_to == "manual":
            continue

        if maps_to == "contragent.nickname":
            options = [n.nickname for n in contragent.nicknames]
            item["nickname_options"] = options
            if len(options) == 1:
                item["default"] = options[0]
            continue

        value = _resolve_contragent_value(maps_to, contragent)
        if value:
            item["default"] = value

    return {
        "id": str(template.id),
        "name": template.name,
        "doc_type": template.doc_type,
        "path": folder_path(template.folder),
        "fields": form_fields,
    }


def build_document_response(template: Template, data: dict, format: str) -> StreamingResponse:
    """
    Общее ядро рендера — валидация + docxtpl + (для pdf) конвертация.
    Переиспользуется в /generate (шаг 1) и /generation-history/{id}/recreate
    (пересоздание по сохранённому payload, см. app/routers_generation_history.py).

    Специально НЕ пишет ничего в generated_documents — это ответственность
    вызывающей стороны: пересоздание уже существующей записи истории не
    должно плодить новую (иначе "кто сгенерировал" исказится на того, кто
    просто посмотрел документ повторно).
    """
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


@templates_router.post("/{template_id}/generate", dependencies=[Depends(require_role(*CAN_GENERATE))])
def generate_document(
    template_id: uuid.UUID,
    data: dict,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    contragent_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
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

    contragent_id — необязателен (из "Папок" документ генерируют без
    привязки к контрагенту, см. DocFormPage) и, как и в GET .../fields,
    рендеринг никак не затрагивает — используется только для истории
    генерации (см. GeneratedDocument): какой контрагент показывать в
    списке. Источник истины для самого документа — по-прежнему только
    тело запроса (см. брейншторм про maps_to).
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    response = build_document_response(template, data, format)

    contragent_title = None
    if contragent_id is not None:
        contragent = db.get(Contragent, contragent_id)
        contragent_title = contragent.title if contragent is not None else None

    # nickname — тот же ключ формы, что и в build_context()/optional-полях
    # выше: конкретный псевдоним, для которого сгенерирован ИМЕННО этот
    # документ (у контрагента их может быть несколько, см. GeneratedDocument).
    nickname = data.get("nickname") or None

    log_generation(
        db, current_user, template.id, template.name, format, data,
        contragent_id=contragent_id, contragent_title=contragent_title, nickname=nickname,
    )

    return response
