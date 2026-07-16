import { API, apiFetch, apiJson, filenameFromResponse } from './client';

/**
 * GET /generation-history — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации (контрагент,
 * псевдоним, шаблон, кто сгенерировал) — сам payload формы сюда не отдаётся.
 *
 * filterType/filterValue — единый фильтр вместо трёх отдельных полей:
 * filterType — 'contragent' | 'nickname' | 'user', filterValue — подстрока
 * (без учёта регистра, см. ILIKE на бэкенде).
 */
export function listGenerationHistory({ filterType, filterValue } = {}) {
  const params = new URLSearchParams();
  if (filterType && filterValue) {
    params.set('filter_type', filterType);
    params.set('filter_value', filterValue);
  }
  const qs = params.toString();
  return apiJson(`${API}/generation-history${qs ? `?${qs}` : ''}`);
}

/**
 * Пересоздать документ по сохранённому payload (этап 2). Файл нигде не
 * хранился — это рендер "на лету", такой же, каким был оригинал, но
 * выполненный сейчас (см. build_document_response на бэкенде). Не создаёт
 * новую запись в истории.
 *
 * Возвращает { blob, filename }: имя приходит из Content-Disposition и
 * собрано сервером по титлу-снимку из истории — то есть совпадает с тем,
 * под которым документ скачали в первый раз.
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
  return { blob: await r.blob(), filename: filenameFromResponse(r) };
}
