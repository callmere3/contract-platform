import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { applyPaymentsImport, checkPaymentsImport } from '../api/payments';
import { formatMoney } from '../api/finance';

/**
 * Импорт поступлений: файл или вставленные строки (просьба владельца
 * 23.09.2026).
 *
 * ДВА ШАГА, «проверить» → «применить», как у номенклатуры и по той же
 * причине: файл собран руками по банковской выписке. В нём пустые полосы
 * между месяцами, подписи, «синхра» вместо «да» и НДС коэффициентом. Увидеть,
 * во что это превратилось, надо ДО записи, а не после.
 *
 * ВСТАВКА ИЗ БУФЕРА — второй вход наравне с файлом, как в номенклатуре: чаще
 * всего доносят несколько строк за неделю, и сохранять ради них файл из
 * Excel — лишнее движение. Ctrl+V слушает окно: своих текстовых полей здесь
 * нет, и заставлять сперва попасть курсором в прямоугольник незачем.
 *
 * ДУБЛИ ПРОПУСКАЮТСЯ ПО УМОЛЧАНИЮ. Файл заливают повторно, чтобы добрать
 * новые строки, а не чтобы завести старые второй раз. Ключ дубля — дата,
 * сумма и описание: своего номера у платежа в выписке нет.
 */
const ru = (iso) => {
  const [y, m, d] = String(iso || '').split('-');
  return y && m && d ? `${d}.${m}.${y}` : iso || '—';
};

export function PaymentsImportModal({ level, isTop, onDone }) {
  const { closeModal } = useModal();
  const [file, setFile] = useState(null);
  const [pasted, setPasted] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);
  const dropping = useRef(false);

  const check = useCallback(async (nextFile, nextPasted) => {
    setBusy(true);
    setError('');
    setPreview(null);
    try {
      setPreview(await checkPaymentsImport({ file: nextFile, pasted: nextPasted }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  // Ctrl+V по окну: Excel кладёт таблицу текстом с табуляцией.
  useEffect(() => {
    if (!isTop) return undefined;
    const onPaste = (e) => {
      const text = e.clipboardData?.getData('text/plain') || '';
      if (!text.includes('\t')) return;      // не таблица — не наше дело
      e.preventDefault();
      setFile(null);
      setPasted(text);
      setDone(null);
      check(null, text);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [isTop, check]);

  function pickFile(next) {
    if (!next) return;
    setFile(next);
    setPasted('');
    setDone(null);
    check(next, '');
  }

  async function apply() {
    setBusy(true);
    setError('');
    try {
      const result = await applyPaymentsImport({ file, pasted, skipDuplicates: true });
      setDone(result);
      onDone?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const totals = preview?.totals;
  const canApply = totals && totals.rows > totals.problems + totals.duplicates;

  return (
    <Modal
      title="Импорт поступлений"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={1180}
      footer={
        <>
          <span className="text-[12.5px] text-text-muted mr-auto">
            {done
              ? `Заведено строк: ${done.created}`
              : 'Сначала посмотрите, что получилось, потом применяйте'}
          </span>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            {done ? 'Закрыть' : 'Отмена'}
          </Button>
          {!done && (
            <Button size="sm" onClick={apply} disabled={busy || !canApply}>
              Применить
            </Button>
          )}
        </>
      }
    >
      {!done && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            dropping.current = true;
          }}
          onDrop={(e) => {
            e.preventDefault();
            dropping.current = false;
            pickFile(e.dataTransfer.files?.[0]);
          }}
          className="border border-dashed border-border rounded-card px-4 py-5 text-center mb-4"
        >
          <div className="text-[13px] text-text mb-1">
            Перетащите файл, выберите его или вставьте строки из Excel по Ctrl+V
          </div>
          <div className="text-[12px] text-text-muted mb-3">
            Книга Excel с листами-месяцами или скопированные строки таблицы
          </div>
          <input
            type="file"
            accept=".xlsx,.xlsm,.csv,.txt,.tsv"
            onChange={(e) => pickFile(e.target.files?.[0])}
            className="text-[12.5px] text-text-secondary"
          />
          {(file || pasted) && (
            <div className="text-[12px] text-text-muted mt-2">
              {file ? file.name : `вставлено строк: ${pasted.trim().split('\n').length}`}
            </div>
          )}
        </div>
      )}

      {busy && <div className="text-[13px] text-text-muted">Разбираю…</div>}
      {error && <div className="text-[13px] text-danger mb-3">{error}</div>}

      {done && (
        <div className="text-[13px] text-text">
          Заведено строк: <b>{done.created}</b>
          {done.duplicates > 0 && (
            <span className="text-text-muted">
              {' '}· пропущено как уже заведённые: {done.duplicates}
            </span>
          )}
          {done.skipped > 0 && (
            <span className="text-danger"> · не прошло из-за замечаний: {done.skipped}</span>
          )}
        </div>
      )}

      {!done && totals && (
        <>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-text mb-3">
            <span>
              Строк: <b className="tabular-nums">{totals.rows}</b>
            </span>
            <span>
              Поступило: <b className="tabular-nums">{formatMoney(totals.amount)}</b>
            </span>
            <span>
              Завод: <b className="tabular-nums">{formatMoney(totals.transfer_amount)}</b>
            </span>
            {totals.duplicates > 0 && (
              <span className="text-text-muted">уже заведено: {totals.duplicates}</span>
            )}
            {totals.problems > 0 && (
              <span className="text-danger">с замечаниями: {totals.problems}</span>
            )}
            {totals.unknown_partners > 0 && (
              <span className="text-text-muted">
                площадок нет в справочнике: {totals.unknown_partners}
              </span>
            )}
          </div>

          {/* Незнакомая площадка — НЕ ошибка: мелких партнёров по
              синхронизации в справочнике и не должно быть, их имя ляжет
              текстом. Говорим об этом прямо, иначе цифра выше читается как
              предупреждение. */}
          {totals.unknown_partners > 0 && (
            <div className="text-[12.5px] text-text-muted mb-3">
              Площадки, которых нет в справочнике, запишутся так, как названы в
              выписке. Это нормально: отчёты по ним мы не разбираем.
            </div>
          )}

          {/* ПРОКРУТКА ПО ОБЕИМ ОСЯМ НА ОДНОЙ КОРОБКЕ. Разносить их по двум
              вложенным нельзя: горизонтальная полоса тогда окажется под
              ПОСЛЕДНЕЙ строкой, и до неё придётся листать вниз — ровно то, на
              что жаловался владелец (24.09.2026). Здесь же она прибита к
              нижнему краю видимой области.

              Но лучшая полоса — та, которая не нужна: столбец «Лист» убран,
              окно стало шире, а колонки уже, и таблица помещается целиком. */}
          <div className="border border-border rounded-card overflow-auto max-h-[52vh]">
            <table className="w-full border-collapse text-[12.5px]">
              <thead className="sticky top-0 bg-surface">
                <tr>
                  {/* НАЗВАНИЕ ЛИСТА НЕ ПОКАЗЫВАЕМ (замечание владельца
                      24.09.2026): при вставке из буфера там стояло бы
                      бессмысленное «вставка», а у файла лист и так виден по
                      дате в соседнем столбце. Месяц строки берётся из её
                      даты, а не из имени листа, — поэтому книга с тремя
                      листами разложится по трём месяцам сама. */}
                  {['Дата', 'Партнёр', 'Описание', 'Поступление',
                    'В валюте', 'НДС', 'Завод', 'Заведено', ''].map((h) => (
                    <th
                      key={h}
                      className="text-left font-medium text-text-muted px-2 py-1.5 border-b border-border whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr
                    key={r.line}
                    className={r.problems.length ? 'bg-danger-soft' : undefined}
                  >
                    <td className="px-2 py-1.5 border-b border-border tabular-nums whitespace-nowrap">
                      {ru(r.occurred_on)}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border max-w-[170px] truncate">
                      {r.partner || <span className="text-text-muted">—</span>}
                      {r.partner && !r.partner_known && (
                        <span className="text-text-muted"> (текстом)</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border max-w-[200px] truncate text-text-muted">
                      {r.description}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border tabular-nums text-right whitespace-nowrap">
                      {r.amount ? formatMoney(r.amount) : '—'}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border tabular-nums text-right whitespace-nowrap">
                      {r.currency_amount ? `${r.currency_amount} ${r.currency || ''}` : ''}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border tabular-nums text-right">
                      {r.vat_rate != null ? `${String(r.vat_rate).replace('.', ',')}%` : ''}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border tabular-nums text-right whitespace-nowrap">
                      {r.transfer_amount ? formatMoney(r.transfer_amount) : '—'}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border text-center">
                      {r.transfer_status || ''}
                    </td>
                    <td className="px-2 py-1.5 border-b border-border whitespace-nowrap">
                      {r.duplicate && <span className="text-text-muted">уже заведено</span>}
                      {r.problems.length > 0 && (
                        <span className="text-danger">{r.problems.join('; ')}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}
