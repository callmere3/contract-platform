import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { TrashIcon } from '../components/ui/icons';
import { useAuth } from '../auth/AuthContext';
import { canManagePartnerReports } from '../auth/permissions';
import { listPartners } from '../api/partners';
import {
  createReport,
  deleteReport,
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
 * ПРАВИЛО РАЗБОРА НАСТРАИВАЕТСЯ ЗДЕСЬ ЖЕ, на предпросмотре: колонки выбираются
 * ПО НАЗВАНИЮ из списка, который сервер прочитал в шапке файла. Первый файл
 * партнёра и есть образец, а галочка «запомнить правило» превращает разовую
 * настройку в постоянную.
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

// Поля единого формата: к ним сводится любой отчёт площадки.
const FIELDS = [
  { name: 'sku', label: 'Артикул', required: true },
  { name: 'title', label: 'Наименование' },
  { name: 'quantity', label: 'Количество' },
  { name: 'amount_author', label: 'Сумма авторских' },
  { name: 'amount_related', label: 'Сумма смежных' },
];

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

  async function runPreview(nextFile = file, nextMapping = mapping, nextVat = vatRate) {
    if (!nextFile || !partnerId) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await previewReport({
        partnerId,
        file: nextFile,
        // Пустое правило = «возьми сохранённое у партнёра или догадайся».
        mapping: Object.keys(nextMapping).length ? nextMapping : null,
        vatRate: nextVat,
      });
      setPreview(data);
      setMapping(data.mapping ?? {});
      setVatRate(data.vat_rate ?? '');
    } catch (e) {
      setError(e.message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  function takeFile(next) {
    setFile(next);
    setPreview(null);
    setMapping({});
    if (next && partnerId) runPreview(next, {}, vatRate);
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
        periodFrom: range.from,
        periodTo: range.to,
        saveRuleToo: rememberRule,
      });
      setNotice(
        `Отчёт «${report.file_name}» загружен за ${report.period_label}: ` +
          `${report.rows_count} строк, авторские ${report.total_author} ₽, ` +
          `смежные ${report.total_related} ₽.`,
      );
      setFile(null);
      setPreview(null);
      setMapping({});
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
              <select
                value={partnerId}
                onChange={(e) => {
                  setPartnerId(e.target.value);
                  setPreview(null);
                  setMapping({});
                }}
                className={`${inputClass} min-w-[220px]`}
              >
                <option value="">— выберите —</option>
                {partners.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
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
            {!partnerId && (
              <div className="text-[12.5px] text-danger mt-2">Сначала выберите партнёра</div>
            )}
          </div>

          {busy && <div className="px-5 pb-5 text-[13px] text-text-muted">Читаем файл…</div>}

          {preview && (
            <div className="px-5 pb-5">
              <div className="text-[12.5px] text-text-secondary mb-3">
                Шапка найдена в строке {preview.header_row}. Колонок в файле:{' '}
                {preview.columns.length}.{' '}
                {preview.rule_saved
                  ? 'Применено сохранённое правило партнёра.'
                  : 'Правила у партнёра ещё нет — соответствие предложено по названиям колонок.'}
              </div>

              <div className="flex flex-col gap-3 mb-4">
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
                        {isFormula ? (
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
                      {isFormula && (
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

              <Button variant="secondary" size="sm" onClick={() => runPreview()} disabled={busy}>
                Пересобрать по правилу
              </Button>

              {preview.problems.length > 0 && (
                <div className="mt-4 text-[13px] text-danger">
                  {preview.problems.map((p) => (
                    <div key={p}>{p}</div>
                  ))}
                </div>
              )}

              {preview.preview.length > 0 && (
                <>
                  <div className="mt-4 overflow-x-auto border border-border rounded-card">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          <th className={th}>Строка</th>
                          <th className={th}>Артикул</th>
                          <th className={th}>Наименование</th>
                          <th className={th}>Количество</th>
                          <th className={th}>Авторские, ₽</th>
                          <th className={th}>Смежные, ₽</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.preview.map((r) => (
                          <tr key={r.row} className={r.problems.length ? 'bg-danger-soft' : undefined}>
                            <td className={`${td} tabular-nums text-text-muted`}>{r.row}</td>
                            <td className={`${td} font-mono`}>{r.sku || '—'}</td>
                            <td className={td}>{r.title || '—'}</td>
                            <td className={`${td} tabular-nums`}>{r.quantity ?? '—'}</td>
                            <td className={`${td} tabular-nums`}>{r.amount_author}</td>
                            <td className={`${td} tabular-nums`}>{r.amount_related}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 text-[13px] text-text">
                    Всего строк: <b className="tabular-nums">{preview.totals.rows}</b> · авторские{' '}
                    <b className="tabular-nums">{preview.totals.amount_author} ₽</b> · смежные{' '}
                    <b className="tabular-nums">{preview.totals.amount_related} ₽</b> · итого{' '}
                    <b className="tabular-nums">{preview.totals.total} ₽</b>
                  </div>

                  {/* Эти два числа — главное, что нужно увидеть ДО загрузки:
                      по строкам без артикула деньги придут «ничьи», а строки с
                      непрочитанной суммой лягут нулями. */}
                  {(preview.totals.no_sku > 0 || preview.totals.problem_rows > 0) && (
                    <div className="mt-2 text-[12.5px] text-danger">
                      {preview.totals.no_sku > 0 && (
                        <div>
                          Без артикула: {preview.totals.no_sku} строк — они загрузятся, но к трекам
                          привязаны не будут.
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

                  {preview.preview_limited && (
                    <div className="mt-1 text-[12px] text-text-muted">
                      В таблице первые {preview.preview.length} строк, итоги — по всему файлу.
                    </div>
                  )}

                  <div className="mt-4 flex flex-wrap items-center gap-4">
                    <Button variant="accent" size="sm" onClick={save} disabled={busy}>
                      {busy ? 'Загружаем…' : 'Загрузить отчёт'}
                    </Button>
                    <span className="text-[12.5px] text-text-muted">
                      период: {range.from} — {range.to}
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
              авторские {totals.author} ₽ · смежные {totals.related} ₽
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
                  <th className={th}>Строк</th>
                  <th className={th}>Не разнесено</th>
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
                    <td className={`${td} tabular-nums`}>{r.rows_count}</td>
                    <td
                      className={`${td} tabular-nums ${
                        r.unmatched_count ? 'text-danger' : 'text-text-muted'
                      }`}
                      title="Строки без артикула или с артикулом, которого нет в каталоге"
                    >
                      {r.unmatched_count || '—'}
                    </td>
                    <td className={`${td} tabular-nums`}>{r.total_author}</td>
                    <td className={`${td} tabular-nums`}>{r.total_related}</td>
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
