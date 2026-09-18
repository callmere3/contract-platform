import { useCallback, useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { PageHeader } from '../components/ui/PageHeader';
import { TrashIcon } from '../components/ui/icons';
import { useAuth } from '../auth/AuthContext';
import { useModal } from '../modals/ModalProvider';
import { canManagePayments } from '../auth/permissions';
import { listPartners } from '../api/partners';
import { formatMoney } from '../api/finance';
import {
  createPayment,
  deletePayment,
  listPayments,
  updatePayment,
} from '../api/payments';

/**
 * ML Finance → «Поступления»: что реально пришло на счёт от площадок.
 *
 * КВАРТАЛ СВЕРХУ, МЕСЯЦЫ ВКЛАДКАМИ, таблица ниже (просьба владельца
 * 19.09.2026). Квартал — единица, которой считают отчёты, месяц — то, в чём
 * лежит выписка; поэтому и то и другое, а не один список за всё время.
 *
 * ТАБЛИЦА ПРАВИТСЯ ПРЯМО НА МЕСТЕ, без кнопки «сохранить»: «заведено» и
 * фактическую сумму проставляют через недели после платежа, и заставлять
 * человека каждый раз открывать окно правки ради одной галочки незачем.
 * Каждое поле уходит на сервер, когда его отпускают (blur) — сеть дёргается
 * на законченную правку, а не на каждую букву.
 *
 * СУММЫ СКЛАДЫВАЕТ СЕРВЕР: в JSON они строки (иначе 1234.10 уезжает в
 * 1234.0999999999999), и считать их на экране нельзя.
 */
const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const ROMAN = ['I', 'II', 'III', 'IV'];

const iso = (d) => d.toISOString().slice(0, 10);
const monthRange = (year, month) => ({
  from: iso(new Date(Date.UTC(year, month, 1))),
  to: iso(new Date(Date.UTC(year, month + 1, 0))),
});

export function PaymentsPage() {
  const { role } = useAuth();
  const { openModal } = useModal();
  const manage = canManagePayments(role);

  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [quarter, setQuarter] = useState(Math.floor(today.getMonth() / 3) + 1);
  // Месяц внутри квартала: 0, 1 или 2. Храним смещение, а не номер месяца, —
  // тогда переключение квартала не оставляет открытым чужой месяц.
  const [monthOffset, setMonthOffset] = useState(today.getMonth() % 3);

  const [partners, setPartners] = useState([]);
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const month = (quarter - 1) * 3 + monthOffset;
  const range = monthRange(year, month);

  useEffect(() => {
    listPartners({ pageSize: 500 })
      .then((d) => setPartners(d.partners ?? []))
      .catch((e) => setError(e.message));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listPayments({ dateFrom: range.from, dateTo: range.to });
      setRows(data.payments ?? []);
      setTotals(data.totals ?? null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [range.from, range.to]);

  useEffect(() => {
    load();
  }, [load]);

  /**
   * Правка одного поля. Значение сразу видно в таблице (иначе поле «прыгает»
   * под руками), а на сервер уходит только то, что тронули.
   */
  function edit(id, field, value) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  }

  async function save(id, field, value) {
    try {
      const { payment } = await updatePayment(id, { [field]: value });
      // Ответ сервера главнее набранного: он привёл сумму к копейкам, а дату
      // к своему виду, и показывать надо именно это.
      setRows((prev) => prev.map((r) => (r.id === id ? payment : r)));
      refreshTotals();
    } catch (e) {
      setError(e.message);
      load();
    }
  }

  // Итоги считает сервер, поэтому после каждой правки их перечитываем. Ради
  // одной суммы тянуть всю страницу заново незачем — запрос тот же, но он
  // дешёвый: строк за месяц десятки.
  async function refreshTotals() {
    try {
      const data = await listPayments({ dateFrom: range.from, dateTo: range.to });
      setTotals(data.totals ?? null);
    } catch {
      /* итоги — не повод пугать человека красной строкой */
    }
  }

  async function addRow() {
    setError('');
    try {
      // Дата новой строки — первое число открытого месяца: строку заводят в
      // том месяце, который смотрят, и подставлять сегодняшнее число
      // (декабрьское в июльской таблице) значило бы прятать её от глаз.
      const { payment } = await createPayment({ occurred_on: range.from });
      setRows((prev) => [...prev, payment]);
    } catch (e) {
      setError(e.message);
    }
  }

  // Спрашиваем своим окном, а не браузерным confirm: тот выглядит системным
  // окном и живёт вне общих правил (Escape, «назад», затемнение).
  function remove(row) {
    openModal('confirm', {
      title: 'Убрать строку?',
      message: 'Строка поступления удалится безвозвратно.',
      confirmLabel: 'Убрать',
      onConfirm: async () => {
        await deletePayment(row.id);
        load();
      },
    });
  }

  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-3 py-2 whitespace-nowrap';
  const td = 'px-3 py-1.5 align-middle border-t border-border';
  const cellInput =
    'w-full bg-transparent border border-transparent hover:border-border focus:border-accent rounded-input px-2 py-1.5 text-[13px] text-text outline-none font-sans';
  const tab = (active) =>
    `px-3 py-1.5 text-[12.5px] rounded-input border cursor-pointer bg-transparent font-sans ${
      active ? 'border-accent text-accent' : 'border-border text-text-secondary'
    }`;

  return (
    <div className="max-w-[1480px] mx-auto px-8 pt-12 pb-20">
      <PageHeader title="Поступления">
        Деньги, которые пришли от площадок: сумма, курс и сколько из неё завели.
      </PageHeader>

      <Card>
        <div className="p-5 border-b border-border flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            {[1, 2, 3, 4].map((q) => (
              <button
                key={q}
                type="button"
                className={tab(q === quarter)}
                onClick={() => {
                  setQuarter(q);
                  setMonthOffset(0);
                }}
              >
                {ROMAN[q - 1]} квартал
              </button>
            ))}
            <input
              value={year}
              onChange={(e) => setYear(Number(e.target.value.replace(/\D/g, '')) || '')}
              className="bg-input-bg border border-border rounded-input px-3 py-2 text-[13px] text-text outline-none font-sans w-[86px] tabular-nums"
            />
          </div>
        </div>

        {/* МЕСЯЦЫ КВАРТАЛА — отдельным рядом: квартал отвечает «какой отчётный
            период», месяц — «в какой выписке искать». Это два разных вопроса,
            и мешать их в один список нельзя. */}
        <div className="px-5 py-3 border-b border-border flex flex-wrap gap-2">
          {[0, 1, 2].map((offset) => (
            <button
              key={offset}
              type="button"
              className={tab(offset === monthOffset)}
              onClick={() => setMonthOffset(offset)}
            >
              {MONTHS[(quarter - 1) * 3 + offset]}
            </button>
          ))}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {error && <div className="px-5 py-3 text-[13px] text-danger">{error}</div>}

        {!loading && (
          <>
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Дата поступления</th>
                  <th className={th}>Партнёр</th>
                  <th className={th}>Описание платежа</th>
                  <th className={th}>Сумма поступления</th>
                  <th className={th}>Курс</th>
                  <th className={th}>Сумма завода</th>
                  <th className={th}>Заведено</th>
                  <th className={th}>Сумма фактического завода</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td className={`${td} text-[13px] text-text-muted`} colSpan={9}>
                      За этот месяц поступлений нет.
                    </td>
                  </tr>
                )}
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className={`${td} w-[150px]`}>
                      <input
                        type="date"
                        value={r.occurred_on ?? ''}
                        disabled={!manage}
                        onChange={(e) => edit(r.id, 'occurred_on', e.target.value)}
                        onBlur={(e) => e.target.value && save(r.id, 'occurred_on', e.target.value)}
                        className={`${cellInput} tabular-nums`}
                      />
                    </td>
                    <td className={`${td} w-[200px]`}>
                      {/* Площадку можно не выбирать: строку заводят по
                          выписке, а чей платёж — иногда выясняют потом. */}
                      <select
                        value={r.partner_id ?? ''}
                        disabled={!manage}
                        onChange={(e) => {
                          edit(r.id, 'partner_id', e.target.value);
                          save(r.id, 'partner_id', e.target.value);
                        }}
                        className={cellInput}
                      >
                        <option value="">— не указан —</option>
                        {partners.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className={td}>
                      <input
                        value={r.description ?? ''}
                        disabled={!manage}
                        placeholder="за что платёж"
                        onChange={(e) => edit(r.id, 'description', e.target.value)}
                        onBlur={(e) => save(r.id, 'description', e.target.value)}
                        className={cellInput}
                      />
                    </td>
                    {['amount', 'rate', 'transfer_amount'].map((field) => (
                      <td key={field} className={`${td} w-[130px]`}>
                        <input
                          value={r[field] ?? ''}
                          disabled={!manage}
                          onChange={(e) => edit(r.id, field, e.target.value)}
                          onBlur={(e) => save(r.id, field, e.target.value)}
                          className={`${cellInput} tabular-nums text-right`}
                        />
                      </td>
                    ))}
                    <td className={`${td} w-[90px] text-center`}>
                      <input
                        type="checkbox"
                        checked={!!r.transferred}
                        disabled={!manage}
                        onChange={(e) => {
                          edit(r.id, 'transferred', e.target.checked);
                          save(r.id, 'transferred', e.target.checked);
                        }}
                      />
                    </td>
                    <td className={`${td} w-[150px]`}>
                      <input
                        value={r.actual_amount ?? ''}
                        disabled={!manage}
                        onChange={(e) => edit(r.id, 'actual_amount', e.target.value)}
                        onBlur={(e) => save(r.id, 'actual_amount', e.target.value)}
                        className={`${cellInput} tabular-nums text-right`}
                      />
                    </td>
                    <td className={`${td} w-[40px] text-right`}>
                      {manage && (
                        <button
                          type="button"
                          onClick={() => remove(r)}
                          title="Убрать строку"
                          aria-label="Убрать строку"
                          className="text-danger bg-transparent border-0 cursor-pointer p-0"
                        >
                          <TrashIcon size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="px-5 py-4 flex flex-wrap items-center gap-4 border-t border-border">
              {manage && (
                <Button variant="secondary" size="sm" onClick={addRow}>
                  Добавить строку
                </Button>
              )}
              {totals && rows.length > 0 && (
                <div className="text-[13px] text-text">
                  Поступило <b className="tabular-nums">{formatMoney(totals.amount)}</b> · завод{' '}
                  <b className="tabular-nums">{formatMoney(totals.transfer_amount)}</b> ·
                  фактически <b className="tabular-nums">{formatMoney(totals.actual_amount)}</b>
                  {totals.not_transferred > 0 && (
                    <span className="text-text-muted"> · не заведено строк: {totals.not_transferred}</span>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
