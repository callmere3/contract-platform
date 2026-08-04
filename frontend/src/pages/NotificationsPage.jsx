import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import {
  applyNotification,
  dismissNotification,
  emitNotificationsChanged,
  listNotifications,
} from '../api/notifications';

/**
 * "Уведомления" — только admin (см. canViewNotifications / CAN_VIEW_NOTIFICATIONS).
 *
 * Предложения дозаполнить карточку контрагента данными, которые менеджер вписал
 * в форму генерации. Две ситуации, по-разному оформленные (severity с бэкенда):
 *   suggestion — поле карточки пустое, значение валидно: кнопки Применить/Отклонить;
 *   warning    — значение кривое или расходится с уже заполненной карточкой:
 *                ⚠ с причиной, применить нельзя (только Скрыть — админ разобрался).
 *
 * Сгруппировано по контрагенту: у одного человека может накопиться несколько
 * недостающих полей, удобнее видеть их вместе.
 *
 * После каждого действия шлём window-событие (emitNotificationsChanged), чтобы
 * бейдж-счётчик в шапке обновился сразу, не дожидаясь своего опроса.
 */
export function NotificationsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setItems(await listNotifications());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(id, fn) {
    setBusyId(id);
    setError('');
    try {
      await fn(id);
      // Убираем обработанную запись из списка сразу, без полного перезапроса —
      // отзывчивее, а остальные строки не мигают.
      setItems((list) => list.filter((i) => i.id !== id));
      emitNotificationsChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  }

  /**
   * «Применить все» для группы контрагента — по просьбе владельца («выборочно
   * ИЛИ целиком»). Применяем только actionable-строки (severity=suggestion):
   * ⚠-предупреждения (расхождение/кривой ввод) применять нельзя, их пропускаем.
   * Последовательно, чтобы reg_number-уникальность и т.п. не гонялись параллельно.
   */
  async function applyGroup(rows) {
    const actionable = rows.filter((r) => r.severity === 'suggestion');
    if (actionable.length === 0) return;
    setBusyId(`group:${rows[0].contragent_id}`);
    setError('');
    const doneIds = [];
    try {
      for (const r of actionable) {
        await applyNotification(r.id);
        doneIds.push(r.id);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      if (doneIds.length) {
        setItems((list) => list.filter((i) => !doneIds.includes(i.id)));
        emitNotificationsChanged();
      }
      setBusyId(null);
    }
  }

  // Группировка по контрагенту с сохранением порядка (первое появление).
  const groups = useMemo(() => {
    const byId = new Map();
    for (const it of items) {
      if (!byId.has(it.contragent_id)) {
        byId.set(it.contragent_id, { id: it.contragent_id, title: it.contragent_title, rows: [] });
      }
      byId.get(it.contragent_id).rows.push(it);
    }
    return [...byId.values()];
  }, [items]);

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between p-5 border-b border-border">
          <span className="text-sm font-semibold text-text">Уведомления</span>
          {!loading && items.length > 0 && (
            <span className="text-[13px] text-text-muted">{items.length}</span>
          )}
        </div>

        {loading && <div className="px-5 py-4 text-[13px] text-text-muted">Загрузка…</div>}
        {!loading && error && <div className="px-5 py-4 text-[13px] text-danger">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="px-5 py-8 text-[13px] text-text-muted text-center">
            Новых уведомлений нет. Здесь появятся данные, которые менеджеры вписывают
            в форму генерации, — чтобы дозаполнить ими карточки контрагентов.
          </div>
        )}

        {!loading &&
          groups.map((g) => {
            const actionable = g.rows.filter((r) => r.severity === 'suggestion').length;
            const groupBusy = busyId === `group:${g.id}`;
            return (
            <div key={g.id} className="border-b border-border last:border-b-0">
              <div className="px-5 pt-4 pb-2 flex items-center justify-between gap-3">
                <span className="text-[13px] font-semibold text-text">{g.title}</span>
                {actionable > 1 && (
                  <Button variant="secondary" size="sm" disabled={groupBusy} onClick={() => applyGroup(g.rows)}>
                    {groupBusy ? 'Применяем…' : `Применить все (${actionable})`}
                  </Button>
                )}
              </div>
              {g.rows.map((it) => (
                <NotificationRow
                  key={it.id}
                  item={it}
                  busy={busyId === it.id}
                  onApply={() => act(it.id, applyNotification)}
                  onDismiss={() => act(it.id, dismissNotification)}
                />
              ))}
            </div>
            );
          })}
      </Card>

      <div className="text-[11px] text-text-muted mt-4 leading-snug">
        «Применить» переносит значение в карточку контрагента (титл и номер договора
        не затрагиваются). ⚠ — менеджер вписал значение, которое не проходит проверку
        или расходится с карточкой: применить нельзя, это повод проверить документ.
      </div>
    </div>
  );
}

function NotificationRow({ item, busy, onApply, onDismiss }) {
  const isWarning = item.severity === 'warning';
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3.5 border-t border-border first:border-t-0">
      <div className="min-w-0">
        <div className="text-[14px] text-text flex items-center gap-2 flex-wrap">
          <span className="text-text-muted">{item.field_label}:</span>
          <span className="font-semibold">{item.value_display}</span>
          {isWarning && <Badge variant="danger">⚠ {item.reason}</Badge>}
        </div>
        <div className="text-[12px] text-text-muted mt-0.5 flex items-center gap-1.5 flex-wrap">
          {item.card_current_display && (
            <>
              <span>в карточке: {item.card_current_display}</span>
              <span className="text-border">·</span>
            </>
          )}
          {item.suggested_by && <span>вписал(а) {item.suggested_by}</span>}
        </div>
      </div>

      <div className="flex items-center gap-2.5 flex-shrink-0">
        {isWarning ? (
          <Button variant="secondary" size="sm" disabled={busy} onClick={onDismiss}>
            Скрыть
          </Button>
        ) : (
          <>
            <Button variant="primary" size="sm" disabled={busy} onClick={onApply}>
              Применить
            </Button>
            <Button variant="secondary" size="sm" disabled={busy} onClick={onDismiss}>
              Отклонить
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
