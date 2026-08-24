import { API, apiFetch, apiJson, filenameFromResponse } from './client';

/**
 * Вызовы вкладки «Dista Connect» (сверка нашей базы с выгрузкой Dista Music).
 * Только транспорт; права проверяет сервер (require_role(ADMIN)).
 *
 * reconcile: загрузка .xlsx выгрузки Dista (колонки id + Название).
 *   commit=false — превью (сервер ничего не пишет, только считает план);
 *   commit=true  — применить (проставить dista_id совпавшим, создать новых).
 * Возвращает {committed, counts, applied, link, create, ambiguous, only_ours, skipped}.
 */
export function distaReconcile(file, commit = false) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('commit', commit ? 'true' : 'false');
  return apiJson(`${API}/dista/reconcile`, { method: 'POST', body: fd });
}

/** Сводка связки: {total, linked, excluded, unlinked}. */
export function distaStatus() {
  return apiJson(`${API}/dista/status`);
}

/** Списки карточек без dista_id: {pending: [...], excluded: [...]}. */
export function distaOnlyOurs() {
  return apiJson(`${API}/dista/only-ours`);
}

/** Пометить карточку «не заводить в Dista» (excluded=true) или вернуть (false). */
export function distaSetExcluded(id, excluded) {
  const body = new URLSearchParams({ excluded: excluded ? 'true' : 'false' });
  return apiJson(`${API}/dista/exclude/${id}`, { method: 'POST', body });
}

/**
 * Выгрузка списка «Нет в Dista» (карточки без dista_id) в .xlsx — имя + артикул.
 * Возвращает Blob (как exportContragents), поэтому идём через apiFetch.
 */
export async function distaOnlyOursExport() {
  const r = await apiFetch(`${API}/dista/only-ours-export`);
  if (!r.ok) throw new Error(`Не удалось выгрузить файл (${r.status})`);
  return r.blob();
}

/**
 * Функциональный экспорт ДЛЯ Dista (.xlsx): только связанные карточки, только
 * нужные Dista колонки (dista_id, название, номер договора, почта, банк. реквизиты).
 * Возвращает { blob, filename }: имя («export for Dista <дата>.xlsx») придумывает
 * сервер и шлёт в Content-Disposition.
 */
export async function distaExport() {
  const r = await apiFetch(`${API}/dista/export`);
  if (!r.ok) throw new Error(`Не удалось выгрузить файл (${r.status})`);
  return { blob: await r.blob(), filename: filenameFromResponse(r, 'export for Dista.xlsx') };
}
