import { API, apiJson } from './client';

/**
 * Уведомления: админ пишет команде, остальные читают.
 *
 * Чтение (список, счётчик, отметка о прочтении) доступно любой роли и
 * отдаёт ТОЛЬКО свои строки — параметра «чьи» нет вовсе. Написание,
 * просмотр отправленного и удаление — только admin (CAN_SEND_NOTIFICATIONS
 * на сервере).
 */

// Событие «число уведомлений могло измениться» — значок в шапке ловит его и
// перезапрашивает счётчик, не дожидаясь своего минутного опроса. Шлём после
// прочтения панели и после отправки/удаления во вкладке админа.
export const NOTIFICATIONS_CHANGED_EVENT = 'notifications-changed';

export function emitNotificationsChanged() {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED_EVENT));
}

/** Мои уведомления, новые сверху. */
export function listMyNotifications() {
  return apiJson(`${API}/notifications`);
}

/** Для значка в шапке: { unread }. */
export function notificationsCount() {
  return apiJson(`${API}/notifications/count`);
}

/** Отметить мои прочитанными — вызывается при открытии панели. */
export function markNotificationsRead() {
  return apiJson(`${API}/notifications/read`, { method: 'POST' });
}

/**
 * Написать уведомление. toAll=true — всем действующим сотрудникам, кроме
 * автора; иначе адресаты берутся из userIds.
 */
export function sendNotification({ text, toAll, userIds = [] }) {
  return apiJson(`${API}/notifications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, to_all: toAll, user_ids: userIds }),
  });
}

/**
 * Убрать уведомление У СЕБЯ. Чужих не касается: на сервере это пометка на
 * строке «адресовано мне», а не удаление объявления. Админское удаление —
 * deleteNotification ниже, оно сносит объявление у всех.
 */
export function hideMyNotification(id) {
  return apiJson(`${API}/notifications/mine/${id}`, { method: 'DELETE' });
}

/** Отправленное — с отметками, кто прочитал (только admin). */
export function listSentNotifications() {
  return apiJson(`${API}/notifications/sent`);
}

/** Удалить отправленное — исчезает и из чужих панелей (каскад). */
export function deleteNotification(id) {
  return apiJson(`${API}/notifications/${id}`, { method: 'DELETE' });
}
