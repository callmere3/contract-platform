import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Ячейка-комбобокс для колонки "Исполнитель" в таблицах формы генерации.
 *
 * Свободный ввод + видимая стрелка ▾, раскрывающая список подсказок
 * (псевдонимы контрагента). Можно и выбрать из списка, и вписать любое
 * значение (напр. приглашённого артиста). Заменяет нативный <datalist>,
 * у которого нет видимого индикатора и который открывается только по
 * двойному клику.
 *
 * Дропдаун рендерится в портал (position: fixed по координатам инпута):
 * таблица обёрнута в overflow-hidden ради скруглённых углов, и обычный
 * absolute-дропдаун обрезался бы её краем.
 */
export function ComboCell({ value, options = [], onChange }) {
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
        className="w-full bg-transparent border-none outline-none text-[13px] text-text font-sans pr-5"
      />
      {options.length > 0 && (
        <button
          type="button"
          tabIndex={-1}
          aria-label="Показать псевдонимы"
          onMouseDown={(e) => e.preventDefault()} // не забирать фокус у инпута
          onClick={() => (open ? setOpen(false) : openWith('all'))}
          className="absolute right-0.5 text-text-muted hover:text-text text-[9px] leading-none px-1 py-1 cursor-pointer"
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
