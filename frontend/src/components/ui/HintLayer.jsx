import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * ПОДСКАЗКИ ВЕЗДЕ — НАШИ, А НЕ БРАУЗЕРНЫЕ (просьба владельца 24.09.2026).
 *
 * Браузерный `title` появляется через секунду, пропадает сам через
 * несколько, рисуется системным шрифтом мимо всей темы и переносит длинный
 * текст как придётся. Заменять его по одному месту мы пробовали трижды и
 * трижды пропускали то одну ветку, то другую — поэтому здесь ОДИН СЛОЙ НА
 * ВСЁ ПРИЛОЖЕНИЕ, а элементу достаточно атрибута.
 *
 *     <button data-hint="Убрать строку">…</button>
 *
 * ПОЧЕМУ АТРИБУТ, А НЕ КОМПОНЕНТ-ОБЁРТКА. Обёртка добавляет в вёрстку лишний
 * `<span>` — а подсказки нужны на ячейках таблицы, кнопках-значках и полях
 * ввода, где лишний элемент ломает то выравнивание, то ширину колонки.
 * Атрибут не меняет ничего и вешается на что угодно, включая `<td>`.
 *
 * ПОЧЕМУ НЕ ОСТАВИТЬ `title`. Убрать системную подсказку, не убрав атрибут,
 * нельзя: браузер покажет её поверх нашей. Поэтому имя другое, а `title`
 * в проекте остаётся только там, где это ПРОП КОМПОНЕНТА (заголовок модалки,
 * шапка вкладки) — их видно по заглавной букве тега.
 *
 * ПОКАЗЫВАЕМ ТОЛЬКО ПО НАВЕДЕНИЮ, не по фокусу: половина мест — поля ввода,
 * и подсказка над строкой, которую в этот момент правят, закрывала бы текст.
 */
export function HintLayer() {
  const [hint, setHint] = useState(null);

  useEffect(() => {
    // Слушаем ДОКУМЕНТ, а не каждый элемент: подсказок в проекте под сотню,
    // и вешать на каждую свой обработчик — лишняя работа на каждый рендер.
    function place(el) {
      const text = el.getAttribute('data-hint');
      if (!text) return setHint(null);
      const r = el.getBoundingClientRect();
      // Над элементом, если сверху есть место, иначе под ним: у верхних
      // строк таблицы места сверху нет.
      const above = r.top > 120;
      setHint({
        text,
        left: Math.min(Math.max(8, r.left), window.innerWidth - 340),
        top: above ? r.top - 8 : r.bottom + 8,
        above,
      });
    }

    const onOver = (e) => {
      const el = e.target?.closest?.('[data-hint]');
      if (el) place(el);
      else setHint(null);
    };
    // Прячем на прокрутке и уходе мыши: подсказка нарисована в портале и
    // за элементом не едет — висеть посреди экрана она не должна.
    const hide = () => setHint(null);

    document.addEventListener('mouseover', onOver);
    document.addEventListener('mouseleave', hide);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    return () => {
      document.removeEventListener('mouseover', onOver);
      document.removeEventListener('mouseleave', hide);
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
    };
  }, []);

  if (!hint) return null;
  return createPortal(
    <div
      role="tooltip"
      style={{
        position: 'fixed',
        left: hint.left,
        top: hint.top,
        transform: hint.above ? 'translateY(-100%)' : undefined,
        maxWidth: 320,
      }}
      className="z-[60] px-2.5 py-2 text-[12.5px] leading-snug text-text bg-surface border border-border rounded-card shadow-[0_8px_24px_rgba(0,0,0,0.18)] pointer-events-none whitespace-pre-line"
    >
      {hint.text}
    </div>,
    document.body,
  );
}
