import { createContext, useContext, useEffect, useState } from 'react';

const ThemeContext = createContext(null);

const STORAGE_KEY = 'ml_theme';

/**
 * Тема ML Docs: dark по умолчанию, переключение ручное (иконка в шапке).
 * Выбор сохраняется в localStorage — иначе тема слетала бы на dark при
 * каждой перезагрузке страницы.
 *
 * prefers-color-scheme намеренно НЕ используется как источник правды:
 * по дизайн-системе переключение ручное. Системную тему берём только как
 * стартовое значение для тех, кто ещё ни разу не выбирал сам.
 */
function readInitialTheme(defaultTheme) {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === 'dark' || saved === 'light') return saved;
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  return defaultTheme;
}

export function ThemeProvider({ defaultTheme = 'dark', children }) {
  const [theme, setTheme] = useState(() => readInitialTheme(defaultTheme));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
