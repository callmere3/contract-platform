import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * Простое «точно?» — вместо браузерного `confirm`, который выглядит системным
 * окном и живёт вне общих правил (Escape, кнопка «назад», затемнение).
 *
 * ОБЩИЙ, а не свой на каждый случай: у окна, где всё содержимое — одна фраза,
 * различаться нечему. Там, где решение принимают, глядя на сам объект (отчёт
 * площадки: период, файл, суммы), по-прежнему своё окно — оно показывает то,
 * по чему решают.
 *
 * Действие выполняет ВЫЗЫВАЮЩИЙ (`onConfirm`), а окно лишь держит «сейчас
 * выполняем» и текст ошибки: удалять умеет страница, а не диалог.
 */
export function ConfirmModal({
  title = 'Подтвердите действие',
  message,
  confirmLabel = 'Удалить',
  onConfirm,
  level,
  isTop,
}) {
  const { closeModal } = useModal();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run() {
    setBusy(true);
    setError('');
    try {
      await onConfirm?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title={title}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={440}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal} disabled={busy}>
            Отмена
          </Button>
          <Button variant="accent" size="sm" onClick={run} disabled={busy}>
            {busy ? 'Выполняем…' : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-[13px] text-text leading-relaxed">
        {message}
        {error && <div className="text-danger mt-3">{error}</div>}
      </div>
    </Modal>
  );
}
