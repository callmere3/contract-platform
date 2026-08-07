import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import {
  canViewUsers,
  canViewGenerationHistory,
  canViewNotifications,
  canUseDistaSync,
} from '../auth/permissions';
import { notificationsCount, NOTIFICATIONS_CHANGED_EVENT } from '../api/notifications';
import { useModal } from '../modals/ModalProvider';

// Первые три вкладки видны всем ролям (см. ТЗ: "менеджер видит все вкладки").
// Ограничения для них — не на уровне доступа к вкладке, а на уровне действий
// внутри неё (кнопки создания/удаления), см. src/auth/permissions.js.
//
// "Пользователи" и "История генерации" — исключение: там доступ не у всех
// ролей (первая — ADMIN правит / DIRECTOR смотрит, вторая — ADMIN/DIRECTOR
// и TOP_MANAGER свою), поэтому остальным вкладка показала бы только 403.
// Прячем целиком.
const TABS = [
  { to: '/search', label: 'Генерация' },
  { to: '/database', label: 'База контрагентов' },
  // Вкладка называется "Шаблоны", а маршрут остался /folders: переименование
  // чисто в подписи — внутри по-прежнему дерево папок с шаблонами, и кнопка
  // "+ Папка" там на месте. Менять URL ради подписи незачем.
  { to: '/folders', label: 'Шаблоны' },
];

export function Header({ companyName = 'ML Docs' }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const { openModal } = useModal();

  // Счётчик непросмотренных уведомлений (только admin). Обновляем на монтировании,
  // раз в минуту и мгновенно по window-событию 'notifications-changed', которое
  // шлёт NotificationsPage после применения/отклонения — иначе бейдж отставал бы.
  const showNotifications = canViewNotifications(user?.role);
  const [notifCount, setNotifCount] = useState(0);
  useEffect(() => {
    if (!showNotifications) return undefined;
    let alive = true;
    const refresh = () =>
      notificationsCount()
        .then((r) => alive && setNotifCount(r.pending || 0))
        .catch(() => {});
    refresh();
    const timer = setInterval(refresh, 60_000);
    window.addEventListener(NOTIFICATIONS_CHANGED_EVENT, refresh);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_CHANGED_EVENT, refresh);
    };
  }, [showNotifications]);

  let tabs = TABS;
  if (canViewGenerationHistory(user?.role)) {
    tabs = [...tabs, { to: '/generation-history', label: 'История генерации' }];
  }
  if (showNotifications) {
    tabs = [...tabs, { to: '/notifications', label: 'Уведомления', badge: notifCount }];
  }
  if (canViewUsers(user?.role)) {
    tabs = [...tabs, { to: '/users', label: 'Пользователи' }];
  }
  if (canUseDistaSync(user?.role)) {
    tabs = [...tabs, { to: '/dista', label: 'Dista Connect' }];
  }

  return (
    <header className="flex items-center justify-between px-8 h-16 bg-surface border-b border-border sticky top-0 z-10">
      <div className="flex items-center gap-9">
        <span className="font-bold text-base tracking-[-0.01em] text-text">{companyName}</span>
        <nav className="flex items-center gap-7">
          {tabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `text-sm py-5 border-b-2 transition-colors no-underline inline-flex items-center gap-1.5 ${
                  isActive
                    ? 'text-text font-semibold border-accent'
                    : 'text-text-secondary font-medium border-transparent'
                }`
              }
            >
              {tab.label}
              {tab.badge > 0 && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[11px] font-semibold leading-none">
                  {tab.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={toggleTheme}
          aria-label="Переключить тему"
          className="w-8 h-8 rounded-full border border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        {/* Имя — точка входа в смену своего пароля: отдельная вкладка ради
            одного действия избыточна, а profile-меню в макете не заложено. */}
        <button
          onClick={() => openModal('changePassword')}
          title="Сменить пароль"
          className="text-[13px] text-text-secondary hover:text-text bg-transparent border-none cursor-pointer p-0 font-sans"
        >
          {user?.full_name || user?.username}
        </button>
        <button
          onClick={logout}
          className="text-[13px] text-accent bg-transparent border-none cursor-pointer p-0 font-sans"
        >
          Выйти
        </button>
      </div>
    </header>
  );
}
