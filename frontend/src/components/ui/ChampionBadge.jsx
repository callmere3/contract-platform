import { useModal } from '../../modals/ModalProvider';

/**
 * Кубок месяца рядом с именем — у того, кто за ПРОШЛЫЙ календарный месяц
 * сделал больше всех уникальных документов.
 *
 * Данные приходят готовыми с сервера (`champion` в /auth/me и /users):
 * фронт ничего не считает и не знает правил — иначе шапка и вкладка
 * «Пользователи» однажды разошлись бы в том, кто чемпион. Пусто — значка
 * нет (не чемпион, либо за прошлый месяц вообще ничего не сгенерировано).
 *
 * Нажатие открывает окно с пояснением (ChampionModal); при наведении —
 * короткая подсказка. Ни там, ни там НЕ показывается число документов —
 * так решил владелец: значок отмечает победителя, а не ведёт счёт.
 *
 * Почему emoji, а не иконка: в проекте нет набора иконок, а тащить его ради
 * одного кубка избыточно. Размер задан явно — иначе emoji в строке имени
 * выглядит крупнее текста и сбивает базовую линию.
 */
export function ChampionBadge({ champion, name, isMe = false, className = '' }) {
  const { openModal } = useModal();
  if (!champion) return null;

  return (
    <button
      type="button"
      onClick={() => openModal('champion', { champion, name, isMe })}
      title={`Кубок месяца: чемпион ${champion.period_of}`}
      aria-label={`Кубок месяца: чемпион ${champion.period_of}. Открыть пояснение`}
      className={`inline-flex items-center text-[15px] leading-none flex-shrink-0 bg-transparent border-none p-0 cursor-pointer ${className}`}
    >
      🏆
    </button>
  );
}
