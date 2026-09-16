import { useEffect, useRef, useState } from 'react';
import { ChampionBadge } from '../components/ui/ChampionBadge';
import { NavLink } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import {
  canViewUsers,
  canViewGenerationHistory,
  canSendNotifications,
  canUseDistaSync,
  canViewChampionBoard,
  canGrantDemoAchievement,
} from '../auth/permissions';
import { notificationsCount, NOTIFICATIONS_CHANGED_EVENT } from '../api/notifications';
import {
  ACHIEVEMENTS_CHANGED_EVENT,
  grantRandomAchievement,
  unopenedCodes,
} from '../achievements/tracker';
import { useModal } from '../modals/ModalProvider';
import { NotificationsPanel } from './NotificationsPanel';

// Первые три вкладки видны всем ролям (см. ТЗ: "менеджер видит все вкладки").
// Ограничения для них — не на уровне доступа к вкладке, а на уровне действий
// внутри неё (кнопки создания/удаления), см. src/auth/permissions.js.
//
// "Пользователи" и "История генерации" — исключение: там доступ не у всех
// ролей (первая — ADMIN правит / DIRECTOR смотрит, вторая — ADMIN/DIRECTOR
// и TOP_MANAGER свою), поэтому остальным вкладка показала бы только 403.
// Прячем целиком.
const TABS = [
  { to: '/search', label: 'Генерация' },
  { to: '/database', label: 'База контрагентов' },
  // Вкладка называется "Шаблоны", а маршрут остался /folders: переименование
  // чисто в подписи — внутри по-прежнему дерево папок с шаблонами, и кнопка
  // "+ Папка" там на месте. Менять URL ради подписи незачем.
  { to: '/folders', label: 'Шаблоны' },
];

export function Header({ companyName = 'ML Docs' }) {
  const { theme, toggleTheme } = useTheme();
  const { user } = useAuth();
  const { openModal } = useModal();

  // Непрочитанные уведомления — у ВСЕХ ролей: значок читают все, пишет их
  // только админ. Обновляем на монтировании, раз в минуту и мгновенно по
  // window-событию 'notifications-changed' (его шлёт панель после прочтения и
  // вкладка админа после отправки) — иначе значок отставал бы на минуту.
  const [unread, setUnread] = useState(0);
  // Панель уведомлений выпадает из значка, поэтому её состояние живёт здесь,
  // а не в стеке модалок: она привязана к кнопке, из которой появилась.
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const bellRef = useRef(null);
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      notificationsCount()
        .then((r) => alive && setUnread(r.unread || 0))
        .catch(() => {});
    refresh();
    const timer = setInterval(refresh, 60_000);
    window.addEventListener(NOTIFICATIONS_CHANGED_EVENT, refresh);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_CHANGED_EVENT, refresh);
    };
  }, []);

  // Точка у имени: есть полученное достижение, которое человек ещё не
  // открывал в профиле. Гаснет при открытии профиля, а не при показе
  // всплывашки — её легко пропустить.
  const [freshAchievements, setFreshAchievements] = useState(0);
  useEffect(() => {
    const refresh = () => setFreshAchievements(unopenedCodes().length);
    refresh();
    window.addEventListener(ACHIEVEMENTS_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(ACHIEVEMENTS_CHANGED_EVENT, refresh);
  }, []);

  let tabs = TABS;
  if (canViewGenerationHistory(user?.role)) {
    tabs = [...tabs, { to: '/generation-history', label: 'История генерации' }];
  }
  // Вкладка — это «написать», поэтому она только у админа и БЕЗ счётчика:
  // непрочитанное показывает значок справа, а не пункт меню.
  if (canSendNotifications(user?.role)) {
    tabs = [...tabs, { to: '/notifications', label: 'Уведомления' }];
  }
  if (canViewUsers(user?.role)) {
    tabs = [...tabs, { to: '/users', label: 'Пользователи' }];
  }
  if (canUseDistaSync(user?.role)) {
    tabs = [...tabs, { to: '/dista', label: 'Dista Connect' }];
  }
  if (canViewChampionBoard(user?.role)) {
    // Вместо подписи — сам кубок. title/aria-label обязательны: иначе
    // вкладка остаётся без имени — и для screen reader, и для того, кто
    // видит незнакомый значок и наводит мышь, чтобы понять, что это.
    tabs = [...tabs, { to: '/champion', label: '🏆', title: 'Кубок', emoji: true }];
  }

  return (
    // z-[45] — не украшение: шапка задаёт слой для выпадающей панели
    // уведомлений, а док черновика в правом нижнем углу живёт на z-40 и при
    // прежнем z-10 накрывал бы её нижний край. Выше остаются подсказки
    // ComboCell (z-50) и модалки (со 100): им и положено перекрывать шапку.
    <header className="flex items-center justify-between px-8 h-16 bg-surface border-b border-border sticky top-0 z-[45]">
      <div className="flex items-center gap-9">
        <span className="font-bold text-base tracking-[-0.01em] text-text">{companyName}</span>
        <nav className="flex items-center gap-7">
          {tabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              title={tab.title}
              aria-label={tab.title}
              className={({ isActive }) =>
                `text-sm py-5 border-b-2 transition-colors no-underline inline-flex items-center gap-1.5 ${
                  isActive
                    ? 'text-text font-semibold border-accent'
                    : 'text-text-secondary font-medium border-transparent'
                }`
              }
            >
              {/* Значок крупнее подписей: emoji в размере text-sm рядом со
                  словами выглядит мелкой точкой. */}
              <span className={tab.emoji ? 'text-[17px] leading-none' : undefined}>
                {tab.label}
              </span>
              {tab.badge > 0 && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[11px] font-semibold leading-none">
                  {tab.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-4">
        {/* Кнопка обкатки: выдаёт случайное достижение, чтобы проверить
            всплывашку, точку у имени и проявление плитки. Настоящим значок
            не становится — он живёт только в браузере (см. tracker.js).
            Поэтому и права на неё серверного нет, как у «Тестовых данных». */}
        {canGrantDemoAchievement(user?.role) && (
          <button
            onClick={() => grantRandomAchievement()}
            title="Выдать случайное достижение — для проверки механизма"
            aria-label="Выдать случайное достижение"
            className="w-8 h-8 rounded-full border border-dashed border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
          >
            🎁
          </button>
        )}
        {/* Значок уведомлений — у всех ролей. Счётчик рисуем только когда
            есть что читать: пустой кружок с нулём выглядел бы поломкой.
            Обёртка relative — якорь для выпадающей панели. */}
        <div className="relative">
          <button
            ref={bellRef}
            onClick={() => setNotificationsOpen((open) => !open)}
            title={unread > 0 ? `Непрочитанных: ${unread}` : 'Уведомления'}
            aria-label="Уведомления"
            aria-expanded={notificationsOpen}
            className="relative w-8 h-8 rounded-full border border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
          >
            🔔
            {unread > 0 && (
              <span className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[17px] h-[17px] px-1 rounded-full bg-danger text-white text-[10px] font-semibold leading-none">
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </button>
          {/* Панель монтируется только открытой — так список запрашивается
              при каждом открытии, а не висит с прошлого раза. */}
          {notificationsOpen && (
            <NotificationsPanel
              anchorRef={bellRef}
              onClose={() => setNotificationsOpen(false)}
            />
          )}
        </div>
        <button
          onClick={toggleTheme}
          aria-label="Переключить тему"
          className="w-8 h-8 rounded-full border border-border flex items-center justify-center text-sm text-text-secondary cursor-pointer bg-transparent"
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        {/* Кубок месяца — снаружи кнопки профиля: у него свой title
            («чемпион за …»), а вложенный в кнопку он подменялся бы её
            подсказкой. Нажатие на кубок открывает своё окно. */}
        <ChampionBadge champion={user?.champion} isMe />
        {/* Имя — вход в карточку профиля: смена пароля, выход, достижения.
            «Выйти» раньше стояло здесь же, отдельной кнопкой рядом с именем,
            и вылетало по ошибке — теперь оно внутри карточки. */}
        <button
          onClick={() => openModal('profile')}
          title={freshAchievements > 0 ? 'Профиль · есть новое достижение' : 'Профиль'}
          className="relative text-[13px] text-text-secondary hover:text-text bg-transparent border-none cursor-pointer p-0 font-sans"
        >
          {user?.full_name || user?.username}
          {freshAchievements > 0 && (
            <span
              aria-label="Есть новое достижение"
              className="absolute -top-1 -right-2.5 w-[7px] h-[7px] rounded-full bg-accent"
            />
          )}
        </button>
      </div>
    </header>
  );
}
