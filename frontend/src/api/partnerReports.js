import { API, apiJson } from './client';

/**
 * Отчёты площадок (ML Finance → «Отчёты», admin и director).
 *
 * Загрузка в два шага, как у номенклатуры: сначала `previewReport` показывает,
 * что получилось из файла, и только потом `createReport` кладёт это в базу.
 * Отчёт приходит раз в квартал — залить его вслепую значит узнать об ошибке
 * через три месяца.
 *
 * Суммы приходят и уходят СТРОКАМИ, как и везде в ML Finance: в JSON-числе
 * 1234.10 превращается в 1234.0999999999999.
 */

/** Загруженные отчёты: { reports: [...], totals }. */
export function listReports({ partnerId, year, quarter } = {}) {
  const params = new URLSearchParams();
  if (partnerId) params.set('partner_id', partnerId);
  if (year) params.set('year', String(year));
  if (quarter) params.set('quarter', String(quarter));
  return apiJson(`${API}/partner-reports?${params}`);
}

/** Строки отчёта; unmatchedOnly — только те, чей артикул не в каталоге. */
export function reportRows(reportId, { page = 1, pageSize = 100, unmatchedOnly = false } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (unmatchedOnly) params.set('unmatched_only', 'true');
  return apiJson(`${API}/partner-reports/${reportId}/rows?${params}`);
}

export function deleteReport(reportId) {
  return apiJson(`${API}/partner-reports/${reportId}`, { method: 'DELETE' });
}

/** Правило разбора партнёра (или null) плюс список полей единого формата. */
export function getRule(partnerId) {
  return apiJson(`${API}/partner-reports/rules/${partnerId}`);
}

export function saveRule(partnerId, { mapping, vatRate = '', sheet = '', sampleFile = '' }) {
  const body = new FormData();
  body.append('mapping', JSON.stringify(mapping));
  body.append('vat_rate', vatRate ?? '');
  body.append('sheet', sheet ?? '');
  body.append('sample_file', sampleFile ?? '');
  return apiJson(`${API}/partner-reports/rules/${partnerId}`, { method: 'PUT', body });
}

function uploadBody({ partnerId, file, mapping, vatRate, sheet }) {
  const body = new FormData();
  body.append('partner_id', partnerId);
  body.append('file', file);
  // Пустое правило означает «возьми сохранённое у партнёра или догадайся»:
  // первый файл нового партнёра читается и без настройки.
  if (mapping) body.append('mapping', JSON.stringify(mapping));
  if (vatRate) body.append('vat_rate', vatRate);
  if (sheet) body.append('sheet', sheet);
  return body;
}

/** Разбор БЕЗ записи: колонки, правило, первые строки и итоги по всему файлу. */
export function previewReport(source) {
  return apiJson(`${API}/partner-reports/preview`, {
    method: 'POST',
    body: uploadBody(source),
  });
}

/** Сохранить отчёт. saveRuleToo — заодно запомнить правило партнёру. */
export function createReport({ year, quarter, saveRuleToo = false, ...source }) {
  const body = uploadBody(source);
  body.append('year', String(year));
  body.append('quarter', String(quarter));
  body.append('save_rule', saveRuleToo ? 'true' : 'false');
  return apiJson(`${API}/partner-reports`, { method: 'POST', body });
}
