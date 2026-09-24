import { useEffect, useRef } from 'react';
import { CloseIcon } from './icons';

/**
 * Базовая модалка. Стек модалок (карточка контрагента → документы) —
 * просто два <Modal> одновременно в дереве, второй поверх первого
 * за счёт возрастающего z-index (уровень задаётся через `level`).
 *
 * ДЕЙСТВИЯ НАД САМИМ ОБЪЕКТОМ — ЗНАЧКАМИ В ШАПКЕ, рядом с крестиком
 * (17.09.2026, решение владельца). Раньше «Редактировать» и «Удалить» стояли
 * кнопками внизу, вперемешку с действиями «дальше» («Документы», «Внести
 * поступление»), и читались как продолжение сценария. Но править и удалять —
 * это про сам объект, а не следующий шаг, и место им там же, где закрытие
 * окна. Внизу остаётся только то, ради чего окно открывают дальше.
 *
 * `fullscreen` — ОКНО ВО ВЕСЬ ЭКРАН, без полей вокруг (просьба владельца
 * 24.09.2026, окно загруженного отчёта). Для окон, где главное — большая
 * таблица: затемнённое поле вокруг ничего не даёт, а таблицу в окне на 85%
 * высоты приходилось листать чаще нужного. `width` при этом не действует.
 * Тело окна становится колонкой: элемент с `flex-1 min-h-0 overflow-auto`
 * забирает всю оставшуюся высоту и прокручивается сам, а всё прочее стоит
 * на месте.
 */
export function Modal({
  title,
  onClose,
  children,
  footer,
  actions,
  width = 480,
  level = 0,
  isTop = true,
  fullscreen = false,
}) {
  // Escape закрывает только ВЕРХНЮЮ модалку стека. Все модалки стека
  // отрисованы одновременно, и каждая повесила бы свой обработчик на
  // document — по одному Escape закрылись бы разом все. Поэтому реагирует
  // только та, которой ModalRoot передал isTop (последняя в стеке).
  useEffect(() => {
    if (!isTop) return;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, isTop]);

  // ФОКУС ПЕРЕЕЗЖАЕТ В ОКНО, ИНАЧЕ ENTER НАЖИМАЕТ КНОПКУ ПОД НИМ (замечание
  // владельца 24.09.2026). Окно открывают кнопкой, и фокус остаётся на ней:
  // нажатие Enter в открытом окне подтверждения снова жало мусорку в строке и
  // открывало ВТОРОЕ такое же окно поверх первого. То же было бы у любого
  // окна, открытого кнопкой.
  //
  // Только если фокус СНАРУЖИ: окно с полем ввода наводит фокус само, и
  // перетягивать его на рамку значило бы ломать ввод. И только у верхнего
  // окна стека — нижние фокус себе не забирают.
  const card = useRef(null);
  useEffect(() => {
    if (!isTop || !card.current) return;
    if (!card.current.contains(document.activeElement)) card.current.focus();
  }, [isTop]);

  // ОКНО ВО ВЕСЬ ЭКРАН ПРЯЧЕТ ПРОКРУТКУ СТРАНИЦЫ ПОД СОБОЙ (замечание
  // владельца 24.09.2026). Окно лежит поверх страницы, а страница под ним
  // длиннее экрана и сохраняла свою полосу прокрутки: справа висела вторая
  // прокрутка, которой в окне нечего прокручивать. Только у полноэкранных:
  // у обычного окна страница видна по краям, и пропавшая полоса сдвинула бы
  // её вбок на свою ширину. Прежнее значение возвращаем, а не стираем —
  // окна вкладываются друг в друга.
  useEffect(() => {
    if (!fullscreen) return;
    const html = document.documentElement;
    const before = html.style.overflow;
    html.style.overflow = 'hidden';
    return () => {
      html.style.overflow = before;
    };
  }, [fullscreen]);

  return (
    <div
      onClick={onClose}
      style={{ zIndex: 100 + level * 10 }}
      className={`fixed inset-0 bg-black/50 flex items-center justify-center ${
        fullscreen ? '' : 'px-4'
      }`}
    >
      <div
        ref={card}
        // tabIndex −1 делает рамку окна годной целью для фокуса, но не
        // добавляет её в обход по Tab: это не элемент управления.
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={fullscreen ? undefined : { width, maxWidth: '100%' }}
        className={`bg-surface flex flex-col outline-none ${
          fullscreen
            ? 'w-full h-full'
            : 'border border-border rounded-card shadow-card max-h-[85vh]'
        }`}
      >
        <div className="flex items-center justify-between gap-4 px-6 py-5 border-b border-border">
          <span className="text-[15px] font-semibold text-text min-w-0 truncate">{title}</span>
          <div className="flex items-center gap-2 flex-shrink-0">
            {actions}
            {/* Крестик и значки рядом — 32 пикселя, и все рисованные, а не
                эмодзи (17.09.2026): эмодзи приходит со своим цветом и своими
                пропорциями от системного шрифта, и на Windows мусорка
                выходила мелким красным пятном, которому не помогал ни
                размер, ни вес. См. components/ui/icons.jsx. */}
            <button
              onClick={onClose}
              aria-label="Закрыть"
              className="w-8 h-8 rounded-full border border-border flex items-center justify-center text-text-secondary cursor-pointer bg-transparent hover:text-text"
            >
              <CloseIcon />
            </button>
          </div>
        </div>

        <div
          className={`px-6 py-6 overflow-y-auto ${
            fullscreen ? 'flex-1 min-h-0 flex flex-col' : ''
          }`}
        >
          {children}
        </div>

        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-5 border-t border-border">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Значок-действие в шапке модалки: карандаш, мусорка и им подобные.
 *
 * Круглый и того же размера, что крестик, — они стоят рядом и должны
 * читаться как один ряд, а не как кнопка и что-то ещё. `danger` красит
 * содержимое в красный: удаление единственное, что стоит выделять цветом,
 * иначе ряд превращается в светофор.
 *
 * `icon` — рисованный значок из `icons.jsx`, а не эмодзи: он берёт цвет
 * кнопки через currentColor, поэтому и красный у удаления, и приглушённый у
 * выключенной получаются сами.
 *
 * `title` обязателен по смыслу: значок без подписи — загадка, и наведение
 * мышью единственный способ её разгадать (оно же уходит в aria-label).
 */
export function ModalAction({ icon, title, onClick, danger = false, disabled = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-hint={title}
      aria-label={title}
      disabled={disabled}
      className={`w-8 h-8 rounded-full border border-border flex items-center justify-center cursor-pointer bg-transparent disabled:opacity-40 disabled:cursor-default ${
        danger ? 'text-danger' : 'text-text-secondary hover:text-text'
      }`}
    >
      {icon}
    </button>
  );
}
