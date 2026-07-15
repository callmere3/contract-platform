import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';

export function DatabasePage({ contragents = [], onOpenImportExport, onOpenContragent }) {
  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex gap-3 p-5 border-b border-border">
          <input
            placeholder="Поиск по названию или псевдониму…"
            className="flex-1 bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
          />
          <select className="bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans">
            <option>Все страны</option>
          </select>
          <select className="bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans">
            <option>Все типы</option>
          </select>
          <Button variant="primary" size="sm" onClick={onOpenImportExport}>
            Импорт/экспорт
          </Button>
        </div>

        {contragents.map((item) => (
          <div
            key={item.id}
            onClick={() => onOpenContragent?.(item)}
            className="flex items-center justify-between px-5 py-4 border-b border-border last:border-b-0 cursor-pointer hover:bg-surface-hover"
          >
            <div className="flex items-center gap-3">
              <div>
                <div className="text-[15px] font-semibold text-text">{item.name}</div>
                {item.alias && (
                  <div className="text-[13px] text-text-muted mt-0.5">{item.alias}</div>
                )}
              </div>
            </div>
            <Badge variant="accent">{item.code}</Badge>
          </div>
        ))}
      </Card>
    </div>
  );
}
