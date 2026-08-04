import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { useAuth } from '../auth/AuthContext';
import {
  canDeleteContragents,
  canEditContragents,
  canEditContractFamily,
  canViewArticle,
} from '../auth/permissions';
import { deleteContragent, getContragent } from '../api/contragents';
import { contragentNameLabel } from '../api/contragentTypes';
import { RequisitesSection } from '../components/ui/RequisitesSection';

const ROWS = [
  ['name', 'ФИО / название'],
  ['country', 'Страна'],
  ['type', 'Тип контрагента'],
  ['reg_number', 'Рег. номер'], // подпись переопределяется под тип, см. ниже
  ['contract_family', 'Тип договора'],
  ['contract_number', 'Номер договора'],
  ['contract_date', 'Дата договора'],
  ['royalty_percent', 'Роялти %'],
];

/**
 * Значение поля карточки для показа. Дата договора приходит с бэкенда в ISO
 * (ГГГГ-ММ-ДД, contragent.contract_date.isoformat()), а показывать её надо в
 * принятом в России формате ДД.ММ.ГГГГ (как и везде в приложении). Остальные
 * поля — как есть; пусто → «—».
 */
function displayValue(key, value) {
  if (value === null || value === '' || value === undefined) return '—';
  if (key === 'contract_date') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
    if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  }
  return String(value);
}

/**
 * Карточка контрагента: просмотр всех полей + действия по правам.
 * Открывается по клику на строку в "Базе контрагентов".
 *
 * Данные грузятся по contragent_id, а не приходят готовыми из списка:
 * в списке (search_contragents) нет ни даты, ни роялти, ни номера договора —
 * только summary. Заодно карточка всегда свежая, даже если список устарел.
 */
export function ContragentCardModal({ contragentId, level, isTop, onChanged }) {
  const { closeModal, openModal } = useModal();
  const { reg_number_meta: regMeta, company_type_by_country: companyTypeByCountry } = useTags();
  const { role } = useAuth();

  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await getContragent(contragentId);
        if (!cancelled) setData(detail);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [contragentId]);

  async function handleDelete() {
    setBusy(true);
    try {
      await deleteContragent(contragentId);
      onChanged?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const labelFor = (key, fallback) => {
    if (key === 'reg_number') return regMeta?.[data?.type]?.label ?? fallback;
    // name — «Название компании» для ООО/ТОО, «ФИО / название» для физлиц
    if (key === 'name') return contragentNameLabel(data?.type, companyTypeByCountry);
    return fallback;
  };

  return (
    <Modal
      title={data?.title ?? 'Карточка контрагента'}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={520}
      footer={
        data && (
          <>
            {canDeleteContragents(role) &&
              (confirmDelete ? (
                <>
                  <span className="text-[13px] text-text-muted mr-auto">Удалить безвозвратно?</span>
                  <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
                    Отмена
                  </Button>
                  <Button variant="accent" size="sm" onClick={handleDelete} disabled={busy}>
                    {busy ? 'Удаляем…' : 'Удалить'}
                  </Button>
                </>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(true)}>
                  Удалить
                </Button>
              ))}
            {/* Кнопка «Редактировать» для всех, кто может править хоть что-то:
                полноправным — вся карточка, менеджеру — только тип договора
                (та же модалка сама определяет режим по роли, см.
                EditContragentModal.restricted). */}
            {!confirmDelete && (canEditContragents(role) || canEditContractFamily(role)) && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => openModal('editContragent', { contragent: data, onSaved: onChanged })}
              >
                Редактировать
              </Button>
            )}
            {!confirmDelete && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => openModal('contragentDocs', { contragentId })}
              >
                Документы
              </Button>
            )}
          </>
        )
      }
    >
      {!data && !error && <div className="text-[13px] text-text-muted">Загрузка…</div>}
      {error && <div className="text-[13px] text-accent">{error}</div>}
      {data && (
        <table className="w-full text-sm">
          <tbody>
            {/* Артикул (страна + рег.номер) — будущий единственный идентификатор
                контрагента, виден только админу. Стоит первым и выделен. Пусто
                (нет страны/рег.номера) → «—», чтобы админ видел, что не готов. */}
            {canViewArticle(role) && (
              <tr>
                <td className="text-text-secondary py-1.5 whitespace-nowrap pr-4">Артикул</td>
                <td className="text-right py-1.5 text-text font-semibold tabular-nums">
                  {data.article || '—'}
                </td>
              </tr>
            )}
            {ROWS.map(([key, label]) => (
              <tr key={key}>
                <td className="text-text-secondary py-1.5 whitespace-nowrap pr-4">
                  {labelFor(key, label)}
                </td>
                <td className="text-right py-1.5 text-text">
                  {displayValue(key, data[key])}
                </td>
              </tr>
            ))}
            <tr>
              <td className="text-text-secondary py-1.5 pr-4">Псевдонимы</td>
              <td className="text-right py-1.5 text-text">
                {data.nicknames?.length ? data.nicknames.join(', ') : '—'}
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {/* Реквизиты — сворачиваемый блок под основными полями, скрыт по
          умолчанию (см. RequisitesSection). Только просмотр; правка — по
          кнопке «Редактировать» (EditContragentModal). */}
      {data && (
        <RequisitesSection
          contragentType={data.type}
          values={data.requisites}
          readOnly
          regNumber={data.reg_number}
          regNumberLabel={regMeta?.[data.type]?.label}
        />
      )}
    </Modal>
  );
}
