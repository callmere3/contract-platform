import { useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { listGenerationHistory } from '../api/generationHistory';

/**
 * "История генерации" — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации: контрагент,
 * шаблон, кто сгенерировал, когда.
 *
 * Просмотра/пересоздания самого документа здесь пока нет (этап 2, файл
 * нигде не хранится — воссоздаётся по сохранённому payload формы).
 */
export function GenerationHistoryPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        setEntries(await listGenerationHistory());
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between p-5 border-b border-border">
          <span className="text-sm font-semibold text-text">История генерации</span>
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}
        {!loading && !error && entries.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">Документы ещё не генерировались.</div>
        )}

        {!loading &&
          !error &&
          entries.map((e) => (
            <div
              key={e.id}
              className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border last:border-b-0"
            >
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-text truncate">
                  {e.contragent_title ?? '— без контрагента —'}
                </div>
                <div className="text-[13px] text-text-muted mt-0.5 truncate">{e.template_name}</div>
              </div>

              <div className="text-right flex-shrink-0">
                <div className="text-[13px] text-text">{e.user_username ?? '—'}</div>
                <div className="text-[11px] text-text-muted mt-0.5">
                  {new Date(e.created_at).toLocaleString('ru-RU')}
                </div>
              </div>
            </div>
          ))}
      </Card>
    </div>
  );
}
