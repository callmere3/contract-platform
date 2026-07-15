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

# Единый рег. номер контрагента (contragents.reg_number) — смысл и ожидаемая
# длина зависят от типа контрагента: ИНН физлица (СГ) — 12 цифр, ОГРНИП —
# 15, ОГРН — 13. Одна и та же колонка в БД для всех трёх (см. models.py,
# докстринг Contragent) — это словарь для подписи в UI и для валидации
# длины, а не отдельные поля.
REG_NUMBER_META = {
    "СГ": ("ИНН", 12),
    "ИП": ("ОГРНИП", 15),
    "ООО": ("ОГРН", 13),
}


def normalize_reg_number(value: str | None, contragent_type: str | None) -> str | None:
    """
    Приводит рег. номер к строке только из цифр и проверяет длину,
    ожидаемую для данного типа контрагента (см. REG_NUMBER_META).

    contragent_type может быть None (напр. тип ещё не выбран/не заполнен
    при "неполном" импорте) — тогда проверяется только "только цифры",
    без проверки длины: не с чем сверять.

    Пустая строка/None -> None (поле не задано, контрагент "неполный").
    """
    if value is None or not value.strip():
        return None
    digits = value.strip()
    if not digits.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"Рег. номер должен состоять только из цифр: {value!r}",
        )
    if contragent_type and contragent_type in REG_NUMBER_META:
        label, length = REG_NUMBER_META[contragent_type]
        if len(digits) != length:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{label} для типа {contragent_type} должен содержать "
                    f"{length} цифр, получено {len(digits)}: {value!r}"
                ),
            )
    return digits


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
