import { API, apiFetch, apiJson } from './client';

/**
 * Номенклатура — каталог треков лейбла (admin и director, CAN_VIEW_NOMENCLATURE).
 *
 * Основной путь данных — импорт выгрузки из Dista. Карточку при этом можно
 * поправить руками (updateTrack, 17.09.2026), и компромисс тут открытый:
 * правка держится до следующего импорта ТОГО ЖЕ артикула — строка файла
 * несёт полное состояние трека и не спрашивает, правил ли кто-то карточку.
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
  exact,
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
  // Точное совпадение: поле должно совпасть со строкой целиком, а не
  // содержать её. «Густ» иначе выдаёт и «ООО Густ Мьюзик», и «Густ Мьюзик KZ».
  if (exact) params.set('exact', 'true');
  if (page) params.set('page', String(page));
  if (pageSize) params.set('page_size', String(pageSize));
  return apiJson(`${API}/nomenclature?${params}`);
}

/** Карточка трека: все поля выгрузки плюс строки прав. */
export function fetchTrackCard(trackId) {
  return apiJson(`${API}/nomenclature/${trackId}`);
}

/**
 * Правка карточки: метаданные и состав прав ЦЕЛИКОМ.
 *
 * Целиком — потому что сервер замещает состав прав пришедшим списком: пошли
 * мы только изменённое, ему пришлось бы гадать, убрали правообладателя или
 * просто не тронули. Тот же принцип, что у импорта.
 *
 * Доли и ставки уходят СТРОКАМИ, как и приходят: «33.33» в JSON-числе
 * превращается в 33.329999999999998.
 *
 * `createMissingOwners` — ответ на вопрос сервера: он отвечает 409
 * `{code:'unknown_owners', owners:[…]}`, если имени нет в базе, и заводит
 * карточки только по этому флагу. Молчаливое заведение означало бы, что
 * опечатка в имени создаёт пустую карточку, мимо которой уйдут деньги.
 */
export function updateTrack(trackId, track, { createMissingOwners = false } = {}) {
  return apiJson(`${API}/nomenclature/${trackId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...track, create_missing_owners: createMissingOwners }),
  });
}

/**
 * Подсказки для поля правообладателя — титлы карточек контрагентов.
 *
 * Именно карточек, а не имён из каталога: у права должна появиться ССЫЛКА на
 * карточку, а имя без карточки приведёт лишь к вопросу «завести?».
 */
export function fetchOwnerSuggestions(q) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  return apiJson(`${API}/nomenclature/owners?${params}`);
}

/**
 * Выгрузка каталога в .xlsx — в том же формате, что отдаёт Dista, с учётом
 * текущих фильтров. Возвращает Blob: запрос требует Authorization, поэтому
 * просто перейти по ссылке нельзя.
 */
export async function exportTracks({
  q,
  owner,
  catalog,
  contragentId,
  caseSensitive,
  exact,
} = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (owner) params.set('owner', owner);
  if (catalog) params.set('catalog', catalog);
  if (contragentId) params.set('contragent_id', contragentId);
  // Выгрузка обязана отдавать ровно то, что видно на экране, — значит, и
  // галочку регистра надо передать.
  if (caseSensitive) params.set('case_sensitive', 'true');
  if (exact) params.set('exact', 'true');
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
