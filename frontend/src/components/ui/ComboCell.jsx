import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Комбобокс: свободный ввод плюс видимая стрелка ▾ со списком подсказок.
 *
 * Заменяет нативный `<datalist>`, у которого нет видимого индикатора, список
 * открывается через раз и выглядит он системным окном, а не частью экрана
 * (жалоба владельца 18.09.2026 — «подсказки браузерные, это некрасиво»).
 * Можно и выбрать из списка, и вписать что угодно своё.
 *
 * ОДИН КОМПОНЕНТ НА ДВА МЕСТА: колонка «Исполнитель» в таблицах формы
 * генерации (там он и родился — отсюда имя) и параметры отчёта площадки.
 * Второй дропдаун со своим поведением разошёлся бы с этим при первой же
 * правке. Внешний вид задаётся `inputClassName`: в таблице поле без рамки и
 * фона, в форме — обычное поле ввода.
 *
 * Дропдаун рендерится в портал (position: fixed по координатам инпута):
 * таблица обёрнута в overflow-hidden ради скруглённых углов, и обычный
 * absolute-дропдаун обрезался бы её краем.
 */
const CELL_INPUT =
  'w-full bg-transparent border-none outline-none text-[13px] text-text font-sans pr-5';

export function ComboCell({
  value,
  options = [],
  onChange,
  inputClassName = CELL_INPUT,
  placeholder,
  arrowLabel = 'Показать подсказки',
}) {
  const [open, setOpen] = useState(false);
  // filtering=true — список сузили по введённому тексту; false — раскрыли
  // стрелкой (показываем ВСЕ подсказки, чтобы можно было просто просмотреть).
  const [filtering, setFiltering] = useState(false);
  const [rect, setRect] = useState(null);
  const wrapRef = useRef(null);
  const inputRef = useRef(null);
  const dropdownRef = useRef(null);

  const shown = !open
    ? []
    : filtering
      ? options.filter((o) => o.toLowerCase().includes((value ?? '').toLowerCase()))
      : options;

  function openWith(mode) {
    if (inputRef.current) {
      const r = inputRef.current.getBoundingClientRect();
      setRect({ left: r.left, top: r.bottom, width: r.width });
    }
    setFiltering(mode === 'type');
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDown = (e) => {
      const t = e.target;
      if (wrapRef.current?.contains(t) || dropdownRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    // при скролле/ресайзе fixed-координаты устареют — проще закрыть
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="relative flex items-center">
      <input
        ref={inputRef}
        value={value ?? ''}
        onChange={(e) => {
          onChange(e.target.value);
          if (options.length) openWith('type');
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false);
          if (e.key === 'ArrowDown' && !open && options.length) openWith('all');
        }}
        placeholder={placeholder}
        className={inputClassName}
      />
      {options.length > 0 && (
        <button
          type="button"
          tabIndex={-1}
          aria-label={arrowLabel}
          onMouseDown={(e) => e.preventDefault()} // не забирать фокус у инпута
          onClick={() => (open ? setOpen(false) : openWith('all'))}
          className="absolute right-1.5 text-text-muted hover:text-text text-[9px] leading-none px-1 py-1 cursor-pointer bg-transparent border-0"
        >
          ▼
        </button>
      )}
      {open &&
        rect &&
        shown.length > 0 &&
        createPortal(
          <div
            ref={dropdownRef}
            style={{ position: 'fixed', left: rect.left, top: rect.top, width: Math.max(rect.width, 140) }}
            className="z-50 mt-1 bg-surface border border-border rounded-input shadow-[0_8px_24px_rgba(0,0,0,0.18)] max-h-52 overflow-y-auto py-1"
          >
            {shown.map((o) => (
              <div
                key={o}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(o);
                  setOpen(false);
                }}
                className="px-3 py-1.5 text-[13px] text-text hover:bg-surface-hover cursor-pointer truncate"
              >
                {o}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
