import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ChampionBadge } from '../components/ui/ChampionBadge';
import { AchievementCard } from '../achievements/AchievementCard';
import { useModal } from './ModalProvider';
import { fetchUserCard } from '../api/users';
import { ROLE_LABELS } from '../auth/permissions';

/**
 * Карточка сотрудника — открывается нажатием на имя во вкладке
 * «Пользователи» (admin и director, те же роли, кому открыт список).
 *
 * Показывает то же, что человек видит у себя в профиле, минус личные
 * действия: чужой пароль отсюда не меняют и чужую сессию не закрывают —
 * управление ролью и «Отключить» остались в строке списка, где им и место.
 *
 * Анимации проявления здесь нет намеренно: она означает «ты только что это
 * получил», а на чужой карточке сообщать нечего. Секретное достижение,
 * если оно не получено, и здесь остаётся замком без условия — начальству
 * видно ровно столько же, сколько самому человеку.
 *
 * Данные берём одним запросом, хотя часть их уже есть в строке списка:
 * иначе карточка зависела бы от того, кто её открыл, и переиспользовать её
 * где-то ещё было бы нельзя.
 */
export function UserProfileModal({ userId, level, isTop }) {
  const { closeModal, openModal } = useModal();

  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    fetchUserCard(userId)
      .then((data) => alive && setCard(data))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [userId]);

  const person = card?.user;
  const achievements = card?.achievements ?? [];
  const earned = achievements.filter((a) => a.earned).length;

  return (
    <Modal
      title="Профиль сотрудника"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={640}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      {loading && <div className="text-[13px] text-text-muted">Загружаем…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}

      {!loading && !error && person && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="text-[19px] font-semibold text-text truncate">
                {person.full_name || person.username}
              </span>
              <ChampionBadge
                champion={person.champion}
                name={person.full_name || person.username}
              />
              {/* Роль подписываем, в отличие от своей карточки: про себя
                  человек и так знает, а чужую роль здесь и смотрят. */}
              <Badge variant="accent">{ROLE_LABELS[person.role] ?? person.role}</Badge>
              {!person.is_active && <Badge variant="neutral">отключён</Badge>}
            </div>
            <div className="text-[13px] text-text-muted">
              {person.username} · {lastSeenText(person)}
            </div>
          </div>

          <section className="flex flex-col gap-2.5">
            <div className="flex items-baseline justify-between gap-3">
              <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-muted">
                Достижения
              </div>
              <div className="text-[12px] text-text-muted tabular-nums">
                получено {earned} из {achievements.length}
              </div>
            </div>

            <div className="grid grid-cols-4 gap-2">
              {achievements.map((a) => (
                <AchievementCard
                  key={a.code}
                  achievement={a}
                  onOpen={() => openModal('achievement', { achievement: a })}
                />
              ))}
            </div>
          </section>
        </div>
      )}
    </Modal>
  );
}

/** «был(а) 16.09.2026, 14:30» — то же, что в строке списка пользователей. */
function lastSeenText(person) {
  if (!person.last_seen_at) return 'ещё не заходил(а)';
  const dt = new Date(person.last_seen_at).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  return `был(а) ${dt}`;
}
