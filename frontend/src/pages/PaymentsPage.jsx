import { useCallback, useEffect, useRef, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { PageHeader } from '../components/ui/PageHeader';
import { TrashIcon } from '../components/ui/icons';
import { PartnerPicker } from '../components/ui/PartnerPicker';
import { Tooltip } from '../components/ui/Tooltip';
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

// ПЛОЩАДКИ, КОТОРЫЕ ПЛАТЯТ В ВАЛЮТЕ (просьба владельца 23.09.2026). Список
// нужен только для того, чтобы не показывать лишнее поле у рублёвых строк:
// сама возможность ввести валютную сумму есть у любой строки, где она уже
// заполнена. Сравниваем по вхождению и без учёта регистра — в выписке
// площадка названа длиннее, чем в справочнике («BELIEVE INTERNATIONAL»,
// «CHOIS MUSIC, INC»).
const CURRENCY_PARTNERS = [
  'chois', 'tiktok', 'believe', 'белив', 'spotify', 'аманат',
  'youtube', 'ютуб',
];

function inCurrency(row) {
  const name = `${row.partner || ''} ${row.partner_name || ''}`.toLowerCase();
  return CURRENCY_PARTNERS.some((key) => name.includes(key));
}
// ОТКРЫТЫЙ ПЕРИОД ЗАПОМИНАЕТСЯ (просьба владельца 23.09.2026). Поступления
// заносят задним числом — за прошлый месяц, а то и за прошлый квартал, — и
// возвращаться к нужному месяцу после каждой перезагрузки страницы значит
// делать одну и ту же работу по десять раз за вечер.
//
// Не в адресе, а в localStorage: это не «что я показываю другому», а «где я
// сейчас работаю». Ссылка на квартал никому не пересылается, зато состояние
// должно пережить и перезагрузку, и уход на соседнюю вкладку.
const PERIOD_KEY = 'ml_payments_period';

function readPeriod() {
  try {
    const saved = JSON.parse(localStorage.getItem(PERIOD_KEY) || 'null');
    if (!saved) return null;
    const { year, quarter, monthOffset } = saved;
    // Мусор в хранилище не должен ломать страницу: проверяем, что это
    // действительно период, а не что-то постороннее.
    const ok =
      Number.isInteger(year) && year > 2000 && year < 2100 &&
      Number.isInteger(quarter) && quarter >= 1 && quarter <= 4 &&
      Number.isInteger(monthOffset) && monthOffset >= 0 && monthOffset <= 2;
    return ok ? { year, quarter, monthOffset } : null;
  } catch {
    return null;                 // приватное окно или запрещённые данные сайта
  }
}

function savePeriod(period) {
  try {
    localStorage.setItem(PERIOD_KEY, JSON.stringify(period));
  } catch {
    /* не беда: просто в следующий раз откроется текущий месяц */
  }
}

const monthRange = (year, month) => ({
  from: iso(new Date(Date.UTC(year, month, 1))),
  to: iso(new Date(Date.UTC(year, month + 1, 0))),
});

/**
 * ENTER СОХРАНЯЕТ, ESCAPE ОТМЕНЯЕТ (просьба владельца 23.09.2026).
 *
 * Поле и так уходит на сервер, когда его отпускают, поэтому Enter просто
 * снимает фокус: сохранение идёт тем же путём, что и раньше, и второй ветки
 * кода, которая однажды разойдётся с первой, не появляется. Раньше Enter не
 * делал ничего — таблица не форма, отправлять нечего, — и это читалось как
 * «правка не сохранилась».
 *
 * Escape нужен рядом с Enter: если есть способ подтвердить, должен быть и
 * способ передумать.
 */
function commitKeys(cancelRef) {
  return (e) => {
    if (e.key === 'Enter') e.currentTarget.blur();
    if (e.key === 'Escape') {
      if (cancelRef) cancelRef.current = true;
      e.currentTarget.blur();
    }
  };
}

/**
 * Ячейка с суммой — «925 000,00» и в покое, и при правке.
 *
 * МАШИННОГО ВИДА ЧЕЛОВЕК НЕ ВИДИТ ВООБЩЕ (просьба владельца 23.09.2026).
 * Раньше при щелчке по ячейке «925 000,00» превращалось в «925000.00»: так
 * было сделано, чтобы пробелы не прыгали под курсором. Но прыгают они только
 * если переформатировать строку на каждую букву, а этого и не нужно — вид
 * задаётся ОДИН РАЗ, когда в поле встают, дальше человек правит обычный
 * текст. Сервер принимает и пробелы, и запятую, и знак рубля.
 *
 * Сравниваем при уходе с тем, что было показано в начале правки, а не со
 * значением с сервера: иначе каждый щелчок по ячейке считался бы правкой и
 * гонял бы запрос впустую.
 */
function MoneyCell({ value, disabled, onSave, className }) {
  const [text, setText] = useState('');
  const [initial, setInitial] = useState('');
  const [editing, setEditing] = useState(false);
  // Отмену держим в ref, а не в состоянии: Escape снимает фокус сразу же, и
  // обработчик ухода прочитал бы ещё старое состояние.
  const cancelled = useRef(false);

  const shown = value ? amount(value) : '';

  return (
    <input
      value={editing ? text : shown}
      disabled={disabled}
      onFocus={() => {
        setText(shown);
        setInitial(shown);
        setEditing(true);
      }}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={commitKeys(cancelled)}
      onBlur={() => {
        setEditing(false);
        if (cancelled.current) {
          cancelled.current = false;
          return;
        }
        if (text !== initial) onSave(text);
      }}
      className={className}
    />
  );
}

/**
 * Ячейка со ставкой — курс или НДС.
 *
 * РАЗДЕЛИТЕЛЬ ДРОБНОЙ ЧАСТИ — ЗАПЯТАЯ (замечание владельца 23.09.2026): она
 * стоит во всех суммах таблицы, и точка у одного только курса выглядит
 * опиской. Сервер хранит и отдаёт число точкой — это машинный вид, — поэтому
 * запятую подставляем на экране, а обратно принимаем любую: `_parse_money` и
 * `_parse_percent` понимают оба разделителя.
 *
 * Знак процента у НДС дорисован по той же причине, что запятая: чтобы не
 * гадать, ставку тут ждут или коэффициент. При правке оба украшения убираем —
 * иначе курсор спотыкается о лишний символ.
 */
function RateCell({ value, disabled, onSave, className, suffix = '', placeholder }) {
  const [text, setText] = useState('');
  const [initial, setInitial] = useState('');
  const [editing, setEditing] = useState(false);
  const cancelled = useRef(false);

  const human = value ? String(value).replace('.', ',') : '';
  const shown = human ? `${human}${suffix}` : '';

  return (
    <input
      // В покое — со знаком процента, при правке без него: иначе курсор,
      // поставленный в конец, дописывал бы цифру после «%». А вот запятая
      // остаётся: машинной точки человек видеть не должен.
      value={editing ? text : shown}
      disabled={disabled}
      placeholder={placeholder}
      onFocus={() => {
        setText(human);
        setInitial(human);
        setEditing(true);
      }}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={commitKeys(cancelled)}
      onBlur={() => {
        setEditing(false);
        if (cancelled.current) {
          cancelled.current = false;
          return;
        }
        if (text !== initial) onSave(text);
      }}
      className={className}
    />
  );
}

/** Сумма для ячейки: те же тысячи, но без «₽» — он в шапке колонки. */
function amount(value) {
  return formatMoney(value).replace(' ₽', '');
}

export function PaymentsPage() {
  const { role } = useAuth();
  const { openModal } = useModal();
  const manage = canManagePayments(role);

  const today = new Date();
  const opened = readPeriod();
  const [year, setYear] = useState(opened?.year ?? today.getFullYear());
  const [quarter, setQuarter] = useState(
    opened?.quarter ?? Math.floor(today.getMonth() / 3) + 1
  );
  // Месяц внутри квартала: 0, 1 или 2. Храним смещение, а не номер месяца, —
  // тогда переключение квартала не оставляет открытым чужой месяц.
  const [monthOffset, setMonthOffset] = useState(opened?.monthOffset ?? today.getMonth() % 3);

  const [partners, setPartners] = useState([]);
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const month = (quarter - 1) * 3 + monthOffset;
  const range = monthRange(year, month);

  useEffect(() => {
    savePeriod({ year, quarter, monthOffset });
  }, [year, quarter, monthOffset]);

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
                  <th className={th}>№</th>
                  <th className={th}>Дата поступления</th>
                  <th className={th}>Партнёр</th>
                  <th className={th}>Описание платежа</th>
                  <th className={th}>Сумма поступления</th>
                  <th className={th}>НДС</th>
                  <th className={th}>Сумма завода</th>
                  <th className={th}>Заведено</th>
                  <th className={th}>Сумма фактического завода</th>
                  <th className={th}>Расхождение</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td className={`${td} text-[13px] text-text-muted`} colSpan={11}>
                      За этот месяц поступлений нет.
                    </td>
                  </tr>
                )}
                {rows.map((r) => (
                  <tr key={r.id}>
                    {/* НОМЕР СЧИТАЕТ СЕРВЕР, и считает по ПОРЯДКУ ЗАВЕДЕНИЯ,
                        а не по дате: на него ссылается столбец «Поступление»
                        во вкладке «Отчёты», и номер, который меняется от
                        правки даты у соседней строки, ссылкой быть не может.
                        У каждого месяца нумерация своя. */}
                    <td className={`${td} w-[52px] text-right`}>
                      <span className="inline-block px-2 py-1.5 text-[13px] text-text-muted tabular-nums">
                        {r.number ?? ''}
                      </span>
                    </td>
                    <td className={`${td} w-[150px]`}>
                      <input
                        type="date"
                        value={r.occurred_on ?? ''}
                        disabled={!manage}
                        onChange={(e) => edit(r.id, 'occurred_on', e.target.value)}
                        onKeyDown={commitKeys()}
                        onBlur={(e) => e.target.value && save(r.id, 'occurred_on', e.target.value)}
                        className={`${cellInput} tabular-nums`}
                      />
                    </td>
                    <td className={`${td} w-[220px]`}>
                      {/* ПОИСКОМ, а не списком: площадок больше сотни, и
                          листать их до нужной буквы в каждой строке —
                          худшее, что можно предложить. Компонент общий с
                          загрузкой отчёта. Площадку можно не выбирать вовсе:
                          строку заводят по выписке, а чей платёж — иногда
                          выясняют потом. */}
                      <PartnerPicker
                        partners={partners}
                        value={r.partner_id ?? ''}
                        allowEmpty
                        // Мелкие партнёры по синхронизации отчётов не
                        // присылают, в справочнике площадок их нет и быть не
                        // должно — а деньги от них приходят, и строку надо
                        // подписать. Имя хранится у поступления отдельным
                        // полем, справочник при этом не засоряется.
                        allowCustom
                        customValue={r.partner_name ?? ''}
                        placeholder="— не указан —"
                        inputClassName={cellInput}
                        onChange={(id) => {
                          if (!manage) return;
                          edit(r.id, 'partner_id', id);
                          save(r.id, 'partner_id', id);
                        }}
                        onCustom={(name) => {
                          if (!manage) return;
                          edit(r.id, 'partner_name', name);
                          save(r.id, 'partner_name', name);
                        }}
                      />
                    </td>
                    {/* ОПИСАНИЕ ЦЕЛИКОМ — ПОДСКАЗКОЙ (просьба владельца
                        23.09.2026): в столбец оно не влезает, а прочитать его
                        надо — там написано, за что платёж. Расширять столбец
                        нельзя, таблица и так упирается в ширину экрана. */}
                    <td className={td}>
                      <Tooltip text={r.description} className="block">
                        <input
                          value={r.description ?? ''}
                          disabled={!manage}
                          placeholder="за что платёж"
                          onChange={(e) => edit(r.id, 'description', e.target.value)}
                          onKeyDown={commitKeys()}
                          onBlur={(e) => save(r.id, 'description', e.target.value)}
                          className={cellInput}
                        />
                      </Tooltip>
                    </td>
                    {/* ПОД СУММОЙ — СУММА В ВАЛЮТЕ (просьба владельца
                        23.09.2026). У CHOIS, TikTok, Believe, Spotify,
                        YouTube и Аманата платёж приходит в валюте, а на счёт
                        падает уже в рублях; сверять строку с письмом площадки
                        удобнее по валютной сумме. В расчётах она НЕ участвует.

                        ПОЛЕ ТЕКСТОВОЕ, валюта пишется прямо в нём: «8 247,81
                        доллар». Числом его делать не за чем — складывать и
                        делить эту сумму не с чем, а вставляют её как есть из
                        письма площадки. Отдельной подписи с кодом валюты тоже
                        нет: она сбивала выравнивание, а теперь валюта внутри
                        самой строки.

                        Поле показываем не всем подряд: у рублёвых платежей
                        оно дублировало бы сумму выше. Но если значение уже
                        стоит, показываем всегда — данные не должны пропадать
                        из-за того, что площадку переименовали. */}
                    <td className={`${td} w-[150px]`}>
                      <MoneyCell
                        value={r.amount}
                        disabled={!manage}
                        onSave={(v) => save(r.id, 'amount', v)}
                        className={`${cellInput} tabular-nums text-right`}
                      />
                      {(r.currency_amount || inCurrency(r)) && (
                        <input
                          value={r.currency_amount ?? ''}
                          disabled={!manage}
                          placeholder="в валюте"
                          onChange={(e) => edit(r.id, 'currency_amount', e.target.value)}
                          onKeyDown={commitKeys()}
                          onBlur={(e) => save(r.id, 'currency_amount', e.target.value)}
                          className={`${cellInput} text-right text-[12px] text-text-muted`}
                        />
                      )}
                    </td>
                    {/* НДС — СТАВКА В ПРОЦЕНТАХ (уточнение владельца
                        23.09.2026): «22» значит 22%. Коэффициент человек не
                        набирает — он знает ставку. Знак процента дорисован
                        для того, чтобы не гадать, что здесь ждут. */}
                    <td className={`${td} w-[110px]`}>
                      <RateCell
                        value={r.vat_rate}
                        suffix="%"
                        placeholder="22%"
                        disabled={!manage}
                        onSave={(v) => save(r.id, 'vat_rate', v)}
                        className={`${cellInput} tabular-nums text-right`}
                      />
                    </td>
                    {/* СВЕРКА ПО ФОРМУЛЕ (владелец 23.09.2026):
                        поступление / курс / (1 + НДС) должно дать сумму
                        завода. Считает сервер — делить деньги на экране
                        нельзя, они там строки.

                        Расхождение показываем ЗНАЧКОМ, а не отдельным
                        столбцом: это не ещё одно число для таблицы, а
                        подсказка «проверьте ввод». Молчим, пока сумма
                        поступления не заполнена: сверять не с чем. */}
                    <td className={`${td} w-[140px] relative`}>
                      <MoneyCell
                        value={r.transfer_amount}
                        disabled={!manage}
                        onSave={(v) => save(r.id, 'transfer_amount', v)}
                        className={`${cellInput} tabular-nums text-right`}
                      />
                      {r.expected_transfer != null &&
                        r.transfer_amount != null &&
                        Number(r.expected_transfer) !== Number(r.transfer_amount) && (
                          <Tooltip
                            text={`По формуле должно быть ${amount(r.expected_transfer)} ₽
сумма поступления / курс / (1 + НДС)`}
                            className="absolute right-1 top-0"
                          >
                            <span className="text-[11px] text-danger cursor-help">≠</span>
                          </Tooltip>
                        )}
                    </td>
                    {/* НЕ ГАЛОЧКА, А ВЫБОР (просьба владельца 23.09.2026):
                        в рабочей таблице тут три положения дел — пусто, «да»
                        и «синхра». Галочкой это не описать, а сводить
                        «синхру» к «не заведено» значит терять то, ради чего
                        колонку ведут. По умолчанию прочерк. */}
                    <td className={`${td} w-[110px]`}>
                      <select
                        value={r.transfer_status ?? ''}
                        disabled={!manage}
                        onChange={(e) => {
                          edit(r.id, 'transfer_status', e.target.value);
                          save(r.id, 'transfer_status', e.target.value);
                        }}
                        className={`${cellInput} cursor-pointer`}
                      >
                        <option value="">—</option>
                        <option value="да">да</option>
                        <option value="синхра">синхра</option>
                      </select>
                    </td>
                    {/* ФАКТИЧЕСКИЙ ЗАВОД, ПОСЧИТАННЫЙ ПО ОТЧЁТАМ, НЕ ПРАВИТСЯ
                        (просьба владельца 19.09.2026): он равен сумме
                        привязанных отчётов, и ручная правка всё равно
                        затёрлась бы при следующей привязке. Отвязали
                        отчёты — поле снова обычное. Сервер тоже откажет:
                        запрет живёт не только на экране. */}
                    <td className={`${td} w-[160px] text-right`}>
                      {r.linked_reports > 0 ? (
                        <Tooltip
                          text={`Сумма ${r.linked_reports} привязанных отчётов.
Чтобы поправить — отвяжите отчёт во вкладке «Отчёты».`}
                        >
                          <span className="inline-block px-2 py-1.5 text-[13px] text-text tabular-nums cursor-help">
                            {amount(r.actual_amount)}
                            <span className="text-text-muted"> ↩</span>
                          </span>
                        </Tooltip>
                      ) : (
                        <MoneyCell
                          value={r.actual_amount}
                          disabled={!manage}
                          onSave={(v) => save(r.id, 'actual_amount', v)}
                          className={`${cellInput} tabular-nums text-right`}
                        />
                      )}
                    </td>
                    {/* РАСХОЖДЕНИЕ СЧИТАЕТ СЕРВЕР: суммы приходят строками, и
                        вычитать их на экране нельзя — «1234.10» в числе с
                        плавающей точкой превращается в 1234.0999999999999.
                        Пусто, пока не заполнены оба числа: разница с
                        неизвестным — не находка, а шум. Ноль отмечаем
                        прочерком и приглушённо: сошлось — значит, смотреть
                        не на что. */}
                    <td className={`${td} w-[130px] text-right`}>
                      {r.difference == null ? (
                        <span className="inline-block px-2 py-1.5 text-[13px] text-text-muted">
                          —
                        </span>
                      ) : (
                        <span
                          className={`inline-block px-2 py-1.5 text-[13px] tabular-nums ${
                            Number(r.difference) === 0 ? 'text-text-muted' : 'text-danger'
                          }`}
                          title="Сумма завода минус сумма фактического завода"
                        >
                          {Number(r.difference) === 0 ? 'сошлось' : amount(r.difference)}
                        </span>
                      )}
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
              {/* ИМПОРТ РЯДОМ С «ДОБАВИТЬ СТРОКУ», а не в шапке вкладки:
                  это два способа одного и того же — пополнить таблицу, и
                  разводить их по разным углам экрана незачем. */}
              {manage && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => openModal('paymentsImport', { onDone: load })}
                >
                  Импорт
                </Button>
              )}
              {manage && (
                <Button variant="secondary" size="sm" onClick={addRow}>
                  Добавить строку
                </Button>
              )}
              {totals && rows.length > 0 && (
                <div className="text-[13px] text-text">
                  {/* НДС в итогах нет: это ставка, а не деньги — складывать
                      коэффициенты нечего. */}
                  Поступило <b className="tabular-nums">{formatMoney(totals.amount)}</b> · завод{' '}
                  <b className="tabular-nums">{formatMoney(totals.transfer_amount)}</b> ·
                  фактически <b className="tabular-nums">{formatMoney(totals.actual_amount)}</b>
                  {/* Итог расхождений — только по сверенным строкам. Ноль
                      показываем словом: «0,00» рядом с остальными суммами
                      читается как «денег нет», а значит здесь обратное — всё
                      сошлось. */}
                  {totals.difference != null && (
                    <>
                      {' '}· расхождение{' '}
                      {Number(totals.difference) === 0 ? (
                        <b className="text-text-muted">сошлось</b>
                      ) : (
                        <b className="tabular-nums text-danger">
                          {formatMoney(totals.difference)}
                        </b>
                      )}
                    </>
                  )}
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
