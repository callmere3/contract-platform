import { API, apiFetch, apiJson, filenameFromResponse } from './client';

/**
 * Отчёты правообладателям (24.09.2026). Настройки — как в окне генерации
 * Dista: период, правообладатели, площадки, товарный фильтр. Пустой список
 * значит «все».
 *
 * Суммы приходят СТРОКАМИ, как во всём ML Finance: фронт их показывает, но не
 * складывает.
 */
function body(settings) {
  return JSON.stringify({
    period_from: settings.periodFrom,
    period_to: settings.periodTo,
    date_basis: settings.dateBasis,
    contragent_ids: settings.contragentIds ?? [],
    partner_ids: settings.partnerIds ?? [],
    track_ids: settings.trackIds ?? [],
    group_detail: settings.groupDetail,
    kinds: settings.kinds,
  });
}

/** Кому и сколько насчитано, и какие отчёты площадок пропущены. */
export function previewRoyalty(settings) {
  return apiJson(`${API}/royalty-reports/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body(settings),
  });
}

/** Файлы: один .xlsx или .zip со всеми. Имя придумывает сервер. */
export async function generateRoyalty(settings) {
  const r = await apiFetch(`${API}/royalty-reports/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body(settings),
  });
  if (!r.ok) {
    let message = `Не удалось сформировать отчёты (${r.status})`;
    try {
      const data = await r.json();
      if (typeof data.detail === 'string') message = data.detail;
    } catch {
      /* ответ не JSON — остаётся общий текст */
    }
    throw new Error(message);
  }
  return { blob: await r.blob(), filename: filenameFromResponse(r, 'Отчеты.zip') };
}
