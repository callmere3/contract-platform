"""
GET /tags — отдаёт допустимые значения тегов (country/contragent_type/
contract_family) из единственного источника правды (app/tags.py).

Нужен, чтобы фронтенд (селекты в модалках загрузки/редактирования шаблона)
не хранил список значений отдельной копией и не расходился с тем, что
реально валидирует бэкенд при сохранении.
"""
from fastapi import APIRouter

from app.tags import CONTRAGENT_TYPES, CONTRACT_FAMILIES, COUNTRIES

tags_router = APIRouter(prefix="/tags", tags=["tags"])


@tags_router.get("")
def get_tags() -> dict:
    return {
        "countries": COUNTRIES,
        "contragent_types": CONTRAGENT_TYPES,
        "contract_families": CONTRACT_FAMILIES,
    }
