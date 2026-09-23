import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Подсказка при наведении — НАША, а не браузерная (просьба владельца
 * 23.09.2026).
 *
 * Браузерный `title` появляется через секунду, пропадает сам через несколько
 * секунд, рисуется системным шрифтом мимо всей темы и не умеет переносить
 * длинный текст по-человечески. Там, где подсказка — часть работы (прочитать
 * описание платежа целиком, узнать, сколько должно быть по формуле), это
 * мешает. Решение то же, что с `datalist` в полях: свой компонент вместо
 * системного.
 *
 * РИСУЕТСЯ В ПОРТАЛЕ, как выпадающий список площадки: таблица живёт внутри
 * карточки со скруглёнными углами (`overflow-hidden`), и обычный absolute её
 * краем обрезало бы.
 *
 * ПОКАЗЫВАЕТСЯ ТОЛЬКО ПО НАВЕДЕНИЮ, не по фокусу: половина мест применения —
 * поля ввода, и подсказка, всплывающая над строкой, которую человек в этот
 * момент правит, закрывала бы ему текст.
 */
export function Tooltip({ text, children, className = '' }) {
  const [rect, setRect] = useState(null);
  const box = useRef(null);

  if (!text) return children;

  function show() {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    // Над элементом, если сверху есть место, иначе под ним: у нижних строк
    // таблицы места сверху хватает, у верхних — нет.
    const above = r.top > 120;
    setRect({
      left: Math.min(Math.max(8, r.left), window.innerWidth - 340),
      top: above ? r.top - 8 : r.bottom + 8,
      above,
    });
  }

  return (
    <span
      ref={box}
      className={className}
      onMouseEnter={show}
      onMouseLeave={() => setRect(null)}
    >
      {children}
      {rect &&
        createPortal(
          <div
            role="tooltip"
            style={{
              position: 'fixed',
              left: rect.left,
              top: rect.top,
              transform: rect.above ? 'translateY(-100%)' : undefined,
              maxWidth: 320,
            }}
            className="z-[60] px-2.5 py-2 text-[12.5px] leading-snug text-text bg-surface border border-border rounded-card shadow-[0_8px_24px_rgba(0,0,0,0.18)] pointer-events-none whitespace-pre-line"
          >
            {text}
          </div>,
          document.body,
        )}
    </span>
  );
}
