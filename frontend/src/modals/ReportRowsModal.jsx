import { useCallback, useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { reportRows } from '../api/partnerReports';
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
 */
const PAGE = 200;

export function ReportRowsModal({ report, level, isTop, onLink }) {
  const { closeModal } = useModal();
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await reportRows(report.id, { page, pageSize: PAGE });
      setRows(data.rows ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [report.id, page]);

  useEffect(() => {
    load();
  }, [load]);

  const th =
    'text-left font-semibold text-[11px] uppercase tracking-[0.04em] text-text-muted px-2 py-1.5 whitespace-nowrap border-b border-border bg-surface sticky top-0';
  const td = 'px-2 py-1 border-t border-border-soft text-[12.5px] whitespace-nowrap';
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const count = (v) => Number(v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

  return (
    <Modal
      title={`Отчёт: ${report.partner} · ${report.period_label}`}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={1320}
      footer={
        <>
          {/* ИТОГ КАК В DISTA: позиций, количество, сумма. Числа берём из
              самого отчёта, а не складываем показанную страницу: страница
              одна из многих, а итог — по всему файлу. */}
          <span className="text-[12.5px] text-text mr-auto tabular-nums">
            Позиций: <b>{report.rows_count}</b> · Кол-во:{' '}
            <b>{count(report.total_quantity)}</b> · Сумма: <b>{formatMoney(report.total)}</b>
            <span className="text-text-muted">
              {' '}
              (авторские {formatMoney(report.total_author)}, смежные{' '}
              {formatMoney(report.total_related)})
            </span>
          </span>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Закрыть
          </Button>
        </>
      }
    >
      {/* ШАПКА ДОКУМЕНТА — только наши поля. Роль «Основания» из Dista здесь
          играет имя файла: по нему отчёт и находят среди присланного. */}
      <div className="grid grid-cols-[auto_1fr_auto_1fr] gap-x-4 gap-y-1.5 text-[12.5px] mb-4">
        <span className="text-text-secondary">Площадка</span>
        <span className="text-text font-semibold">{report.partner}</span>
        <span className="text-text-secondary">Период</span>
        <span className="text-text">{report.period_label}</span>

        <span className="text-text-secondary">Файл</span>
        <span className="text-text truncate" data-hint={report.file_name}>
          {report.file_name}
          {report.sheet ? ` · лист «${report.sheet}»` : ''}
        </span>
        <span className="text-text-secondary">НДС в суммах</span>
        <span className="text-text">
          {report.vat_rate ? `${String(report.vat_rate).replace('.', ',')}%` : 'нет'}
        </span>

        <span className="text-text-secondary">Поступление</span>
        <span className="text-text">
          {report.payment_label ?? <span className="text-text-muted">не привязано</span>}{' '}
          {/* ПРИВЯЗКА ЖИВЁТ ЗДЕСЬ, раз нажатие на строку теперь открывает
              сам отчёт: это действие над документом, и место ему в его же
              шапке, а не в окне, которое ещё надо найти. */}
          <button
            type="button"
            onClick={() => onLink?.(report)}
            className="text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
          >
            {report.payment_id ? 'изменить' : 'привязать'}
          </button>
        </span>
        <span className="text-text-secondary">Вне каталога</span>
        <span className={Number(report.unmatched_amount) > 0 ? 'text-danger' : 'text-text-muted'}>
          {Number(report.unmatched_amount) > 0
            ? `${formatMoney(report.unmatched_amount)} · строк ${report.unmatched_count}`
            : 'нет'}
        </span>
      </div>

      {loading && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}

      {!loading && !error && (
        <div className="border border-border rounded-card overflow-auto max-h-[56vh]">
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
