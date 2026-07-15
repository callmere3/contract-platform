import { API, apiFetch, apiJson } from './client';

/**
 * GET /generation-history — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации (контрагент,
 * шаблон, кто сгенерировал) — сам payload формы сюда не отдаётся.
 */
export function listGenerationHistory() {
  return apiJson(`${API}/generation-history`);
}

/**
 * Пересоздать документ по сохранённому payload (этап 2). Файл нигде не
 * хранился — это рендер "на лету", такой же, каким был оригинал, но
 * выполненный сейчас (см. build_document_response на бэкенде). Не создаёт
 * новую запись в истории.
 */
export async function recreateGeneratedDocument(entryId, format = 'docx') {
  const r = await apiFetch(`${API}/generation-history/${entryId}/recreate?format=${format}`);
  if (!r.ok) {
    let detail = `Не удалось воссоздать документ (${r.status})`;
    try {
      const body = await r.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
    } catch {
      /* тело не JSON */
    }
    throw new Error(detail);
  }
  return r.blob();
}
