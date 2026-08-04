"""
GET /tags — отдаёт допустимые значения тегов (country/contragent_type/
contract_family) и метаданные рег. номера (reg_number_meta) из единственного
источника правды (app/tags.py).

Нужен, чтобы фронтенд (селекты в модалках загрузки/редактирования шаблона,
форма создания контрагента) не хранил список значений отдельной копией и
не расходился с тем, что реально валидирует бэкенд при сохранении.
"""
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.roles import ROLES
from app.tags import (
    COMPANY_TYPE_BY_COUNTRY,
    CONTRAGENT_TYPES,
    CONTRACT_FAMILIES,
    COUNTRIES,
    OBLIGATION_BUCKETS,
    REG_NUMBER_META,
    REQUISITE_FIELDS_BY_TYPE,
)
from app.template_analysis import requisite_field_descriptors

tags_router = APIRouter(prefix="/tags", tags=["tags"])


@tags_router.get("", dependencies=[Depends(get_current_user)])
def get_tags() -> dict:
    return {
        "countries": COUNTRIES,
        "contragent_types": CONTRAGENT_TYPES,
        "contract_families": CONTRACT_FAMILIES,
        # Бакеты обязательства для приложений/актов — у них тег не семейство,
        # а «БЕЗ_ОБЯЗАТЕЛЬСТВА»/«ОБЯЗАТЕЛЬСТВО» (см. app/tags.py). Модалка
        # шаблона показывает их вместо семейств, когда тип документа —
        # приложение или акт.
        "obligation_buckets": OBLIGATION_BUCKETS,
        # {"СГ": {"label": "ИНН", "length": 12}, ...} — фронтенд подставляет
        # правильную подпись и длину под уже выбранный тип контрагента,
        # не хардкодя это отдельно.
        "reg_number_meta": {
            k: {"label": label, "length": length} for k, (label, length) in REG_NUMBER_META.items()
        },
        # {"РУ": "ООО", "КЗ": "ТОО"} — фронт фильтрует список типов под
        # выбранную страну (для КЗ предлагает ТОО, а не ООО), не хардкодя
        # связку у себя. См. COMPANY_TYPE_BY_COUNTRY в app/tags.py.
        "company_type_by_country": COMPANY_TYPE_BY_COUNTRY,
        # Список ролей для селекта на вкладке "Пользователи" — из того же
        # единственного источника правды (app/roles.py: ROLES), которым
        # валидируется роль при создании/правке пользователя.
        "roles": list(ROLES),
        # Поля реквизитов карточки по типу контрагента: {тип: [{name, type,
        # label, hint, choices?}]}. Фронт рисует по ним сворачиваемый блок
        # реквизитов в карточке — набор и подписи не хардкодит. Ключи значений
        # (Contragent.requisites) — те же name. См. REQUISITE_FIELDS_BY_TYPE и
        # requisite_field_descriptors.
        "requisite_fields_by_type": {
            t: requisite_field_descriptors(t) for t in REQUISITE_FIELDS_BY_TYPE
        },
    }
