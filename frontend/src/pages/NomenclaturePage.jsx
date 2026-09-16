import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { UnderConstruction } from '../components/ui/UnderConstruction';

/**
 * ML Finance → «Номенклатура»: каталог треков с правами. Пока заглушка —
 * настоящий каталог живёт в Dista (Firebird), у нас его ещё нет.
 *
 * Экран собран по образцу того, как номенклатуру смотрят в самой Dista
 * (скриншот владельца 16.09.2026): сверху поиск по артикулу/ISRC/названию, под
 * ним таблица треков. Два отличия от их окна сделаны сознательно:
 *
 *   - ПРАВА НЕ РАЗЛОЖЕНЫ ПО НУМЕРОВАННЫМ КОЛОНКАМ. В Dista это «Владелец
 *     авт.прав 1», «Доля(%) авт.прав 1», «Роялти(%) авт.прав 1», «Владелец
 *     авт.прав 2» и так далее — таблица растёт вправо с каждым новым
 *     правообладателем, а третий по счёту просто не влезает. У нас право —
 *     это СТРОКА (трек × правообладатель × вид права), поэтому в ячейке
 *     столько строк, сколько правообладателей, и колонок всегда две: смежные
 *     и авторские. Это та же модель, что описана в брейншторме по расчёту
 *     роялти, и менять её ради похожести на чужое окно незачем.
 *   - ФИЛЬТРЫ СВЕРХУ, А НЕ ПАНЕЛЬЮ СЛЕВА — как на «Контрагентах» в обоих
 *     продуктах: человек ходит между этими экранами, и поиск должен быть в
 *     одном и том же месте. Там же, справа от фильтров, стоит и
 *     «Импорт/экспорт» — два справочника рядом, и пополняют их одинаково.
 *
 * В ТАБЛИЦЕ ТОЛЬКО ТО, ПО ЧЕМУ ТРЕК ОПОЗНАЮТ: артикул, ISRC/UPC, название,
 * исполнитель и права. Автор слов/музыки и альбом убраны отсюда (просьба
 * владельца 16.09.2026) — они пойдут в карточку трека, которая откроется
 * нажатием на строку. Исполнитель при этом ОТДЕЛЬНАЯ колонка, а не вторая
 * строчка под названием: по нему ищут и им сортируют, а подпись ни
 * отсортировать, ни выровнять глазом по столбцу нельзя. В демо-строках автор
 * и альбом оставлены — они понадобятся карточке, и выбрасывать их, чтобы
 * через неделю вписывать заново, незачем.
 *
 * Строки ниже — демонстрационные (взяты из того же скриншота), в них видно
 * главное свойство каталога: доли считаются ОТДЕЛЬНО по видам прав, и у
 * кавера наших авторских может не быть вовсе. Когда каталог появится
 * по-настоящему, снимается UnderConstruction и DEMO_TRACKS меняется на
 * запрос — разметка таблицы уже настоящая.
 */

// author и album в таблицу не выводятся — они для карточки трека (см. выше).
const DEMO_TRACKS = [
  {
    sku: '7231772',
    code: 'FR2X42308142',
    title: 'Бедный поэт',
    artist: 'Bakr',
    author: 'Shabdanbek Ergeshov',
    album: '—',
    since: '01.01.2000',
    related: [{ owner: 'TURAN MEDIA', share: 100, royalty: 80 }],
    authors: [{ owner: 'TURAN MEDIA', share: 100, royalty: 80 }],
  },
  {
    sku: '7242249',
    code: 'FRX872269820',
    title: '808 PROBLEM',
    artist: 'SIDODGI DAVLAT',
    author: 'Andrey Zolotuhin',
    album: '808 PROBLEM',
    since: '01.01.2000',
    related: [{ owner: 'ИП Штанов Владислав Игоревич', share: 100, royalty: 80 }],
    authors: [
      { owner: 'ИП Погорельских', share: 50, royalty: 80 },
      { owner: 'ИП Штанов Владислав Игоревич', share: 50, royalty: 80 },
    ],
  },
  {
    sku: '7202276',
    code: 'FRX202276214',
    title: 'Autumn In My Soul',
    artist: 'ONEX1NE',
    author: 'Евгений Дмитриев',
    album: '—',
    since: '01.01.2000',
    related: [{ owner: 'ООО Густ Мьюзик', share: 100, royalty: 85 }],
    authors: [{ owner: 'ООО Густ Мьюзик', share: 100, royalty: 85 }],
  },
  {
    sku: '7220988',
    code: 'FR2X41809203',
    title: 'Avokado',
    artist: 'LOVANDA',
    author: 'LOVANDA',
    album: 'Avokado',
    since: '01.01.2000',
    related: [{ owner: 'ИП Погорельских', share: 100, royalty: 80 }],
    authors: [{ owner: 'ИП Погорельских', share: 100, royalty: 80 }],
  },
  {
    sku: '7221020',
    code: 'FR59R1898158',
    title: 'Suck My Electro',
    artist: 'Taly & Smith',
    author: 'Taly & Smith',
    album: 'Bomber',
    since: '01.01.2000',
    related: [{ owner: 'ИП Погорельских', share: 100, royalty: 80 }],
    authors: [{ owner: 'ИП Погорельских', share: 100, royalty: 80 }],
  },
  {
    // Кавер: фонограмма наша, произведение чужое. Авторских долей нет — и это
    // не пробел в данных, а нормальное состояние (см. брейншторм, §3).
    sku: '7242236',
    code: 'SMRUS0052784',
    title: 'Тупая тёлка',
    artist: 'Masha Hima',
    author: 'Мария Колесникова',
    album: 'Сборник',
    since: '01.01.2000',
    related: [{ owner: 'ИП Штанов Владислав Игоревич', share: 100, royalty: 80 }],
    authors: [],
  },
];

const DEMO_OWNERS = ['ИП Погорельских', 'ИП Штанов Владислав Игоревич', 'ООО Густ Мьюзик', 'TURAN MEDIA'];
const DEMO_ALBUMS = ['808 PROBLEM', 'Avokado', 'Bomber', 'Сборник'];

export function NomenclaturePage() {
  const selectClass =
    'bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none';
  const th =
    'text-left font-semibold text-[11.5px] uppercase tracking-[0.04em] text-text-muted px-4 py-3 whitespace-nowrap';
  const td = 'px-4 py-3 align-top border-t border-border';

  return (
    <div className="max-w-[1180px] mx-auto px-8 pt-12 pb-20">
      <UnderConstruction
        align="left"
        note="Так этот раздел будет выглядеть. Каталог пока живёт в Dista — треки и доли сюда ещё не перенесены, в таблице показаны демонстрационные строки."
      >
        <h1 className="text-[26px] font-extrabold tracking-[-0.02em] text-text mb-1.5">
          Номенклатура
        </h1>
        <p className="text-[13.5px] text-text-secondary mb-6 max-w-[620px] leading-relaxed">
          Треки и их правообладатели: у кого какая доля и по какой ставке роялти. Отсюда
          квартальный отчёт будет знать, кому сколько причитается. Пополняется импортом из
          Dista — файлом, как база контрагентов.
        </p>

        <Card>
          <div className="flex flex-wrap gap-3 p-5 border-b border-border">
            <input
              defaultValue=""
              placeholder="Артикул, ISRC/UPC, название или исполнитель…"
              className="flex-1 min-w-[280px] bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
            />
            <select defaultValue="" className={selectClass}>
              <option value="">Все правообладатели</option>
              {DEMO_OWNERS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <select defaultValue="" className={selectClass}>
              <option value="">Все альбомы</option>
              {DEMO_ALBUMS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-[13px] text-text-secondary select-none">
              <input type="checkbox" defaultChecked={false} />
              Показывать архивные
            </label>
            {/* Импорт/экспорт стоит там же, где на «Контрагентах», и называется
                так же: два справочника, и пополняют их одним движением —
                выгрузили Excel, поправили, залили обратно. Для номенклатуры
                импорт вдобавок ежедневный (десятки новых треков и правки
                долей), так что кнопка здесь не «на будущее», а главный способ
                наполнения каталога.

                Кому её показывать — вопрос открытый: вкладка сейчас видна
                admin и director вместе со всем ML Finance, а треки, возможно,
                будет заливать кто-то ещё, и пускать его к суммам выплат ради
                этого не хочется. Решится вместе с правом на импорт (см.
                брейншторм по номенклатуре, §9). */}
            <Button variant="primary" size="sm" disabled>
              Импорт/экспорт
            </Button>
          </div>

          {/* Единственная настоящая <table> в проекте — и по делу: колонки здесь
              разной ширины и зависят от содержимого (название тянется,
              артикул нет), а сетка из div'ов такое держит только с
              фиксированными долями. Обёртка со скроллом обязательна: колонок
              семь, и на узком экране таблица должна уезжать вбок, а не
              схлопывать колонки. */}
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
                  <th className={th}>Права с</th>
                </tr>
              </thead>
              <tbody>
                {DEMO_TRACKS.map((t) => (
                  <tr key={t.sku}>
                    <td className={`${td} tabular-nums text-text-secondary whitespace-nowrap`}>
                      {t.sku}
                    </td>
                    <td className={`${td} font-mono text-[12px] text-text-secondary whitespace-nowrap`}>
                      {t.code}
                    </td>
                    <td className={`${td} font-semibold text-text`}>{t.title}</td>
                    <td className={`${td} text-text-secondary`}>{t.artist}</td>
                    <td className={td}>
                      <RightsCell owners={t.related} />
                    </td>
                    <td className={td}>
                      <RightsCell owners={t.authors} />
                    </td>
                    <td className={`${td} text-text-muted whitespace-nowrap`}>{t.since}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-5 py-4 border-t border-border text-[13px] text-text-muted">
            Показаны 6 строк · в каталоге Dista их больше 100 000 · нажатие на строку откроет
            карточку трека: альбом, авторы слов и музыки, история долей
          </div>
        </Card>
      </UnderConstruction>

      <div className="text-[11px] text-text-muted mt-6 leading-snug max-w-[620px]">
        Доля — это часть прав, которой распоряжается лейбл; у кавера наших авторских может не
        быть вовсе, и сумма долей меньше 100% здесь норма. Роялти — то, какая часть
        вознаграждения уходит правообладателю, и она своя у каждой строки прав.
      </div>
    </div>
  );
}

/**
 * Правообладатели одного вида прав на трек: кто, с какой долей и по какой
 * ставке. Пусто — это осмысленное состояние («наших долей нет», типичный
 * кавер), поэтому пишем словами, а не ставим прочерк: прочерк читается как
 * «данные не заполнены», а это совсем другой случай.
 */
function RightsCell({ owners }) {
  if (owners.length === 0) {
    return <span className="text-text-muted italic">наших долей нет</span>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      {owners.map((o) => (
        <span key={o.owner}>
          <span className="block text-text leading-snug">{o.owner}</span>
          <span className="block text-[12px] text-text-muted tabular-nums">
            доля {o.share}% · роялти {o.royalty}%
          </span>
        </span>
      ))}
    </div>
  );
}
