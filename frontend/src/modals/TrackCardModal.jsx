import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { useModal } from './ModalProvider';
import { fetchTrackCard, formatPercent } from '../api/nomenclature';

/**
 * Карточка трека: ВСЕ поля выгрузки Dista.
 *
 * В таблице каталога их ровно столько, сколько нужно, чтобы трек опознать, —
 * остальное живёт здесь: авторы слов и музыки, альбом, жанр, каталог, доли на
 * уровне трека и дата прав. Так решил владелец: таблица на семи колонках
 * читается, на пятнадцати — нет.
 *
 * ДОЛИ ПОКАЗАНЫ ДВАЖДЫ, И ЭТО НЕ ОШИБКА ВЁРСТКИ. Сверху — «Доля авторских
 * прав» и «Доля смежных прав» из выгрузки, то есть доля на уровне трека;
 * ниже, в блоках прав, — доли конкретных правообладателей. Эти числа иногда
 * противоречат друг другу: у 45 617 треков доля смежных равна нулю, а
 * владелец смежных при этом указан со стопроцентной долей. Показать одно
 * значило бы решить за владельца, какое из них правда; у нас пока нет
 * оснований решать, и до первого живого отчёта карточка честно показывает
 * оба (см. брейншторм по номенклатуре, §3).
 *
 * Данные тянутся по track_id, а не приходят из строки списка: в списке нет ни
 * альбома, ни авторов, ни каталога — только то, что нарисовано в таблице.
 */
export function TrackCardModal({ trackId, level, isTop }) {
  const { closeModal } = useModal();

  const [card, setCard] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    fetchTrackCard(trackId)
      .then((data) => !cancelled && setCard(data))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [trackId]);

  return (
    <Modal
      title={card ? card.title : 'Трек'}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={640}
    >
      {!card && !error && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}
      {card && (
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

          {/* Два блока, а не одна таблица прав: смежные и авторские
              независимы, и складывать их доли между собой нельзя — у кавера
              фонограмма своя, а произведение чужое. */}
          <RightsBlock title="Смежные права" hint="на фонограмму" owners={card.rights.related} />
          <RightsBlock
            title="Авторские права"
            hint="на произведение — музыку и текст"
            owners={card.rights.author}
          />

          <div className="text-[11px] text-text-muted mt-5 leading-snug">
            {card.source_file ? `Из выгрузки «${card.source_file}»` : 'Источник выгрузки неизвестен'}
            {card.imported_at ? ` · загружено ${russianDate(card.imported_at.slice(0, 10))}` : ''}
            {card.archived ? ' · трек в архиве: его нет в последней выгрузке' : ''}
          </div>
        </>
      )}
    </Modal>
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
function RightsBlock({ title, hint, owners }) {
  return (
    <div className="mb-5 last:mb-0">
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-[13px] font-semibold text-text">{title}</span>
        <span className="text-[11.5px] text-text-muted">{hint}</span>
      </div>
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

function percentOrDash(value) {
  return value === null || value === undefined ? '' : formatPercent(value);
}

/** ISO с сервера → ДД.ММ.ГГГГ, как везде в приложении. */
function russianDate(value) {
  if (!value) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(value);
}
