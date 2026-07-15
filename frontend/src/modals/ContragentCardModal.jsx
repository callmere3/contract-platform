import { Modal } from '../components/ui/Modal';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border last:border-b-0">
      <span className="text-[13px] text-text-secondary">{label}</span>
      <span className="text-sm text-text font-medium">{value || '—'}</span>
    </div>
  );
}

export function ContragentCardModal({ contragent, level = 0, onOpenDocForm }) {
  const { closeModal, openModal } = useModal();

  return (
    <Modal
      title={contragent?.name ?? 'Контрагент'}
      onClose={closeModal}
      level={level}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Закрыть
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() =>
              openModal('contragentDocs', { contragent, level: level + 1, onOpenDocForm })
            }
          >
            Документы
          </Button>
        </>
      }
    >
      <div className="flex justify-end mb-3">
        <Badge variant="accent">{contragent?.code ?? '—'}</Badge>
      </div>
      <Row label="Псевдоним" value={contragent?.alias} />
      <Row label="ИНН" value={contragent?.inn} />
      <Row label="Номер договора" value={contragent?.contractNumber} />
    </Modal>
  );
}
