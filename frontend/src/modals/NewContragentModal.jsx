import { useEffect, useMemo, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { contragentNameLabel, isCompanyType, typesForCountry } from '../api/contragentTypes';
import { createContragent, searchContragents } from '../api/contragents';
import { RequisitesSection } from '../components/ui/RequisitesSection';

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
  const {
    countries,
    contragent_types: types,
    contract_families: families,
    reg_number_meta: regMeta,
    company_type_by_country: companyTypeByCountry,
  } = useTags();

  const [name, setName] = useState('');
  const [country, setCountry] = useState('');
  const [type, setType] = useState('');
  const [contractFamily, setContractFamily] = useState('');
  const [contractDate, setContractDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [royalty, setRoyalty] = useState('70');
  const [regNumber, setRegNumber] = useState('');
  const [nicknames, setNicknames] = useState('');
  // Реквизиты при создании необязательны (по решению владельца) — сворачиваемый
  // блок, скрыт по умолчанию. Набор полей — по выбранному типу.
  const [requisites, setRequisites] = useState({});
  const setReq = (name, value) => setRequisites((r) => ({ ...r, [name]: value }));

  const [similar, setSimilar] = useState([]); // титлы похожих карточек (подсказка)
  const [busy, setBusy] = useState(false);

  // Подпись и длина рег. номера зависят от типа: ИНН 12 / ОГРНИП 15 / ОГРН 13.
  // Источник — GET /tags (reg_number_meta), не хардкод: те же значения
  // валидирует бэкенд в normalize_reg_number.
  const meta = regMeta?.[type];

  // Типы под выбранную страну: для KZ предлагается ТОО, а не ООО (см.
  // typesForCountry). При смене страны сбрасываем тип, если он стал скрыт.
  const visibleTypes = typesForCountry(types, country, companyTypeByCountry);
  function onCountryChange(next) {
    setCountry(next);
    if (type && !typesForCountry(types, next, companyTypeByCountry).includes(type)) {
      setType('');
    }
  }

  // Подсказка «похожие уже есть» на лету, дебаунс 400 мс. Это ТОЛЬКО
  // подсказка: настоящая защита от дублей — на сервере (409 по вычисленному
  // титлу, см. create_contragent). Прежний жёсткий блок по точному
  // совпадению c.name снят 10.09.2026: у 465 из 828 карточек name пустой
  // (пришли импортом), и против них он не срабатывал в принципе.
  //
  // Ищем по ПЕРВОМУ СЛОВУ (фамилия / начало названия), а не по всей введённой
  // строке. Импортная карточка хранит сокращённый титл «Кеосеян Э. З. (ИП)»,
  // подстроки «Кеосеян Эдгар Зареевич» в нём нет — поиск по полному ФИО не
  // находил ровно тех, кого важнее всего показать (так и родился дубль).
  useEffect(() => {
    // Порог — первое слово от 3 символов: на 1–2 буквах поиск вываливал сотни
    // совпадений.
    const firstWord = name.trim().split(/\s+/)[0] || '';
    if (firstWord.length < 3) {
      setSimilar([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const data = await searchContragents({ q: firstWord });
        // Если тип выбран — показываем только контрагентов ЭТОГО типа: у ООО
        // не должны всплывать СГ/ИП. При смене типа поиск перезапускается
        // (type в зависимостях эффекта).
        const matches = data.contragents.filter((c) => !type || c.type === type);
        setSimilar(matches.map((c) => c.title));
      } catch {
        setSimilar([]); // сеть недоступна — не мешаем работать
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [name, type]);

  const royaltyNum = useMemo(() => parseFloat(royalty.replace(',', '.')), [royalty]);

  function validate() {
    if (!name.trim()) return 'Укажите ФИО/название.';
    if (!country || !type || !contractFamily) return 'Заполните страну, тип контрагента и тип договора.';
    if (!contractDate) return 'Укажите дату договора.';
    if (!royalty.trim()) return 'Укажите роялти %.';
    if (Number.isNaN(royaltyNum) || royaltyNum < 0 || royaltyNum > 100)
      return 'Роялти должно быть числом от 0 до 100.';
    if (regNumber && !/^\d+$/.test(regNumber)) return 'Рег. номер должен состоять только из цифр.';
    return '';
  }

  // Один запрос на создание. confirmDuplicate=true уходит вторым заходом,
  // после того как оператор подтвердил совпадение титла (см. submit).
  async function create(confirmDuplicate) {
    const created = await createContragent({
      name: name.trim(),
      country,
      contragentType: type,
      contractFamily,
      contractDate,
      royaltyPercent: royaltyNum,
      regNumber: regNumber.trim(),
      nicknames: nicknames.trim(),
      // сервер сам отсеет пустые/чужие ключи (_parse_requisites)
      requisites,
      confirmDuplicate,
    });
    closeModal();
    // Сразу показываем документы созданного контрагента — не нужно его
    // потом искать заново, чтобы сделать документ (как в боевой версии).
    openModal('contragentDocs', { contragentId: created.id });
  }

  async function submit() {
    const problem = validate();
    if (problem) {
      openModal('alert', { title: 'Проверьте форму', message: problem });
      return;
    }
    setBusy(true);
    try {
      await create(false);
    } catch (e) {
      // 409 — сервер нашёл карточку с таким же вычисленным титлом. Это не
      // отказ, а вопрос: полный тёзка и вторая карточка того же человека
      // (аванс/роялти) законны. Показываем найденное и, если оператор
      // подтвердил, повторяем запрос с флагом.
      if (e.status === 409 && e.detail?.code === 'duplicate_title') {
        openModal('confirmDuplicateContragent', {
          message: e.message,
          duplicates: e.detail.duplicates || [],
          onConfirm: async () => {
            setBusy(true);
            try {
              await create(true);
            } catch (err) {
              openModal('alert', { title: 'Не удалось создать контрагента', message: err.message });
            } finally {
              setBusy(false);
            }
          },
        });
        return;
      }
      openModal('alert', { title: 'Не удалось создать контрагента', message: e.message });
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
            label={contragentNameLabel(type, companyTypeByCountry)}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={
              isCompanyType(type, companyTypeByCountry) ? 'Ромашка (без «ООО»/кавычек)' : 'Иванов Иван Иванович'
            }
          />
          {similar.length > 0 && (
            <div className="text-[11px] text-text-muted mt-1.5 leading-snug">
              Похожие уже есть: {similar.slice(0, 8).join(', ')}
              {similar.length > 8 && ` и ещё ${similar.length - 8}`}
            </div>
          )}
        </div>

        <Field as="select" label="Страна" value={country} onChange={(e) => onCountryChange(e.target.value)}>
          <option value="">— выберите —</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Field>

        <Field as="select" label="Тип контрагента" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">— выберите —</option>
          {visibleTypes.map((t) => (
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
          hint={meta ? `обычно ${meta.length} цифр, необязательно` : 'Сначала выберите тип контрагента'}
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
            hint="через запятую, необязательно"
          />
        </div>
      </div>

      {/* Реквизиты — необязательны при создании, сворачиваемый блок (скрыт по
          умолчанию). Рег. номер — первым полем блока, зеркалит верхнее поле
          (одно состояние regNumber). Появляется, когда выбран тип. */}
      <RequisitesSection
        contragentType={type}
        values={requisites}
        onChange={setReq}
        regNumber={regNumber}
        onRegNumberChange={setRegNumber}
        regNumberLabel={meta?.label ?? 'Рег. номер'}
        regNumberHint={
          meta ? `обычно ${meta.length} цифр, необязательно` : 'Сначала выберите тип контрагента'
        }
      />

    </Modal>
  );
}
