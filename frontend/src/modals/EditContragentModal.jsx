import { useMemo, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { updateContragent } from '../api/contragents';

/**
 * Правка карточки контрагента (PATCH /contragents/{id}) — только для
 * admin/director (см. CAN_EDIT_CONTRAGENTS; manager сюда не попадает,
 * кнопка ему не показывается в ContragentCardModal).
 *
 * Отправляем ТОЛЬКО изменённые поля: сервер трактует отсутствие поля как
 * "не трогать". Иначе, например, повторная отправка того же reg_number
 * без изменений гоняла бы проверку уникальности вхолостую, а пустая
 * строка в необязательном поле молча затирала бы значение.
 *
 * title и contract_number не редактируются — их пересобирает сервер сам,
 * как только меняются ФИО, тип или дата договора (см. update_contragent),
 * поэтому полей для них здесь нет.
 *
 * nicknames редактируются: непустое значение (через запятую) ПОЛНОСТЬЮ
 * заменяет прежний список, пустое — очищает его (см. update_contragent).
 * Как и остальные поля, отправляется только если реально изменилось.
 *
 * onSaved — колбэк обновления списка контрагентов (refetch из DatabasePage):
 * после сохранения список должен обновиться сразу (напр. сбросить красную
 * подсветку неполной карточки), а не ждать перезагрузки/смены вкладки.
 */
export function EditContragentModal({ contragent, level, isTop, onSaved }) {
  const { closeModal } = useModal();
  const {
    countries,
    contragent_types: types,
    contract_families: families,
    reg_number_meta: regMeta,
  } = useTags();

  const [name, setName] = useState(contragent.name ?? '');
  const [country, setCountry] = useState(contragent.country ?? '');
  const [type, setType] = useState(contragent.type ?? '');
  const [contractFamily, setContractFamily] = useState(contragent.contract_family ?? '');
  const [contractDate, setContractDate] = useState(contragent.contract_date ?? '');
  const [royalty, setRoyalty] = useState(
    contragent.royalty_percent === null || contragent.royalty_percent === undefined
      ? ''
      : String(contragent.royalty_percent),
  );
  const [regNumber, setRegNumber] = useState(contragent.reg_number ?? '');
  const [nicknames, setNicknames] = useState((contragent.nicknames ?? []).join(', '));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const meta = regMeta?.[type];
  const royaltyNum = useMemo(() => (royalty.trim() ? parseFloat(royalty.replace(',', '.')) : null), [royalty]);

  function validate() {
    if (!name.trim()) return 'ФИО/название не может быть пустым.';
    if (royalty.trim() && (Number.isNaN(royaltyNum) || royaltyNum < 0 || royaltyNum > 100))
      return 'Роялти должно быть числом от 0 до 100.';
    if (regNumber && !/^\d+$/.test(regNumber)) return 'Рег. номер должен состоять только из цифр.';
    if (regNumber && meta && regNumber.length !== meta.length)
      return `${meta.label} должен содержать ${meta.length} цифр, сейчас ${regNumber.length}.`;
    return '';
  }

  /** Только реально изменённые поля — см. докстринг модуля. */
  function changedFields() {
    const fields = {};
    const put = (key, next, prev) => {
      const a = next ?? '';
      const b = prev ?? '';
      if (String(a) !== String(b)) fields[key] = a;
    };
    put('name', name.trim(), contragent.name);
    put('country', country, contragent.country);
    put('contragent_type', type, contragent.type);
    put('contract_family', contractFamily, contragent.contract_family);
    put('contract_date', contractDate, contragent.contract_date);
    put('royalty_percent', royalty.trim(), contragent.royalty_percent);
    put('reg_number', regNumber.trim(), contragent.reg_number);

    // Псевдонимы: нормализуем обе стороны (убираем лишние пробелы/пустые),
    // чтобы правка "IVAN,PETROV" -> "IVAN, PETROV" не считалась изменением.
    // Пустая строка при изменении = очистить весь список (см. бэкенд).
    const nickInput = nicknames.split(',').map((n) => n.trim()).filter(Boolean).join(', ');
    const nickOriginal = (contragent.nicknames ?? []).join(', ');
    if (nickInput !== nickOriginal) fields.nicknames = nickInput;

    return fields;
  }

  async function submit() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    const fields = changedFields();
    if (Object.keys(fields).length === 0) {
      closeModal();
      return;
    }
    setBusy(true);
    setError('');
    try {
      await updateContragent(contragent.id, fields);
      onSaved?.(); // обновить список сразу — сбросить красную подсветку и т.п.
      // Закрываем и эту модалку, и карточку под ней: карточка показывает
      // данные, загруженные ДО правки, и после сохранения они устарели.
      // Проще закрыть обе, чем перезагружать карточку под спойлером.
      closeModal();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Редактировать контрагента"
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
            {busy ? 'Сохраняем…' : 'Сохранить'}
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
            hint="Титл и номер договора пересоберёт сервер, если менялись ФИО, тип или дата договора"
          />
        </div>

        <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">— не задано —</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Field>

        <Field as="select" label="Тип контрагента" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">— не задано —</option>
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
          hint={meta ? `${meta.length} цифр` : 'Зависит от типа контрагента'}
        />

        <Field
          as="select"
          label="Тип договора"
          value={contractFamily}
          onChange={(e) => setContractFamily(e.target.value)}
        >
          <option value="">— не задано —</option>
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

        <Field label="Роялти %" value={royalty} onChange={(e) => setRoyalty(e.target.value)} />

        <div className="col-span-2">
          <Field
            label="Псевдоним(ы)"
            value={nicknames}
            onChange={(e) => setNicknames(e.target.value)}
            placeholder="July Jones, Vladimir Ivanov"
            hint="через запятую; заменяет весь список, пусто — очистить"
          />
        </div>
      </div>

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
