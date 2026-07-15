import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';

function FolderIcon() {
  return (
    <div className="w-[26px] h-5 relative flex-shrink-0">
      <div className="absolute top-0 left-0 w-3 h-[5px] bg-accent rounded-t-sm opacity-85" />
      <div className="absolute top-[3px] left-0 w-[26px] h-[17px] bg-accent rounded-sm opacity-85" />
    </div>
  );
}

export function FoldersPage({ folders = [], onNewFolder, onNewTemplate, onOpenTemplate }) {
  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between p-5 border-b border-border">
          <span className="text-sm font-semibold text-text">Все шаблоны</span>
          <div className="flex gap-2.5">
            <Button variant="secondary" size="sm" onClick={onNewFolder}>
              + Папка
            </Button>
            <Button variant="primary" size="sm" onClick={onNewTemplate}>
              + Шаблон
            </Button>
          </div>
        </div>

        {folders.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between px-5 py-4 border-b border-border last:border-b-0 hover:bg-surface-hover"
          >
            <div className="flex items-center gap-3.5">
              <FolderIcon />
              <span
                onClick={() => onOpenTemplate?.(item)}
                className="text-[15px] font-semibold text-text cursor-pointer"
              >
                {item.name}
              </span>
            </div>
            <button className="w-7 h-7 rounded-full border border-border flex items-center justify-center text-xs text-text-secondary cursor-pointer bg-transparent">
              ↗
            </button>
          </div>
        ))}
      </Card>
    </div>
  );
}
