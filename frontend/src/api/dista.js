import { API, apiFetch, apiJson } from './client';

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

/** Сводка связки: {total, linked, unlinked}. */
export function distaStatus() {
  return apiJson(`${API}/dista/status`);
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
