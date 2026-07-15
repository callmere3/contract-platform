import { useCallback, useEffect, useState } from 'react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { listUsers, updateUser } from '../api/users';
import { useTags } from '../api/TagsContext';
import { useAuth } from '../auth/AuthContext';
import { ROLE_LABELS } from '../auth/permissions';
import { useModal } from '../modals/ModalProvider';

/**
 * "Пользователи" — только для admin (все три эндпоинта /users защищены
 * require_role(ADMIN)). Вкладка в шапке тоже показывается только ему.
 *
 * Роль меняется прямо в строке, без отдельной модалки: это одно поле из
 * трёх возможных значений, ради него открывать диалог избыточно.
 *
 * Себя изменить нельзя — бэкенд запрещает менять роль и деактивировать
 * самого себя (иначе единственный админ может отобрать доступ у самого
 * себя безвозвратно). Здесь просто не даём такой возможности в UI.
 */
export function UsersPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingId, setSavingId] = useState(null);
  const { roles } = useTags();
  const { user: me } = useAuth();
  const { openModal } = useModal();

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setUsers(await listUsers());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function changeRole(user, role) {
    setSavingId(user.id);
    setError('');
    try {
      await updateUser(user.id, { role });
      setUsers((list) => list.map((u) => (u.id === user.id ? { ...u, role } : u)));
    } catch (e) {
      setError(e.message);
    } finally {
      setSavingId(null);
    }
  }

  async function toggleActive(user) {
    setSavingId(user.id);
    setError('');
    try {
      const next = !user.is_active;
      await updateUser(user.id, { is_active: next });
      setUsers((list) => list.map((u) => (u.id === user.id ? { ...u, is_active: next } : u)));
    } catch (e) {
      setError(e.message);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between p-5 border-b border-border">
          <span className="text-sm font-semibold text-text">Пользователи</span>
          <Button variant="primary" size="sm" onClick={() => openModal('newUser', { onDone: load })}>
            + Пользователь
          </Button>
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}

        {!loading &&
          users.map((u) => {
            const isMe = u.id === me?.id;
            const busy = savingId === u.id;
            return (
              <div
                key={u.id}
                className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-text truncate flex items-center gap-2">
                    {u.full_name || u.username}
                    {isMe && <Badge variant="neutral">это вы</Badge>}
                    {!u.is_active && <Badge variant="neutral">отключён</Badge>}
                  </div>
                  <div className="text-[13px] text-text-muted mt-0.5 truncate">{u.username}</div>
                </div>

                <div className="flex items-center gap-2.5 flex-shrink-0">
                  {isMe ? (
                    // Себе роль не меняем — бэкенд это запретит (400), а
                    // кнопка, которая гарантированно вернёт ошибку, только
                    // путает. Показываем текущую роль как есть.
                    <Badge variant="accent">{ROLE_LABELS[u.role] ?? u.role}</Badge>
                  ) : (
                    <>
                      <select
                        value={u.role}
                        disabled={busy}
                        onChange={(e) => changeRole(u, e.target.value)}
                        className="bg-input-bg border border-border rounded-input px-2.5 py-1.5 text-[13px] text-text font-sans outline-none"
                      >
                        {roles.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r] ?? r}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => toggleActive(u)}
                      >
                        {u.is_active ? 'Отключить' : 'Включить'}
                      </Button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
      </Card>

      <div className="text-[11px] text-text-muted mt-4 leading-snug">
        Отключение пользователя сразу обрывает все его текущие сессии. Свою роль изменить нельзя —
        иначе можно потерять доступ безвозвратно.
      </div>
    </div>
  );
}
