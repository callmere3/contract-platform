import { useState } from 'react';
import { useTags } from '../../api/TagsContext';

/**
 * Сворачиваемый блок реквизитов контрагента (адреса, банк, паспорт СГ, ЭДО-
 * почта/НДС и т.п.). По умолчанию СКРЫТ — чтобы не перегружать карточку.
 *
 * Набор полей и их подписи/типы приходят с сервера (GET /tags →
 * requisite_fields_by_type[тип]) — фронт их не хардкодит. reg_number сюда не
 * входит (он отдельное поле карточки).
 *
 * Режимы:
 *   readOnly — просмотр (карточка контрагента): показывает только заполненные
 *              реквизиты, значениями (для choice — подпись варианта, для date —
 *              ДД.ММ.ГГГГ).
 *   иначе    — правка: инпуты; onChange(name, value) на каждое изменение.
 *
 * values — {имя_метки: значение}. Тип поля (text/date/choice) определяет контрол.
 */
const CONTROL =
  'w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text outline-none font-sans';

function displayValue(field, raw) {
  if (field.type === 'choice') {
    const opt = field.choices?.find((c) => c.value === String(raw));
    return opt ? opt.label : String(raw);
  }
  if (field.type === 'date') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(raw));
    if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  }
  return String(raw);
}

const isFilled = (v) => (v ?? '').toString().trim() !== '';

export function RequisitesSection({
  contragentType,
  values,
  onChange,
  readOnly = false,
  defaultOpen = false,
  title = 'Реквизиты',
  // Рег. номер (ИНН/ОГРНИП/ОГРН/БИН) показываем ПЕРВЫМ полем блока — «всё в
  // одном месте» (по просьбе владельца). Он НЕ часть словаря requisites
  // (отдельная колонка-идентификатор), поэтому едет отдельными пропсами и
  // зеркалит верхнее поле рег. номера в форме. Если regNumberLabel не задан
  // (тип не выбран) — строку рег. номера не показываем.
  regNumber,
  onRegNumberChange,
  regNumberLabel,
  regNumberHint,
}) {
  const { requisite_fields_by_type: byType } = useTags();
  const fields = byType?.[contragentType] || [];
  const [open, setOpen] = useState(defaultOpen);

  const hasReg = Boolean(regNumberLabel);
  const regFilled = isFilled(regNumber);

  // Тип без набора реквизитов И без рег. номера (не выбран) — блока нет вовсе.
  if (fields.length === 0 && !hasReg) return null;

  const filledCount =
    (hasReg && regFilled ? 1 : 0) + fields.filter((f) => isFilled(values?.[f.name])).length;

  return (
    <div className="border-t border-border pt-4 mt-5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-[11px] font-bold tracking-[0.08em] text-text-muted"
      >
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        {title.toUpperCase()}
        <span className="font-normal tracking-normal">
          {filledCount > 0 ? `· заполнено ${filledCount}` : '· пусто'}
        </span>
      </button>

      {open && (
        <div className="grid grid-cols-2 gap-3 mt-3">
          {/* Рег. номер — первым, отдельно от словаря requisites (зеркалит
              верхнее поле формы). Показ/правка по тем же правилам, что и
              остальные реквизиты. */}
          {hasReg &&
            (readOnly ? (
              <div>
                <div className="text-xs text-text-secondary mb-0.5">{regNumberLabel}</div>
                <div className={`text-sm break-words ${regFilled ? 'text-text' : 'text-text-muted'}`}>
                  {regFilled ? regNumber : '—'}
                </div>
              </div>
            ) : (
              <div>
                <div className="text-xs text-text-secondary mb-1.5">{regNumberLabel}</div>
                <input
                  className={CONTROL}
                  type="text"
                  value={regNumber ?? ''}
                  onChange={(e) => onRegNumberChange(e.target.value)}
                  placeholder={regNumberHint || 'только цифры'}
                />
              </div>
            ))}
          {readOnly ? (
            // Показываем ВСЕ поля, а не только заполненные: пустые — с прочерком,
            // чтобы менеджер видел, что именно надо дозаполнить (иначе непонятно,
            // каких реквизитов не хватает).
            fields.map((f) => {
              const filled = isFilled(values?.[f.name]);
              return (
                <div key={f.name}>
                  <div className="text-xs text-text-secondary mb-0.5">{f.label}</div>
                  <div className={`text-sm break-words ${filled ? 'text-text' : 'text-text-muted'}`}>
                    {filled ? displayValue(f, values[f.name]) : '—'}
                  </div>
                </div>
              );
            })
          ) : (
            fields.map((f) => (
              <div key={f.name}>
                <div className="text-xs text-text-secondary mb-1.5">{f.label}</div>
                {f.type === 'choice' ? (
                  <select
                    className={CONTROL}
                    value={values?.[f.name] ?? ''}
                    onChange={(e) => onChange(f.name, e.target.value)}
                  >
                    <option value="">— не выбрано —</option>
                    {(f.choices || []).map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={CONTROL}
                    type={f.type === 'date' ? 'date' : 'text'}
                    value={values?.[f.name] ?? ''}
                    onChange={(e) => onChange(f.name, e.target.value)}
                    placeholder={f.type === 'date' ? '' : f.hint || ''}
                  />
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
