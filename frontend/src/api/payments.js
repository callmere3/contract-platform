import { API, apiJson } from './client';

/**
 * Поступления от площадок (ML Finance → «Поступления», admin и director).
 *
 * Деньги — СТРОКАМИ в обе стороны, как везде в ML Finance: в JSON-числе
 * 1234.10 превращается в 1234.0999999999999. Складывает их сервер, экран
 * только показывает.
 *
 * Правка построчная и по одному полю: таблицу дозаполняют — «заведено» и
 * фактическую сумму проставляют через недели после платежа.
 */

/** Строки за период: { payments: [...], totals }. */
export function listPayments({ dateFrom, dateTo, partnerId } = {}) {
  const params = new URLSearchParams();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (partnerId) params.set('partner_id', partnerId);
  return apiJson(`${API}/payments?${params}`);
}

/** Завести строку. Обязательна только дата — остальное дозаполняют. */
export function createPayment(payment) {
  return apiJson(`${API}/payments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payment),
  });
}

/**
 * Поправить строку. Шлём ТОЛЬКО тронутое поле: сервер отличает «не прислали»
 * от «прислали пусто», и очистка поля — такое же осмысленное действие, как
 * ввод.
 */
export function updatePayment(paymentId, patch) {
  return apiJson(`${API}/payments/${paymentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export function deletePayment(paymentId) {
  return apiJson(`${API}/payments/${paymentId}`, { method: 'DELETE' });
}
