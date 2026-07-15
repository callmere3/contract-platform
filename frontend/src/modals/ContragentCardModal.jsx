import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { useAuth } from '../auth/AuthContext';
import { canDeleteContragents, canEditContragents } from '../auth/permissions';
import { deleteContragent, getContragent } from '../api/contragents';

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
 * Карточка контрагента: просмотр всех полей + действия по правам.
 * Открывается по клику на строку в "Базе контрагентов".
 *
 * Данные грузятся по contragent_id, а не приходят готовыми из списка:
 * в списке (search_contragents) нет ни даты, ни роялти, ни номера договора —
 * только summary. Заодно карточка всегда свежая, даже если список устарел.
 */
export function ContragentCardModal({ contragentId, level, isTop, onDeleted }) {
  const { closeModal, openModal } = useModal();
  const { reg_number_meta: regMeta } = useTags();
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
      onDeleted?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const labelFor = (key, fallback) =>
    key === 'reg_number' ? (regMeta?.[data?.type]?.label ?? fallback) : fallback;

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
            {!confirmDelete && canEditContragents(role) && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => openModal('editContragent', { contragent: data })}
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
            {ROWS.map(([key, label]) => (
              <tr key={key}>
                <td className="text-text-secondary py-1.5 whitespace-nowrap pr-4">
                  {labelFor(key, label)}
                </td>
                <td className="text-right py-1.5 text-text">
                  {data[key] === null || data[key] === '' || data[key] === undefined
                    ? '—'
                    : String(data[key])}
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
    </Modal>
  );
}
