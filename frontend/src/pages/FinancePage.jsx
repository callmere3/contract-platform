import { useCallback, useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { Button } from '../components/ui/Button';
import { useTags } from '../api/TagsContext';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canViewBalances } from '../auth/permissions';
import { formatMoney, listFinanceContragents } from '../api/finance';

/**
 * ML Finance → «Контрагенты»: та же база, что в ML Docs, но с балансом у
 * каждого и без всего документного.
 *
 * Чего здесь намеренно НЕТ по сравнению с «Базой контрагентов»:
 *   - красной подсветки неполных карточек: «неполная» — это про поля для
 *     документов, а в финансах карточка без даты договора совершенно
 *     нормальна;
 *   - импорта/экспорта и создания контрагента: карточки заводят в ML Docs,
 *     здесь по ним только считают деньги.
 *
 * Поиск и фильтры — те же параметры, что у ML Docs, и обрабатывает их тот же
 * серверный поиск: человек не должен находить контрагента в одном продукте и
 * не находить в другом.
 */
const PAGE_SIZE = 100;

export function FinancePage() {
  const { role } = useAuth();
  const [q, setQ] = useState('');
  const [country, setCountry] = useState('');
  const [contragentType, setContragentType] = useState('');
  const [page, setPage] = useState(1);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const { countries, contragent_types: contragentTypes } = useTags();
  const { openModal } = useModal();

  // Смена фильтра — назад на первую страницу: отфильтровав до пары записей,
  // иначе останешься на «стр. 5», где пусто.
  useEffect(() => {
    setPage(1);
  }, [q, country, contragentType]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listFinanceContragents({
        q: q.trim(),
        country,
        contragentType,
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(data.contragents ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [q, country, contragentType, page]);

  useEffect(() => {
    // Поиск с задержкой: список в 800+ карточек незачем дёргать на каждую
    // букву. 300 мс — примерно пауза между словами.
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  const selectClass =
    'bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none';

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <PageHeader title="Контрагенты">
        Баланс по каждому: поступления минус расходы. Нажмите на строку чтобы добавить новое поступление или расход.
      </PageHeader>

      <Card>
        <div className="flex gap-3 p-5 border-b border-border">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по названию или псевдониму…"
            className="flex-1 bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
          />
          <select value={country} onChange={(e) => setCountry(e.target.value)} className={selectClass}>
            <option value="">Все страны</option>
            {countries.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <select
            value={contragentType}
            onChange={(e) => setContragentType(e.target.value)}
            className={selectClass}
          >
            <option value="">Все типы</option>
            {contragentTypes.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-danger">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {q || country || contragentType ? 'Ничего не найдено.' : 'Контрагентов пока нет.'}
          </div>
        )}

        {!loading &&
          !error &&
          items.map((c) => (
            <FinanceRow
              key={c.id}
              contragent={c}
              showBalance={canViewBalances(role)}
              onClick={() =>
                openModal('financeContragent', { contragentId: c.id, onChanged: load })
              }
            />
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

/**
 * Строка списка: кто это слева, баланс справа.
 *
 * Отрицательный баланс красим, нулевой — приглушаем, положительный оставляем
 * обычным текстом. Красить плюс зелёным не стали: в списке из сотни строк
 * два цвета сразу превращаются в ёлку, а искать глазом надо именно минусы.
 */
function FinanceRow({ contragent, onClick, showBalance }) {
  const negative = Number(contragent.balance) < 0;
  const zero = Number(contragent.balance) === 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between gap-4 px-5 py-3.5 border-b border-border last:border-b-0 bg-transparent cursor-pointer text-left font-sans hover:bg-surface-hover"
    >
      <span className="min-w-0">
        <span className="block text-[15px] font-semibold text-text truncate">
          {contragent.title}
        </span>
        <span className="block text-[12.5px] text-text-muted truncate mt-0.5">
          {[contragent.country, contragent.type, ...(contragent.nicknames ?? [])]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      {/* Баланс видят не все: у кого права нет, тому сервер его и не
          присылает, а строка остаётся справочной — кто это и какие у него
          псевдонимы. */}
      {showBalance && (
        <span
          className={`text-[15px] font-semibold tabular-nums flex-shrink-0 ${
            negative ? 'text-danger' : zero ? 'text-text-muted' : 'text-text'
          }`}
        >
          {formatMoney(contragent.balance)}
        </span>
      )}
    </button>
  );
}
