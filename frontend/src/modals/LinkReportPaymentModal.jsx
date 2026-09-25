import { useCallback, useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { Spinner } from '../components/ui/Spinner';
import { useModal } from './ModalProvider';
import { listPayments } from '../api/payments';
import {
  CURRENCY_SIGNS,
  linkReportPayment,
  rateText,
  unlinkReportPayment,
} from '../api/partnerReports';
import { formatMoney } from '../api/finance';
import Region from '../components/ui/Region';

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
 * Сумма в КОПЕЙКАХ, целым числом, — или null, если это не число.
 *
 * Деньги приходят строками, и `Number('1234.10')` — тот самый способ получить
 * 1234.0999999999999, от которого мы бережёмся по всему ML Finance. Целые
 * копейки складывать и вычитать можно без оглядки: рублёвые суммы до сотни
 * триллионов укладываются в точное целое.
 */
const kopecks = (value) => {
  const text = String(value ?? '').replace(/\s/g, '').replace(',', '.');
  if (!/^-?\d+(\.\d*)?$/.test(text)) return null;
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = text.replace('-', '').split('.');
  const total = Number(whole) * 100 + Number((fraction + '00').slice(0, 2));
  return negative ? -total : total;
};

/**
 * Одна ли это сумма — С ДОПУСКОМ В РУБЛЬ.
 *
 * Сначала допуск был копейкой, как у знака «≠» в таблице поступлений
 * (отчёт «101 и К»: 48 063,78 против 48 063,79 в выписке). Но у МегаФона
 * расхождение выходит больше: площадка округляет вознаграждение В КАЖДОЙ
 * строке, а мы считаем по формуле и округляем один раз, в итоге. На двухстах
 * строках набегает 11 копеек (июнь 2026), и подсказка молчала ровно там,
 * где совпадение очевидно (просьба владельца 24.09.2026).
 *
 * РУБЛЬ — ТОЛЬКО ДЛЯ ПОДСКАЗКИ. Знак «≠» в поступлениях по-прежнему
 * ставится от копейки: подсказка лишь поднимает строку наверх, а решает и
 * нажимает человек, и остаток он видит в столбце «Расхождение».
 */
const ADVICE_TOLERANCE = 100; // в копейках

const closeMoney = (a, b) => {
  const one = kopecks(a);
  const other = kopecks(b);
  return one !== null && other !== null && Math.abs(one - other) <= ADVICE_TOLERANCE;
};

export function LinkReportPaymentModal({ report, level, isTop, onChanged }) {
  const { closeModal } = useModal();
  // УЖЕ ПРИВЯЗАННЫЙ ОТЧЁТ ОТКРЫВАЕТСЯ НА СВОЁМ МЕСЯЦЕ (просьба владельца
  // 24.09.2026): там его строка и соседи, среди которых выбирают замену.
  // Раньше окно всегда открывалось на текущем квартале.
  const linkedOn = report.payment_date ? new Date(`${report.payment_date}T00:00:00Z`) : null;
  const today = linkedOn ?? new Date();
  const [year, setYear] = useState(today.getUTCFullYear?.() ?? today.getFullYear());
  const [quarter, setQuarter] = useState(
    Math.floor((linkedOn ? today.getUTCMonth() : today.getMonth()) / 3) + 1,
  );
  // НОМЕР ПОСТУПЛЕНИЯ СВОЙ У КАЖДОГО МЕСЯЦА, а в квартале месяцев три — и
  // «№1» встречается трижды (замечание владельца 23.09.2026). Поэтому здесь
  // есть выбор месяца, а пока смотрят квартал целиком, рядом с номером
  // подписан месяц: иначе строки не различить.
  const [monthOffset, setMonthOffset] = useState(
    linkedOn ? linkedOn.getUTCMonth() % 3 : null,          // null — весь квартал
  );
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // ЧТО ИМЕННО ДЕЛАЕМ — для индикатора (просьба владельца 24.09.2026):
  // привязка большого валютного отчёта пересчитывает сотни тысяч строк и идёт
  // десятки секунд, и без движения на экране кажется, что сервис завис.
  const [action, setAction] = useState(null);
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
    setAction('link');
    setError('');
    try {
      const res = await linkReportPayment(report.id, payment.id);
      onChanged?.(res?.report);
      // СУММА В ВАЛЮТЕ НЕ СОШЛАСЬ — окно не закрываем: отчёт привязан, но
      // курс не поставлен, и человек должен увидеть почему, а не гадать, отчего
      // суммы остались в валюте.
      const check = res?.currency_check;
      if (check && !check.matches) {
        setError(
          `Привязано, но сумма в валюте не сошлась: в отчёте ${check.report} ${check.currency}, ` +
            `в поступлении ${check.payment ?? 'не указана'}${check.payment_currency ? ' ' + check.payment_currency : ''}. ` +
            'Курс не поставлен — задайте его в окне отчёта.',
        );
        setBusy(false);
        setAction(null);
        return;
      }
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
      setAction(null);
    }
  }

  async function unlink() {
    setBusy(true);
    setAction('unlink');
    setError('');
    try {
      const res = await unlinkReportPayment(report.id);
      onChanged?.(res?.report);
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
      setAction(null);
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
  // У ВАЛЮТНОГО ОТЧЁТА ПОДХОДЯЩАЯ СТРОКА — ПО СУММЕ В ВАЛЮТЕ, а не по сумме
  // завода: курс к рублю ещё не известен (или выведен из того же платежа), и
  // сравнивать рубли значило бы сравнивать отчёт с самим собой. Сверка в
  // валюте — с точностью до цента, как и на сервере.
  const foreign = Boolean(report.currency && report.currency !== 'RUB' && report.currency_total);
  const inCurrency = (p) => {
    const text = String(p.currency_amount ?? '');
    const sign = CURRENCY_SIGNS[report.currency];
    if (!text || (sign && /[$€₸₽]/.test(text) && !text.includes(sign))) return false;
    const digits = text.replace(/[^\d,.-]/g, '');
    return closeMoney(digits, report.currency_total);
  };
  const advised = (p) =>
    p.id !== report.payment_id &&
    !!p.partner_id &&
    p.partner_id === report.partner_id &&
    (foreign ? inCurrency(p) : closeMoney(p.transfer_amount, report.total));
  // ТЕКУЩАЯ ПРИВЯЗКА — ПЕРВОЙ, ЗА НЕЙ ВЕСЬ СПИСОК (просьба владельца
  // 24.09.2026). Окно открывают «изменить», то есть затем, чтобы выбрать
  // другую строку, — и выбрать её можно сразу: нажатие перепривязывает, а
  // прежний платёж сервер пересчитает сам. Прежде у привязанного отчёта
  // была видна одна его строка, и до списка вели ещё «Отвязать» и повторное
  // открытие — два лишних действия.
  const current = rows.filter((p) => p.id === report.payment_id);
  const rest = rows.filter((p) => p.id !== report.payment_id);
  const shown = [...current, ...rest.filter(advised), ...rest.filter((p) => !advised(p))];
  const adviceCount = rest.filter(advised).length;

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
      // Внизу только «Отвязать»: с чем связан отчёт, видно первой строкой
      // списка, и повторять это подписью незачем (просьба владельца).
      footer={
        report.payment_id ? (
          <Button variant="secondary" size="sm" onClick={unlink} disabled={busy}>
            {action === 'unlink' ? 'Отвязываем…' : 'Отвязать'}
          </Button>
        ) : null
      }
    >
      {/* ПОКА ИДЁТ ЗАПРОС — ТОЛЬКО ИНДИКАТОР: список прячем, чтобы не нажать
          вторую строку, пока пересчитывается первая. */}
      {action ? (
        <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
          <Spinner size={36} className="text-accent" />
          <div className="text-[14px] text-text">
            {action === 'link' ? 'Привязываем отчёт к поступлению…' : 'Отвязываем от поступления…'}
          </div>
          <div className="text-[12.5px] text-text-muted max-w-[420px]">
            У большого отчёта это может занять до минуты: суммы всех строк
            пересчитываются заново.
          </div>
        </div>
      ) : (
        <>
      <div className="text-[13px] text-text mb-4">
        <b>{report.partner}</b>
        <Region value={report.region} /> · {report.period_label} · итог{' '}
        <b className="tabular-nums">
          {foreign
            ? `${formatMoney(report.currency_total).replace(' ₽', '')} ${CURRENCY_SIGNS[report.currency] || report.currency}`
            : formatMoney(report.total)}
        </b>
        {foreign && report.currency_rate && (
          <span className="text-text-secondary"> · курс {rateText(report.currency_rate)}</span>
        )}
        {/* СУММА ВНЕ КАТАЛОГА — РЯДОМ С ИТОГОМ (просьба владельца
            24.09.2026): сверяя отчёт с платежом, полезно сразу видеть, какая
            его часть пока ни на что не отнесена. Пишем, только если она есть:
            «вне каталога 0,00» — лишний шум в строке, которую читают за
            секунду. */}
        {Number(report.unmatched_amount) > 0 && (
          <>
            {' '}· вне каталога{' '}
            <b className="tabular-nums text-danger">
              {formatMoney(report.unmatched_amount)}
            </b>
          </>
        )}
      </div>

      <div className="text-[12px] text-text-secondary mb-1.5">Квартал поступления</div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {[1, 2, 3, 4].map((q) => (
          <button
            key={q}
            type="button"
            className={tab(q === quarter)}
            onClick={() => setQuarter(q)}
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

      <div className="text-[12px] text-text-secondary mb-1.5">Месяц</div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          className={tab(monthOffset === null)}
          onClick={() => setMonthOffset(null)}
        >
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

      {!loading && shown.length === 0 && (
        <div className="text-[13px] text-text-muted">
          За этот период поступлений нет — заведите строку во вкладке «Поступления».
        </div>
      )}

      {!loading && adviceCount > 0 && (
        <div className="text-[12px] text-accent mb-1.5">
          {adviceCount === 1
            ? 'Подсвечена строка, где совпали площадка и сумма завода.'
            : `Подсвечены ${adviceCount} строки, где совпали площадка и сумма завода.`}
        </div>
      )}

      {!loading && shown.length > 0 && (
        <div className="border border-border rounded-card divide-y divide-border max-h-[320px] overflow-y-auto">
          {shown.map((p) => {
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
                  // ТЕКУЩАЯ ПРИВЯЗКА — ЗЕЛЁНЫМ (просьба владельца 24.09.2026),
                  // подсказка — цветом акцента: «уже связано» и «похоже, эта»
                  // — разные ответы, и путать их глазом нельзя.
                  current ? 'bg-success/10' : advice ? 'bg-accent-soft' : 'bg-transparent'
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
                    data-hint={`Поступление от ${ru(p.occurred_on)}`}
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
                  {/* Сумма в валюте — то, с чем сверяется валютный отчёт. */}
                  {foreign && p.currency_amount && (
                    <span className="text-text-secondary tabular-nums">{p.currency_amount}</span>
                  )}
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
                    <span className="text-success">отчёт привязан к этой строке</span>
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
        </>
      )}
    </Modal>
  );
}
