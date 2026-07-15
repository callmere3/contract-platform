import { Modal } from '../components/ui/Modal';
import { useModal } from './ModalProvider';

// Моки на этапе scaffold — в реальной версии список совместимых шаблонов
// приходит из GET /contragents/{id}/templates.
const MOCK_TEMPLATES = [
  { id: 1, code: 'ПРИЛ_СГ_РОЯЛТИ', name: 'Приложение — Роялти' },
  { id: 2, code: 'АКТ_СГ_РОЯЛТИ', name: 'Акт — Роялти' },
];

export function ContragentDocsModal({ contragent, level = 0, onOpenDocForm }) {
  const { closeModal, closeAllModals } = useModal();

  const handleSelect = (template) => {
    onOpenDocForm?.(template, contragent);
    closeAllModals();
  };

  return (
    <Modal title="Документы контрагента" onClose={closeModal} level={level}>
      <div className="text-[13px] text-text-secondary mb-4">
        Совместимые шаблоны для «{contragent?.name}»
      </div>
      <div className="border border-border rounded-input overflow-hidden">
        {MOCK_TEMPLATES.map((tpl) => (
          <div
            key={tpl.id}
            onClick={() => handleSelect(tpl)}
            className="flex items-center justify-between px-4 py-3 border-b border-border last:border-b-0 cursor-pointer hover:bg-surface-hover"
          >
            <div>
              <div className="text-sm font-semibold text-text">{tpl.name}</div>
              <div className="text-[11px] text-text-muted mt-0.5 tracking-[0.03em]">
                {tpl.code}
              </div>
            </div>
            <span className="text-text-secondary text-xs">↗</span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
