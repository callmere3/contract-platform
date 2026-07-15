import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { TAG_OPTIONS } from '../mocks/tagOptions';

export function NewContragentModal({ onCreated }) {
  const { closeModal } = useModal();
  const [name, setName] = useState('');
  const [alias, setAlias] = useState('');
  const [country, setCountry] = useState(TAG_OPTIONS.countries[0]);
  const [type, setType] = useState(TAG_OPTIONS.contragentTypes[0]);
  const [contractFamily, setContractFamily] = useState(TAG_OPTIONS.contractFamilies[0]);
  const [inn, setInn] = useState('');

  const submit = () => {
    onCreated?.({ name, alias, country, type, contractFamily, inn });
    closeModal();
  };

  return (
    <Modal
      title="Новый контрагент"
      onClose={closeModal}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!name.trim()}>
            Создать
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Field
            label="Название / ФИО"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Иванов Иван Иванович"
          />
        </div>
        <Field
          label="Псевдоним"
          value={alias}
          onChange={(e) => setAlias(e.target.value)}
          hint="если нет — оставьте пустым"
        />
        <Field label="ИНН" value={inn} onChange={(e) => setInn(e.target.value)} />
        <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
          {TAG_OPTIONS.countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Field>
        <Field as="select" label="Тип" value={type} onChange={(e) => setType(e.target.value)}>
          {TAG_OPTIONS.contragentTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Field>
        <div className="col-span-2">
          <Field
            as="select"
            label="Тип договора"
            value={contractFamily}
            onChange={(e) => setContractFamily(e.target.value)}
          >
            {TAG_OPTIONS.contractFamilies.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </Field>
        </div>
      </div>
    </Modal>
  );
}
