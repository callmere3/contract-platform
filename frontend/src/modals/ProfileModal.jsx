import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { ChampionBadge } from '../components/ui/ChampionBadge';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { fetchMyAchievements } from '../api/profile';

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

  useEffect(() => {
    let alive = true;
    fetchMyAchievements()
      .then((data) => alive && setAchievements(data.achievements ?? []))
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
            <div className="grid grid-cols-2 gap-2">
              {achievements.map((a) => (
                <AchievementCard key={a.code} achievement={a} />
              ))}
            </div>
          )}
        </section>
      </div>
    </Modal>
  );
}

/**
 * Плитка достижения. Полученное — в цвете, ещё нет — приглушённое и с
 * прогрессом («3 из 10»), чтобы было видно, к чему идти: у семи учёток из
 * десяти пока ноль документов, и без этого раздел был бы просто пустым.
 */
function AchievementCard({ achievement }) {
  const { icon, title, hint, subtitle, earned, progress, count } = achievement;
  const share = progress && progress.target > 0 ? progress.current / progress.target : 0;

  return (
    <div
      title={hint}
      className={`flex flex-col gap-1.5 p-3 rounded-input border ${
        earned ? 'border-border bg-surface' : 'border-dashed border-border bg-transparent'
      }`}
    >
      <div className="flex items-center gap-2">
        <span role="img" aria-hidden="true" className={`text-[22px] leading-none ${earned ? '' : 'grayscale opacity-45'}`}>
          {icon}
        </span>
        {/* Счётчик повторяемого достижения: «×2» у второго кубка. */}
        {count > 1 && <span className="text-[13px] font-semibold text-accent">×{count}</span>}
      </div>

      <div className={`text-[13px] font-semibold leading-tight ${earned ? 'text-text' : 'text-text-muted'}`}>
        {title}
      </div>

      <div className="text-[11.5px] text-text-muted leading-snug">{subtitle || hint}</div>

      {!earned && progress && (
        <div className="flex items-center gap-2 mt-0.5">
          <span className="flex-1 h-1.5 bg-input-bg rounded-full overflow-hidden">
            <span
              className="block h-full rounded-full bg-border"
              style={{ width: `${Math.min(100, Math.round(share * 100))}%` }}
            />
          </span>
          <span className="text-[11px] text-text-muted tabular-nums">
            {progress.current} из {progress.target}
          </span>
        </div>
      )}
    </div>
  );
}
