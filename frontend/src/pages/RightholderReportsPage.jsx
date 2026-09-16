import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { UnderConstruction } from '../components/ui/UnderConstruction';

/**
 * ML Finance → «Отчёты правообладателям»: сюда приносят выгруженную из Dista
 * детализацию по ОДНОМУ правообладателю, а обратно получают тот же Excel, но
 * с подставленным балансом — готовый к отправке.
 *
 * Чем отличается от соседней «Загрузки отчётов»: там общий квартальный отчёт
 * на всех, и он МЕНЯЕТ балансы; здесь файл на одного человека, и баланс,
 * наоборот, в него ПОДСТАВЛЯЕТСЯ. Разные направления — поэтому и вкладки
 * разные, а не один экран с переключателем.
 *
 * Раздел пока не работает — почему он всё равно показан и как устроено «в
 * разработке», см. UnderConstruction.
 */
export function RightholderReportsPage() {
  return (
    <div className="max-w-[720px] mx-auto px-8 pt-[104px] pb-16">
      <UnderConstruction note="Так этот раздел будет выглядеть. Отчёты правообладателям пока не формируются.">
        <Badge variant="pill" className="mb-6">
          ОТЧЁТЫ ПРАВООБЛАДАТЕЛЯМ
        </Badge>

        {/* Переносы руками — по той же причине, что и на соседней вкладке:
            автоперенос на 46px рвёт строку где придётся. */}
        <h1 className="text-[46px] font-extrabold tracking-[-0.025em] leading-[1.12] mb-4 text-text">
          Детализация из Dista —<br />
          готовый отчёт<br />
          правообладателю
        </h1>

        <p className="text-[17px] text-text-secondary max-w-[480px] mx-auto mb-10 leading-relaxed">
          Загрузите Excel с детализацией по одному правообладателю — ML Finance подставит в него
          текущий баланс и вернёт готовый файл в том же формате.
        </p>

        <Button variant="primary" disabled>
          + Загрузить детализацию
        </Button>
      </UnderConstruction>
    </div>
  );
}
