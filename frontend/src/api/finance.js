import { API, apiJson } from './client';

/**
 * ML Finance — деньги по контрагентам (admin и director, CAN_USE_FINANCE).
 *
 * База контрагентов тут ТА ЖЕ, что в ML Docs: сервер строит список тем же
 * поиском, только добавляет каждому баланс. Поэтому фильтры и пагинация
 * совпадают с «Базой контрагентов» до параметра.
 *
 * СУММЫ — СТРОКИ, а не числа, и такими же приходят с сервера. Деньги в
 * double расходятся в копейках («1234.10» → 1234.0999999999999), поэтому
 * фронт их не парсит и не складывает: он их показывает. Всё, что надо
 * посчитать, считает сервер.
 */

/** Список с балансами: { contragents: [...+balance], total, page, page_size }. */
export function listFinanceContragents({ q, country, contragentType, page, pageSize }) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (country) params.set('country', country);
  if (contragentType) params.set('contragent_type', contragentType);
  if (page) params.set('page', String(page));
  if (pageSize) params.set('page_size', String(pageSize));
  return apiJson(`${API}/finance/contragents?${params}`);
}

/** Карточка: ФИО, никнеймы, реквизиты, баланс, итоги и все операции. */
export function fetchFinanceCard(contragentId) {
  return apiJson(`${API}/finance/contragents/${contragentId}`);
}

/**
 * Внести операцию. kind — 'income' | 'expense'; amount строкой («10 000,50»
 * сервер разберёт сам); occurredOn — ISO-дата из <input type="date">.
 *
 * period — только для поступлений: {yearFrom, quarterFrom, yearTo?, quarterTo?}.
 * Поступление это квартальный отчёт, и без квартала непонятно, за что пришли
 * деньги: дата зачисления на это не отвечает — за I квартал платят в апреле.
 */
export function addFinanceOperation(
  contragentId,
  { kind, amount, category, occurredOn, documentNumber, comment, period },
) {
  const body = new FormData();
  body.append('kind', kind);
  body.append('amount', amount);
  body.append('category', category);
  body.append('occurred_on', occurredOn);
  if (documentNumber) body.append('document_number', documentNumber);
  if (comment) body.append('comment', comment);
  // Период — только у поступлений (расход с периодом сервер отвергает).
  // «По» не шлём, если период в один квартал: сервер сам продублирует начало.
  if (period) {
    body.append('period_year_from', String(period.yearFrom));
    body.append('period_quarter_from', String(period.quarterFrom));
    if (period.yearTo) body.append('period_year_to', String(period.yearTo));
    if (period.quarterTo) body.append('period_quarter_to', String(period.quarterTo));
  }
  // Form-data, а не JSON: эндпоинт принимает Form(...), как и создание
  // контрагента — в этом проекте так устроены все пишущие ручки, кроме
  // пользователей и уведомлений.
  return apiJson(`${API}/finance/contragents/${contragentId}/operations`, {
    method: 'POST',
    body,
  });
}

/** Удалить операцию — только admin. Правки операций нет: удалить и внести заново. */
export function deleteFinanceOperation(operationId) {
  return apiJson(`${API}/finance/operations/${operationId}`, { method: 'DELETE' });
}

/**
 * «7000.5» → «7 000,50 ₽». Форматируем строку, не приводя её к числу дважды:
 * Number нужен только Intl, результат в дальнейших расчётах не участвует.
 */
export function formatMoney(value) {
  const number = Number(value ?? 0);
  if (Number.isNaN(number)) return String(value ?? '');
  return `${number.toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ₽`;
}
