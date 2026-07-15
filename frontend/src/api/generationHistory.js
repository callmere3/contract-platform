import { API, apiJson } from './client';

/**
 * GET /generation-history — только Admin и Director (см. app/roles.py:
 * CAN_VIEW_GENERATION_HISTORY). Показывает факт генерации (контрагент,
 * шаблон, кто сгенерировал) — сам payload формы сюда не отдаётся.
 */
export function listGenerationHistory() {
  return apiJson(`${API}/generation-history`);
}
