import { API, apiJson } from './client';

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
export function listTracks({ q, owner, catalog, page, pageSize } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (owner) params.set('owner', owner);
  if (catalog) params.set('catalog', catalog);
  if (page) params.set('page', String(page));
  if (pageSize) params.set('page_size', String(pageSize));
  return apiJson(`${API}/nomenclature?${params}`);
}

/** Карточка трека: все поля выгрузки плюс строки прав. */
export function fetchTrackCard(trackId) {
  return apiJson(`${API}/nomenclature/${trackId}`);
}

/**
 * Каталоги для фильтра. Справочник считается ПО ДАННЫМ (в выгрузке их 502),
 * а не задан списком: каталог приезжает из Dista, и любой зафиксированный
 * перечень разошёлся бы с ним на первом же импорте.
 */
export function fetchCatalogs() {
  return apiJson(`${API}/nomenclature/catalogs`);
}

/** «80» → «80%»; пусто → прочерк. */
export function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '—';
  return `${value}%`;
}
