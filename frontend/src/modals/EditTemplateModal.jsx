import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { TAG_OPTIONS } from '../mocks/tagOptions';

const EMPTY_TAG_LABEL = '— не задано —';

// Название + теги; файл в MinIO не трогается (см. update_template в
// routers_templates.py) — сюда файл специально не добавляем.
export function EditTemplateModal({ template, onSaved }) {
  const { closeModal } = useModal();
  const [name, setName] = useState(template?.name ?? '');
  const [country, setCountry] = useState(template?.country ?? '');
  const [contragentType, setContragentType] = useState(template?.contragent_type ?? '');
  const [contractFamily, setContractFamily] = useState(template?.contract_family ?? '');

  const submit = () => {
    onSaved?.({ id: template?.id, name, country, contragentType, contractFamily });
    closeModal();
  };

  return (
    <Modal
      title="Редактировать шаблон"
      onClose={closeModal}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!name.trim()}>
            Сохранить
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Название шаблона" value={name} onChange={(e) => setName(e.target.value)} />

        <div className="grid grid-cols-3 gap-4">
          <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">{EMPTY_TAG_LABEL}</option>
            {TAG_OPTIONS.countries.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Field>
          <Field
            as="select"
            label="Тип контрагента"
            value={contragentType}
            onChange={(e) => setContragentType(e.target.value)}
          >
            <option value="">{EMPTY_TAG_LABEL}</option>
            {TAG_OPTIONS.contragentTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Field>
          <Field
            as="select"
            label="Тип договора"
            value={contractFamily}
            onChange={(e) => setContractFamily(e.target.value)}
          >
            <option value="">{EMPTY_TAG_LABEL}</option>
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
