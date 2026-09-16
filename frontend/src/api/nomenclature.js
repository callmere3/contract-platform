import { API, apiFetch, apiJson } from './client';

/**
 * Номенклатура — каталог треков лейбла (admin и director, CAN_VIEW_NOMENCLATURE).
 *
 * Только чтение: каталог наполняет импорт выгрузки из Dista, а не интерфейс.
 * Строка выгрузки несёт полное состояние трека — доли, ставки,
 * правообладателей, — и правка одной ячейки в интерфейсе жила бы ровно до
 * следующего импорта.
 *
 * ДОЛИ И СТАВКИ — СТРОКИ («100», «33.33», «80»), как и суммы в ML Finance:
 * в JSON дробное число двоичное, и 33.33 уезжает в 33.329999999999998.
 * Фронт их показывает, а не считает.
 */

/** Список: { tracks: [...], total, page, page_size }. */
export function listTracks({
  q,
  owner,
  catalog,
  contragentId,
  caseSensitive,
  page,
  pageSize,
} = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (owner) params.set('owner', owner);
  if (catalog) params.set('catalog', catalog);
  // Отбор по СВЯЗИ с карточкой, а не по имени: у контрагента бывает
  // несколько написаний в выгрузке, и по титлу нашлись бы не все его треки.
  if (contragentId) params.set('contragent_id', contragentId);
  // Регистр важен не всегда, но иногда он и есть вопрос: в каталоге живут
  // «ООО Густ Мьюзик» и «ООО ГУСТ МЬЮЗИК» как разные правообладатели.
  if (caseSensitive) params.set('case_sensitive', 'true');
  if (page) params.set('page', String(page));
  if (pageSize) params.set('page_size', String(pageSize));
  return apiJson(`${API}/nomenclature?${params}`);
}

/** Карточка трека: все поля выгрузки плюс строки прав. */
export function fetchTrackCard(trackId) {
  return apiJson(`${API}/nomenclature/${trackId}`);
}

/**
 * Выгрузка каталога в .xlsx — в том же формате, что отдаёт Dista, с учётом
 * текущих фильтров. Возвращает Blob: запрос требует Authorization, поэтому
 * просто перейти по ссылке нельзя.
 */
export async function exportTracks({ q, owner, catalog, contragentId, caseSensitive } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (owner) params.set('owner', owner);
  if (catalog) params.set('catalog', catalog);
  if (contragentId) params.set('contragent_id', contragentId);
  // Выгрузка обязана отдавать ровно то, что видно на экране, — значит, и
  // галочку регистра надо передать.
  if (caseSensitive) params.set('case_sensitive', 'true');
  const qs = params.toString();
  const r = await apiFetch(`${API}/nomenclature/export${qs ? `?${qs}` : ''}`);
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}

/**
 * Источник импорта → тело запроса. Их два: файл .xlsx и вставка из буфера
 * (Ctrl+V), то есть текст с табуляциями, каким его кладут в буфер Excel и
 * грид Dista. Проверки на сервере после этого одинаковые.
 */
function importBody(source) {
  const body = new FormData();
  if (source.file) body.append('file', source.file);
  if (source.text) body.append('pasted', source.text);
  return body;
}

/**
 * Прогон источника БЕЗ записи: что заведётся, что обновится, что не пройдёт
 * и кого из правообладателей сервер не узнаёт.
 *
 * Шаг обязательный: применение ЗАМЕЩАЕТ состав прав у каждого трека из
 * файла, и делать это вслепую нельзя.
 */
export function checkTracksImport(source) {
  return apiJson(`${API}/nomenclature/import/check`, {
    method: 'POST',
    body: importBody(source),
  });
}

/**
 * Применить файл. ownerMap — решения человека по похожим именам
 * ({«ИП Погорельских»: «Погорельских А.А. (ИП)»}), createMissingOwners —
 * заводить ли карточки на тех, кого в базе нет вовсе.
 */
export function applyTracksImport(
  source,
  { ownerMap = {}, createMissingOwners = true, skipRows = [] } = {},
) {
  const body = importBody(source);
  body.append('owner_map', JSON.stringify(ownerMap));
  body.append('create_missing_owners', createMissingOwners ? 'true' : 'false');
  // Номера строк, у которых человек снял галочку в предпросмотре.
  body.append('skip_rows', JSON.stringify(skipRows));
  return apiJson(`${API}/nomenclature/import/apply`, { method: 'POST', body });
}

/** «80» → «80%»; пусто → прочерк. */
export function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '—';
  return `${value}%`;
}
