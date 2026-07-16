import { useModal } from './ModalProvider';
import { NewContragentModal } from './NewContragentModal';
import { EditContragentModal } from './EditContragentModal';
import { ContragentCardModal } from './ContragentCardModal';
import { ContragentDocsModal } from './ContragentDocsModal';
import { ImportExportModal } from './ImportExportModal';
import { NewTemplateModal, NewFolderModal } from './NewTemplateModal';
import { EditTemplateModal } from './EditTemplateModal';
import { NewUserModal } from './NewUserModal';
import { ChangePasswordModal } from './ChangePasswordModal';
import { DocumentPreviewModal } from './DocumentPreviewModal';

const REGISTRY = {
  newContragent: NewContragentModal,
  editContragent: EditContragentModal,
  contragentCard: ContragentCardModal,
  contragentDocs: ContragentDocsModal,
  importExport: ImportExportModal,
  newTemplate: NewTemplateModal,
  newFolder: NewFolderModal,
  editTemplate: EditTemplateModal,
  newUser: NewUserModal,
  changePassword: ChangePasswordModal,
  documentPreview: DocumentPreviewModal,
};

export function ModalRoot() {
  const { stack } = useModal();

  return stack.map((entry, i) => {
    const Component = REGISTRY[entry.name];
    if (!Component) return null;
    // level — индекс в стеке, определяет z-index (модалка поверх модалки).
    // isTop — только верхняя модалка реагирует на Escape (см. Modal.jsx).
    return <Component key={i} level={i} isTop={i === stack.length - 1} {...entry.props} />;
  });
}
