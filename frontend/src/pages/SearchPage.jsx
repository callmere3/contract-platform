import { useState } from 'react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ContragentRow } from '../components/ui/ContragentRow';
import { useContragentSearch } from '../hooks/useContragentSearch';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canCreateContragents } from '../auth/permissions';

/**
 * Стартовый экран: hero-поиск. Главный сценарий — найти контрагента и сразу
 * перейти к его документам (модалка "Документы контрагента").
 *
 * Выдача появляется только когда что-то введено (enabled: q не пустой) —
 * незачем грузить весь список из 200 записей на пустой строке, для этого
 * есть вкладка "База контрагентов".
 */
export function SearchPage() {
  const [q, setQ] = useState('');
  const { openModal } = useModal();
  const { role } = useAuth();

  const query = q.trim();
  const { items, loading, error } = useContragentSearch({ q: query, enabled: query.length > 0 });

  const openDocs = (contragent) => openModal('contragentDocs', { contragentId: contragent.id });

  return (
    <div className="max-w-[720px] mx-auto px-8 pt-[104px] pb-16">
      <div className="text-center">
        <Badge variant="pill" className="mb-6">
          ГЕНЕРАТОР ДОГОВОРОВ
        </Badge>

        <h1 className="text-[46px] font-extrabold tracking-[-0.025em] leading-[1.12] mb-4 text-text">
          Найдите контрагента —<br />
          получите документ
        </h1>

        <p className="text-[17px] text-text-secondary max-w-[440px] mx-auto mb-10 leading-relaxed">
          Никакой ручной сборки договоров, приложений и актов
        </p>
      </div>

      <div className="flex items-center gap-3 bg-input-bg border border-border-strong rounded-card px-5 py-4 shadow-card">
        <span className="w-4 h-4 rounded-full border-2 border-text-muted relative flex-shrink-0">
          <span className="absolute w-[7px] h-[2px] bg-text-muted -right-[5px] -bottom-[1px] rotate-45 rounded-full" />
        </span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Найти контрагента по имени или псевдониму"
          className="flex-1 border-none outline-none bg-transparent text-[15px] text-text font-sans"
          autoFocus
        />
      </div>

      {query.length > 0 && (
        <Card className="mt-4">
          {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Ищем…</div>}
          {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="px-5 py-4 text-[13px] text-text-muted">Ничего не найдено.</div>
          )}
          {!loading &&
            !error &&
            items.map((c) => <ContragentRow key={c.id} contragent={c} onClick={openDocs} />)}
        </Card>
      )}

      {canCreateContragents(role) && (
        <div className="mt-6 text-center">
          <Button variant="primary" onClick={() => openModal('newContragent')}>
            + Новый контрагент
          </Button>
        </div>
      )}
    </div>
  );
}
