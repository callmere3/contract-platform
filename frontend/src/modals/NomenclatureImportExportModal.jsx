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
      setResult(await applyTracksImport(file, { ownerMap, createMissingOwners: createOwners }));
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
      width={640}
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
              'Выгрузить весь каталог в Excel — в том же формате, что и выгрузка из Dista.'
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={handleExport} disabled={busy}>
            {busy ? 'Готовим файл…' : 'Скачать .xlsx'}
          </Button>
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

          {plan && <Plan plan={plan} replace={replace} setReplace={setReplace} />}

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
                disabled={busy || plan.ready === 0}
              >
                {busy ? 'Применяем…' : `Применить (${plan.ready})`}
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

/** Что получится, если применить файл. */
function Plan({ plan, replace, setReplace }) {
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
                  onChange={(e) =>
                    setReplace((prev) => ({ ...prev, [o.name]: e.target.checked }))
                  }
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

      {plan.errors.length > 0 && <Issues title="Не пройдут" items={plan.errors} danger />}
      {plan.warnings.length > 0 && <Issues title="Предупреждения" items={plan.warnings} />}
    </div>
  );
}

/** Список проблемных строк — с номером строки файла, чтобы было что искать. */
function Issues({ title, items, danger }) {
  return (
    <div className="px-4 py-3 border-b border-border last:border-b-0">
      <div className={`text-[13px] font-semibold mb-1.5 ${danger ? 'text-danger' : 'text-text'}`}>
        {title}
      </div>
      <div className="max-h-[200px] overflow-y-auto flex flex-col gap-1">
        {items.map((item) => (
          <div key={`${item.row}-${item.sku}`} className="text-[12.5px] text-text-secondary">
            <span className="text-text-muted">стр. {item.row}</span>
            {item.sku ? ` · ${item.sku}` : ''} — {item.messages.join('; ')}
          </div>
        ))}
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
