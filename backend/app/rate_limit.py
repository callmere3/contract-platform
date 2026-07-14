"""
Rate limiting для /auth/login — защита от перебора паролей (брутфорса).

In-memory, не Redis — осознанное упрощение под текущий масштаб: uvicorn
запущен БЕЗ `--workers` (один процесс, см. docker-compose.yml: `command:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`), поэтому общая
память между запросами гарантирована. ВАЖНО НА БУДУЩЕЕ: если когда-нибудь
появится `--workers N` или несколько реплик `api` — этот лимитер перестанет
быть общим между процессами (у каждого воркера будет своя память, лимит
фактически умножится на число воркеров), и его нужно будет заменить на
Redis-based (например, `redis` + `INCR`+`EXPIRE`).

Два независимых лимита:
  - по паре (IP, логин) — короткий порог: защита от точечного перебора
    пароля к ОДНОМУ конкретному аккаунту.
  - по одному IP — более широкий порог: защита от перебора логинов вообще
    (кто-то пробует много разных username с одного адреса).

Считаем только НЕУДАЧНЫЕ попытки — успешный логин не наказывается и сам
сбрасывает счётчик по этой паре (IP, логин), но не сбрасывает общий счётчик
по IP (если с этого IP до этого были неудачные попытки по ДРУГИМ логинам,
это подозрительная активность само по себе, один успешный логин её не отменяет).
"""
import time
from collections import defaultdict, deque

PER_ACCOUNT_WINDOW_SECONDS = 15 * 60   # 15 минут
PER_ACCOUNT_MAX_ATTEMPTS = 5           # неудачных попыток к одному логину

PER_IP_WINDOW_SECONDS = 15 * 60
PER_IP_MAX_ATTEMPTS = 20               # неудачных попыток с одного IP суммарно

_account_attempts: dict[str, deque[float]] = defaultdict(deque)
_ip_attempts: dict[str, deque[float]] = defaultdict(deque)


def _cleanup(bucket: deque[float], window: int, now: float) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def _check(bucket_map: dict[str, deque[float]], key: str, window: int, max_attempts: int, now: float) -> int:
    """Возвращает 0, если не заблокирован, иначе — сколько секунд ждать."""
    bucket = bucket_map[key]
    _cleanup(bucket, window, now)
    if len(bucket) >= max_attempts:
        return max(int(window - (now - bucket[0])), 1)
    return 0


def check_login_rate_limit(ip: str, username: str) -> int:
    """
    Вызывается ПЕРЕД проверкой пароля. Возвращает 0, если можно пробовать
    логиниться, иначе — сколько секунд подождать (для заголовка Retry-After).
    """
    now = time.time()
    account_wait = _check(_account_attempts, f"{ip}:{username}", PER_ACCOUNT_WINDOW_SECONDS, PER_ACCOUNT_MAX_ATTEMPTS, now)
    ip_wait = _check(_ip_attempts, ip, PER_IP_WINDOW_SECONDS, PER_IP_MAX_ATTEMPTS, now)
    return max(account_wait, ip_wait)


def record_failed_login(ip: str, username: str) -> None:
    now = time.time()
    _account_attempts[f"{ip}:{username}"].append(now)
    _ip_attempts[ip].append(now)


def record_successful_login(ip: str, username: str) -> None:
    _account_attempts.pop(f"{ip}:{username}", None)
    # общий счётчик по IP намеренно НЕ трогаем — см. докстринг модуля
