import { useCallback, useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { listPayments } from '../api/payments';
import { linkReportPayment, unlinkReportPayment } from '../api/partnerReports';
import { formatMoney } from '../api/finance';

/**
 * «К какому поступлению относится этот отчёт» (19.09.2026, просьба владельца).
 *
 * Отчёт говорит, что площадка насчитала; поступление — что пришло на счёт.
 * Связав их, мы отвечаем на вопрос «по чему пришли эти деньги», и у строки
 * поступления заполняется СУММА ФАКТИЧЕСКОГО ЗАВОДА — итог привязанных к ней
 * отчётов (считает сервер: числа уже в базе, и вводить их руками значит
 * однажды ошибиться в третьем знаке).
 *
 * СНАЧАЛА КВАРТАЛ, ПОТОМ СТРОКА: платёж приходит позже отчётного периода — за
 * второй квартал платят в третьем, — поэтому квартал поступления выбирают
 * отдельно, а не подставляют из отчёта.
 *
 * ПЛОЩАДКУ СВЕРЯЕТ СЕРВЕР: отчёт МТС нельзя подшить к платежу другой
 * площадки. Здесь мы лишь показываем это заранее — строки чужих площадок
 * видно, но выбрать их нельзя: спрятать их значило бы оставить человека
 * гадать, почему нужной строки нет.
 */
const ROMAN = ['I', 'II', 'III', 'IV'];
const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const SHORT = [
  'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
];
const iso = (d) => d.toISOString().slice(0, 10);
const quarterRange = (year, quarter) => ({
  from: iso(new Date(Date.UTC(year, (quarter - 1) * 3, 1))),
  to: iso(new Date(Date.UTC(year, quarter * 3, 0))),
});
const monthRange = (year, month) => ({
  from: iso(new Date(Date.UTC(year, month, 1))),
  to: iso(new Date(Date.UTC(year, month + 1, 0))),
});
const ru = (isoDate) => {
  const [y, m, d] = String(isoDate || '').split('-');
  return y && m && d ? `${d}.${m}.${y}` : isoDate;
};

/**
 * Одна ли это сумма. СРАВНИВАЕМ КАК СТРОКИ, приведя к копейкам.
 *
 * `Number()` на деньгах — тот самый способ получить 1234.0999999999999, от
 * которого мы бережёмся по всему ML Finance. Складывать и делить здесь нечего,
 * нужен ровно вопрос «одно и то же число или нет», а на него отвечает
 * приведение к виду «целое.дд».
 */
const kopecks = (value) => {
  const text = String(value ?? '').replace(/\s/g, '').replace(',', '.');
  if (!/^-?\d+(\.\d*)?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  return `${whole}.${(fraction + '00').slice(0, 2)}`;
};
const sameMoney = (a, b) => {
  const one = kopecks(a);
  return one !== null && one === kopecks(b);
};

export function LinkReportPaymentModal({ report, level, isTop, onChanged }) {
  const { closeModal } = useModal();
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [quarter, setQuarter] = useState(Math.floor(today.getMonth() / 3) + 1);
  // НОМЕР ПОСТУПЛЕНИЯ СВОЙ У КАЖДОГО МЕСЯЦА, а в квартале месяцев три — и
  // «№1» встречается трижды (замечание владельца 23.09.2026). Поэтому здесь
  // есть выбор месяца, а пока смотрят квартал целиком, рядом с номером
  // подписан месяц: иначе строки не различить.
  const [monthOffset, setMonthOffset] = useState(null);   // null — весь квартал
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const range =
    monthOffset === null
      ? quarterRange(year, quarter)
      : monthRange(year, (quarter - 1) * 3 + monthOffset);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listPayments({ dateFrom: range.from, dateTo: range.to });
      setRows(data.payments ?? []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [range.from, range.to]);

  useEffect(() => {
    load();
  }, [load]);

  async function link(payment) {
    setBusy(true);
    setError('');
    try {
      await linkReportPayment(report.id, payment.id);
      onChanged?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError('');
    try {
      await unlinkReportPayment(report.id);
      onChanged?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  // РЕКОМЕНДУЕМАЯ СТРОКА ИДЁТ ПЕРВОЙ (просьба владельца 24.09.2026).
  // Совпали площадка и сумма завода — это и есть тот платёж, и искать его
  // глазами в списке из тридцати строк незачем.
  //
  // Сверяем именно СУММУ ЗАВОДА: привязка нужна затем, чтобы она сошлась с
  // фактическим заводом, и итог отчёта сравнивают с ней. Сумма поступления к
  // сверке отношения не имеет — это то, что упало на счёт, вместе с чужими
  // деньгами и до всех пересчётов.
  //
  // Совпадений может быть несколько (одна площадка платит дважды на ту же
  // сумму) — тогда наверху окажутся все: выбрать всё равно человеку.
  const advised = (p) =>
    p.id !== report.payment_id &&
    !!p.partner_id &&
    p.partner_id === report.partner_id &&
    sameMoney(p.transfer_amount, report.total);
  const ordered = [...rows.filter(advised), ...rows.filter((p) => !advised(p))];
  const adviceCount = rows.filter(advised).length;

  const tab = (active) =>
    `px-3 py-1.5 text-[12.5px] rounded-input border cursor-pointer bg-transparent font-sans ${
      active ? 'border-accent text-accent' : 'border-border text-text-secondary'
    }`;

  return (
    <Modal
      title="Поступление по отчёту"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={760}
      footer={
        report.payment_id ? (
          <>
            <span className="text-[12.5px] text-text-muted mr-auto">
              Отчёт привязан к поступлению{' '}
              {report.payment_label || `от ${ru(report.payment_date)}`}
            </span>
            <Button variant="secondary" size="sm" onClick={unlink} disabled={busy}>
              Отвязать
            </Button>
          </>
        ) : null
      }
    >
      <div className="text-[13px] text-text mb-4">
        <b>{report.partner}</b> · {report.period_label} · итог{' '}
        <b className="tabular-nums">{formatMoney(report.total)}</b>
      </div>

      <div className="text-[12px] text-text-secondary mb-1.5">Квартал поступления</div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {[1, 2, 3, 4].map((q) => (
          <button key={q} type="button" className={tab(q === quarter)} onClick={() => setQuarter(q)}>
            {ROMAN[q - 1]} квартал
          </button>
        ))}
        <input
          value={year}
          onChange={(e) => setYear(Number(e.target.value.replace(/\D/g, '')) || '')}
          className="bg-input-bg border border-border rounded-input px-3 py-2 text-[13px] text-text outline-none font-sans w-[86px] tabular-nums"
        />
      </div>

      <div className="text-[12px] text-text-secondary mb-1.5">Месяц</div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button type="button" className={tab(monthOffset === null)} onClick={() => setMonthOffset(null)}>
          Весь квартал
        </button>
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

      {loading && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-danger mb-3">{error}</div>}

      {!loading && rows.length === 0 && (
        <div className="text-[13px] text-text-muted">
          За этот квартал поступлений нет — заведите строку во вкладке «Поступления».
        </div>
      )}

      {!loading && adviceCount > 0 && (
        <div className="text-[12px] text-accent mb-1.5">
          {adviceCount === 1
            ? 'Похоже, это первая строка — площадка и сумма завода совпали.'
            : `Наверху ${adviceCount} строки, где совпали площадка и сумма завода.`}
        </div>
      )}

      {!loading && rows.length > 0 && (
        <div className="border border-border rounded-card divide-y divide-border max-h-[320px] overflow-y-auto">
          {ordered.map((p) => {
            // Чужая площадка — строку видно, но выбрать нельзя: сервер такую
            // связку не примет, и лучше сказать об этом здесь, чем дать
            // нажать и показать отказ.
            const otherPartner = p.partner_id && p.partner_id !== report.partner_id;
            const current = p.id === report.payment_id;
            const advice = advised(p);
            return (
              <button
                key={p.id}
                type="button"
                disabled={busy || otherPartner || current}
                onClick={() => link(p)}
                className={`block w-full text-left px-3 py-2.5 border-0 font-sans ${
                  advice ? 'bg-accent-soft' : 'bg-transparent'
                } ${
                  otherPartner || current ? 'cursor-default' : 'cursor-pointer hover:bg-hover'
                }`}
              >
                <div className="flex items-baseline gap-3 text-[13px]">
                  {/* НОМЕР, А НЕ ДАТА (просьба владельца 23.09.2026): им
                      человек называет строку, глядя в таблицу поступлений, и
                      квартал здесь уже выбран сверху — дата ничего не
                      различает, за месяц её повторяет половина строк. Сама
                      дата осталась в подсказке. */}
                  <span
                    className="text-text tabular-nums shrink-0"
                    title={`Поступление от ${ru(p.occurred_on)}`}
                  >
                    {p.number ? `№${p.number}` : '—'}
                    {monthOffset === null && (
                      <span className="text-text-muted">
                        {' '}
                        {SHORT[Number(String(p.occurred_on).slice(5, 7)) - 1]}
                      </span>
                    )}
                  </span>
                  <span className={otherPartner ? 'text-danger' : 'text-text-secondary'}>
                    {p.partner || 'площадка не указана'}
                  </span>
                  <span className="text-text-muted flex-1 truncate">{p.description || ''}</span>
                  {/* ЗДЕСЬ СУММА ЗАВОДА, А НЕ СУММА ПОСТУПЛЕНИЯ (уточнение
                      владельца 23.09.2026): привязка отчёта нужна как раз
                      затем, чтобы завод сошёлся с фактическим заводом, и
                      сравнивать надо эти два числа. Сумма поступления к
                      сверке отношения не имеет — это то, что упало на счёт,
                      вместе с чужими деньгами и до всех пересчётов.

                      ПУСТО И НОЛЬ — РАЗНЫЕ ВЕЩИ: formatMoney(null) рисует
                      «0,00 ₽», и строка выглядела платежом на нулевую сумму,
                      хотя число просто ещё не занесли. */}
                  {p.transfer_amount ? (
                    <span className="text-text tabular-nums">
                      {formatMoney(p.transfer_amount)}
                    </span>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </div>
                <div className="text-[11.5px] mt-0.5">
                  {current ? (
                    <span className="text-text-muted">отчёт уже привязан к этой строке</span>
                  ) : otherPartner ? (
                    <span className="text-text-muted">другая площадка — привязать нельзя</span>
                  ) : advice ? (
                    /* Говорим, ПОЧЕМУ строка наверху: подсказка, за которой
                       не видно основания, — это гадание, а человек отвечает
                       за то, к чему привязал деньги. */
                    <span className="text-accent">
                      похоже, эта: площадка и сумма завода совпали
                    </span>
                  ) : (
                    <span className="text-text-muted">
                      {`фактический завод: ${
                        p.actual_amount ? formatMoney(p.actual_amount) : 'пока пусто'
                      }`}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
