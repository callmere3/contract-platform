import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * Пояснение к кубку месяца. Открывается нажатием на сам значок — и в шапке
 * (свой кубок), и во вкладке «Пользователи» (чужой).
 *
 * Количество документов здесь НЕ показывается — сознательно, по решению
 * владельца: значок отмечает победителя, а не ведёт счёт на табло. Число
 * приходит с сервера (`champion.documents`) и остаётся доступным для
 * отладки, но в интерфейс его выводить не нужно — если соберётесь
 * «дополнить» окно счётчиком, это оно и есть.
 */
export function ChampionModal({ champion, name, isMe, level, isTop }) {
  const { closeModal } = useModal();
  // Родительный падеж — «чемпион августа 2026», а не «чемпион август 2026».
  // Форму даёт сервер (period_of): склонять месяцы на фронте значило бы
  // держать второй список названий, который однажды разойдётся с первым.
  const period = champion?.period_of;

  return (
    <Modal
      title="Кубок месяца"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={420}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      <div className="flex flex-col items-center text-center gap-4 py-2">
        <span role="img" aria-label="Кубок" className="text-[72px] leading-none">
          🏆
        </span>

        <div className="text-[17px] font-semibold text-text">
          {isMe ? 'Вы — чемпион' : `${name} — чемпион`}
          {period ? ` ${period}` : ''}
        </div>

        <p className="text-[13.5px] text-text-secondary leading-relaxed m-0 max-w-[46ch]">
          Кубок получает тот, кто за прошедший месяц сформировал больше всех документов.
          Значок обновляется первого числа каждого месяца.
        </p>
      </div>
    </Modal>
  );
}
