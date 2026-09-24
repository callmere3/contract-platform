import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { PageHeader } from '../components/ui/PageHeader';
import { listUsers } from '../api/users';
import {
  deleteNotification,
  emitNotificationsChanged,
  listSentNotifications,
  sendNotification,
} from '../api/notifications';

/**
 * «Уведомления» — только admin (canSendNotifications / CAN_SEND_NOTIFICATIONS).
 * Здесь их ПИШУТ; читают все остальные значком в шапке.
 *
 * Было до 16.09.2026: предложения дозаполнить карточку контрагента
 * значениями из формы генерации. Механизм убран целиком — вместе с
 * app/suggestions.py и захватом при генерации.
 *
 * Два блока: форма отправки сверху и список отправленного снизу, с
 * отметками «прочитали N из M» — счёт приходит с сервера, строкой на
 * каждого адресата.
 */
export function NotificationsPage() {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [toAll, setToAll] = useState(true);
  const [picked, setPicked] = useState([]);   // id выбранных получателей
  const [people, setPeople] = useState([]);
  const [sent, setSent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState(null); // у какого уведомления раскрыт список

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [users, notes] = await Promise.all([listUsers(), listSentNotifications()]);
      // Отключённых в получатели не предлагаем — сервер их всё равно отсеет.
      setPeople(users.filter((u) => u.is_active));
      setSent(notes);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function togglePerson(id) {
    setPicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  }

  async function submit() {
    const head = title.trim();
    const body = text.trim();
    if (!head) {
      setError('Напишите заголовок — по нему в панели видно, о чём уведомление.');
      return;
    }
    if (!body) {
      setError('Напишите текст уведомления.');
      return;
    }
    if (!toAll && picked.length === 0) {
      setError('Выберите, кому отправить, или переключитесь на «всем».');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await sendNotification({ title: head, text: body, toAll, userIds: picked });
      setTitle('');
      setText('');
      setPicked([]);
      setToAll(true);
      await load();
      // Сам админ адресатом не становится, но значок мог измениться у него
      // же в другой вкладке — событие дешёвое, пусть будет.
      emitNotificationsChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id) {
    setBusy(true);
    setError('');
    try {
      await deleteNotification(id);
      setSent((list) => list.filter((n) => n.id !== id));
      emitNotificationsChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-[880px] mx-auto px-8 pt-12 pb-20 flex flex-col gap-6">
      {/* spaced={false}: расстояние здесь задаёт gap-6 контейнера. */}
      <PageHeader title="Уведомления" spaced={false}>
        Объявления команде. Видно, кому отправлено и кто уже прочитал; получатели фиксируются в
        момент отправки.
      </PageHeader>

      {error && (
        <Card>
          <div className="p-4 text-[13px] text-danger">{error}</div>
        </Card>
      )}

      <Card>
        <div className="p-5 border-b border-border text-sm font-semibold text-text">
          Написать уведомление
        </div>
        <div className="p-5 flex flex-col gap-4">
          {/* Заголовок отдельным полем, а не первой строкой текста: по нему
              человек в панели понимает, о чём объявление, не разворачивая
              его. Длина ограничена и здесь, и на сервере (120). */}
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
            placeholder="Заголовок — о чём уведомление"
            className="w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-[14px] font-semibold text-text font-sans outline-none"
          />
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            maxLength={2000}
            placeholder="Например: с понедельника все акты по ИП делаем через новый шаблон"
            className="w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-[14px] text-text font-sans outline-none resize-y leading-relaxed"
          />

          <div className="flex flex-col gap-2.5">
            <div className="flex items-center gap-4 text-[13px]">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" checked={toAll} onChange={() => setToAll(true)} />
                <span className={toAll ? 'text-text font-medium' : 'text-text-secondary'}>
                  Всем
                </span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" checked={!toAll} onChange={() => setToAll(false)} />
                <span className={!toAll ? 'text-text font-medium' : 'text-text-secondary'}>
                  Выбрать получателей
                </span>
              </label>
            </div>

            {!toAll && (
              <div className="flex flex-wrap gap-2">
                {people.map((u) => {
                  const on = picked.includes(u.id);
                  return (
                    <button
                      key={u.id}
                      type="button"
                      onClick={() => togglePerson(u.id)}
                      className={`text-[13px] px-3 py-1.5 rounded-input border cursor-pointer ${
                        on
                          ? 'border-accent bg-accent-soft text-accent font-semibold'
                          : 'border-border bg-transparent text-text-secondary'
                      }`}
                    >
                      {u.full_name || u.username}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[12px] text-text-muted">
              {toAll
                ? 'Получат все действующие сотрудники, кроме вас'
                : `Выбрано: ${picked.length}`}
            </span>
            <Button variant="primary" size="sm" disabled={busy} onClick={submit}>
              {busy ? 'Отправляем…' : 'Отправить'}
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <div className="p-5 border-b border-border text-sm font-semibold text-text">
          Отправленные
        </div>

        {loading && <div className="p-5 text-[13px] text-text-muted">Загружаем…</div>}

        {!loading && sent.length === 0 && (
          <div className="p-5 text-[13px] text-text-muted">Пока ничего не отправляли.</div>
        )}

        {!loading &&
          sent.map((n) => (
            <div key={n.id} className="px-5 py-4 border-b border-border last:border-b-0">
              {/* У отправленных до 16.09.2026 заголовка нет — показываем их
                  как раньше, одним текстом. Отступ под заголовком — в пустую
                  строку, как в панели у получателя. */}
              {n.title && (
                <div className="text-[14px] font-semibold text-text leading-snug mb-4">
                  {n.title}
                </div>
              )}
              <div className="text-[13.5px] text-text leading-relaxed whitespace-pre-line">
                {n.text}
              </div>
              <div className="flex items-center flex-wrap gap-2 mt-2 text-[12px] text-text-muted">
                <span>{formatWhen(n.created_at)}</span>
                <span className="text-border">·</span>
                {/* Прочтения раскрываются по нажатию: имена нужны редко, а
                    место занимают всегда. Список уже пришёл с сервера. */}
                <button
                  type="button"
                  onClick={() => setOpened(opened === n.id ? null : n.id)}
                  className="bg-transparent border-none p-0 cursor-pointer text-[12px] text-accent font-semibold font-sans"
                >
                  прочитали {n.read_count} из {n.total}
                </button>
                <span className="text-border">·</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => remove(n.id)}
                  className="bg-transparent border-none p-0 cursor-pointer text-[12px] text-text-muted font-sans hover:text-danger"
                >
                  удалить
                </button>
              </div>

              {opened === n.id && (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {n.recipients.map((r) => (
                    <span
                      key={r.id}
                      data-hint={r.read_at ? `прочитал(а) ${formatWhen(r.read_at)}` : 'ещё не открыл(а)'}
                      className={`text-[11.5px] px-2 py-1 rounded-badge border ${
                        r.read_at
                          ? 'border-transparent bg-accent-soft text-accent'
                          : 'border-dashed border-border text-text-muted'
                      }`}
                    >
                      {r.full_name || r.username}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
      </Card>
    </div>
  );
}

function formatWhen(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
