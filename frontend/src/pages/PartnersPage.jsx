import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canManagePartners } from '../auth/permissions';
import { listPartners } from '../api/partners';

/**
 * ML Finance → «Партнёры»: площадки и агрегаторы, от которых приходят деньги.
 *
 * Экран устроен как «Контрагенты» и намеренно: это соседние вкладки одного
 * продукта, и человек не должен переучиваться, переходя между ними. Отсюда
 * тот же поиск с задержкой, та же пагинация и та же кнопка импорта справа от
 * фильтров.
 *
 * Разница только в содержимом строки: у партнёра ОДНО ПОЛЕ — имя. Поэтому
 * здесь нет ни фильтров по стране и типу, ни подсветки неполных карточек:
 * заполнять нечего, и всё, что с партнёром можно сделать, — переименовать
 * или удалить (модалка `partnerCard`).
 */
const PAGE_SIZE = 100;

export function PartnersPage() {
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const { openModal } = useModal();
  const { role } = useAuth();

  useEffect(() => {
    setPage(1);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listPartners({ q: q.trim(), page, pageSize: PAGE_SIZE });
      setItems(data.partners ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [q, page]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <PageHeader title="Партнёры">
        Площадки и агрегаторы, от которых приходят деньги. Нажмите на строку, чтобы посмотреть
        код Dista, поправить или удалить.
      </PageHeader>

      <Card>
        <div className="flex flex-wrap gap-3 p-5 border-b border-border">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по названию или коду Dista…"
            className="flex-1 min-w-[280px] bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
          />
          {canManagePartners(role) && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => openModal('newPartner', { onSaved: load })}
              >
                + Партнёр
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => openModal('partnersImportExport', { onImported: load })}
              >
                Импорт/экспорт
              </Button>
            </>
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-danger">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {q ? 'Ничего не найдено.' : 'Партнёров пока нет.'}
          </div>
        )}

        {!loading &&
          !error &&
          items.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => openModal('partnerCard', { partner: p, onChanged: load })}
              className="w-full flex items-center gap-4 px-5 py-3.5 border-b border-border last:border-b-0 bg-transparent cursor-pointer text-left font-sans hover:bg-surface-hover"
            >
              {/* Только имя: в списке партнёра ищут глазами по названию, а код
                  нужен при сверке — он в карточке, и по нему по-прежнему ищет
                  поле поиска (просьба владельца 17.09.2026). */}
              <span className="text-[15px] font-semibold text-text truncate">{p.name}</span>
            </button>
          ))}

        {!loading && !error && total > 0 && (
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-t border-border">
            <span className="text-[13px] text-text-muted">
              {total > PAGE_SIZE ? `Показаны ${from}–${to} из ${total}` : `Всего: ${total}`}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-2.5">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ← Назад
                </Button>
                <span className="text-[13px] text-text-muted tabular-nums">
                  Стр. {page} из {totalPages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Вперёд →
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
