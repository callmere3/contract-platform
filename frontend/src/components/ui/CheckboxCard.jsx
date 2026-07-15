/** Чекбокс в обводке-карточке — для заметных опций типа "Есть видеоклип". */
export function CheckboxCard({ label, hint, checked, onChange }) {
  return (
    <div className="border border-border rounded-input px-4 py-3.5">
      <label className="flex items-center gap-2.5 text-sm text-text cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={onChange}
          className="w-4 h-4 accent-accent"
        />
        {label}
      </label>
      {hint && (
        <div className="text-[11px] text-text-muted mt-1.5 ml-[26px] leading-snug">
          {hint}
        </div>
      )}
    </div>
  );
}

/** Обычный инлайн-чекбокс без рамки — для менее заметных опций типа "Исполнитель — группа". */
export function InlineCheckbox({ label, hint, checked, onChange }) {
  return (
    <label className="flex items-center gap-2.5 text-sm text-text cursor-pointer mb-5">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="w-4 h-4 accent-accent"
      />
      {label}
      {hint && <span className="text-[11px] text-text-muted font-normal">{hint}</span>}
    </label>
  );
}
