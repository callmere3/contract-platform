/**
 * Схема поля повторяет форму реального API (template_analysis.py → GET /templates/{id}/fields):
 *   { name, label, type: 'text'|'choice'|'date'|'flag', hint?, default?, choices?, readOnly? }
 * `readOnly` — расширение поверх схемы для конкретно "номер договора"
 * (фактически нередактируемое поле, см. design-tokens-ml-docs.md §6.1).
 */
export function FieldRenderer({ field, value, onChange }) {
  const controlClass =
    'w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text outline-none font-sans';

  if (field.type === 'flag') {
    return (
      <label className="flex items-center gap-2.5 text-sm text-text cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="w-4 h-4 accent-accent"
        />
        {field.label}
        {field.hint && (
          <span className="text-[11px] text-text-muted font-normal">{field.hint}</span>
        )}
      </label>
    );
  }

  return (
    <div>
      <div className="text-xs text-text-secondary mb-1.5">{field.label}</div>

      {field.type === 'choice' ? (
        <select
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className={controlClass}
        >
          {field.choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === 'date' ? 'date' : 'text'}
          value={value ?? field.default ?? ''}
          readOnly={field.readOnly}
          onChange={(e) => onChange(e.target.value)}
          className={controlClass}
        />
      )}

      {field.hint && (
        <div className="text-[11px] text-text-muted mt-1.5 leading-snug">{field.hint}</div>
      )}
    </div>
  );
}
