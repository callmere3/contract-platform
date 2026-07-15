import { useState } from 'react';
import { ThemeProvider } from './theme/ThemeContext';
import { ModalProvider, useModal } from './modals/ModalProvider';
import { ModalRoot } from './modals/ModalRoot';
import { Header } from './layout/Header';
import { SearchPage } from './pages/SearchPage';
import { DatabasePage } from './pages/DatabasePage';
import { FoldersPage } from './pages/FoldersPage';
import { DocFormPage } from './pages/DocFormPage';

// Мок-данные только для визуальной проверки на этапе scaffold —
// в реальной версии заменяются на данные из API (src/api/*).
const MOCK_CONTRAGENTS = [
  { id: 1, name: 'Ааа Б. В. (ИП)', alias: 'abvvba', code: 'РУ · ИП · АВАНС' },
  { id: 2, name: 'Ибара М. Ж. (СГ)', alias: 'RE3, Irridia', code: 'РУ · СГ · РОЯЛТИ', inn: '771234567890' },
  { id: 3, name: 'Петров П. П. (СГ)', alias: '', code: 'РУ · СГ · АВАНС ОБЯЗАТЕЛЬСТВО' },
];

const MOCK_FOLDERS = [
  { id: 1, name: 'КЗ' },
  { id: 2, name: 'РУ' },
  { id: 3, name: 'ТЕСТ' },
];

function AppShell() {
  const [tab, setTab] = useState('search');
  const [docForm, setDocForm] = useState(null); // { template, contragent } | null
  const { openModal } = useModal();

  // Клик по табу в шапке всегда возвращает к обычным вкладкам —
  // форма генерации это временный "экран поверх", а не отдельный таб.
  const handleTabChange = (nextTab) => {
    setDocForm(null);
    setTab(nextTab);
  };

  // Общий колбэк для перехода в форму генерации — используется и из
  // модалки "Документы контрагента" (через стек модалок), и с прямого
  // клика по папке на вкладке "Папки".
  const openDocForm = (template, contragent) => {
    setDocForm({ template: template ?? null, contragent: contragent ?? null });
  };

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      <Header activeTab={tab} onTabChange={handleTabChange} />

      {docForm ? (
        <DocFormPage
          templateCode={docForm.template?.code}
          contragent={docForm.contragent}
          onBack={() => setDocForm(null)}
          onGenerate={(payload) => console.log('generate', payload)}
        />
      ) : (
        <>
          {tab === 'search' && (
            <SearchPage onOpenNewContragent={() => openModal('newContragent')} />
          )}
          {tab === 'database' && (
            <DatabasePage
              contragents={MOCK_CONTRAGENTS}
              onOpenImportExport={() => openModal('importExport')}
              onOpenContragent={(contragent) =>
                openModal('contragentCard', { contragent, onOpenDocForm: openDocForm })
              }
            />
          )}
          {tab === 'folders' && (
            <FoldersPage
              folders={MOCK_FOLDERS}
              onNewFolder={() => openModal('newFolder')}
              onNewTemplate={() => openModal('newTemplate', { folders: MOCK_FOLDERS })}
              onOpenTemplate={() => openDocForm()}
            />
          )}
        </>
      )}

      <ModalRoot />
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="dark">
      <ModalProvider>
        <AppShell />
      </ModalProvider>
    </ThemeProvider>
  );
}
