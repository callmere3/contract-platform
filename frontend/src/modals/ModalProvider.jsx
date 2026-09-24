import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { createModalHistory } from './modalHistory';

const ModalContext = createContext(null);

/**
 * Стек модалок: [{ name, props }, ...]. Последний элемент — самая верхняя.
 *
 * КНОПКА «НАЗАД» ЗАКРЫВАЕТ МОДАЛКУ, А НЕ УНОСИТ СО СТРАНИЦЫ (17.09.2026, по
 * жалобе владельца). До этого модалка жила вне истории браузера: открыв
 * карточку трека и нажав «назад», человек уезжал на предыдущую вкладку, а
 * карточка оставалась висеть поверх неё. Последнее действие — открытие
 * модалки, его «назад» и должно отменять.
 *
 * Как устроено — см. `modalHistory.js`: открытие кладёт в историю одну запись
 * с тем же адресом, закрытие её снимает, а popstate закрывает верхнюю
 * модалку. Счётчики живут там, потому что ошибка в них проявляется не сразу,
 * а на второй-третьей модалке, и их удобнее проверять без React.
 *
 * ЕСЛИ ПОСЛЕ ЗАКРЫТИЯ МОДАЛКИ ВЫ УХОДИТЕ СО СТРАНИЦЫ относительной
 * навигацией (`navigate(-1)`), учтите нашу запись: `modalHistory.depth`
 * говорит, сколько их сейчас. Так делает форма генерации — см. DocFormPage,
 * «Выйти из формы?».
 */
export function ModalProvider({ children }) {
  const [stack, setStack] = useState([]);
  const historyRef = useRef(null);
  if (historyRef.current === null) historyRef.current = createModalHistory();

  useEffect(() => {
    const onPop = () => {
      if (historyRef.current.onPop()) setStack((s) => s.slice(0, -1));
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const openModal = useCallback((name, props = {}) => {
    historyRef.current.open();
    setStack((s) => [...s, { name, props }]);
  }, []);

  // `count` > 1 — закрыть окно вместе с тем, из которого его открыли
  // (удалили отчёт из его же карточки — карточке больше нечего показывать).
  const closeModal = useCallback((count = 1) => {
    const n = typeof count === 'number' && count > 0 ? count : 1;
    setStack((s) => s.slice(0, -n));
    historyRef.current.close(n);
  }, []);

  const closeAllModals = useCallback(() => {
    setStack([]);
    // Историю не отматываем: этот вызов бывает ровно перед уходом на другой
    // экран (ContragentDocsModal → форма генерации), и back() выполнился бы
    // уже после перехода. Подробности — в modalHistory.forget().
    historyRef.current.forget();
  }, []);

  // Заменить верхнюю модалку другой, не добавляя уровень стека. Запись в
  // истории та же: с точки зрения «назад» это по-прежнему одна открытая
  // модалка.
  const replaceModal = useCallback(
    (name, props = {}) => setStack((s) => [...s.slice(0, -1), { name, props }]),
    [],
  );

  return (
    <ModalContext.Provider
      value={{
        stack,
        openModal,
        closeModal,
        closeAllModals,
        replaceModal,
        modalHistory: historyRef.current,
      }}
    >
      {children}
    </ModalContext.Provider>
  );
}

export function useModal() {
  const ctx = useContext(ModalContext);
  if (!ctx) throw new Error('useModal must be used within ModalProvider');
  return ctx;
}
