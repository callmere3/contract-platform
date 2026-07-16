import { useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { listGenerationHistory, recreateGeneratedDocument } from '../api/generationHistory';

const FILTER_TYPES = [
  { value: 'contragent', label: 'Контрагент' },
  { value: 'nickname', label: 'Псевдоним' },
  { value: 'user', label: 'Пользователь' },
];

/** Название шаблона уходит в <title> вкладки предпросмотра — это HTML, а не
 *  JSX, экранирование React здесь не работает. Названия задаёт админ, но
 *  собирать HTML из непроверенной строки всё равно нельзя. */
function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}

/**
 * "История генерации" — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации: контрагент,
 * псевдоним, шаблон, кто сгенерировал, когда — и позволяет посмотреть сам
 * документ (этап 2): он нигде не хранится, а воссоздаётся на лету по
 * сохранённому payload формы через тот же рендер, что и при первой генерации.
 *
 * Фильтр один общий, а не три отдельных поля: сначала выбирается ТИП
 * (контрагент/псевдоним/пользователь), потом вводится значение — под ним
 * ищется подстрока (см. ILIKE на бэкенде). Пока тип не выбран, поле ввода
 * не показывается — фильтровать нечем.
 */
export function GenerationHistoryPage() {
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

  /**
   * Открывает документ в новой вкладке — встроенным просмотрщиком браузера,
   * без скачивания.
   *
   * Всегда PDF, даже если документ генерировали в .docx: показать .docx
   * браузер не умеет, встроенный просмотрщик есть только у PDF.
   *
   * ПОРЯДОК ВАЖЕН. Вкладку открываем СРАЗУ по клику, до await: если позвать
   * window.open() после конвертации, браузер уже не считает вызов жестом
   * пользователя и блокирует вкладку как всплывающее окно. Поэтому сначала
   * открываем пустую с заглушкой, а документ досылаем в неё, когда он готов.
   *
   * Прямую ссылку на эндпоинт сюда не подставить: он закрыт JWT, а вкладка
   * не отправит заголовок Authorization — получили бы 401. Поэтому качаем
   * через apiFetch (он приложит токен и обновит его при 401) и отдаём
   * вкладке blob:-ссылку.
   */
  async function preview(entry) {
    const key = `${entry.id}:preview`;
    setDownloading(key);
    setError('');

    const tab = window.open('', '_blank');
    if (!tab) {
      setError('Браузер заблокировал новую вкладку — разрешите всплывающие окна для этого сайта.');
      setDownloading(null);
      return;
    }
    tab.document.write(
      '<title>Готовим документ…</title>' +
        '<p style="font:14px system-ui,sans-serif;color:#666;padding:24px">' +
        'Собираем документ и конвертируем в PDF…</p>',
    );

    try {
      const blob = await recreateGeneratedDocument(entry.id, 'pdf');
      const url = URL.createObjectURL(blob);
      // Не location.replace(url), а обёртка с iframe — только ради заголовка
      // вкладки: у blob-ссылки его нет, и во вкладке светился бы UUID вместо
      // названия документа. Когда открыто несколько документов сразу, это
      // разница между "какой из них какой" и вкладками-близнецами.
      tab.document.open();
      tab.document.write(
        `<title>${escapeHtml(entry.template_name)}</title>` +
          '<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>' +
          `<iframe src="${url}"></iframe>`,
      );
      tab.document.close();
      // URL сознательно НЕ освобождаем: он нужен открытой вкладке. Браузер
      // уберёт его сам, когда закроется или перезагрузится эта страница —
      // blob живёт ровно столько, сколько документ, который его создал.
    } catch (e) {
      tab.close();
      setError(e.message);
    } finally {
      setDownloading(null);
    }
  }

  const selectClass =
    'bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none';

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center gap-3 p-5 border-b border-border">
          <span className="text-sm font-semibold text-text mr-auto">История генерации</span>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className={selectClass}
          >
            <option value="">Без фильтра</option>
            {FILTER_TYPES.map((t) => (
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
                  {/* Просмотр — всегда PDF, открывается в новой вкладке
                      (см. preview() выше). Кнопки скачивания рядом остаются,
                      они отдают оба формата. */}
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={downloading === `${e.id}:preview`}
                    onClick={() => preview(e)}
                  >
                    {downloading === `${e.id}:preview` ? '…' : 'Просмотр'}
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
