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
from app.tags import CONTRAGENT_TYPES, CONTRACT_FAMILIES, COUNTRIES, REG_NUMBER_META

tags_router = APIRouter(prefix="/tags", tags=["tags"])


@tags_router.get("", dependencies=[Depends(get_current_user)])
def get_tags() -> dict:
    return {
        "countries": COUNTRIES,
        "contragent_types": CONTRAGENT_TYPES,
        "contract_families": CONTRACT_FAMILIES,
        # {"СГ": {"label": "ИНН", "length": 12}, ...} — фронтенд подставляет
        # правильную подпись и длину под уже выбранный тип контрагента,
        # не хардкодя это отдельно.
        "reg_number_meta": {
            k: {"label": label, "length": length} for k, (label, length) in REG_NUMBER_META.items()
        },
        # Список ролей для селекта на вкладке "Пользователи" — из того же
        # единственного источника правды (app/roles.py: ROLES), которым
        # валидируется роль при создании/правке пользователя.
        "roles": list(ROLES),
    }
