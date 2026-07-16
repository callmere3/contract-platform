/**
 * Права ролей — ЗЕРКАЛО backend/app/roles.py и констант в роутерах.
 *
 * Это чисто UX-слой: настоящая защита всегда на сервере через
 * Depends(require_role(...)). Здесь мы только не показываем кнопку, нажатие
 * на которую гарантированно вернёт 403 — чтобы человек не тыкал в то, что
 * ему всё равно не дадут сделать.
 *
 * ВАЖНО: при любом изменении прав на бэкенде правится и этот файл. Если они
 * разойдутся, худшее, что случится — кнопка есть, а сервер отвечает 403
 * (неприятно, но не дыра); либо кнопки нет, а право есть (функция просто
 * недоступна из UI).
 *
 * Матрица (согласована с ТЗ и бэкендом):
 *
 *   действие                      | admin | director | top_manager | manager
 *   ------------------------------|-------|----------|-------------|--------
 *   генерация документов          |   +   |    +     |     +       |   +
 *   создание контрагента          |   +   |    +     |     +       |   +
 *   редактирование карточки       |   +   |    +     |     +       |   -
 *   удаление контрагента          |   +   |    -     |     -       |   -
 *   экспорт в Excel               |   +   |    +     |     +       |   -
 *   импорт из Excel               |   +   |    -     |     -       |   -
 *   папки/шаблоны: просмотр       |   +   |    +     |     +       |   +
 *   папки/шаблоны: управление     |   +   |    -     |     -       |   -
 *   пользователи (вкладка)        |   +   |    -     |     -       |   -
 *   просмотр audit_log            |   +   |    +     |     -       |   -
 *   история генерации (вкладка)   |   +   |    +     |     -       |   -
 */
export const ADMIN = 'admin';
export const DIRECTOR = 'director';
export const TOP_MANAGER = 'top_manager';
export const MANAGER = 'manager';

export const ROLE_LABELS = {
  [ADMIN]: 'ADMIN',
  [DIRECTOR]: 'DIRECTOR',
  [TOP_MANAGER]: 'TOP MANAGER',
  [MANAGER]: 'MANAGER',
};

const is = (role, ...allowed) => allowed.includes(role);

// backend: CAN_CREATE_CONTRAGENTS = (ADMIN, DIRECTOR, TOP_MANAGER, MANAGER)
export const canCreateContragents = (role) => is(role, ADMIN, DIRECTOR, TOP_MANAGER, MANAGER);

// backend: CAN_EDIT_CONTRAGENTS = (ADMIN, DIRECTOR, TOP_MANAGER) — правка карточки и никнеймов
export const canEditContragents = (role) => is(role, ADMIN, DIRECTOR, TOP_MANAGER);

// backend: CAN_DELETE_CONTRAGENTS = (ADMIN,)
export const canDeleteContragents = (role) => is(role, ADMIN);

// backend: CAN_EXPORT_CONTRAGENTS = (ADMIN, DIRECTOR, TOP_MANAGER)
export const canExport = (role) => is(role, ADMIN, DIRECTOR, TOP_MANAGER);

// backend: CAN_IMPORT = (ADMIN,)
export const canImport = (role) => is(role, ADMIN);

// backend: CAN_MANAGE_TEMPLATES = (ADMIN,) — создание/правка/удаление папок и шаблонов
export const canManageTemplates = (role) => is(role, ADMIN);

// backend: все эндпоинты /users защищены require_role(ADMIN) —
// список, создание и правка пользователей доступны только админу
export const canManageUsers = (role) => is(role, ADMIN);

// Кнопка "Импорт/экспорт" целиком: у manager внутри неё нет ничего
// доступного, поэтому прячем её саму, а не только поле импорта внутри
// (у director она видна, но блок импорта внутри скрыт — см. canImport).
export const canOpenImportExport = (role) => canExport(role) || canImport(role);

// backend: CAN_VIEW_GENERATION_HISTORY = (ADMIN, DIRECTOR) — вкладка "История генерации"
export const canViewGenerationHistory = (role) => is(role, ADMIN, DIRECTOR);

// Кнопка "Заполнить тестовыми" в форме генерации.
//
// ЕДИНСТВЕННОЕ право в этом файле БЕЗ пары в roles.py — и это осознанно.
// Остальные скрывают кнопку, которая вернула бы 403; здесь защищать нечего:
// демо-значения приходят в схеме полей всем ролям (см. DEMO_VALUES в
// template_analysis.py), они заведомо ненастоящие, и "заполнить форму" —
// не привилегия, а набор кликов, который менеджер и так может сделать
// руками. Ограничение чисто UX: кнопка нужна для проверки шаблонов, в
// рабочем потоке менеджера она только мешала бы.
export const canFillDemoData = (role) => is(role, ADMIN);
