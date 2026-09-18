import { useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { deleteReport } from '../api/partnerReports';
import { formatMoney } from '../api/finance';

/**
 * «Удалить отчёт?» — своим окном, а не браузерным `confirm` (просьба
 * владельца 18.09.2026). Дело не только во внешнем виде: системное окно умеет
 * показать одну строку текста, а решение здесь принимают, глядя на сам
 * отчёт — чья площадка, за какой период и на какую сумму. Заодно оно
 * подчиняется общим правилам стека модалок: Escape, кнопка «назад», затемнение.
 *
 * УДАЛЯЕТ САМО, как карточка партнёра: страница только перечитывает список.
 * Иначе состояние «удаляем…» и текст ошибки пришлось бы держать на странице,
 * то есть в двух местах сразу.
 *
 * Правки отчёта нет вовсе — только удалить и загрузить заново, — поэтому
 * удаление здесь обычное дело, а не крайняя мера: об этом прямо сказано в
 * окне, чтобы человек не искал кнопку «исправить».
 */
export function ConfirmDeleteReportModal({ report, level, isTop, onDeleted }) {
  const { closeModal } = useModal();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function remove() {
    setBusy(true);
    setError('');
    try {
      await deleteReport(report.id);
      closeModal();
      onDeleted?.();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Удалить отчёт?"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={480}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal} disabled={busy}>
            Отмена
          </Button>
          <Button variant="accent" size="sm" onClick={remove} disabled={busy}>
            {busy ? 'Удаляем…' : 'Удалить'}
          </Button>
        </>
      }
    >
      <div className="text-[13px] text-text leading-relaxed">
        <div className="mb-3">
          <b>{report.partner}</b> · {report.period_label}
        </div>
        <div className="text-text-secondary">Файл: {report.file_name}</div>
        <div className="text-text-secondary">
          Строк: {report.rows_count} · авторские {formatMoney(report.total_author)} · смежные{' '}
          {formatMoney(report.total_related)}
        </div>
        <div className="mt-3 text-text-muted">
          Отчёт удалится вместе со всеми строками. Загрузить его заново можно тем же файлом —
          правки у отчётов нет по замыслу.
        </div>
        {error && <div className="text-danger mt-3">{error}</div>}
      </div>
    </Modal>
  );
}
