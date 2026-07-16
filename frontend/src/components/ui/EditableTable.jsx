/**
 * columns: [{ key, label, width }]  — width опционален (для №/НЛ узких колонок)
 * rows: [{ id, ...значения по key }]
 * onChangeCell(rowId, key, value)
 * onRemoveRow(rowId)
 * onAddRow()
 *
 * Кнопка «+ Добавить строку» — не отдельный элемент под таблицей, а её
 * футер: внутри той же рамки, с верхней границей и подложкой, как заголовок.
 */
export function EditableTable({ columns, rows, onChangeCell, onRemoveRow, onAddRow, addLabel }) {
  return (
    <div className="mb-5 border border-border rounded-input overflow-hidden">
      {/* Подсказки для комбо-колонок (исполнитель): один datalist на колонку,
          общий для всех строк. Ячейка ниже — обычный input со свободным вводом
          плюс list=... с этими подсказками (выбрать из списка ИЛИ вписать своё). */}
      {columns
        .filter((c) => c.type === 'combo' && c.options?.length)
        .map((c) => (
          <datalist key={c.key} id={`dl-${c.key}`}>
            {c.options.map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
        ))}
      <div style={{ display: 'table', tableLayout: 'fixed', width: '100%' }}>
        {/* Заголовок — подложка чуть темнее полотна, чтобы отделить шапку.
            Границы вешаем на ЯЧЕЙКИ, а не на table-row: по спецификации CSS
            border на display:table-row не рендерится (из-за этого строки
            раньше и не разделялись визуально). */}
        <div style={{ display: 'table-row' }} className="bg-surface-hover text-[11px] font-bold tracking-[0.04em] text-text-secondary uppercase">
          <div style={{ display: 'table-cell', width: 36 }} className="border-r border-border py-2.5 pl-3.5 pr-2">
            №
          </div>
          {columns.map((col) => (
            <div
              key={col.key}
              style={{ display: 'table-cell', width: col.width }}
              className="border-r border-border last:border-r-0 py-2.5 px-2"
            >
              {col.label}
            </div>
          ))}
          <div style={{ display: 'table-cell', width: 44 }} className="py-2.5 px-2" />
        </div>

        {/* Строки — верхняя граница на каждой ячейке отделяет строку от
            предыдущей (и первую строку от шапки). */}
        {rows.map((row, i) => (
          <div key={row.id} style={{ display: 'table-row' }} className="text-[13px] text-text">
            <div style={{ display: 'table-cell', width: 36 }} className="border-r border-t border-border py-2 pl-3.5 pr-2 text-text-muted tabular-nums">
              {i + 1}
            </div>
            {columns.map((col) => (
              <div
                key={col.key}
                style={{ display: 'table-cell', width: col.width }}
                className="border-r border-t border-border last:border-r-0 py-1.5 px-2"
              >
                {/* Тип ячейки диктует схема поля с сервера:
                    flag  — is_group / has_profanity (галочка внутри строки);
                    combo — колонка исполнителя: свободный ввод + подсказки из
                            псевдонимов контрагента (datalist), можно и выбрать,
                            и вписать своё (напр. приглашённого артиста);
                    иначе — обычный текстовый ввод. */}
                {col.type === 'flag' ? (
                  <input
                    type="checkbox"
                    checked={!!row[col.key]}
                    onChange={(e) => onChangeCell(row.id, col.key, e.target.checked)}
                    className="w-4 h-4 accent-accent block mx-auto"
                  />
                ) : (
                  <input
                    value={row[col.key] ?? ''}
                    onChange={(e) => onChangeCell(row.id, col.key, e.target.value)}
                    list={col.type === 'combo' && col.options?.length ? `dl-${col.key}` : undefined}
                    className="w-full bg-transparent border-none outline-none text-[13px] text-text font-sans"
                  />
                )}
              </div>
            ))}
            <div
              style={{ display: 'table-cell', width: 44 }}
              onClick={() => onRemoveRow(row.id)}
              className="border-t border-border text-text-muted cursor-pointer text-center py-2 px-2 hover:text-accent"
            >
              ×
            </div>
          </div>
        ))}
      </div>

      {/* Футер таблицы: кнопка добавления строки как часть таблицы. */}
      <button
        type="button"
        onClick={onAddRow}
        className="w-full text-left bg-surface-hover border-t border-border py-2.5 px-3.5 text-[12px] font-semibold text-text-secondary hover:text-text hover:bg-surface transition-colors cursor-pointer font-sans"
      >
        {addLabel ?? '+ Добавить строку'}
      </button>
    </div>
  );
}
