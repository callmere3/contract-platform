import { API, apiFetch, apiJson } from './client';

/**
 * Партнёры — справочник площадок и агрегаторов, от которых приходят деньги
 * (ML Finance, admin и director).
 *
 * У партнёра ОДНО ПОЛЕ — имя, поэтому и клиент такой короткий: список, завести,
 * переименовать, удалить. Всё остальное про площадку живёт в карточках
 * контрагентов и в самих отчётах.
 */

/** Список: { partners: [{id, name}], total, page, page_size }. */
export function listPartners({ q, page, pageSize } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (page) params.set('page', String(page));
  if (pageSize) params.set('page_size', String(pageSize));
  return apiJson(`${API}/partners?${params}`);
}

export function createPartner(name) {
  const body = new FormData();
  body.append('name', name);
  return apiJson(`${API}/partners`, { method: 'POST', body });
}

/** Переименовать — единственная правка, какая у партнёра есть. */
export function renamePartner(id, name) {
  const body = new FormData();
  body.append('name', name);
  return apiJson(`${API}/partners/${id}`, { method: 'PATCH', body });
}

export function deletePartner(id) {
  return apiJson(`${API}/partners/${id}`, { method: 'DELETE' });
}

export function importPartners(file) {
  const body = new FormData();
  body.append('file', file);
  return apiJson(`${API}/partners/import`, { method: 'POST', body });
}

/** Выгрузка в .xlsx. Blob, а не переход по ссылке: запрос требует токен. */
export async function exportPartners() {
  const r = await apiFetch(`${API}/partners/export`);
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}
