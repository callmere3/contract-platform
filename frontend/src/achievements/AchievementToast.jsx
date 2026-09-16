import { useEffect, useRef, useState } from 'react';
import { ACHIEVEMENT_EARNED_EVENT } from './tracker';

// Сколько висит одна всплывашка. Пять секунд — успеть прочитать три слова
// и не мешать работе; закрыть можно раньше крестиком.
const SHOW_MS = 5000;

/**
 * Всплывашка «получено достижение» — снизу по центру, поверх всего, кроме
 * модалок.
 *
 * Показывает по одной, очередью: за один документ можно взять сразу два
 * значка (например, «Проба пера» и «Ночная смена»), и две карточки внахлёст
 * читались бы хуже, чем одна за другой.
 *
 * Снизу по центру, а не справа: справа внизу живёт плашка черновика
 * (DraftDock), они бы столкнулись.
 */
export function AchievementToast() {
  const [queue, setQueue] = useState([]);
  const timer = useRef(null);

  useEffect(() => {
    const onEarned = (e) => {
      const items = e.detail?.achievements ?? [];
      if (items.length) setQueue((q) => [...q, ...items]);
    };
    window.addEventListener(ACHIEVEMENT_EARNED_EVENT, onEarned);
    return () => window.removeEventListener(ACHIEVEMENT_EARNED_EVENT, onEarned);
  }, []);

  // Таймер перезапускается на каждой новой карточке очереди.
  useEffect(() => {
    if (queue.length === 0) return undefined;
    timer.current = setTimeout(() => setQueue((q) => q.slice(1)), SHOW_MS);
    return () => clearTimeout(timer.current);
  }, [queue]);

  if (queue.length === 0) return null;
  const current = queue[0];

  return (
    <div
      role="status"
      // Центрируем полями (left-0 right-0 + mx-auto), а не -translate-x-1/2:
      // трансформу занимает анимация выезда, и два механизма на одном
      // свойстве — верный способ однажды разъехаться.
      className="achievement-toast fixed bottom-6 left-0 right-0 mx-auto w-fit z-40 flex items-center gap-3.5 bg-surface border border-accent rounded-card shadow-card pl-4 pr-3 py-3 max-w-[360px]"
    >
      <span className="text-[34px] leading-none flex-shrink-0" aria-hidden="true">
        {current.icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[11px] font-semibold tracking-[0.06em] uppercase text-accent">
          Новое достижение
        </span>
        <span className="block text-[14px] font-semibold text-text truncate">{current.title}</span>
        <span className="block text-[11.5px] text-text-muted truncate">{current.hint}</span>
      </span>
      <button
        type="button"
        onClick={() => setQueue((q) => q.slice(1))}
        aria-label="Скрыть"
        className="self-start w-6 h-6 flex items-center justify-center rounded-full bg-transparent border-none cursor-pointer text-[13px] text-text-muted hover:text-text font-sans"
      >
        ✕
      </button>
      {queue.length > 1 && (
        <span className="absolute -top-2 -right-2 inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-full bg-accent text-white text-[11px] font-semibold leading-none">
          +{queue.length - 1}
        </span>
      )}
    </div>
  );
}
