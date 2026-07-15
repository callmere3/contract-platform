import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from './theme/ThemeContext';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { canManageUsers, canViewGenerationHistory } from './auth/permissions';
import { TagsProvider } from './api/TagsContext';
import { ModalProvider } from './modals/ModalProvider';
import { ModalRoot } from './modals/ModalRoot';
import { Header } from './layout/Header';
import { LoginPage } from './pages/LoginPage';
import { SearchPage } from './pages/SearchPage';
import { DatabasePage } from './pages/DatabasePage';
import { FoldersPage } from './pages/FoldersPage';
import { DocFormPage } from './pages/DocFormPage';
import { UsersPage } from './pages/UsersPage';
import { GenerationHistoryPage } from './pages/GenerationHistoryPage';

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

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      <Header />
      <Routes>
        {/* Стартовый экран — поиск: самый частый сценарий (найти контрагента
            и сразу сделать по нему документ), см. дизайн-макет hero-поиска. */}
        <Route path="/" element={<Navigate to="/search" replace />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/database" element={<DatabasePage />} />
        <Route path="/folders" element={<FoldersPage />} />
        {/* Форма генерации — отдельный роут, а не состояние: ссылку на неё
            можно сохранить/переслать, работает кнопка "назад" браузера.
            contragentId необязателен (?contragent=...) — из папок шаблон
            открывают без привязки к контрагенту. */}
        <Route path="/doc/:templateId" element={<DocFormPage />} />
        {/* Пользователи — только admin. Прятать вкладку в шапке мало:
            без этой проверки не-админ мог бы зайти прямо по /app/users и
            увидеть пустой экран с 403 вместо понятного поведения. Реальная
            защита всё равно на сервере (require_role(ADMIN) на /users). */}
        <Route
          path="/users"
          element={canManageUsers(user?.role) ? <UsersPage /> : <Navigate to="/search" replace />}
        />
        {/* История генерации — Admin/Director, та же защита от прямого
            захода по адресу, что и у "Пользователей" выше. */}
        <Route
          path="/generation-history"
          element={
            canViewGenerationHistory(user?.role) ? (
              <GenerationHistoryPage />
            ) : (
              <Navigate to="/search" replace />
            )
          }
        />
        {/* Неизвестный адрес — не 404-экран, а тихий возврат на поиск:
            для внутреннего инструмента отдельная страница ошибки избыточна. */}
        <Route path="*" element={<Navigate to="/search" replace />} />
      </Routes>
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
        <AppShell />
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
