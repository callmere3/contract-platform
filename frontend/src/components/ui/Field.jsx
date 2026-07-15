/**
 * Универсальное поле формы: лейбл (12px secondary) → контрол → подсказка (11px muted).
 * `as="select"` рендерит select вместо input; children в этом случае — опции.
 */
export function Field({ label, hint, as = 'input', children, ...controlProps }) {
  const controlClass =
    'w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text outline-none font-sans';

  return (
    <div>
      <div className="text-xs text-text-secondary mb-1.5">{label}</div>
      {as === 'select' ? (
        <select className={controlClass} {...controlProps}>
          {children}
        </select>
      ) : (
        <input className={controlClass} {...controlProps} />
      )}
      {hint && (
        <div className="text-[11px] text-text-muted mt-1.5 leading-snug">{hint}</div>
      )}
    </div>
  );
}

/** Заголовок секции формы: ДОКУМЕНТ / КОНТРАГЕНТ / РЕЛИЗ / ТРЕКИ */
export function SectionLabel({ children }) {
  return (
    <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-4">
      {children}
    </div>
  );
}
