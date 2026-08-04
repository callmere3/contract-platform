import { useMemo, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Field } from '../components/ui/Field';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { useAuth } from '../auth/AuthContext';
import { canEditContragents } from '../auth/permissions';
import { updateContragent } from '../api/contragents';
import { contragentNameLabel } from '../api/contragentTypes';
import { RequisitesSection } from '../components/ui/RequisitesSection';

/** Только непустые (обрезанные) значения — для сравнения и отправки. */
function normRequisites(obj) {
  const out = {};
  Object.entries(obj || {}).forEach(([k, v]) => {
    const s = (v ?? '').toString().trim();
    if (s) out[k] = s;
  });
  return out;
}
/** Стабильная сериализация (ключи по алфавиту) — чтобы порядок не считался изменением. */
function stableJson(obj) {
  return JSON.stringify(
    Object.keys(obj)
      .sort()
      .reduce((a, k) => ((a[k] = obj[k]), a), {}),
  );
}

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
 * title НЕ редактируется и НЕ ПЕРЕСЧИТЫВАЕТСЯ при правке карточки (решение
 * 31.07.2026, см. update_contragent): все титлы соответствуют базе компании,
 * пересчёт разошёлся бы с подписанными документами. Меняется он только через
 * импорт, поэтому поля для него здесь нет.
 *
 * contract_number, наоборот, ВЫВЕДЕН в форму и редактируется (по просьбе
 * владельца 04.08.2026, период заполнения базы) — это ручной override: сервер
 * сохраняет переданное значение как есть, без пересчёта по build_contract_number.
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
  const { user: me } = useAuth();
  const {
    countries,
    contragent_types: types,
    contract_families: families,
    reg_number_meta: regMeta,
    company_type_by_country: companyTypeByCountry,
  } = useTags();

  // Менеджеру доступна правка ТОЛЬКО типа договора (contract_family): он может
  // открыть эту же модалку, но видит одно поле, а сервер отклонит попытку
  // изменить что-то ещё (см. CAN_EDIT_CONTRACT_FAMILY / update_contragent).
  // Полноправные редакторы (admin/director/top_manager/tester) правят всё.
  const restricted = !canEditContragents(me?.role);

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
  // Номер договора выведен в форму и редактируется (по просьбе владельца
  // 04.08.2026). Это РУЧНОЙ OVERRIDE: сервер сохраняет переданное значение
  // как есть, без пересчёта по формуле (title по-прежнему не редактируется —
  // поля для него в форме нет). Пустая строка = очистить номер.
  const [contractNumber, setContractNumber] = useState(contragent.contract_number ?? '');
  const [nicknames, setNicknames] = useState((contragent.nicknames ?? []).join(', '));
  // Реквизиты доступны для правки ЛЮБОЙ роли (в т.ч. менеджеру в restricted-
  // режиме) — по решению владельца (CAN_EDIT_REQUISITES). Полная замена словаря.
  const [requisites, setRequisites] = useState({ ...(contragent.requisites ?? {}) });
  const setReq = (name, value) => setRequisites((r) => ({ ...r, [name]: value }));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const meta = regMeta?.[type];
  const royaltyNum = useMemo(() => (royalty.trim() ? parseFloat(royalty.replace(',', '.')) : null), [royalty]);

  function validate() {
    // Рег. номер правит ЛЮБАЯ роль (в т.ч. менеджер в restricted) — проверяем
    // всегда, до early-return для restricted.
    if (regNumber && !/^\d+$/.test(regNumber)) return 'Рег. номер должен состоять только из цифр.';
    if (regNumber && meta && regNumber.length !== meta.length)
      return `${meta.label} должен содержать ${meta.length} цифр, сейчас ${regNumber.length}.`;
    if (restricted) return ''; // остальные поля менеджеру недоступны — валидировать нечего
    if (!name.trim()) return 'ФИО/название не может быть пустым.';
    if (royalty.trim() && (Number.isNaN(royaltyNum) || royaltyNum < 0 || royaltyNum > 100))
      return 'Роялти должно быть числом от 0 до 100.';
    return '';
  }

  /** Реквизиты изменились относительно исходных? (нормализованное сравнение) */
  function requisitesChanged() {
    return (
      stableJson(normRequisites(requisites)) !== stableJson(normRequisites(contragent.requisites))
    );
  }

  /** Только реально изменённые поля — см. докстринг модуля. */
  function changedFields() {
    // Менеджер (restricted) правит тип договора И реквизиты — остальное сервер
    // всё равно отклонит (см. update_contragent).
    if (restricted) {
      const out = {};
      const next = contractFamily ?? '';
      const prev = contragent.contract_family ?? '';
      if (next !== prev) out.contract_family = next;
      // Рег. номер менеджер тоже правит (в блоке реквизитов) — сервер его
      // теперь принимает от любой роли (см. update_contragent).
      if ((regNumber ?? '').trim() !== (contragent.reg_number ?? '')) {
        out.reg_number = regNumber.trim();
      }
      // Псевдонимы менеджер тоже правит (по просьбе владельца). Нормализуем обе
      // стороны так же, как в полном режиме (см. ниже).
      const nickInput = nicknames.split(',').map((n) => n.trim()).filter(Boolean).join(', ');
      if (nickInput !== (contragent.nicknames ?? []).join(', ')) out.nicknames = nickInput;
      if (requisitesChanged()) out.requisites = JSON.stringify(normRequisites(requisites));
      return out;
    }
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
    put('contract_number', contractNumber.trim(), contragent.contract_number);

    // Псевдонимы: нормализуем обе стороны (убираем лишние пробелы/пустые),
    // чтобы правка "IVAN,PETROV" -> "IVAN, PETROV" не считалась изменением.
    // Пустая строка при изменении = очистить весь список (см. бэкенд).
    const nickInput = nicknames.split(',').map((n) => n.trim()).filter(Boolean).join(', ');
    const nickOriginal = (contragent.nicknames ?? []).join(', ');
    if (nickInput !== nickOriginal) fields.nicknames = nickInput;

    // Реквизиты — полная замена словаря, только если реально изменились.
    if (requisitesChanged()) fields.requisites = JSON.stringify(normRequisites(requisites));

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
      title={restricted ? 'Тип договора контрагента' : 'Редактировать контрагента'}
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
        {!restricted && (
          <div className="col-span-2">
            <Field
              label={contragentNameLabel(type, companyTypeByCountry)}
              value={name}
              onChange={(e) => setName(e.target.value)}
              hint="Титл при правке карточки не пересчитывается — он соответствует базе компании и обновляется только импортом"
            />
          </div>
        )}

        {!restricted && (
          <Field as="select" label="Страна" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">— не задано —</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Field>
        )}

        {!restricted && (
          <Field as="select" label="Тип контрагента" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">— не задано —</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Field>
        )}

        {!restricted && (
          <Field
            label={meta?.label ?? 'Рег. номер'}
            value={regNumber}
            onChange={(e) => setRegNumber(e.target.value)}
            placeholder="только цифры"
            hint={meta ? `${meta.length} цифр` : 'Зависит от типа контрагента'}
          />
        )}

        <div className={restricted ? 'col-span-2' : ''}>
          <Field
            as="select"
            label="Тип договора"
            value={contractFamily}
            onChange={(e) => setContractFamily(e.target.value)}
            hint={restricted ? 'Определяет, какие документы подбираются контрагенту' : undefined}
          >
            <option value="">— не задано —</option>
            {families.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </Field>
        </div>

        {!restricted && (
          <Field
            label="Дата договора"
            type="date"
            value={contractDate}
            onChange={(e) => setContractDate(e.target.value)}
          />
        )}

        {!restricted && (
          <Field label="Роялти %" value={royalty} onChange={(e) => setRoyalty(e.target.value)} />
        )}

        {/* Номер договора — ручной override (по просьбе владельца 04.08.2026):
            сервер сохраняет значение как есть, без пересчёта по формуле. */}
        {!restricted && (
          <div className="col-span-2">
            <Field
              label="Номер договора"
              value={contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="как в подписанном документе"
              hint="Сохраняется как есть, без пересчёта; пусто — очистить"
            />
          </div>
        )}

        {/* Псевдонимы правит любая роль (в т.ч. менеджер в restricted) — по
            просьбе владельца. В restricted-режиме это поле идёт после select
            типа договора. */}
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

      {/* Реквизиты — сворачиваемый блок, скрыт по умолчанию. Правит любая роль
          (в т.ч. менеджер в restricted-режиме). Набор полей — по типу. Рег.
          номер — первым полем блока, зеркалит верхнее поле (одно состояние
          regNumber), правится всеми ролями. */}
      <RequisitesSection
        contragentType={type}
        values={requisites}
        onChange={setReq}
        regNumber={regNumber}
        onRegNumberChange={setRegNumber}
        regNumberLabel={meta?.label ?? 'Рег. номер'}
        regNumberHint={meta ? `${meta.length} цифр` : undefined}
      />

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
