import { API, apiJson } from './client';

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
