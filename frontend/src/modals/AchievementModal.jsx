import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * Одно достижение крупно — открывается нажатием на плитку в профиле.
 *
 * Сюда вынесено всё, чего нет на самой плитке: условие, счётчик повторов
 * («×2» у второго кубка), список месяцев и прогресс. Плитка намеренно
 * осталась только значком с названием — раздел читается как ряд наград, а
 * не как таблица цифр.
 *
 * Секретное достижение и здесь молчит: пока не получено, приходит «замок»
 * с текстом «Условие скрыто», и показывать нечего — ни условия, ни
 * прогресса в ответе сервера попросту нет.
 */
export function AchievementModal({ achievement, level, isTop }) {
  const { closeModal } = useModal();
  const { icon, title, hint, subtitle, earned, progress, count } = achievement;
  const share = progress && progress.target > 0 ? progress.current / progress.target : 0;

  return (
    <Modal
      title={title}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={380}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      <div className="flex flex-col items-center text-center gap-3 py-1">
        <span
          role="img"
          aria-hidden="true"
          className={`text-[56px] leading-none ${earned ? '' : 'grayscale opacity-40'}`}
        >
          {icon}
        </span>

        {/* Счётчик повторов — только здесь: на плитке он превращал бы ряд
            наград в таблицу. */}
        {count > 1 && <div className="text-[17px] font-semibold text-accent">×{count}</div>}

        <div className={`text-[13px] font-semibold ${earned ? 'text-accent' : 'text-text-muted'}`}>
          {earned ? 'Получено' : 'Ещё не получено'}
        </div>

        <p className="text-[13.5px] text-text-secondary leading-relaxed m-0 max-w-[40ch]">{hint}</p>

        {subtitle && <p className="text-[13px] text-text m-0">{subtitle}</p>}

        {!earned && progress && (
          <div className="w-full flex items-center gap-2.5 mt-1">
            <span className="flex-1 h-2 bg-input-bg rounded-full overflow-hidden">
              <span
                className="block h-full rounded-full bg-border"
                style={{ width: `${Math.min(100, Math.round(share * 100))}%` }}
              />
            </span>
            <span className="text-[12px] text-text-muted tabular-nums">
              {progress.current} из {progress.target}
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
}
