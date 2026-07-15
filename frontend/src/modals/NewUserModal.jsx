import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { ROLE_LABELS } from '../auth/permissions';
import { createUser } from '../api/users';

/**
 * Создание пользователя (только admin).
 *
 * Пароль задаётся здесь и больше нигде не показывается — на сервере он
 * хранится только argon2-хэшем. Если пользователь его забудет, admin
 * задаёт новый через PATCH, а не "смотрит старый".
 */
export function NewUserModal({ onDone, level, isTop }) {
  const { closeModal } = useModal();
  const { roles } = useTags();

  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  function validate() {
    if (!username.trim()) return 'Укажите логин.';
    // Зеркалит Field(min_length=8) на бэкенде — ловим до отправки.
    if (password.length < 8) return 'Пароль должен быть не короче 8 символов.';
    if (!role) return 'Выберите роль.';
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
      await createUser({ username: username.trim(), password, fullName: fullName.trim(), role });
      onDone?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Новый пользователь"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={480}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Создаём…' : 'Создать'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4">
        <Field
          label="Логин"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="ivanov"
          autoComplete="off"
        />
        <Field
          label="ФИО"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Иванов Иван"
          hint="необязательно"
        />
        <Field
          label="Пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint="минимум 8 символов; посмотреть его потом будет нельзя, только задать новый"
          autoComplete="new-password"
        />
        <Field as="select" label="Роль" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">— выберите —</option>
          {roles.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r] ?? r}
            </option>
          ))}
        </Field>
      </div>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
