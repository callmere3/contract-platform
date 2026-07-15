import { Button } from './Button';

/**
 * columns: [{ key, label, width }]  — width опционален (для №/НЛ узких колонок)
 * rows: [{ id, ...значения по key }]
 * onChangeCell(rowId, key, value)
 * onRemoveRow(rowId)
 * onAddRow()
 */
export function EditableTable({ columns, rows, onChangeCell, onRemoveRow, onAddRow, addLabel }) {
  return (
    <div className="mb-5">
      <div className="border border-border rounded-input overflow-hidden">
        <div className="w-full table-fixed" style={{ display: 'table', tableLayout: 'fixed', width: '100%' }}>
          {/* Заголовок */}
          <div style={{ display: 'table-row' }} className="bg-input-bg text-[11px] font-bold tracking-[0.04em] text-text-muted">
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

          {/* Строки */}
          {rows.map((row, i) => (
            <div key={row.id} style={{ display: 'table-row' }} className="text-[13px] text-text border-t border-border">
              <div style={{ display: 'table-cell', width: 36 }} className="border-r border-border py-2 pl-3.5 pr-2">
                {i + 1}
              </div>
              {columns.map((col) => (
                <div
                  key={col.key}
                  style={{ display: 'table-cell', width: col.width }}
                  className="border-r border-border last:border-r-0 py-1.5 px-2"
                >
                  {/* Тип ячейки диктует схема поля с сервера:
                      flag  — is_group / has_profanity (галочка внутри строки);
                      select — колонка исполнителя, когда у контрагента есть
                               псевдонимы (тогда выбираем из них, а не пишем
                               руками);
                      иначе — обычный текстовый ввод. */}
                  {col.type === 'flag' ? (
                    <input
                      type="checkbox"
                      checked={!!row[col.key]}
                      onChange={(e) => onChangeCell(row.id, col.key, e.target.checked)}
                      className="w-4 h-4 accent-accent block mx-auto"
                    />
                  ) : col.type === 'select' ? (
                    <select
                      value={row[col.key] ?? ''}
                      onChange={(e) => onChangeCell(row.id, col.key, e.target.value)}
                      className="w-full bg-transparent border-none outline-none text-[13px] text-text font-sans"
                    >
                      <option value="">—</option>
                      {col.options?.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={row[col.key] ?? ''}
                      onChange={(e) => onChangeCell(row.id, col.key, e.target.value)}
                      className="w-full bg-transparent border-none outline-none text-[13px] text-text font-sans"
                    />
                  )}
                </div>
              ))}
              <div
                style={{ display: 'table-cell', width: 44 }}
                onClick={() => onRemoveRow(row.id)}
                className="text-text-muted cursor-pointer text-center py-2 px-2"
              >
                ×
              </div>
            </div>
          ))}
        </div>
      </div>

      <Button variant="secondary" size="sm" onClick={onAddRow}>
        {addLabel ?? '+ Добавить строку'}
      </Button>
    </div>
  );
}
