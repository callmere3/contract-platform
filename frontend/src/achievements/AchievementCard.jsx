/**
 * Плитка достижения: только значок и название. Условие — подсказкой при
 * наведении, всё остальное (счётчик повторов, месяцы, прогресс) — в окне
 * по нажатию (AchievementModal). Так раздел читается как ряд наград, а не
 * как таблица цифр.
 *
 * Полученное — в цвете и со сплошной рамкой, ещё нет — блёклое и
 * пунктиром: разница видна сразу, без единой цифры на плитке.
 *
 * Общая для своего профиля и чужого (ProfileModal / UserProfileModal):
 * чужой рисуется теми же плитками, только без анимации — проявление из
 * серого в цветное сообщает «ты только что это получил», а на чужой
 * карточке сообщать нечего.
 */
export function AchievementCard({ achievement, onOpen, isFresh = false, revealIndex = 0 }) {
  const { icon, title, hint, earned } = achievement;

  return (
    <button
      type="button"
      onClick={onOpen}
      title={hint}
      className={`flex flex-col items-center text-center gap-1 px-1.5 py-2.5 rounded-input border cursor-pointer min-h-[80px] justify-center ${
        earned
          ? 'border-border bg-surface'
          : 'border-dashed border-border bg-transparent'
      } ${isFresh ? 'achievement-reveal-card' : ''}`}
      style={isFresh ? { animationDelay: `${revealIndex * 320}ms` } : undefined}
    >
      <span
        role="img"
        aria-hidden="true"
        className={`text-[24px] leading-none ${earned ? '' : 'grayscale opacity-40'} ${
          isFresh ? 'achievement-reveal' : ''
        }`}
        // Несколько новых значков зажигаются по очереди, а не разом.
        style={isFresh ? { animationDelay: `${revealIndex * 320}ms` } : undefined}
      >
        {icon}
      </span>
      <span
        className={`text-[10.5px] font-semibold leading-[1.2] ${
          earned ? 'text-text' : 'text-text-muted'
        }`}
      >
        {title}
      </span>
    </button>
  );
}
