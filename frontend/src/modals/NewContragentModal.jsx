import { useEffect, useMemo, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { createContragent, searchContragents } from '../api/contragents';

/**
 * Создание контрагента. Доступно всем ролям (CAN_CREATE_CONTRAGENTS).
 *
 * title и contract_number НЕ вводятся руками — их вычисляет сервер
 * (см. build_contragent_title / build_contract_number), поэтому в форме их нет.
 *
 * Обязательные поля продиктованы бэкендом (Form(...) без default в
 * create_contragent): name, country, contragent_type, contract_family,
 * contract_date, royalty_percent. Необязательные: reg_number, nicknames.
 */
export function NewContragentModal({ level, isTop }) {
  const { closeModal, openModal } = useModal();
  const { countries, contragent_types: types, contract_families: families, reg_number_meta: regMeta } = useTags();

  const [name, setName] = useState('');
  const [country, setCountry] = useState('');
  const [type, setType] = useState('');
  const [contractFamily, setContractFamily] = useState('');
  const [contractDate, setContractDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [royalty, setRoyalty] = useState('70');
  const [regNumber, setRegNumber] = useState('');
  const [nicknames, setNicknames] = useState('');

  const [duplicates, setDuplicates] = useState(null); // {exact: bool, titles: []}
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // Подпись и длина рег. номера зависят от типа: ИНН 12 / ОГРНИП 15 / ОГРН 13.
  // Источник — GET /tags (reg_number_meta), не хардкод: те же значения
  // валидирует бэкенд в normalize_reg_number.
  const meta = regMeta?.[type];

  // Проверка дублей по ФИО на лету. Дебаунс 400 мс — как в боевом index.html.
  // Ищем по name, а не по title: у одного человека "Иванов (СГ)" и
  // "Иванов (ИП)" — разные title, но это один и тот же человек, и завести
  // его дважды нельзя (см. findExistingByName в боевой версии).
  useEffect(() => {
    const q = name.trim();
    if (!q) {
      setDuplicates(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const data = await searchContragents({ q });
        const normalized = q.toLowerCase();
        const exact = data.contragents.find((c) => (c.name || '').trim().toLowerCase() === normalized);
        setDuplicates({
          exact: Boolean(exact),
          titles: data.contragents.map((c) => c.title),
        });
      } catch {
        setDuplicates(null); // сеть недоступна — не мешаем работать
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [name]);

  const royaltyNum = useMemo(() => parseFloat(royalty.replace(',', '.')), [royalty]);

  function validate() {
    if (!name.trim()) return 'Укажите ФИО/название.';
    if (!country || !type || !contractFamily) return 'Заполните страну, тип контрагента и тип договора.';
    if (!contractDate) return 'Укажите дату договора.';
    if (!royalty.trim()) return 'Укажите роялти %.';
    if (Number.isNaN(royaltyNum) || royaltyNum < 0 || royaltyNum > 100)
      return 'Роялти должно быть числом от 0 до 100.';
    if (regNumber && !/^\d+$/.test(regNumber)) return 'Рег. номер должен состоять только из цифр.';
    if (regNumber && meta && regNumber.length !== meta.length)
      return `${meta.label} должен содержать ${meta.length} цифр, сейчас ${regNumber.length}.`;
    if (duplicates?.exact) return 'Контрагент с таким ФИО уже существует.';
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
      // Свежая проверка дубля по ФИО прямо перед созданием — на случай, если
      // оператор кликнул "Создать" раньше, чем отработал дебаунс живой
      // проверки (или тот упал из-за сетевого сбоя во время ввода). У name
      // нет unique-констрейнта на бэкенде, это единственная защита от дублей
      // по ФИО — см. findExistingByName в боевом index.html.
      const q = name.trim();
      let exact = null;
      try {
        const dup = await searchContragents({ q });
        const normalized = q.toLowerCase();
        exact = dup.contragents.find((c) => (c.name || '').trim().toLowerCase() === normalized) || null;
      } catch {
        /* сеть недоступна — не блокируем создание из-за сбоя самой проверки */
      }
      if (exact) {
        setError(`Контрагент с таким ФИО уже существует: «${exact.title}».`);
        return; // finally ниже вернёт busy=false
      }

      const created = await createContragent({
        name: name.trim(),
        country,
        contragentType: type,
        contractFamily,
        contractDate,
        royaltyPercent: royaltyNum,
        regNumber: regNumber.trim(),
        nicknames: nicknames.trim(),
      });
      closeModal();
      // Сразу показываем документы созданного контрагента — не нужно его
      // потом искать заново, чтобы сделать документ (как в боевой версии).
      openModal('contragentDocs', { contragentId: created.id });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Новый контрагент"
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
            {busy ? 'Создаём…' : 'Создать'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Field
            label="ФИО / название"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Иванов Иван Иванович"
          />
          {duplicates?.exact && (
            <div className="text-[11px] text-accent mt-1.5 leading-snug">
              Контрагент с таким ФИО уже существует — создать через эту форму нельзя.
            </div>
          )}
          {duplicates && !duplicates.exact && duplicates.titles.length > 0 && (
            <div className="text-[11px] text-text-muted mt-1.5 leading-snug">
              Похожие уже есть: {duplicates.titles.join(', ')}
            </div>
          )}
        </div>

        <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">— выберите —</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Field>

        <Field as="select" label="Тип контрагента" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">— выберите —</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Field>

        <Field
          label={meta?.label ?? 'Рег. номер'}
          value={regNumber}
          onChange={(e) => setRegNumber(e.target.value)}
          placeholder="только цифры"
          hint={
            meta
              ? `${meta.length} цифр, необязательно — можно дозаполнить позже`
              : 'Сначала выберите тип контрагента'
          }
        />

        <Field
          as="select"
          label="Тип договора"
          value={contractFamily}
          onChange={(e) => setContractFamily(e.target.value)}
        >
          <option value="">— выберите —</option>
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </Field>

        <Field
          label="Дата договора"
          type="date"
          value={contractDate}
          onChange={(e) => setContractDate(e.target.value)}
        />

        <Field
          label="Роялти %"
          value={royalty}
          onChange={(e) => setRoyalty(e.target.value)}
          placeholder="70"
        />

        <div className="col-span-2">
          <Field
            label="Псевдоним(ы)"
            value={nicknames}
            onChange={(e) => setNicknames(e.target.value)}
            placeholder="July Jones, Vladimir Ivanov"
            hint="через запятую, можно оставить пустым и добавить позже"
          />
        </div>
      </div>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
