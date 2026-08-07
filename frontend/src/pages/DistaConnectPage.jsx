import { useEffect, useRef, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import {
  distaOnlyOurs,
  distaOnlyOursExport,
  distaReconcile,
  distaSetExcluded,
  distaStatus,
} from '../api/dista';

/**
 * «Dista Connect» — только admin (canUseDistaSync / CAN_USE_DISTA_SYNC).
 *
 * Сверка нашей базы контрагентов с выгрузкой из Dista Music (Excel: id +
 * Название). Наш сервис — мастер данных; от Dista нужен лишь факт нового
 * контрагента и его id для связки (Contragent.dista_id).
 *
 * Двухшаговый цикл (как экран подтверждения правки карточки): сначала
 * «Проверить» показывает ПЛАН (что свяжется/создастся/пропустится), ничего не
 * записывая; затем «Применить» проставляет dista_id совпавшим и заводит новых.
 * Сверка не трогает бизнес-поля существующих карточек — только связку.
 */

// Секции детального плана. already_linked показываем только счётчиком (действий
// не требует). Порядок — по важности для глаза.
const SECTIONS = [
  {
    key: 'link',
    title: 'Связать',
    tone: 'ok',
    hint: 'Имя совпало с карточкой — проставим dista_id',
    render: (x) => `${x.name}  →  ${x.card_title}`,
  },
  {
    key: 'create',
    title: 'Создать',
    tone: 'info',
    hint: 'Нет у нас — заведём карточку (только имя + dista_id, реквизиты пусты)',
    render: (x) => `${x.name}   (id ${x.dista_id})`,
  },
  {
    key: 'ambiguous',
    title: 'Спорные',
    tone: 'warn',
    hint: 'Совпало с несколькими карточками — не трогаем, свяжите вручную',
    render: (x) => `${x.name}:  ${x.candidates.join('  ·  ')}`,
  },
  {
    key: 'only_ours',
    title: 'Нет в Dista',
    tone: 'muted',
    hint: 'Есть у нас, но нет в выгрузке — завести в Dista вручную',
    render: (x) => x.title,
  },
  {
    key: 'skipped',
    title: 'Пропущено',
    tone: 'muted',
    hint: 'Строки без id или без названия — связать/создать нечего',
    render: (x) => `строка ${x.row ?? '—'}: ${x.reason}`,
  },
];

const TONE_TEXT = {
  ok: 'text-emerald-600 dark:text-emerald-400',
  info: 'text-sky-600 dark:text-sky-400',
  warn: 'text-amber-600 dark:text-amber-400',
  muted: 'text-text-muted',
};

function StatTile({ label, count, tone }) {
  return (
    <div className="flex-1 min-w-[120px] border border-border rounded-input px-4 py-3 bg-surface">
      <div className={`text-2xl font-bold tabular-nums ${TONE_TEXT[tone] || 'text-text'}`}>
        {count}
      </div>
      <div className="text-xs text-text-secondary mt-0.5">{label}</div>
    </div>
  );
}

export function DistaConnectPage() {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null); // ответ reconcile(commit=false)
  const [applied, setApplied] = useState(null); // {linked, created} после commit
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(null); // {total, linked, excluded, unlinked}
  const [lists, setLists] = useState(null); // {pending: [...], excluded: [...]}
  const [downloading, setDownloading] = useState(false);
  const [excludeBusyId, setExcludeBusyId] = useState(null);

  const loadStatus = () => distaStatus().then(setStatus).catch(() => {});
  const loadLists = () => distaOnlyOurs().then(setLists).catch(() => {});
  const refresh = () => {
    loadStatus();
    loadLists();
  };
  useEffect(() => {
    refresh();
  }, []);

  async function toggleExclude(id, excluded) {
    setExcludeBusyId(id);
    setError('');
    try {
      await distaSetExcluded(id, excluded);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setExcludeBusyId(null);
    }
  }

  async function downloadOnlyOurs() {
    setDownloading(true);
    setError('');
    try {
      const blob = await distaOnlyOursExport();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'dista_to_add.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading(false);
    }
  }

  function onPick(e) {
    setFile(e.target.files?.[0] || null);
    setPreview(null);
    setApplied(null);
    setError('');
  }

  async function check() {
    if (!file) return;
    setBusy(true);
    setError('');
    setApplied(null);
    try {
      setPreview(await distaReconcile(file, false));
    } catch (e) {
      setError(e.message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const res = await distaReconcile(file, true);
      setApplied(res.applied);
      setPreview(null); // план применён — устарел; для нового цикла жмут «Проверить»
      refresh(); // связанных стало больше — обновить сводку и список «нет в Dista»
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const c = preview?.counts;
  const hasActions = c && (c.link > 0 || c.create > 0);

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <h1 className="text-2xl font-bold text-text">Dista Connect</h1>
      <p className="text-sm text-text-secondary mt-2 leading-relaxed max-w-[70ch]">
        Сверка базы контрагентов с выгрузкой из Dista Music. Загрузите Excel из Dista (колонки{' '}
        <b>id</b> и <b>Название</b>). Сначала «Проверить» покажет план — что свяжется, что
        создастся, что нужно завести в Dista вручную. Записывается только после «Применить», и
        только связка <b>dista_id</b>: реквизиты, номер договора и прочие поля существующих карточек
        не затрагиваются.
      </p>

      {/* Сводка связки + выгрузка «Нет в Dista» (Этап 2). Доступна всегда, без
          загрузки файла: это standing-список карточек без dista_id — тех, кого
          нужно завести в Dista вручную. */}
      <Card className="mt-6 p-5">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="text-sm text-text-secondary">
            {status ? (
              <>
                Всего карточек <b className="text-text tabular-nums">{status.total}</b> · связано с
                Dista <b className="text-text tabular-nums">{status.linked}</b> · не связано{' '}
                <b className="text-text tabular-nums">{status.unlinked}</b>
                {status.excluded > 0 && (
                  <> · исключено <b className="text-text tabular-nums">{status.excluded}</b></>
                )}
              </>
            ) : (
              'Загрузка сводки…'
            )}
          </div>
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              onClick={downloadOnlyOurs}
              disabled={downloading || (status && status.unlinked === 0)}
            >
              {downloading
                ? 'Готовим файл…'
                : `Скачать список «Нет в Dista»${status ? ` (${status.unlinked})` : ''}`}
            </Button>
          </div>
        </div>
        <p className="text-xs text-text-muted mt-2 leading-relaxed">
          Файл с колонками Название + Артикул — заведите этих контрагентов в Dista вручную и впишите
          артикул в заметку карточки. Тогда следующая сверка свяжет их автоматически по артикулу.
          Тестовых контрагентов можно «Исключить» — они уйдут из списка и из файла.
        </p>

        {lists && (
          <div className="mt-4 border-t border-border pt-3">
            {lists.pending.length === 0 ? (
              <div className="text-[13px] text-text-muted">
                Нечего заводить: все карточки связаны или исключены.
              </div>
            ) : (
              <div className="flex flex-col max-h-[320px] overflow-y-auto">
                {lists.pending.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center gap-3 py-1.5 border-b border-border/50 last:border-b-0"
                  >
                    <span className="text-[13px] text-text flex-1 truncate">{c.title}</span>
                    <span className="text-[12px] text-text-muted tabular-nums">{c.article || '—'}</span>
                    <button
                      onClick={() => toggleExclude(c.id, true)}
                      disabled={excludeBusyId === c.id}
                      className="text-[12px] text-text-secondary hover:text-accent bg-transparent border-none cursor-pointer p-0 font-sans disabled:opacity-40"
                    >
                      Исключить
                    </button>
                  </div>
                ))}
              </div>
            )}

            {lists.excluded.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer list-none text-[12px] font-semibold text-text-muted select-none">
                  Исключённые из Dista · {lists.excluded.length}
                </summary>
                <div className="flex flex-col mt-1 max-h-[240px] overflow-y-auto">
                  {lists.excluded.map((c) => (
                    <div
                      key={c.id}
                      className="flex items-center gap-3 py-1.5 border-b border-border/50 last:border-b-0"
                    >
                      <span className="text-[13px] text-text-secondary flex-1 truncate">{c.title}</span>
                      <span className="text-[12px] text-text-muted tabular-nums">{c.article || '—'}</span>
                      <button
                        onClick={() => toggleExclude(c.id, false)}
                        disabled={excludeBusyId === c.id}
                        className="text-[12px] text-text-secondary hover:text-text bg-transparent border-none cursor-pointer p-0 font-sans disabled:opacity-40"
                      >
                        Вернуть
                      </button>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </Card>

      <Card className="mt-4 p-5">
        <div className="flex items-center gap-3 flex-wrap">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx"
            onChange={onPick}
            className="hidden"
          />
          <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()}>
            {file ? 'Выбрать другой файл' : 'Выбрать файл .xlsx'}
          </Button>
          <span className="text-[13px] text-text-secondary truncate max-w-[280px]">
            {file ? file.name : 'файл не выбран'}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={check} disabled={!file || busy}>
              {busy && !applied ? 'Проверяем…' : 'Проверить'}
            </Button>
          </div>
        </div>
      </Card>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}

      {applied && (
        <div className="mt-6 border border-emerald-500/40 bg-emerald-500/5 rounded-card p-4 text-sm text-text">
          Готово: связано <b>{applied.linked}</b>, создано новых <b>{applied.created}</b>. Чтобы
          свериться заново, нажмите «Проверить».
        </div>
      )}

      {preview && (
        <div className="mt-6">
          <div className="flex gap-3 flex-wrap">
            <StatTile label="Связать" count={c.link} tone="ok" />
            <StatTile label="Создать" count={c.create} tone="info" />
            <StatTile label="Уже связано" count={c.already_linked} tone="muted" />
            <StatTile label="Спорные" count={c.ambiguous} tone="warn" />
            <StatTile label="Нет в Dista" count={c.only_ours} tone="muted" />
            <StatTile label="Пропущено" count={c.skipped} tone="muted" />
          </div>

          <div className="flex items-center gap-3 mt-5">
            <Button variant="primary" size="sm" onClick={apply} disabled={!hasActions || busy}>
              {busy ? 'Применяем…' : `Применить (свяжется ${c.link}, создастся ${c.create})`}
            </Button>
            {!hasActions && (
              <span className="text-[13px] text-text-secondary">
                Применять нечего — новых связей и карточек нет.
              </span>
            )}
          </div>

          <div className="mt-6 flex flex-col gap-4">
            {SECTIONS.map((s) => {
              const rows = preview[s.key] || [];
              if (rows.length === 0) return null;
              return (
                <Card key={s.key} className="p-0">
                  <details>
                    <summary className="cursor-pointer list-none px-4 py-3 flex items-center gap-2 select-none">
                      <span className={`text-sm font-semibold ${TONE_TEXT[s.tone]}`}>{s.title}</span>
                      <span className="text-xs text-text-muted">· {rows.length}</span>
                      <span className="text-xs text-text-secondary ml-2 font-normal">{s.hint}</span>
                    </summary>
                    <div className="border-t border-border max-h-[360px] overflow-y-auto">
                      {rows.map((x, i) => (
                        <div
                          key={i}
                          className="px-4 py-1.5 text-[13px] text-text border-b border-border/50 last:border-b-0 break-words"
                        >
                          {s.render(x)}
                        </div>
                      ))}
                    </div>
                  </details>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
