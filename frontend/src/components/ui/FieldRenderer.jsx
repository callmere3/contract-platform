/**
 * Рендер одного поля формы генерации по схеме с сервера
 * (GET /templates/{id}/fields → template_analysis.py):
 *   { name, label, type: 'text'|'choice'|'date'|'flag'|'list', hint?, default?,
 *     choices?, item_fields?, maps_to?, nickname_options? }
 *
 * type='list' здесь НЕ обрабатывается — списки рисует EditableTable
 * отдельно (у них своя логика строк и автоподстановки).
 *
 * nickname_options — приходит только для поля с maps_to='contragent.nickname',
 * когда форма открыта по конкретному контрагенту: у него может быть
 * несколько псевдонимов, и вместо ручного ввода даём выбор из его же
 * списка (см. get_template_fields на бэкенде).
 *
 * readOnly — только для 'contract' (номер договора) при генерации по
 * контрагенту: значение берётся из карточки и правке не подлежит, но
 * выглядит как обычный input, без серого disabled-вида
 * (см. design-tokens-ml-docs.md §6.1).
 */
export function FieldRenderer({ field, value, onChange, readOnly = false }) {
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
        {field.hint && <span className="text-[11px] text-text-muted font-normal">{field.hint}</span>}
      </label>
    );
  }

  const hasNicknameOptions = Array.isArray(field.nickname_options) && field.nickname_options.length > 0;

  return (
    <div>
      <div className="text-xs text-text-secondary mb-1.5">{field.label}</div>

      {field.type === 'choice' ? (
        <select value={value ?? ''} onChange={(e) => onChange(e.target.value)} className={controlClass}>
          {field.choices?.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      ) : hasNicknameOptions ? (
        <select value={value ?? ''} onChange={(e) => onChange(e.target.value)} className={controlClass}>
          {/* Пустой вариант нужен: nickname — необязательная метка (см.
              optional в generate_document), у контрагента может не быть
              псевдонима вовсе, и это законно. */}
          <option value="">—</option>
          {field.nickname_options.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === 'date' ? 'date' : 'text'}
          value={value ?? ''}
          readOnly={readOnly}
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
