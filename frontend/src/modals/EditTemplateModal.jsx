import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { typesForCountry } from '../api/contragentTypes';
import {
  deleteTemplate,
  downloadTemplateFile,
  getMapsToOptions,
  getTemplateFields,
  replaceTemplateFile,
  setTemplateVisibility,
  updateTemplate,
  updateTemplateFields,
} from '../api/templates';

/**
 * Поля для настройки источников (maps_to) — только скалярные. Списки (tracks,
 * videoclips) к скалярному атрибуту контрагента не привязать, а `performers`
 * вообще ВИРТУАЛЬНОЕ поле (сноска исполнителей): реальной метки в .docx нет,
 * и попытка его связать вернула бы 404 «В шаблоне нет метки 'performers'».
 * Поэтому в настройке источников списки не показываем и не отправляем.
 */
const mappableFields = (schemaFields) => schemaFields.filter((f) => f.type !== 'list');

/**
 * Настройка существующего шаблона (только admin): метаданные, замена файла,
 * источники значений полей (maps_to), удаление.
 *
 * Три отдельные операции на бэкенде, и намеренно не сливаем их в одну
 * кнопку "Сохранить всё": PATCH /templates/{id} (метаданные),
 * PUT /templates/{id}/file (файл), PATCH /templates/{id}/fields (maps_to).
 * У каждой свои ошибки, и валить их в общий "сохранить" — значит терять
 * понимание, что именно не прошло.
 */
export function EditTemplateModal({ template, onDone, level, isTop }) {
  const { closeModal } = useModal();
  const {
    countries,
    contragent_types: types,
    contract_families: families,
    obligation_buckets: buckets,
    company_type_by_country: companyTypeByCountry,
  } = useTags();

  // Приложение/акт тегируются бакетом обязательства, а не семейством (у них
  // платёжной оси нет — см. бэкенд app/tags.py). doc_type у шаблона тут не
  // меняется, поэтому справочник и подпись выбираем один раз по template.doc_type.
  const isObligationDoc = template.doc_type === 'appendix' || template.doc_type === 'act';
  const familyOptions = isObligationDoc ? buckets : families;
  const familyLabel = isObligationDoc ? 'Обязательство (для приложения/акта)' : 'Тип договора';

  const [name, setName] = useState(template.name ?? '');
  const [country, setCountry] = useState(template.country ?? '');
  const [contragentType, setContragentType] = useState(template.contragent_type ?? '');
  const [contractFamily, setContractFamily] = useState(template.contract_family ?? '');
  const [hidden, setHidden] = useState(Boolean(template.hidden_for_managers));

  // Типы под выбранную страну (для КЗ — ТОО, не ООО). Уже сохранённое
  // значение всегда оставляем в списке, даже если оно «чужое» (легаси-шаблон
  // с ООО+КЗ), — иначе селект молча показал бы не то. При смене страны руками
  // сбрасываем ставший скрытым тип.
  const base = typesForCountry(types, country, companyTypeByCountry);
  const visibleTypes =
    contragentType && !base.includes(contragentType) ? [...base, contragentType] : base;
  function onCountryChange(next) {
    setCountry(next);
    if (contragentType && !typesForCountry(types, next, companyTypeByCountry).includes(contragentType)) {
      setContragentType('');
    }
  }

  const [fields, setFields] = useState([]);
  const [mapsToOptions, setMapsToOptions] = useState([]);
  const [mapping, setMapping] = useState({}); // {placeholder: maps_to}
  const [loadingFields, setLoadingFields] = useState(true);

  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Схема полей + список допустимых maps_to. Без contragent_id: здесь нас
  // интересует структура шаблона, а не подстановка значений конкретного
  // контрагента.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [schema, options] = await Promise.all([
          getTemplateFields(template.id),
          getMapsToOptions(),
        ]);
        if (cancelled) return;
        const mappable = mappableFields(schema.fields);
        setFields(mappable);
        setMapsToOptions(options.options);
        setMapping(Object.fromEntries(mappable.map((f) => [f.name, f.maps_to ?? 'manual'])));
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoadingFields(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.id]);

  async function saveMeta() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateTemplate(template.id, { name: name.trim(), country, contragentType, contractFamily });
      onDone?.();
      setNotice('Метаданные сохранены.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveMapping() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateTemplateFields(template.id, mapping);
      setNotice('Источники значений сохранены.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDownloadFile() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const { blob, filename } = await downloadTemplateFile(template.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleVisibility() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await setTemplateVisibility(template.id, !hidden);
      setHidden(res.hidden_for_managers);
      onDone?.(); // обновить список — пометка "скрыт" в дереве
      setNotice(
        res.hidden_for_managers ? 'Шаблон скрыт от менеджеров.' : 'Шаблон виден менеджерам.',
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReplaceFile(file) {
    if (!file) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await replaceTemplateFile(template.id, file);
      // Метки пересканированы — перечитываем схему: могли появиться новые
      // поля или исчезнуть старые. maps_to существующих меток сервер
      // сохраняет (см. replace_template_file), но новые придут как 'manual'.
      const schema = await getTemplateFields(template.id);
      const mappable = mappableFields(schema.fields);
      setFields(mappable);
      setMapping(Object.fromEntries(mappable.map((f) => [f.name, f.maps_to ?? 'manual'])));
      onDone?.();
      setNotice('Файл заменён, метки пересканированы.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await deleteTemplate(template.id);
      onDone?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Настройка шаблона"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={620}
      footer={
        confirmDelete ? (
          <>
            <span className="text-[13px] text-text-muted mr-auto">Удалить шаблон и файл?</span>
            <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
              Отмена
            </Button>
            <Button variant="accent" size="sm" onClick={handleDelete} disabled={busy}>
              {busy ? 'Удаляем…' : 'Удалить'}
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="secondary"
              size="sm"
              className="mr-auto"
              onClick={() => setConfirmDelete(true)}
            >
              Удалить
            </Button>
            <Button variant="secondary" size="sm" onClick={closeModal}>
              Закрыть
            </Button>
          </>
        )
      }
    >
      {/* --- метаданные --- */}
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Field label="Название" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <Field as="select" label="Страна" value={country} onChange={(e) => onCountryChange(e.target.value)}>
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
          {visibleTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Field>
        <div className="col-span-2">
          <Field
            as="select"
            label={familyLabel}
            value={contractFamily}
            onChange={(e) => setContractFamily(e.target.value)}
          >
            <option value="">— не задан —</option>
            {/* Уже сохранённое «чужое» значение (напр. легаси-тег АВАНС на
                приложении до перетегирования) оставляем в списке, иначе селект
                молча показал бы «не задан» — админ должен видеть и поправить. */}
            {(contractFamily && !familyOptions.includes(contractFamily)
              ? [...familyOptions, contractFamily]
              : familyOptions
            ).map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </Field>
        </div>
      </div>
      <div className="mt-4">
        <Button variant="primary" size="sm" onClick={saveMeta} disabled={busy || !name.trim()}>
          Сохранить метаданные
        </Button>
      </div>

      {/* --- источники значений (maps_to) --- */}
      <div className="mt-7 pt-6 border-t border-border">
        <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-4">
          ИСТОЧНИКИ ЗНАЧЕНИЙ
        </div>
        <div className="text-[11px] text-text-muted mb-4 leading-snug">
          Поля с источником «контрагент» подставляются автоматически при генерации по конкретному
          контрагенту. Значение остаётся редактируемым — это предзаполнение, а не жёсткая подстановка.
        </div>

        {loadingFields && <div className="text-[13px] text-text-muted">Загрузка полей…</div>}
        {!loadingFields && fields.length === 0 && (
          <div className="text-[13px] text-text-muted">В шаблоне нет полей для заполнения.</div>
        )}
        {!loadingFields && fields.length > 0 && (
          <>
            <div className="border border-border rounded-input overflow-hidden">
              {fields.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center justify-between gap-3 px-3.5 py-2.5 border-b border-border last:border-b-0"
                >
                  <div className="min-w-0">
                    <div className="text-[13px] text-text truncate">{f.label ?? f.name}</div>
                    <div className="text-[11px] text-text-muted tracking-[0.03em] truncate">
                      {f.name}
                    </div>
                  </div>
                  <select
                    value={mapping[f.name] ?? 'manual'}
                    onChange={(e) => setMapping((m) => ({ ...m, [f.name]: e.target.value }))}
                    className="bg-input-bg border border-border rounded-input px-2.5 py-1.5 text-[13px] text-text font-sans outline-none flex-shrink-0 max-w-[240px]"
                  >
                    {mapsToOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <Button variant="primary" size="sm" onClick={saveMapping} disabled={busy}>
                Сохранить источники
              </Button>
            </div>
          </>
        )}
      </div>

      {/* --- видимость для менеджеров --- */}
      <div className="mt-7 pt-6 border-t border-border">
        <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-4">
          ВИДИМОСТЬ
        </div>
        <div className="flex items-center justify-between gap-4">
          <div className="text-[13px] text-text-secondary leading-snug">
            {hidden
              ? 'Скрыт от менеджеров — виден только админам, директору, топ-менеджеру и тестеру. Пригодится, чтобы обкатать шаблон до показа рабочим менеджерам.'
              : 'Виден всем ролям, включая менеджеров.'}
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={toggleVisibility}
            disabled={busy}
            className="flex-shrink-0"
          >
            {hidden ? 'Показать менеджерам' : 'Скрыть от менеджеров'}
          </Button>
        </div>
      </div>

      {/* --- замена файла --- */}
      <div className="mt-7 pt-6 border-t border-border">
        <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-4">ФАЙЛ</div>
        <div className="flex items-center gap-2.5">
          {/* Скачать → поправить у себя → заменить: цикл правки шаблона
              целиком в одном месте, без поиска исходника на диске. */}
          <Button variant="secondary" size="sm" onClick={handleDownloadFile} disabled={busy}>
            Скачать .docx
          </Button>
          <label className="inline-block">
            <input
              type="file"
              accept=".docx"
              disabled={busy}
              onChange={(e) => handleReplaceFile(e.target.files?.[0])}
              className="hidden"
            />
            <span className="cursor-pointer inline-block bg-transparent border border-border text-text rounded-input px-4 py-2.5 text-[13px] font-semibold">
              Заменить .docx…
            </span>
          </label>
        </div>
        <div className="text-[11px] text-text-muted mt-1.5 leading-snug">
          Скачайте исходник, внесите правки и залейте обратно. При замене метки
          пересканируются, а настроенные источники значений сохранятся у полей, которые остались
          в шаблоне.
        </div>
      </div>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
      {notice && !error && <div className="text-[13px] text-text-muted mt-4">{notice}</div>}
    </Modal>
  );
}
