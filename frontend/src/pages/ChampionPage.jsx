import { useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { fetchChampionBoard } from '../api/champion';

/**
 * «Кубок» — только admin (canViewChampionBoard / CAN_VIEW_CHAMPION_BOARD).
 *
 * Два блока и два РАЗНЫХ месяца, это не путаница:
 *   сверху — кто носит кубок прямо сейчас, то есть победитель ПРОШЛОГО,
 *            уже закрытого месяца (его же значок стоит у имени);
 *   снизу  — рейтинг ТЕКУЩЕГО месяца: кто идёт на кубок следующим.
 *
 * Считает всё сервер (app/champion.py). Здесь только показ — поэтому
 * страница не знает ни правил уникальности, ни того, кто вне конкурса.
 */
export function ChampionPage() {
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    fetchChampionBoard()
      .then((data) => alive && setBoard(data))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const current = board?.current;
  const rating = board?.rating;
  const rows = rating?.rows ?? [];
  const leader = rows.length > 0 ? rows[0].documents : 0;

  return (
    <div className="max-w-[880px] mx-auto px-8 pt-12 pb-20 flex flex-col gap-6">
      {error && (
        <Card>
          <div className="p-5 text-[13px] text-danger">{error}</div>
        </Card>
      )}

      {/* Обладатель кубка */}
      <Card>
        <div className="flex flex-col items-center text-center gap-3 px-6 py-9">
          <span role="img" aria-label="Кубок" className="text-[64px] leading-none">
            🏆
          </span>
          {loading ? (
            <div className="text-[13px] text-text-muted">Загружаем…</div>
          ) : current ? (
            <>
              <div className="text-[20px] font-semibold text-text">
                {current.winners.map((w) => w.full_name || w.username).join(', ')}
              </div>
              <div className="text-[14px] text-text-secondary">
                {current.winners.length > 1 ? 'чемпионы ' : 'чемпион '}
                {current.period_of}
              </div>
            </>
          ) : (
            <>
              <div className="text-[17px] font-semibold text-text">Кубок пока никому не вручён</div>
              <div className="text-[13px] text-text-muted max-w-[42ch] leading-relaxed">
                За прошлый месяц не сформировано ни одного документа. Кубок появится
                первого числа месяца, следующего за тем, в котором была работа.
              </div>
            </>
          )}
        </div>
      </Card>

      {/* Гонка текущего месяца */}
      <Card>
        <div className="flex items-baseline justify-between p-5 border-b border-border">
          <span className="text-sm font-semibold text-text">
            Рейтинг {rating ? rating.period_of : 'месяца'}
          </span>
          <span className="text-[12px] text-text-muted">идёт сейчас</span>
        </div>

        {loading && <div className="p-5 text-[13px] text-text-muted">Загружаем…</div>}

        {!loading && rows.length === 0 && (
          <div className="p-5 text-[13px] text-text-muted">
            В этом месяце ещё никто не формировал документы.
          </div>
        )}

        {!loading &&
          rows.map((r, i) => (
            <div
              key={r.id}
              className="flex items-center gap-4 px-5 py-3.5 border-b border-border last:border-b-0"
            >
              <span
                className={`w-6 text-center text-[13px] font-semibold tabular-nums flex-shrink-0 ${
                  i === 0 ? 'text-accent' : 'text-text-muted'
                }`}
              >
                {i + 1}
              </span>

              <span className="text-[14px] text-text truncate flex-shrink-0 w-[190px]">
                {r.full_name || r.username}
              </span>

              {/* Полоса — доля от лидера: глазами видно отрыв, а не только цифру */}
              <span className="flex-1 h-2 bg-input-bg rounded-full overflow-hidden">
                <span
                  className={`block h-full rounded-full ${i === 0 ? 'bg-accent' : 'bg-border'}`}
                  style={{ width: leader > 0 ? `${Math.round((r.documents / leader) * 100)}%` : 0 }}
                />
              </span>

              <span className="text-[13px] text-text-secondary tabular-nums w-14 text-right flex-shrink-0">
                {r.documents}
              </span>
            </div>
          ))}
      </Card>

      <p className="text-[12.5px] text-text-muted leading-relaxed m-0 px-1">
        Считаются уникальные документы: один и тот же документ, выгруженный и в Word,
        и в PDF, — это один документ. Тот же шаблон тому же контрагенту, но с другими
        данными, считается отдельно. Администраторы в зачёт не идут.
      </p>
    </div>
  );
}
