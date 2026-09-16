import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canExportNomenclature, canImportNomenclature } from '../auth/permissions';
import { applyTracksImport, checkTracksImport, exportTracks } from '../api/nomenclature';

/**
 * Импорт и экспорт номенклатуры.
 *
 * ИМПОРТ В ДВА ШАГА: сначала «проверить» — сервер читает файл и показывает,
 * что получится, — и только потом «применить». Это не перестраховка: строка
 * выгрузки несёт ПОЛНОЕ состояние трека, и применение замещает состав его
 * прав целиком. Человек, который заливает файл каждый день, должен видеть,
 * что именно он сейчас переписывает.
 *
 * ПРАВООБЛАДАТЕЛИ — отдельный разговор внутри импорта. Имя из файла сервер
 * сверяет с карточками контрагентов и с теми, кто уже встречался в каталоге:
 *   - узнал — молчит;
 *   - похоже на существующего (лишний пробел, точка, «ИП» спереди вместо
 *     скобок, приписка KZ, опечатка) — предлагает замену, и по умолчанию она
 *     ВКЛЮЧЕНА: дубль правообладателя стоит дороже лишнего нажатия, его потом
 *     ищут по всему каталогу;
 *   - не знает вовсе — предлагает завести карточку контрагента.
 * Решение всегда за человеком: сервер только подсказывает.
 *
 * Экспорт отдаёт файл в ТОМ ЖЕ формате, что и Dista, с учётом текущих
 * фильтров списка — выгрузили, поправили руками, залили обратно.
 */
export function NomenclatureImportExportModal({ level, isTop, filters = {}, onImported }) {
  const { closeModal } = useModal();
  const { role } = useAuth();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [plan, setPlan] = useState(null);
  const [result, setResult] = useState(null);
  // Решения по похожим именам: {имя из файла: заменить?}. По умолчанию — да.
  const [replace, setReplace] = useState({});
  const [createOwners, setCreateOwners] = useState(true);
  // Строки, у которых человек снял галочку в таблице предпросмотра. Храним
  // номера строк файла — их же он видит на экране.
  const [skipRows, setSkipRows] = useState([]);

  const filterParts = [filters.q ? `«${filters.q}»` : null, filters.owner].filter(Boolean);

  async function handleExport() {
    setBusy(true);
    setError('');
    try {
      const blob = await exportTracks(filters);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filterParts.length ? 'nomenclature_filtered.xlsx' : 'nomenclature.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCheck(picked) {
    if (!picked) return;
    setBusy(true);
    setError('');
    setPlan(null);
    setResult(null);
    setFile(picked);
    try {
      const got = await checkTracksImport(picked);
      setPlan(got);
      setSkipRows([]);
      // Замены предлагаем принятыми: чаще всего подсказка верна, а отказаться
      // — одно нажатие.
      setReplace(Object.fromEntries(got.owners.similar.map((o) => [o.name, true])));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleApply() {
    setBusy(true);
    setError('');
    try {
      const ownerMap = Object.fromEntries(
        plan.owners.similar
          .filter((o) => replace[o.name])
          .map((o) => [o.name, o.suggestion]),
      );
      setResult(
        await applyTracksImport(file, {
          ownerMap,
          createMissingOwners: createOwners,
          skipRows,
        }),
      );
      setPlan(null);
      onImported?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Импорт / экспорт номенклатуры"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={1100}
    >
      {canExportNomenclature(role) && (
        <div className={canImportNomenclature(role) ? 'mb-6 pb-6 border-b border-border' : ''}>
          <div className="text-sm font-semibold text-text mb-1.5">Экспорт</div>
          <div className="text-[13px] text-text-secondary mb-3">
            {filterParts.length ? (
              <>
                Выгрузить каталог по текущему фильтру:{' '}
                <span className="text-text font-medium">{filterParts.join(' · ')}</span>. Уберите
                фильтры в списке, чтобы выгрузить весь каталог.
              </>
            ) : (
              <>
                Выгрузить весь каталог в Excel — в том же формате, что и выгрузка из Dista.{' '}
                {/* Про полторы минуты сказано намеренно: 121 тысяча строк
                    собирается в файл около 80 секунд, и без предупреждения
                    человек решит, что кнопка не сработала, и нажмёт ещё раз. */}
                <span className="text-text-muted">
                  Это 121 тысяча строк — файл собирается около полутора минут.
                </span>
              </>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={handleExport} disabled={busy}>
            {busy ? 'Готовим файл…' : 'Скачать .xlsx'}
          </Button>
          {busy && !filterParts.length && (
            <div className="text-[12px] text-text-muted mt-2">
              Собираем весь каталог, это займёт около полутора минут. Не закрывайте окно.
            </div>
          )}
        </div>
      )}

      {canImportNomenclature(role) && (
        <div>
          <div className="text-sm font-semibold text-text mb-1.5">Импорт</div>
          <div className="text-[13px] text-text-secondary mb-3">
            Файл в формате выгрузки Dista. Строка ищется по артикулу: знакомый трек обновится, а
            состав его прав заменится тем, что в файле.
          </div>

          <label className="inline-block">
            <input
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => handleCheck(e.target.files?.[0])}
            />
            <span className="inline-block px-3.5 py-2 rounded-input border border-border text-[13px] text-text cursor-pointer">
              {busy ? 'Читаем файл…' : file ? 'Выбрать другой файл' : 'Выбрать файл .xlsx'}
            </span>
          </label>

          {plan && (
            <Plan
              plan={plan}
              replace={replace}
              setReplace={setReplace}
              skipRows={skipRows}
              setSkipRows={setSkipRows}
            />
          )}

          {plan && plan.owners.new.length > 0 && (
            <label className="flex items-start gap-2 mt-4 text-[13px] text-text-secondary">
              <input
                type="checkbox"
                checked={createOwners}
                onChange={(e) => setCreateOwners(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                Завести карточки контрагентов на новых правообладателей ({plan.owners.new.length}).
                Карточка создаётся пустой, с одним названием — остальное заполняется в ML Docs.
              </span>
            </label>
          )}

          {plan && (
            <div className="flex items-center gap-3 mt-4">
              <Button
                variant="primary"
                size="sm"
                onClick={handleApply}
                disabled={busy || plan.ready - skipRows.length <= 0}
              >
                {busy ? 'Применяем…' : `Применить (${plan.ready - skipRows.length})`}
              </Button>
              {plan.ready === 0 && (
                <span className="text-[12.5px] text-text-muted">
                  Применять нечего: ни одна строка не прошла проверку.
                </span>
              )}
            </div>
          )}

          {result && <Result result={result} />}
        </div>
      )}

      {error && <div className="text-[13px] text-danger mt-4">{error}</div>}
    </Modal>
  );
}

/** Что получится, если применить файл: сводка, правообладатели и таблица строк. */
function Plan({ plan, replace, setReplace, skipRows, setSkipRows }) {
  const toggleRow = (row) =>
    setSkipRows((prev) => (prev.includes(row) ? prev.filter((r) => r !== row) : [...prev, row]));

  const cell = 'px-2 py-1.5 border-b border-border';
  const head =
    'px-2 py-2 text-left font-semibold text-text-muted border-b border-border bg-surface';

  return (
    <div className="mt-4 border border-border rounded-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border text-[13px] text-text">
        Строк в файле: <b>{plan.rows}</b> · заведётся: <b>{plan.tracks_new}</b> · обновится:{' '}
        <b>{plan.tracks_updated}</b>
        {plan.error_rows > 0 && (
          <>
            {' '}
            · <span className="text-danger">не пройдёт: {plan.error_rows}</span>
          </>
        )}
      </div>

      {plan.owners.similar.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <div className="text-[13px] font-semibold text-text mb-2">
            Похоже на тех, кто уже есть
          </div>
          <div className="flex flex-col gap-2">
            {plan.owners.similar.map((o) => (
              <label key={o.name} className="flex items-start gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={!!replace[o.name]}
                  onChange={(e) => setReplace((prev) => ({ ...prev, [o.name]: e.target.checked }))}
                  className="mt-0.5"
                />
                <span className="text-text-secondary">
                  <span className="text-text">{o.name}</span> → <b>{o.suggestion}</b>{' '}
                  <span className="text-text-muted">({o.rows} стр.)</span>
                </span>
              </label>
            ))}
          </div>
          <div className="text-[11.5px] text-text-muted mt-2">
            Снимите галочку, если это разные правообладатели: тогда имя из файла останется как есть
            и станет новым.
          </div>
        </div>
      )}

      {plan.owners.new.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <div className="text-[13px] font-semibold text-text mb-1.5">Новые правообладатели</div>
          <div className="text-[13px] text-text-secondary">
            {plan.owners.new.map((o) => `${o.name} (${o.rows})`).join(', ')}
          </div>
        </div>
      )}

      {/* ТАБЛИЦА, А НЕ СПИСОК ОШИБОК — так устроено окно предпроверки в самой
          Dista, и так правильнее: человеку надо видеть, что и в какую колонку
          попало (что «0.8» понято как 80%, а имя правообладателя не съехало на
          соседнее место), а не только перечень претензий. Список ошибок без
          самих данных читается как приговор без дела. */}
      <div className="px-4 pt-3 pb-2 text-[13px] font-semibold text-text">Что прочитано</div>
      <div className="overflow-auto max-h-[340px] border-t border-border">
        <table className="text-[12px] border-collapse whitespace-nowrap">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={head}>Ок</th>
              <th className={head}>Стр.</th>
              {plan.columns.map((c) => (
                <th key={c} className={head}>
                  {c}
                </th>
              ))}
              <th className={head}>Замечания</th>
            </tr>
          </thead>
          <tbody>
            {plan.preview.map((r) => {
              const skipped = !r.ok || skipRows.includes(r.row);
              return (
                <tr
                  key={r.row}
                  className={
                    !r.ok
                      ? 'bg-danger-soft'
                      : skipped
                        ? 'opacity-40'
                        : r.action === 'new'
                          ? 'bg-accent-soft'
                          : undefined
                  }
                >
                  <td className={cell}>
                    <input
                      type="checkbox"
                      checked={!skipped}
                      disabled={!r.ok}
                      onChange={() => toggleRow(r.row)}
                      title={r.ok ? 'Снять — не заливать эту строку' : 'Строка не прошла проверку'}
                    />
                  </td>
                  <td className={`${cell} text-text-muted tabular-nums`}>{r.row}</td>
                  {r.values.map((v, i) => (
                    <td key={i} className={`${cell} text-text max-w-[220px] truncate`} title={v}>
                      {v}
                    </td>
                  ))}
                  <td className={`${cell} text-danger`}>
                    {[...r.errors, ...r.warnings].join('; ')}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 text-[11.5px] text-text-muted">
        Цветом выделены новые треки, красным — строки, которые не пройдут. Галочку можно снять и у
        нормальной строки, если заливать её не нужно.
        {plan.preview_limited ? ` Показаны первые ${plan.preview.length} строк из ${plan.rows}.` : ''}
      </div>
    </div>
  );
}

/** Итог применения. */
function Result({ result }) {
  return (
    <div className="mt-4 border border-border rounded-card px-4 py-3 text-[13px] text-text">
      Заведено: <b>{result.created}</b> · обновлено: <b>{result.updated}</b> · строк прав:{' '}
      <b>{result.rights}</b>
      {result.skipped_rows > 0 && (
        <>
          {' '}
          · <span className="text-danger">пропущено: {result.skipped_rows}</span>
        </>
      )}
      {result.owners_created.length > 0 && (
        <div className="text-[12.5px] text-text-secondary mt-1.5">
          Заведены карточки: {result.owners_created.join(', ')}
        </div>
      )}
    </div>
  );
}
