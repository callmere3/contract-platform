import { useCallback, useEffect, useRef, useState } from 'react';
import { searchContragents } from '../api/contragents';

/**
 * Поиск контрагентов с дебаунсом — общий для hero-поиска и "Базы контрагентов".
 *
 * Дебаунс 400 мс — как в боевом index.html (debounce(checkContragentDuplicates, 400)):
 * не дёргаем сервер на каждое нажатие клавиши.
 *
 * Защита от гонки: ответы на быстро набранные запросы могут прийти в
 * произвольном порядке, и медленный ответ на "Ив" мог бы перезаписать
 * быстрый ответ на "Иванов". Поэтому у каждого запроса свой номер, и
 * результат применяется, только если он от последнего.
 *
 * enabled=false — не искать вообще (например, hero-поиск с пустой строкой:
 * там незачем грузить весь список из 200 записей, пока ничего не введено).
 */
export function useContragentSearch({ q = '', country = '', contragentType = '', enabled = true }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(0);

  const fetchNow = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const data = await searchContragents({ q, country, contragentType });
      if (id !== requestId.current) return; // пришёл устаревший ответ — игнорируем
      setItems(data.contragents);
      setError('');
    } catch (e) {
      if (id !== requestId.current) return;
      setError(e.message);
      setItems([]);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [q, country, contragentType]);

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      setLoading(false);
      setError('');
      return;
    }

    setLoading(true);
    const timer = setTimeout(fetchNow, 400);
    return () => clearTimeout(timer);
  }, [enabled, fetchNow]);

  // Мгновенный повторный запрос без дебаунса — например, после удаления
  // контрагента из карточки: список должен обновиться сразу, а не через 400мс
  // и не ждать смены вкладки.
  return { items, loading, error, refetch: fetchNow };
}
