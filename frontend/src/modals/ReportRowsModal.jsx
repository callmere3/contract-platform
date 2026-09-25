import { useEffect, useRef, useState } from 'react';
import { Modal, ModalAction } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { ComboCell } from '../components/ui/ComboCell';
import { PencilIcon, TrashIcon } from '../components/ui/icons';
import { useModal } from './ModalProvider';
import {
  currencySign,
  exportUnmatched,
  rateText,
  reportRows,
  updateReport,
} from '../api/partnerReports';
import { formatMoney } from '../api/finance';
import Region from '../components/ui/Region';

/**
 * ЗАГРУЖЕННЫЙ ОТЧЁТ ЦЕЛИКОМ — «как в Dista» (просьба владельца 24.09.2026,
 * его скриншот «Расходной накладной»).
 *
 * Раньше загруженный отчёт нельзя было посмотреть вовсе: в списке стояли
 * только итоги, а что внутри — знал лишь предпросмотр, и то до загрузки.
 * Проверить «а что мы, собственно, залили» было нечем.
 *
 * ЧТО ВЗЯТО ИЗ DISTA И ЧТО НЕТ. Взята форма: шапка документа, под ней
 * позиции, внизу итог «позиций / количество / сумма». НЕ взяты поля,
 * которых у нас нет и не будет: склад, договор, срок оплаты, сценарий
 * оформления, цена за штуку. Dista — общая программа для разного бизнеса, и
 * половина её граф к музыкальным отчётам отношения не имеет; копировать их
 * значило бы завести пустые колонки, которые никто не заполнит.
 *
 * НАЗВАНИЕ И КОД — ИЗ НОМЕНКЛАТУРЫ, а не из файла площадки: в детализации
 * правообладателю трек называется так, как он называется у нас. Из строки
 * отчёта название берётся только там, где трека нет.
 *
 * ПРАВКА — КАРАНДАШОМ В ШАПКЕ, рядом с мусоркой (просьба владельца
 * 24.09.2026): это действия над самим документом, и место им там же, где
 * во всех остальных карточках проекта. Правится ШАПКА, а не данные: период,
 * четыре параметра и привязка к поступлению. Строки, суммы и привязка к
 * каталогу не меняются — «исправленный» отчёт, у которого файл говорит
 * одно, а база другое, объяснить потом нечем.
 */

/**
 * ВЕСЬ ОТЧЁТ ОДНОЙ ТАБЛИЦЕЙ, БЕЗ СТРАНИЦ (просьба владельца 24.09.2026:
 * «всё на одной странице, даже если будет большая прокрутка»).
 *
 * Отрисовать всё разом нельзя: у Believe полмиллиона строк, у ОМА полтора
 * миллиона, и браузер на таком ляжет. Поэтому прокрутка — на весь отчёт, а
 * в документе живут только видимые строки плюс запас (`OVERSCAN`); сверху и
 * снизу их подпирают пустые строки нужной высоты. Сами строки приезжают с
 * сервера кусками по `BLOCK` по мере прокрутки и держатся в кеше, пока
 * человек рядом (`KEEP_BLOCKS`).
 *
 * ВЫСОТА СТРОКИ ЗАДАНА ЖЁСТКО (`ROW_H`), и на этом держится весь расчёт:
 * номер строки получается делением прокрутки на высоту. Поэтому ячейки не
 * переносят текст, а обрезают его многоточием, и полный текст — в
 * подсказке. По той же причине ширины колонок заданы (`table-fixed`): иначе
 * таблица пересчитывала бы их по каждому новому куску, и колонки прыгали бы
 * под рукой.
 *
 * ОЧЕНЬ ДЛИННЫЙ ОТЧЁТ ПРОКРУЧИВАЕТСЯ В МАСШТАБЕ. Браузеры не рисуют
 * элементы выше нескольких миллионов пикселей (Firefox — около 17,9 млн), а
 * полтора миллиона строк по 27 px — это 40 млн. Выше `MAX_HEIGHT` высота
 * таблицы перестаёт расти, и полоса прокрутки просто пробегает весь отчёт
 * пропорционально: одно деление колеса мыши тогда сдвигает больше строк.
 */
const BLOCK = 500; // строк за запрос — столько отдаёт сервер максимум
const ROW_H = 27;
const OVERSCAN = 20;
const MAX_HEIGHT = 8_000_000;
const KEEP_BLOCKS = 40;

const ATTRS = [
  { name: 'content_type', label: 'Тип контента' },
  { name: 'usage_type', label: 'Тип использования' },
  { name: 'usage_kind', label: 'Вид использования' },
  { name: 'territory', label: 'Территория' },
];

export function ReportRowsModal({
  report,
  level,
  isTop,
  onLink,
  onDelete,
  onChanged,
  attrOptions = {},
}) {
  const { closeModal } = useModal();
  // Карточка живёт в состоянии: после правки сервер возвращает её целиком, и
  // окно должно показать новое, не дожидаясь, пока перечитается список.
  const [card, setCard] = useState(report);
  const [perRow, setPerRow] = useState({});
  // null — отчёт ещё не открылся: пока не знаем числа строк, рисовать нечего.
  const [total, setTotal] = useState(null);
  const [error, setError] = useState('');

  // Куски строк: номер куска → строки. В ref, а не в состоянии: их много и
  // они приходят вразнобой; перерисовку зовёт счётчик `version`.
  const blocks = useRef(new Map());
  const inflight = useRef(new Set());
  const [version, setVersion] = useState(0);
  // Поколение данных. После правки шапки куски перечитываются (в строках
  // лежит снимок параметров), и ответ, пришедший на старый запрос, должен
  // быть выброшен, а не лечь в свежий кеш.
  const [gen, setGen] = useState(0);
  const genRef = useRef(0);

  const scroller = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(800);

  const [editing, setEditing] = useState(false);
  const [exporting, setExporting] = useState(false);

  async function downloadUnmatched() {
    setExporting(true);
    setError('');
    try {
      const { blob, filename } = await exportUnmatched(card.id);
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
      setExporting(false);
    }
  }
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);

  // Первый кусок заодно говорит, сколько строк в отчёте и какие параметры
  // взяты из колонок файла.
  useEffect(() => {
    genRef.current = gen;
    blocks.current = new Map();
    inflight.current = new Set();
    let cancelled = false;
    reportRows(card.id, { page: 1, pageSize: BLOCK })
      .then((data) => {
        if (cancelled) return;
        blocks.current.set(0, data.rows ?? []);
        setTotal(data.total ?? 0);
        setPerRow(data.per_row_attributes ?? {});
        setVersion((v) => v + 1);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [card.id, gen]);

  // Высота видимой части: окно во весь экран, и она меняется вместе с окном
  // браузера.
  const tableShown = total !== null;
  // ОТЧЁТ ИЗ НЕСКОЛЬКИХ ФАЙЛОВ (ВОИС шлёт два за месяц): первым столбцом —
  // номер файла, с его именем в подсказке. Номера строк на сервере сквозные,
  // диапазоны файлов лежат в `files`.
  const ranges = card.files || [];
  const multi = ranges.length > 1;
  const widths = multi ? [56, ...COLUMN_WIDTHS] : COLUMN_WIDTHS;
  const fileOf = (row) => {
    const index = ranges.findIndex((f) => row >= f.first_row && row <= f.last_row);
    return index < 0 ? null : { index, name: ranges[index].name };
  };
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setViewH(el.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [tableShown]);

  // КАКИЕ СТРОКИ СЕЙЧАС НА ЭКРАНЕ. Без масштаба это просто прокрутка,
  // делённая на высоту строки; с масштабом — доля пройденной прокрутки от
  // всего отчёта (см. MAX_HEIGHT в начале файла).
  const rowsCount = total ?? 0;
  const fullH = rowsCount * ROW_H;
  const bodyH = Math.min(fullH, MAX_HEIGHT);
  const viewRows = Math.ceil(viewH / ROW_H);
  const lastStart = Math.max(0, rowsCount - viewRows);
  const maxScroll = Math.max(1, bodyH - viewH);
  const startExact =
    fullH <= MAX_HEIGHT
      ? scrollTop / ROW_H
      : Math.min(1, scrollTop / maxScroll) * lastStart;
  const first = Math.max(0, Math.floor(startExact) - OVERSCAN);
  const last = Math.min(rowsCount, Math.ceil(startExact) + viewRows + OVERSCAN);
  const topPad = Math.min(bodyH, Math.max(0, scrollTop - (startExact - first) * ROW_H));
  const bottomPad = Math.max(0, bodyH - topPad - (last - first) * ROW_H);

  // ДОГРУЗКА КУСКОВ — с задержкой: пока ползунок тащат, экран пробегает
  // сотни кусков, и просить каждый из них незачем. Спрашиваем то, на чём
  // остановились.
  useEffect(() => {
    if (total === null || last <= first) return;
    const timer = setTimeout(() => {
      const from = Math.floor(first / BLOCK);
      const to = Math.floor((last - 1) / BLOCK);
      const myGen = genRef.current;
      for (let b = from; b <= to; b += 1) {
        if (blocks.current.has(b) || inflight.current.has(b)) continue;
        inflight.current.add(b);
        reportRows(card.id, { page: b + 1, pageSize: BLOCK })
          .then((data) => {
            if (genRef.current !== myGen) return;
            blocks.current.set(b, data.rows ?? []);
            // Кеш не растёт бесконечно: дальние от экрана куски выбрасываем,
            // вернётся человек — приедут заново.
            if (blocks.current.size > KEEP_BLOCKS) {
              const center = (from + to) / 2;
              const far = [...blocks.current.keys()]
                .sort((x, y) => Math.abs(y - center) - Math.abs(x - center))
                .slice(0, blocks.current.size - KEEP_BLOCKS);
              for (const key of far) blocks.current.delete(key);
            }
            setVersion((v) => v + 1);
          })
          .catch((e) => genRef.current === myGen && setError(e.message))
          .finally(() => inflight.current.delete(b));
      }
    }, 120);
    return () => clearTimeout(timer);
  }, [card.id, total, first, last, version]);

  function startEdit() {
    setDraft({
      from: card.period?.from ?? '',
      to: card.period?.to ?? '',
      ...Object.fromEntries(ATTRS.map((a) => [a.name, card[a.name] ?? ''])),
      rate: rateText(card.currency_rate),
    });
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError('');
    try {
      const { report: fresh } = await updateReport(card.id, {
        periodFrom: draft.from,
        periodTo: draft.to,
        attributes: Object.fromEntries(ATTRS.map((a) => [a.name, draft[a.name]])),
        // Курс шлём, только если его и правда поменяли: пересчёт строк —
        // тяжёлая операция, и гонять её на правке периода незачем.
        currencyRate:
          foreign && draft.rate !== rateText(card.currency_rate) ? draft.rate : undefined,
      });
      setCard(fresh);
      setEditing(false);
      // В строках лежит снимок параметров отчёта — перечитываем их.
      setGen((g) => g + 1);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-2 py-1.5 whitespace-nowrap border-b border-border bg-surface sticky top-0 z-[1]';
  // Высота строки задана жёстко — см. ROW_H: ячейка не переносит текст.
  const td =
    'px-2 py-0 border-t border-border text-[12.5px] whitespace-nowrap overflow-hidden text-ellipsis';
  const field =
    'bg-input-bg border border-border rounded-input px-2 py-1 text-[12.5px] text-text outline-none font-sans';
  const count = (v) => Number(v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  // Валютный отчёт: курс правится; пока его нет — суммы в валюте, не в рублях.
  const foreign = Boolean(card.currency && card.currency !== 'RUB');
  const sign = currencySign(card);
  const money = (v) => (sign ? formatMoney(v).replace('₽', sign) : formatMoney(v));

  return (
    <Modal
      title={`Отчёт: ${card.partner} · ${card.period_label}`}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      // ВО ВЕСЬ ЭКРАН (просьба владельца 24.09.2026): отчёт — это таблица на
      // сотни строк, и в окне 1320×85% её листали чаще нужного, а поле
      // вокруг пустовало. Шапка отчёта стоит на месте, таблица забирает всю
      // оставшуюся высоту и прокручивается сама.
      fullscreen
      actions={
        !editing && (
          <>
            <ModalAction icon={<PencilIcon />} title="Изменить" onClick={startEdit} />
            <ModalAction
              icon={<TrashIcon />}
              title="Удалить отчёт"
              danger
              onClick={() => onDelete?.(card)}
            />
          </>
        )
      }
      footer={
        editing ? (
          <>
            <span className="text-[12.5px] text-text-muted mr-auto">
              Правится только шапка: строки и суммы останутся как есть.
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              Отмена
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </>
        ) : (
          <>
            {/* ИТОГ КАК В DISTA: позиций, количество, сумма. Числа берём из
                самого отчёта, а не складываем показанную страницу: страница
                одна из многих, а итог — по всему файлу. */}
            <span className="text-[12.5px] text-text mr-auto tabular-nums">
              Позиций: <b>{card.rows_count}</b> · Кол-во:{' '}
              <b>{count(card.total_quantity)}</b> · Сумма: <b>{money(card.total)}</b>
              <span className="text-text-muted">
                {' '}
                (авторские {money(card.total_author)}, смежные{' '}
                {money(card.total_related)})
              </span>
            </span>
            {/* Кнопки «Закрыть» нет (просьба владельца 24.09.2026): её работу
                делает крестик в шапке, а два способа одного действия
                заставляют гадать, есть ли между ними разница. */}
          </>
        )
      }
    >
      {/* ШАПКА ДОКУМЕНТА — только наши поля. Роль «Основания» из Dista здесь
          играет имя файла: по нему отчёт и находят среди присланного.

          ДВЕ КОЛОНКИ С ПОСТОЯННЫМ ПОРЯДКОМ (замечание владельца 24.09.2026).
          Раньше это была одна сетка пар «подпись — значение», и у валютного
          отчёта строка «Курс к рублю» сдвигала всё, что шло после неё:
          «Поступление» и «Вне каталога» переезжали из колонки в колонку.
          Теперь привязка и выгрузка всегда третьей и четвёртой строкой
          слева, а курс — последней, чтобы ничего не двигать. */}
      <div className="grid grid-cols-2 gap-x-10 text-[12.5px] mb-4 shrink-0">
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center content-start">
          <span className="text-text-secondary">Площадка</span>
          {/* Приписка ВНУТРИ ячейки: сетка здесь двухколоночная, и отдельным
              элементом она встала бы в колонку подписей и сдвинула всё ниже. */}
          <span className="text-text font-semibold">
            {card.partner}
            <Region value={card.region} />
          </span>
          <span className="text-text-secondary">Файл</span>
          <span className="text-text truncate" data-hint={card.file_name}>
            {card.file_name}
            {card.sheet ? ` · лист «${card.sheet}»` : ''}
          </span>
          <span className="text-text-secondary">Поступление</span>
          <span className="text-text">
            {card.payment_label ?? <span className="text-text-muted">не привязано</span>}{' '}
            <button
              type="button"
              onClick={() =>
                // Свежая карточка приходит обратно: иначе в шапке так и висело
                // бы прежнее поступление, пока окно не откроют заново.
                onLink?.(card, (fresh) => {
                  if (!fresh) return;
                  setCard(fresh);
                  // Привязка ставит курс и пересчитывает СТРОКИ в рубли, а
                  // отвязка возвращает их в валюту — перечитываем и строки, не
                  // только шапку (замечание владельца 24.09.2026).
                  setGen((g) => g + 1);
                })
              }
              className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
            >
              {card.payment_id ? 'изменить' : 'привязать'}
            </button>
          </span>
          <span className="text-text-secondary">Вне каталога</span>
          <span className={Number(card.unmatched_amount) > 0 ? 'text-danger' : 'text-text-muted'}>
            {Number(card.unmatched_amount) > 0
              ? `${money(card.unmatched_amount)} · строк ${card.unmatched_count}`
              : 'нет'}
            {/* ВЫГРУЗКА ЭТИХ СТРОК — ЗДЕСЬ, у загруженного отчёта, а не в импорте
                (просьба владельца 24.09.2026): заводить недостающие позиции в
                номенклатуру — отдельная работа, к загрузке файла она не
                относится. Выгружаются все такие строки. */}
            {card.unmatched_count > 0 && (
              <>
                {' '}
                <button
                  type="button"
                  onClick={downloadUnmatched}
                  disabled={exporting}
                  className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
                >
                  {exporting ? 'выгружаем…' : 'выгрузить в Excel'}
                </button>
              </>
            )}
          </span>

          {/* ВАЛЮТА И КУРС — своей строкой: курс правится (просьба владельца
              24.09.2026). При привязке к поступлению он ставится сам, если
              сошлась сумма в валюте, а поправить его вправе человек — суммы
              отчёта и фактический завод поступления пересчитаются. */}
          {foreign && (
            <>
              <span className="text-text-secondary">Курс к рублю</span>
              <span className="text-text">
                {editing ? (
                  <input
                    value={draft.rate}
                    onChange={(e) => setDraft((d) => ({ ...d, rate: e.target.value }))}
                    placeholder="не задан"
                    className={`${field} w-[140px] tabular-nums`}
                  />
                ) : card.currency_rate ? (
                  rateText(card.currency_rate)
                ) : (
                  <span className="text-danger">не задан — суммы пока в {card.currency}</span>
                )}
                <span className="text-text-muted">
                  {' '}· файл в {card.currency}, итог {formatMoney(card.currency_total).replace('₽', currencySign({ ...card, rate_pending: true }) || card.currency)}
                </span>
              </span>
            </>
          )}
        </div>
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center content-start">
          <span className="text-text-secondary">Период</span>
          <span className="text-text">
            {editing ? (
              <span className="flex items-center gap-2">
                <input
                  type="date"
                  value={draft.from}
                  onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))}
                  className={`${field} tabular-nums`}
                />
                <span className="text-text-muted">—</span>
                <input
                  type="date"
                  value={draft.to}
                  onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
                  className={`${field} tabular-nums`}
                />
              </span>
            ) : (
              card.period_label
            )}
          </span>

          <span className="text-text-secondary">НДС в суммах</span>
          <span className="text-text">
            {card.vat_rate ? `${String(card.vat_rate).replace('.', ',')}%` : 'нет'}
            {/* Отчёт в валюте: суммы уже в рублях, а здесь — по какому курсу
                их перевели. Без этого числа в отчёте нечем объяснить. */}
          </span>

          {/* ЧЕТЫРЕ ПАРАМЕТРА — В ШАПКЕ, а не только столбцами таблицы: у
              большинства площадок они одни на весь отчёт, и повторять их в
              каждой из полумиллиона строк незачем. */}
          {ATTRS.map((a) => (
            <Wrap key={a.name} label={a.label}>
              {editing && !perRow[a.name] ? (
                <ComboCell
                  value={draft[a.name] ?? ''}
                  options={attrOptions[a.name] ?? []}
                  onChange={(v) => setDraft((d) => ({ ...d, [a.name]: v }))}
                  placeholder="—"
                  arrowLabel={`Показать значения: ${a.label}`}
                  inputClassName={`${field} w-full pr-6`}
                />
              ) : perRow[a.name] ? (
                /* ПАРАМЕТР ИЗ КОЛОНКИ ФАЙЛА НЕ ПРАВИТСЯ (просьба владельца
                   24.09.2026): у него своё значение в каждой строке, и одно
                   поле на весь отчёт их не заменит — а заменило бы, так
                   затёрло бы данные площадки. Значения видны в таблице ниже,
                   своим столбцом. */
                <span
                  className="text-text-secondary"
                  data-hint="Берётся из колонки файла — у каждой строки своё значение, смотрите столбец в таблице"
                >
                  из колонки файла
                </span>
              ) : (
                <span className="text-text">{card[a.name] || '—'}</span>
              )}
            </Wrap>
          ))}
        </div>
      </div>

      {error && <div className="text-[13px] text-danger mb-3">{error}</div>}
      {!tableShown && !error && <div className="text-[13px] text-text-muted">Загрузка…</div>}

      {tableShown && (
        <div
          ref={scroller}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          className="border border-border rounded-card overflow-auto flex-1 min-h-0"
        >
          <table className="w-full min-w-[1400px] table-fixed border-collapse">
            <colgroup>
              {widths.map((w, i) => (
                <col key={i} style={{ width: w }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {multi && <th className={th}>Файл</th>}
                <th className={th}>Артикул</th>
                <th className={th}>Код/ISRC/UPC</th>
                <th className={th}>Товар</th>
                <th className={th}>Исполнитель</th>
                <th className={th}>Тип контента</th>
                <th className={th}>Тип использования</th>
                <th className={th}>Вид использования</th>
                <th className={th}>Территория</th>
                {/* Заголовки чисел — ПО ПРАВОМУ КРАЮ, как сами числа: иначе
                    заголовок стоит над началом колонки, а число у её конца,
                    и столбцы кажутся сдвинутыми (замечание владельца). */}
                <th className={`${th} text-right`}>Кол-во</th>
                <th className={`${th} text-right`}>Сумма</th>
                <th className={`${th} text-right`}>Сумма авт.</th>
                <th className={`${th} text-right`}>Сумма смж.</th>
              </tr>
            </thead>
            <tbody>
              {topPad > 0 && <Spacer height={topPad} span={widths.length} />}
              {Array.from({ length: last - first }, (_, k) => first + k).map((i) => {
                const r = blocks.current.get(Math.floor(i / BLOCK))?.[i % BLOCK];
                if (!r) {
                  // Кусок ещё едет — место под строку держим, чтобы
                  // прокрутка не прыгала, когда он приедет.
                  return (
                    <tr key={`wait-${i}`} style={{ height: ROW_H }}>
                      <td colSpan={widths.length} className={`${td} text-text-muted`}>
                        …
                      </td>
                    </tr>
                  );
                }
                return (
                  <tr
                    key={r.row}
                    style={{ height: ROW_H }}
                    /* Строку, которой нет в номенклатуре, подсвечиваем: её
                       деньги ушли в «Вне каталога», и это видно сразу. */
                    className={r.matched ? undefined : 'bg-danger-soft'}
                  >
                  {multi && (
                    <td className={`${td} text-text-secondary`} data-hint={fileOf(r.row)?.name}>
                      {fileOf(r.row) ? fileOf(r.row).index + 1 : '—'}
                    </td>
                  )}
                  <td className={`${td} font-mono`}>{r.sku || '—'}</td>
                  <td className={`${td} font-mono text-text-secondary`} data-hint={r.code}>
                    {r.code || '—'}
                  </td>
                  <td className={td} data-hint={r.title}>
                    {r.title || '—'}
                  </td>
                  <td className={`${td} text-text-secondary`} data-hint={r.artist}>
                    {r.artist || '—'}
                  </td>
                  <td className={`${td} text-text-secondary`}>{r.content_type || '—'}</td>
                  <td className={`${td} text-text-secondary`}>{r.usage_type || '—'}</td>
                  <td className={`${td} text-text-secondary`}>{r.usage_kind || '—'}</td>
                  <td className={`${td} text-text-secondary`}>{r.territory || '—'}</td>
                  <td className={`${td} tabular-nums text-right`}>{count(r.quantity)}</td>
                  <td className={`${td} tabular-nums text-right`}>{r.total}</td>
                  <td className={`${td} tabular-nums text-right`}>{r.amount_author}</td>
                  <td className={`${td} tabular-nums text-right`}>{r.amount_related}</td>
                  </tr>
                );
              })}
              {bottomPad > 0 && <Spacer height={bottomPad} span={widths.length} />}
            </tbody>
          </table>
        </div>
      )}

    </Modal>
  );
}

// Ширины колонок — по порядку заголовков. Заданы, а не посчитаны по
// содержимому: иначе они менялись бы с каждым приехавшим куском строк.
const COLUMN_WIDTHS = [96, 150, '22%', '14%', 110, 130, 130, 96, 90, 110, 110, 110];

/** Пустая строка-подпорка: держит высоту строк, которых сейчас нет в документе. */
function Spacer({ height, span }) {
  return (
    <tr aria-hidden style={{ height }}>
      <td colSpan={span} className="p-0 border-0" />
    </tr>
  );
}

/** Подпись и значение одной строкой сетки — чтобы не повторять разметку. */
function Wrap({ label, children }) {
  return (
    <>
      <span className="text-text-secondary">{label}</span>
      <span>{children}</span>
    </>
  );
}
