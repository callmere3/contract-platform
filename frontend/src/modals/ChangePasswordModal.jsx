import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { changePasswordRequest } from '../api/client';

/**
 * Смена своего пароля — доступна всем ролям (это действие над собой).
 *
 * После успеха все остальные сессии обрываются на сервере, а текущему
 * клиенту выдаётся новая пара токенов (её кладёт changePasswordRequest) —
 * поэтому здесь не нужно ни разлогинивать, ни перезагружать страницу.
 */
export function ChangePasswordModal({ level, isTop }) {
  const { closeModal } = useModal();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  function validate() {
    if (!current) return 'Введите текущий пароль.';
    // Зеркалит Field(min_length=8) на бэкенде — ловим до отправки.
    if (next.length < 8) return 'Новый пароль должен быть не короче 8 символов.';
    // Проверка совпадения — только на клиенте: серверу второе поле не нужно,
    // это защита от опечатки в пароле, который нигде больше не увидеть.
    if (next !== repeat) return 'Новый пароль и подтверждение не совпадают.';
    if (next === current) return 'Новый пароль совпадает с текущим.';
    return '';
  }

  async function submit() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await changePasswordRequest(current, next);
      setDone(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Modal
        title="Пароль изменён"
        onClose={closeModal}
        level={level}
        isTop={isTop}
        width={440}
        footer={
          <Button variant="primary" size="sm" onClick={closeModal}>
            Готово
          </Button>
        }
      >
        <div className="text-[13px] text-text-secondary leading-relaxed">
          Пароль обновлён. Все остальные сессии — на других устройствах и в других браузерах —
          завершены; там нужно войти заново. Здесь вход сохранён.
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      title="Смена пароля"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={440}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Меняем…' : 'Сменить пароль'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4">
        <Field
          label="Текущий пароль"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
        />
        <Field
          label="Новый пароль"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          hint="минимум 8 символов"
          autoComplete="new-password"
        />
        <Field
          label="Новый пароль ещё раз"
          type="password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          autoComplete="new-password"
        />
      </div>

      <div className="text-[11px] text-text-muted mt-4 leading-snug">
        После смены все остальные сессии будут завершены.
      </div>

      {error && <div className="text-[13px] text-accent mt-3 leading-snug">{error}</div>}
    </Modal>
  );
}
