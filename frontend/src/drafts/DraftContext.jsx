import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useAuth } from '../auth/AuthContext';

/**
 * Черновик формы генерации — один на пользователя, в localStorage.
 *
 * Почему localStorage, а не сервер: автосохранение идёт после каждого
 * изменения поля (см. DocFormPage), и слать на сервер запрос на каждую
 * букву — плохо. localStorage переживает закрытие вкладки, а больше от
 * черновика ничего и не нужно. Плата — черновик живёт только в этом
 * браузере, между устройствами не синхронизируется (осознанный выбор,
 * см. обсуждение 17.07.2026).
 *
 * Один черновик, «последний»: новая незавершённая форма замещает
 * предыдущую. Модель выбрана под формулировку «в черновик сохраняется
 * последний не сформированный документ».
 *
 * Привязка к user.id: на общем ПК под разными аккаунтами (напр. TestManager
 * у нескольких людей) один не должен видеть черновик другого. В черновике
 * личные данные (ФИО, паспорт, реквизиты) — как и токены, за собой убираем:
 * ключ у каждого пользователя свой, чужой не читается.
 */
const DraftContext = createContext(null);

const keyFor = (userId) => `ml_draft:${userId || '_'}`;

function readDraft(userId) {
  try {
    const raw = localStorage.getItem(keyFor(userId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    // битый JSON или приватный режим — черновика просто нет
    return null;
  }
}

export function DraftProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const [draft, setDraft] = useState(() => readDraft(userId));

  // Смена аккаунта в этом же браузере — перечитываем черновик нового
  // пользователя (у каждого свой ключ).
  useEffect(() => {
    setDraft(readDraft(userId));
  }, [userId]);

  const saveDraft = useCallback(
    (next) => {
      const withMeta = { ...next, savedAt: new Date().toISOString() };
      try {
        localStorage.setItem(keyFor(userId), JSON.stringify(withMeta));
      } catch {
        // переполнение квоты/приватный режим — черновик не сохранится,
        // но форму ронять из-за этого нельзя
      }
      setDraft(withMeta);
    },
    [userId],
  );

  const clearDraft = useCallback(() => {
    try {
      localStorage.removeItem(keyFor(userId));
    } catch {
      // ignore
    }
    setDraft(null);
  }, [userId]);

  return (
    <DraftContext.Provider value={{ draft, saveDraft, clearDraft }}>
      {children}
    </DraftContext.Provider>
  );
}

export function useDraft() {
  const ctx = useContext(DraftContext);
  if (!ctx) throw new Error('useDraft must be used within DraftProvider');
  return ctx;
}
