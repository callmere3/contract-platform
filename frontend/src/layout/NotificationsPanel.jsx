import { useEffect, useRef, useState } from 'react';
import {
  emitNotificationsChanged,
  hideMyNotification,
  listMyNotifications,
  markNotificationsRead,
} from '../api/notifications';

/**
 * Панель уведомлений — выпадает из значка 🔔 в шапке, доступна любой роли.
 *
 * Именно выпадающая, а не модалка по центру: уведомление — это взгляд
 * вскользь, а модалка гасит экран и требует закрыть себя, то есть ведёт
 * себя как дело, которым нужно заняться. Панель привязана к значку, из
 * которого она появилась, — видно, откуда она взялась.
 *
 * ОТКРЫТИЕ ПАНЕЛИ И ЕСТЬ ПРОЧТЕНИЕ: сразу после загрузки списка шлём
 * отметку на сервер и гасим значок. Пометки «новое» при этом остаются
 * видимыми — они посчитаны по ответу, который пришёл ДО отметки, поэтому
 * человек всё-таки видит, что появилось с прошлого раза.
 *
 * Список запрашивается при КАЖДОМ открытии, а не один раз: между двумя
 * открытиями админ мог написать что угодно, а значок рядом уже показывает
 * новое число — панель, отдающая вчерашний список, противоречила бы ему.
 *
 * Закрывается нажатием мимо, Escape и повторным нажатием на значок. Кнопки
 * «Закрыть» нет намеренно: у выпадающей панели её роль играет всё
 * остальное окно.
 */
export function NotificationsPanel({ onClose, anchorRef }) {
  const panelRef = useRef(null);
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

  // Нажатие мимо и Escape. Сам значок из «мимо» исключён: иначе его
  // обработчик закрыл бы панель, а следом открыл заново — и она не
  // закрывалась бы вовсе.
  useEffect(() => {
    const onDown = (e) => {
      if (panelRef.current?.contains(e.target)) return;
      if (anchorRef?.current?.contains(e.target)) return;
      onClose();
    };
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose, anchorRef]);

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
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Уведомления"
      // Высота ограничена, прокрутка внутри: объявления копятся, а панель
      // не должна уезжать за нижний край экрана.
      className="absolute right-0 top-[calc(100%+10px)] w-[380px] max-h-[70vh] overflow-y-auto bg-surface border border-border rounded-card shadow-card z-20 p-3.5"
    >
      {loading && <div className="text-[13px] text-text-muted">Загружаем…</div>}
      {error && <div className="text-[13px] text-danger">{error}</div>}

      {!loading && !error && items.length === 0 && (
        <div className="text-[13px] text-text-muted leading-relaxed">
          Пока ничего нет. Здесь появятся сообщения от администратора.
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="flex flex-col gap-2.5">
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
              {/* Заголовка нет у уведомлений, отправленных до 16.09.2026:
                  колонку добавили позже, а придумать его за автора значило
                  бы подписать его словами, которых он не писал. Такие
                  показываем как раньше — одним текстом.

                  Отступ под заголовком — в пустую строку: заголовок и текст
                  должны читаться как две разные вещи, а не как один абзац,
                  у которого первая строка потолще. */}
              {n.title && (
                <div className="text-[14px] font-semibold text-text leading-snug mb-4">
                  {n.title}
                </div>
              )}
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
    </div>
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
