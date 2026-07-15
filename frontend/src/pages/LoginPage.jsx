import { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';

/**
 * Экран входа. Показывается, пока status !== 'authed' (см. AuthContext).
 *
 * Отдельного роута /login намеренно нет: экран входа — это состояние
 * приложения, а не адрес. Иначе при разлогине по протухшему токену
 * пришлось бы уводить пользователя с его текущего URL и потом
 * возвращать обратно; так он остаётся на месте и после входа видит ту
 * же страницу, на которой был.
 */
export function LoginPage() {
  const { login, expiredMessage } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (!username.trim() || !password) {
      setError('Заполните логин и пароль.');
      return;
    }
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err.message);
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  const inputClass =
    'w-full bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans focus:border-border-strong';

  return (
    <div className="min-h-screen flex items-center justify-center px-8">
      <Card className="w-full max-w-[380px]">
        <form onSubmit={handleSubmit} className="p-8">
          <div className="text-[16px] font-bold mb-1">ML Docs</div>
          <div className="text-[13px] text-text-muted mb-7">Генератор договоров</div>

          <div className="mb-4">
            <div className="text-xs text-text-secondary mb-1.5">Логин</div>
            <input
              className={inputClass}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </div>

          <div className="mb-5">
            <div className="text-xs text-text-secondary mb-1.5">Пароль</div>
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          {(error || expiredMessage) && (
            <div className="text-[13px] text-accent mb-4 leading-snug">
              {error || expiredMessage}
            </div>
          )}

          <Button type="submit" variant="primary" size="sm" className="w-full" disabled={busy}>
            {busy ? 'Входим…' : 'Войти'}
          </Button>
        </form>
      </Card>
    </div>
  );
}
