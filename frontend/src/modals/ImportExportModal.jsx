import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

export function ImportExportModal({ onExport, onImport }) {
  const { closeModal } = useModal();

  return (
    <Modal title="Импорт / экспорт" onClose={closeModal}>
      <div className="mb-6">
        <div className="text-sm font-semibold text-text mb-1.5">Экспорт</div>
        <div className="text-[13px] text-text-secondary mb-3">
          Выгрузить всю базу контрагентов в Excel.
        </div>
        <Button variant="secondary" size="sm" onClick={onExport}>
          Скачать .xlsx
        </Button>
      </div>

      <div>
        <div className="text-sm font-semibold text-text mb-1.5">Импорт</div>
        <div className="text-[13px] text-text-secondary mb-3">
          Загрузить контрагентов из Excel-файла того же формата.
        </div>
        <label className="inline-block">
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => onImport?.(e.target.files?.[0])}
            className="hidden"
          />
          <span className="cursor-pointer inline-block bg-button-primary-bg text-button-primary-text rounded-input px-4 py-2.5 text-[13px] font-semibold">
            Выбрать файл…
          </span>
        </label>
      </div>
    </Modal>
  );
}
