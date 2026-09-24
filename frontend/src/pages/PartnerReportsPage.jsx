import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { ComboCell } from '../components/ui/ComboCell';
import { PartnerPicker } from '../components/ui/PartnerPicker';
import { Tooltip } from '../components/ui/Tooltip';
import {
  FilterIcon,
  FilterPickIcon,
  FilterSetupIcon,
  TrashIcon,
} from '../components/ui/icons';
import { useAuth } from '../auth/AuthContext';
import { canManagePartnerReports } from '../auth/permissions';
import { listPartners } from '../api/partners';
// Тот же формат сумм, что во всём ML Finance: «40 916,36 ₽». Своё
// форматирование здесь разошлось бы с балансами и операциями.
import { formatMoney } from '../api/finance';
import {
  checkTrack,
  createReport,
  currencySign,
  inspectReport,
  deleteAlias,
  fetchAttributeOptions,
  listAliases,
  listReports,
  previewReport,
} from '../api/partnerReports';
import { useModal } from '../modals/ModalProvider';

/**
 * ML Finance → «Отчёты»: загрузка отчётов площадок.
 *
 * ФАЙЛ ПЕРЕТАСКИВАЮТ В ОКНО, а не указывают путь к нему (в Dista путь вбивают
 * строкой, и файл обязан лежать на диске машины). Поле выбора осталось рядом:
 * перетаскивание удобно, когда файл уже открыт в проводнике, и бесполезно,
 * когда его ищут.
 *
 * ПРАВИЛА ИЗВЕСТНЫХ ПЛОЩАДОК ЖИВУТ НА СЕРВЕРЕ (`BUILTIN_RULES`): файл узнаётся
 * по колонкам, и правило применяется само — экран лишь показывает, что оно
 * применилось. Настроить колонки руками по-прежнему можно, и галочка
 * «запомнить правило» сделает настройку постоянной для этого партнёра.
 *
 * ФОРМУЛА — для случая, когда нужной суммы в отчёте нет отдельной колонкой. В
 * отчёте МТС, например, есть только общая сумма вознаграждения и две ставки, а
 * авторские и смежные считаются из них:
 *
 *     [Сумма вознаграждения…] * [Ставка…авторские] / ([Ставка…авторские] + [Ставка…смежные])
 *
 * Названия колонок там длиной в строку, поэтому рядом с полем формулы стоит
 * список «+ колонка»: ссылка вставляется выбором, а не перепечатыванием.
 *
 * ПЕРИОД — ПАРА ДАТ. Площадки отчитываются по-разному: МТС присылает месяц,
 * кто-то квартал, изредка попадается произвольный отрезок. Кнопки «Месяц» и
 * «Квартал» — просто быстрый способ заполнить эти две даты.
 */
const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const ROMAN = ['I', 'II', 'III', 'IV'];

// ПАРАМЕТРЫ ОТЧЁТА — одинаковые для всего файла и дальше уходят в отчёт
// правообладателю. Значения свободные: какие бывают виды использования, знает
// площадка, а не мы, — поэтому поле с подсказками по тому, что уже вводили, а
// не список из кода.
const ATTRS = [
  { name: 'content_type', label: 'Тип контента' },
  { name: 'usage_type', label: 'Тип использования' },
  { name: 'usage_kind', label: 'Вид использования' },
  { name: 'territory', label: 'Территория' },
];

/**
 * КОЛОНКИ СПИСКА ЗАГРУЖЕННЫХ ОТЧЁТОВ — одним описанием (24.09.2026).
 *
 * По нему рисуется и таблица, и окно настройки фильтра, и берётся значение
 * из выбранной ячейки. Разойдись они — в фильтре появилась бы колонка,
 * которой нет на экране, или наоборот.
 *
 * `text` — то, ПО ЧЕМУ ищем: именно показанная строка, а не сырое число.
 * Человек видит «40 916,36» и ждёт, что «916» найдётся.
 */
const REPORT_COLUMNS = [
  { key: 'partner', label: 'Партнёр', text: (r) => r.partner },
  { key: 'period', label: 'Период', text: (r) => r.period_label },
  ...['content_type', 'usage_type', 'usage_kind', 'territory'].map((name) => ({
    key: name,
    label: { content_type: 'Тип контента', usage_type: 'Тип использования',
             usage_kind: 'Вид использования', territory: 'Территория' }[name],
    text: (r) => r[name] || '',
  })),
  { key: 'payment', label: 'Поступление', text: (r) => r.payment_label || '' },
  { key: 'unmatched', label: 'Вне каталога', text: (r) => reportAmount(r, r.unmatched_amount) },
  { key: 'author', label: 'Авторские', text: (r) => reportAmount(r, r.total_author) },
  { key: 'related', label: 'Смежные', text: (r) => reportAmount(r, r.total_related) },
];

// Поля единого формата: к ним сводится любой отчёт площадки.
// «ЗАПОЛНЯЕТСЯ ПРАВИЛОМ» — такой же осознанный выбор, как колонка
// (замечание владельца 24.09.2026). Артикул ОБЯЗАТЕЛЕН: код площадки указан
// верно не всегда, и пустое поле должно значить «ниоткуда не берётся», то
// есть ошибку настройки, а не молчаливое «как-нибудь найдётся».
const SKU_AUTO = '__auto__';

const FIELDS = [
  // У «101 и К» нашего артикула в отчёте нет вовсе — он находится по коду
  // площадки («UPC / ISRC»), по названию или вписывается руками. Сама
  // колонка кода здесь НЕ настраивается: она живёт в правиле площадки, а
  // человеку важно одно — берётся артикул из файла или находится.
  { name: 'sku', label: 'Артикул', required: true },
  { name: 'quantity', label: 'Количество' },
  { name: 'amount_author', label: 'Сумма авторских' },
  { name: 'amount_related', label: 'Сумма смежных' },
];

// НАЗВАНИЕ И ИСПОЛНИТЕЛЬ ЗДЕСЬ НЕ НАСТРАИВАЮТСЯ (просьба владельца
// 24.09.2026): в детализации правообладателю они берутся ИЗ НОМЕНКЛАТУРЫ по
// артикулу, а не из отчёта площадки, и настраивать нечего. В правиле поля
// остались — встроенные правила их заполняют, и оттуда же работает подбор
// артикула по названию, когда площадка код не проставила.

/**
 * Ставка НДС так, как её называет человек: «22%», а не «22.00».
 *
 * Сервер хранит и отдаёт её числом с двумя знаками — это машинный вид, и
 * показывать его незачем (то же решение, что у сумм и курса в «Поступлениях»).
 * Знак процента и запятая дорисовываются в покое; как только в поле встали,
 * показываем то, что в нём лежит, — иначе курсор спотыкается о лишний символ.
 */
function RateField({ value, onChange, className }) {
  const [editing, setEditing] = useState(false);
  const pretty = (raw) => {
    const text = String(raw ?? '').trim();
    if (!text) return '';
    const number = Number(text.replace(',', '.'));
    if (!Number.isFinite(number)) return text;
    return `${String(number).replace('.', ',')}%`;
  };
  return (
    <input
      value={editing ? value ?? '' : pretty(value)}
      onChange={(e) => onChange(e.target.value)}
      onFocus={() => setEditing(true)}
      onBlur={() => setEditing(false)}
      placeholder="нет"
      className={className}
    />
  );
}

/**
 * Количество для ячейки: «493 817», а не «493817.00».
 *
 * Сервер отдаёт его строкой с двумя знаками, как и деньги (колонка в базе
 * `Numeric(16,2)`), но количество — это счёт прослушиваний, и хвост «,00»
 * в нём читается как машинный вид. Дробное сохраняем: у части площадок
 * количество приходит долями.
 */
function count(value) {
  if (value == null || value === '') return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
}

/**
 * Кнопка-значок в шапке списка отчётов.
 *
 * Значок без подписи — загадка, поэтому `title` обязателен (он же уходит в
 * `aria-label`). Включённое состояние красится акцентом: у фильтра «включён»
 * и «выключен» выглядят одинаково, если не показать этого прямо, — и человек
 * гадает, почему список короче обычного.
 */
function FilterButton({ icon, title, onClick, active = false, disabled = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-hint={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled}
      className={`w-8 h-8 rounded-input border flex items-center justify-center cursor-pointer bg-transparent disabled:opacity-40 disabled:cursor-default ${
        active ? 'border-accent text-accent' : 'border-border text-text-secondary hover:text-text'
      }`}
    >
      {icon}
    </button>
  );
}

/** Сумма для ячейки таблицы: те же тысячи, но без «₽» — он в шапке колонки. */
function amount(value) {
  return formatMoney(value).replace(' ₽', '');
}

/**
 * Сумма отчёта в списке. У валютного отчёта без курса — со знаком валюты:
 * шапка колонки обещает рубли, а там ещё доллары или евро.
 */
function reportAmount(report, value) {
  const sign = currencySign(report);
  return sign ? `${amount(value)} ${sign}` : amount(value);
}

/** Российская дата: 2026-07-01 → 01.07.2026. */
function ru(isoDate) {
  const [y, m, d] = String(isoDate || '').split('-');
  return y && m && d ? `${d}.${m}.${y}` : isoDate;
}

const iso = (d) => d.toISOString().slice(0, 10);
const monthRange = (year, month) => ({
  from: iso(new Date(Date.UTC(year, month, 1))),
  to: iso(new Date(Date.UTC(year, month + 1, 0))),
});
const quarterRange = (year, quarter) => ({
  from: iso(new Date(Date.UTC(year, (quarter - 1) * 3, 1))),
  to: iso(new Date(Date.UTC(year, quarter * 3, 0))),
});

export function PartnerReportsPage() {
  const { role } = useAuth();
  const { openModal } = useModal();
  const manage = canManagePartnerReports(role);

  const [partners, setPartners] = useState([]);
  const [partnerId, setPartnerId] = useState('');

  const today = new Date();
  const [mode, setMode] = useState('month');
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(Math.max(0, today.getMonth() - 1));
  const [quarter, setQuarter] = useState(Math.floor(today.getMonth() / 3) + 1);
  const [range, setRange] = useState(monthRange(today.getFullYear(), Math.max(0, today.getMonth() - 1)));

  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [vatRate, setVatRate] = useState('');
  // КТО ПОСТАВИЛ ПЛОЩАДКУ: человек выбрал её в поле или её определил файл
  // (баг, найден владельцем 24.09.2026). Перетащили отчёт одной площадки, не
  // загрузили, перетащили другой — и второй разбирался по правилу первой:
  // площадка оставалась в поле, а правило партнёра сильнее встроенного.
  // Определившееся само при новом файле сбрасываем, выбранное человеком —
  // нет: его выбор всегда главнее.
  const [partnerPicked, setPartnerPicked] = useState(false);
  const [rememberRule, setRememberRule] = useState(true);
  // Артикулы, вписанные руками: {номер строки: артикул}. Живут до загрузки и
  // уезжают вместе с файлом — сервер применяет их до привязки к каталогу.
  const [manualSkus, setManualSkus] = useState({});
  const [skuInfo, setSkuInfo] = useState({});
  const [onlyUnmatched, setOnlyUnmatched] = useState(false);
  // Какие формулы человек сейчас правит: остальные показаны словами.
  const [editing, setEditing] = useState({});
  const [showMapping, setShowMapping] = useState(false);
  // Параметры отчёта: приезжают из правила партнёра в предпросмотре, правятся
  // руками и уходят вместе с отчётом.
  const [attributes, setAttributes] = useState({});
  const [attrOptions, setAttrOptions] = useState({});
  // ФИЛЬТР СПИСКА ОТЧЁТОВ — как в Dista (просьба владельца 24.09.2026): три
  // кнопки в шапке вместо общей суммы. Условия живут отдельно от того,
  // включены ли они: «Выключить» не должно стирать набранное — иначе
  // сравнить «всё» и «только МТС» значило бы набрать условие заново.
  const [filters, setFilters] = useState({});
  const [filterOn, setFilterOn] = useState(false);
  // Режим «взять значение из ячейки». Отдельный режим, а не скрытый жест:
  // нажатие на строку и так открывает привязку к поступлению, и вешать на
  // него второй смысл значило бы гадать, что случится.
  const [pickMode, setPickMode] = useState(false);
  // Запомненные сопоставления выбранной площадки: «название — исполнитель →
  // артикул». Их заводит сервис, когда артикул вписывают руками.
  const [aliases, setAliases] = useState([]);
  const [showAliases, setShowAliases] = useState(false);

  const [reports, setReports] = useState([]);
  const [busy, setBusy] = useState(false);
  // СТРОКИ СЧИТАЮТСЯ В ФОНЕ (просьба владельца 24.09.2026): форма уже
  // заполнена по шапке, и кнопка «Загрузить отчёт» доступна, не дожидаясь
  // предпросмотра. Отдельно от `busy`, чтобы не блокировать загрузку.
  const [rowsLoading, setRowsLoading] = useState(false);
  // Идёт именно ЗАГРУЗКА отчёта, а не чтение шапки: подпись кнопки «Загружаем…»
  // должна появляться только тогда.
  const [saving, setSaving] = useState(false);
  // КУРС К РУБЛЮ для отчёта в валюте. Спрашивается, только когда сервер
  // увидел в файле не рубли (`needs_rate`); без него такой отчёт не грузится.
  const [currencyRate, setCurrencyRate] = useState('');
  // Номер текущего разбора: ответ на устаревший запрос (сменили файл, нажали
  // «Загрузить», пересобрали с другим правилом) должен быть выброшен, а не
  // лечь поверх свежего.
  const previewSeq = useRef(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const fileInput = useRef(null);

  // Период пересобирается из выбранного режима; «произвольный» правят руками.
  useEffect(() => {
    if (mode === 'month') setRange(monthRange(year, month));
    if (mode === 'quarter') setRange(quarterRange(year, quarter));
  }, [mode, year, month, quarter]);

  useEffect(() => {
    listPartners({ pageSize: 500 })
      .then((d) => setPartners(d.partners ?? []))
      .catch((e) => setError(e.message));
    fetchAttributeOptions()
      .then((d) => setAttrOptions(d.options ?? {}))
      .catch(() => setAttrOptions({}));
  }, []);

  const loadAliases = useCallback(async () => {
    if (!partnerId) {
      setAliases([]);
      return;
    }
    try {
      const data = await listAliases(partnerId);
      setAliases(data.aliases ?? []);
    } catch {
      setAliases([]);
    }
  }, [partnerId]);

  useEffect(() => {
    loadAliases();
    setShowAliases(false);
  }, [loadAliases]);

  const loadReports = useCallback(async () => {
    try {
      const data = await listReports({});
      setReports(data.reports ?? []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  /** Вписанный артикул: сразу показываем, что это за трек — или что его нет. */
  async function lookupSku(rowNum, sku) {
    const code = sku.trim();
    setManualSkus((m) => ({ ...m, [rowNum]: code }));
    if (!code) {
      setSkuInfo((s) => ({ ...s, [rowNum]: null }));
      return;
    }
    try {
      const data = await checkTrack(code);
      setSkuInfo((s) => ({ ...s, [rowNum]: data }));
    } catch {
      setSkuInfo((s) => ({ ...s, [rowNum]: null }));
    }
  }

  async function runPreview(
    nextFile = file,
    nextMapping = mapping,
    nextVat = vatRate,
    nextPartner = partnerId,
    nextRate = currencyRate,
  ) {
    if (!nextFile) return;
    const seq = ++previewSeq.current;
    setBusy(true);
    setRowsLoading(false);
    setError('');
    setNotice('');
    const source = {
      partnerId: nextPartner,
      file: nextFile,
      // Пустое правило = «возьми готовое правило площадки, сохранённое у
      // партнёра или догадайся по названиям колонок».
      mapping: Object.keys(nextMapping).length ? nextMapping : null,
      vatRate: nextVat,
      currencyRate: nextRate,
      manualSkus,
    };
    // ДВА ШАГА (просьба владельца 24.09.2026): сначала шапка — за доли
    // секунды, и форма с кнопкой «Загрузить отчёт» готова сразу; потом строки
    // — в фоне. Раньше всё это был один запрос, и кнопка появлялась через
    // полминуты: столько у «Зайцев.нет» занимают разбор и привязка к каталогу.
    let data;
    try {
      data = await inspectReport(source);
      if (seq !== previewSeq.current) return;
      setPreview(data);
      setMapping(data.mapping ?? {});
      setVatRate(data.vat_rate ?? '');
      // Параметры подставляем из правила партнёра — но не затираем то, что
      // человек уже вписал руками на этом файле.
      setAttributes((prev) =>
        Object.fromEntries(
          // ИМЕННО `||`, а не `??`: пустая строка здесь значит «ещё не
          // заполнено», и подставить в неё значение из правила надо. С `??`
          // первый предпросмотр записывал пустоту, и второй её сохранял.
          ATTRS.map(({ name }) => [name, prev[name] || data.attributes?.[name] || '']),
        ),
      );
      // ПЕРИОД ИЗ ШАПКИ ФАЙЛА: у МТС он там написан прямо («за период с
      // 1 июля 2026 по 31 июля 2026»), и это надёжнее, чем месяц по
      // умолчанию, — файл за июнь грузят в июле. Ставим режим «свой», иначе
      // кнопки месяца тут же пересчитали бы даты обратно.
      if (data.period?.from && data.period?.to) {
        setMode('custom');
        setRange({ from: data.period.from, to: data.period.to });
      }
      // Площадку мог определить сам файл — тогда ставим её в поле: человек
      // должен видеть, за кого будет засчитан отчёт, и вправе это поменять.
      // Сравниваем с тем, что РЕАЛЬНО отправили, а не с состоянием: при новом
      // файле площадку сбрасывают и разбирают заново, а состояние к этому
      // моменту ещё держит прежнее значение — и определившаяся площадка не
      // вернулась бы в поле, если совпала с прошлой.
      if (data.partner?.id && data.partner.id !== nextPartner) {
        setPartnerId(data.partner.id);
        setPartnerPicked(false);
        setNotice(`Площадка определена по файлу: ${data.partner.name}.`);
      }
    } catch (e) {
      if (seq !== previewSeq.current) return;
      setError(e.message);
      setPreview(null);
      setBusy(false);
      return;
    }
    setBusy(false);

    // Строки. Сервер запоминает разбор, и если человек нажмёт «Загрузить»,
    // не дождавшись, загрузка подхватит этот же расчёт, а не начнёт заново.
    // Шлём ТЕ ЖЕ настройки, что и шапке, — иначе у разбора был бы другой ключ.
    setRowsLoading(true);
    try {
      const full = await previewReport({ ...source, partnerId: data.partner?.id || nextPartner });
      if (seq !== previewSeq.current) return;
      // Из полного ответа берём СТРОКИ И ИТОГИ, а форму не трогаем: пока
      // строки считались, человек мог поправить период или параметры.
      setPreview(full);
    } catch (e) {
      if (seq === previewSeq.current) setError(e.message);
    } finally {
      if (seq === previewSeq.current) setRowsLoading(false);
    }
  }

  function takeFile(next) {
    // Партнёра спрашивать не обязательно: знакомый отчёт называет площадку сам.
    // А определившуюся по ПРЕДЫДУЩЕМУ файлу забываем: иначе второй отчёт
    // разбирался бы по правилу чужой площадки.
    const keepPartner = partnerPicked ? partnerId : '';
    setPartnerId(keepPartner);
    setFile(next);
    setPreview(null);
    setMapping({});
    // Ставка НДС — свойство ОТЧЁТА, как и параметры: у нового файла она
    // приедет из его правила. Оставь мы прежнюю — файл площадки «без НДС»
    // молча поделился бы на 1.22.
    setVatRate('');
    // Курс — свойство ОТЧЁТА: у следующего файла валюта может быть другой.
    setCurrencyRate('');
    // Новый файл — новые номера строк: вписанные артикулы к нему отношения не
    // имеют, и оставить их значит проставить код чужой строке.
    setManualSkus({});
    setSkuInfo({});
    setOnlyUnmatched(false);
    setShowMapping(false);
    // Параметры — свойство ОТЧЁТА, а не сеанса: у нового файла они приедут из
    // правила партнёра заново.
    setAttributes({});
    if (next) runPreview(next, {}, '', keepPartner);
  }

  // ПАРАМЕТРЫ, ВЗЯТЫЕ ИЗ КОЛОНОК ФАЙЛА: {имя параметра: имя колонки}.
  // Считаем по ТЕКУЩЕМУ правилу, а не по ответу предпросмотра: человек
  // меняет это в настройке колонок, и поле «одно значение на весь отчёт»
  // должно исчезать сразу, а не после пересборки.
  const fromColumns = Object.fromEntries(
    ATTRS.map(({ name }) => [name, mapping[name]?.column || '']).filter(([, c]) => c),
  );
  // Столбцы параметров в предпросмотре — по ТОМУ правилу, которым файл
  // разобран, а не по текущему в форме: пока не нажали «Применить и
  // пересобрать», в строках лежат старые значения.
  const shownAttrs = ATTRS.filter((a) => preview?.attributes_from_columns?.[a.name]);

  async function save() {
    // Предпросмотр, если он ещё считается, больше не нужен на экране: сервер
    // отдаст его расчёт загрузке, а ответ самого предпросмотра выбросим.
    previewSeq.current += 1;
    setRowsLoading(false);
    setBusy(true);
    setSaving(true);
    setError('');
    try {
      const { report, remembered } = await createReport({
        partnerId,
        file,
        mapping,
        vatRate,
        currencyRate,
        manualSkus,
        // Параметр, взятый из колонки, значением НЕ шлём: у него своё в
        // каждой строке, а снимок в шапке отчёта означал бы обратное.
        attributes: Object.fromEntries(
          ATTRS.map(({ name }) => [name, fromColumns[name] ? '' : attributes[name] ?? '']),
        ),
        periodFrom: range.from,
        periodTo: range.to,
        saveRuleToo: rememberRule,
      });
      setNotice(
        `Отчёт «${report.file_name}» загружен за ${report.period_label}: ` +
          `${report.rows_count} строк, авторские ${formatMoney(report.total_author)}, ` +
          `смежные ${formatMoney(report.total_related)}.` +
          (remembered
            ? ` Запомнили артикулов для этой площадки: ${remembered} — в следующем отчёте` +
              ' они подставятся сами.'
            : ''),
      );
      loadAliases();
      setFile(null);
      setPreview(null);
      setMapping({});
      setManualSkus({});
      setSkuInfo({});
      loadReports();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      setSaving(false);
    }
  }

  // Подтверждение — СВОИМ окном, а не браузерным confirm: решение принимают,
  // глядя на сам отчёт (площадка, период, суммы), а системное окно умеет
  // показать одну строку. Удаляет само окно, страница только перечитывает
  // список.
  function remove(report) {
    openModal('confirmDeleteReport', { report, onDeleted: loadReports });
  }

  // Строки без трека приходят ОТДЕЛЬНЫМ списком и показываются только по
  // кнопке: дописанные в конец обычной таблицы, они выглядели так, будто отчёт
  // ими заканчивается.
  const unmatchedRows = preview?.unmatched_rows ?? [];
  const shownRows = onlyUnmatched ? unmatchedRows : preview?.preview ?? [];
  // Настройку колонок показываем, когда правила нет (его надо проверить) или
  // когда её открыли вручную.
  const mappingOpen = showMapping || preview?.rule_source === 'guess';

  // ОТБОР ИДЁТ ПО ТОМУ, ЧТО ВИДНО НА ЭКРАНЕ, а не запросом к серверу: список
  // и так приходит целиком (до 200 отчётов), а фильтр в Dista — это взгляд
  // на уже загруженное. Понадобится больше — тогда и переносить на сервер,
  // вместе с постраничностью.
  const activeFilters = Object.entries(filters).filter(([, text]) => text.trim());
  const shownReports =
    filterOn && activeFilters.length
      ? reports.filter((r) =>
          activeFilters.every(([key, text]) => {
            const column = REPORT_COLUMNS.find((c) => c.key === key);
            return String(column?.text(r) ?? '')
              .toLowerCase()
              .includes(text.trim().toLowerCase());
          }),
        )
      : reports;

  // Ячейка в режиме выбора: прицел вместо курсора и подсветка под мышью,
  // чтобы было видно, что берётся именно она, а не строка целиком.
  const cellClass = (extra = '') =>
    `${td} ${extra} ${pickMode ? 'cursor-crosshair hover:bg-accent-soft' : ''}`;
  const cellPick = (key, report) =>
    pickMode
      ? (e) => {
          e.stopPropagation();
          pickValue(REPORT_COLUMNS.find((c) => c.key === key), report);
        }
      : undefined;

  // ВЗЯТОЕ ЗНАЧЕНИЕ ВСЕГДА ОДНО (уточнение владельца 24.09.2026): прежние
  // условия стираются, а не дополняются. Иначе после двух-трёх нажатий
  // список пустел бы по причинам, которых на экране не видно, — а
  // складывать условия есть где, в окне тонкой настройки.
  //
  // Фильтр включаем сразу: человек нажал «взять», глядя на строку, и ждёт
  // результата, а не ещё одного нажатия.
  function pickValue(column, report) {
    setFilters({ [column.key]: String(column.text(report) ?? '') });
    setFilterOn(true);
    setPickMode(false);
  }

  const inputClass =
    'bg-input-bg border border-border rounded-input px-3 py-2 text-[13px] text-text outline-none font-sans';
  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-3 py-2 whitespace-nowrap';
  const td = 'px-3 py-2 align-top border-t border-border text-[12.5px]';
  const tab = (active) =>
    `px-3 py-1.5 text-[12.5px] rounded-input border cursor-pointer bg-transparent font-sans ${
      active ? 'border-accent text-accent' : 'border-border text-text-secondary'
    }`;

  return (
    // ШИРЕ ОСТАЛЬНЫХ ВКЛАДОК (просьба владельца 18.09.2026): в списке отчётов
    // десять столбцов — партнёр, период, четыре параметра и три суммы, — и на
    // 1180 они не помещались, а горизонтальная прокрутка в списке, который
    // читают глазами сверху вниз, только мешает.
    <div className="max-w-[1480px] mx-auto px-8 pt-12 pb-20">
      <PageHeader title="Отчёты партнёров">
        Отчёты площадок за месяц или квартал. Перетащите файл, проверьте, что колонки поняты
        верно, — и он ляжет в единый вид: артикул, количество, суммы авторских и смежных.
      </PageHeader>

      {manage && (
        <Card className="mb-6">
          <div className="p-5 flex flex-wrap gap-4 items-end border-b border-border">
            <label className="block">
              <span className="block text-[12px] text-text-secondary mb-1">Партнёр</span>
              <PartnerPicker
                partners={partners}
                value={partnerId}
                inputClassName={`${inputClass} min-w-[240px]`}
                onChange={(id) => {
                  setPartnerId(id);
                  setPartnerPicked(Boolean(id));
                  setMapping({});
                  // Файл уже перетащили, а партнёра выбрали после — разбираем
                  // заново: у нового партнёра может быть своё правило.
                  if (file) runPreview(file, {}, vatRate, id);
                  else setPreview(null);
                }}
              />
            </label>

            {/* ПЕРИОД. Месяц и квартал — кнопки, заполняющие пару дат; «свой»
                оставляет их править руками. Отдельного признака «это месяц» не
                храним: даты и так всё говорят. */}
            <div>
              <span className="block text-[12px] text-text-secondary mb-1">Период отчёта</span>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={tab(mode === 'month')} onClick={() => setMode('month')}>
                  Месяц
                </button>
                <button type="button" className={tab(mode === 'quarter')} onClick={() => setMode('quarter')}>
                  Квартал
                </button>
                <button type="button" className={tab(mode === 'custom')} onClick={() => setMode('custom')}>
                  Свой
                </button>

                {mode === 'month' && (
                  <select
                    value={month}
                    onChange={(e) => setMonth(Number(e.target.value))}
                    className={inputClass}
                  >
                    {MONTHS.map((m, i) => (
                      <option key={m} value={i}>
                        {m}
                      </option>
                    ))}
                  </select>
                )}
                {mode === 'quarter' && (
                  <select
                    value={quarter}
                    onChange={(e) => setQuarter(Number(e.target.value))}
                    className={inputClass}
                  >
                    {[1, 2, 3, 4].map((q) => (
                      <option key={q} value={q}>
                        {ROMAN[q - 1]} квартал
                      </option>
                    ))}
                  </select>
                )}
                {mode !== 'custom' ? (
                  <input
                    value={year}
                    onChange={(e) => setYear(Number(e.target.value.replace(/\D/g, '')) || '')}
                    className={`${inputClass} w-[86px] tabular-nums`}
                  />
                ) : (
                  <>
                    <input
                      type="date"
                      value={range.from}
                      onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
                      className={inputClass}
                    />
                    <span className="text-[12.5px] text-text-muted">—</span>
                    <input
                      type="date"
                      value={range.to}
                      onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
                      className={inputClass}
                    />
                  </>
                )}
              </div>
            </div>
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) takeFile(dropped);
            }}
            onClick={() => fileInput.current?.click()}
            className={`m-5 border-2 border-dashed rounded-card px-6 py-10 text-center cursor-pointer ${
              dragOver ? 'border-accent bg-accent/5' : 'border-border'
            }`}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".xlsx,.xlsm,.csv,.tsv,.txt"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && takeFile(e.target.files[0])}
            />
            <div className="text-[14px] text-text font-semibold">
              {file ? file.name : 'Перетащите сюда файл отчёта'}
            </div>
            <div className="text-[12.5px] text-text-muted mt-1">
              {file
                ? 'Можно перетащить другой файл или нажать, чтобы выбрать'
                : 'или нажмите, чтобы выбрать: .xlsx, .csv, .tsv'}
            </div>
            {/* Про партнёра здесь больше не спрашиваем: знакомый отчёт
                называет площадку сам, а незнакомый скажет об этом при разборе. */}
            {!partnerId && !file && (
              <div className="text-[12.5px] text-text-muted mt-2">
                Площадка определится по файлу — а если формат незнакомый, выберите её сами
              </div>
            )}
          </div>

          {/* НАД ПРЕДПРОСМОТРОМ НЕ ОСТАЛОСЬ НИЧЕГО (просьба владельца
              24.09.2026): и параметры отчёта, и ставка НДС переехали в
              «настроить колонки» — это настройки разбора, и спрашивать их в
              двух местах незачем. Здесь только файл, площадка и период: без
              них отчёт не прочитать и не подписать. */}

          {/* ЗАПОМНЕННЫЕ АРТИКУЛЫ площадки. Список нужен не для красоты:
              сопоставление, сделанное по ошибке, иначе повторялось бы в каждом
              следующем отчёте молча — увидеть и убрать, вот и вся задача. */}
          {aliases.length > 0 && (
            <div className="px-5 pb-5 text-[12.5px]">
              <button
                type="button"
                onClick={() => setShowAliases((v) => !v)}
                className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
              >
                Запомненные артикулы этой площадки: {aliases.length}
                {showAliases ? ' — скрыть' : ' — показать'}
              </button>
              {showAliases && (
                <div className="mt-2 border border-border rounded-card divide-y divide-border">
                  {aliases.map((a) => (
                    <div key={a.id} className="flex items-center gap-3 px-3 py-2">
                      <div className="flex-1">
                        <span className="text-text">{a.title}</span>
                        {a.artist && <span className="text-text-secondary"> — {a.artist}</span>}
                        <span className="text-text-muted"> → </span>
                        <span className="text-text font-mono">{a.sku}</span>
                        {/* Что это за трек СЕЙЧАС: каталог живёт своей жизнью,
                            и сопоставление могло указывать на позицию, которой
                            уже нет. */}
                        <span className="text-text-muted">
                          {a.track_title
                            ? ` (${a.track_title}${a.track_artist ? ` — ${a.track_artist}` : ''})`
                            : ' (нет в номенклатуре)'}
                        </span>
                      </div>
                      {manage && (
                        <button
                          type="button"
                          data-hint="Забыть: в следующем отчёте строка снова будет без артикула"
                          aria-label="Забыть сопоставление"
                          onClick={async () => {
                            try {
                              await deleteAlias(a.id);
                              loadAliases();
                            } catch (e) {
                              setError(e.message);
                            }
                          }}
                          className="text-danger bg-transparent border-0 cursor-pointer p-0"
                        >
                          <TrashIcon size={15} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {busy && <div className="px-5 pb-5 text-[13px] text-text-muted">Читаем файл…</div>}

          {preview && (
            <div className="px-5 pb-5">
              {/* ОТКУДА ПРАВИЛО — первое, что надо понять, глядя на разбор:
                  готовое правило площадки и догадка по названиям колонок дают
                  одинаково аккуратную таблицу, а доверия заслуживают разного. */}
              <div className="text-[12.5px] text-text-secondary mb-3">
                Шапка найдена в строке {preview.header_row}. Колонок в файле:{' '}
                {preview.columns.length}.{' '}
                {preview.rule_source === 'builtin' && (
                  <b className="text-accent">
                    Применено готовое правило «{preview.rule_name}» — колонки и формулы уже
                    настроены.
                  </b>
                )}
                {preview.rule_source === 'partner' && 'Применено сохранённое правило партнёра.'}
                {preview.rule_source === 'form' && 'Применено правило, которое вы настроили ниже.'}
                {preview.rule_source === 'guess' &&
                  'Готового правила для такого файла нет — колонки предложены по названиям, проверьте их.'}
                {' '}
                {/* Настройка колонок нужна ровно тогда, когда правила нет.
                    Когда оно есть, показывать шесть полей с уже подставленными
                    значениями незачем — это готовый ответ, который человек всё
                    равно не правит. Ссылка оставлена: правило может однажды
                    разойтись с файлом. */}
                <button
                  type="button"
                  onClick={() => setShowMapping((v) => !v)}
                  className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans"
                >
                  {mappingOpen ? 'скрыть настройку колонок' : 'настроить колонки'}
                </button>
              </div>

              <div className={`flex-col gap-3 mb-4 ${mappingOpen ? 'flex' : 'hidden'}`}>
                {FIELDS.map((f) => {
                  const spec = mapping[f.name] ?? {};
                  // Режим определяется НАЛИЧИЕМ ключа, а не его значением:
                  // у пустой формулы значение пустое, и по нему поле
                  // переключалось обратно на список (ошибка первого дня).
                  const isFormula = Object.prototype.hasOwnProperty.call(spec, 'formula');
                  return (
                    <div key={f.name} className="flex items-end gap-2 flex-wrap">
                      <label className="block flex-1 min-w-[320px]">
                        <span className="block text-[12px] text-text-secondary mb-1">
                          {f.label}
                          {f.required && ' *'}
                        </span>
                        {/* ГОТОВУЮ ФОРМУЛУ НЕ ПОКАЗЫВАЕМ СТРОКОЙ: у площадок
                            названия колонок длиной в предложение, и выражение
                            всё равно не помещается — читается как мусор. Видно,
                            что поле считается, а само выражение — в подсказке
                            при наведении и по «изменить». */}
                        {isFormula && spec.formula && !editing[f.name] ? (
                          <div
                            className={`${inputClass} w-full flex items-center justify-between gap-3`}
                            data-hint={spec.formula}
                          >
                            <span className="text-text-secondary">Рассчитано по формуле</span>
                            <button
                              type="button"
                              onClick={() => setEditing((e) => ({ ...e, [f.name]: true }))}
                              className="text-[12px] text-accent bg-transparent border-0 p-0 cursor-pointer font-sans"
                            >
                              изменить
                            </button>
                          </div>
                        ) : isFormula ? (
                          <input
                            value={spec.formula ?? ''}
                            onChange={(e) =>
                              setMapping((m) => ({ ...m, [f.name]: { formula: e.target.value } }))
                            }
                            placeholder="[Сумма всего] - [Сумма авт.]"
                            className={`${inputClass} w-full font-mono text-[12px]`}
                          />
                        ) : (
                          <select
                            value={spec.auto ? SKU_AUTO : spec.column ?? ''}
                            onChange={(e) =>
                              setMapping((m) => {
                                const next = { ...m };
                                if (e.target.value === SKU_AUTO) next[f.name] = { auto: true };
                                else if (e.target.value) next[f.name] = { column: e.target.value };
                                else delete next[f.name];
                                return next;
                              })
                            }
                            className={`${inputClass} w-full`}
                          >
                            <option value="">— нет —</option>
                            {/* ОТДЕЛЬНЫЙ ПУНКТ, А НЕ ПУСТОТА: у «101 и К»
                                артикула в файле нет, и его находят по коду
                                площадки, по названию или руками. Прочерк
                                рядом значит ровно «ниоткуда не берётся» — то
                                есть ошибку, и сервер её не примет. */}
                            {f.name === 'sku' && (
                              <option value={SKU_AUTO}>заполняется правилом</option>
                            )}
                            {preview.columns.filter(Boolean).map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                        )}
                      </label>

                      {/* Вставка ссылки на колонку: названия у площадок длиной
                          в строку, и перепечатывать их руками — гарантированная
                          опечатка. */}
                      {isFormula && (!spec.formula || editing[f.name]) && (
                        <select
                          value=""
                          onChange={(e) => {
                            if (!e.target.value) return;
                            const ref = `[${e.target.value}]`;
                            setMapping((m) => ({
                              ...m,
                              [f.name]: { formula: `${m[f.name]?.formula ?? ''}${ref}` },
                            }));
                          }}
                          className={`${inputClass} max-w-[210px]`}
                        >
                          <option value="">+ колонка</option>
                          {preview.columns.filter(Boolean).map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      )}

                      <button
                        type="button"
                        onClick={() =>
                          setMapping((m) => {
                            const next = { ...m };
                            next[f.name] = isFormula ? { column: '' } : { formula: '' };
                            return next;
                          })
                        }
                        className="text-[12px] text-accent bg-transparent border-0 p-0 pb-2 cursor-pointer font-sans whitespace-nowrap"
                      >
                        {isFormula ? 'выбрать колонкой' : 'задать формулой'}
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* ЧЕТЫРЕ ПАРАМЕТРА — ЗДЕСЬ ЖЕ, а не отдельным блоком сверху
                  (просьба владельца 24.09.2026): это такая же настройка
                  разбора, как артикул и суммы.

                  У большинства площадок параметр ОДИН НА ВЕСЬ ФАЙЛ — тогда
                  его вписывают значением, с подсказками из того, что уже
                  вводили. У Believe в одном отчёте 308 сочетаний, а
                  территория идёт по странам — тогда «выбрать колонкой», как
                  у сумм МТС «задать формулой». Формулы у параметров не
                  бывает: формулы считают числа, а это слова. */}
              <div className={`flex-col gap-3 mb-4 ${mappingOpen ? 'flex' : 'hidden'}`}>
                {ATTRS.map((a) => {
                  const byColumn = Object.prototype.hasOwnProperty.call(
                    mapping[a.name] ?? {}, 'column',
                  );
                  return (
                    <div key={a.name} className="flex items-end gap-2 flex-wrap">
                      <label className="block flex-1 min-w-[320px]">
                        <span className="block text-[12px] text-text-secondary mb-1">
                          {a.label}
                        </span>
                        {byColumn ? (
                          <select
                            value={mapping[a.name]?.column ?? ''}
                            onChange={(e) =>
                              setMapping((m) => ({ ...m, [a.name]: { column: e.target.value } }))
                            }
                            className={`${inputClass} w-full`}
                          >
                            <option value="">— нет —</option>
                            {preview.columns.filter(Boolean).map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <ComboCell
                            value={attributes[a.name] ?? ''}
                            options={attrOptions[a.name] ?? []}
                            onChange={(v) => setAttributes((prev) => ({ ...prev, [a.name]: v }))}
                            placeholder="—"
                            arrowLabel={`Показать значения: ${a.label}`}
                            inputClassName={`${inputClass} w-full pr-6`}
                          />
                        )}
                      </label>

                      <button
                        type="button"
                        onClick={() =>
                          setMapping((m) => {
                            const next = { ...m };
                            if (byColumn) delete next[a.name];
                            else next[a.name] = { column: '' };
                            return next;
                          })
                        }
                        className="text-[12px] text-accent bg-transparent border-0 p-0 pb-2 cursor-pointer font-sans whitespace-nowrap"
                      >
                        {byColumn ? 'задать значением' : 'выбрать колонкой'}
                      </button>
                    </div>
                  );
                })}

                {/* СТАВКА НДС — ЗДЕСЬ ЖЕ (просьба владельца 24.09.2026): это
                    такая же настройка разбора, как колонки, и применяется той
                    же кнопкой ниже. Отдельного «пересобрать по уходу из поля»
                    у неё больше нет — иначе одно и то же действие делалось бы
                    двумя способами. */}
                <label className="flex items-end gap-2 flex-wrap">
                  <span className="block flex-1 min-w-[320px]">
                    <span className="block text-[12px] text-text-secondary mb-1">
                      НДС в суммах
                    </span>
                    <RateField
                      value={vatRate}
                      onChange={setVatRate}
                      className={`${inputClass} w-full tabular-nums`}
                    />
                  </span>
                  <span className="text-[12px] text-text-muted pb-2 max-w-[320px]">
                    Если суммы в отчёте с НДС — укажите ставку, она будет вычтена.
                    В отчётах «без НДС» поле пустое.
                  </span>
                </label>
              </div>

              {/* Кнопка живёт ВНУТРИ настройки: файл разбирается заново с
                  новым правилом, и делать это на каждую правку поля незачем. */}
              {mappingOpen && (
                <Button variant="secondary" size="sm" onClick={() => runPreview()} disabled={busy}>
                  Применить и пересобрать
                </Button>
              )}

              {(preview.problems || []).length > 0 && (
                <div className="mt-4 text-[13px] text-danger">
                  {preview.problems.map((p) => (
                    <div key={p}>{p}</div>
                  ))}
                </div>
              )}

              {/* ПРЕДУПРЕЖДЕНИЕ — НЕ ОТКАЗ: файл разобран и грузится, но с ним
                  что-то не так. Сейчас это «буквы в файле уже потеряны» —
                  решение принимает человек, потому что у него, возможно,
                  лежит рядом тот же отчёт в .xlsx, где они целы. Красным не
                  красим: красный здесь означал бы «загрузить нельзя». */}
              {(preview.warnings || []).length > 0 && (
                <div className="mt-4 flex flex-col gap-1.5">
                  {preview.warnings.map((w) => (
                    <div
                      key={w}
                      className="rounded-md border border-accent/40 bg-accent-soft px-3 py-2 text-[13px] text-text"
                    >
                      {w}
                    </div>
                  ))}
                </div>
              )}

              {preview.preview?.length > 0 && (
                <>
                  {/* СТРОКИ, КОТОРЫХ НЕТ В НОМЕНКЛАТУРЕ, — отдельным взглядом:
                      в файле их полтора десятка на семь сотен, и искать их
                      глазами бессмысленно. Это не только «нет артикула»: код
                      может стоять, а трека с таким кодом у нас не быть. */}
                  {unmatchedRows.length > 0 && (
                    <div className="mt-4 flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        className={tab(onlyUnmatched)}
                        onClick={() => setOnlyUnmatched((v) => !v)}
                      >
                        {onlyUnmatched
                          ? 'Показать все строки'
                          : `Показать строки, которых нет в номенклатуре (${preview.totals.unmatched})`}
                      </button>
                      <span className="text-[12.5px] text-text-muted">
                        Артикул не указан в отчёте или его нет в нашем каталоге. Можно вписать
                        руками — прямо в таблице.
                        {unmatchedRows.length < preview.totals.unmatched &&
                          ` Показаны первые ${unmatchedRows.length}.`}
                      </span>
                    </div>
                  )}

                  {/* НАЧАЛО ФАЙЛА — ПЯТЬ СТРОК БЕЗ ПРОКРУТКИ (просьба владельца
                      18.09.2026): предпросмотр нужен, чтобы убедиться, что
                      колонки поняты верно, а не читать отчёт.

                      СПИСОК ВНЕ КАТАЛОГА — В ОКНЕ С ПРОКРУТКОЙ (просьба
                      владельца 24.09.2026): у «Зайцев.нет» таких строк сотня,
                      и выведенные целиком они уводили кнопку «Загрузить отчёт»
                      далеко вниз. Высота ограничена, заголовок колонок липкий,
                      полный список — выгрузкой в Excel. */}
                  <div className="mt-4 overflow-auto max-h-[360px] border border-border rounded-card">
                    <table className="w-full border-collapse">
                      <thead className="sticky top-0 bg-surface z-10">
                        <tr>
                          <th className={th}>Строка</th>
                          <th className={th}>Артикул</th>
                          <th className={th}>Наименование</th>
                          <th className={th}>Исполнитель</th>
                          <th className={th}>Количество</th>
                          <th className={th}>Авторские, ₽</th>
                          <th className={th}>Смежные, ₽</th>
                          {/* Столбцы параметров появляются, ТОЛЬКО если
                              правило берёт их из колонок: у площадок с общим
                              значением они повторяли бы одно и то же в каждой
                              строке и занимали место. Предпросмотр отвечает
                              на один вопрос — верно ли поняты колонки, — и
                              проверить надо как раз то, что меняется. */}
                          {shownAttrs.map((a) => (
                            <th className={th} key={a.name}>{a.label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {shownRows.map((r) => (
                          <tr key={r.row} className={r.problems.length ? 'bg-danger-soft' : undefined}>
                            <td className={`${td} tabular-nums text-text-muted`}>{r.row}</td>
                            {/* Артикул: у найденной строки — текст (подобранный
                                по названию помечен, это догадка сервиса, а не
                                данные площадки), у ненайденной — поле ввода. */}
                            <td className={`${td} font-mono`}>
                              {/* Артикул, подобранный по названию, показан как
                                  обычный: он привязан к треку и это такой же
                                  факт, как код из файла. Пометка сбоку заставляла
                                  бы перепроверять то, что проверять не нужно. */}
                              {r.matched ? (
                                r.sku || '—'
                              ) : (
                                /* СТРОКА С ПОЛЕМ — ТОЙ ЖЕ ВЫСОТЫ, ЧТО ОБЫЧНАЯ
                                   (замечание владельца 24.09.2026): поле ростом
                                   с строку текста и заходит в отступы ячейки
                                   отрицательным полем, а ответ «что за трек»
                                   стоит справа, а не второй строкой. Иначе
                                   список вне каталога выходил заметно выше
                                   остальных строк и меньше помещался в окно. */
                                <div className="flex items-center gap-2 whitespace-nowrap">
                                  <input
                                    value={manualSkus[r.row] ?? r.sku ?? ''}
                                    placeholder="артикул"
                                    onChange={(e) => lookupSku(r.row, e.target.value)}
                                    className={`${inputClass} w-[110px] h-[22px] -my-[2px] px-2 py-0 font-mono text-[12px] leading-none`}
                                  />
                                  {/* Найденный трек показываем НАЗВАНИЕМ: код
                                      из соседней системы сам по себе не
                                      подтверждает, что это тот же трек. */}
                                  {skuInfo[r.row]?.found && (
                                    <span className="text-[11px] text-accent font-sans">
                                      {skuInfo[r.row].title} — {skuInfo[r.row].artist}
                                    </span>
                                  )}
                                  {skuInfo[r.row] && !skuInfo[r.row].found && (
                                    <span className="text-[11px] text-danger font-sans">
                                      нет в каталоге
                                    </span>
                                  )}
                                </div>
                              )}
                            </td>
                            <td className={td}>{r.title || '—'}</td>
                            <td className={td}>{r.artist || '—'}</td>
                            <td className={`${td} tabular-nums`}>{count(r.quantity)}</td>
                            <td className={`${td} tabular-nums`}>{amount(r.amount_author)}</td>
                            <td className={`${td} tabular-nums`}>{amount(r.amount_related)}</td>
                            {shownAttrs.map((a) => (
                              <td className={td} key={a.name}>{r[a.name] || '—'}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 text-[13px] text-text">
                    Всего строк: <b className="tabular-nums">{preview.totals.rows}</b> · авторские{' '}
                    <b className="tabular-nums">{formatMoney(preview.totals.amount_author)}</b> ·
                    смежные{' '}
                    <b className="tabular-nums">{formatMoney(preview.totals.amount_related)}</b> ·
                    итого <b className="tabular-nums">{formatMoney(preview.totals.total)}</b>
                  </div>

                  {/* Эти два числа — главное, что нужно увидеть ДО загрузки:
                      по строкам без артикула деньги придут «ничьи», а строки с
                      непрочитанной суммой лягут нулями. */}
                  {(preview.totals.no_sku > 0 || preview.totals.problem_rows > 0) && (
                    <div className="mt-2 text-[12.5px] text-danger">
                      {/* Одно число вместо трёх: сколько строк не привязалось
                          к номенклатуре. Подобранные считаются привязанными —
                          проверять их человек не будет, и рассказывать о них
                          нечего. */}
                      {preview.totals.unmatched > 0 && (
                        <div>
                          Нет в номенклатуре: {preview.totals.unmatched} строк — они
                          загрузятся в «Вне каталога».
                        </div>
                      )}
                      {preview.totals.problem_rows > 0 && (
                        <div>
                          С непонятными суммами: {preview.totals.problem_rows} строк — они
                          загрузятся с нулями.
                        </div>
                      )}
                    </div>
                  )}

                </>
              )}

              {rowsLoading && (
                <div className="mt-4 text-[13px] text-text-muted">
                  Разбираем строки файла… «Загрузить отчёт» можно нажать, не дожидаясь.
                </div>
              )}

              {/* КНОПКА — СРАЗУ ПОСЛЕ ШАПКИ, а не после предпросмотра (просьба
                  владельца 24.09.2026): период, площадка и параметры известны
                  по верху файла, и ждать разбора строк, чтобы нажать
                  «Загрузить», незачем. Не показываем только при отказе
                  разбора — грузить тогда нечего. */}
              {/* КУРС — ТОЛЬКО У ОТЧЁТА В ВАЛЮТЕ, и прямо над кнопкой, а не в
                  настройке колонок: без него такой отчёт не грузится, и
                  прятать поле значило бы заставить искать, почему «Загрузить»
                  не работает. Применяется Enter'ом или уходом из поля —
                  строки пересчитываются в рубли заново. */}
              {preview.needs_rate && (
                <div className="mt-4 flex flex-wrap items-center gap-3 text-[13px]">
                  <span className="text-text">
                    Суммы отчёта в <b>{(preview.currencies || []).filter((c) => c !== 'RUB').join(', ')}</b>
                    . Курс к рублю:
                  </span>
                  <input
                    value={currencyRate}
                    onChange={(e) => setCurrencyRate(e.target.value)}
                    onBlur={() => {
                      if ((currencyRate || '') !== (preview.currency_rate || '')) {
                        runPreview(file, mapping, vatRate, partnerId, currencyRate);
                      }
                    }}
                    onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                    placeholder="76,75 или 0,0122"
                    className={`${inputClass} w-[150px] py-1 tabular-nums`}
                  />
                  <span className="text-[12.5px] text-text-muted">
                    Можно не вводить: курс подставится сам при привязке к поступлению, если
                    сумма в валюте сойдётся. Больше 1 — умножаем, меньше 1 — делим.
                  </span>
                </div>
              )}

              {!(preview.problems || []).length && (
                <div className="mt-4 flex flex-wrap items-center gap-4">
                  <Button
                    variant="accent"
                    size="sm"
                    onClick={save}
                    disabled={busy}
                  >
                    {saving ? 'Загружаем…' : 'Загрузить отчёт'}
                  </Button>
                  <span className="text-[12.5px] text-text-muted">
                    период: {ru(range.from)} — {ru(range.to)}
                    {preview.period?.from === range.from && preview.period?.to === range.to
                      ? ' (из шапки отчёта)'
                      : ''}
                  </span>
                  <label className="flex items-center gap-2 text-[13px] text-text-secondary select-none">
                    <input
                      type="checkbox"
                      checked={rememberRule}
                      onChange={(e) => setRememberRule(e.target.checked)}
                    />
                    Запомнить правило для этого партнёра
                  </label>
                </div>
              )}
            </div>
          )}

          {error && <div className="px-5 pb-5 text-[13px] text-danger">{error}</div>}
          {notice && !error && (
            <div className="px-5 pb-5 text-[13px] text-text-secondary">{notice}</div>
          )}
        </Card>
      )}

      <Card>
        {/* ТРИ КНОПКИ ФИЛЬТРА ВМЕСТО ОБЩЕЙ СУММЫ (просьба владельца
            24.09.2026, по образцу Dista): включить-выключить, взять значение
            из ячейки, тонкая настройка. Суммы отсюда убраны — место одно, а
            отбор нужнее: по площадке, территории и виду использования
            отчёты ищут глазами по всему списку. */}
        <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border">
          <div className="text-sm font-semibold text-text">
            Загруженные отчёты
            {filterOn && activeFilters.length > 0 && (
              <span className="text-text-muted font-normal">
                {' '}— отобрано {shownReports.length} из {reports.length}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <FilterButton
              icon={<FilterIcon />}
              title={
                activeFilters.length === 0
                  ? 'Условий пока нет — задайте их в настройке фильтра'
                  : filterOn
                    ? 'Выключить фильтр (условия сохранятся)'
                    : 'Включить фильтр'
              }
              active={filterOn && activeFilters.length > 0}
              disabled={activeFilters.length === 0}
              onClick={() => setFilterOn((v) => !v)}
            />
            <FilterButton
              icon={<FilterPickIcon />}
              title="Взять значение из ячейки в фильтр"
              active={pickMode}
              onClick={() => setPickMode((v) => !v)}
            />
            <FilterButton
              icon={<FilterSetupIcon />}
              title="Настроить условия по колонкам"
              onClick={() =>
                openModal('reportFilter', {
                  columns: REPORT_COLUMNS,
                  value: filters,
                  onApply: (next, on) => {
                    setFilters(next);
                    setFilterOn(on && Object.values(next).some((t) => t.trim()));
                  },
                })
              }
            />
          </div>
        </div>

        {pickMode && (
          <div className="px-5 py-2 text-[12.5px] text-accent border-b border-border">
            Нажмите на ячейку — её значение станет условием фильтра.
          </div>
        )}

        {/* «Ничего не нашлось» и «отчётов нет» — разные ответы: во втором
            случае человек ждёт, что список пуст, а в первом ищет, почему. */}
        {shownReports.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {reports.length === 0
              ? 'Отчётов пока нет.'
              : 'Под условия фильтра не подошёл ни один отчёт.'}
          </div>
        )}

        {shownReports.length > 0 && (
          <div>
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Партнёр</th>
                  <th className={th}>Период</th>
                  {/* ЧЕТЫРЕ ОТДЕЛЬНЫХ СТОЛБЦА (просьба владельца 18.09.2026):
                      по ним сверяют отчёты между собой, а склеенные через «·»
                      они читались как одна подпись. Таблица от этого шире —
                      она и скроллится вбок. */}
                  {ATTRS.map((a) => (
                    <th key={a.name} className={th}>
                      {a.label}
                    </th>
                  ))}
                  <th className={th}>Поступление</th>
                  {/* «ВНЕ КАТАЛОГА», А НЕ «НЕ РАЗНЕСЕНО» (просьба владельца
                      24.09.2026): столбец показывает деньги по строкам,
                      которых нет в номенклатуре, и с тех пор, как у них
                      появился общий адрес — служебная позиция «Вне
                      каталога», — так и понятнее, и точнее. */}
                  <th className={th}>Вне каталога, ₽</th>
                  <th className={th}>Авторские, ₽</th>
                  <th className={th}>Смежные, ₽</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {shownReports.map((r) => (
                  /* СТРОКА КЛИКАБЕЛЬНА (19.09.2026): нажатие открывает
                     «к какому поступлению относится этот отчёт». Это
                     единственное действие над загруженным отчётом, кроме
                     удаления, — отдельной кнопки ради него заводить незачем. */
                  <tr
                    key={r.id}
                    onClick={() => {
                      // В режиме выбора строка не открывает отчёт: сейчас
                      // нажатие значит «взять это значение», и делать его
                      // двусмысленным нельзя.
                      if (pickMode) return;
                      // НАЖАТИЕ ОТКРЫВАЕТ САМ ОТЧЁТ (просьба владельца
                      // 24.09.2026, вид «как в Dista»), а не привязку к
                      // поступлению: посмотреть, что залили, — главное
                      // действие над загруженным отчётом. Привязка уехала
                      // в шапку этого же окна, и путь до неё стал длиннее
                      // на одно нажатие — зато перестал быть единственным.
                      openModal('reportRows', {
                        report: r,
                        attrOptions,
                        onChanged: loadReports,
                        onDelete: (report) =>
                          openModal('confirmDeleteReport', {
                            report,
                            onDeleted: loadReports,
                            closeParent: true,
                          }),
                        onLink: (report, onFresh) =>
                          openModal('linkReportPayment', {
                            report,
                            onChanged: (fresh) => {
                              loadReports();
                              onFresh?.(fresh);
                            },
                          }),
                      });
                    }}
                    className={pickMode ? 'hover:bg-hover' : 'cursor-pointer hover:bg-hover'}
                  >
                    <td
                      className={cellClass('font-semibold text-text')}
                      onClick={cellPick('partner', r)}
                    >
                      {r.partner}
                    </td>
                    {/* Имя файла и число строк убраны из списка (просьба
                        владельца 18.09.2026): имя площадки и период отвечают,
                        что это за отчёт, а строки — служебное число. Имя файла
                        осталось в журнале действий и в сообщении о загрузке. */}
                    <td className={cellClass()} onClick={cellPick('period', r)}>
                      {r.period_label}
                    </td>
                    {ATTRS.map((a) => (
                      <td
                        key={a.name}
                        className={cellClass('text-text-secondary whitespace-nowrap')}
                        onClick={cellPick(a.name, r)}
                      >
                        {r[a.name] || '—'}
                      </td>
                    ))}
                    {/* К какому поступлению отчёт привязан. Пусто — значит,
                        деньги по нему ещё не свели с выпиской.

                        НОМЕР, ПЛОЩАДКА И КВАРТАЛ, А НЕ ДАТА (просьба владельца
                        23.09.2026): дата платежа ничего не говорит — отчётов
                        за месяц несколько, платежи идут вперемешку, и
                        «01.07.2026» повторяется у половины строк. Номером же
                        человек называет строку, глядя в таблицу поступлений.
                        Подпись собирает сервер, чтобы номер и здесь, и там
                        считались одним кодом. */}
                    <td className={cellClass('whitespace-nowrap')} onClick={cellPick('payment', r)}>
                      {r.payment_label ? (
                        /* Подсказка наша, а не браузерная (просьба владельца
                           24.09.2026): та появляется через секунду, сама
                           пропадает и рисуется мимо темы. */
                        <Tooltip
                          text={`Поступление от ${ru(r.payment_date)}`}
                          className="inline-block"
                        >
                          <span className="cursor-help">{r.payment_label}</span>
                        </Tooltip>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    {/* СУММА, а не число строк (просьба владельца 18.09.2026):
                        десять строк по рублю и одна на сто тысяч выглядят
                        одинаково, если считать строки. */}
                    {/* ПОДСКАЗКА НАША, А НЕ БРАУЗЕРНАЯ (просьба владельца
                        24.09.2026): браузерная появляется через секунду, сама
                        пропадает и рисуется системным шрифтом мимо темы — а
                        здесь она часть работы, по ней решают, лезть ли в
                        отчёт. То же решение, что в «Поступлениях». */}
                    <td
                      className={cellClass(
                        `tabular-nums ${
                          Number(r.unmatched_amount) > 0 ? 'text-danger' : 'text-text-muted'
                        }`,
                      )}
                      onClick={cellPick('unmatched', r)}
                    >
                      {Number(r.unmatched_amount) > 0 ? (
                        <Tooltip
                          text={
                            `Строк без трека: ${r.unmatched_count}.\n` +
                            'Эти деньги пока не на что отнести: они привязаны к\n' +
                            'служебной позиции «Вне каталога», артикул 0000001'
                          }
                          className="inline-block"
                        >
                          <span className="cursor-help">{reportAmount(r, r.unmatched_amount)}</span>
                        </Tooltip>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className={cellClass('tabular-nums')} onClick={cellPick('author', r)}>
                      {reportAmount(r, r.total_author)}
                    </td>
                    <td
                      className={cellClass(`tabular-nums ${r.rate_pending ? 'text-danger' : ''}`)}
                      onClick={cellPick('related', r)}
                      data-hint={
                        r.rate_pending
                          ? `Суммы в ${r.currency}: курс не задан. Он подставится сам при привязке к поступлению, если сумма в валюте сойдётся`
                          : undefined
                      }
                    >
                      {reportAmount(r, r.total_related)}
                    </td>
                    <td className={`${td} text-right`}>
                      {manage && (
                        <button
                          type="button"
                          onClick={(e) => {
                            // Иначе нажатие на мусорку откроет ещё и окно
                            // привязки: клик всплывает до строки.
                            e.stopPropagation();
                            remove(r);
                          }}
                          data-hint="Удалить отчёт"
                          aria-label="Удалить отчёт"
                          className="text-danger bg-transparent border-0 cursor-pointer p-0"
                        >
                          <TrashIcon size={16} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
