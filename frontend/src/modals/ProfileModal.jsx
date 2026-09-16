import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { ChampionBadge } from '../components/ui/ChampionBadge';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { fetchMyAchievements } from '../api/profile';
import {
  demoCodes,
  markProfileOpened,
  revealSecret,
  unopenedCodes,
} from '../achievements/tracker';

/**
 * Карточка профиля — открывается нажатием на своё имя в шапке.
 *
 * Имя, смена пароля, выход и достижения. «Выйти» переехало сюда из шапки:
 * в верхнем меню оно стояло рядом с именем и вылетало по ошибке, а внутри
 * карточки требует двух осознанных действий. Роль не подписываем — на
 * собственной карточке она выглядит служебной пометкой.
 *
 * Достижения запрашиваются при открытии, а не живут в /auth/me: их счёт
 * идёт по всей истории генерации, и дёргать его на каждой загрузке
 * страницы ради значка, который смотрят раз в неделю, незачем.
 */
export function ProfileModal({ level, isTop }) {
  const { closeModal, openModal } = useModal();
  const { user, logout } = useAuth();

  const [achievements, setAchievements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Что подсветить: значки, полученные с прошлого открытия профиля. Список
  // снимаем ОДИН раз при монтировании — сразу после этого он гасится
  // (markProfileOpened ниже), и без снимка анимировать было бы уже нечего.
  const [fresh] = useState(() => unopenedCodes());
  // Значки, выданные кнопкой обкатки: сервер о них не знает, но показать их
  // надо полученными — иначе проверять анимацию было бы не на чем.
  const [demo] = useState(() => demoCodes());

  // Полученное достижение должно выглядеть полученным. Для секретного это
  // значит раскрыть его: у выданного кнопкой сервер по-прежнему присылает
  // замок, и без подмены значок так и остался бы 🔒 — но уже цветным, что
  // выглядит поломкой. У настоящего раскрытый вид приходит с сервера, и
  // revealSecret его не трогает.
  const asShown = (a) => (demo.includes(a.code) ? { ...revealSecret(a), earned: true } : a);

  useEffect(() => {
    let alive = true;
    fetchMyAchievements()
      .then((data) => {
        if (!alive) return;
        setAchievements(data.achievements ?? []);
        // Профиль открыт — точка у имени больше не нужна.
        markProfileOpened();
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Modal title="Профиль" onClose={closeModal} level={level} isTop={isTop} width={480}>
      <div className="flex flex-col gap-5">
        {/* Кто я. Роль не подписываем: человек и так знает, кто он, а на
            своей же карточке это выглядит как служебная пометка. */}
        <div className="flex items-center gap-2.5">
          <span className="text-[19px] font-semibold text-text truncate">
            {user?.full_name || user?.username}
          </span>
          <ChampionBadge champion={user?.champion} isMe />
        </div>

        <div className="flex flex-col gap-2.5">
          {/* Инструкция первой: она нужна новичку, а смена пароля — раз в
              полгода. */}
          <Button
            variant="secondary"
            size="sm"
            className="w-full"
            onClick={() => openModal('guide')}
          >
            Инструкция
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="w-full"
            onClick={() => openModal('changePassword')}
          >
            Сменить пароль
          </Button>
          {/* Выход не закрывает окно руками: со сбросом сессии размонтируется
              всё приложение вместе со стеком модалок. */}
          <Button variant="secondary" size="sm" className="w-full" onClick={logout}>
            Выйти
          </Button>
        </div>

        <section className="flex flex-col gap-2.5">
          <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-muted">
            Достижения
          </div>

          {loading && <div className="text-[13px] text-text-muted">Загружаем…</div>}
          {error && <div className="text-[13px] text-danger">{error}</div>}

          {!loading && !error && (
            <div className="grid grid-cols-3 gap-2">
              {achievements.map((a) => (
                <AchievementCard
                  key={a.code}
                  achievement={asShown(a)}
                  isFresh={fresh.includes(a.code)}
                  revealIndex={fresh.indexOf(a.code)}
                  onOpen={() => openModal('achievement', { achievement: asShown(a) })}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </Modal>
  );
}

/**
 * Плитка достижения: только значок и название. Условие — подсказкой при
 * наведении, всё остальное (счётчик повторов, месяцы, прогресс) — в окне
 * по нажатию (AchievementModal). Так раздел читается как ряд наград, а не
 * как таблица цифр.
 *
 * Полученное — в цвете и со сплошной рамкой, ещё нет — блёклое и
 * пунктиром: разница видна сразу, без единой цифры на плитке.
 */
function AchievementCard({ achievement, onOpen, isFresh = false, revealIndex = 0 }) {
  const { icon, title, hint, earned } = achievement;

  return (
    <button
      type="button"
      onClick={onOpen}
      title={hint}
      className={`flex flex-col items-center text-center gap-1.5 px-2 py-3 rounded-input border cursor-pointer min-h-[86px] justify-center ${
        earned
          ? 'border-border bg-surface'
          : 'border-dashed border-border bg-transparent'
      } ${isFresh ? 'achievement-reveal-card' : ''}`}
      style={isFresh ? { animationDelay: `${revealIndex * 320}ms` } : undefined}
    >
      <span
        role="img"
        aria-hidden="true"
        className={`text-[26px] leading-none ${earned ? '' : 'grayscale opacity-40'} ${
          isFresh ? 'achievement-reveal' : ''
        }`}
        // Несколько новых значков зажигаются по очереди, а не разом.
        style={isFresh ? { animationDelay: `${revealIndex * 320}ms` } : undefined}
      >
        {icon}
      </span>
      <span
        className={`text-[11.5px] font-semibold leading-tight ${
          earned ? 'text-text' : 'text-text-muted'
        }`}
      >
        {title}
      </span>
    </button>
  );
}
