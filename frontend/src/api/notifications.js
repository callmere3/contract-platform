import { API, apiJson } from './client';

/**
 * Вызовы к /notifications — вкладка "Уведомления" (только admin,
 * CAN_VIEW_NOTIFICATIONS на всех эндпоинтах).
 *
 * Предложения дозаполнить/поправить карточку контрагента значениями, которые
 * менеджер вписал в форму генерации (см. бэкенд app/routers_notifications.py).
 */

// Событие "число уведомлений могло измениться" — бейдж-счётчик в шапке ловит
// его и сразу перезапрашивает /count, не дожидаясь своего минутного опроса.
// Шлём и после действий на самой вкладке (применить/отклонить), и после
// генерации документа (там на сервере мог родиться новый suggestion).
// Общий константный ключ вместо строк по коду — чтобы источник и слушатель
// не разъехались.
export const NOTIFICATIONS_CHANGED_EVENT = 'notifications-changed';

export function emitNotificationsChanged() {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED_EVENT));
}

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
