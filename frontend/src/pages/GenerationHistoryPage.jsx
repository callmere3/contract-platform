import { useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { listGenerationHistory, recreateGeneratedDocument } from '../api/generationHistory';

/**
 * "История генерации" — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации: контрагент,
 * шаблон, кто сгенерировал, когда — и позволяет посмотреть сам документ
 * (этап 2): он нигде не хранится, а воссоздаётся на лету по сохранённому
 * payload формы через тот же рендер, что и при первой генерации.
 */
export function GenerationHistoryPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // `${entryId}:${format}` — какая именно кнопка сейчас скачивает, чтобы
  // не блокировать всю строку из-за соседней кнопки docx/pdf.
  const [downloading, setDownloading] = useState(null);

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

  async function download(entry, format) {
    const key = `${entry.id}:${format}`;
    setDownloading(key);
    setError('');
    try {
      const blob = await recreateGeneratedDocument(entry.id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${entry.template_name}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading(null);
    }
  }

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

              <div className="flex items-center gap-4 flex-shrink-0">
                <div className="text-right">
                  <div className="text-[13px] text-text">{e.user_username ?? '—'}</div>
                  <div className="text-[11px] text-text-muted mt-0.5">
                    {new Date(e.created_at).toLocaleString('ru-RU')}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={downloading === `${e.id}:docx`}
                    onClick={() => download(e, 'docx')}
                  >
                    {downloading === `${e.id}:docx` ? '…' : 'docx'}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={downloading === `${e.id}:pdf`}
                    onClick={() => download(e, 'pdf')}
                  >
                    {downloading === `${e.id}:pdf` ? '…' : 'pdf'}
                  </Button>
                </div>
              </div>
            </div>
          ))}
      </Card>

      <div className="text-[11px] text-text-muted mt-4 leading-snug">
        Документ воссоздаётся заново по сохранённым данным формы — если шаблон с тех пор
        изменили, результат может отличаться от исходного.
      </div>
    </div>
  );
}
