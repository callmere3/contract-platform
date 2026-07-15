/**
 * Кнопки по правилам design-tokens-ml-docs.md:
 * - primary: нейтральная заливка (buttonPrimaryBg/buttonPrimaryText) — для "создать запись" и т.п.
 * - accent: заливка акцентом — ИСКЛЮЧЕНИЕ, только для финального "Сформировать документ"
 * - secondary: прозрачный фон + обводка border
 */
export function Button({ variant = 'primary', size = 'md', className = '', ...props }) {
  const base =
    'font-sans font-semibold cursor-pointer transition-colors whitespace-nowrap inline-flex items-center justify-center gap-2';

  const sizes = {
    md: 'text-sm px-6 py-3 rounded-btn', // hero CTA
    sm: 'text-[13px] px-4 py-2.5 rounded-input', // компактные кнопки внутри карточек
  };

  const variants = {
    primary: 'bg-button-primary-bg text-button-primary-text border-none',
    accent: 'bg-accent text-white border-none',
    secondary: 'bg-transparent text-text border border-border',
  };

  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    />
  );
}
