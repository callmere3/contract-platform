import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, ModalAction } from '../components/ui/Modal';
import { PencilIcon, TrashIcon } from '../components/ui/icons';
import { ComboCell } from '../components/ui/ComboCell';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canEditNomenclature } from '../auth/permissions';
import {
  fetchOwnerSuggestions,
  fetchTrackCard,
  formatPercent,
  updateTrack,
} from '../api/nomenclature';

/**
 * Карточка трека: ВСЕ поля выгрузки Dista — и правка их же.
 *
 * В таблице каталога полей ровно столько, сколько нужно, чтобы трек
 * опознать, — остальное живёт здесь: авторы слов и музыки, альбом, жанр,
 * каталог, доли на уровне трека и дата прав.
 *
 * АВТОРСКИЕ ПРАВА ВСЕГДА ПЕРВЫМИ, смежные вторыми (просьба владельца
 * 17.09.2026) — здесь и в таблице каталога один и тот же порядок: человек,
 * который ходит из списка в карточку и обратно, не должен каждый раз
 * перечитывать подписи, чтобы понять, где чьи доли.
 *
 * ДОЛИ ПОКАЗАНЫ ДВАЖДЫ, И ЭТО НЕ ОШИБКА ВЁРСТКИ. Сверху — «Доля авторских
 * прав» и «Доля смежных прав» из выгрузки, то есть доля на уровне трека;
 * ниже, в блоках прав, — доли конкретных правообладателей. Эти числа иногда
 * противоречат друг другу: у 45 617 треков доля смежных равна нулю, а
 * владелец смежных при этом указан со стопроцентной долей. Показать одно
 * значило бы решить за владельца, какое из них правда.
 *
 * ПРАВКА (17.09.2026). Карандаш в шапке открывает ту же карточку полями
 * ввода: метаданные, состав правообладателей, доли и ставки. Ключевое здесь —
 * СВЕРКА ДОЛЕЙ СО СПРАВОЧНЫМИ: она считается на каждый набранный символ и
 * показана прямо над кнопкой сохранения, потому что сервер несходящуюся
 * карточку не примет, и узнавать об этом в момент нажатия «Сохранить» — это
 * узнавать поздно. Поправить можно с обеих сторон: и долю правообладателя, и
 * справочную долю трека («Взять сумму» ставит её равной сумме долей) — ровно
 * поэтому обе живут в одной форме.
 *
 * Данные тянутся по track_id, а не приходят из строки списка: в списке нет ни
 * альбома, ни авторов, ни каталога — только то, что нарисовано в таблице.
 */
const AUTHOR = 'author';
const RELATED = 'related';

// Порядок блоков — один на карточку и на форму правки, чтобы не разъехались.
const RIGHT_BLOCKS = [
  { type: AUTHOR, title: 'Авторские права', field: 'share_author' },
  { type: RELATED, title: 'Смежные права', field: 'share_related' },
];

export function TrackCardModal({ trackId, level, isTop, onChanged }) {
  const { closeModal } = useModal();
  const { role } = useAuth();

  const [card, setCard] = useState(null);
  const [error, setError] = useState('');

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');
  // Незнакомые правообладатели: сервер отвечает 409 со списком и подсказками,
  // и это не отказ, а вопрос — заводить ли карточки. Ответ уходит вторым
  // запросом с createMissingOwners.
  const [unknownOwners, setUnknownOwners] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchTrackCard(trackId)
      .then((data) => !cancelled && setCard(data))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [trackId]);

  const startEdit = () => {
    setForm(toForm(card));
    setSaveError('');
    setUnknownOwners(null);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setForm(null);
    setSaveError('');
    setUnknownOwners(null);
  };

  async function save(createMissingOwners = false) {
    setBusy(true);
    setSaveError('');
    try {
      const saved = await updateTrack(trackId, toPayload(form), { createMissingOwners });
      setCard(saved);
      setEditing(false);
      setForm(null);
      setUnknownOwners(null);
      onChanged?.();
    } catch (e) {
      // 409 с кодом — это вопрос про незнакомые имена, а не ошибка ввода.
      if (e.status === 409 && e.detail?.code === 'unknown_owners') {
        setUnknownOwners(e.detail.owners ?? []);
      } else {
        setSaveError(e.message);
      }
    } finally {
      setBusy(false);
    }
  }

  const canEdit = canEditNomenclature(role);

  return (
    <Modal
      title={card ? card.title : 'Трек'}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={editing ? 760 : 640}
      actions={
        card &&
        canEdit &&
        !editing && (
          <ModalAction icon={<PencilIcon />} title="Редактировать" onClick={startEdit} />
        )
      }
      footer={
        editing && (
          <>
            <Button variant="secondary" size="sm" onClick={cancelEdit} disabled={busy}>
              Отмена
            </Button>
            <Button variant="primary" size="sm" onClick={() => save(false)} disabled={busy}>
              {busy ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </>
        )
      }
    >
      {!card && !error && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}

      {card && !editing && <CardView card={card} />}

      {card && editing && form && (
        <TrackForm
          form={form}
          setForm={setForm}
          saveError={saveError}
          unknownOwners={unknownOwners}
          onConfirmOwners={() => save(true)}
          onReplaceOwner={(name, suggestion) => {
            setForm((f) => ({
              ...f,
              rights: f.rights.map((r) => (r.owner === name ? { ...r, owner: suggestion } : r)),
            }));
            setUnknownOwners(null);
          }}
          busy={busy}
        />
      )}
    </Modal>
  );
}

/* ------------------------------------------------------------------ чтение */

function CardView({ card }) {
  return (
    <>
      <table className="w-full text-sm mb-6">
        <tbody>
          <Row label="Артикул" value={card.sku} mono />
          <Row label="Код / ISRC / UPC" value={card.code} mono />
          <Row label="Исполнитель" value={card.artist} />
          <Row label="Автор слов/музыки" value={card.authors} />
          <Row label="Альбом" value={card.album} />
          <Row label="Жанр" value={card.genre} />
          <Row label="Каталог" value={card.catalog} />
          <Row label="Доля авторских прав" value={percentOrDash(card.share_author)} />
          <Row label="Доля смежных прав" value={percentOrDash(card.share_related)} />
          <Row label="Роялти" value={percentOrDash(card.royalty_percent)} />
          <Row label="Дата прав" value={russianDate(card.rights_since)} />
        </tbody>
      </table>

      {/* Два блока, а не одна таблица прав: смежные и авторские независимы, и
          складывать их доли между собой нельзя — у кавера фонограмма своя, а
          произведение чужое.

          Подписи «на фонограмму» и «на произведение» убраны (просьба
          владельца 17.09.2026): в карточку смотрят те, кто и так знает
          разницу, а объяснять её каждый раз — шум. */}
      {RIGHT_BLOCKS.map((block) => (
        <RightsBlock
          key={block.type}
          title={block.title}
          owners={block.type === AUTHOR ? card.rights.author : card.rights.related}
        />
      ))}

      {/* Откуда и когда приехала строка, в карточке не пишем: это нужно при
          разборе импорта, а не при взгляде на трек. Архив — другое дело: это
          состояние самого трека. */}
      {card.archived && (
        <div className="text-[11px] text-text-muted mt-5 leading-snug">
          Трек в архиве: его нет в последней выгрузке.
        </div>
      )}
    </>
  );
}

function Row({ label, value, mono }) {
  return (
    <tr>
      <td className="text-text-secondary py-1.5 whitespace-nowrap pr-4 align-top">{label}</td>
      <td className={`text-right py-1.5 text-text ${mono ? 'font-mono text-[13px]' : ''}`}>
        {value || '—'}
      </td>
    </tr>
  );
}

/** Правообладатели одного вида прав. Пусто — осмысленный ответ, не пробел. */
function RightsBlock({ title, owners }) {
  return (
    <div className="mb-5 last:mb-0">
      <div className="text-[13px] font-semibold text-text mb-2">{title}</div>
      {owners.length === 0 ? (
        <div className="text-[13px] text-text-muted italic">
          Наших долей нет — такое бывает у каверов и ремиксов.
        </div>
      ) : (
        <div className="border border-border rounded-card overflow-hidden">
          {owners.map((o, i) => (
            <div
              key={`${o.owner}-${i}`}
              className="flex items-center justify-between gap-4 px-3.5 py-2.5 border-b border-border last:border-b-0"
            >
              <span className="text-[13.5px] text-text min-w-0 truncate">{o.owner}</span>
              <span className="text-[12.5px] text-text-muted tabular-nums whitespace-nowrap">
                доля {formatPercent(o.share)} · роялти {formatPercent(o.royalty)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ правка */

function TrackForm({
  form,
  setForm,
  saveError,
  unknownOwners,
  onConfirmOwners,
  onReplaceOwner,
  busy,
}) {
  const { ownerOptions, onOwnerInput } = useOwnerOptions();

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const setRight = (key, field, value) =>
    setForm((f) => ({
      ...f,
      rights: f.rights.map((r) => (r.key === key ? { ...r, [field]: value } : r)),
    }));

  const addRight = (type) =>
    setForm((f) => ({
      ...f,
      rights: [...f.rights, { key: newKey(), right_type: type, owner: '', share: '', royalty: '' }],
    }));

  const removeRight = (key) =>
    setForm((f) => ({ ...f, rights: f.rights.filter((r) => r.key !== key) }));

  return (
    <>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 mb-6">
        <Field label="Артикул" value={form.sku} onChange={set('sku')} mono />
        <Field label="Код / ISRC / UPC" value={form.code} onChange={set('code')} mono />
        <Field label="Наименование" value={form.title} onChange={set('title')} />
        <Field label="Исполнитель" value={form.artist} onChange={set('artist')} />
        <Field label="Автор слов/музыки" value={form.authors} onChange={set('authors')} />
        <Field label="Альбом" value={form.album} onChange={set('album')} />
        <Field label="Жанр" value={form.genre} onChange={set('genre')} />
        <Field label="Каталог" value={form.catalog} onChange={set('catalog')} />
        <Field
          label="Дата прав"
          value={form.rights_since}
          onChange={set('rights_since')}
          type="date"
        />
        <Field label="Роялти, %" value={form.royalty_percent} onChange={set('royalty_percent')} />
        <Field
          label="Доля авторских прав, %"
          value={form.share_author}
          onChange={set('share_author')}
        />
        <Field
          label="Доля смежных прав, %"
          value={form.share_related}
          onChange={set('share_related')}
        />
      </div>

      {RIGHT_BLOCKS.map((block) => (
        <RightsEditor
          key={block.type}
          title={block.title}
          rights={form.rights.filter((r) => r.right_type === block.type)}
          declared={form[block.field]}
          onDeclared={set(block.field)}
          onChange={setRight}
          onOwnerInput={onOwnerInput}
          ownerOptions={ownerOptions}
          onAdd={() => addRight(block.type)}
          onRemove={removeRight}
        />
      ))}

      {unknownOwners && (
        <div className="mt-5 border border-border rounded-card p-4">
          <div className="text-[13px] font-semibold text-text mb-1.5">
            В базе нет таких контрагентов
          </div>
          <div className="text-[12.5px] text-text-secondary mb-3 leading-relaxed">
            Право должно ссылаться на карточку — иначе деньги по нему не с кем свести. Заведём
            пустые карточки (титл и больше ничего, заполняются в ML Docs) или поправим имя.
          </div>
          {unknownOwners.map((item) => (
            <div key={item.name} className="flex items-center gap-3 mb-2 last:mb-3">
              <span className="text-[13px] text-text min-w-0 truncate">{item.name}</span>
              {item.suggestion && (
                <button
                  type="button"
                  onClick={() => onReplaceOwner(item.name, item.suggestion)}
                  className="text-[12.5px] text-accent bg-transparent border-0 cursor-pointer p-0 font-sans text-left"
                >
                  может быть, это «{item.suggestion}»?
                </button>
              )}
            </div>
          ))}
          <Button variant="secondary" size="sm" onClick={onConfirmOwners} disabled={busy}>
            {busy ? 'Сохраняем…' : 'Завести карточки и сохранить'}
          </Button>
        </div>
      )}

      {saveError && <div className="text-[13px] text-danger mt-4">{saveError}</div>}
    </>
  );
}

/**
 * Строки прав одного вида плюс сверка со справочной долей.
 *
 * Сверка стоит ПОД строками, а не над ними: сначала человек видит, из чего
 * складывается сумма, и только потом — сходится ли она. Наоборот читалось бы
 * как приговор до предъявления дела.
 */
function RightsEditor({
  title,
  rights,
  declared,
  onDeclared,
  onChange,
  onOwnerInput,
  ownerOptions,
  onAdd,
  onRemove,
}) {
  const total = rights.reduce((acc, r) => acc + (toNumber(r.share) ?? 0), 0);
  const want = toNumber(declared);
  const matches = want !== null && cents(total) === cents(want);

  return (
    <div className="mb-5">
      <div className="text-[13px] font-semibold text-text mb-2">{title}</div>

      {rights.map((right) => (
        <div key={right.key} className="flex items-end gap-2.5 mb-2">
          <div className="flex-1 min-w-0">
            <Field
              label="Правообладатель"
              value={right.owner}
              onChange={(v) => {
                onChange(right.key, 'owner', v);
                onOwnerInput(v);
              }}
              options={(ownerOptions ?? []).map((o) => o.title)}
            />
          </div>
          <div className="w-[92px]">
            <Field
              label="Доля, %"
              value={right.share}
              onChange={(v) => onChange(right.key, 'share', v)}
            />
          </div>
          <div className="w-[92px]">
            <Field
              label="Роялти, %"
              value={right.royalty}
              onChange={(v) => onChange(right.key, 'royalty', v)}
            />
          </div>
          <button
            type="button"
            onClick={() => onRemove(right.key)}
            title="Убрать правообладателя"
            aria-label="Убрать правообладателя"
            className="w-9 h-9 mb-0.5 rounded-input border border-border flex items-center justify-center text-danger bg-transparent cursor-pointer"
          >
            <TrashIcon size={16} />
          </button>
        </div>
      ))}

      <div className="flex items-center justify-between gap-4 mt-2.5">
        <button
          type="button"
          onClick={onAdd}
          className="text-[12.5px] text-accent bg-transparent border-0 p-0 cursor-pointer font-sans"
        >
          + правообладатель
        </button>

        {/* СВЕРКА С ДОЛЕЙ УРОВНЯ ТРЕКА. Считается на каждый символ: сервер
            несходящуюся карточку не примет, и узнать об этом надо до нажатия
            «Сохранить», а не после. «Взять сумму» правит справочную долю —
            вторая сторона того же равенства, и у 45 617 исторических треков
            неверна именно она (общая доля смежных 0 при владельце со 100%). */}
        <div className="text-[12.5px] tabular-nums text-right">
          <span className={matches ? 'text-text-muted' : 'text-danger'}>
            у правообладателей {trim(total)}% · справочная{' '}
            {want === null ? 'не заполнена' : `${trim(want)}%`}
          </span>
          {!matches && (
            <button
              type="button"
              onClick={() => onDeclared(trim(total))}
              className="ml-2 text-accent bg-transparent border-0 p-0 cursor-pointer font-sans text-[12.5px]"
            >
              взять сумму
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Подсказки по правообладателям — ОДИН СПИСОК НА ВСЮ ФОРМУ, а не по списку на
 * строку: набирают всегда в одном поле, в том, где стоит курсор, и держать
 * несколько одинаковых списков значило бы несколько раз спрашивать сервер об
 * одном и том же.
 *
 * Список приходит с сервера (титлы карточек контрагентов) и обновляется по
 * мере набора: их 729, и отдавать всё разом незачем. Именно КАРТОЧКИ, а не
 * имена из каталога: право должно получить ссылку, а имя без карточки
 * приведёт лишь к вопросу «завести?».
 */
function useOwnerOptions() {
  const [ownerOptions, setOwnerOptions] = useState([]);
  const timer = useRef(null);

  // С задержкой, как поиск на страницах: человек набирает фамилию буква за
  // буквой, и дёргать сервер на каждую незачем.
  const onOwnerInput = useCallback((value) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      fetchOwnerSuggestions(value)
        .then((data) => setOwnerOptions(data.owners ?? []))
        // Молча: подсказки — удобство, и их отсутствие не повод пугать
        // человека красной строкой посреди формы.
        .catch(() => setOwnerOptions([]));
    }, 250);
  }, []);

  useEffect(() => {
    onOwnerInput('');
    return () => clearTimeout(timer.current);
  }, [onOwnerInput]);

  return { ownerOptions, onOwnerInput };
}

function Field({ label, value, onChange, type = 'text', mono = false, options }) {
  const control = `w-full bg-input-bg border border-border rounded-input px-3 py-2 text-[13.5px] text-text outline-none font-sans ${
    mono ? 'font-mono' : ''
  }`;
  return (
    <label className="block">
      <span className="block text-[12px] text-text-secondary mb-1">{label}</span>
      {/* ПОДСКАЗКИ — НАШИМ комбобоксом, а не браузерным `datalist` (правка
          18.09.2026): тот выглядит системным окном, открывается через раз и
          ничем не показывает, что подсказки вообще есть. Компонент общий с
          колонкой «Исполнитель» в форме генерации. */}
      {options ? (
        <ComboCell
          value={value}
          options={options}
          onChange={onChange}
          arrowLabel={`Показать подсказки: ${label}`}
          inputClassName={`${control} pr-6`}
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={control}
        />
      )}
    </label>
  );
}

/* ----------------------------------------------------------------- утилиты */

function toForm(card) {
  const rights = [
    ...card.rights.author.map((r) => ({ ...r, right_type: AUTHOR })),
    ...card.rights.related.map((r) => ({ ...r, right_type: RELATED })),
  ].map((r) => ({
    key: newKey(),
    right_type: r.right_type,
    owner: r.owner ?? '',
    share: r.share ?? '',
    royalty: r.royalty ?? '',
  }));

  return {
    sku: card.sku ?? '',
    code: card.code ?? '',
    title: card.title ?? '',
    artist: card.artist ?? '',
    authors: card.authors ?? '',
    album: card.album ?? '',
    genre: card.genre ?? '',
    catalog: card.catalog ?? '',
    share_author: card.share_author ?? '',
    share_related: card.share_related ?? '',
    royalty_percent: card.royalty_percent ?? '',
    // С сервера дата приходит как ГГГГ-ММ-ДД — ровно то, что понимает
    // <input type="date">.
    rights_since: card.rights_since ?? '',
    rights,
  };
}

/** Форма → тело запроса. Всё строками: доли в JSON-числе теряют точность. */
function toPayload(form) {
  return {
    sku: form.sku,
    code: form.code,
    title: form.title,
    artist: form.artist,
    authors: form.authors,
    album: form.album,
    genre: form.genre,
    catalog: form.catalog,
    share_author: form.share_author,
    share_related: form.share_related,
    royalty_percent: form.royalty_percent,
    rights_since: form.rights_since,
    rights: form.rights
      // Пустая строка прав — это строка, которую добавили и не заполнили;
      // отправлять её значит получить отказ «правообладатель не может быть
      // пустым» за то, чего человек не делал.
      .filter((r) => String(r.owner).trim() !== '')
      .map((r) => ({
        right_type: r.right_type,
        owner: r.owner,
        share: r.share,
        royalty: r.royalty,
      })),
  };
}

/** «80,5», «80%» и «80» — одно и то же число; пусто и мусор — null. */
function toNumber(value) {
  const raw = String(value ?? '')
    .trim()
    .replace(',', '.')
    .replace('%', '');
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** Сравниваем доли в сотых долях процента: 0.1 + 0.2 в двоичной дроби ≠ 0.3. */
function cents(value) {
  return Math.round(value * 100);
}

/** 100.00 → «100», 33.33 → «33.33»: хвостовые нули в доле только мешают. */
function trim(value) {
  return String(Number(value.toFixed(2)));
}

function newKey() {
  return `r${Math.random().toString(36).slice(2)}`;
}

function percentOrDash(value) {
  return value === null || value === undefined ? '' : formatPercent(value);
}

/** ISO с сервера → ДД.ММ.ГГГГ, как везде в приложении. */
function russianDate(value) {
  if (!value) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(value);
}
