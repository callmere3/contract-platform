import { API, apiFetch, apiJson, filenameFromResponse } from './client';

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

/**
 * Загруженные отчёты: { reports: [...], totals }.
 *
 * Фильтр по периоду — ПЕРЕСЕЧЕНИЕ: у площадок периоды разные (месяц, квартал),
 * и «покажи всё за третий квартал» должно находить и июльский отчёт.
 */
export function listReports({ partnerId, periodFrom, periodTo } = {}) {
  const params = new URLSearchParams();
  if (partnerId) params.set('partner_id', partnerId);
  if (periodFrom) params.set('period_from', periodFrom);
  if (periodTo) params.set('period_to', periodTo);
  return apiJson(`${API}/partner-reports?${params}`);
}

/** Строки отчёта; unmatchedOnly — только те, чей артикул не в каталоге. */
export function reportRows(reportId, { page = 1, pageSize = 100, unmatchedOnly = false } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (unmatchedOnly) params.set('unmatched_only', 'true');
  return apiJson(`${API}/partner-reports/${reportId}/rows?${params}`);
}

/**
 * Поправить ШАПКУ отчёта: период и четыре параметра. Данные не трогает —
 * строки и суммы остаются как были, см. update_report на сервере.
 */
export function updateReport(reportId, { periodFrom, periodTo, attributes = {}, currencyRate }) {
  const body = new FormData();
  body.append('period_from', periodFrom);
  body.append('period_to', periodTo);
  // Курс шлём, только если его правили: «не прислали» — не трогать,
  // «прислали пусто» — вернуть суммы в валюту.
  if (currencyRate !== undefined) body.append('currency_rate', currencyRate ?? '');
  for (const [name, value] of Object.entries(attributes)) body.append(name, value ?? '');
  return apiJson(`${API}/partner-reports/${reportId}`, { method: 'PATCH', body });
}

export function deleteReport(reportId) {
  return apiJson(`${API}/partner-reports/${reportId}`, { method: 'DELETE' });
}

/** Правило разбора партнёра (или null) плюс список полей единого формата. */
export function getRule(partnerId) {
  return apiJson(`${API}/partner-reports/rules/${partnerId}`);
}

export function saveRule(
  partnerId,
  { mapping, vatRate = '', sheet = '', sampleFile = '', attributes = {} },
) {
  const body = new FormData();
  body.append('mapping', JSON.stringify(mapping));
  body.append('vat_rate', vatRate ?? '');
  body.append('sheet', sheet ?? '');
  body.append('sample_file', sampleFile ?? '');
  for (const [name, value] of Object.entries(attributes)) body.append(name, value ?? '');
  return apiJson(`${API}/partner-reports/rules/${partnerId}`, { method: 'PUT', body });
}

/** Есть ли такой артикул в каталоге — для строки, куда его вписывают руками. */
export function checkTrack(sku) {
  return apiJson(`${API}/partner-reports/track?sku=${encodeURIComponent(sku)}`);
}

/**
 * Запомненные сопоставления площадки: «название — исполнитель → артикул».
 *
 * Их заводит сам сервис, когда человек вписывает артикул в предпросмотре, —
 * чтобы в следующем отчёте той же площадки тот же трек приехал уже с
 * артикулом. Список нужен, чтобы ошибочное сопоставление можно было убрать:
 * иначе оно повторялось бы в каждом отчёте молча.
 */
export function listAliases(partnerId) {
  return apiJson(`${API}/partner-reports/aliases/${partnerId}`);
}

export function deleteAlias(aliasId) {
  return apiJson(`${API}/partner-reports/aliases/${aliasId}`, { method: 'DELETE' });
}

/**
 * Привязать отчёт к строке поступления: «эти деньги пришли по этому отчёту».
 *
 * Сервер сверяет площадку (отчёт МТС нельзя подшить к чужому платежу) и
 * пересчитывает у поступления «сумму фактического завода» — она равна сумме
 * привязанных к нему отчётов.
 */
export function linkReportPayment(reportId, paymentId) {
  const body = new FormData();
  body.append('payment_id', paymentId);
  return apiJson(`${API}/partner-reports/${reportId}/payment`, { method: 'POST', body });
}

export function unlinkReportPayment(reportId) {
  return apiJson(`${API}/partner-reports/${reportId}/payment`, { method: 'DELETE' });
}

/** Что уже вводили в параметрах отчёта — для подсказок в полях. */
export function fetchAttributeOptions() {
  return apiJson(`${API}/partner-reports/attributes`);
}

function uploadBody({
  partnerId,
  file,
  mapping,
  vatRate,
  currencyRate,
  sheet,
  manualSkus,
  attributes,
}) {
  const body = new FormData();
  // Курс к рублю — только у отчётов в валюте (Believe KZ в евро, AE в
  // долларах). Больше 1 — умножаем, меньше 1 — делим (см. currency_factor).
  if (currencyRate) body.append('currency_rate', currencyRate);
  // Партнёр может быть не выбран: предпросмотр узнаёт площадку по колонкам
  // файла и возвращает её. При сохранении он, наоборот, обязателен.
  body.append('partner_id', partnerId || '');
  body.append('file', file);
  // Пустое правило означает «возьми сохранённое у партнёра или догадайся»:
  // первый файл нового партнёра читается и без настройки.
  if (mapping) body.append('mapping', JSON.stringify(mapping));
  if (vatRate) body.append('vat_rate', vatRate);
  if (sheet) body.append('sheet', sheet);
  // Артикулы, вписанные руками в предпросмотре: {номер строки: артикул}.
  if (manualSkus && Object.keys(manualSkus).length) {
    body.append('manual_skus', JSON.stringify(manualSkus));
  }
  // Параметры отчёта (тип контента, тип и вид использования, территория)
  // шлём ВСЕГДА, даже пустыми: «не прислали» и «очистили» на сервере
  // одинаковы, а вот у правила партнёра пустое значение должно стирать
  // прежнее, а не оставлять его.
  for (const [name, value] of Object.entries(attributes ?? {})) {
    body.append(name, value ?? '');
  }
  return body;
}

/**
 * БЫСТРЫЙ ВЗГЛЯД — только шапка файла: площадка, правило, период, параметры,
 * НДС. Доли секунды даже на полумиллионном отчёте; по нему форма сразу
 * показывает кнопку «Загрузить отчёт», а строки считает `previewReport` следом.
 */
export function inspectReport(source) {
  return apiJson(`${API}/partner-reports/inspect`, {
    method: 'POST',
    body: uploadBody(source),
  });
}

/**
 * Строки ВНЕ КАТАЛОГА загруженного отчёта — файлом, все. Живёт у отчёта, а не
 * в импорте: разбираться с недостающими позициями — отдельная работа.
 * Имя файла («Вне каталога <площадка>.xlsx») придумывает сервер.
 */
export async function exportUnmatched(reportId) {
  const r = await apiFetch(`${API}/partner-reports/${reportId}/unmatched`);
  if (!r.ok) {
    let message = `Не удалось выгрузить файл (${r.status})`;
    try {
      const data = await r.json();
      if (typeof data.detail === 'string') message = data.detail;
    } catch {
      /* ответ не JSON — остаётся общий текст */
    }
    throw new Error(message);
  }
  return { blob: await r.blob(), filename: filenameFromResponse(r, 'Вне каталога.xlsx') };
}

/** Знак валюты для сумм отчёта, ещё не переведённого в рубли. */
export const CURRENCY_SIGNS = { USD: '$', EUR: '€', KZT: '₸', RUB: '₽' };

/**
 * Валютный отчёт без курса: его суммы — ещё валюта, а не рубли, и рисовать
 * их со знаком ₽ значило бы выдать доллары за рубли.
 */
export function currencySign(report) {
  if (!report?.rate_pending) return null;
  return CURRENCY_SIGNS[report.currency] || report.currency;
}

/** Курс, как его показывать: «83,381152». */
export function rateText(rate) {
  return rate == null || rate === '' ? '' : String(rate).replace('.', ',');
}

/** Разбор БЕЗ записи: колонки, правило, первые строки и итоги по всему файлу. */
export function previewReport(source) {
  return apiJson(`${API}/partner-reports/preview`, {
    method: 'POST',
    body: uploadBody(source),
  });
}

/**
 * Сохранить отчёт. Период — пара дат: площадки отчитываются то за месяц, то за
 * квартал, а «месяц» и «квартал» в форме лишь заполняют эти две даты.
 * saveRuleToo — заодно запомнить правило партнёру.
 */
export function createReport({ periodFrom, periodTo, saveRuleToo = false, ...source }) {
  const body = uploadBody(source);
  body.append('period_from', periodFrom);
  body.append('period_to', periodTo);
  body.append('save_rule', saveRuleToo ? 'true' : 'false');
  return apiJson(`${API}/partner-reports`, { method: 'POST', body });
}
