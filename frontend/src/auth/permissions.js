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
 *   действие                      | admin | director | top_manager | tester | manager
 *   ------------------------------|-------|----------|-------------|--------|--------
 *   генерация документов          |   +   |    +     |     +       |   +    |   +
 *   создание контрагента          |   +   |    +     |     +       |   +    |   +
 *   редактирование карточки       |   +   |    +     |     +       |   +    | + врем.
 *   удаление контрагента          |   +   |    -     |     -       |   -    |   -
 *   экспорт в Excel               |   +   |    +     |     -       |   -    |   -
 *   импорт из Excel               |   +   |    -     |     -       |   -    |   -
 *   папки/шаблоны: просмотр       |   +   |    +     |     +       |   +    |   +
 *   папки/шаблоны: управление     |   +   |    -     |     -       |   -    |   -
 *   пользователи (вкладка)        |   +   |    +     |     -       |   -    |   -
 *   создание/смена ролей          |   +   |    -     |     -       |   -    |   -
 *   просмотр audit_log            |   +   |    +     |     -       |   -    |   -
 *   история генерации (вкладка)   |   +   |    +     |     +       |   +    |   +
 *   история генерации: вся, не своя |  +  |    +     |     -       |   -    |   -
 *   уведомления: написать команде |   +   |    -     |     -       |   -    |   -
 *   вкладка «Кубок»               |   +   |    +     |     +       |   +    |   +
 *   ML Finance (второй продукт)   |   +   |    +     |     -       |   -    |   -
 *   внести поступление/расход     |   +   |    +     |     -       |   -    |   -
 *   удалить операцию              |   +   |    -     |     -       |   -    |   -
 *   кнопка "Тестовые данные"      |   +   |    -     |     -       |   +    |   -
 *
 * «+ врем.» у менеджера — послабление на период заполнения базы
 * (CAN_EDIT_CONTRAGENTS = ROLES в roles.py), откатывается двумя строками.
 * Пока оно действует, top_manager и manager не отличаются ничем.
 *
 * TESTER — самостоятельная роль, не копия TOP_MANAGER: у него скрытые
 * шаблоны и кнопка "Тестовые данные" (не право, а удобство — серверной
 * проверки нет, см. canFillDemoData ниже), зато он вне зачёта кубка.
 * Прежняя зависимость между этими двумя ролями снята.
 */
export const ADMIN = 'admin';
export const DIRECTOR = 'director';
export const TOP_MANAGER = 'top_manager';
export const TESTER = 'tester';
export const MANAGER = 'manager';

export const ROLE_LABELS = {
  [ADMIN]: 'ADMIN',
  [DIRECTOR]: 'DIRECTOR',
  [TOP_MANAGER]: 'TOP MANAGER',
  [TESTER]: 'TESTER',
  [MANAGER]: 'MANAGER',
};

const is = (role, ...allowed) => allowed.includes(role);

// backend: CAN_CREATE_CONTRAGENTS = (ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER)
export const canCreateContragents = (role) =>
  is(role, ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER);

// backend: CAN_EDIT_CONTRAGENTS = ROLES
// ⚠️ ВРЕМЕННО (04.08.2026): на период массового заполнения базы менеджерам
// открыты ВСЕ поля карточки. Вернуть к (ADMIN, DIRECTOR, TOP_MANAGER, TESTER)
// и синхронно в roles.py, когда менеджеры закончат заполнение.
export const canEditContragents = (role) => is(role, ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER);

// backend: CAN_EDIT_CONTRACT_FAMILY = ROLES — тип договора карточки может менять
// ЛЮБАЯ роль, включая manager (остальные поля — только canEditContragents).
// Менеджеру модалка правки показывает единственное поле «Тип договора».
export const canEditContractFamily = (role) =>
  is(role, ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER);

// backend: CAN_DELETE_CONTRAGENTS = (ADMIN,)
export const canDeleteContragents = (role) => is(role, ADMIN);

// backend: CAN_EDIT_TITLE = (ADMIN,) — титл карточки правит только админ
// (даже когда менеджерам временно открыта вся карточка). Поле «Титл» в форме
// показывается только ему.
export const canEditTitle = (role) => is(role, ADMIN);

// Артикул (страна + рег.номер, будущий единственный идентификатор) в карточке
// показывается только админу. Гейт чисто UI — само значение производно от
// country+reg_number, которые в карточке видны всем; здесь скрываем строку.
export const canViewArticle = (role) => is(role, ADMIN);

// backend: CAN_USE_DISTA_SYNC = (ADMIN,) — вкладка «Dista Connect» (сверка
// базы контрагентов с выгрузкой Dista Music). Только admin. С 16.09.2026
// вкладка живёт в ML Finance, но право прежнее.
export const canUseDistaSync = (role) => is(role, ADMIN);

// backend: CAN_USE_FINANCE = (ADMIN, DIRECTOR) — второй продукт ML Finance
// (балансы контрагентов, поступления и расходы) и переключатель продуктов в
// шапке. У кого права нет, тот второго продукта не видит вовсе.
export const canUseFinance = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_ADD_FINANCE_OPERATIONS = (ADMIN, DIRECTOR) — вносить деньги
// могут оба, а вот удалять (CAN_DELETE_FINANCE_OPERATIONS) — только admin.
// Правки операции нет вовсе: ошибочную удаляют и вносят заново.
export const canAddFinanceOperations = (role) => is(role, ADMIN, DIRECTOR);
export const canDeleteFinanceOperations = (role) => is(role, ADMIN);

// Номенклатура — каталог треков. Сейчас совпадает с canUseFinance, но живёт
// отдельной строкой намеренно: каталог наполняет импорт, и заливать треки,
// скорее всего, будет не тот человек, которому положено видеть суммы выплат
// (зеркало CAN_VIEW_NOMENCLATURE в roles.py).
export const canViewNomenclature = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_EXPORT_NOMENCLATURE / CAN_IMPORT_NOMENCLATURE. Выгрузить
// каталог могут оба, залить — только admin: импорт замещает состав прав у
// каждого трека из файла, и цена ошибки тут выше, чем у чтения.
export const canExportNomenclature = (role) => is(role, ADMIN, DIRECTOR);
export const canImportNomenclature = (role) => is(role, ADMIN);

// backend: CAN_VIEW_PARTNERS / CAN_MANAGE_PARTNERS. Справочник площадок, от
// которых приходят деньги: смотрят и ведут те же, кто видит ML Finance.
export const canViewPartners = (role) => is(role, ADMIN, DIRECTOR);
export const canManagePartners = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_EXPORT_CONTRAGENTS = (ADMIN, DIRECTOR) — у top_manager/tester убран
export const canExport = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_VIEW_CHAMPION_BOARD = ROLES — вкладка «Кубок» (обладатель
// кубка и рейтинг текущего месяца) у ВСЕХ ролей: соревнование, которого не
// видят соревнующиеся, не соревнование. Чисел доска не показывает — только
// порядок мест и шкалу относительно лидера.
export const canViewChampionBoard = (role) =>
  is(role, ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER);

// backend: CAN_IMPORT = (ADMIN,)
export const canImport = (role) => is(role, ADMIN);

// backend: CAN_MANAGE_TEMPLATES = (ADMIN,) — создание/правка/удаление папок и шаблонов
export const canManageTemplates = (role) => is(role, ADMIN);

// backend: CAN_VIEW_USERS = (ADMIN, DIRECTOR) — видеть список пользователей и роли.
// Director только СМОТРИТ; создание/правка/смена ролей — за админом (canManageUsers).
export const canViewUsers = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_MANAGE_USERS = (ADMIN,) — создание/правка/деактивация/смена ролей.
export const canManageUsers = (role) => is(role, ADMIN);

// backend: CAN_SEND_NOTIFICATIONS = (ADMIN,) — вкладка «Уведомления»,
// то есть НАПИСАТЬ команде. Читать свои уведомления может любая роль,
// отдельного права на это нет: сервер отдаёт строки текущего пользователя. — вкладка "Уведомления": применить
// или отклонить предложения дозаполнить карточку контрагента данными, которые
// менеджер вписал в форму генерации. Только admin (правка эталонных карточек).
export const canSendNotifications = (role) => is(role, ADMIN);

// Кнопка "Импорт/экспорт" целиком: у manager внутри неё нет ничего
// доступного, поэтому прячем её саму, а не только поле импорта внутри
// (у director она видна, но блок импорта внутри скрыт — см. canImport).
export const canOpenImportExport = (role) => canExport(role) || canImport(role);

// backend: CAN_VIEW_GENERATION_HISTORY = ROLES — вкладка "История генерации" у
// ВСЕХ ролей, каждый видит СВОЮ генерацию. admin/director — всё, остальные
// (top_manager/tester/manager) только свои (сервер ограничивает по user_id).
export const canViewGenerationHistory = (role) =>
  is(role, ADMIN, DIRECTOR, TOP_MANAGER, TESTER, MANAGER);

// backend: SEES_ALL_GENERATION_HISTORY = (ADMIN, DIRECTOR) — видит историю ВСЕХ.
// Остальные видят лишь свою — поэтому им бесполезен фильтр по пользователю
// (он всегда они сами), UI его для них скрывает.
export const canViewAllGenerationHistory = (role) => is(role, ADMIN, DIRECTOR);

// backend: CAN_DELETE_GENERATION_HISTORY = (ADMIN,) — удаление записей истории
// генерации (чистка тестовых). Кнопка удаления в строке — только админу.
export const canDeleteGenerationHistory = (role) => is(role, ADMIN);

// Кнопка "Заполнить тестовыми" в форме генерации.
//
// ЕДИНСТВЕННОЕ право в этом файле БЕЗ пары в roles.py — и это осознанно.
// Остальные скрывают кнопку, которая вернула бы 403; здесь защищать нечего:
// демо-значения приходят в схеме полей всем ролям (см. DEMO_VALUES в
// template_analysis.py), они заведомо ненастоящие, и "заполнить форму" —
// не привилегия, а набор кликов, который менеджер и так может сделать
// руками. Ограничение чисто UX: кнопка нужна для проверки шаблонов, в
// рабочем потоке менеджера она только мешала бы.
//
// TESTER — роль, заведённая ровно ради этой кнопки: по правам доступа она
// копия TOP_MANAGER, а вся разница здесь.
export const canFillDemoData = (role) => is(role, ADMIN, TESTER);

// Кнопка «выдать случайное достижение» в шапке — как и «Тестовые данные»,
// это удобство для обкатки, а не право: серверной проверки нет и быть не
// может, достижение выдаётся только в браузере (см. tracker.js).
//
// ТОЛЬКО TESTER (16.09.2026, просьба владельца). Раньше был и ADMIN — чтобы
// владелец мог проверить механизм, не переключая себе роль; механизм
// проверен, а кнопка осталась висеть в рабочей шапке админа рядом с
// уведомлениями и профилем. Это единственное право, которого у админа нет
// намеренно: понадобится — он заводит себе учётку тестера, а не
// возвращает кнопку.
export const canGrantDemoAchievement = (role) => is(role, TESTER);
