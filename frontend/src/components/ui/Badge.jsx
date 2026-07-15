export function Badge({ children, variant = 'accent', className = '' }) {
  const variants = {
    // код контрагента, статус — accentSoft фон + accent текст
    accent: 'bg-accent-soft text-accent font-semibold',
    // мета-бейдж (роль пользователя и т.п.) — нейтральная обводка
    neutral: 'border border-border text-text-muted',
    // pill-бейдж hero-блока
    pill: 'bg-accent-soft text-accent font-semibold rounded-full',
  };

  const shape = variant === 'pill' ? '' : 'rounded-badge';

  return (
    <span
      className={`inline-block text-[11px] tracking-[0.03em] px-2.5 py-1 whitespace-nowrap ${shape} ${variants[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
