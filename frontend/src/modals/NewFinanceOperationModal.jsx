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
 * кнопку. Отсюда же и категории: у поступлений и расходов они разные
 * (приходят квартальные отчёты, уходят выплаты), и сервер проверяет
 * категорию против вида.
 *
 * У ПОСТУПЛЕНИЯ ОБЯЗАТЕЛЕН ПЕРИОД — за какой квартал деньги. Дата
 * зачисления на это не отвечает: за I квартал платят в апреле. Если одним
 * платежом закрыли несколько кварталов, включается «за несколько кварталов»
 * и появляется второй конец диапазона.
 *
 * Сумму отправляем строкой, как напечатали: «10 000,50» разберёт сервер.
 * Приводить её к числу здесь нельзя — деньги в double расходятся в копейках.
 *
 * Дата операции по умолчанию сегодняшняя, но меняется: операции регулярно
 * заносят задним числом, и дата внесения хранится отдельно.
 */
const QUARTER_LABELS = ['I квартал', 'II квартал', 'III квартал', 'IV квартал'];

/**
 * Прошлый квартал — он и есть обычный случай: отчёт приходит за квартал,
 * который только что закончился.
 */
function previousQuarter(now = new Date()) {
  const quarter = Math.floor(now.getMonth() / 3) + 1;
  return quarter === 1
    ? { year: now.getFullYear() - 1, quarter: 4 }
    : { year: now.getFullYear(), quarter: quarter - 1 };
}

export function NewFinanceOperationModal({ contragentId, kind, title, onDone, level, isTop }) {
  const { closeModal } = useModal();
  const { finance_categories: categoriesByKind = {}, finance_quarters: quarters = [1, 2, 3, 4] } =
    useTags();

  const income = kind === 'income';
  const options = categoriesByKind?.[kind] ?? [];
  const start = previousQuarter();

  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState('');
  const [occurredOn, setOccurredOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [documentNumber, setDocumentNumber] = useState('');
  const [comment, setComment] = useState('');
  const [yearFrom, setYearFrom] = useState(String(start.year));
  const [quarterFrom, setQuarterFrom] = useState(String(start.quarter));
  const [range, setRange] = useState(false);
  const [yearTo, setYearTo] = useState(String(start.year));
  const [quarterTo, setQuarterTo] = useState(String(start.quarter));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Категория по умолчанию — первая из справочника своего вида. Держим в
  // состоянии только осознанный выбор, чтобы не сбрасывать его, когда
  // справочник догрузится.
  const chosenCategory = category || options[0]?.value || '';

  // Годы для выбора: ближайшие прошлые плюс следующий. Отчёты приходят за
  // недавние кварталы, а руками набирать год — лишний способ опечататься.
  const thisYear = new Date().getFullYear();
  const years = [thisYear + 1, thisYear, thisYear - 1, thisYear - 2, thisYear - 3];

  async function submit() {
    if (!amount.trim()) {
      setError('Укажите сумму.');
      return;
    }
    if (!chosenCategory) {
      setError('Выберите категорию.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await addFinanceOperation(contragentId, {
        kind,
        amount: amount.trim(),
        category: chosenCategory,
        occurredOn,
        documentNumber: documentNumber.trim(),
        comment: comment.trim(),
        period: income
          ? {
              yearFrom,
              quarterFrom,
              // Один квартал — конец не шлём вовсе: сервер продублирует
              // начало сам, и «пусто = один квартал» не расползается по коду.
              yearTo: range ? yearTo : null,
              quarterTo: range ? quarterTo : null,
            }
          : null,
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

        {/* Категория одна — показываем её строкой, а не списком из одного
            пункта: выбор, которого нет, только отвлекает. Появится вторая —
            здесь сам собой окажется обычный селект. */}
        {options.length > 1 ? (
          <Field label="Категория">
            <select
              value={chosenCategory}
              onChange={(e) => setCategory(e.target.value)}
              className={control}
            >
              {options.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <div className="text-[13px]">
            <span className="text-text-muted">Категория: </span>
            <span className="text-text">{options[0]?.label ?? '—'}</span>
          </div>
        )}

        {income && (
          <div className="flex flex-col gap-2">
            <span className="text-xs text-text-secondary">
              {range ? 'Период: с' : 'За какой квартал'}
            </span>
            <div className="flex gap-2">
              <select
                value={quarterFrom}
                onChange={(e) => setQuarterFrom(e.target.value)}
                className={control}
              >
                {quarters.map((q) => (
                  <option key={q} value={String(q)}>
                    {QUARTER_LABELS[q - 1]}
                  </option>
                ))}
              </select>
              <select
                value={yearFrom}
                onChange={(e) => setYearFrom(e.target.value)}
                className={control}
              >
                {years.map((y) => (
                  <option key={y} value={String(y)}>
                    {y}
                  </option>
                ))}
              </select>
            </div>

            {range && (
              <>
                <span className="text-xs text-text-secondary">по</span>
                <div className="flex gap-2">
                  <select
                    value={quarterTo}
                    onChange={(e) => setQuarterTo(e.target.value)}
                    className={control}
                  >
                    {quarters.map((q) => (
                      <option key={q} value={String(q)}>
                        {QUARTER_LABELS[q - 1]}
                      </option>
                    ))}
                  </select>
                  <select
                    value={yearTo}
                    onChange={(e) => setYearTo(e.target.value)}
                    className={control}
                  >
                    {years.map((y) => (
                      <option key={y} value={String(y)}>
                        {y}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <label className="flex items-center gap-2 text-[12.5px] text-text-secondary cursor-pointer">
              <input type="checkbox" checked={range} onChange={(e) => setRange(e.target.checked)} />
              Выплата сразу за несколько кварталов
            </label>
          </div>
        )}

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
