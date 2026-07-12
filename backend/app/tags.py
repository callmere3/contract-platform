"""
Канонические значения тегов страна / тип контрагента / тип договора.

Используются и контрагентами (contragents.country/type/contract_family), и
шаблонами (templates.country/contragent_type/contract_family) — подбор
документов по контрагенту (шаг 4 брейншторма) сравнивает эти поля НАПРЯМУЮ,
без ILIKE. Поэтому критично, чтобы значения всегда приходили в одном и том
же регистре и написании, а не как их напечатал оператор ('ру' vs 'РУ').

COUNTRIES / CONTRAGENT_TYPES / CONTRACT_FAMILIES — единственный источник
правды для обоих мест; при добавлении нового значения (например, нового
типа договора) достаточно дополнить список здесь.
"""
from fastapi import HTTPException

COUNTRIES = ["РУ", "КЗ"]
CONTRAGENT_TYPES = ["СГ", "ИП", "ООО"]
CONTRACT_FAMILIES = ["РОЯЛТИ", "АВАНС", "АВАНС_ОБЯЗАТЕЛЬСТВО"]


def normalize_tag(value: str, allowed: list[str], field_name: str) -> str:
    """
    Приводит value к канонической форме из allowed, сравнивая без учёта
    регистра (оператор мог напечатать 'ру' вместо 'РУ' — так и произошло
    при первом ручном тесте через Swagger).

    Бросает HTTPException(400), если значения нет среди допустимых — лучше
    явная ошибка сразу при создании, чем тег, который потом молча не
    совпадёт при подборе документов (шаг 4) и документы просто не найдутся
    без объяснения причины.
    """
    stripped = (value or "").strip()
    for canonical in allowed:
        if stripped.casefold() == canonical.casefold():
            return canonical
    raise HTTPException(
        status_code=400,
        detail=(
            f"Недопустимое значение поля {field_name}: {value!r}. "
            f"Допустимые значения: {', '.join(allowed)}"
        ),
    )


def normalize_optional_tag(value: str | None, allowed: list[str], field_name: str) -> str | None:
    """
    Как normalize_tag(), но для полей, которые законно бывают пустыми —
    теги на Template можно дозаполнить позже (см. models.py: "8 текущих
    шаблонов дозаполняются тегами вручную ПОСЛЕ миграции"), в отличие от
    полей контрагента, где все три тега обязательны при создании через UI.

    Пустая строка или None -> None (тег не задан). Непустое значение,
    которого нет в allowed, -> та же явная ошибка 400, что и в normalize_tag.
    """
    if not value or not value.strip():
        return None
    return normalize_tag(value, allowed, field_name)
