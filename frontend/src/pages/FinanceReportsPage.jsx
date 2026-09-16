import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { UnderConstruction } from '../components/ui/UnderConstruction';

/**
 * ML Finance → «Загрузка отчётов»: первый экран продукта, собран по образцу
 * hero-страницы «Генерация» в ML Docs — крупное обещание и одно действие под
 * ним. Поисковой строки здесь нет: искать нечего, отчёт приносят файлом.
 *
 * Раздел пока не работает — почему он всё равно показан и как устроено «в
 * разработке», см. UnderConstruction.
 */
export function FinanceReportsPage() {
  return (
    <div className="max-w-[720px] mx-auto px-8 pt-[104px] pb-16">
      <UnderConstruction note="Так этот раздел будет выглядеть. Загрузка отчётов пока не работает — балансы ведутся вручную во вкладке «Контрагенты».">
        <Badge variant="pill" className="mb-6">
          ЗАГРУЗКА ОТЧЁТОВ
        </Badge>

        {/* Переносы расставлены руками: на 46px строка «обновите балансы всех
            контрагентов» в 720 пикселей не влезает, а автоперенос рвёт её в
            произвольном месте — заголовок начинает выглядеть случайным. */}
        <h1 className="text-[46px] font-extrabold tracking-[-0.025em] leading-[1.12] mb-4 text-text">
          Загрузите отчёт из Dista —<br />
          обновите балансы всех<br />
          контрагентов в один клик
        </h1>

        <p className="text-[17px] text-text-secondary max-w-[480px] mx-auto mb-10 leading-relaxed">
          Квартальный отчёт из Dista распределится по всем контрагентам и обновит их баланс.
        </p>

        <Button variant="primary" disabled>
          + Загрузить отчёт
        </Button>
      </UnderConstruction>
    </div>
  );
}
