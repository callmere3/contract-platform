/**
 * Крутящийся индикатор «идёт работа».
 *
 * Рисованный, а не символ: берёт цвет текста через currentColor и одинаково
 * выглядит в светлой и тёмной теме. Нужен там, где запрос идёт десятки
 * секунд (привязка большого отчёта к поступлению пересчитывает сотни тысяч
 * строк) и без движения на экране кажется, что сервис завис.
 */
export function Spinner({ size = 28, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={`animate-spin ${className}`}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.2" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
