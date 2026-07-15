import { NavLink } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import { canManageUsers, canViewGenerationHistory } from '../auth/permissions';
import { useModal } from '../modals/ModalProvider';

// Первые три вкладки видны всем ролям (см. ТЗ: "менеджер видит все вкладки").
// Ограничения для них — не на уровне доступа к вкладке, а на уровне действий
// внутри неё (кнопки создания/удаления), см. src/auth/permissions.js.
//
// "Пользователи" и "История генерации" — исключение: там все действия
// доступны не всем ролям (первая — только ADMIN, вторая — ADMIN/DIRECTOR),
// поэтому остальным вкладка показала бы только ошибку 403. Прячем целиком.
const TABS = [
  { to: '/search', label: 'Поиск' },
  { to: '/database', label: 'База контрагентов' },
  { to: '/folders', label: 'Папки' },
];

export function Header({ companyName = 'ML Docs' }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const { openModal } = useModal();

  let tabs = TABS;
  if (canViewGenerationHistory(user?.role)) {
    tabs = [...tabs, { to: '/generation-history', label: 'История генерации' }];
  }
  if (canManageUsers(user?.role)) {
    tabs = [...tabs, { to: '/users', label: 'Пользователи' }];
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
