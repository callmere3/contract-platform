import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useTags } from '../api/TagsContext';
import { addFinanceOperation } from '../api/finance';

/**
 * Внести поступление или расход по контрагенту.
 *
 * Вид операции (приход/расход) задаётся ПРИ ОТКРЫТИИ и здесь не
 * переключается: человек нажал «+ Расход», и предлагать ему передумать в
 * той же форме — лишний способ ошибиться. Ошибся — закрыл и нажал другую
 * кнопку.
 *
 * Сумму отправляем строкой, как напечатали: «10 000,50» разберёт сервер.
 * Приводить её к числу здесь нельзя — деньги в double расходятся в копейках.
 *
 * Дата операции по умолчанию сегодняшняя, но меняется: операции регулярно
 * заносят задним числом, и дата внесения хранится отдельно.
 */
export function NewFinanceOperationModal({ contragentId, kind, title, onDone, level, isTop }) {
  const { closeModal } = useModal();
  const { finance_categories: categories = [] } = useTags();

  const income = kind === 'income';
  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState(income ? 'royalty' : 'advance');
  const [occurredOn, setOccurredOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [documentNumber, setDocumentNumber] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit() {
    if (!amount.trim()) {
      setError('Укажите сумму.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await addFinanceOperation(contragentId, {
        kind,
        amount: amount.trim(),
        category,
        occurredOn,
        documentNumber: documentNumber.trim(),
        comment: comment.trim(),
      });
      onDone?.();
      closeModal();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const control =
    'w-full bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text outline-none font-sans';

  return (
    <Modal
      title={income ? 'Поступление' : 'Расход'}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={460}
      footer={
        <div className="flex items-center gap-3">
          <Button variant="primary" size="sm" disabled={busy} onClick={submit}>
            {busy ? 'Сохраняем…' : 'Внести'}
          </Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={closeModal}>
            Отмена
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {title && (
          <div className="text-[13px] text-text-muted">
            Контрагент: <span className="text-text">{title}</span>
          </div>
        )}

        <Field label="Сумма, ₽">
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            // Не type="number": он глотает пробелы и запятую, а именно так
            // суммы и печатают. Разбирает строку сервер.
            inputMode="decimal"
            placeholder="10 000,50"
            autoFocus
            className={control}
          />
        </Field>

        <Field label="Категория">
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={control}>
            {categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Дата операции">
          <input
            type="date"
            value={occurredOn}
            onChange={(e) => setOccurredOn(e.target.value)}
            className={control}
          />
        </Field>

        <Field label="Номер документа">
          <input
            value={documentNumber}
            onChange={(e) => setDocumentNumber(e.target.value)}
            placeholder="счёт, акт — если есть"
            className={control}
          />
        </Field>

        <Field label="Комментарий">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="за что"
            className={`${control} resize-y leading-relaxed`}
          />
        </Field>

        {error && <div className="text-[13px] text-danger">{error}</div>}
      </div>
    </Modal>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs text-text-secondary">{label}</span>
      {children}
    </label>
  );
}
