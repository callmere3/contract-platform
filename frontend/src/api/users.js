import { API, apiJson } from './client';

/**
 * Вызовы к /users — только для admin (require_role(ADMIN) на всех трёх
 * эндпоинтах).
 *
 * В отличие от контрагентов и шаблонов, здесь тело — JSON, а не form-data
 * (роутер принимает pydantic-модели CreateUserRequest/UpdateUserRequest).
 */

export function listUsers() {
  return apiJson(`${API}/users`);
}

/** password — минимум 8 символов (Field(min_length=8) на бэкенде). */
export function createUser({ username, password, fullName, role }) {
  return apiJson(`${API}/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username,
      password,
      full_name: fullName || null,
      role,
    }),
  });
}

/**
 * Правка пользователя. Шлём только то, что меняем: на бэкенде каждое поле
 * проверяется на `is not None`, поэтому не переданное просто не трогается.
 *
 * is_active=false деактивирует и обрывает все текущие сессии пользователя
 * (revoke_all_user_tokens) — иначе уже выданные токены жили бы до конца TTL.
 */
export function updateUser(userId, fields) {
  return apiJson(`${API}/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
}
