import { useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ContragentRow } from '../components/ui/ContragentRow';
import { useContragentSearch } from '../hooks/useContragentSearch';
import { useTags } from '../api/TagsContext';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canOpenImportExport } from '../auth/permissions';

/**
 * "База контрагентов": весь список с фильтрами.
 *
 * В отличие от hero-поиска, здесь список грузится сразу (enabled всегда):
 * это справочник, его открывают чтобы посмотреть что вообще есть.
 * Лимит 200 — на стороне сервера (см. search_contragents).
 *
 * Фильтр по contract_family намеренно отсутствует — его нет и на бэкенде
 * (см. докстринг search_contragents: "фильтр по роялти/авансу не нужен").
 */
export function DatabasePage() {
  const [q, setQ] = useState('');
  const [country, setCountry] = useState('');
  const [contragentType, setContragentType] = useState('');
  const { countries, contragent_types: contragentTypes } = useTags();
  const { openModal } = useModal();
  const { role } = useAuth();

  const { items, loading, error, refetch } = useContragentSearch({
    q: q.trim(),
    country,
    contragentType,
  });

  const selectClass =
    'bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none';

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex gap-3 p-5 border-b border-border">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по названию или псевдониму…"
            className="flex-1 bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
          />
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className={selectClass}
          >
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
          {canOpenImportExport(role) && (
            <Button
              variant="primary"
              size="sm"
              // Экспорт выгружает контрагентов по ТЕКУЩЕМУ фильтру списка —
              // передаём его в модалку (см. handleExport там).
              onClick={() =>
                openModal('importExport', { filters: { q: q.trim(), country, contragentType } })
              }
            >
              Импорт/экспорт
            </Button>
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {q || country || contragentType ? 'Ничего не найдено.' : 'Контрагентов пока нет.'}
          </div>
        )}
        {!loading &&
          !error &&
          items.map((c) => (
            <ContragentRow
              key={c.id}
              contragent={c}
              onClick={() =>
                openModal('contragentCard', { contragentId: c.id, onChanged: refetch })
              }
            />
          ))}
      </Card>
    </div>
  );
}
