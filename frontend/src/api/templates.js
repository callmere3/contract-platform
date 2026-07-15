import { API, apiFetch, apiJson } from './client';

/**
 * Вызовы к /folders и /templates.
 *
 * Управление (создание/правка/удаление) — только admin (require_role(ADMIN)
 * на бэкенде). Просмотр дерева и генерация — всем ролям.
 *
 * Как и с контрагентами, тело — form-data (Form(...) в роутерах), не JSON.
 */

/** Содержимое папки: подпапки + шаблоны + breadcrumb. Без parentId — корень. */
export function browseFolder(parentId) {
  const qs = parentId ? `?parent_id=${parentId}` : '';
  return apiJson(`${API}/folders${qs}`);
}

/** Создать папку. Без parentId — папка верхнего уровня. */
export function createFolder({ name, parentId }) {
  const body = new URLSearchParams({ name });
  if (parentId) body.append('parent_id', parentId);
  return apiJson(`${API}/folders`, { method: 'POST', body });
}

/** Переименовать папку. Удаления папок на бэкенде нет вовсе — только переименование. */
export function renameFolder(folderId, name) {
  return apiJson(`${API}/folders/${folderId}`, {
    method: 'PUT',
    body: new URLSearchParams({ name }),
  });
}

/**
 * Загрузить НОВЫЙ шаблон (.docx) в папку. Теги необязательны — можно
 * дозаполнить позже через updateTemplate.
 */
export function uploadTemplate({ name, folderId, docType, country, contragentType, contractFamily, file }) {
  const fd = new FormData();
  fd.append('name', name);
  fd.append('folder_id', folderId);
  if (docType) fd.append('doc_type', docType);
  if (country) fd.append('country', country);
  if (contragentType) fd.append('contragent_type', contragentType);
  if (contractFamily) fd.append('contract_family', contractFamily);
  fd.append('file', file);
  return apiJson(`${API}/templates`, { method: 'POST', body: fd });
}

/**
 * Обновить метаданные шаблона: название и/или теги.
 *
 * Семантика тегов на бэкенде: поле не передано — не трогаем; пустая строка —
 * снять тег; непустое — проставить. name обязателен всегда (Form(...)).
 */
export function updateTemplate(templateId, { name, country, contragentType, contractFamily }) {
  const body = new URLSearchParams({ name });
  if (country !== undefined) body.append('country', country ?? '');
  if (contragentType !== undefined) body.append('contragent_type', contragentType ?? '');
  if (contractFamily !== undefined) body.append('contract_family', contractFamily ?? '');
  return apiJson(`${API}/templates/${templateId}`, { method: 'PATCH', body });
}

/** Заменить файл шаблона. maps_to существующих меток переживает замену (см. бэкенд). */
export function replaceTemplateFile(templateId, file) {
  const fd = new FormData();
  fd.append('file', file);
  return apiJson(`${API}/templates/${templateId}/file`, { method: 'PUT', body: fd });
}

export function deleteTemplate(templateId) {
  return apiJson(`${API}/templates/${templateId}`, { method: 'DELETE' });
}

/**
 * Схема полей формы генерации. contragentId необязателен: если передан —
 * поля с настроенным maps_to приходят с уже подставленным default из
 * карточки контрагента, а nickname получает nickname_options (список).
 */
export function getTemplateFields(templateId, contragentId) {
  const qs = contragentId ? `?contragent_id=${contragentId}` : '';
  return apiJson(`${API}/templates/${templateId}/fields${qs}`);
}

/** Допустимые значения maps_to с подписями — для селекта "Источник значения". */
export function getMapsToOptions() {
  return apiJson(`${API}/templates/maps-to-options`);
}

/** Настроить источник значения полей: {placeholder: maps_to}. Только admin. */
export function updateTemplateFields(templateId, mapping) {
  return apiJson(`${API}/templates/${templateId}/fields`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mapping),
  });
}

/**
 * Генерация документа. Возвращает Blob (файл), поэтому apiFetch напрямую.
 * format: 'docx' | 'pdf'.
 */
export async function generateDocument(templateId, payload, format = 'docx') {
  const r = await apiFetch(`${API}/templates/${templateId}/generate?format=${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    let detail = `Не удалось сформировать документ (${r.status})`;
    try {
      const body = await r.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
    } catch {
      /* тело не JSON */
    }
    throw new Error(detail);
  }
  return r.blob();
}
