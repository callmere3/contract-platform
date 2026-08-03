/**
 * Фильтрация списка типов контрагента под выбранную страну.
 *
 * Орг.форма компании зависит от страны: РУ → ООО, КЗ → ТОО. Связка приходит
 * с сервера (GET /tags: company_type_by_country), фронт её не хардкодит —
 * здесь только применяем к списку типов, чтобы для КЗ предлагался ТОО, а не
 * ООО, и наоборот. Физлица (ФЛ/СГ/ИП) от страны не зависят — остаются всегда.
 *
 * Пока страна не выбрана (или связка ещё не загрузилась) — показываем все
 * типы: скрывать нечего, а пустой селект хуже полного.
 */
export function typesForCountry(allTypes, country, companyTypeByCountry) {
  if (!country || !companyTypeByCountry) return allTypes;
  const companyTypes = Object.values(companyTypeByCountry); // ['ООО', 'ТОО']
  const allowedCompany = companyTypeByCountry[country];
  // Оставляем тип, если он НЕ орг.форма компании (физлицо — всегда),
  // либо это орг.форма именно этой страны.
  return allTypes.filter((t) => !companyTypes.includes(t) || t === allowedCompany);
}

/** true, если тип — орг.форма компании (ООО/ТОО), а не физлицо (ФЛ/СГ/ИП). */
export function isCompanyType(type, companyTypeByCountry) {
  const companyTypes = companyTypeByCountry ? Object.values(companyTypeByCountry) : ['ООО', 'ТОО'];
  return companyTypes.includes(type);
}

/**
 * Подпись поля name под тип контрагента: у компаний это НАЗВАНИЕ организации,
 * у физлиц — ФИО. Зеркало field_meta_for на бэкенде (форма генерации), чтобы
 * карточка и модалки контрагента называли поле так же.
 */
export function contragentNameLabel(type, companyTypeByCountry) {
  return isCompanyType(type, companyTypeByCountry) ? 'Название компании' : 'ФИО / название';
}
