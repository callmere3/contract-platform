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
    requisite_fields_by_type: reqByType,
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
  // Шаг подтверждения: null — показываем форму; иначе {fields, rows} —
  // экран «было → стало» перед сохранением (по просьбе владельца 04.08.2026,
  // чтобы наглядно видеть, что именно меняется). Сохранение идёт только после
  // явного «Подтвердить».
  const [pending, setPending] = useState(null);

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

  // ---- Формирование дифа «было → стало» для экрана подтверждения ----
  const fmt = (v) => {
    const s = v === null || v === undefined ? '' : String(v).trim();
    return s === '' ? '—' : s;
  };
  const fmtDate = (v) => {
    if (!v) return '—';
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v));
    return m ? `${m[3]}.${m[2]}.${m[1]}` : String(v);
  };
  // Значение одного реквизита для показа: choice → подпись варианта, date →
  // ДД.ММ.ГГГГ, пусто → «—» (зеркалит RequisitesSection.displayValue).
  const reqDisplay = (descriptor, raw) => {
    const s = (raw ?? '').toString().trim();
    if (!s) return '—';
    if (descriptor?.type === 'choice') {
      const opt = descriptor.choices?.find((c) => c.value === s);
      return opt ? opt.label : s;
    }
    if (descriptor?.type === 'date') {
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
      if (m) return `${m[3]}.${m[2]}.${m[1]}`;
    }
    return s;
  };

  /**
   * Человекочитаемый диф по payload changedFields(): [{key,label,before,after}].
   * reg_number/contract_number/дата форматируются под показ; requisites
   * разворачиваются пополе (одна строка на каждый изменившийся реквизит)
   * — так в подтверждении видно конкретное поле, а не JSON целиком.
   */
  function buildDiffRows(fields) {
    const rows = [];
    const push = (key, label, before, after) => rows.push({ key, label, before, after });

    if ('name' in fields)
      push('name', contragentNameLabel(type, companyTypeByCountry), fmt(contragent.name), fmt(fields.name));
    if ('country' in fields) push('country', 'Страна', fmt(contragent.country), fmt(fields.country));
    if ('contragent_type' in fields)
      push('contragent_type', 'Тип контрагента', fmt(contragent.type), fmt(fields.contragent_type));
    if ('contract_family' in fields)
      push('contract_family', 'Тип договора', fmt(contragent.contract_family), fmt(fields.contract_family));
    if ('contract_date' in fields)
      push('contract_date', 'Дата договора', fmtDate(contragent.contract_date), fmtDate(fields.contract_date));
    if ('royalty_percent' in fields)
      push('royalty_percent', 'Роялти %', fmt(contragent.royalty_percent), fmt(fields.royalty_percent));
    if ('reg_number' in fields)
      push('reg_number', meta?.label ?? 'Рег. номер', fmt(contragent.reg_number), fmt(fields.reg_number));
    if ('contract_number' in fields)
      push('contract_number', 'Номер договора', fmt(contragent.contract_number), fmt(fields.contract_number));
    if ('nicknames' in fields)
      push('nicknames', 'Псевдонимы', fmt((contragent.nicknames ?? []).join(', ')), fmt(fields.nicknames));

    if ('requisites' in fields) {
      const after = JSON.parse(fields.requisites); // нормализованный словарь непустых
      const before = contragent.requisites ?? {};
      const descriptors = reqByType?.[type] || [];
      const descByName = Object.fromEntries(descriptors.map((d) => [d.name, d]));
      const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
      [...keys].forEach((k) => {
        const b = (before[k] ?? '').toString().trim();
        const a = (after[k] ?? '').toString().trim();
        if (b === a) return;
        const d = descByName[k];
        push(`req.${k}`, d?.label ?? k, reqDisplay(d, b), reqDisplay(d, a));
      });
    }
    return rows;
  }

  /** «Сохранить» → сначала валидация и экран подтверждения (не сохраняем сразу). */
  function review() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    const fields = changedFields();
    if (Object.keys(fields).length === 0) {
      closeModal(); // менять нечего — просто закрыть
      return;
    }
    setError('');
    setPending({ fields, rows: buildDiffRows(fields) });
  }

  /** «Подтвердить» на экране дифа — фактическое сохранение. */
  async function doSave() {
    setBusy(true);
    setError('');
    try {
      await updateContragent(contragent.id, pending.fields);
      onSaved?.(); // обновить список сразу — сбросить красную подсветку и т.п.
      // Закрываем и эту модалку, и карточку под ней: карточка показывает
      // данные, загруженные ДО правки, и после сохранения они устарели.
      // Проще закрыть обе, чем перезагружать карточку под спойлером.
      closeModal();
      closeModal();
    } catch (e) {
      // Ошибка (напр. конфликт рег. номера) — вернуть к форме, чтобы поправить.
      setError(e.message);
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <Modal
      title={
        pending
          ? 'Подтвердите изменения'
          : restricted
            ? 'Тип договора контрагента'
            : 'Редактировать контрагента'
      }
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={560}
      footer={
        pending ? (
          <>
            <Button variant="secondary" size="sm" onClick={() => setPending(null)} disabled={busy}>
              Назад
            </Button>
            <Button variant="primary" size="sm" onClick={doSave} disabled={busy}>
              {busy ? 'Сохраняем…' : 'Подтвердить'}
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" size="sm" onClick={closeModal}>
              Отмена
            </Button>
            <Button variant="primary" size="sm" onClick={review} disabled={busy}>
              Сохранить
            </Button>
          </>
        )
      }
    >
      {pending && (
        <div>
          <p className="text-[13px] text-text-secondary mb-3 leading-snug">
            Проверьте, что изменится в карточке. Сохранение произойдёт только после подтверждения.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-text-muted">
                  <th className="text-left font-medium pb-2 pr-4">Поле</th>
                  <th className="text-left font-medium pb-2 pr-4">Было</th>
                  <th className="text-left font-medium pb-2">Стало</th>
                </tr>
              </thead>
              <tbody>
                {pending.rows.map((r) => (
                  <tr key={r.key} className="border-t border-border align-top">
                    <td className="py-2 pr-4 text-text-secondary whitespace-nowrap">{r.label}</td>
                    <td className="py-2 pr-4 text-text-muted break-words">{r.before}</td>
                    <td className="py-2 text-text font-medium break-words">{r.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!pending && (
      <>
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
      </>
      )}

      {error && <div className="text-[13px] text-accent mt-4 leading-snug">{error}</div>}
    </Modal>
  );
}
