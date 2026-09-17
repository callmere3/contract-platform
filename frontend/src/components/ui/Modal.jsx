import { useEffect } from 'react';

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

  return (
    <div
      onClick={onClose}
      style={{ zIndex: 100 + level * 10 }}
      className="fixed inset-0 bg-black/50 flex items-center justify-center px-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width, maxWidth: '100%' }}
        className="bg-surface border border-border rounded-card shadow-card max-h-[85vh] flex flex-col"
      >
        <div className="flex items-center justify-between gap-4 px-6 py-5 border-b border-border">
          <span className="text-[15px] font-semibold text-text min-w-0 truncate">{title}</span>
          <div className="flex items-center gap-2 flex-shrink-0">
            {actions}
            <button
              onClick={onClose}
              aria-label="Закрыть"
              className="w-7 h-7 rounded-full border border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
            >
              ×
            </button>
          </div>
        </div>

        <div className="px-6 py-6 overflow-y-auto">{children}</div>

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
 * `title` обязателен по смыслу: значок без подписи — загадка, и наведение
 * мышью единственный способ её разгадать (оно же уходит в aria-label).
 */
export function ModalAction({ icon, title, onClick, danger = false, disabled = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={`w-7 h-7 rounded-full border border-border flex items-center justify-center text-[13px] cursor-pointer bg-transparent disabled:opacity-40 disabled:cursor-default ${
        danger ? 'text-danger' : 'text-text-secondary'
      }`}
    >
      {icon}
    </button>
  );
}
