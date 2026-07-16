import { Badge } from './Badge';

/**
 * Строка списка контрагентов — по дизайн-системе: название 15/600, алиасы
 * 13px muted под ним, бейдж-код справа, hover — surface-hover.
 *
 * Полнота карточки считается на бэкенде (is_complete в _contragent_summary):
 * заполнены ВСЕ поля, которые менеджер видит в карточке. Неполную карточку
 * подсвечиваем красным (красный левый кант + мягкая красная подложка +
 * красный бейдж "не заполнено") — контрагент бывает заведён "неполным" через
 * импорт, и это надо дозаполнить. У полной карточки бейдж показывает тег-код
 * country · type · contract_family (у полной все три тега точно заполнены).
 */
export function ContragentRow({ contragent, onClick }) {
  const complete = contragent.is_complete;
  const parts = [contragent.country, contragent.type, contragent.contract_family].filter(Boolean);
  const nicknames = contragent.nicknames?.join(', ');

  return (
    <div
      onClick={() => onClick?.(contragent)}
      className={`flex items-center justify-between px-5 py-4 border-b border-border last:border-b-0 cursor-pointer transition-colors ${
        complete
          ? 'hover:bg-surface-hover'
          : 'bg-danger-soft border-l-2 border-l-danger'
      }`}
    >
      <div className="min-w-0 pr-4">
        <div className="text-[15px] font-semibold text-text truncate">{contragent.title}</div>
        {nicknames && <div className="text-[13px] text-text-muted mt-0.5 truncate">{nicknames}</div>}
      </div>
      {complete ? (
        <Badge variant="accent" className="flex-shrink-0">
          {parts.join(' · ')}
        </Badge>
      ) : (
        <Badge variant="danger" className="flex-shrink-0">
          не заполнено
        </Badge>
      )}
    </div>
  );
}
