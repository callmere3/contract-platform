import { NavLink } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import { ROLE_LABELS } from '../auth/permissions';

// Все три вкладки видны всем ролям (см. ТЗ: "менеджер видит все вкладки").
// Ограничения — не на уровне доступа к вкладке, а на уровне действий
// внутри неё (кнопки создания/удаления), см. src/auth/permissions.js.
const TABS = [
  { to: '/search', label: 'Поиск' },
  { to: '/database', label: 'База контрагентов' },
  { to: '/folders', label: 'Папки' },
];

export function Header({ companyName = 'ML Docs' }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  return (
    <header className="flex items-center justify-between px-8 h-16 bg-surface border-b border-border sticky top-0 z-10">
      <div className="flex items-center gap-9">
        <span className="font-bold text-base tracking-[-0.01em] text-text">{companyName}</span>
        <nav className="flex items-center gap-7">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `text-sm py-5 border-b-2 transition-colors no-underline ${
                  isActive
                    ? 'text-text font-semibold border-accent'
                    : 'text-text-secondary font-medium border-transparent'
                }`
              }
            >
              {tab.label}
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
        <div className="flex items-center gap-1.5 text-[13px] text-text-secondary">
          <span>{user?.full_name || user?.username}</span>
          <span className="px-2 py-0.5 border border-border rounded-[5px] text-[11px] text-text-muted">
            {ROLE_LABELS[user?.role] ?? user?.role}
          </span>
        </div>
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
