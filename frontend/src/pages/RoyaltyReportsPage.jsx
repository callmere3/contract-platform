import { useEffect, useRef, useState } from 'react';
import { PageHeader } from '../components/ui/PageHeader';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Spinner } from '../components/ui/Spinner';
import { searchContragents } from '../api/contragents';
import { listPartners } from '../api/partners';
import { listTracks } from '../api/nomenclature';
import { generateRoyalty, previewRoyalty } from '../api/royaltyReports';
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
 * (ведомости каждому выбранному), «По правообладателю» и «По объекту». Пока
 * работает первый; два других — следующим шагом.
 *
 * Считает СЕРВЕР (`royalty_reports.py`): суммы приходят строками, и
 * складывать их на экране нельзя.
 */
const MODES = [
  { key: 'holders', label: 'Правообладателям' },
  { key: 'holder', label: 'По правообладателю' },
  { key: 'object', label: 'По объекту' },
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

const inputClass =
  'bg-input-bg border border-border rounded-input px-3 py-2 text-[13px] text-text outline-none font-sans';

export function RoyaltyReportsPage() {
  const [mode, setMode] = useState('holders');
  const [modeOpen, setModeOpen] = useState(false);
  const [tab, setTab] = useState('main');

  const start = lastQuarter();
  const [year, setYear] = useState(start.year);
  const [period, setPeriod] = useState(quarterRange(start.year, start.q));
  const [dateBasis, setDateBasis] = useState('period');
  const [kinds, setKinds] = useState({ summary: true, detailed: true });
  const [groupDetail, setGroupDetail] = useState(true);

  // Выбор: режим «все/по выбранным» и сам список. У правообладателей «все» —
  // это те, кому за период есть что начислить.
  const [holdersAll, setHoldersAll] = useState(false);
  const [holders, setHolders] = useState([]);
  const [partnersAll, setPartnersAll] = useState(true);
  const [partners, setPartners] = useState([]);
  const [tracksAll, setTracksAll] = useState(true);
  const [tracks, setTracks] = useState([]);

  const [preview, setPreview] = useState(null);
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
  };
  // Любая правка настроек делает прежний расчёт недействительным: показывать
  // числа, посчитанные для другого выбора, значит вводить в заблуждение.
  const settingsKey = JSON.stringify(settings);
  useEffect(() => {
    setPreview(null);
  }, [settingsKey]);

  const ready = holdersAll || holders.length > 0;
  const whyNot = !ready
    ? 'Выберите правообладателей во вкладке «Правообладатели»'
    : !settings.kinds.length
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
    <div className="max-w-[1280px] mx-auto px-8 pt-12 pb-20">
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
                      setMode(m.key);
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
        Квартальные ведомости правообладателям по загруженным отчётам площадок: сколько
        причитается каждому по его долям и ставкам роялти.
      </PageHeader>

      {mode !== 'holders' ? (
        <Card>
          <div className="p-10 text-center text-[14px] text-text-secondary">
            Режим «{MODES.find((m) => m.key === mode).label}» — следующий шаг. Пока работает
            «Правообладателям».
          </div>
        </Card>
      ) : (
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
                {tab === 'main' && (
                  <MainTab
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

                {busy && (
                  <div className="flex items-center gap-3 text-[13px] text-text-secondary">
                    <Spinner size={20} className="text-accent" />
                    {busy === 'preview' ? 'Считаем…' : 'Собираем файлы…'} У крупного
                    правообладателя это может занять до минуты.
                  </div>
                )}
                {error && <div className="text-[13px] text-danger">{error}</div>}

                {preview && !busy && <PreviewTable preview={preview} />}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function MainTab({
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

function PreviewTable({ preview }) {
  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-3 py-2 whitespace-nowrap border-b border-border';
  const td = 'px-3 py-2 border-t border-border text-[13px]';
  const num = `${td} tabular-nums text-right`;
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
