/**
 * Базовая модалка. Стек модалок (карточка контрагента → документы) —
 * просто два <Modal> одновременно в дереве, второй поверх первого
 * за счёт возрастающего z-index (уровень задаётся через `level`).
 */
export function Modal({ title, onClose, children, footer, width = 480, level = 0 }) {
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
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <span className="text-[15px] font-semibold text-text">{title}</span>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="w-7 h-7 rounded-full border border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
          >
            ×
          </button>
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
