import { createContext, useContext, useEffect, useState } from 'react';
import { API, apiJson } from './client';

const TagsContext = createContext(null);

/**
 * Справочники с сервера (GET /tags) — единственный источник правды для всех
 * селектов: страна / тип контрагента / тип договора, плюс reg_number_meta
 * (подпись и длина рег. номера под каждый тип: ИНН 12 / ОГРНИП 15 / ОГРН 13).
 *
 * Фронт НЕ хранит эти списки своей копией: бэкенд валидирует ими же
 * (app/tags.py), и любое расхождение приводило бы к 400 на сохранении.
 *
 * Грузится один раз после логина. Ошибка загрузки не блокирует приложение —
 * селекты просто останутся пустыми, а не уронят весь UI.
 */
export function TagsProvider({ children }) {
  const [tags, setTags] = useState({
    countries: [],
    contragent_types: [],
    contract_families: [],
    reg_number_meta: {},
    roles: [],
  });
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiJson(`${API}/tags`);
        if (!cancelled) setTags(data);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return <TagsContext.Provider value={{ ...tags, error }}>{children}</TagsContext.Provider>;
}

export function useTags() {
  const ctx = useContext(TagsContext);
  if (!ctx) throw new Error('useTags must be used within TagsProvider');
  return ctx;
}
