import { useTheme } from '../theme/ThemeContext';

const TABS = [
  { key: 'search', label: 'Поиск' },
  { key: 'database', label: 'База контрагентов' },
  { key: 'folders', label: 'Папки' },
];

export function Header({ activeTab, onTabChange, companyName = 'ML Docs', user }) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="flex items-center justify-between px-8 h-16 bg-surface border-b border-border sticky top-0 z-10">
      <div className="flex items-center gap-9">
        <span className="font-bold text-base tracking-[-0.01em] text-text">
          {companyName}
        </span>
        <nav className="flex items-center gap-7">
          {TABS.map((tab) => {
            const active = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => onTabChange(tab.key)}
                className={`text-sm py-5 border-b-2 transition-colors cursor-pointer bg-transparent ${
                  active
                    ? 'text-text font-semibold border-accent'
                    : 'text-text-secondary font-medium border-transparent'
                }`}
              >
                {tab.label}
              </button>
            );
          })}
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
          <span>{user?.name ?? 'Admin'}</span>
          <span className="px-2 py-0.5 border border-border rounded-[5px] text-[11px] text-text-muted">
            {user?.role ?? 'ADMIN'}
          </span>
        </div>
        <a href="#" className="text-[13px] text-accent no-underline">
          Выйти
        </a>
      </div>
    </header>
  );
}
