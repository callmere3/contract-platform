import { createContext, useContext, useState } from 'react';

const ModalContext = createContext(null);

export function ModalProvider({ children }) {
  // Стек: [{ name, props }, ...]. Последний элемент — самая верхняя модалка.
  const [stack, setStack] = useState([]);

  const openModal = (name, props = {}) => setStack((s) => [...s, { name, props }]);
  const closeModal = () => setStack((s) => s.slice(0, -1));
  const closeAllModals = () => setStack([]);
  // Заменить текущую верхнюю модалку другой (не добавляя уровень стека) —
  // пригодится для "переключиться на соседнюю модалку", а не "открыть поверх".
  const replaceModal = (name, props = {}) =>
    setStack((s) => [...s.slice(0, -1), { name, props }]);

  return (
    <ModalContext.Provider
      value={{ stack, openModal, closeModal, closeAllModals, replaceModal }}
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
