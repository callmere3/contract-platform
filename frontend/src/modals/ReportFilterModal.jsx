import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';

/**
 * «Настройка фильтра данных» для списка загруженных отчётов — по образцу
 * Dista (скриншот владельца 24.09.2026).
 *
 * СТРОКА НА КОЛОНКУ, а не набор разных полей: так видно сразу все условия
 * разом и то, что большинство колонок не ограничено. Именно этого не хватало
 * в прежнем виде списка, где отбирали только по площадке и кварталу.
 *
 * УСЛОВИЕ — ПОДСТРОКА, без учёта регистра. Ни языка запросов, ни сравнений
 * «больше-меньше» здесь нет намеренно: отбирают по площадке, территории и
 * виду использования — то есть по словам. Понадобится сравнение сумм —
 * заводить его надо отдельно и осознанно, а не расширением этого поля.
 *
 * ЧЕТЫРЕ КНОПКИ, КАК В DISTA, и каждая отвечает на свой вопрос: «Включить» —
 * применить и включить, «Выключить» — оставить условия, но перестать
 * фильтровать (их не приходится набирать заново), «Очистить» — стереть
 * условия, «Отмена» — уйти, ничего не тронув.
 */
export function ReportFilterModal({ columns, value, level, isTop, onApply }) {
  const { closeModal } = useModal();
  const [draft, setDraft] = useState(value ?? {});

  const set = (key, text) =>
    setDraft((prev) => {
      const next = { ...prev };
      if (text) next[key] = text;
      else delete next[key];
      return next;
    });

  function apply(on) {
    onApply?.(draft, on);
    closeModal();
  }

  const input =
    'w-full bg-input-bg border border-border rounded-input px-2 py-1 text-[12.5px] text-text outline-none font-sans';

  return (
    <Modal
      title="Настройка фильтра данных"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={560}
      footer={
        <>
          <Button
            variant="secondary"
            size="sm"
            className="mr-auto"
            onClick={() => setDraft({})}
          >
            Очистить
          </Button>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="secondary" size="sm" onClick={() => apply(false)}>
            Выключить
          </Button>
          <Button size="sm" onClick={() => apply(true)}>
            Включить
          </Button>
        </>
      }
    >
      <div className="border border-border rounded-card overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-[11px] uppercase tracking-[0.04em] text-text-muted font-semibold px-3 py-1.5 border-b border-border w-[45%]">
                Колонка
              </th>
              <th className="text-left text-[11px] uppercase tracking-[0.04em] text-text-muted font-semibold px-3 py-1.5 border-b border-border">
                Условия
              </th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.key}>
                <td className="px-3 py-1 border-t border-border text-[12.5px] text-text">
                  {c.label}
                </td>
                <td className="px-3 py-1 border-t border-border">
                  <input
                    value={draft[c.key] ?? ''}
                    onChange={(e) => set(c.key, e.target.value)}
                    className={input}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-[12px] text-text-muted mt-3">
        Совпадение по части значения, регистр не важен. Пустое поле — колонка
        не ограничена.
      </div>
    </Modal>
  );
}
