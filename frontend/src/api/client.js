/**
 * Единая точка входа для ЛЮБОГО запроса к нашему API.
 *
 * Схема авторизации перенесена один-в-один из боевого backend/static/index.html
 * (этап 6): access/refresh в localStorage, автоматическая попытка обновить
 * access по 401, и только если refresh тоже не сработал — разлогин.
 *
 * Почему localStorage, а не sessionStorage/httpOnly-cookie:
 *  - переживает перезагрузку страницы, а не только вкладку;
 *  - access живёт 30 минут (backend/app/config.py: jwt_access_ttl_minutes),
 *    поэтому даже утечка через XSS даёт короткое окно;
 *  - refresh (14 дней) ротируется на каждое обновление (app/auth.py) —
 *    повторное использование отозванного токена будет видно на сервере.
 * Менять эту схему на cookie можно только вместе с бэкендом, не в одиночку.
 */

// Тот же origin, что и API: фронт отдаётся тем же FastAPI (см. base '/app/'
// в vite.config.js). При запуске dev-сервера отдельно — проксируется через
// vite (см. server.proxy там же), поэтому здесь всегда пустая строка.
export const API = '';

const ACCESS_KEY = 'ml_access_token';
const REFRESH_KEY = 'ml_refresh_token';

let accessToken = localStorage.getItem(ACCESS_KEY) || null;
let refreshToken = localStorage.getItem(REFRESH_KEY) || null;

/**
 * Колбэк, который зовётся, когда пользователь окончательно потерял сессию
 * (refresh не помог). Ставится один раз из AuthContext — так api-слой не
 * знает про React, а AuthContext не лезет внутрь fetch-логики.
 */
let onSessionExpired = () => {};
export function setSessionExpiredHandler(fn) {
  onSessionExpired = fn;
}

export function getTokens() {
  return { accessToken, refreshToken };
}

export function setTokens(access, refresh) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem(ACCESS_KEY, access);
  else localStorage.removeItem(ACCESS_KEY);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  else localStorage.removeItem(REFRESH_KEY);
}

async function tryRefresh() {
  if (!refreshToken) return false;
  try {
    const r = await fetch(`${API}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!r.ok) {
      setTokens(null, null);
      return false;
    }
    const data = await r.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    setTokens(null, null);
    return false;
  }
}

/**
 * Несколько параллельных запросов могут словить 401 одновременно (типичный
 * случай: страница грузит /tags и /contragents разом после простоя). Без
 * этого замка каждый из них дёрнул бы /auth/refresh со СВОИМ refresh-токеном,
 * а так как refresh ротируется на каждое использование, второй запрос
 * пришёл бы уже с отозванным токеном и выкинул бы пользователя на логин —
 * при полностью живой сессии. Поэтому обновляем ровно один раз, остальные
 * ждут тот же промис.
 */
let refreshPromise = null;
function refreshOnce() {
  if (!refreshPromise) {
    refreshPromise = tryRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function apiFetch(url, options = {}) {
  const withAuth = (opts) => ({
    ...opts,
    headers: {
      ...(opts.headers || {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });

  let r = await fetch(url, withAuth(options));
  if (r.status === 401 && refreshToken) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      r = await fetch(url, withAuth(options));
    } else {
      onSessionExpired();
    }
  }
  return r;
}

/**
 * apiFetch + разбор JSON + понятная ошибка из detail (FastAPI кладёт текст
 * ошибки именно туда — см. HTTPException(detail=...) по всему бэкенду).
 * Кидает Error с человекочитаемым сообщением, которое можно показать как есть.
 */
export async function apiJson(url, options = {}) {
  const r = await apiFetch(url, options);
  if (!r.ok) {
    let detail = `Ошибка ${r.status}`;
    try {
      const body = await r.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
    } catch {
      /* тело не JSON — оставляем код статуса */
    }
    throw new Error(detail);
  }
  if (r.status === 204) return null;
  return r.json();
}

// ---- auth-специфичные вызовы (без токена / с особой обработкой) ----

export async function loginRequest(username, password) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || 'Неверный логин или пароль');
  }
  const data = await r.json();
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function logoutRequest() {
  // best-effort: даже если сервер недоступен и запрос на отзыв не дойдёт,
  // токены всё равно стираются локально — пользователь выходит в любом случае
  try {
    await fetch(`${API}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    /* игнорируем: локальный выход важнее */
  }
  setTokens(null, null);
}

export function fetchCurrentUser() {
  return apiJson(`${API}/auth/me`);
}
