import { fetchMyAchievements } from '../api/profile';

/**
 * Отслеживание новых достижений: всплывашка в момент получения, точка у
 * имени в шапке и подсветка в профиле.
 *
 * ПОЧЕМУ В БРАУЗЕРЕ, А НЕ НА СЕРВЕРЕ. Достижения нигде не хранятся, они
 * считаются на лету из истории генерации (см. app/achievements.py).
 * Значит, «новое» — это разница с тем, что человек уже видел, а видел он
 * это в своём браузере. Заводить ради уведомления таблицу выданных наград
 * и миграцию к ней — несоразмерно.
 *
 * ДВА РАЗНЫХ СОСТОЯНИЯ, и это не дублирование:
 *   seen   — про что уже показывали всплывашку. Чтобы не показать дважды.
 *   opened — что человек посмотрел в профиле. Пока не посмотрел, у имени
 *            горит точка, а плитка в профиле проявляется из серой в цветную.
 * Всплывашку легко пропустить (отошёл, свернул вкладку), поэтому точка
 * держится до реального открытия профиля, а не гаснет вместе с ней.
 *
 * ПЕРВЫЙ ЗАПУСК МОЛЧИТ. Если в хранилище пусто, текущие достижения просто
 * записываются как уже виденные: иначе человек, у которого их пять,
 * получил бы пять всплывашек подряд на ровном месте — и на новом
 * компьютере тоже.
 */

const SEEN_KEY = 'ml_achievements_seen';
const OPENED_KEY = 'ml_achievements_opened';
// Достижения, «выданные» кнопкой обкатки. Отдельным ключом, чтобы их было
// видно как ненастоящие и можно было стереть, не трогая остальное.
const DEMO_KEY = 'ml_achievements_demo';

/** Событие «набор достижений обновился» — шапка перерисовывает точку. */
export const ACHIEVEMENTS_CHANGED_EVENT = 'achievements-changed';
/** Событие «получено новое» — всплывашка показывает эти достижения. */
export const ACHIEVEMENT_EARNED_EVENT = 'achievement-earned';

// Последний известный список полученного. Держим в памяти, чтобы шапка
// могла спросить «есть ли непросмотренное?» без запроса к серверу.
let lastEarned = [];
// Последний полный ответ сервера — из него кнопка обкатки берёт, что выдать.
let lastItems = [];

function readCodes(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;         // null = ни разу не писали, см. «первый запуск»
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;                   // приватный режим или битое значение
  }
}

function writeCodes(key, codes) {
  try {
    localStorage.setItem(key, JSON.stringify(codes));
  } catch {
    /* не смогли запомнить — в худшем случае всплывашка повторится */
  }
}

/** Коды, выданные кнопкой обкатки. Профиль рисует их как полученные. */
export function demoCodes() {
  return readCodes(DEMO_KEY) ?? [];
}

/** Коды полученных достижений, которые человек ещё не смотрел в профиле. */
export function unopenedCodes() {
  const opened = readCodes(OPENED_KEY) ?? [];
  const all = [...new Set([...lastEarned, ...demoCodes()])];
  return all.filter((code) => !opened.includes(code));
}

/** Профиль открыт — гасим точку и запоминаем, что всё показано. */
export function markProfileOpened() {
  writeCodes(OPENED_KEY, [...new Set([...lastEarned, ...demoCodes()])]);
  window.dispatchEvent(new Event(ACHIEVEMENTS_CHANGED_EVENT));
}

/**
 * Выдать случайное достижение — кнопка обкатки для тестера.
 *
 * Настоящим оно не становится и стать не может: достижения считаются из
 * истории генерации, и «выдать» их сервер не умеет по устройству. Здесь
 * проверяется ровно то, что и требуется проверить, — всплывашка, точка у
 * имени и проявление плитки в профиле.
 *
 * Выдаём из ещё не выданных, чтобы каждое нажатие давало новый значок.
 * Когда закончились — набор сбрасывается и можно идти по кругу, иначе
 * кнопка однажды перестала бы что-либо делать.
 */
export function grantRandomAchievement() {
  if (lastItems.length === 0) return null;

  const granted = demoCodes();
  const pool = lastItems.filter((a) => !a.earned && !granted.includes(a.code));
  const source = pool.length > 0 ? pool : lastItems;
  if (pool.length === 0) writeCodes(DEMO_KEY, []);   // круг пройден, начинаем заново

  const pick = source[Math.floor(Math.random() * source.length)];
  const nextDemo = [...new Set([...(pool.length > 0 ? granted : []), pick.code])];
  writeCodes(DEMO_KEY, nextDemo);

  // Секретное под замком показываем как настоящее: у него другой значок и
  // название, и именно это и интересно проверить.
  const shown = pick.secret && !pick.earned
    ? { ...pick, icon: '👻', title: 'Призрак', hint: 'Вернуться после перерыва больше 100 дней' }
    : pick;

  window.dispatchEvent(new Event(ACHIEVEMENTS_CHANGED_EVENT));
  window.dispatchEvent(
    new CustomEvent(ACHIEVEMENT_EARNED_EVENT, { detail: { achievements: [shown] } }),
  );
  return shown;
}

/**
 * Спросить сервер и, если появилось новое, показать всплывашку.
 *
 * Вызывается при входе в приложение и после генерации документа — именно
 * там достижение чаще всего и случается. Ошибку глотаем: не смогли
 * проверить значки — это не повод мешать работе.
 */
export async function refreshAchievements() {
  let items;
  try {
    const data = await fetchMyAchievements();
    items = data.achievements ?? [];
  } catch {
    return [];
  }

  lastItems = items;
  const earned = items.filter((a) => a.earned);
  lastEarned = earned.map((a) => a.code);

  const seen = readCodes(SEEN_KEY);
  if (seen === null) {
    // Первый запуск в этом браузере: молча принимаем текущее состояние.
    writeCodes(SEEN_KEY, lastEarned);
    writeCodes(OPENED_KEY, lastEarned);
    window.dispatchEvent(new Event(ACHIEVEMENTS_CHANGED_EVENT));
    return [];
  }

  const fresh = earned.filter((a) => !seen.includes(a.code));
  writeCodes(SEEN_KEY, lastEarned);
  window.dispatchEvent(new Event(ACHIEVEMENTS_CHANGED_EVENT));

  if (fresh.length > 0) {
    window.dispatchEvent(
      new CustomEvent(ACHIEVEMENT_EARNED_EVENT, { detail: { achievements: fresh } }),
    );
  }
  return fresh;
}
