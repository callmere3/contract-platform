import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import {
  emitNotificationsChanged,
  hideMyNotification,
  listMyNotifications,
  markNotificationsRead,
} from '../api/notifications';

/**
 * Панель уведомлений — открывается значком в шапке, доступна любой роли.
 *
 * Открытие панели И ЕСТЬ прочтение: сразу после загрузки списка шлём
 * отметку на сервер и гасим значок. Пометки «новое» при этом остаются
 * видимыми — они посчитаны по ответу, который пришёл ДО отметки, поэтому
 * человек всё-таки видит, что именно появилось с прошлого раза.
 */
export function NotificationsModal({ level, isTop }) {
  const { closeModal } = useModal();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [removing, setRemoving] = useState(null);

  useEffect(() => {
    let alive = true;
    listMyNotifications()
      .then((data) => {
        if (!alive) return;
        setItems(data);
        if (data.some((n) => !n.read_at)) {
          // Отметку не ждём и на ошибке не настаиваем: не прочиталось —
          // значок останется, человек откроет панель ещё раз.
          markNotificationsRead().then(emitNotificationsChanged, () => {});
        }
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  /**
   * Убрать уведомление у себя. У других оно остаётся: на сервере это
   * пометка на строке «адресовано мне». Из списка убираем сразу, не
   * дожидаясь перезагрузки, — ответ ничего нового не приносит.
   */
  async function remove(id) {
    setRemoving(id);
    setError('');
    try {
      await hideMyNotification(id);
      setItems((list) => list.filter((n) => n.id !== id));
      emitNotificationsChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setRemoving(null);
    }
  }

  return (
    <Modal
      title="Уведомления"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={480}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      {loading && <div className="text-[13px] text-text-muted">Загружаем…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}

      {!loading && !error && items.length === 0 && (
        <div className="text-[13px] text-text-muted leading-relaxed">
          Пока ничего нет. Здесь появятся сообщения от администратора.
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="flex flex-col gap-3">
          {items.map((n) => (
            <div
              key={n.id}
              className={`relative p-3.5 pr-9 rounded-input border ${
                n.read_at ? 'border-border bg-transparent' : 'border-accent bg-accent-soft'
              }`}
            >
              {/* Убрать у себя. Крестик в углу, а не кнопка в ряд: действие
                  второстепенное, а читают здесь текст. */}
              <button
                type="button"
                disabled={removing === n.id}
                onClick={() => remove(n.id)}
                title="Убрать у себя"
                aria-label="Убрать уведомление"
                className="absolute top-2.5 right-2.5 w-6 h-6 flex items-center justify-center rounded-full bg-transparent border-none cursor-pointer text-[13px] text-text-muted hover:text-danger font-sans"
              >
                ✕
              </button>
              <div className="text-[13.5px] text-text leading-relaxed whitespace-pre-line">
                {n.text}
              </div>
              <div className="flex items-center gap-2 mt-2 text-[11.5px] text-text-muted">
                <span>{n.author || 'администратор'}</span>
                <span className="text-border">·</span>
                <span>{formatWhen(n.created_at)}</span>
                {!n.read_at && (
                  <>
                    <span className="text-border">·</span>
                    <span className="text-accent font-semibold">новое</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

/** «16.09.2026, 14:30» — дату показываем целиком: объявления живут долго. */
function formatWhen(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
