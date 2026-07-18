import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * Подтверждение выхода из формы генерации с несохранённым (не
 * сформированным) документом. Три исхода:
 *   - Сохранить черновик — оставить и уйти (плашка появится в углу);
 *   - Сбросить — выбросить введённое и уйти;
 *   - Остаться (крестик/Esc/фон) — вернуться к форме.
 *
 * Логику сохранения/сброса и сам переход выполняет вызывающая сторона
 * (DocFormPage) — модалка только предлагает выбор.
 */
export function ConfirmExitDraftModal({ onSave, onDiscard, level, isTop }) {
  const { closeModal } = useModal();

  return (
    <Modal
      title="Выйти из формы?"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={440}
      footer={
        <>
          <Button
            variant="secondary"
            size="sm"
            className="mr-auto"
            onClick={() => {
              closeModal();
              onDiscard?.();
            }}
          >
            Сбросить
          </Button>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Остаться
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              closeModal();
              onSave?.();
            }}
          >
            Сохранить черновик
          </Button>
        </>
      }
    >
      <p className="text-[13px] text-text-secondary leading-relaxed m-0">
        Документ ещё не сформирован. Сохранить его как черновик, чтобы вернуться позже, или сбросить
        введённые данные?
      </p>
    </Modal>
  );
}
