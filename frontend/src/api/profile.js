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
