import { useEffect, useRef, useState } from 'react';
import { PageHeader } from '../components/ui/PageHeader';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Spinner } from '../components/ui/Spinner';
import { searchContragents } from '../api/contragents';
import { listPartners } from '../api/partners';
import { listTracks } from '../api/nomenclature';
import {
  exportSummary,
  generateRoyalty,
  previewRoyalty,
  summaryRoyalty,
} from '../api/royaltyReports';
import { formatMoney } from '../api/finance';

/**
 * ГЕНЕРАЦИЯ ОТЧЁТОВ (24.09.2026, просьба владельца: «вид как в Dista»).
 *
 * Слева — вкладки настройки, в центре — выбранная настройка и итог расчёта.
 * Из окна Dista взято то, что относится к делу: период и чем его мерить,
 * правообладатели, площадки, товарный фильтр, вид ведомости. Не взяты
 * закрывающие акты, платёжные поручения, отправка писем, склады и валюта —
 * у нас их нет (валюта одна, рубль).
 *
 * РЕЖИМЫ — В ЗАГОЛОВКЕ, как списки в «Номенклатуре»: «Правообладателям»
 * (ведомости каждому выбранному) и «Сводные отчёты». Вместо трёх отдельных
 * режимов Dista («по правообладателю», «по объекту», «по площадке») — один,
 * а по чему сводка, выбирается на вкладке «Основные» (просьба владельца
 * 24.09.2026): смысл у них один — количество и суммы, разложенные по
 * выбранному признаку.
 *
 * Считает СЕРВЕР (`royalty_reports.py`): суммы приходят строками, и
 * складывать их на экране нельзя.
 */
const MODES = [
  { key: 'holders', label: 'Правообладателям' },
  { key: 'summary', label: 'Сводные отчёты' },
];
const SUMMARY_BY = [
  { key: 'holder', label: 'Правообладателю' },
  { key: 'track', label: 'Объекту' },
  { key: 'partner', label: 'Площадке' },
];
const TABS = [
  { key: 'main', label: 'Основные' },
  { key: 'holders', label: 'Правообладатели' },
  { key: 'partners', label: 'Площадки' },
  { key: 'tracks', label: 'Товарный фильтр' },
];
const ROMAN = ['I', 'II', 'III', 'IV'];

const iso = (d) => d.toISOString().slice(0, 10);
const quarterRange = (year, q) => ({
  from: iso(new Date(Date.UTC(year, (q - 1) * 3, 1))),
  to: iso(new Date(Date.UTC(year, q * 3, 0))),
});
const ru = (value) => {
  const [y, m, d] = String(value || '').split('-');
  return y && m && d ? `${d}.${m}.${y}` : value;
};
// По умолчанию — ПРОШЛЫЙ квартал: отчёты правообладателям делают по
// закрытому кварталу, а не по текущему.
function lastQuarter() {
  const now = new Date();
  let q = Math.floor(now.getMonth() / 3);
  let year = now.getFullYear();
  if (q === 0) {
    q = 4;
    year -= 1;
  }
  return { year, q };
}

// НАСТРОЙКИ ЗАПОМИНАЮТСЯ (просьба владельца 24.09.2026: «выбрал квартал и
// вид отчёта — не хочу выбирать каждый раз заново»). В браузере, как
// открытый период в «Поступлениях»: это «где я сейчас работаю», а не данные,
// которыми делятся. Всё прочитанное проверяется — мусор в хранилище или
// приватное окно, где оно бросает исключение, страницу не роняют: просто
// открываются настройки по умолчанию.
//
// У КАЖДОГО РЕЖИМА СВОИ НАСТРОЙКИ, а открывается страница ВСЕГДА на
// «Правообладателям» (просьба владельца 25.09.2026). Ведомости делают
// адресно — одному-двум правообладателям, — а сводку смотрят по всем, и
// общий набор настроек заставлял перевыбирать их при каждом переключении.
// Хранятся рядом: { holders: {...}, summary: {...} }. Прежняя общая запись
// (ml_royalty_settings) служит заготовкой обоим режимам один раз.
const STORE = 'ml_royalty_settings_by_mode';
const OLD_STORE = 'ml_royalty_settings';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function readJson(key) {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || 'null');
    return raw && typeof raw === 'object' ? raw : null;
  } catch {
    return null;
  }
}

function loadStore() {
  const store = readJson(STORE);
  if (store) return store;
  const old = readJson(OLD_STORE) || {};
  return { holders: old, summary: old };
}

/**
 * Сохранённые настройки режима → значения для страницы, каждое проверено.
 * По умолчанию сводка смотрит ВСЕХ правообладателей, ведомости — никого:
 * их делают адресно.
 */
function restore(saved, mode) {
  const s = saved && typeof saved === 'object' ? saved : {};
  const start = lastQuarter();
  return {
    tab: pick(s.tab, ['main', 'holders', 'partners', 'tracks'], 'main'),
    year: Number.isInteger(s.year) && s.year > 2000 && s.year < 2100 ? s.year : start.year,
    period:
      DATE.test(s.period?.from || '') && DATE.test(s.period?.to || '')
        ? { from: s.period.from, to: s.period.to }
        : quarterRange(start.year, start.q),
    dateBasis: pick(s.dateBasis, ['period', 'report'], 'period'),
    kinds: { summary: bool(s.kinds?.summary, true), detailed: bool(s.kinds?.detailed, true) },
    groupDetail: bool(s.groupDetail, true),
    holdersAll: bool(s.holdersAll, mode === 'summary'),
    holders: savedItems(s.holders),
    partnersAll: bool(s.partnersAll, true),
    partners: savedItems(s.partners),
    tracksAll: bool(s.tracksAll, true),
    tracks: savedItems(s.tracks),
    by: pick(s.by, ['holder', 'track', 'partner'], 'holder'),
  };
}

/** Выбранные элементы списка: только {id, label, sub} со строковым id. */
function savedItems(value) {
  return Array.isArray(value)
    ? value
        .filter((x) => x && typeof x.id === 'string' && typeof x.label === 'string')
        .map((x) => ({ id: x.id, label: x.label, sub: typeof x.sub === 'string' ? x.sub : '' }))
    : [];
}

const pick = (value, allowed, fallback) => (allowed.includes(value) ? value : fallback);
const bool = (value, fallback) => (typeof value === 'boolean' ? value : fallback);

const inputClass =
  'bg-input-bg border border-border rounded-input px-3 py-2 text-[13px] text-text outline-none font-sans';

export function RoyaltyReportsPage() {
  // Хранилище читаем ОДИН раз — при открытии страницы; дальше оно живёт в
  // ref и пишется целиком. Режим при открытии — всегда «Правообладателям».
  const store = useRef(null);
  if (store.current === null) store.current = loadStore();
  const [initial] = useState(() => restore(store.current.holders, 'holders'));
  const [mode, setMode] = useState('holders');
  const [modeOpen, setModeOpen] = useState(false);
  const [tab, setTab] = useState(initial.tab);

  const [year, setYear] = useState(initial.year);
  const [period, setPeriod] = useState(initial.period);
  const [dateBasis, setDateBasis] = useState(initial.dateBasis);
  const [kinds, setKinds] = useState(initial.kinds);
  const [groupDetail, setGroupDetail] = useState(initial.groupDetail);

  // Выбор: режим «все/по выбранным» и сам список. У правообладателей «все» —
  // это те, кому за период есть что начислить.
  const [holdersAll, setHoldersAll] = useState(initial.holdersAll);
  const [holders, setHolders] = useState(initial.holders);
  const [partnersAll, setPartnersAll] = useState(initial.partnersAll);
  const [partners, setPartners] = useState(initial.partners);
  const [tracksAll, setTracksAll] = useState(initial.tracksAll);
  const [tracks, setTracks] = useState(initial.tracks);

  const [by, setBy] = useState(initial.by);
  const [preview, setPreview] = useState(null);
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(null); // 'preview' | 'generate'
  const [error, setError] = useState('');

  const settings = {
    periodFrom: period.from,
    periodTo: period.to,
    dateBasis,
    contragentIds: holdersAll ? [] : holders.map((h) => h.id),
    partnerIds: partnersAll ? [] : partners.map((p) => p.id),
    trackIds: tracksAll ? [] : tracks.map((t) => t.id),
    groupDetail,
    kinds: Object.keys(kinds).filter((k) => kinds[k]),
    by,
  };
  // Любая правка настроек делает прежний расчёт недействительным: показывать
  // числа, посчитанные для другого выбора, значит вводить в заблуждение.
  const settingsKey = JSON.stringify(settings);
  useEffect(() => {
    setPreview(null);
    setSummary(null);
  }, [settingsKey, mode]);

  // Любая правка — сразу в хранилище, в запись ТЕКУЩЕГО режима. Запись может
  // не пройти (приватное окно, переполнение) — тогда просто не запомним.
  const current = {
    tab, year, period, dateBasis, kinds, groupDetail, by,
    holdersAll, holders, partnersAll, partners, tracksAll, tracks,
  };
  useEffect(() => {
    store.current = { ...store.current, [mode]: current };
    try {
      localStorage.setItem(STORE, JSON.stringify(store.current));
    } catch {
      /* не запомнили — не беда */
    }
    // current собирается из перечисленного ниже; отдельной зависимостью он
    // был бы новым объектом на каждый рендер.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, tab, year, period, dateBasis, kinds, groupDetail, by,
      holdersAll, holders, partnersAll, partners, tracksAll, tracks]);

  /** Переключить режим: запомнить настройки этого, поднять настройки того. */
  function switchMode(next) {
    if (next === mode) return;
    store.current = { ...store.current, [mode]: current };
    const r = restore(store.current[next], next);
    setTab(r.tab);
    setYear(r.year);
    setPeriod(r.period);
    setDateBasis(r.dateBasis);
    setKinds(r.kinds);
    setGroupDetail(r.groupDetail);
    setHoldersAll(r.holdersAll);
    setHolders(r.holders);
    setPartnersAll(r.partnersAll);
    setPartners(r.partners);
    setTracksAll(r.tracksAll);
    setTracks(r.tracks);
    setBy(r.by);
    setMode(next);
  }

  const isSummary = mode === 'summary';
  const ready = holdersAll || holders.length > 0;
  const whyNot = !ready
    ? 'Выберите правообладателей во вкладке «Правообладатели»'
    : !isSummary && !settings.kinds.length
      ? 'Отметьте вид ведомости во вкладке «Основные»'
      : (!partnersAll && !partners.length)
        ? 'Выберите площадки или поставьте «Все»'
        : (!tracksAll && !tracks.length)
          ? 'Выберите позиции товарного фильтра или поставьте «Все»'
          : '';

  async function calculate() {
    setBusy('preview');
    setError('');
    try {
      setPreview(await previewRoyalty(settings));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function buildSummary() {
    setBusy('summary');
    setError('');
    try {
      setSummary(await summaryRoyalty(settings));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function downloadSummary() {
    setBusy('export');
    setError('');
    try {
      // Построенную сводку выгружаем как есть, без пересчёта: сервер её
      // запомнил. Настройки поменялись — снимок сброшен, и сервер посчитает.
      const { blob, filename } = await exportSummary({ ...settings, snapshot: summary?.snapshot });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function generate() {
    setBusy('generate');
    setError('');
    try {
      const { blob, filename } = await generateRoyalty(settings);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const tabBadge = {
    holders: holdersAll ? 'все' : holders.length || '',
    partners: partnersAll ? 'все' : partners.length || '',
    tracks: tracksAll ? 'все' : tracks.length || '',
  };

  return (
    // ШИРЕ ОСТАЛЬНЫХ ВКЛАДОК (просьба владельца 24.09.2026): в сводке по
    // правообладателю восемь колонок сумм, и на 1280 они уезжали в
    // горизонтальную прокрутку, а знак рубля переносился на новую строку.
    <div className="max-w-[1680px] mx-auto px-8 pt-12 pb-20">
      <PageHeader
        title={
          <>
            Генерация отчётов:{' '}
            <span className="relative inline-block">
            <button
              type="button"
              onClick={() => setModeOpen((v) => !v)}
              className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[26px] font-extrabold tracking-[-0.02em] underline decoration-dotted underline-offset-4"
            >
              {MODES.find((m) => m.key === mode).label}
            </button>
            {modeOpen && (
              <span className="absolute left-0 top-full mt-2 z-20 flex flex-col bg-surface border border-border rounded-card shadow-card py-1.5 min-w-[220px]">
                {MODES.map((m) => (
                  <button
                    key={m.key}
                    type="button"
                    onClick={() => {
                      switchMode(m.key);
                      setModeOpen(false);
                    }}
                    className={`text-left px-4 py-2 text-[14px] font-normal tracking-normal bg-transparent border-0 cursor-pointer font-sans hover:bg-hover ${
                      m.key === mode ? 'text-accent font-semibold' : 'text-text'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </span>
            )}
            </span>
          </>
        }
      >
        {/* Описание — своё у каждого режима (просьба владельца 24.09.2026):
            ведомости и сводки отвечают на разные вопросы. */}
        {mode === 'summary'
          ? 'Сколько Лицензиарам причитается за период — сводкой по правообладателю, объекту или площадке: количество, сумма реализации, вознаграждение и комиссия Лицензиата.'
          : 'Квартальные ведомости правообладателям по загруженным отчётам площадок: сколько причитается каждому по его долям и ставкам роялти.'}
      </PageHeader>

      {
        <div className="grid grid-cols-[220px_1fr] gap-6 items-start">
          {/* ВКЛАДКИ НАСТРОЙКИ — СЛЕВА, как в Dista: их четыре, и каждая
              отвечает на свой вопрос — за какой период, кому, по каким
              площадкам, по каким позициям. */}
          <Card>
            <nav className="flex flex-col py-2">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`flex items-center justify-between gap-2 text-left px-4 py-2.5 text-[13.5px] border-0 cursor-pointer font-sans ${
                    tab === t.key
                      ? 'bg-accent-soft text-accent font-semibold'
                      : 'bg-transparent text-text hover:bg-hover'
                  }`}
                >
                  {t.label}
                  {tabBadge[t.key] !== undefined && tabBadge[t.key] !== '' && (
                    <span className="text-[11.5px] text-text-muted font-normal">
                      {tabBadge[t.key]}
                    </span>
                  )}
                </button>
              ))}
            </nav>
          </Card>

          <div className="flex flex-col gap-6 min-w-0">
            <Card>
              <div className="p-6">
                {tab === 'main' && isSummary && (
                  <div className="mb-6">
                    <div className="text-[12px] text-text-secondary mb-1.5">Сводка по</div>
                    <div className="flex flex-wrap gap-2">
                      {SUMMARY_BY.map((b) => (
                        <button
                          key={b.key}
                          type="button"
                          onClick={() => setBy(b.key)}
                          className={`px-3 py-1.5 text-[13px] rounded-input border cursor-pointer bg-transparent font-sans ${
                            by === b.key
                              ? 'border-accent text-accent font-semibold'
                              : 'border-border text-text-secondary'
                          }`}
                        >
                          {b.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {tab === 'main' && (
                  <MainTab
                    isSummary={isSummary}
                    year={year}
                    setYear={setYear}
                    period={period}
                    setPeriod={setPeriod}
                    dateBasis={dateBasis}
                    setDateBasis={setDateBasis}
                    kinds={kinds}
                    setKinds={setKinds}
                    groupDetail={groupDetail}
                    setGroupDetail={setGroupDetail}
                  />
                )}
                {tab === 'holders' && (
                  <Picker
                    title="Правообладатели"
                    all={holdersAll}
                    setAll={setHoldersAll}
                    allLabel="Все, кому за период есть что начислить"
                    items={holders}
                    setItems={setHolders}
                    placeholder="Фамилия, название или псевдоним…"
                    search={async (q) =>
                      ((await searchContragents({ q, pageSize: 20 })).contragents ?? []).map(
                        (c) => ({ id: c.id, label: c.title, sub: (c.nicknames || []).join(', ') }),
                      )
                    }
                  />
                )}
                {tab === 'partners' && (
                  <Picker
                    title="Площадки"
                    all={partnersAll}
                    setAll={setPartnersAll}
                    allLabel="Все площадки"
                    items={partners}
                    setItems={setPartners}
                    placeholder="Название площадки или код Dista…"
                    search={async (q) =>
                      ((await listPartners({ q, pageSize: 20 })).partners ?? []).map((p) => ({
                        id: p.id,
                        label: p.name,
                      }))
                    }
                  />
                )}
                {tab === 'tracks' && (
                  <Picker
                    title="Товарный фильтр"
                    all={tracksAll}
                    setAll={setTracksAll}
                    allLabel="Все позиции выбранных правообладателей"
                    items={tracks}
                    setItems={setTracks}
                    placeholder="Артикул, ISRC, название или исполнитель…"
                    // ТОЛЬКО ПОЗИЦИИ ВЫБРАННЫХ ПРАВООБЛАДАТЕЛЕЙ: товарный фильтр
                    // сужает их отчёт, а не заводит чужие треки.
                    disabledText={
                      holdersAll || !holders.length
                        ? 'Позиции ищутся среди треков выбранных правообладателей — сначала выберите их во вкладке «Правообладатели».'
                        : ''
                    }
                    search={async (q) => {
                      const lists = await Promise.all(
                        holders.map((h) => listTracks({ q, contragentId: h.id, pageSize: 20 })),
                      );
                      const seen = new Map();
                      for (const list of lists) {
                        for (const t of list.tracks ?? []) {
                          if (!seen.has(t.id)) {
                            seen.set(t.id, { id: t.id, label: `${t.sku} — ${t.title}`, sub: t.artist });
                          }
                        }
                      }
                      return [...seen.values()];
                    }}
                  />
                )}
              </div>
            </Card>

            {/* ИТОГ И ДЕЙСТВИЯ — ПОД НАСТРОЙКОЙ, на любой вкладке: сначала
                «Рассчитать» — увидеть, кому и сколько, — потом «Сформировать». */}
            <Card>
              <div className="p-6 flex flex-col gap-4">
                {isSummary ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={buildSummary}
                      disabled={Boolean(busy) || Boolean(whyNot)}
                    >
                      Построить сводку
                    </Button>
                    <Button
                      variant="accent"
                      size="sm"
                      onClick={downloadSummary}
                      disabled={Boolean(busy) || Boolean(whyNot)}
                    >
                      Выгрузить в Excel
                    </Button>
                    <span className="text-[12.5px] text-text-muted">
                      {whyNot ||
                        `Сводка по ${SUMMARY_BY.find((b) => b.key === by).label.toLowerCase()} за ${ru(period.from)} — ${ru(period.to)}.`}
                    </span>
                  </div>
                ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={calculate}
                    disabled={Boolean(busy) || Boolean(whyNot)}
                  >
                    Рассчитать
                  </Button>
                  <Button
                    variant="accent"
                    size="sm"
                    onClick={generate}
                    disabled={Boolean(busy) || Boolean(whyNot)}
                  >
                    Сформировать отчёты
                  </Button>
                  <span className="text-[12.5px] text-text-muted">
                    {whyNot ||
                      `Период: ${ru(period.from)} — ${ru(period.to)}. ` +
                        (settings.kinds.length === 2
                          ? 'Сводный и детализированный'
                          : settings.kinds[0] === 'summary'
                            ? 'Только сводный'
                            : 'Только детализированный') +
                        '; несколько файлов придут одним архивом.'}
                  </span>
                </div>
                )}

                {busy && (
                  <div className="flex items-center gap-3 text-[13px] text-text-secondary">
                    <Spinner size={20} className="text-accent" />
                    {busy === 'generate' || busy === 'export' ? 'Собираем файл…' : 'Считаем…'}{' '}
                    По всем правообладателям это может занять до минуты.
                  </div>
                )}
                {error && <div className="text-[13px] text-danger">{error}</div>}

                {preview && !busy && !isSummary && <PreviewTable preview={preview} />}
                {summary && !busy && isSummary && <SummaryTable summary={summary} />}
              </div>
            </Card>
          </div>
        </div>
      }
    </div>
  );
}

function MainTab({
  isSummary,
  year,
  setYear,
  period,
  setPeriod,
  dateBasis,
  setDateBasis,
  kinds,
  setKinds,
  groupDetail,
  setGroupDetail,
}) {
  const tab = (active) =>
    `px-3 py-1.5 text-[12.5px] rounded-input border cursor-pointer bg-transparent font-sans ${
      active ? 'border-accent text-accent' : 'border-border text-text-secondary'
    }`;
  const label = 'text-[12px] text-text-secondary mb-1.5';
  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className={label}>Период реализации</div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {[1, 2, 3, 4].map((q) => {
            const r = quarterRange(year, q);
            return (
              <button
                key={q}
                type="button"
                className={tab(period.from === r.from && period.to === r.to)}
                onClick={() => setPeriod(r)}
              >
                {ROMAN[q - 1]} квартал
              </button>
            );
          })}
          <input
            value={year}
            onChange={(e) => setYear(Number(e.target.value.replace(/\D/g, '')) || '')}
            className={`${inputClass} w-[80px] tabular-nums`}
          />
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={period.from}
            onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))}
            className={`${inputClass} tabular-nums`}
          />
          <span className="text-text-muted">—</span>
          <input
            type="date"
            value={period.to}
            onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))}
            className={`${inputClass} tabular-nums`}
          />
        </div>
      </div>

      <div>
        <div className={label}>Какие отчёты площадок брать</div>
        <div className="flex flex-col gap-2 text-[13.5px] text-text">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              checked={dateBasis === 'period'}
              onChange={() => setDateBasis('period')}
              className="mt-1"
            />
            <span>
              По дате реализации площадки
              <span className="block text-[12.5px] text-text-muted">
                отчёты, привязанные к поступлениям за выбранный период: площадки платят позже,
                и июньский отчёт, оплаченный в июле, — это III квартал
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              checked={dateBasis === 'report'}
              onChange={() => setDateBasis('report')}
              className="mt-1"
            />
            <span>
              По дате формирования отчёта
              <span className="block text-[12.5px] text-text-muted">
                по периоду самого отчёта площадки, целиком внутри выбранного — независимо от
                поступления
              </span>
            </span>
          </label>
        </div>
      </div>

      {!isSummary && (
      <div>
        <div className={label}>Ведомости</div>
        <div className="flex flex-col gap-2 text-[13.5px] text-text">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={kinds.summary}
              onChange={(e) => setKinds((k) => ({ ...k, summary: e.target.checked }))}
            />
            Сводный отчёт — по строке на трек
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={kinds.detailed}
              onChange={(e) => setKinds((k) => ({ ...k, detailed: e.target.checked }))}
            />
            Детализированный отчёт — площадка, параметры, период
          </label>
          <label className="flex items-center gap-2 cursor-pointer ml-6">
            <input
              type="checkbox"
              checked={groupDetail}
              disabled={!kinds.detailed}
              onChange={(e) => setGroupDetail(e.target.checked)}
            />
            Группировать данные детализации
            <span className="text-[12.5px] text-text-muted">
              — одинаковые строки (трек, площадка, параметры, период) складываются в одну
            </span>
          </label>
        </div>
      </div>
      )}

      <div className="text-[12.5px] text-text-muted">
        Валюта отчёта — российский рубль. Валютные отчёты площадок, у которых ещё нет курса, в
        расчёт не попадают — расчёт покажет, какие именно.
      </div>
    </div>
  );
}

/**
 * Выбор «все / по выбранным» с поиском — одинаковый для правообладателей,
 * площадок и позиций номенклатуры (как три вкладки выбора в Dista).
 */
function Picker({ title, all, setAll, allLabel, items, setItems, placeholder, search, disabledText }) {
  const [q, setQ] = useState('');
  const [found, setFound] = useState([]);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const text = q.trim();
    if (!text || all || disabledText) {
      setFound([]);
      return undefined;
    }
    const my = ++seq.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const list = await search(text);
        if (my === seq.current) setFound(list);
      } catch {
        if (my === seq.current) setFound([]);
      } finally {
        if (my === seq.current) setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
    // search меняется на каждой отрисовке — поиск зависит от строки и режима.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, all, disabledText]);

  const chosen = new Set(items.map((i) => i.id));
  const add = (item) => {
    if (!chosen.has(item.id)) setItems((list) => [...list, item]);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4 text-[13.5px] text-text">
        <span className="font-semibold">{title}</span>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="radio" checked={all} onChange={() => setAll(true)} />
          {allLabel}
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="radio" checked={!all} onChange={() => setAll(false)} />
          По выбранным
        </label>
      </div>

      {!all && disabledText && <div className="text-[13px] text-text-muted">{disabledText}</div>}

      {!all && !disabledText && (
        <>
          <div className="relative">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={placeholder}
              className={`${inputClass} w-full`}
            />
            {(found.length > 0 || loading) && (
              <div className="absolute left-0 right-0 top-full mt-1 z-10 bg-surface border border-border rounded-card shadow-card max-h-[320px] overflow-y-auto">
                {loading && <div className="px-3 py-2 text-[12.5px] text-text-muted">Ищем…</div>}
                {found.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => add(item)}
                    disabled={chosen.has(item.id)}
                    className="block w-full text-left px-3 py-2 border-0 bg-transparent cursor-pointer font-sans hover:bg-hover disabled:cursor-default disabled:opacity-50"
                  >
                    <span className="text-[13px] text-text">{item.label}</span>
                    {item.sub && (
                      <span className="text-[12px] text-text-muted"> · {item.sub}</span>
                    )}
                    {chosen.has(item.id) && (
                      <span className="text-[12px] text-accent"> · выбран</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between text-[12.5px] text-text-secondary">
            <span>Выбрано: {items.length}</span>
            {items.length > 0 && (
              <button
                type="button"
                onClick={() => setItems([])}
                className="text-danger bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
              >
                Удалить все
              </button>
            )}
          </div>
          {items.length > 0 && (
            <div className="border border-border rounded-card divide-y divide-border max-h-[360px] overflow-y-auto">
              {items.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="text-[13px] text-text truncate">
                    {item.label}
                    {item.sub && <span className="text-text-muted"> · {item.sub}</span>}
                  </span>
                  <button
                    type="button"
                    onClick={() => setItems((list) => list.filter((x) => x.id !== item.id))}
                    className="text-text-muted hover:text-danger bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px] shrink-0"
                  >
                    убрать
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Плашки «не вошли в расчёт» — общие для ведомостей и сводок. */
function Warnings({ skipped = [], unlinked = [] }) {
  return (
    <>
      {skipped.length > 0 && (
        <div className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-[13px] text-text">
          Не вошли в расчёт — валютные отчёты без курса:{' '}
          {skipped
            .map((r) => `${r.partner} (${ru(r.period_from)} — ${ru(r.period_to)}, ${r.currency})`)
            .join('; ')}
          . Привяжите их к поступлению или задайте курс в окне отчёта.
        </div>
      )}
      {unlinked.length > 0 && (
        <div className="rounded-md border border-border bg-accent-soft px-3 py-2 text-[13px] text-text">
          Не привязаны к поступлению и потому не вошли:{' '}
          {unlinked.map((r) => `${r.partner} (${ru(r.period_from)} — ${ru(r.period_to)})`).join('; ')}
          . Привязать можно во вкладке «Отчёты».
        </div>
      )}
    </>
  );
}

function SummaryTable({ summary }) {
  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-3 py-2 border-b border-border';
  const td = 'px-3 py-2 border-t border-border text-[13px]';
  const numeric = (c) =>
    c.money || ['quantity', 'tracks', 'reports', 'holders'].includes(c.field);
  const show = (c, v) => {
    if (v === null || v === undefined || v === '') return '—';
    if (c.money) return formatMoney(v);
    if (c.field === 'quantity') return Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
    return v;
  };
  // На экране — топ-10 по вознаграждению (их и присылает сервер), итог — по
  // всем строкам, полный список — в Excel.
  const rows = summary.rows;
  return (
    <div className="flex flex-col gap-3">
      <Warnings skipped={summary.skipped_reports} unlinked={summary.unlinked_reports} />
      {!summary.rows.length ? (
        <div className="text-[13px] text-text-muted">За этот период строк нет.</div>
      ) : (
        <>
          <div className="border border-border rounded-card overflow-auto max-h-[560px]">
            <table className="w-full border-collapse">
              <thead className="sticky top-0 bg-surface">
                <tr>
                  {summary.columns.map((c) => (
                    <th key={c.field} className={`${th} ${numeric(c) ? 'text-right' : ''}`}>
                      {c.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.key || i}>
                    {summary.columns.map((c) => (
                      <td
                        key={c.field}
                        className={`${td} ${numeric(c) ? 'tabular-nums text-right whitespace-nowrap' : ''} ${
                          c.field === 'reward' ? 'font-semibold' : ''
                        }`}
                      >
                        {show(c, r[c.field])}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="bg-surface-hover">
                  {summary.columns.map((c, i) => (
                    <td
                      key={c.field}
                      className={`${td} font-semibold ${numeric(c) ? 'tabular-nums text-right whitespace-nowrap' : ''}`}
                    >
                      {i === 0 ? 'Итого' : c.field in summary.totals ? show(c, summary.totals[c.field]) : ''}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="text-[12.5px] text-text-muted">
            {summary.total_rows > rows.length
              ? `Показаны первые ${rows.length} из ${summary.total_rows} по вознаграждению; итог — по всем строкам, полный список — в Excel.`
              : `Строк: ${summary.total_rows}.`}
          </div>
        </>
      )}
    </div>
  );
}

function PreviewTable({ preview }) {
  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-3 py-2 whitespace-nowrap border-b border-border';
  const td = 'px-3 py-2 border-t border-border text-[13px]';
  // Числа не переносятся: знак рубля не должен уезжать на новую строку.
  const num = `${td} tabular-nums text-right whitespace-nowrap`;
  const skipped = preview.skipped_reports ?? [];
  const unlinked = preview.unlinked_reports ?? [];
  return (
    <div className="flex flex-col gap-3">
      {skipped.length > 0 && (
        <div className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-[13px] text-text">
          Не вошли в расчёт — валютные отчёты без курса:{' '}
          {skipped
            .map((r) => `${r.partner} (${ru(r.period_from)} — ${ru(r.period_to)}, ${r.currency})`)
            .join('; ')}
          . Привяжите их к поступлению или задайте курс в окне отчёта.
        </div>
      )}
      {unlinked.length > 0 && (
        <div className="rounded-md border border-border bg-accent-soft px-3 py-2 text-[13px] text-text">
          Не привязаны к поступлению и потому не вошли:{' '}
          {unlinked
            .map((r) => `${r.partner} (${ru(r.period_from)} — ${ru(r.period_to)})`)
            .join('; ')}
          . Привязать можно во вкладке «Отчёты».
        </div>
      )}
      {!preview.contragents.length ? (
        <div className="text-[13px] text-text-muted">
          За этот период начислений нет: у выбранных правообладателей нет строк в загруженных
          отчётах площадок.
        </div>
      ) : (
        <div className="border border-border rounded-card overflow-auto max-h-[480px]">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>Правообладатель</th>
                <th className={`${th} text-right`}>Треков</th>
                <th className={`${th} text-right`}>Количество</th>
                <th className={`${th} text-right`}>Сумма реализации</th>
                <th className={`${th} text-right`}>Вознагр. авторские</th>
                <th className={`${th} text-right`}>Вознагр. смежные</th>
                <th className={`${th} text-right`}>К выплате</th>
              </tr>
            </thead>
            <tbody>
              {preview.contragents.map((c) => (
                <tr key={c.id}>
                  <td className={td}>{c.title}</td>
                  <td className={num}>{c.tracks}</td>
                  <td className={num}>
                    {Number(c.quantity).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}
                  </td>
                  <td className={num}>{formatMoney(c.realization)}</td>
                  <td className={num}>{formatMoney(c.reward_author)}</td>
                  <td className={num}>{formatMoney(c.reward_related)}</td>
                  <td className={`${num} font-semibold`}>{formatMoney(c.reward)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {preview.contragents.length > 1 && (
        <div className="text-[13px] text-text">
          Правообладателей: <b>{preview.totals.contragents}</b> · сумма реализации{' '}
          <b className="tabular-nums">{formatMoney(preview.totals.realization)}</b> · к выплате{' '}
          <b className="tabular-nums">{formatMoney(preview.totals.reward)}</b>
        </div>
      )}
    </div>
  );
}
