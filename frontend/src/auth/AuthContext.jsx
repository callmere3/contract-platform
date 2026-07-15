import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  fetchCurrentUser,
  getTokens,
  loginRequest,
  logoutRequest,
  setSessionExpiredHandler,
  setTokens,
} from '../api/client';

const AuthContext = createContext(null);

/**
 * Состояние сессии на весь фронт.
 *
 * status:
 *   'loading'   — идёт восстановление сессии из localStorage (первый рендер).
 *                 Пока так, НЕ показываем ни приложение, ни экран входа:
 *                 иначе при каждой перезагрузке страницы залогиненный
 *                 пользователь видел бы вспышку формы логина.
 *   'anon'      — не авторизован, показываем LoginPage.
 *   'authed'    — есть user, показываем приложение.
 */
export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading');
  const [user, setUser] = useState(null);
  const [expiredMessage, setExpiredMessage] = useState('');

  const handleSessionExpired = useCallback(() => {
    setUser(null);
    setStatus('anon');
    setExpiredMessage('Сессия истекла, войдите снова.');
  }, []);

  // api-слой не знает про React — отдаём ему колбэк один раз.
  useEffect(() => {
    setSessionExpiredHandler(handleSessionExpired);
  }, [handleSessionExpired]);

  // Восстановление сессии при загрузке страницы: если в localStorage лежат
  // токены, проверяем их живость через /auth/me. apiFetch внутри сам
  // попробует refresh, если access протух — поэтому отдельная проверка
  // срока годности здесь не нужна.
  useEffect(() => {
    const { accessToken, refreshToken } = getTokens();
    if (!accessToken && !refreshToken) {
      setStatus('anon');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchCurrentUser();
        if (cancelled) return;
        setUser(me);
        setStatus('authed');
      } catch {
        if (cancelled) return;
        setTokens(null, null);
        setUser(null);
        setStatus('anon');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username, password) => {
    await loginRequest(username, password);
    const me = await fetchCurrentUser();
    setUser(me);
    setExpiredMessage('');
    setStatus('authed');
    return me;
  }, []);

  const logout = useCallback(async () => {
    await logoutRequest();
    setUser(null);
    setExpiredMessage('');
    setStatus('anon');
  }, []);

  return (
    <AuthContext.Provider
      value={{ status, user, role: user?.role ?? null, login, logout, expiredMessage }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
