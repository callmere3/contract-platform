import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Modal } from '../components/ui/Modal';
import { useModal } from './ModalProvider';
import { getContragent, getContragentTemplates } from '../api/contragents';

const DOC_TYPE_LABELS = {
  contract: 'Договор',
  appendix: 'Приложение',
  act: 'Акт',
};

/**
 * Документы, подходящие контрагенту (GET /contragents/{id}/templates).
 * Подбор — строгое совпадение трёх тегов (country/type/contract_family)
 * контрагента и шаблона.
 *
 * Пустой список бывает по двум разным причинам, и их важно различать:
 *  1) у контрагента не заполнены теги ("неполная" карточка из импорта) —
 *     сервер отдаёт пустой список молча, это не ошибка;
 *  2) теги есть, но ни один шаблон под них не заведён.
 * Поэтому грузим и карточку тоже — чтобы сказать человеку, что именно не так.
 */
export function ContragentDocsModal({ contragentId, level, isTop }) {
  const { closeModal, closeAllModals } = useModal();
  const navigate = useNavigate();

  const [contragent, setContragent] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [detail, docs] = await Promise.all([
          getContragent(contragentId),
          getContragentTemplates(contragentId),
        ]);
        if (cancelled) return;
        setContragent(detail);
        setTemplates(docs.templates);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [contragentId]);

  const openDocForm = (template) => {
    // Уходим на отдельный роут формы генерации — модалки при этом закрываем
    // все: форма это полноценный экран, а не ещё один слой поверх.
    closeAllModals();
    navigate(`/doc/${template.id}?contragent=${contragentId}`);
  };

  const tagsIncomplete =
    contragent && !(contragent.country && contragent.type && contragent.contract_family);

  return (
    <Modal
      title="Документы контрагента"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={520}
    >
      {loading && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-accent">{error}</div>}

      {!loading && !error && contragent && (
        <>
          <div className="text-[13px] text-text-secondary mb-4">
            Совместимые шаблоны для «{contragent.title}»
          </div>

          {tagsIncomplete && (
            <div className="text-[13px] text-text-muted leading-relaxed">
              У карточки не заполнены страна, тип контрагента или тип договора — без них подобрать
              документы нельзя. Дозаполните карточку, и шаблоны появятся здесь.
            </div>
          )}

          {!tagsIncomplete && templates.length === 0 && (
            <div className="text-[13px] text-text-muted leading-relaxed">
              Нет шаблонов для связки {contragent.country} · {contragent.type} ·{' '}
              {contragent.contract_family}.
            </div>
          )}

          {templates.length > 0 && (
            <div className="border border-border rounded-input overflow-hidden">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  onClick={() => openDocForm(tpl)}
                  className="flex items-center justify-between px-4 py-3 border-b border-border last:border-b-0 cursor-pointer hover:bg-surface-hover transition-colors"
                >
                  <div className="min-w-0 pr-3">
                    <div className="text-sm font-semibold text-text truncate">{tpl.name}</div>
                    <div className="text-[11px] text-text-muted mt-0.5 tracking-[0.03em]">
                      {DOC_TYPE_LABELS[tpl.doc_type] ?? tpl.doc_type ?? '—'}
                    </div>
                  </div>
                  <span className="w-7 h-7 rounded-full border border-border flex items-center justify-center text-text-secondary text-xs flex-shrink-0">
                    ↗
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
