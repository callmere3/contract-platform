import { useLocation, useNavigate } from 'react-router-dom';
import { useDraft } from './DraftContext';

const DOC_TYPE_LABELS = { contract: 'Договор', appendix: 'Приложение', act: 'Акт' };

/**
 * Плашка черновика в правом нижнем углу — как свёрнутое письмо в почте.
 * Видна на всех экранах, КРОМЕ самой формы: пока ты в форме, черновик —
 * это она и есть, плашка была бы дублем.
 *
 * Клик по плашке — вернуться к незавершённому документу (restore=1, форма
 * восстановит сохранённые значения). Крестик — выбросить черновик.
 *
 * z-40 — ниже модалок (у них z начинается со 100, см. Modal.jsx): диалог
 * подтверждения выхода должен перекрывать плашку, а не наоборот.
 */
export function DraftDock() {
  const { draft, clearDraft } = useDraft();
  const navigate = useNavigate();
  const location = useLocation();

  if (!draft || location.pathname.startsWith('/doc/')) return null;

  const title = draft.title || 'Документ';
  const kind = DOC_TYPE_LABELS[draft.docType] || 'Документ';

  const open = () => {
    const qs = new URLSearchParams({ restore: '1' });
    if (draft.contragentId) qs.set('contragent', draft.contragentId);
    navigate(`/doc/${draft.templateId}?${qs.toString()}`);
  };

  return (
    <div className="fixed bottom-5 right-5 z-40 flex items-center gap-2 bg-surface border border-border rounded-card shadow-card pl-3.5 pr-2 py-2.5 max-w-[280px]">
      <button
        onClick={open}
        className="flex items-center gap-2.5 min-w-0 bg-transparent border-none cursor-pointer text-left p-0"
        title="Продолжить заполнение"
      >
        <span className="text-accent text-sm flex-shrink-0" aria-hidden>
          ✎
        </span>
        <span className="min-w-0">
          <span className="block text-[13px] font-semibold text-text truncate">{title}</span>
          <span className="block text-[11px] text-text-muted truncate">Черновик · {kind}</span>
        </span>
      </button>
      <button
        onClick={clearDraft}
        aria-label="Удалить черновик"
        className="w-6 h-6 rounded-full border border-border flex items-center justify-center text-xs text-text-secondary cursor-pointer bg-transparent hover:text-text flex-shrink-0"
      >
        ×
      </button>
    </div>
  );
}
