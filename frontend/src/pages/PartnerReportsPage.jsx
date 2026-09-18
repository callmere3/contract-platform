import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { TrashIcon } from '../components/ui/icons';
import { useAuth } from '../auth/AuthContext';
import { canManagePartnerReports } from '../auth/permissions';
import { listPartners } from '../api/partners';
// Тот же формат сумм, что во всём ML Finance: «40 916,36 ₽». Своё
// форматирование здесь разошлось бы с балансами и операциями.
import { formatMoney } from '../api/finance';
import {
  checkTrack,
  createReport,
  deleteReport,
  fetchAttributeOptions,
  listReports,
  previewReport,
} from '../api/partnerReports';

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

// Поля единого формата: к ним сводится любой отчёт площадки.
const FIELDS = [
  { name: 'sku', label: 'Артикул', required: true },
  { name: 'title', label: 'Наименование' },
  // Исполнитель нужен не для расчёта, а для ПОДБОРА артикула, когда площадка
  // код не проставила: одного названия мало — в каталоге пять «Азимутов».
  { name: 'artist', label: 'Исполнитель' },
  { name: 'quantity', label: 'Количество' },
  { name: 'amount_author', label: 'Сумма авторских' },
  { name: 'amount_related', label: 'Сумма смежных' },
];

/**
 * Выбор партнёра ПОИСКОМ, а не списком из сотни строк (просьба владельца
 * 18.09.2026). Стоит начать печатать — список сразу сужается до подходящих:
 * длинный перечень, который надо листать до нужной буквы, ровно та работа, от
 * которой поиск и избавляет. Ищем и по имени, и по коду Dista — у человека со
 * строчкой отчёта в руках чаще именно код.
 */
function PartnerPicker({ partners, value, onChange, inputClass }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const chosen = partners.find((p) => p.id === value) || null;

  const found = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? partners.filter(
          (p) =>
            (p.name || '').toLowerCase().includes(q) ||
            (p.dista_id || '').toLowerCase().includes(q),
        )
      : partners;
    return list.slice(0, 50);
  }, [partners, query]);

  // Нажатие мимо закрывает список и возвращает в поле имя выбранного: поле
  // показывает выбор, а не остатки поиска.
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  function pick(partner) {
    onChange(partner.id);
    setOpen(false);
    setQuery('');
  }

  return (
    <div className="relative" ref={box}>
      <input
        value={open ? query : chosen?.name ?? ''}
        placeholder={chosen ? chosen.name : '— начните вводить —'}
        onFocus={() => {
          setOpen(true);
          setQuery('');
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && found.length) pick(found[0]);
          if (e.key === 'Escape') {
            setOpen(false);
            setQuery('');
          }
        }}
        className={`${inputClass} min-w-[240px]`}
      />
      {open && (
        <div className="absolute z-50 mt-1 w-[320px] max-h-[280px] overflow-y-auto bg-surface border border-border rounded-card shadow-lg">
          {found.length === 0 && (
            <div className="px-3 py-2 text-[12.5px] text-text-muted">Ничего не нашлось</div>
          )}
          {found.map((p) => (
            <button
              key={p.id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(p)}
              className={`block w-full text-left px-3 py-2 text-[13px] bg-transparent border-0 cursor-pointer font-sans ${
                p.id === value ? 'text-accent' : 'text-text'
              } hover:bg-hover`}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Сумма для ячейки таблицы: те же тысячи, но без «₽» — он в шапке колонки. */
function amount(value) {
  return formatMoney(value).replace(' ₽', '');
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

  const [reports, setReports] = useState([]);
  const [totals, setTotals] = useState(null);
  const [busy, setBusy] = useState(false);
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

  const loadReports = useCallback(async () => {
    try {
      const data = await listReports({});
      setReports(data.reports ?? []);
      setTotals(data.totals ?? null);
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
  ) {
    if (!nextFile) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await previewReport({
        partnerId: nextPartner,
        file: nextFile,
        // Пустое правило = «возьми готовое правило площадки, сохранённое у
        // партнёра или догадайся по названиям колонок».
        mapping: Object.keys(nextMapping).length ? nextMapping : null,
        vatRate: nextVat,
        manualSkus,
      });
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
      if (data.partner?.id && data.partner.id !== partnerId) {
        setPartnerId(data.partner.id);
        setNotice(`Площадка определена по файлу: ${data.partner.name}.`);
      }
    } catch (e) {
      setError(e.message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  function takeFile(next) {
    // Партнёра спрашивать не обязательно: знакомый отчёт называет площадку сам.
    setFile(next);
    setPreview(null);
    setMapping({});
    // Новый файл — новые номера строк: вписанные артикулы к нему отношения не
    // имеют, и оставить их значит проставить код чужой строке.
    setManualSkus({});
    setSkuInfo({});
    setOnlyUnmatched(false);
    setShowMapping(false);
    // Параметры — свойство ОТЧЁТА, а не сеанса: у нового файла они приедут из
    // правила партнёра заново.
    setAttributes({});
    if (next) runPreview(next, {}, vatRate);
  }

  async function save() {
    setBusy(true);
    setError('');
    try {
      const { report } = await createReport({
        partnerId,
        file,
        mapping,
        vatRate,
        manualSkus,
        attributes,
        periodFrom: range.from,
        periodTo: range.to,
        saveRuleToo: rememberRule,
      });
      setNotice(
        `Отчёт «${report.file_name}» загружен за ${report.period_label}: ` +
          `${report.rows_count} строк, авторские ${formatMoney(report.total_author)}, ` +
          `смежные ${formatMoney(report.total_related)}.`,
      );
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
    }
  }

  async function remove(report) {
    if (!window.confirm(`Удалить отчёт «${report.file_name}» вместе со строками?`)) return;
    try {
      await deleteReport(report.id);
      loadReports();
    } catch (e) {
      setError(e.message);
    }
  }

  // Строки без трека приходят ОТДЕЛЬНЫМ списком и показываются только по
  // кнопке: дописанные в конец обычной таблицы, они выглядели так, будто отчёт
  // ими заканчивается.
  const unmatchedRows = preview?.unmatched_rows ?? [];
  const shownRows = onlyUnmatched ? unmatchedRows : preview?.preview ?? [];
  // Настройку колонок показываем, когда правила нет (его надо проверить) или
  // когда её открыли вручную.
  const mappingOpen = showMapping || preview?.rule_source === 'guess';

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
    <div className="max-w-[1180px] mx-auto px-8 pt-12 pb-20">
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
                inputClass={inputClass}
                onChange={(id) => {
                  setPartnerId(id);
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

            <label className="block">
              <span className="block text-[12px] text-text-secondary mb-1">НДС в суммах, %</span>
              <input
                value={vatRate ?? ''}
                onChange={(e) => setVatRate(e.target.value)}
                onBlur={() => preview && runPreview()}
                placeholder="нет"
                title="Если суммы в отчёте С НДС — укажите ставку (сейчас 22), и она будет вычтена. В отчётах «без НДС» поле оставляют пустым."
                className={`${inputClass} w-[110px] tabular-nums`}
              />
            </label>
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

          {/* ПАРАМЕТРЫ ОТЧЁТА — ПОД ЗАГРУЗКОЙ ФАЙЛА (просьба владельца
              18.09.2026): сверху остаётся то, без чего файл не прочитать
              (партнёр, период, НДС), а это — свойства уже прочитанного
              отчёта, и заполняют их один раз на площадку: галочка «запомнить
              правило» сохраняет их вместе с колонками. У знакомого формата
              они приезжают заполненными (у МТС — «RBT · <не участвует> ·
              Mobile · RU»). */}
          <div className="px-5 pb-5 flex flex-wrap gap-4 items-end">
            {ATTRS.map((a) => (
              <label className="block" key={a.name}>
                <span className="block text-[12px] text-text-secondary mb-1">{a.label}</span>
                <input
                  value={attributes[a.name] ?? ''}
                  onChange={(e) =>
                    setAttributes((prev) => ({ ...prev, [a.name]: e.target.value }))
                  }
                  list={`attr-${a.name}`}
                  placeholder="—"
                  className={`${inputClass} w-[190px]`}
                />
                <datalist id={`attr-${a.name}`}>
                  {(attrOptions[a.name] ?? []).map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </label>
            ))}
          </div>

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
                            title={spec.formula}
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
                            value={spec.column ?? ''}
                            onChange={(e) =>
                              setMapping((m) => {
                                const next = { ...m };
                                if (e.target.value) next[f.name] = { column: e.target.value };
                                else delete next[f.name];
                                return next;
                              })
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

              {/* Кнопка живёт ВНУТРИ настройки: файл разбирается заново с
                  новым правилом, и делать это на каждую правку поля незачем. */}
              {mappingOpen && (
                <Button variant="secondary" size="sm" onClick={() => runPreview()} disabled={busy}>
                  Применить и пересобрать
                </Button>
              )}

              {preview.problems.length > 0 && (
                <div className="mt-4 text-[13px] text-danger">
                  {preview.problems.map((p) => (
                    <div key={p}>{p}</div>
                  ))}
                </div>
              )}

              {preview.preview.length > 0 && (
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

                  {/* ДВАДЦАТЬ СТРОК И БЕЗ ПРОКРУТКИ (просьба владельца
                      18.09.2026): предпросмотр нужен, чтобы убедиться, что
                      колонки поняты верно, а не читать отчёт. Вбок таблица
                      по-прежнему скроллится — колонок больше, чем ширины. */}
                  <div className="mt-4 overflow-x-auto border border-border rounded-card">
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
                                <div className="flex flex-col gap-1">
                                  <input
                                    value={manualSkus[r.row] ?? r.sku ?? ''}
                                    placeholder="артикул"
                                    onChange={(e) => lookupSku(r.row, e.target.value)}
                                    className={`${inputClass} w-[120px] py-1 font-mono text-[12px]`}
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
                            <td className={`${td} tabular-nums`}>{r.quantity ?? '—'}</td>
                            <td className={`${td} tabular-nums`}>{amount(r.amount_author)}</td>
                            <td className={`${td} tabular-nums`}>{amount(r.amount_related)}</td>
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
                          Нет в номенклатуре: {preview.totals.unmatched} строк — они загрузятся
                          неразнесёнными.
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

                  <div className="mt-4 flex flex-wrap items-center gap-4">
                    <Button variant="accent" size="sm" onClick={save} disabled={busy}>
                      {busy ? 'Загружаем…' : 'Загрузить отчёт'}
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
                </>
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
        <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border">
          <div className="text-sm font-semibold text-text">Загруженные отчёты</div>
          {totals && reports.length > 0 && (
            <div className="text-[12.5px] text-text-muted tabular-nums">
              авторские {formatMoney(totals.author)} · смежные {formatMoney(totals.related)}
            </div>
          )}
        </div>

        {reports.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">Отчётов пока нет.</div>
        )}

        {reports.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Партнёр</th>
                  <th className={th}>Период</th>
                  <th className={th}>Файл</th>
                  <th className={th}>Параметры</th>
                  <th className={th}>Строк</th>
                  <th className={th}>Не разнесено, ₽</th>
                  <th className={th}>Авторские, ₽</th>
                  <th className={th}>Смежные, ₽</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id}>
                    <td className={`${td} font-semibold text-text`}>{r.partner}</td>
                    <td className={td}>{r.period_label}</td>
                    <td className={`${td} text-text-secondary`}>{r.file_name}</td>
                    {/* Параметры отчёта одной ячейкой: четыре отдельных
                        столбца растянули бы таблицу вдвое, а читают их
                        вместе — «музыка · стриминг · РФ». */}
                    <td className={`${td} text-text-secondary`}>
                      {ATTRS.map((a) => r[a.name]).filter(Boolean).join(' · ') || '—'}
                    </td>
                    <td className={`${td} tabular-nums`}>{r.rows_count}</td>
                    {/* СУММА, а не число строк (просьба владельца 18.09.2026):
                        десять строк по рублю и одна на сто тысяч выглядят
                        одинаково, если считать строки. */}
                    <td
                      className={`${td} tabular-nums ${
                        Number(r.unmatched_amount) > 0 ? 'text-danger' : 'text-text-muted'
                      }`}
                      title={`Строк без трека: ${r.unmatched_count}. Это суммы, которые пока не на что отнести.`}
                    >
                      {Number(r.unmatched_amount) > 0 ? amount(r.unmatched_amount) : '—'}
                    </td>
                    <td className={`${td} tabular-nums`}>{amount(r.total_author)}</td>
                    <td className={`${td} tabular-nums`}>{amount(r.total_related)}</td>
                    <td className={`${td} text-right`}>
                      {manage && (
                        <button
                          type="button"
                          onClick={() => remove(r)}
                          title="Удалить отчёт"
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
