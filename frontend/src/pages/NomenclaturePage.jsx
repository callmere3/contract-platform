import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { useModal } from '../modals/ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canExportNomenclature, canImportNomenclature } from '../auth/permissions';
import { listTracks } from '../api/nomenclature';

/**
 * ML Finance → «Номенклатура»: каталог треков лейбла с правообладателями,
 * долями и ставками роялти. 121 529 позиций, приехали импортом выгрузки из
 * Dista (ops/import_tracks.py).
 *
 * Экран собран по образцу того, как номенклатуру смотрят в самой Dista
 * (скриншот владельца 16.09.2026): сверху поиск, под ним таблица. Два
 * отличия от их окна сделаны сознательно:
 *
 *   - ПРАВА НЕ РАЗЛОЖЕНЫ ПО НУМЕРОВАННЫМ КОЛОНКАМ. В Dista это «Владелец
 *     авт.прав 1», «Доля(%) авт.прав 1», «Роялти(%) авт.прав 1», «Владелец
 *     авт.прав 2» и так далее — таблица растёт вправо с каждым новым
 *     правообладателем, а третий по счёту уже уезжает за край экрана. У нас
 *     право — это СТРОКА (трек × правообладатель × вид права), поэтому
 *     колонок всегда две, а строк в ячейке столько, сколько правообладателей.
 *   - ФИЛЬТРЫ СВЕРХУ, А НЕ ПАНЕЛЬЮ СЛЕВА — как на «Контрагентах» в обоих
 *     продуктах: человек ходит между этими экранами, и поиск должен быть в
 *     одном и том же месте.
 *
 * ФИЛЬТРОВ РОВНО ДВА: общий поиск и правообладатель. Выпадающий список
 * каталогов тут был и убран (17.09.2026): каталогов 502, и выбрать в таком
 * списке что-то нереально — он занимает место и создаёт видимость
 * инструмента. На сервере параметр остался, но экрану он не нужен.
 *
 * В ТАБЛИЦЕ ТОЛЬКО ТО, ПО ЧЕМУ ТРЕК ОПОЗНАЮТ: артикул, ISRC/UPC, название,
 * исполнитель и права. Всё остальное — авторы слов и музыки, альбом, жанр,
 * каталог, доли на уровне трека, дата прав — в карточке, которая открывается
 * нажатием на строку (просьба владельца 16.09.2026). Исполнитель при этом
 * ОТДЕЛЬНАЯ колонка, а не подпись под названием: по нему ищут, и колонку
 * глаз проходит сверху вниз, а подпись — нет.
 *
 * Поиск с задержкой и пагинация — как в «Контрагентах»: каталог больше базы
 * контрагентов в полтораста раз, и дёргать сервер на каждую букву тем более
 * незачем.
 */
const PAGE_SIZE = 50;

export function NomenclaturePage() {
  const [q, setQ] = useState('');
  const [owner, setOwner] = useState('');
  const [page, setPage] = useState(1);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const { openModal } = useModal();
  const { role } = useAuth();

  // Смена фильтра — назад на первую страницу: иначе, отфильтровав до десятка
  // строк, останешься на «стр. 40», где пусто.
  useEffect(() => {
    setPage(1);
  }, [q, owner]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listTracks({
        q: q.trim(),
        owner: owner.trim(),
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(data.tracks ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [q, owner, page]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  const inputClass =
    'bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans';
  const th =
    'text-left font-semibold text-[11.5px] uppercase tracking-[0.04em] text-text-muted px-4 py-3 whitespace-nowrap';
  const td = 'px-4 py-3 align-top border-t border-border';

  return (
    <div className="max-w-[1180px] mx-auto px-8 pt-12 pb-20">
      <h1 className="text-[26px] font-extrabold tracking-[-0.02em] text-text mb-1.5">
        Номенклатура
      </h1>
      <p className="text-[13.5px] text-text-secondary mb-6 max-w-[620px] leading-relaxed">
        Треки и их правообладатели: у кого какая доля и по какой ставке роялти. Нажмите на
        строку — откроется карточка трека со всеми полями выгрузки.
      </p>

      <Card>
        <div className="flex flex-wrap gap-3 p-5 border-b border-border">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Артикул, ISRC/UPC, название или исполнитель…"
            className={`flex-1 min-w-[280px] ${inputClass}`}
          />
          {/* Правообладатель — поле ввода, а не список: их 729, и такой
              список листают дольше, чем набирают фамилию. */}
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="Правообладатель"
            className={`w-[200px] ${inputClass}`}
          />
          {/* Импорт/экспорт стоит там же, где на «Контрагентах». Экспорт
              выгружает ровно то, что видно при текущем фильтре, — поэтому
              фильтры и передаются внутрь. */}
          {(canExportNomenclature(role) || canImportNomenclature(role)) && (
            <Button
              variant="primary"
              size="sm"
              onClick={() =>
                openModal('nomenclatureImportExport', {
                  filters: { q: q.trim(), owner: owner.trim() },
                  onImported: load,
                })
              }
            >
              Импорт/экспорт
            </Button>
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-danger">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-4 text-[13px] text-text-muted">
            {q || owner ? 'Ничего не найдено.' : 'Каталог пуст.'}
          </div>
        )}

        {/* Единственная настоящая <table> в проекте — и по делу: колонки
            разной ширины и зависят от содержимого (название тянется, артикул
            нет), а сетка из div'ов такое держит только с фиксированными
            долями. Обёртка со скроллом обязательна: на узком экране таблица
            должна уезжать вбок, а не схлопывать колонки. */}
        {!loading && !error && items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-[13px]">
              <thead>
                <tr>
                  <th className={th}>Артикул</th>
                  <th className={th}>ISRC / UPC</th>
                  <th className={th}>Наименование</th>
                  <th className={th}>Исполнитель</th>
                  <th className={th}>Смежные права</th>
                  <th className={th}>Авторские права</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => openModal('trackCard', { trackId: t.id })}
                    className="cursor-pointer hover:bg-surface-hover"
                  >
                    <td className={`${td} tabular-nums text-text-secondary whitespace-nowrap`}>
                      {t.sku}
                    </td>
                    <td
                      className={`${td} font-mono text-[12px] text-text-secondary whitespace-nowrap`}
                    >
                      {t.code || '—'}
                    </td>
                    {/* Название и исполнитель — одинаково важные опознавательные
                        знаки трека, поэтому и выглядят одинаково (просьба
                        владельца 17.09.2026). Приглушённый исполнитель читался
                        как пояснение к названию, хотя ищут чаще именно по нему. */}
                    <td className={`${td} font-semibold text-text`}>{t.title}</td>
                    <td className={`${td} font-semibold text-text`}>{t.artist || '—'}</td>
                    <td className={td}>
                      <RightsCell owners={t.rights?.related ?? []} />
                    </td>
                    <td className={td}>
                      <RightsCell owners={t.rights?.author ?? []} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && !error && total > 0 && (
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-t border-border">
            <span className="text-[13px] text-text-muted">
              {total > PAGE_SIZE ? `Показаны ${from}–${to} из ${total}` : `Всего: ${total}`}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-2.5">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ← Назад
                </Button>
                <span className="text-[13px] text-text-muted tabular-nums">
                  Стр. {page} из {totalPages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Вперёд →
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>

      <div className="text-[11px] text-text-muted mt-4 leading-snug max-w-[620px]">
        Доля — это часть прав, которой распоряжается лейбл; у кавера наших авторских может не
        быть вовсе, и сумма долей меньше 100% здесь норма. Роялти — та часть вознаграждения,
        что уходит правообладателю, и она своя у каждой строки прав. Каталог обновляется
        выгрузкой из Dista.
      </div>
    </div>
  );
}

/**
 * Правообладатели одного вида прав: кто, с какой долей и по какой ставке.
 *
 * Пусто — это осмысленное состояние («наших долей нет», типичный кавер),
 * поэтому пишем словами, а не ставим прочерк: прочерк читается как «данные не
 * заполнены», а это противоположный случай.
 */
function RightsCell({ owners }) {
  if (!owners.length) {
    return <span className="text-text-muted italic">наших долей нет</span>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      {owners.map((o, i) => (
        <span key={`${o.owner}-${i}`}>
          <span className="block text-text leading-snug">{o.owner}</span>
          {/* Доля и роялти — КАЖДОЕ СВОЕЙ СТРОКОЙ. Одной строкой «доля 100% ·
              роялти 70%» в узкую колонку не влезало, и перенос отрывал от неё
              хвост: «70%» оставалось болтаться отдельной строчкой без
              подписи. nowrap не даёт разорвать уже сами пары. */}
          <span className="block text-[12px] text-text-muted tabular-nums whitespace-nowrap">
            доля {o.share ?? '—'}%
          </span>
          <span className="block text-[12px] text-text-muted tabular-nums whitespace-nowrap">
            роялти {o.royalty ?? '—'}%
          </span>
        </span>
      ))}
    </div>
  );
}
