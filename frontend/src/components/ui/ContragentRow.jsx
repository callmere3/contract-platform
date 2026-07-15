import { Badge } from './Badge';

/**
 * Строка списка контрагентов — по дизайн-системе: название 15/600, алиасы
 * 13px muted под ним, бейдж-код справа, hover — surface-hover.
 *
 * Тег-код собирается из country/type/contract_family. Любой из них может
 * быть пустым: контрагент, заведённый импортом, бывает "неполным" (см.
 * докстринг Contragent на бэкенде) — тогда показываем нейтральный бейдж
 * "не заполнено" вместо акцентного, чтобы это было заметно, но не кричало
 * ошибкой.
 */
export function ContragentRow({ contragent, onClick }) {
  const parts = [contragent.country, contragent.type, contragent.contract_family].filter(Boolean);
  const complete = parts.length === 3;
  const nicknames = contragent.nicknames?.join(', ');

  return (
    <div
      onClick={() => onClick?.(contragent)}
      className="flex items-center justify-between px-5 py-4 border-b border-border last:border-b-0 cursor-pointer hover:bg-surface-hover transition-colors"
    >
      <div className="min-w-0 pr-4">
        <div className="text-[15px] font-semibold text-text truncate">{contragent.title}</div>
        {nicknames && <div className="text-[13px] text-text-muted mt-0.5 truncate">{nicknames}</div>}
      </div>
      <Badge variant={complete ? 'accent' : 'neutral'} className="flex-shrink-0">
        {complete ? parts.join(' · ') : 'не заполнено'}
      </Badge>
    </div>
  );
}
