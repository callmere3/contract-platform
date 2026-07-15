import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { TAG_OPTIONS } from '../mocks/tagOptions';

const EMPTY_TAG_LABEL = '— не задано —';

export function NewTemplateModal({ folders = [], onCreated }) {
  const { closeModal } = useModal();
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [folderId, setFolderId] = useState(folders[0]?.id ?? '');
  const [country, setCountry] = useState('');
  const [contragentType, setContragentType] = useState('');
  const [contractFamily, setContractFamily] = useState('');

  const submit = () => {
    onCreated?.({ file, name, folderId, country, contragentType, contractFamily });
    closeModal();
  };

  return (
    <Modal
      title="Новый шаблон"
      onClose={closeModal}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!file || !name.trim()}>
            Загрузить
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Название шаблона" value={name} onChange={(e) => setName(e.target.value)} />
        <Field as="select" label="Папка" value={folderId} onChange={(e) => setFolderId(e.target.value)}>
          {folders.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </Field>

        <div>
          <div className="text-xs text-text-secondary mb-1.5">Файл шаблона (.docx)</div>
          <label className="inline-block">
            <input
              type="file"
              accept=".docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
            <span className="cursor-pointer inline-block border border-border rounded-input px-4 py-2.5 text-sm text-text">
              {file ? file.name : 'Выбрать файл…'}
            </span>
          </label>
        </div>

        {/* Теги — опциональны, "не задано" разрешено (в отличие от контрагента,
            где все три тега обязательны). Можно дозаполнить позже через
            EditTemplateModal. */}
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

export function NewFolderModal({ onCreated }) {
  const { closeModal } = useModal();
  const [name, setName] = useState('');

  const submit = () => {
    onCreated?.({ name });
    closeModal();
  };

  return (
    <Modal
      title="Новая папка"
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
      <Field label="Название папки" value={name} onChange={(e) => setName(e.target.value)} />
    </Modal>
  );
}
