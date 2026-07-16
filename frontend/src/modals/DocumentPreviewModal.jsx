import { useEffect, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { recreateGeneratedDocument } from '../api/generationHistory';

/**
 * Предпросмотр документа из "Истории генерации" — прямо в браузере, без
 * скачивания (Admin/Director, как и вся вкладка).
 *
 * ПОЧЕМУ ВСЕГДА PDF, даже если документ генерировали в .docx: браузер не
 * умеет показывать .docx, встроенный просмотрщик есть только у PDF. То
 * есть превью — это всегда PDF-версия того же самого рендера. Кнопки
 * скачивания docx/pdf в строке истории остаются на месте.
 *
 * ПОЧЕМУ blob, а не <iframe src="/generation-history/{id}/recreate">:
 * эндпоинт закрыт JWT, а iframe не отправит заголовок Authorization —
 * получили бы 401. Поэтому качаем через apiFetch (он и токен приложит, и
 * обновит его при 401, см. api/client.js) и отдаём iframe blob:-ссылку.
 * Заодно это обошло Content-Disposition: attachment на бэкенде: с blob'ом
 * заголовок не участвует, и менять бэкенд ради превью не пришлось.
 *
 * Документ пересоздаётся на лету (готовые файлы нигде не хранятся) плюс
 * конвертируется в PDF через LibreOffice — это пара секунд, поэтому
 * состояние загрузки здесь обязательно, а не для красоты.
 *
 * Высота задана фиксированной (60vh), а не через flex: базовая Modal
 * ограничена max-h-[85vh] и не растягивает тело по высоте. Подгонять её
 * ради одного экрана незачем — под ней десяток других модалок.
 */
export function DocumentPreviewModal({ entry, level, isTop }) {
  const { closeModal } = useModal();
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let objectUrl = '';
    let cancelled = false;

    (async () => {
      try {
        const blob = await recreateGeneratedDocument(entry.id, 'pdf');
        objectUrl = URL.createObjectURL(blob);
        // Модалку могли закрыть, пока шла конвертация — тогда ссылку
        // нужно освободить сразу, иначе она утечёт мимо cleanup ниже
        // (тот увидит objectUrl ещё пустым).
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setUrl(objectUrl);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();

    // Освобождаем blob при закрытии: иначе документ висит в памяти
    // вкладки до перезагрузки страницы.
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [entry.id]);

  function download() {
    // Файл уже здесь — качаем из того же blob'а, второй раз сервер не
    // дёргаем. URL не освобождаем: модалка ещё открыта и показывает его.
    const a = document.createElement('a');
    a.href = url;
    a.download = `${entry.template_name}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  const subtitle = [entry.contragent_title, entry.nickname].filter(Boolean).join(' · ');

  return (
    <Modal
      title={entry.template_name}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={900}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Закрыть
          </Button>
          <Button variant="primary" size="sm" onClick={download} disabled={!url}>
            Скачать PDF
          </Button>
        </>
      }
    >
      {subtitle && <div className="text-[13px] text-text-secondary mb-4">{subtitle}</div>}

      {!url && !error && (
        <div className="h-[60vh] flex items-center justify-center text-[13px] text-text-muted">
          Собираем документ и конвертируем в PDF…
        </div>
      )}

      {error && (
        <div className="h-[60vh] flex items-center justify-center px-8 text-[13px] text-accent text-center leading-snug">
          {error}
        </div>
      )}

      {url && (
        <iframe
          src={url}
          title="Предпросмотр документа"
          className="w-full h-[60vh] border border-border rounded-input bg-white"
        />
      )}
    </Modal>
  );
}
