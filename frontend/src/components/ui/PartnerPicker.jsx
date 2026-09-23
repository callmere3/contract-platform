import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Выбор площадки ПОИСКОМ, а не списком: их больше сотни, и список, который
 * надо листать до нужной буквы, — ровно та работа, от которой поиск
 * избавляет. Стоит начать печатать — перечень сразу сужается до подходящих.
 *
 * Ищет и по имени, и по коду Dista: у человека со строчкой отчёта в руках
 * чаще именно код. Обычно выбрать можно ТОЛЬКО существующую площадку —
 * значение наружу это её id, а не набранный текст: отчёт привязывается к
 * справочнику, а не к тому, как его назвали в поле.
 *
 * ИСКЛЮЧЕНИЕ — `allowCustom` (таблица поступлений, 23.09.2026). Мелкие
 * партнёры по синхронизации отчётов не присылают, в справочнике площадок их
 * нет и быть не должно, а деньги от них приходят и строку подписать надо.
 * Тогда набранное имя можно оставить как есть — оно уходит через `onCustom`
 * и хранится у поступления отдельным полем. Заводить ради этого площадку
 * нельзя: справочник — это те, по кому мы разбираем отчёты.
 *
 * ОДИН КОМПОНЕНТ НА ДВА ЭКРАНА — загрузка отчёта и таблица поступлений.
 * Второй такой же со своим поведением разошёлся бы с первым при первой же
 * правке.
 *
 * Список рисуется В ПОРТАЛЕ (position: fixed по координатам поля): в таблице
 * поступлений он живёт внутри карточки с overflow-hidden (скруглённые углы),
 * и обычный absolute-дропдаун обрезался бы её краем.
 */
export function PartnerPicker({
  partners,
  value,
  onChange,
  inputClassName,
  placeholder = '— начните вводить —',
  allowEmpty = false,
  allowCustom = false,
  customValue = '',
  onCustom,
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  // Набранное держим и в ref: обработчики закрытия живут в эффекте и видели
  // бы значение на момент подписки, а не то, что человек успел напечатать.
  const typed = useRef('');
  typed.current = query;
  const [rect, setRect] = useState(null);
  const box = useRef(null);
  const input = useRef(null);
  const dropdown = useRef(null);
  const chosen = partners.find((p) => p.id === value) || null;
  // Набранное руками имя показывается так же, как выбранное из справочника:
  // для человека это одно и то же — чей платёж.
  const shown = chosen?.name ?? (allowCustom ? customValue : '') ?? '';

  const found = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? partners.filter(
          (p) =>
            (p.name || '').toLowerCase().includes(q) ||
            (p.dista_id || '').toLowerCase().includes(q),
        )
      : partners;
    return list.slice(0, 50);
  }, [partners, query]);

  function place() {
    if (!input.current) return;
    const r = input.current.getBoundingClientRect();
    setRect({ left: r.left, top: r.bottom, width: Math.max(r.width, 220) });
  }

  // Нажатие мимо закрывает список и возвращает в поле имя выбранного: поле
  // показывает выбор, а не остатки поиска. При скролле координаты портала
  // устаревают — проще закрыть, чем гоняться за ними.
  useEffect(() => {
    if (!open) return undefined;
    // НАБРАННОЕ СОХРАНЯЕТСЯ САМО, когда человек уходит из поля (просьба
    // владельца 23.09.2026). Раньше оно требовало нажатия «оставить как
    // есть», и это была лишняя работа: в таблице поступлений площадок вне
    // справочника больше, чем в нём, и подтверждать каждую — то же самое, что
    // набирать имя дважды.
    //
    // Точное совпадение со справочником при этом выигрывает у текста: если
    // набрано ровно «МТС», подставляем площадку, а не одноимённую надпись.
    const close = () => {
      const text = typed.current.trim();
      if (allowCustom && text) {
        const exact = partners.find(
          (p) => (p.name || '').trim().toLowerCase() === text.toLowerCase(),
        );
        if (exact) onChange(exact.id);
        else onCustom?.(text);
      }
      setOpen(false);
      setQuery('');
    };
    const away = (e) => {
      if (box.current?.contains(e.target) || dropdown.current?.contains(e.target)) return;
      close();
    };
    document.addEventListener('mousedown', away);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', away);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open, allowCustom, partners, onChange, onCustom]);

  function pick(partner) {
    onChange(partner ? partner.id : '');
    setOpen(false);
    setQuery('');
  }

  function keepTyped() {
    onCustom?.(query.trim());
    setOpen(false);
    setQuery('');
  }

  return (
    <div className="relative" ref={box}>
      <input
        ref={input}
        value={open ? query : shown}
        placeholder={shown || placeholder}
        onFocus={() => {
          place();
          setQuery('');
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          place();
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && found.length) pick(found[0]);
          // Ничего не нашлось, но имя набрано — оставляем как есть.
          else if (e.key === 'Enter' && allowCustom && query.trim()) keepTyped();
          if (e.key === 'Escape') {
            // Отмена: стираем набранное прежде, чем закрыть, — иначе его
            // сохранил бы обработчик ухода из поля.
            typed.current = '';
            setQuery('');
            setOpen(false);
          }
        }}
        className={inputClassName}
      />
      {open &&
        rect &&
        createPortal(
          <div
            ref={dropdown}
            style={{ position: 'fixed', left: rect.left, top: rect.top, width: rect.width }}
            className="z-50 mt-1 max-h-[280px] overflow-y-auto bg-surface border border-border rounded-card shadow-[0_8px_24px_rgba(0,0,0,0.18)]"
          >
            {allowEmpty && (
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(null)}
                className="block w-full text-left px-3 py-2 text-[13px] bg-transparent border-0 cursor-pointer font-sans text-text-muted hover:bg-hover"
              >
                — не указан —
              </button>
            )}
            {found.length === 0 && !(allowCustom && query.trim()) && (
              <div className="px-3 py-2 text-[12.5px] text-text-muted">Ничего не нашлось</div>
            )}
            {found.map((p) => (
              <button
                key={p.id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(p)}
                className={`block w-full text-left px-3 py-2 text-[13px] bg-transparent border-0 cursor-pointer font-sans ${
                  p.id === value ? 'text-accent' : 'text-text'
                } hover:bg-hover`}
              >
                {p.name}
              </button>
            ))}
            {/* «ОСТАВИТЬ КАК ЕСТЬ» — ПОСЛЕДНИМ (замечание владельца
                23.09.2026). Сначала человек должен увидеть подходящие
                площадки: набранное имя чаще всего есть в справочнике, и
                предлагать «оставить как есть» первой строкой значит
                подталкивать к выбору, который справочник обходит. */}
            {allowCustom && query.trim() && (
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={keepTyped}
                className={`block w-full text-left px-3 py-2 text-[13px] bg-transparent border-0 cursor-pointer font-sans text-text hover:bg-hover ${
                  found.length ? 'border-t border-border' : ''
                }`}
              >
                Оставить как есть: <b>{query.trim()}</b>
                <span className="text-text-muted"> — сохранится и просто так, если уйти из поля</span>
              </button>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
