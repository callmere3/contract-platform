import { useModal } from './ModalProvider';
import { NewContragentModal } from './NewContragentModal';
import { ContragentCardModal } from './ContragentCardModal';
import { ContragentDocsModal } from './ContragentDocsModal';
import { ImportExportModal } from './ImportExportModal';
import { NewTemplateModal, NewFolderModal } from './NewTemplateModal';
import { EditTemplateModal } from './EditTemplateModal';

const REGISTRY = {
  newContragent: NewContragentModal,
  contragentCard: ContragentCardModal,
  contragentDocs: ContragentDocsModal,
  importExport: ImportExportModal,
  newTemplate: NewTemplateModal,
  newFolder: NewFolderModal,
  editTemplate: EditTemplateModal,
};

export function ModalRoot() {
  const { stack } = useModal();

  return stack.map((entry, i) => {
    const Component = REGISTRY[entry.name];
    if (!Component) return null;
    // level передаём как индекс в стеке — определяет z-index (модалка поверх модалки)
    return <Component key={i} level={i} {...entry.props} />;
  });
}
