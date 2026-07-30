import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import {
  getGenerationEntry,
  listGenerationHistory,
  recreateGeneratedDocument,
} from '../api/generationHistory';
import { useAuth } from '../auth/AuthContext';
import { canViewAllGenerationHistory } from '../auth/permissions';

const FILTER_TYPES = [
  { value: 'contragent', label: 'Контрагент' },
  { value: 'nickname', label: 'Псевдоним' },
  // Фильтр по пользователю — только тем, кто видит всю историю: у top_manager
  // все записи и так его собственные, искать по себе незачем.
  { value: 'user', label: 'Пользователь', allOnly: true },
];

/**
 * "История генерации" — Admin/Director (вся история) и Top-manager (только
 * СВОИ документы, ограничение серверное по user_id — см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY / SEES_ALL_GENERATION_HISTORY). Показывает факт
 * генерации: контрагент, псевдоним, шаблон, кто сгенерировал, когда — и
 * позволяет посмотреть сам документ (этап 2): он нигде не хранится, а
 * воссоздаётся на лету по сохранённому payload формы через тот же рендер, что
 * и при первой генерации.
 *
 * Фильтр один общий, а не три отдельных поля: сначала выбирается ТИП
 * (контрагент/псевдоним/пользователь), потом вводится значение — под ним
 * ищется подстрока (см. ILIKE на бэкенде). Пока тип не выбран, поле ввода
 * не показывается — фильтровать нечем.
 */
export function GenerationHistoryPage() {
  const navigate = useNavigate();
  const { role } = useAuth();
  const seesAll = canViewAllGenerationHistory(role);
  const filterTypes = FILTER_TYPES.filter((t) => seesAll || !t.allOnly);

  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterValue, setFilterValue] = useState('');
  // `${entryId}:${format}` — какая именно кнопка сейчас скачивает, чтобы
  // не блокировать всю строку из-за соседней кнопки docx/pdf.
  const [downloading, setDownloading] = useState(null);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        setEntries(await listGenerationHistory({ filterType, filterValue: filterValue.trim() }));
        setError('');
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }, 400); // тот же дебаунс, что и в поиске контрагентов — не дёргать сервер на каждую букву

    return () => clearTimeout(timer);
  }, [filterType, filterValue]);

  async function download(entry, format) {
    const key = `${entry.id}:${format}`;
    setDownloading(key);
    setError('');
    try {
      // Имя — с сервера (Content-Disposition), собрано по титлу-снимку из
      // истории: тот же файл, что скачали в первый раз. Раньше здесь стояло
      // название шаблона, и оно расходилось с именем при генерации.
      const { blob, filename } = await recreateGeneratedDocument(entry.id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
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

  /**
   * "Открыть форму": ведёт в форму генерации того же шаблона с
   * предзаполненными данными из истории. payload забираем точечно
   * (getGenerationEntry — в списке его нет) и передаём форме через
   * navigation state, не через URL (он большой). DocFormPage разложит
   * плоский payload по полям формы (см. prefillRef там).
   *
   * Пришло на замену предпросмотру в браузере: тот конвертировал в PDF на
   * каждый клик (долго), а рядом и так есть кнопки скачивания.
   */
  async function openForm(entry) {
    setDownloading(`${entry.id}:form`);
    setError('');
    try {
      const data = await getGenerationEntry(entry.id);
      const qs = data.contragent_id ? `?contragent=${data.contragent_id}` : '';
      navigate(`/doc/${data.template_id}${qs}`, { state: { prefill: data.payload } });
      // навигация уводит со страницы — downloading сбрасывать не нужно
    } catch (e) {
      setError(e.message);
      setDownloading(null);
    }
  }

  const selectClass =
    'bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none';

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center gap-3 p-5 border-b border-border">
          <span className="text-sm font-semibold text-text mr-auto">
            История генерации
            {!seesAll && (
              <span className="text-text-muted font-normal"> · только мои документы</span>
            )}
          </span>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className={selectClass}
          >
            <option value="">Без фильтра</option>
            {filterTypes.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          {filterType && (
            <input
              autoFocus
              value={filterValue}
              onChange={(e) => setFilterValue(e.target.value)}
              placeholder="Введите значение…"
              className="bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans w-56"
            />
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-accent">{error}</div>}
        {!loading && !error && entries.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {filterType && filterValue ? 'Ничего не найдено.' : 'Документы ещё не генерировались.'}
          </div>
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
                  {e.nickname && (
                    <span className="text-text-secondary font-normal"> · {e.nickname}</span>
                  )}
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
                  {/* "Открыть форму" — вместо предпросмотра: ведёт в форму
                      генерации того же шаблона с предзаполненными данными из
                      истории. Кнопки скачивания рядом отдают готовый документ. */}
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!e.template_id || downloading === `${e.id}:form`}
                    title={e.template_id ? undefined : 'Шаблон удалён — открыть форму нечем'}
                    onClick={() => openForm(e)}
                  >
                    {downloading === `${e.id}:form` ? '…' : 'Открыть форму'}
                  </Button>
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
