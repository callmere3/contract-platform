import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { browseFolder } from '../api/templates';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canManageTemplates } from '../auth/permissions';

const DOC_TYPE_LABELS = {
  contract: 'Договор',
  appendix: 'Приложение',
  act: 'Акт',
};

function FolderIcon() {
  return (
    <div className="w-[26px] h-5 relative flex-shrink-0">
      <div className="absolute top-0 left-0 w-3 h-[5px] bg-accent rounded-t-sm opacity-85" />
      <div className="absolute top-[3px] left-0 w-[26px] h-[17px] bg-accent rounded-sm opacity-85" />
    </div>
  );
}

/**
 * "Папки": дерево шаблонов. Навигация — по клику, содержимое каждой папки
 * запрашивается отдельно (GET /folders?parent_id=...), структура заранее
 * не известна, глубина любая.
 *
 * Текущая папка хранится в стейте, а не в URL: дерево — это навигация
 * внутри вкладки, а не адресуемый ресурс (в отличие от формы генерации,
 * ссылку на которую имеет смысл сохранять).
 *
 * Все роли видят дерево и могут открыть шаблон на генерацию. Кнопки
 * управления (папка/шаблон) — только admin (CAN_MANAGE_TEMPLATES).
 */
export function FoldersPage() {
  const [folderId, setFolderId] = useState(null);
  const [data, setData] = useState({ breadcrumb: [], folders: [], templates: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { openModal } = useModal();
  const { role } = useAuth();
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await browseFolder(folderId));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [folderId]);

  useEffect(() => {
    load();
  }, [load]);

  const isEmpty = data.folders.length === 0 && data.templates.length === 0;

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between p-5 border-b border-border gap-4">
          <div className="flex items-center gap-1.5 text-sm min-w-0">
            <button
              onClick={() => setFolderId(null)}
              className="text-text-secondary hover:text-text bg-transparent border-none cursor-pointer p-0 font-sans font-semibold"
            >
              Все шаблоны
            </button>
            {data.breadcrumb.map((name, i) => (
              <span key={i} className="flex items-center gap-1.5 min-w-0">
                <span className="text-text-muted">/</span>
                <span
                  className={
                    i === data.breadcrumb.length - 1
                      ? 'text-text font-semibold truncate'
                      : 'text-text-secondary truncate'
                  }
                >
                  {name}
                </span>
              </span>
            ))}
          </div>

          {canManageTemplates(role) && (
            <div className="flex gap-2.5 flex-shrink-0">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => openModal('newFolder', { parentId: folderId, onDone: load })}
              >
                + Папка
              </Button>
              {/* Шаблон можно положить только ВНУТРЬ папки: folder_id обязателен
                  (Form(...)), в корне шаблонов не бывает — см. browse_folder. */}
              {folderId && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => openModal('newTemplate', { folderId, onDone: load })}
                >
                  + Шаблон
                </Button>
              )}
            </div>
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}
        {!loading && !error && isEmpty && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {folderId ? 'Папка пуста.' : 'Папок пока нет.'}
          </div>
        )}

        {!loading &&
          !error &&
          data.folders.map((folder) => (
            <div
              key={folder.id}
              onClick={() => setFolderId(folder.id)}
              className="flex items-center px-5 py-4 border-b border-border last:border-b-0 hover:bg-surface-hover cursor-pointer transition-colors"
            >
              <div className="flex items-center gap-3.5 min-w-0">
                <FolderIcon />
                <span className="text-[15px] font-semibold text-text truncate">{folder.name}</span>
              </div>
            </div>
          ))}

        {!loading &&
          !error &&
          data.templates.map((tpl) => {
            const tags = [tpl.country, tpl.contragent_type, tpl.contract_family].filter(Boolean);
            return (
              <div
                key={tpl.id}
                className="flex items-center justify-between px-5 py-4 border-b border-border last:border-b-0 hover:bg-surface-hover transition-colors gap-3"
              >
                <div
                  onClick={() => navigate(`/doc/${tpl.id}`)}
                  className="min-w-0 flex-1 cursor-pointer"
                >
                  <div className="text-[15px] font-semibold text-text truncate">{tpl.name}</div>
                  <div className="text-[13px] text-text-muted mt-0.5">
                    {DOC_TYPE_LABELS[tpl.doc_type] ?? tpl.doc_type ?? 'Тип не задан'}
                  </div>
                </div>
                <div className="flex items-center gap-2.5 flex-shrink-0">
                  {/* Теги нужны для подбора документов через контрагента.
                      Без них шаблон не найдётся в "Документах контрагента" —
                      поэтому неполный набор явно помечаем. */}
                  <Badge variant={tags.length === 3 ? 'accent' : 'neutral'}>
                    {tags.length === 3 ? tags.join(' · ') : 'теги не заданы'}
                  </Badge>
                  {canManageTemplates(role) && (
                    <button
                      onClick={() => openModal('editTemplate', { template: tpl, onDone: load })}
                      className="w-7 h-7 rounded-full border border-border flex items-center justify-center text-xs text-text-secondary cursor-pointer bg-transparent hover:text-text"
                      aria-label="Настроить шаблон"
                    >
                      ⋯
                    </button>
                  )}
                </div>
              </div>
            );
          })}
      </Card>
    </div>
  );
}
