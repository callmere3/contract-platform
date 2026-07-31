import { API, apiJson } from './client';

/**
 * Вызовы к /notifications — вкладка "Уведомления" (только admin,
 * CAN_VIEW_NOTIFICATIONS на всех эндпоинтах).
 *
 * Предложения дозаполнить/поправить карточку контрагента значениями, которые
 * менеджер вписал в форму генерации (см. бэкенд app/routers_notifications.py).
 */

export function listNotifications() {
  return apiJson(`${API}/notifications`);
}

/** Счётчик для бейджа в шапке: { pending, actionable }. */
export function notificationsCount() {
  return apiJson(`${API}/notifications/count`);
}

/** Применить предложение к карточке (прямая запись колонки). */
export function applyNotification(id) {
  return apiJson(`${API}/notifications/${id}/apply`, { method: 'POST' });
}

/** Отклонить предложение — больше не всплывает (пока не придёт другое значение). */
export function dismissNotification(id) {
  return apiJson(`${API}/notifications/${id}/dismiss`, { method: 'POST' });
}
