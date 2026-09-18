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
import { ConfirmExitDraftModal } from './ConfirmExitDraftModal';
import { ConfirmDuplicateContragentModal } from './ConfirmDuplicateContragentModal';
import { ChampionModal } from './ChampionModal';
import { ProfileModal } from './ProfileModal';
import { UserProfileModal } from './UserProfileModal';
import { AchievementModal } from './AchievementModal';
import { GuideModal } from './GuideModal';
import { FinanceContragentModal } from './FinanceContragentModal';
import { NewFinanceOperationModal } from './NewFinanceOperationModal';
import { TrackCardModal } from './TrackCardModal';
import { NomenclatureImportExportModal } from './NomenclatureImportExportModal';
import {
  NewPartnerModal,
  PartnerCardModal,
  PartnersImportExportModal,
} from './PartnerModals';
import { ConfirmDeleteReportModal } from './ConfirmDeleteReportModal';
import { ConfirmModal } from './ConfirmModal';
import { LinkReportPaymentModal } from './LinkReportPaymentModal';
import { AlertModal } from './AlertModal';

const REGISTRY = {
  alert: AlertModal,
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
  confirmExitDraft: ConfirmExitDraftModal,
  confirmDuplicateContragent: ConfirmDuplicateContragentModal,
  champion: ChampionModal,
  profile: ProfileModal,
  userProfile: UserProfileModal,
  achievement: AchievementModal,
  guide: GuideModal,
  financeContragent: FinanceContragentModal,
  newFinanceOperation: NewFinanceOperationModal,
  trackCard: TrackCardModal,
  nomenclatureImportExport: NomenclatureImportExportModal,
  partnerCard: PartnerCardModal,
  newPartner: NewPartnerModal,
  partnersImportExport: PartnersImportExportModal,
  confirmDeleteReport: ConfirmDeleteReportModal,
  confirm: ConfirmModal,
  linkReportPayment: LinkReportPaymentModal,
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
