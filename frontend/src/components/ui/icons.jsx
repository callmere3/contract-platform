/**
 * Значки действий — рисованные, а не эмодзи.
 *
 * Эмодзи 🗑 и ✎ в шапке модалки читались плохо, и увеличение размера не
 * помогло (жалоба владельца 17.09.2026): эмодзи рисует шрифт системы, он
 * приходит со своим цветом и своими пропорциями, живёт в своём поле и не
 * слушается ни `font-size` толком, ни `color` вовсе — на Windows мусорка
 * выходила мелким красным пятном.
 *
 * SVG слушается: `currentColor` берёт цвет кнопки (в том числе красный у
 * удаления и приглушённый у выключенной), размер задаётся явно, а толщина
 * линии — общая для всех значков, поэтому в ряду они выглядят одним
 * набором, а не собранием из разных мест.
 */
const STROKE = 1.8;

function Svg({ children, size = 18 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Корзина: крышка с ручкой, корпус и две полоски внутри. */
export function TrashIcon({ size }) {
  return (
    <Svg size={size}>
      <path d="M4 7h16" />
      <path d="M10 4h4" />
      <path d="M6 7l1 12.5a1.5 1.5 0 0 0 1.5 1.5h7a1.5 1.5 0 0 0 1.5-1.5L18 7" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </Svg>
  );
}

/** Карандаш: правка. */
export function PencilIcon({ size }) {
  return (
    <Svg size={size}>
      <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z" />
      <path d="M14.5 6.5l3 3" />
    </Svg>
  );
}

/** Крестик закрытия — в том же наборе, чтобы ряд выглядел единым. */
export function CloseIcon({ size }) {
  return (
    <Svg size={size}>
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </Svg>
  );
}
