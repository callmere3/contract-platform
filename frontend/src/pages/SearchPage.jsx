import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';

export function SearchPage({ onOpenNewContragent }) {
  return (
    <div className="max-w-[720px] mx-auto px-8 pt-[104px] pb-16 text-center">
      <Badge variant="pill" className="mb-6">
        ГЕНЕРАТОР ДОГОВОРОВ
      </Badge>

      <h1 className="text-[46px] font-extrabold tracking-[-0.025em] leading-[1.12] mb-4 text-text">
        Найдите контрагента —<br />получите документ
      </h1>

      <p className="text-[17px] text-text-secondary max-w-[440px] mx-auto mb-10 leading-relaxed">
        Никакой ручной сборки договоров, приложений и актов
      </p>

      <div className="flex items-center gap-3 bg-input-bg border border-border-strong rounded-card px-5 py-4 shadow-card">
        <span className="w-4 h-4 rounded-full border-2 border-text-muted relative flex-shrink-0">
          <span className="absolute w-[7px] h-[2px] bg-text-muted -right-[5px] -bottom-[1px] rotate-45 rounded-full" />
        </span>
        <input
          placeholder="Найти контрагента по имени или псевдониму"
          className="flex-1 border-none outline-none bg-transparent text-[15px] text-text font-sans"
        />
      </div>

      <div className="mt-6">
        <Button variant="primary" onClick={onOpenNewContragent}>
          + Новый контрагент
        </Button>
      </div>
    </div>
  );
}
