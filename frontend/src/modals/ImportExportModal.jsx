import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canExport, canImport } from '../auth/permissions';
import { exportContragents, importContragents } from '../api/contragents';

/**
 * Импорт/экспорт контрагентов.
 *
 * Права разные у двух половин модалки (см. app/roles.py):
 *   экспорт — admin + director + top_manager (CAN_EXPORT_CONTRAGENTS)
 *   импорт  — только admin (CAN_IMPORT), "загрузку данных внутрь делает
 *             только Admin"
 * Поэтому у director/top_manager модалка открывается, но блок импорта в
 * ней скрыт — ровно как в боевом index.html (applyRolePermissions).
 * У manager кнопки открытия этой модалки нет вовсе.
 */
export function ImportExportModal({ level, isTop }) {
  const { closeModal } = useModal();
  const { role } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [report, setReport] = useState(null);

  async function handleExport() {
    setBusy(true);
    setError('');
    try {
      const blob = await exportContragents();
      // Скачивание через временную ссылку: сервер отдаёт файл потоком,
      // просто перейти по URL нельзя — запрос требует Authorization.
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'contragents_export.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(file) {
    if (!file) return;
    setBusy(true);
    setError('');
    setReport(null);
    try {
      setReport(await importContragents(file));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Импорт / экспорт" onClose={closeModal} level={level} isTop={isTop} width={520}>
      {canExport(role) && (
        <div className={canImport(role) ? 'mb-6 pb-6 border-b border-border' : ''}>
          <div className="text-sm font-semibold text-text mb-1.5">Экспорт</div>
          <div className="text-[13px] text-text-secondary mb-3">
            Выгрузить всю базу контрагентов в Excel.
          </div>
          <Button variant="secondary" size="sm" onClick={handleExport} disabled={busy}>
            {busy ? 'Готовим файл…' : 'Скачать .xlsx'}
          </Button>
        </div>
      )}

      {canImport(role) && (
        <div>
          <div className="text-sm font-semibold text-text mb-1.5">Импорт</div>
          <div className="text-[13px] text-text-secondary mb-3">
            Загрузить контрагентов из Excel-файла того же формата. Совпадение ищется по титлу:
            существующие карточки обновляются, новые — создаются.
          </div>
          <label className="inline-block">
            <input
              type="file"
              accept=".xlsx"
              disabled={busy}
              onChange={(e) => handleImport(e.target.files?.[0])}
              className="hidden"
            />
            <span className="cursor-pointer inline-block bg-button-primary-bg text-button-primary-text rounded-input px-4 py-2.5 text-[13px] font-semibold">
              {busy ? 'Загружаем…' : 'Выбрать файл…'}
            </span>
          </label>
        </div>
      )}

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}

      {report && (
        <div className="mt-5 pt-5 border-t border-border">
          <div className="text-[13px] text-text mb-2">
            Создано: {report.created} · Обновлено: {report.updated} · Пропущено: {report.skipped}
          </div>
          {/* details — массив объектов {row, status, title?, reason?, warnings[]}
              (см. import_contragents на бэкенде). Показываем только строки с
              проблемами: успешные без предупреждений не нужны — их количество
              уже видно в сводке выше, а список на сотни строк только мешает. */}
          {report.details?.filter((d) => d.reason || d.warnings?.length).length > 0 && (
            <div className="max-h-40 overflow-y-auto text-[11px] text-text-muted leading-relaxed">
              {report.details
                .filter((d) => d.reason || d.warnings?.length)
                .map((d, i) => (
                  <div key={i} className="mb-1">
                    <span className="text-text-secondary">Строка {d.row}</span> — {d.status}
                    {d.title ? ` · ${d.title}` : ''}
                    {d.reason ? `: ${d.reason}` : ''}
                    {d.warnings?.length ? `: ${d.warnings.join('; ')}` : ''}
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
