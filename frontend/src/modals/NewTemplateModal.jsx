import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { createFolder, uploadTemplate } from '../api/templates';

// doc_type определяет, как строится форма генерации: у 'contract' номер и
// дата договора вычисляются, у 'appendix'/'act' — вводятся (это номер уже
// существующего договора). См. LINKED_DOC_TYPES в template_analysis.py.
const DOC_TYPES = [
  { value: 'contract', label: 'Договор' },
  { value: 'appendix', label: 'Приложение' },
  { value: 'act', label: 'Акт' },
];

/** Создание папки. parentId не задан — папка верхнего уровня. */
export function NewFolderModal({ parentId, onDone, level, isTop }) {
  const { closeModal } = useModal();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) {
      setError('Укажите название папки.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await createFolder({ name: name.trim(), parentId });
      onDone?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Новая папка"
      onClose={closeModal}
      level={level}
      isTop={isTop}
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
      <Field
        label="Название"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="РУ"
        hint={parentId ? 'Будет создана внутри текущей папки' : 'Папка верхнего уровня'}
      />
      {error && <div className="text-[13px] text-accent mt-4">{error}</div>}
    </Modal>
  );
}

/**
 * Загрузка нового шаблона (.docx) в папку.
 *
 * Теги (страна/тип/тип договора) необязательны при загрузке, но без них
 * шаблон не будет подбираться через контрагента — поэтому подсказываем это
 * прямо в форме, а не оставляем на догадку.
 */
export function NewTemplateModal({ folderId, onDone, level, isTop }) {
  const { closeModal } = useModal();
  const { countries, contragent_types: types, contract_families: families } = useTags();

  const [name, setName] = useState('');
  const [docType, setDocType] = useState('');
  const [country, setCountry] = useState('');
  const [contragentType, setContragentType] = useState('');
  const [contractFamily, setContractFamily] = useState('');
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) {
      setError('Укажите название шаблона.');
      return;
    }
    if (!file) {
      setError('Выберите файл .docx.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await uploadTemplate({
        name: name.trim(),
        folderId,
        docType,
        country,
        contragentType,
        contractFamily,
        file,
      });
      onDone?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Новый шаблон"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={560}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Загружаем…' : 'Загрузить'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Field
            label="Название"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Договор СГ Роялти"
          />
        </div>

        <Field as="select" label="Тип документа" value={docType} onChange={(e) => setDocType(e.target.value)}>
          <option value="">— не задан —</option>
          {DOC_TYPES.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </Field>

        <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">— не задан —</option>
          {countries.map((c) => (
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
          <option value="">— не задан —</option>
          {types.map((t) => (
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
          <option value="">— не задан —</option>
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </Field>

        <div className="col-span-2">
          <div className="text-xs text-text-secondary mb-1.5">Файл шаблона</div>
          <label className="inline-block">
            <input
              type="file"
              accept=".docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
            <span className="cursor-pointer inline-block bg-transparent border border-border text-text rounded-input px-4 py-2.5 text-[13px] font-semibold">
              {file ? file.name : 'Выбрать .docx…'}
            </span>
          </label>
          <div className="text-[11px] text-text-muted mt-1.5 leading-snug">
            Метки в шаблоне сканируются автоматически — форма генерации строится по ним.
          </div>
        </div>
      </div>

      <div className="text-[11px] text-text-muted mt-4 leading-snug">
        Без трёх тегов (страна, тип контрагента, тип договора) шаблон не будет предлагаться в
        «Документах контрагента» — подбор идёт по строгому совпадению всех трёх.
      </div>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
