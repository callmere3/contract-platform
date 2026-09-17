import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Modal, ModalAction } from '../components/ui/Modal';
import { PencilIcon, TrashIcon } from '../components/ui/icons';
import { Button } from '../components/ui/Button';
import { RequisitesSection } from '../components/ui/RequisitesSection';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { useTags } from '../api/TagsContext';
import {
  canAddFinanceOperations,
  canDeleteContragents,
  canDeleteFinanceOperations,
  canEditContractFamily,
  canEditContragents,
} from '../auth/permissions';
import { deleteFinanceOperation, fetchFinanceCard, formatMoney } from '../api/finance';
import { deleteContragent, getContragent } from '../api/contragents';

/**
 * Карточка контрагента в ML Finance: кто это, по каким реквизитам платить,
 * сколько сейчас баланс и все операции.
 *
 * Полей меньше, чем в карточке ML Docs, и это не урезанная копия: там
 * показывают то, что подставится в документ (тип договора, роялти, даты),
 * здесь — то, по чему платят. Общее только ФИО и никнеймы.
 *
 * Правки операции нет — только удалить и внести заново (и удалять может
 * admin). Денежная строка, которую можно молча переписать, — не история.
 */
export function FinanceContragentModal({ contragentId, level, isTop, onChanged }) {
  const { closeModal, closeAllModals, openModal } = useModal();
  const navigate = useNavigate();
  const { role } = useAuth();
  // Подпись рег. номера зависит от типа контрагента (ИНН / ОГРНИП / ОГРН /
  // БИН) и приходит с сервера — без неё блок реквизитов эту строку не
  // покажет вовсе.
  const { reg_number_meta: regMeta } = useTags();

  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [removing, setRemoving] = useState(null);
  // Удаление САМОЙ КАРТОЧКИ (не операции) — с подтверждением, как в ML Docs.
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setCard(await fetchFinanceCard(contragentId));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [contragentId]);

  useEffect(() => {
    load();
  }, [load]);

  /** Внесли операцию — обновляем и карточку, и список за ней (баланс изменился). */
  const afterChange = useCallback(() => {
    load();
    onChanged?.();
  }, [load, onChanged]);

  /**
   * Правка карточки открывает ТУ ЖЕ модалку, что и в ML Docs: набор полей,
   * права и ограниченный режим для менеджера живут там, и заводить финансам
   * свою форму значило бы держать две правды об одной карточке. Модалке
   * нужна полная карточка (поля документов), а финансовая отдаёт свой набор —
   * поэтому перед открытием дотягиваем её обычным запросом.
   */
  async function openEdit() {
    setBusy(true);
    setError('');
    try {
      const full = await getContragent(contragentId);
      openModal('editContragent', { contragent: full, onSaved: afterChange });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeCard() {
    setBusy(true);
    setError('');
    try {
      await deleteContragent(contragentId);
      onChanged?.();
      closeModal();
    } catch (e) {
      // Сюда прилетает 409 сервера: по контрагенту есть операции или на него
      // ссылается номенклатура. Текст уже человеческий — показываем как есть.
      setError(e.message);
      setConfirmDelete(false);
      setBusy(false);
    }
  }

  async function remove(operationId) {
    setRemoving(operationId);
    setError('');
    try {
      await deleteFinanceOperation(operationId);
      afterChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setRemoving(null);
    }
  }

  const negative = card && Number(card.balance) < 0;

  return (
    <Modal
      title={card ? card.title : 'Контрагент'}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={720}
      actions={
        card && (
          <>
            {(canEditContragents(role) || canEditContractFamily(role)) && (
              <ModalAction icon={<PencilIcon />} title="Редактировать" onClick={openEdit} disabled={busy} />
            )}
            {canDeleteContragents(role) && (
              <ModalAction
                icon={<TrashIcon />}
                title="Удалить"
                danger
                disabled={confirmDelete || busy}
                onClick={() => setConfirmDelete(true)}
              />
            )}
          </>
        )
      }
      footer={
        confirmDelete ? (
          <div className="flex items-center gap-3 w-full">
            <span className="text-[13px] text-text-muted mr-auto">Удалить карточку безвозвратно?</span>
            <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
              Отмена
            </Button>
            <Button variant="accent" size="sm" onClick={removeCard} disabled={busy}>
              {busy ? 'Удаляем…' : 'Удалить'}
            </Button>
          </div>
        ) : (
        <div className="flex items-center gap-3">
          {/* «Треки» уводит в номенклатуру, отфильтрованную по ЭТОЙ карточке.
              Отбор идёт по ссылке track_rights.contragent_id, а не по имени:
              у одного лейбла в выгрузке встречается по два написания, и поиск
              по титлу показал бы не все его треки. Кнопка появляется, только
              если треки есть: пустой переход бессмысленен. */}
          {card?.tracks_count > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                closeAllModals();
                navigate(`/finance?contragent=${contragentId}`);
              }}
            >
              Треки ({card.tracks_count})
            </Button>
          )}
          {canAddFinanceOperations(role) && (
            <>
              <Button
                variant="primary"
                size="sm"
                onClick={() =>
                  openModal('newFinanceOperation', {
                    contragentId,
                    kind: 'income',
                    title: card?.title,
                    onDone: afterChange,
                  })
                }
              >
                + Поступление
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  openModal('newFinanceOperation', {
                    contragentId,
                    kind: 'expense',
                    title: card?.title,
                    onDone: afterChange,
                  })
                }
              >
                + Расход
              </Button>
            </>
          )}
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Закрыть
          </Button>
        </div>
        )
      }
    >
      {loading && <div className="text-[13px] text-text-muted">Загружаем…</div>}
      {error && <div className="text-[13px] text-danger mb-3">{error}</div>}

      {!loading && card && (
        <div className="flex flex-col gap-5">
          {/* Баланс крупно: за ним сюда и приходят. Рядом — из чего сложился,
              иначе «−3 000» ничего не объясняет. */}
          <div className="flex items-end justify-between gap-4 p-4 rounded-input border border-border">
            <div>
              <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-muted">
                Текущий баланс
              </div>
              <div
                className={`text-[26px] font-semibold tabular-nums mt-1 ${
                  negative ? 'text-danger' : 'text-text'
                }`}
              >
                {formatMoney(card.balance)}
              </div>
            </div>
            <div className="text-[12.5px] text-text-muted text-right leading-relaxed tabular-nums">
              <div>поступления: {formatMoney(card.income_total)}</div>
              <div>расходы: {formatMoney(card.expense_total)}</div>
            </div>
          </div>

          <section className="flex flex-col gap-1.5">
            <Row label="ФИО / название" value={card.name} />
            <Row label="Псевдонимы" value={card.nicknames.join(', ')} />
            <Row label="Страна и тип" value={[card.country, card.type].filter(Boolean).join(' · ')} />
            {/* Связка с Dista переехала сюда из карточки ML Docs (17.09.2026):
                там она была чужой — ML Docs про договоры, а Dista про каталог
                и деньги. Рядом с ней и живёт всё остальное дистовское:
                «Dista Connect» и номенклатура. «Исключён из Dista» — не то же
                самое, что пусто: это решение человека, а не пробел в данных. */}
            <Row
              label="Dista ID"
              value={card.dista_id || (card.dista_excluded ? 'исключён из Dista' : '')}
            />
          </section>

          {/* Реквизиты рисует тот же компонент, что и в ML Docs: набор полей
              приходит с сервера по типу контрагента, фронт его не хардкодит.
              Здесь блок раскрыт сразу — платят именно по нему. */}
          <RequisitesSection
            contragentType={card.type}
            values={card.requisites}
            regNumber={card.reg_number}
            regNumberLabel={regMeta?.[card.type]?.label}
            readOnly
            defaultOpen
          />

          <section className="flex flex-col gap-2">
            <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-muted">
              Операции
            </div>

            {card.operations.length === 0 && (
              <div className="text-[13px] text-text-muted">
                Операций пока нет. Поступления и расходы вносятся кнопками внизу.
              </div>
            )}

            {card.operations.map((op) => (
              <Operation
                key={op.id}
                operation={op}
                canDelete={canDeleteFinanceOperations(role)}
                busy={removing === op.id}
                onDelete={() => remove(op.id)}
              />
            ))}
          </section>
        </div>
      )}
    </Modal>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline gap-3 text-[13.5px]">
      <span className="w-[140px] flex-shrink-0 text-text-muted">{label}</span>
      <span className="text-text">{value || '—'}</span>
    </div>
  );
}

/**
 * Одна операция: дата и категория слева, сумма со знаком справа.
 *
 * Сумма приходит положительной, знак несёт kind — так же, как хранится в
 * базе. Рисуем его сами типографским минусом (−), а не берём готовый
 * signed_amount: у того обычный дефис, который в колонке цифр выглядит
 * короткой чёрточкой не на своём месте.
 */
function Operation({ operation, canDelete, busy, onDelete }) {
  const income = operation.kind === 'income';

  return (
    <div className="flex items-start justify-between gap-4 px-3.5 py-3 rounded-input border border-border">
      <div className="min-w-0">
        <div className="text-[13.5px] text-text">
          {operation.category_label}
          {/* Период — за какие кварталы деньги. Подпись собрал сервер: формат
              периода такое же правило, как правило знака суммы, и разъезжаться
              ему в двух местах незачем. У расходов периода нет. */}
          {operation.period_label && (
            <span className="text-text-secondary"> · за {operation.period_label}</span>
          )}
          {operation.document_number && (
            <span className="text-text-muted"> · {operation.document_number}</span>
          )}
        </div>
        {operation.comment && (
          <div className="text-[12.5px] text-text-secondary mt-0.5 break-words">
            {operation.comment}
          </div>
        )}
        <div className="text-[11.5px] text-text-muted mt-1">
          {formatDate(operation.occurred_on)}
          {operation.created_by && ` · внёс(ла) ${operation.created_by}`}
        </div>
      </div>

      <div className="flex items-center gap-2.5 flex-shrink-0">
        <span
          className={`text-[14px] font-semibold tabular-nums ${
            income ? 'text-success' : 'text-danger'
          }`}
        >
          {income ? '+' : '−'}
          {formatMoney(operation.amount)}
        </span>
        {canDelete && (
          <button
            type="button"
            disabled={busy}
            onClick={onDelete}
            title="Удалить операцию"
            aria-label="Удалить операцию"
            className="w-6 h-6 flex items-center justify-center rounded-full bg-transparent border-none cursor-pointer text-[13px] text-text-muted hover:text-danger font-sans"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/** «2026-09-05» → «05.09.2026». */
function formatDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(iso);
}
