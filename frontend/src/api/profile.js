import { API, apiJson } from './client';

/**
 * Достижения текущего пользователя для карточки профиля.
 *
 * Только свои — сервер не принимает id (см. routers_profile.py). Считает
 * тоже он: правила («что считается документом», пороги вех) живут в одном
 * месте с кубком, иначе профиль и рейтинг разошлись бы в числах.
 */
export function fetchMyAchievements() {
  return apiJson(`${API}/profile/achievements`);
}

/**
 * Отметить действие, которого не видно в данных, — сейчас это сброшенный
 * черновик (достижение «Разбитое сердце»). Имя события сервер принимает
 * только из своего белого списка, произвольное он отвергнет.
 */
export function reportEvent(event) {
  return apiJson(`${API}/profile/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event }),
  });
}
