import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

const MISSING_PREFIX = 'Не заполнены обязательные поля: ';

/**
 * Универсальное окно ошибки/сообщения — заметное, во весь экран (оверлей с
 * затемнением), с понятным текстом и кнопкой «Закрыть». Открывается через
 * openModal('alert', { title, message }) из любого места (генерация, создание
 * и правка контрагента и т.д.) — вместо мелкой подписи внизу формы.
 *
 * Может встать ПОВЕРХ другой модалки (правка контрагента): стек модалок это
 * умеет (level/z-index), закрытие снимает только ошибку и возвращает к форме.
 *
 * Особый случай — «Не заполнены обязательные поля: A, B»: разбираем на список,
 * чтобы оператор видел аккуратный перечень, а не строку через запятую.
 */
export function AlertModal({ title = 'Что-то пошло не так', message, level, isTop }) {
  const { closeModal } = useModal();
  const text = typeof message === 'string' ? message : String(message ?? '');
  const isMissing = text.startsWith(MISSING_PREFIX);
  const fields = isMissing
    ? text.slice(MISSING_PREFIX.length).split(',').map((s) => s.trim()).filter(Boolean)
    : null;

  return (
    <Modal
      title={title}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={460}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      {isMissing ? (
        <div className="text-sm text-text leading-relaxed">
          <div className="mb-3">Чтобы продолжить, заполните обязательные поля:</div>
          <ul className="list-disc pl-5 space-y-1.5 marker:text-accent">
            {fields.map((f) => (
              <li key={f} className="text-text">
                {f}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="text-sm text-text leading-relaxed whitespace-pre-line">{text}</div>
      )}
    </Modal>
  );
}
