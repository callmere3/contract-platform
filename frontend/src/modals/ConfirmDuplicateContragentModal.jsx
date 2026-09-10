import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * Подтверждение создания карточки, титл которой уже есть в базе.
 *
 * Открывается формой «Новый контрагент» в ответ на 409 duplicate_title от
 * POST /contragents (см. create_contragent): сервер сравнивает ВЫЧИСЛЕННЫЙ
 * титл новой карточки с титлами существующих и по умолчанию не даёт создать
 * вторую такую же. Причина появления окна — инцидент 09.09.2026: прежняя
 * проверка жила только на фронте, сверяла ФИО и не видела импортных карточек
 * (у них ФИО пустое, есть только сокращённый титл), поэтому дубль создался
 * молча.
 *
 * Почему это вопрос, а не запрет: титл — фамилия + инициалы + тип, и «Иванов
 * И. И. (СГ)» законно бывают двумя РАЗНЫМИ людьми; вторая карточка на того же
 * человека под аванс/роялти тоже норма. Подтверждение уходит вторым запросом
 * с confirm_duplicate=true и попадает в audit_log — видно, с чем именно
 * согласился оператор.
 *
 * Само создание выполняет вызывающая сторона (NewContragentModal) — модалка
 * только показывает найденное и предлагает выбор.
 */
export function ConfirmDuplicateContragentModal({
  message,
  duplicates = [],
  onConfirm,
  level,
  isTop,
}) {
  const { closeModal } = useModal();

  return (
    <Modal
      title="Такая карточка уже есть"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={460}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              closeModal();
              onConfirm?.();
            }}
          >
            Всё равно создать
          </Button>
        </>
      }
    >
      <div className="text-sm text-text leading-relaxed">
        <div className="mb-3">{message || 'Карточка с таким титлом уже есть в базе.'}</div>
        {duplicates.length > 0 && (
          <ul className="list-disc pl-5 space-y-1.5 marker:text-accent">
            {duplicates.map((d) => (
              <li key={d.id} className="text-text">
                {d.title}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 text-[13px] text-text-secondary">
          Если это тот же контрагент — нажмите «Отмена» и найдите его в базе через поиск.
        </div>
      </div>
    </Modal>
  );
}
