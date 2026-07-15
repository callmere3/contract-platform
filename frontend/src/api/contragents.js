import { API, apiFetch, apiJson } from './client';

/**
 * Вызовы к /contragents. Здесь только транспорт — никакой бизнес-логики и
 * никаких проверок прав: права проверяет сервер (require_role), а UI прячет
 * кнопки через src/auth/permissions.js.
 *
 * Бэкенд принимает контрагентов как form-data (Form(...) в роутере), а не
 * JSON — поэтому везде URLSearchParams, а не JSON.stringify.
 */

/** Поиск: q + необязательные фильтры country/contragent_type. Без параметров — весь список (лимит 200). */
export function searchContragents({ q, country, contragentType } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (country) params.set('country', country);
  if (contragentType) params.set('contragent_type', contragentType);
  const qs = params.toString();
  return apiJson(`${API}/contragents${qs ? `?${qs}` : ''}`);
}

/** Полная карточка: все поля + никнеймы (в списке поиска их нет). */
export function getContragent(id) {
  return apiJson(`${API}/contragents/${id}`);
}

/** Документы (шаблоны), подходящие контрагенту по его тегам country/type/contract_family. */
export function getContragentTemplates(id) {
  return apiJson(`${API}/contragents/${id}/templates`);
}

/**
 * Создание. title и contract_number вычисляет сервер — их не передаём
 * (см. докстринг create_contragent на бэкенде).
 * Пустые reg_number/nicknames не отправляем вовсе: сервер отличает
 * "не передано" от "передано пустым".
 */
export function createContragent({
  name,
  country,
  contragentType,
  contractFamily,
  contractDate,
  royaltyPercent,
  regNumber,
  nicknames,
}) {
  const body = new URLSearchParams({
    name,
    country,
    contragent_type: contragentType,
    contract_family: contractFamily,
    contract_date: contractDate,
    royalty_percent: String(royaltyPercent),
  });
  if (nicknames) body.append('nicknames', nicknames);
  if (regNumber) body.append('reg_number', regNumber);
  return apiJson(`${API}/contragents`, { method: 'POST', body });
}

/**
 * Правка карточки (PATCH). Отправляем ТОЛЬКО изменённые поля: сервер
 * трактует отсутствие поля как "не трогать", а пустую строку — как
 * "очистить" (см. update_contragent). Поэтому fields собирается вызывающим
 * кодом уже отфильтрованным.
 */
export function updateContragent(id, fields) {
  const body = new URLSearchParams();
  Object.entries(fields).forEach(([k, v]) => {
    if (v !== undefined) body.append(k, v === null ? '' : String(v));
  });
  return apiJson(`${API}/contragents/${id}`, { method: 'PATCH', body });
}

export function deleteContragent(id) {
  return apiJson(`${API}/contragents/${id}`, { method: 'DELETE' });
}

/** Импорт из Excel (только admin). Возвращает отчёт {created, updated, skipped, details}. */
export function importContragents(file) {
  const fd = new FormData();
  fd.append('file', file);
  return apiJson(`${API}/contragents/import`, { method: 'POST', body: fd });
}

/**
 * Экспорт в Excel (admin+director). Возвращает Blob, а не JSON —
 * поэтому идём через apiFetch напрямую, минуя apiJson.
 */
export async function exportContragents() {
  const r = await apiFetch(`${API}/contragents/export`);
  if (!r.ok) throw new Error(`Не удалось выгрузить файл (${r.status})`);
  return r.blob();
}
