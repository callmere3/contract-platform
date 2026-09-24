import { useCallback, useEffect, useState } from 'react';
import { Modal, ModalAction } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { ComboCell } from '../components/ui/ComboCell';
import { PencilIcon, TrashIcon } from '../components/ui/icons';
import { useModal } from './ModalProvider';
import { reportRows, updateReport } from '../api/partnerReports';
import { formatMoney } from '../api/finance';

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
const PAGE = 200;

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
  const [rows, setRows] = useState([]);
  const [perRow, setPerRow] = useState({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await reportRows(card.id, { page, pageSize: PAGE });
      setRows(data.rows ?? []);
      setTotal(data.total ?? 0);
      setPerRow(data.per_row_attributes ?? {});
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [card.id, page]);

  useEffect(() => {
    load();
  }, [load]);

  function startEdit() {
    setDraft({
      from: card.period?.from ?? '',
      to: card.period?.to ?? '',
      ...Object.fromEntries(ATTRS.map((a) => [a.name, card[a.name] ?? ''])),
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
      });
      setCard(fresh);
      setEditing(false);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-2 py-1.5 whitespace-nowrap border-b border-border bg-surface sticky top-0';
  const td = 'px-2 py-1 border-t border-border-soft text-[12.5px] whitespace-nowrap';
  const field =
    'bg-input-bg border border-border rounded-input px-2 py-1 text-[12.5px] text-text outline-none font-sans';
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const count = (v) => Number(v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

  return (
    <Modal
      title={`Отчёт: ${card.partner} · ${card.period_label}`}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={1320}
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
              <b>{count(card.total_quantity)}</b> · Сумма: <b>{formatMoney(card.total)}</b>
              <span className="text-text-muted">
                {' '}
                (авторские {formatMoney(card.total_author)}, смежные{' '}
                {formatMoney(card.total_related)})
              </span>
            </span>
            <Button variant="secondary" size="sm" onClick={closeModal}>
              Закрыть
            </Button>
          </>
        )
      }
    >
      {/* ШАПКА ДОКУМЕНТА — только наши поля. Роль «Основания» из Dista здесь
          играет имя файла: по нему отчёт и находят среди присланного. */}
      <div className="grid grid-cols-[auto_1fr_auto_1fr] gap-x-4 gap-y-2 items-center text-[12.5px] mb-4">
        <span className="text-text-secondary">Площадка</span>
        <span className="text-text font-semibold">{card.partner}</span>
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

        <span className="text-text-secondary">Файл</span>
        <span className="text-text truncate" data-hint={card.file_name}>
          {card.file_name}
          {card.sheet ? ` · лист «${card.sheet}»` : ''}
        </span>
        <span className="text-text-secondary">НДС в суммах</span>
        <span className="text-text">
          {card.vat_rate ? `${String(card.vat_rate).replace('.', ',')}%` : 'нет'}
        </span>

        <span className="text-text-secondary">Поступление</span>
        <span className="text-text">
          {card.payment_label ?? <span className="text-text-muted">не привязано</span>}{' '}
          {/* В ПРАВКЕ ПОКАЗЫВАЕМ ВЕСЬ СПИСОК: сюда и пришли затем, чтобы
              поменять строку, и прятать остальные значило бы заставить
              сперва отвязать. Вне правки привязка открывается обычным
              окном — с одной уже выбранной строкой. */}
          <button
            type="button"
            onClick={() =>
              // Свежая карточка приходит обратно: иначе в шапке так и висело
              // бы прежнее поступление, пока окно не откроют заново.
              onLink?.(card, editing, (fresh) => fresh && setCard(fresh))
            }
            className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
          >
            {card.payment_id ? 'изменить' : 'привязать'}
          </button>
        </span>
        <span className="text-text-secondary">Вне каталога</span>
        <span className={Number(card.unmatched_amount) > 0 ? 'text-danger' : 'text-text-muted'}>
          {Number(card.unmatched_amount) > 0
            ? `${formatMoney(card.unmatched_amount)} · строк ${card.unmatched_count}`
            : 'нет'}
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

      {error && <div className="text-[13px] text-danger mb-3">{error}</div>}
      {loading && <div className="text-[13px] text-text-muted">Загрузка…</div>}

      {!loading && (
        <div className="border border-border rounded-card overflow-auto max-h-[46vh]">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className={th}>Артикул</th>
                <th className={th}>Код/ISRC/UPC</th>
                <th className={th}>Товар</th>
                <th className={th}>Исполнитель</th>
                <th className={th}>Тип контента</th>
                <th className={th}>Тип использования</th>
                <th className={th}>Вид использования</th>
                <th className={th}>Территория</th>
                <th className={th}>Кол-во</th>
                <th className={th}>Сумма</th>
                <th className={th}>Сумма авт.</th>
                <th className={th}>Сумма смж.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.row}
                  /* Строку, которой нет в номенклатуре, подсвечиваем: её
                     деньги ушли в «Вне каталога», и это видно сразу. */
                  className={r.matched ? undefined : 'bg-danger-soft'}
                >
                  <td className={`${td} font-mono`}>{r.sku || '—'}</td>
                  <td className={`${td} font-mono text-text-secondary`}>{r.code || '—'}</td>
                  <td className={`${td} max-w-[280px] truncate`} data-hint={r.title}>
                    {r.title || '—'}
                  </td>
                  <td className={`${td} max-w-[200px] truncate text-text-secondary`}>
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
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* СТРАНИЦЫ, А НЕ ВСЁ РАЗОМ: в отчёте Believe полмиллиона строк, и
          браузер на них ляжет. По двести — столько же, сколько в
          предпросмотре импорта номенклатуры. */}
      {pages > 1 && (
        <div className="flex items-center gap-3 mt-3 text-[12.5px] text-text-secondary">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((v) => v - 1)}
          >
            Назад
          </Button>
          <span className="tabular-nums">
            {page} из {pages}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= pages || loading}
            onClick={() => setPage((v) => v + 1)}
          >
            Вперёд
          </Button>
        </div>
      )}
    </Modal>
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
