import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';

/**
 * ML Finance → «Загрузка отчётов»: первый экран продукта, собран по образцу
 * hero-страницы «Генерация» в ML Docs — крупное обещание и одно действие под
 * ним. Поисковой строки здесь нет: искать нечего, отчёт приносят файлом.
 *
 * РАЗДЕЛ ПОКА НЕ РАБОТАЕТ и показан намеренно (решение владельца 16.09.2026):
 * по нему видно, куда движется продукт, а тому, кто откроет его по ошибке,
 * сразу понятно, что грузить ещё нечего.
 *
 * «В разработке» сделано ДВУМЯ слоями, и это не украшательство:
 *   - содержимое приглушено и НЕ ПРИНИМАЕТ НАЖАТИЙ (`pointer-events-none`),
 *     поэтому кнопка не нажимается физически, а не только выглядит неактивной.
 *     Одного `disabled` на кнопке мало: завтра рядом появится вторая, и о ней
 *     забудут;
 *   - поверх — штамп, который читается раньше, чем текст под ним.
 * Когда загрузка заработает, снимается ровно этот блок: сама страница уже
 * настоящая.
 */
export function FinanceReportsPage() {
  return (
    <div className="max-w-[720px] mx-auto px-8 pt-[104px] pb-16 relative">
      {/* Слой содержимого: приглушён и не реагирует на мышь. aria-hidden —
          чтобы скринридер не зачитывал недоступное действие как доступное. */}
      <div className="opacity-40 grayscale pointer-events-none select-none" aria-hidden="true">
        <div className="text-center">
          <Badge variant="pill" className="mb-6">
            ЗАГРУЗКА ОТЧЁТОВ
          </Badge>

          <h1 className="text-[46px] font-extrabold tracking-[-0.025em] leading-[1.12] mb-4 text-text">
            Загрузи отчёт из Dista —<br />
            получи финальный отчёт с балансом
          </h1>

          <p className="text-[17px] text-text-secondary max-w-[480px] mx-auto mb-10 leading-relaxed">
            Квартальный отчёт разложится по контрагентам: суммы сойдутся с уже внесёнными
            выплатами, и по каждому будет видно, сколько причитается. Сводить таблицы руками
            больше не придётся.
          </p>

          <Button variant="primary" disabled>
            Загрузить отчёт
          </Button>
        </div>
      </div>

      {/* Штамп поверх. Наклон и пунктир — чтобы он читался как пометка на
          макете, а не как часть интерфейса, которую можно нажать. */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 pointer-events-none">
        <span className="-rotate-[8deg] border-2 border-dashed border-text-muted rounded-card px-6 py-2.5 text-[22px] font-extrabold tracking-[0.12em] uppercase text-text-muted">
          В разработке
        </span>
        <span className="text-[13px] text-text-muted max-w-[320px] text-center leading-relaxed">
          Так этот раздел будет выглядеть. Загрузка отчётов пока не работает — балансы ведутся
          вручную во вкладке «Контрагенты».
        </span>
      </div>
    </div>
  );
}
