import { useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from './theme/ThemeContext';
import { AuthProvider, useAuth } from './auth/AuthContext';
import {
  canUseDocs,
  canViewUsers,
  canViewGenerationHistory,
  canSendNotifications,
  canUseDistaSync,
  canViewChampionBoard,
  canUseFinance,
  canViewNomenclature,
  canViewPartnerReports,
  canViewPayments,
  canViewPartners,
} from './auth/permissions';
import { TagsProvider } from './api/TagsContext';
import { ModalProvider } from './modals/ModalProvider';
import { ModalRoot } from './modals/ModalRoot';
import { DraftProvider } from './drafts/DraftContext';
import { DraftDock } from './drafts/DraftDock';
import { AchievementToast } from './achievements/AchievementToast';
import { refreshAchievements } from './achievements/tracker';
import { Header } from './layout/Header';
import { LoginPage } from './pages/LoginPage';
import { SearchPage } from './pages/SearchPage';
import { DatabasePage } from './pages/DatabasePage';
import { FoldersPage } from './pages/FoldersPage';
import { DocFormPage } from './pages/DocFormPage';
import { UsersPage } from './pages/UsersPage';
import { GenerationHistoryPage } from './pages/GenerationHistoryPage';
import { NotificationsPage } from './pages/NotificationsPage';
import { DistaConnectPage } from './pages/DistaConnectPage';
import { FinancePage } from './pages/FinancePage';
import { NomenclaturePage } from './pages/NomenclaturePage';
import { PartnerReportsPage } from './pages/PartnerReportsPage';
import { PaymentsPage } from './pages/PaymentsPage';
import { PartnersPage } from './pages/PartnersPage';
import { ChampionPage } from './pages/ChampionPage';

/**
 * Фронт отдаётся с того же FastAPI по пути /app (см. base в vite.config.js) —
 * поэтому basename обязателен, иначе роутер будет считать /app частью пути
 * и ни один маршрут не совпадёт.
 *
 * BASE_URL приходит из vite и равен '/app/' в проде и '/' в dev-режиме —
 * так один и тот же код работает в обоих случаях без правок.
 */
const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, '');

function AppShell() {
  const { user } = useAuth();

  // КУДА ЧЕЛОВЕК ПОПАДАЕТ ПОСЛЕ ВХОДА и куда его возвращает чужой адрес.
  // У финансового менеджера ML Docs нет вовсе, и «вернуть на поиск» для него
  // значило бы вернуть на пустой экран, которого он не должен видеть.
  const home = canUseDocs(user?.role) ? '/search' : '/finance';

  // Проверка достижений при входе в приложение: значок мог появиться не
  // за документ, а по итогам месяца (кубок) — тогда узнать о нём больше
  // неоткуда. Второй раз проверяем после генерации (см. DocFormPage).
  useEffect(() => {
    refreshAchievements();
  }, []);

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      <Header />
      <Routes>
        {/* Стартовый экран — поиск: самый частый сценарий (найти контрагента
            и сразу сделать по нему документ), см. дизайн-макет hero-поиска. */}
        <Route path="/" element={<Navigate to={home} replace />} />
        {/* ЭКРАНЫ ML DOCS ЗАКРЫТЫ от роли второго продукта — той же защитой
            от прямого захода по адресу, что и у «Пользователей». Раньше эти
            маршруты были открыты всем залогиненным: других ролей, кроме
            документных, попросту не существовало. */}
        <Route
          path="/search"
          element={canUseDocs(user?.role) ? <SearchPage /> : <Navigate to={home} replace />}
        />
        <Route
          path="/database"
          element={canUseDocs(user?.role) ? <DatabasePage /> : <Navigate to={home} replace />}
        />
        {/* Кубок — только admin. Как и у «Пользователей»: прятать вкладку
            мало, иначе по прямому адресу /app/champion не-админ увидел бы
            пустой экран с 403 вместо понятного поведения. */}
        <Route
          path="/champion"
          element={
            canViewChampionBoard(user?.role) ? <ChampionPage /> : <Navigate to={home} replace />
          }
        />
        <Route
          path="/folders"
          element={canUseDocs(user?.role) ? <FoldersPage /> : <Navigate to={home} replace />}
        />
        {/* Форма генерации — отдельный роут, а не состояние: ссылку на неё
            можно сохранить/переслать, работает кнопка "назад" браузера.
            contragentId необязателен (?contragent=...) — из папок шаблон
            открывают без привязки к контрагенту. */}
        <Route
          path="/doc/:templateId"
          element={canUseDocs(user?.role) ? <DocFormPage /> : <Navigate to={home} replace />}
        />
        {/* Пользователи — только admin. Прятать вкладку в шапке мало:
            без этой проверки не-админ мог бы зайти прямо по /app/users и
            увидеть пустой экран с 403 вместо понятного поведения. Реальная
            защита всё равно на сервере: список — CAN_VIEW_USERS (admin/
            director), правка — require_role(ADMIN). */}
        <Route
          path="/users"
          element={canViewUsers(user?.role) ? <UsersPage /> : <Navigate to={home} replace />}
        />
        {/* История генерации — Admin/Director, та же защита от прямого
            захода по адресу, что и у "Пользователей" выше. */}
        <Route
          path="/generation-history"
          element={
            canViewGenerationHistory(user?.role) ? (
              <GenerationHistoryPage />
            ) : (
              <Navigate to={home} replace />
            )
          }
        />
        {/* Уведомления — только admin, та же защита от прямого захода по адресу. */}
        <Route
          path="/notifications"
          element={
            canSendNotifications(user?.role) ? (
              <NotificationsPage />
            ) : (
              <Navigate to={home} replace />
            )
          }
        />
        {/* ML Finance — второй продукт (admin и director). Та же защита от
            прямого захода по адресу, что у «Пользователей»: без неё менеджер
            по ссылке /app/finance увидел бы пустой экран с 403 вместо
            понятного возврата на поиск. Настоящая защита — на сервере, там
            право стоит на всём роутере /finance. */}
        {/* Корень ML Finance — «Номенклатура»: первая вкладка продукта.
            Право своё (canViewNomenclature), хоть сейчас и совпадает с
            финансовым: каталог треков и суммы выплат — разные вещи, и
            разойтись им предстоит на импорте. */}
        <Route
          path="/finance"
          element={
            canViewNomenclature(user?.role) ? (
              <NomenclaturePage />
            ) : (
              <Navigate to={home} replace />
            )
          }
        />
        <Route
          path="/finance/contragents"
          element={canUseFinance(user?.role) ? <FinancePage /> : <Navigate to={home} replace />}
        />
        {/* Партнёры — площадки, от которых приходят деньги. Право своё
            (canViewPartners), хоть и совпадает с финансовым: справочник
            площадок и суммы выплат — разные вещи. */}
        <Route
          path="/finance/partners"
          element={canViewPartners(user?.role) ? <PartnersPage /> : <Navigate to={home} replace />}
        />
        {/* Отчёты площадок — та же защита от прямого захода по адресу, что и
            у остальных вкладок ML Finance. */}
        <Route
          path="/finance/reports"
          element={
            canViewPartnerReports(user?.role) ? <PartnerReportsPage /> : <Navigate to={home} replace />
          }
        />
        {/* Поступления от площадок — та же защита от прямого захода по
            адресу, что и у остальных вкладок ML Finance. */}
        <Route
          path="/finance/payments"
          element={canViewPayments(user?.role) ? <PaymentsPage /> : <Navigate to={home} replace />}
        />
        {/* Dista Connect — только admin, та же защита от прямого захода по
            адресу. Вкладка переехала в меню ML Finance, но маршрут прежний:
            менять адрес ради переезда пункта меню значило бы ломать
            сохранённые ссылки. */}
        <Route
          path="/dista"
          element={
            canUseDistaSync(user?.role) ? <DistaConnectPage /> : <Navigate to={home} replace />
          }
        />
        {/* Неизвестный адрес — не 404-экран, а тихий возврат на поиск:
            для внутреннего инструмента отдельная страница ошибки избыточна. */}
        <Route path="*" element={<Navigate to={home} replace />} />
      </Routes>
      <DraftDock />
      <AchievementToast />
      <ModalRoot />
    </div>
  );
}

/**
 * Гейт авторизации. Пока идёт восстановление сессии из localStorage
 * (status === 'loading') не показываем ничего — иначе залогиненный
 * пользователь при каждой перезагрузке видел бы вспышку экрана входа.
 */
function AuthGate() {
  const { status } = useAuth();

  if (status === 'loading') {
    return <div className="min-h-screen bg-bg" />;
  }
  if (status !== 'authed') {
    return <LoginPage />;
  }
  return (
    <TagsProvider>
      <ModalProvider>
        <DraftProvider>
          <AppShell />
        </DraftProvider>
      </ModalProvider>
    </TagsProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="light">
      <BrowserRouter basename={BASENAME}>
        <AuthProvider>
          <AuthGate />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
