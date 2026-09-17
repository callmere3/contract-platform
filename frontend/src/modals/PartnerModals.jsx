import { useState } from 'react';
import { Modal, ModalAction } from '../components/ui/Modal';
import { PencilIcon, TrashIcon } from '../components/ui/icons';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { canManagePartners } from '../auth/permissions';
import {
  createPartner,
  deletePartner,
  exportPartners,
  importPartners,
  renamePartner,
} from '../api/partners';

/**
 * Окна справочника партнёров — все три в одном файле намеренно: у партнёра
 * одно поле, и каждая из этих модалок — это подпись, поле ввода и кнопка.
 * Разложенные по трём файлам, они состояли бы из импортов.
 */

/**
 * Карточка партнёра: имя, переименование и удаление.
 *
 * Свойств у партнёра нет, поэтому «карточка» — это, по сути, его имя и два
 * значка в шапке. Правка открывается прямо здесь, а не отдельной модалкой:
 * ради одного поля городить второе окно поверх первого незачем.
 */
export function PartnerCardModal({ partner, level, isTop, onChanged }) {
  const { closeModal } = useModal();
  const { role } = useAuth();

  const [name, setName] = useState(partner.name);
  const [distaId, setDistaId] = useState(partner.dista_id ?? '');
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const manage = canManagePartners(role);

  async function save() {
    setBusy(true);
    setError('');
    try {
      await renamePartner(partner.id, name.trim(), distaId.trim());
      onChanged?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError('');
    try {
      await deletePartner(partner.id);
      onChanged?.();
      closeModal();
    } catch (e) {
      setError(e.message);
      setConfirmDelete(false);
      setBusy(false);
    }
  }

  return (
    <Modal
      title={partner.name}
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={440}
      actions={
        manage && (
          <>
            <ModalAction
              icon={<PencilIcon />}
              title="Переименовать"
              disabled={editing || confirmDelete}
              onClick={() => setEditing(true)}
            />
            <ModalAction
              icon={<TrashIcon />}
              title="Удалить"
              danger
              disabled={confirmDelete || busy}
              onClick={() => setConfirmDelete(true)}
            />
          </>
        )
      }
      footer={
        confirmDelete ? (
          <>
            <span className="text-[13px] text-text-muted mr-auto">Удалить партнёра?</span>
            <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
              Отмена
            </Button>
            <Button variant="accent" size="sm" onClick={remove} disabled={busy}>
              {busy ? 'Удаляем…' : 'Удалить'}
            </Button>
          </>
        ) : editing ? (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setName(partner.name);
                setDistaId(partner.dista_id ?? '');
                setEditing(false);
              }}
            >
              Отмена
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={busy || !name.trim()}>
              {busy ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </>
        ) : (
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Закрыть
          </Button>
        )
      }
    >
      {editing ? (
        <div className="flex flex-col gap-4">
          <NameField value={name} onChange={setName} onSubmit={save} />
          <DistaField value={distaId} onChange={setDistaId} onSubmit={save} />
        </div>
      ) : (
        /* Только код. Пояснение «почему у партнёра больше ничего нет» убрано
           (просьба владельца 17.09.2026): его читают один раз, а висело оно в
           каждой карточке. Причина по-прежнему записана в CLAUDE.md. */
        <div className="text-[13px]">
          <span className="text-text-secondary">Код в Dista: </span>
          <span className="text-text tabular-nums">{partner.dista_id || 'не проставлен'}</span>
        </div>
      )}
      {error && <div className="text-[13px] text-danger mt-3">{error}</div>}
    </Modal>
  );
}

/** Завести партнёра: одно поле и кнопка. */
export function NewPartnerModal({ level, isTop, onSaved }) {
  const { closeModal } = useModal();
  const [name, setName] = useState('');
  const [distaId, setDistaId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function save() {
    setBusy(true);
    setError('');
    try {
      await createPartner(name.trim(), distaId.trim());
      onSaved?.();
      closeModal();
    } catch (e) {
      // 409 — партнёр с таким именем уже есть; текст сервера человеческий.
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Новый партнёр"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={440}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={closeModal}>
            Отмена
          </Button>
          <Button variant="primary" size="sm" onClick={save} disabled={busy || !name.trim()}>
            {busy ? 'Сохраняем…' : 'Добавить'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <NameField value={name} onChange={setName} onSubmit={save} autoFocus />
        {/* Код можно не знать сейчас — проставят при сверке. Обязательным его
            делать нельзя: часть площадок живёт у нас и без Dista. */}
        <DistaField value={distaId} onChange={setDistaId} onSubmit={save} />
      </div>
      {error && <div className="text-[13px] text-danger mt-3">{error}</div>}
    </Modal>
  );
}

/**
 * Импорт и экспорт справочника.
 *
 * Файл в одну колонку, поэтому и окно простое: без предпросмотра, который
 * нужен номенклатуре. Там строка переписывает состав прав у трека, а здесь
 * самое страшное — лишнее имя в списке, и оно видно сразу.
 */
export function PartnersImportExportModal({ level, isTop, onImported }) {
  const { closeModal } = useModal();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [report, setReport] = useState(null);

  async function handleExport() {
    setBusy(true);
    setError('');
    try {
      const blob = await exportPartners();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'partners.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(file) {
    if (!file) return;
    setBusy(true);
    setError('');
    setReport(null);
    try {
      setReport(await importPartners(file));
      onImported?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Импорт / экспорт партнёров"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={480}
    >
      <div className="mb-6 pb-6 border-b border-border">
        <div className="text-sm font-semibold text-text mb-1.5">Экспорт</div>
        <div className="text-[13px] text-text-secondary mb-3">
          Выгрузить справочник в Excel — ровно в том виде, в каком его принимает импорт: код
          Dista первой колонкой, название второй.
        </div>
        <Button variant="secondary" size="sm" onClick={handleExport} disabled={busy}>
          {busy ? 'Готовим файл…' : 'Скачать .xlsx'}
        </Button>
      </div>

      <div className="text-sm font-semibold text-text mb-1.5">Импорт</div>
      <div className="text-[13px] text-text-secondary mb-3">
        Две колонки: сначала код Dista, потом название — по строке на партнёра. Шапка
        необязательна, код можно не заполнять. Сопоставление идёт сначала по коду, потом по
        названию: знакомый код переименует партнёра, знакомое название получит код.
      </div>
      <label className="inline-block">
        <input
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(e) => handleImport(e.target.files?.[0])}
        />
        <span className="inline-block px-3.5 py-2 rounded-input border border-border text-[13px] text-text cursor-pointer">
          {busy ? 'Читаем…' : 'Выбрать файл .xlsx'}
        </span>
      </label>

      {report && (
        <div className="mt-4 text-[13px] text-text">
          Добавлено: <b>{report.created}</b> · обновлено: <b>{report.updated}</b> · без изменений:{' '}
          <b>{report.skipped}</b>
          {report.names.length > 0 && (
            <div className="text-[12.5px] text-text-secondary mt-1.5">
              {report.names.join(', ')}
            </div>
          )}
          {report.conflicts?.length > 0 && (
            <div className="text-[12.5px] text-danger mt-2">
              Пропущены из-за конфликта: {report.conflicts.join('; ')}
            </div>
          )}
        </div>
      )}
      {error && <div className="text-[13px] text-danger mt-3">{error}</div>}
    </Modal>
  );
}

/** Код Dista: необязателен, проставляется при сверке. */
function DistaField({ value, onChange, onSubmit }) {
  return (
    <label className="block">
      <span className="block text-[12.5px] text-text-secondary mb-1.5">Код в Dista</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSubmit();
        }}
        placeholder="необязательно"
        className="w-full bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans tabular-nums"
      />
    </label>
  );
}


/** Поле имени: Enter сохраняет — окно из одного поля, тянуться к кнопке незачем. */
function NameField({ value, onChange, onSubmit, autoFocus = false }) {
  return (
    <label className="block">
      <span className="block text-[12.5px] text-text-secondary mb-1.5">Название</span>
      <input
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && value.trim()) onSubmit();
        }}
        placeholder="Яндекс Музыка"
        className="w-full bg-input-bg border border-border rounded-input px-3.5 py-2.5 text-sm text-text outline-none font-sans"
      />
    </label>
  );
}
