"""
Номенклатура — каталог треков лейбла (ML Finance).

  GET   /nomenclature            — список с поиском и фильтрами
  GET   /nomenclature/owners     — подсказки по правообладателям
  GET   /nomenclature/{track_id} — карточка трека: все поля выгрузки
  PATCH /nomenclature/{track_id} — правка карточки руками

ОСНОВНОЙ ПУТЬ ДАННЫХ — ИМПОРТ выгрузки из Dista (`ops/import_tracks.py` и
`/import/apply`): в день приезжает несколько десятков строк, и каждая несёт
полное состояние трека — доли, ставки, правообладателей.

РУЧНАЯ ПРАВКА КАРТОЧКИ (17.09.2026, просьба владельца) этого не отменяет и
живёт рядом с ним с открытым глазами компромиссом: правка держится до
следующего импорта ТОГО ЖЕ артикула — строка файла замещает состав прав
целиком и не спрашивает, правил ли кто-то карточку руками. Иначе пришлось бы
завести «поле правили руками, не трогать», то есть второй источник правды в
каждой ячейке. Поэтому правка — для того, чтобы поправить одну позицию
здесь и сейчас, а не чтобы вести каталог в обход Dista.

ПРАВИЛА ПРОВЕРКИ У ПРАВКИ ТЕ ЖЕ, ЧТО У ИМПОРТА, и берутся они из того же
модуля (`nomenclature_import.check_required` / `check_shares`): обязательные
поля и СВЕРКА ДОЛЕЙ ПРАВООБЛАДАТЕЛЕЙ СО СПРАВОЧНЫМИ — отдельно по авторским
и смежным. Разойдись эти две калитки, и руками заводилось бы то, что импорт
принять отказывается.

ПОИСК ПО ПОДСТРОКЕ ИДЁТ ПО ОДНОЙ КОЛОНКЕ `search_text` — склейке артикула,
кода, названия и исполнителя, которую считает сама база (миграция
f4a6b2c98e71). Ищем по ней, а не по четырём полям через OR, ПО ПРИЧИНЕ
ПЛАНИРОВЩИКА: четыре отдельных триграммных индекса он оценивает дороже
полного чтения таблицы и берёт seq scan — 800 мс на каждый символ в строке
поиска против 90 мс по индексу (замер на проде 18.09.2026). Добавляя сюда
новое поле для поиска, добавляйте его В СКЛЕЙКУ (миграцией), а не пятым
условием через OR: пятое условие вернёт всё туда же, откуда ушли.

ЕСЛИ ПОЯВИТСЯ НОВЫЙ МАРШРУТ СО СЛОВОМ ВМЕСТО uuid — регистрировать его ДО
`/{track_id}`, иначе FastAPI попробует разобрать это слово как uuid и вернёт
422. Та же грабля, что с `/import` и `/export` у контрагентов.

ЧЕГО ЗДЕСЬ НЕТ: расчёта роялти. Каталог знает, кому какая доля принадлежит,
но деньги по нему пока не считаются — это следующий этап (см. брейншторм по
номенклатуре).
"""
import io
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Contragent, Track, TrackRight, User
from app.nomenclature_import import (
    AUTHOR,
    COLUMNS,
    MAX_LEN,
    RELATED,
    RIGHT_LABELS,
    RIGHT_SLOTS,
    TEXT_FIELDS,
    OwnerIndex,
    check_required,
    check_shares,
    keep_if_richer,
    parse_date,
    read_pasted,
    read_rows,
    share_percent,
)
from app.roles import (
    CAN_EDIT_NOMENCLATURE,
    CAN_EXPORT_NOMENCLATURE,
    CAN_IMPORT_NOMENCLATURE,
    CAN_VIEW_NOMENCLATURE,
)

nomenclature_router = APIRouter(
    prefix="/nomenclature",
    tags=["nomenclature"],
    # Право на всём роутере, как у финансов: забыть Depends на новом
    # эндпоинте — вопрос времени.
    dependencies=[Depends(require_role(*CAN_VIEW_NOMENCLATURE))],
)

# Страница каталога. Сотня строк — столько же, сколько в базе контрагентов;
# больше незачем: в таблице у каждой строки по нескольку строк прав, и
# страница на 500 позиций просто не читается.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# Импорт из интерфейса — про ежедневную выгрузку в несколько десятков строк.
# Каталог целиком (121 тысяча) заливают скриптом на сервере: разбор такого
# файла занимает минуты, и держать всё это время открытым HTTP-запрос незачем.
MAX_IMPORT_ROWS = 20_000
# Сколько проблемных строк показываем поимённо. Список на тысячу строк никто
# не читает, а число в итогах говорит всё, что нужно.
MAX_ISSUES = 100
# Сколько строк показываем таблицей. Больше двух сотен никто глазами не
# проверяет, а браузеру каждая строка — это тридцать ячеек.
MAX_PREVIEW_ROWS = 200
# Строки, которые НЕ ПРОЙДУТ, отдаются отдельным списком и целиком: их человек
# и разбирает, а в первые двести строк файла попадают далеко не все (в одном
# из боевых файлов их 309 на пять тысяч). Предел всё же есть — файл, где не
# проходит вообще всё, разбирают не глазами, а в Excel.
MAX_ERROR_PREVIEW = 2000


def percent(value: Decimal | None) -> str | None:
    """
    Процент строкой: «100», «33.33», «80».

    Строкой по той же причине, что и деньги в ML Finance: в JSON число с
    дробной частью — двоичный тип, и 33.33 уезжает в 33.329999999999998.
    Фронт проценты не считает, он их показывает.

    Хвостовые нули срезаются: в выгрузке доля лежит как 1 или 0.5, и
    «100.00%» рядом с «50.00%» читается хуже, чем «100%» и «50%».
    """
    if value is None:
        return None
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _right(row: TrackRight) -> dict:
    return {
        "owner": row.owner,
        "share": percent(row.share),
        "royalty": percent(row.royalty),
    }


def _rights_by_track(db: Session, track_ids: list[uuid.UUID]) -> dict:
    """
    Права для целой страницы ОДНИМ запросом.

    По запросу на строку это была бы полусотня запросов на страницу — та же
    ошибка, от которой в ML Finance спасает `balances`.
    """
    if not track_ids:
        return {}

    rows = db.scalars(
        select(TrackRight)
        .where(TrackRight.track_id.in_(track_ids))
        .order_by(TrackRight.slot)
    ).all()

    by_track: dict[uuid.UUID, dict] = {
        track_id: {AUTHOR: [], RELATED: []} for track_id in track_ids
    }
    for row in rows:
        bucket = by_track.setdefault(row.track_id, {AUTHOR: [], RELATED: []})
        bucket.setdefault(row.right_type, []).append(_right(row))
    return by_track


def _summary(track: Track, rights: dict) -> dict:
    """Строка списка: то, по чему трек опознают, и права."""
    return {
        "id": str(track.id),
        "sku": track.sku,
        "code": track.code,
        "title": track.title,
        "artist": track.artist,
        "archived": track.archived_at is not None,
        "in_catalog": track.in_catalog,
        "rights": {
            "author": rights.get(AUTHOR, []),
            "related": rights.get(RELATED, []),
        },
    }


def _escape_like(value: str) -> str:
    """
    Экранируем подстановки LIKE. Человек, набравший «50%» или «mix_1», ищет
    именно эти символы, а не «что угодно после 50»: в артикулах и названиях
    и то и другое встречается.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered_tracks(
    q: str | None,
    owner: str | None,
    catalog: str | None,
    include_archived: bool,
    contragent_id: uuid.UUID | None = None,
    case_sensitive: bool = False,
    exact: bool = False,
    in_catalog: bool | None = True,
):
    """
    Общий сбор фильтров для списка и выгрузки: экспорт обязан отдавать ровно
    то, что человек видит на экране, — значит, и фильтровать тем же кодом.

    `case_sensitive` — галочка «учитывать регистр» на экране. По умолчанию
    регистр не важен: человек ищет «густ», а в каталоге «ООО ГУСТ МЬЮЗИК».
    Но регистр иногда и есть сам вопрос — в каталоге живут «ООО Густ Мьюзик»
    и «ООО ГУСТ МЬЮЗИК» как два разных правообладателя, и различить их без
    точного поиска нечем.

    `exact` — галочка «точное совпадение»: поле должно совпасть со строкой
    поиска ЦЕЛИКОМ, а не содержать её. Нужно там же, где и регистр: «Густ» в
    поиске правообладателя выдаёт и «ООО Густ Мьюзик», и «Густ Мьюзик KZ», а
    свести отчёт надо по одному из них.

    На скорости это не сказывается: триграммные индексы (pg_trgm) работают и
    с LIKE, и с ILIKE. Точное совпадение сделано ТЕМ ЖЕ LIKE без подстановок,
    а не через `lower(col) = ...`: равенство с функцией не попадает ни в один
    наш индекс, а LIKE без «%» попадает в триграммный.
    """
    def like_of(column, value: str):
        pattern = _escape_like(value) if exact else f"%{_escape_like(value)}%"
        return (
            column.like(pattern, escape="\\")
            if case_sensitive
            else column.ilike(pattern, escape="\\")
        )

    query = select(Track)
    # КАТАЛОГ И неКАТАЛОГ — два списка одной таблицы. По умолчанию показываем
    # каталог: изъятые позиции нужны отдельным взглядом, а не вперемешку с
    # рабочими. None — «оба списка», это для служебных запросов.
    if in_catalog is not None:
        query = query.where(Track.in_catalog.is_(in_catalog))
    if not include_archived:
        query = query.where(Track.archived_at.is_(None))
    if q and q.strip():
        needle = q.strip()
        if exact:
            # Точное совпадение — вопрос про ОТДЕЛЬНОЕ поле: «артикул равен
            # этой строке». По склейке его не задать, поэтому здесь
            # по-прежнему четыре условия. Это дёшево: LIKE без подстановок
            # отбирает считанные строки, и план всё равно индексный.
            query = query.where(
                or_(
                    like_of(Track.sku, needle),
                    like_of(Track.code, needle),
                    like_of(Track.title, needle),
                    like_of(Track.artist, needle),
                )
            )
        else:
            # ПОИСК ПО ПОДСТРОКЕ — ОДНИМ УСЛОВИЕМ по склейке четырёх полей
            # (`Track.search_text`, правка 18.09.2026). С четырьмя ILIKE через
            # OR планировщик оценивал четыре GIN-скана дороже полного чтения
            # таблицы и брал seq scan: 800 мс на каждый набранный символ
            # против 90 мс по индексу. Одно условие — одному индексу, и
            # выбирать плану больше не из чего.
            query = query.where(like_of(Track.search_text, needle))
    if owner and owner.strip():
        # EXISTS, а не JOIN: у трека несколько строк прав, и join размножил бы
        # его в выдаче — пришлось бы городить DISTINCT и ломать пагинацию.
        query = query.where(
            select(TrackRight.id)
            .where(
                TrackRight.track_id == Track.id,
                like_of(TrackRight.owner, owner.strip()),
            )
            .exists()
        )
    if contragent_id is not None:
        # По ССЫЛКЕ, а не по имени: у карточки может быть несколько написаний
        # в каталоге, и поиск по титлу нашёл бы не все её треки. Ровно ради
        # этого ссылка и заводилась.
        query = query.where(
            select(TrackRight.id)
            .where(
                TrackRight.track_id == Track.id,
                TrackRight.contragent_id == contragent_id,
            )
            .exists()
        )
    if catalog and catalog.strip():
        query = query.where(Track.catalog == catalog.strip())
    return query


@nomenclature_router.get("")
def list_tracks(
    q: str | None = None,
    owner: str | None = None,
    catalog: str | None = None,
    contragent_id: uuid.UUID | None = None,
    case_sensitive: bool = False,
    exact: bool = False,
    in_catalog: bool = True,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_session),
) -> dict:
    """
    Каталог с поиском и фильтрами.

    `q` ищет сразу по четырём полям — артикул, ISRC/UPC, название,
    исполнитель, — потому что человек, у которого в руках строчка отчёта, не
    знает заранее, что именно он держит: код это или название. Ровно так же
    устроен поиск контрагентов (титл, ФИО, псевдоним одним полем).

    `owner` — подстрока имени правообладателя, а не выбор из списка: их 730,
    и выпадающий список такой длины листают дольше, чем набирают фамилию.
    `contragent_id` — другое: это поиск по СВЯЗИ с карточкой, им пользуется
    кнопка «Треки» в карточке контрагента. Имя и ссылка не взаимозаменяемы —
    у карточки бывает несколько написаний в каталоге.

    `catalog` — точное совпадение, и в интерфейсе поля под него больше нет:
    выпадающий список на 502 каталога убран 17.09.2026, выбрать в нём что-то
    было нереально. Параметр остался как параметр API — им пользуется
    выгрузка и им удобно дёргать каталог целиком из скрипта.

    Архивные по умолчанию скрыты: трек, исчезнувший из выгрузки, не удаляется
    (по нему могли идти начисления), но и в рабочем списке ему делать нечего.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = _filtered_tracks(
        q, owner, catalog, include_archived, contragent_id, case_sensitive, exact,
        in_catalog,
    )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    tracks = db.scalars(
        # ПО АРТИКУЛУ, а не по названию (правка 17.09.2026). По названию
        # первая страница открывалась треками «!», «...», «:(» — каталог
        # выглядел сломанным, хотя это настоящие названия. Артикул же растёт
        # со временем: наверху оказывается самое старое, внизу — недавнее, и
        # список читается как история каталога.
        #
        # Сортировка строковая, и это осознанно: у 116 490 треков артикул —
        # семизначное число (одинаковая длина, поэтому порядок совпадает с
        # числовым), а у 5 036 он буквенный (SEN…, GussBoost). Приводить к
        # числу нечем — такие строки просто уронили бы запрос.
        query.order_by(Track.sku)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    rights = _rights_by_track(db, [t.id for t in tracks])
    # Чья это карточка, когда отбор идёт по ней: экран показывает имя прямо в
    # поле правообладателя, и добывать его отдельным запросом ради одной
    # строки незачем. Имя берём из карточки, а не из прав: у карточки может
    # быть несколько написаний в каталоге, и показать одно из них значило бы
    # выбрать наугад.
    card = db.get(Contragent, contragent_id) if contragent_id else None
    return {
        "tracks": [_summary(t, rights.get(t.id, {})) for t in tracks],
        "contragent": {"id": str(card.id), "title": card.title} if card else None,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@nomenclature_router.get(
    "/export", dependencies=[Depends(require_role(*CAN_EXPORT_NOMENCLATURE))]
)
def export_tracks(
    q: str | None = None,
    owner: str | None = None,
    catalog: str | None = None,
    contragent_id: uuid.UUID | None = None,
    case_sensitive: bool = False,
    exact: bool = False,
    in_catalog: bool = True,
    include_archived: bool = False,
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Каталог в .xlsx — в ТОМ ЖЕ формате, в каком его отдаёт Dista.

    Симметрия с импортом здесь не украшение, а смысл всей затеи: выгрузили,
    поправили руками, залили обратно. Поэтому колонки, их порядок и формат
    значений (доли правообладателей — долями единицы, общие — процентами)
    повторяют выгрузку буква в букву, включая её странности вроде трёх
    заготовленных мест под правообладателей.

    Фильтры те же, что у списка: выгружается ровно то, что видно на экране.

    Пишем ПОТОКОВО (write_only) и одним проходом по join'у треков с правами:
    в каталоге 121 тысяча строк, и собирать их в память объектами ORM — это
    гигабайты на ровном месте.
    """
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Номенклатура")
    ws.append(list(COLUMNS))

    ids = _filtered_tracks(
        q, owner, catalog, include_archived, contragent_id, case_sensitive, exact,
        in_catalog,
    ).with_only_columns(Track.id)
    # КОЛОНКАМИ, А НЕ ОБЪЕКТАМИ ORM. Сначала здесь было select(Track, TrackRight),
    # и выгрузка всего каталога занимала 93 секунды: на каждую из 244 тысяч
    # строк join'а SQLAlchemy собирал объекты Track и TrackRight со всей их
    # обвязкой. Кортежи те же данные отдают в разы быстрее, а собирать из них
    # строку файла всё равно приходится вручную.
    rows = (
        select(
            Track.id,
            Track.rights_since,
            Track.sku,
            Track.code,
            Track.title,
            Track.artist,
            Track.authors,
            Track.share_author,
            Track.share_related,
            Track.catalog,
            Track.album,
            Track.genre,
            Track.royalty_percent,
            TrackRight.right_type,
            TrackRight.slot,
            TrackRight.owner,
            TrackRight.share,
            TrackRight.royalty,
        )
        .select_from(Track)
        .outerjoin(TrackRight, TrackRight.track_id == Track.id)
        .where(Track.id.in_(ids))
        .order_by(Track.sku)
        .execution_options(yield_per=5000)
    )

    current_id = None
    track_cells: list = []
    rights: dict = {}
    for row in db.execute(rows):
        if row[0] != current_id:
            if current_id is not None:
                ws.append(track_cells + _rights_cells(rights))
            current_id = row[0]
            track_cells = [
                # Датой, а не строкой: Excel покажет её как дату, и наш же
                # импорт прочитает её обратно без разбора текста.
                row[1] or "",
                row[2],
                row[3] or "",
                row[4],
                row[5] or "",
                row[6] or "",
                _plain(row[7]),
                _plain(row[8]),
                row[9] or "",
                row[10] or "",
                row[11] or "",
                _plain(row[12]),
            ]
            rights = {}
        if row[13] is not None:
            rights[(row[13], row[14])] = (row[15], row[16], row[17])
    if current_id is not None:
        ws.append(track_cells + _rights_cells(rights))

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="nomenclature.xlsx"'},
    )


def _rights_cells(rights: dict) -> list:
    """
    Права трека → 18 ячеек в порядке выгрузки Dista.

    Порядок именно такой (первый и второй авторские, первые и вторые
    смежные, и только потом третьи) — он исторический, и менять его нельзя:
    файл должен заливаться обратно чем угодно, что читает выгрузку Dista.
    """
    cells: list = []
    for right_type, slot in (
        (AUTHOR, 1),
        (AUTHOR, 2),
        (RELATED, 1),
        (RELATED, 2),
        (AUTHOR, 3),
        (RELATED, 3),
    ):
        row = rights.get((right_type, slot))
        if row is None:
            cells += ["", "", ""]
            continue
        owner, share, royalty = row
        # ПРОЦЕНТАМИ 0-100, как в файле, который приносит владелец. В выгрузке
        # Dista те же числа лежат долями единицы, но в процентных ячейках
        # (0.8 = 80%) — читаем мы оба вида, а пишем один: обычные числа
        # понятны и Excel'ю, и человеку, который правит файл руками.
        cells += [
            owner,
            float(share) if share is not None else "",
            float(royalty) if royalty is not None else "",
        ]
    return cells


def _plain(value: Decimal | None):
    """
    Доля или ставка в ячейку — ЧИСЛОМ, а не строкой: файл правят в Excel, и
    текстовые «100» в колонке чисел мешают и сортировке, и формулам. Пусто
    остаётся пустым: ноль и «не заполнено» — разные вещи.
    """
    if value is None:
        return ""
    return float(value)


def _owner_index(db: Session) -> OwnerIndex:
    """
    Кого мы уже знаем: карточки контрагентов (с их id — по ним право получит
    ссылку) плюс имена, встречавшиеся в каталоге. Контрагенты главные: в
    боевом каталоге 729 имён из 730 совпадают с титлом буква в букву.
    """
    cards = db.execute(select(Contragent.title, Contragent.id)).all()
    owners = db.scalars(select(TrackRight.owner).distinct()).all()
    return OwnerIndex(owners, cards)


def _read_input(file: UploadFile | None, pasted: str | None, check_sums: bool = True):
    """
    Источник импорта → разобранные строки. Их два, и оба ведут в один и тот
    же разборщик:
      - файл .xlsx, выгруженный из Dista или правленный в Excel;
      - ВСТАВКА ИЗ БУФЕРА: человек выделил строки в Excel или в гриде Dista
        и нажал Ctrl+V. Для десятка треков это быстрее, чем сохранять файл.

    Проверки после этого одинаковые: разница только в том, откуда взялись
    ячейки.

    `check_sums=False` — сверку долей со справочными не делаем. Так грузится
    неКаталог: изъятые позиции приезжают из исторических списков, где доли
    не сходятся, и починить их уже негде (см. `nomenclature_import`).
    """
    if pasted and pasted.strip():
        rows = list(read_pasted(pasted, check_sums))
        # Ни одного артикула — значит, вставили не таблицу каталога, а
        # что-то другое (одну колонку, текст, кусок другого отчёта). Отвечаем
        # понятной фразой, а не сотней одинаковых ошибок «не заполнен
        # артикул» в предпросмотре.
        if not rows or not any(r.track.get("sku") for r in rows):
            raise HTTPException(
                400,
                "В буфере нет строк каталога. Скопируйте строки из Excel или из окна "
                "номенклатуры Dista — колонки должны идти в том же порядке, что в выгрузке.",
            )
        return _limit(rows)

    if file is None:
        raise HTTPException(400, "Не выбран файл и нечего вставить")
    if not (file.filename or "").endswith(".xlsx"):
        raise HTTPException(400, "Ожидается файл .xlsx — тот же, что выгружает Dista")
    content = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")
    return _limit(list(read_rows(wb[wb.sheetnames[0]], check_sums)))


def _limit(rows: list):
    """Один предел на оба источника — см. MAX_IMPORT_ROWS."""
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            400,
            f"В файле {len(rows)} строк — это больше {MAX_IMPORT_ROWS}. "
            "Каталог такого размера заливают на сервере (ops/import_tracks.py), "
            "а через интерфейс — ежедневные выгрузки в несколько десятков строк.",
        )
    return rows


def _used_slots(rows: list) -> list:
    """
    Какие места правообладателей заняты хоть в одной строке файла.

    Нужно, чтобы не показывать в предпросмотре пустые колонки: у файла,
    где у всех треков по одному правообладателю, шесть заготовленных мест
    превращаются в восемнадцать пустых столбцов, и таблицу приходится
    листать вбок (жалоба владельца 17.09.2026).

    Считается ПО ВСЕМУ ФАЙЛУ, а не по показанным двум сотням строк: иначе
    колонка исчезла бы из-за того, что второй правообладатель встречается
    лишь на пятисотой строке, и человек решил бы, что данные потерялись.

    Порядок — как в файле (первый и второй авторские, первые и вторые
    смежные, потом третьи): человек сверяет предпросмотр со своим Excel.
    """
    present = {
        (right["right_type"], right["slot"]) for row in rows for right in row.rights
    }
    order = [(t, s) for t, s, *_ in RIGHT_SLOTS]
    # Первое место показываем всегда, даже если файл пустой: без него
    # непонятно, куда вообще попадают правообладатели.
    always = {(AUTHOR, 1), (RELATED, 1)}
    return [slot for slot in order if slot in present or slot in always]


def _preview_columns(slots: list) -> list:
    """Подписи колонок предпросмотра: общие поля плюс занятые места прав."""
    by_slot = {(t, s): (c_owner, c_share, c_royalty) for t, s, c_owner, c_share, c_royalty in RIGHT_SLOTS}
    columns = list(COLUMNS[:12])
    for slot in slots:
        columns += [COLUMNS[i] for i in by_slot[slot]]
    return columns


def _preview_row(row, existing_skus: set, slots: list) -> dict:
    """
    Строка файла для предпросмотра — значениями по колонкам, как их прочитал
    сервер.

    Именно КАК ПРОЧИТАЛ, а не как они лежат в файле: смысл экрана в том,
    чтобы человек увидел, что доля «0.8» понята как 80%, дата — как дата, а
    имя правообладателя попало в ту колонку, в которую он его клал. Список
    ошибок без этого читается как приговор без дела.
    """
    track = row.track
    values = [
        track["rights_since"].strftime("%d.%m.%Y") if track.get("rights_since") else "",
        track.get("sku") or "",
        track.get("code") or "",
        track.get("title") or "",
        track.get("artist") or "",
        track.get("authors") or "",
        percent(track.get("share_author")) or "",
        percent(track.get("share_related")) or "",
        track.get("catalog") or "",
        track.get("album") or "",
        track.get("genre") or "",
        percent(track.get("royalty_percent")) or "",
    ]
    by_slot = {(r["right_type"], r["slot"]): r for r in row.rights}
    for right_type, slot in slots:
        right = by_slot.get((right_type, slot))
        if right is None:
            values += ["", "", ""]
        else:
            values += [
                right["owner"],
                percent(right["share"]) or "",
                percent(right["royalty"]) or "",
            ]

    return {
        "row": row.row_num,
        "ok": row.ok,
        "action": "update" if track.get("sku") in existing_skus else "new",
        "errors": row.errors,
        "warnings": row.warnings,
        "values": values,
    }


def _plan(db: Session, rows: list) -> dict:
    """
    Что получится, если применить файл: сколько нового, что не так и каких
    правообладателей мы не узнаём.

    Считается ДО всякой записи и возвращается человеку на подтверждение:
    импорт замещает состав прав целиком, и делать это вслепую нельзя.
    """
    index = _owner_index(db)
    skus = [r.track["sku"] for r in rows if r.track.get("sku")]
    existing = set(
        db.scalars(select(Track.sku).where(Track.sku.in_(skus))).all()
    ) if skus else set()

    errors = [
        {"row": r.row_num, "sku": r.track.get("sku"), "messages": r.errors}
        for r in rows
        if r.errors
    ]
    warnings = [
        {"row": r.row_num, "sku": r.track.get("sku"), "messages": r.warnings}
        for r in rows
        if r.warnings and not r.errors
    ]

    # Правообладателей смотрим по ВСЕМ строкам, включая ошибочные: человек
    # поправит долю и зальёт снова, а вопрос «кто это» останется тем же.
    counts: dict[str, int] = {}
    for row in rows:
        for right in row.rights:
            counts[right["owner"]] = counts.get(right["owner"], 0) + 1

    similar, unknown, known = [], [], 0
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        verdict, suggestion = index.match(name)
        if verdict == "exact":
            known += 1
        elif verdict == "similar":
            similar.append({"name": name, "suggestion": suggestion, "rows": count})
        else:
            unknown.append({"name": name, "rows": count})

    ok_rows = [r for r in rows if r.ok]
    existing_skus = existing
    slots = _used_slots(rows)
    return {
        # Колонки отдаёт СЕРВЕР, а не рисует фронт: формат файла живёт в
        # nomenclature_import.COLUMNS, и подписи в предпросмотре обязаны
        # совпадать с ним, иначе человек будет сверять глазами не то. Пустые
        # места правообладателей сюда не попадают — см. _used_slots.
        "columns": _preview_columns(slots),
        "preview": [_preview_row(r, existing_skus, slots) for r in rows[:MAX_PREVIEW_ROWS]],
        "preview_limited": len(rows) > MAX_PREVIEW_ROWS,
        # ОТДЕЛЬНЫЙ СПИСОК НЕПРОХОДЯЩИХ СТРОК, а не первые двести файла: по
        # ссылке «не пройдёт: N» человек хочет увидеть именно эти строки, где
        # бы они ни лежали. Формат тот же, что у preview, — таблица рисуется
        # одним и тем же кодом.
        "error_preview": [
            _preview_row(r, existing_skus, slots)
            for r in [x for x in rows if x.errors][:MAX_ERROR_PREVIEW]
        ],
        "error_preview_limited": len(errors) > MAX_ERROR_PREVIEW,
        "rows": len(rows),
        "ready": len(ok_rows),
        "tracks_new": len({r.track["sku"] for r in ok_rows} - existing),
        "tracks_updated": len({r.track["sku"] for r in ok_rows} & existing),
        "rights": sum(len(r.rights) for r in ok_rows),
        "error_rows": len(errors),
        "errors": errors[:MAX_ISSUES],
        "warning_rows": len(warnings),
        "warnings": warnings[:MAX_ISSUES],
        "owners": {"known": known, "similar": similar, "new": unknown},
    }


@nomenclature_router.post(
    "/import/check", dependencies=[Depends(require_role(*CAN_IMPORT_NOMENCLATURE))]
)
def import_check(
    file: UploadFile | None = File(None),
    pasted: str = Form(""),
    in_catalog: bool = Form(True),
    db: Session = Depends(get_session),
) -> dict:
    """
    Прогон файла БЕЗ записи: что заведётся, что обновится, что не пройдёт и
    кого из правообладателей мы не узнаём.

    Двухшаговый импорт («показать план → применить») здесь не
    перестраховка: строка выгрузки несёт полное состояние трека, и применение
    ЗАМЕЩАЕТ состав его прав. Человек, который заливает файл руками каждый
    день, должен видеть, что именно он сейчас переписывает.

    `pasted` — вставка из буфера вместо файла (Ctrl+V в окне импорта).

    `in_catalog` — В КАКОЙ СПИСОК грузим: каталог или неКаталог (изъятые
    позиции). Решает та вкладка, с которой открыли импорт, — иначе пришлось
    бы спрашивать об этом ещё раз, уже другими словами.
    """
    plan = _plan(db, _read_input(file, pasted, check_sums=in_catalog))
    plan["in_catalog"] = in_catalog
    return plan


@nomenclature_router.post(
    "/import/apply", dependencies=[Depends(require_role(*CAN_IMPORT_NOMENCLATURE))]
)
def import_apply(
    file: UploadFile | None = File(None),
    pasted: str = Form(""),
    owner_map: str = Form("{}"),
    create_missing_owners: bool = Form(True),
    skip_rows: str = Form("[]"),
    in_catalog: bool = Form(True),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Применить файл.

    `owner_map` — решения человека по похожим именам: {«ИП Погорельских»:
    «Погорельских А.А. (ИП)»}. Замена делается ПРИ ЗАПИСИ, а не правкой файла:
    файл — документ, пришедший из Dista, и переписывать его мы не вправе.

    `create_missing_owners` — заводить ли карточки контрагентов на тех, кого
    в базе нет вовсе. Карточка создаётся ПУСТОЙ, с одним титлом: остальное
    (страна, тип, реквизиты) заполняет человек в ML Docs, и до тех пор она
    честно подсвечивается как неполная.

    Строки с ошибками ПРОПУСКАЮТСЯ, а не роняют весь файл: в выгрузке на
    несколько десятков строк из-за одной кривой доли незачем откладывать
    остальные. Сколько пропущено и почему — в ответе.

    `in_catalog` — в какой список кладём: каталог или неКаталог. ПОЗИЦИЯ ИЗ
    ФАЙЛА ПЕРЕЕЗЖАЕТ в тот список, куда её грузят: файл с изъятыми и означает
    «эти теперь изъяты». Обратно она возвращается тем же способом — импортом
    в каталог.

    У неКаталога СВЕРКИ ДОЛЕЙ СО СПРАВОЧНЫМИ НЕТ (18.09.2026): изъятые
    позиции приезжают из исторических списков, где доли не сходятся, и чинить
    их негде. Остальные проверки — обязательные поля, артикул, разбор чисел —
    те же самые.
    """
    rows = _read_input(file, pasted, check_sums=in_catalog)
    try:
        mapping = json.loads(owner_map or "{}")
        if not isinstance(mapping, dict):
            raise ValueError
        # Строки, которые человек снял галочкой в предпросмотре. Номера, а не
        # артикулы: в предпросмотре он видит именно номера строк файла.
        skipped_by_hand = set(json.loads(skip_rows or "[]"))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(400, "owner_map и skip_rows должны быть корректным JSON")

    index = _owner_index(db)
    ready = [r for r in rows if r.ok and r.row_num not in skipped_by_hand]

    # Имена после замен и те, кого придётся завести.
    used: set[str] = set()
    for row in ready:
        for right in row.rights:
            right["owner"] = mapping.get(right["owner"], right["owner"])
            used.add(right["owner"])
    to_create = sorted(
        name for name in used if index.match(name)[0] == "new"
    )
    created_owners: list[str] = []
    created_ids: dict[str, uuid.UUID] = {}
    if to_create:
        if not create_missing_owners:
            raise HTTPException(
                400,
                "В файле есть правообладатели, которых нет в базе: "
                + ", ".join(to_create[:5])
                + ("…" if len(to_create) > 5 else ""),
            )
        for name in to_create:
            card_id = uuid.uuid4()
            db.add(Contragent(id=card_id, title=name))
            created_ids[name] = card_id
            created_owners.append(name)
        db.flush()

    # Тянем и ТЕКСТ уже лежащих треков, а не только id: он нужен, чтобы
    # выгрузка Dista не затёрла восстановленные буквы своей же испорченной
    # копией (см. keep_if_richer).
    existing = {
        row.sku: row
        for row in db.execute(
            select(Track.sku, Track.id, *(getattr(Track, f) for f in TEXT_FIELDS)).where(
                Track.sku.in_([r.track["sku"] for r in ready])
            )
        )
    } if ready else {}

    source = (file.filename if file is not None else None) or "буфер обмена"
    now = datetime.now(timezone.utc)
    created = updated = 0
    touched: list[uuid.UUID] = []
    rights_rows: list[dict] = []

    kept_letters = 0
    for row in ready:
        sku = row.track["sku"]
        was = existing.get(sku)
        track_id = was.id if was is not None else None
        if was is not None:
            # НЕ ЗАТИРАТЬ ЦЕЛОЕ ИСПОРЧЕННЫМ: если пришедшее название — это
            # ровно наше, пропущенное через cp1251, новостей в нём нет.
            for field_name in TEXT_FIELDS:
                kept = keep_if_richer(row.track.get(field_name), getattr(was, field_name))
                if kept != row.track.get(field_name):
                    row.track[field_name] = kept
                    kept_letters += 1
        if track_id is None:
            track_id = uuid.uuid4()
            db.add(
                Track(
                    id=track_id,
                    **row.track,
                    in_catalog=in_catalog,
                    source_file=source,
                    imported_at=now,
                )
            )
            created += 1
        else:
            db.execute(
                update(Track)
                .where(Track.id == track_id)
                .values(
                    **row.track,
                    in_catalog=in_catalog,
                    source_file=source,
                    imported_at=now,
                    archived_at=None,
                )
            )
            updated += 1
        touched.append(track_id)
        for right in row.rights:
            # Ссылка на карточку ставится ЗДЕСЬ, при записи: имя из файла уже
            # прошло замены, а недостающие карточки только что заведены.
            # Право без карточки останется с пустой ссылкой — врать ей
            # некуда, а имя в строке всё равно сохранится.
            owner_name = right["owner"]
            contragent_id = created_ids.get(owner_name) or index.contragent_for(owner_name)
            rights_rows.append(
                {
                    "id": uuid.uuid4(),
                    "track_id": track_id,
                    "contragent_id": contragent_id,
                    **right,
                }
            )

    if touched:
        db.flush()
        # Права замещаются целиком: сносим прежние и кладём пришедшие.
        db.execute(delete(TrackRight).where(TrackRight.track_id.in_(touched)))
    if rights_rows:
        db.execute(insert(TrackRight), rights_rows)

    skipped = [
        {
            "row": r.row_num,
            "sku": r.track.get("sku"),
            "messages": r.errors or ["снята галочка в предпросмотре"],
        }
        for r in rows
        if r.errors or r.row_num in skipped_by_hand
    ]
    # ОДНА запись в журнал на весь прогон, а не на каждый трек: журнал
    # недавно чистили от шума скриптов, засыпать его импортом нельзя.
    log_action(
        db,
        current_user,
        "nomenclature.import",
        entity_type="track",
        meta={
            "file": source,
            # Куда грузили: по журналу должно быть понятно, отчего позиция
            # переехала в неКаталог.
            "list": "catalog" if in_catalog else "non_catalog",
            "created": created,
            "updated": updated,
            "skipped": len(skipped),
            "unchecked": len(skipped_by_hand),
            "owners_created": created_owners[:20],
            "owners_replaced": len(mapping),
            # Сколько раз файл пытался затереть целое написание своей же
            # испорченной копией. В журнале это видно, чтобы было понятно,
            # почему название в базе не совпадает со строкой выгрузки.
            "kept_letters": kept_letters,
        },
    )
    db.commit()

    return {
        "created": created,
        "updated": updated,
        "rights": len(rights_rows),
        "skipped_rows": len(skipped),
        "skipped": skipped[:MAX_ISSUES],
        "owners_created": created_owners,
        "kept_letters": kept_letters,
    }


@nomenclature_router.get("/owners")
def owner_suggestions(
    q: str | None = None, db: Session = Depends(get_session)
) -> dict:
    """
    Подсказки для поля правообладателя в форме правки: титлы карточек
    контрагентов.

    ИМЕННО КАРТОЧКИ, а не имена, встречавшиеся в каталоге: смысл правки в
    том, чтобы право получило ССЫЛКУ на карточку, а имя, которого в базе нет,
    ссылки не даст и потребует заводить карточку. Подсказывать то, что заведомо
    приведёт к лишнему вопросу, незачем.

    Маршрут зарегистрирован ДО `/{track_id}` — иначе FastAPI попробует
    разобрать «owners» как uuid и ответит 422 (та же грабля, что с
    `/import` и `/export`).
    """
    query = select(Contragent.id, Contragent.title)
    needle = (q or "").strip()
    if needle:
        query = query.where(
            Contragent.title.ilike(f"%{_escape_like(needle)}%", escape="\\")
        )
    rows = db.execute(query.order_by(Contragent.title).limit(20)).all()
    return {"owners": [{"id": str(cid), "title": title} for cid, title in rows]}


def _card(db: Session, track: Track) -> dict:
    """Карточка трека одним словарём — им отвечают и чтение, и правка."""
    rights = _rights_by_track(db, [track.id]).get(track.id, {})
    return {
        **_summary(track, rights),
        "authors": track.authors,
        "album": track.album,
        "genre": track.genre,
        "catalog": track.catalog,
        "share_author": percent(track.share_author),
        "share_related": percent(track.share_related),
        "royalty_percent": percent(track.royalty_percent),
        "rights_since": track.rights_since.isoformat() if track.rights_since else None,
        "source_file": track.source_file,
        "imported_at": track.imported_at.isoformat() if track.imported_at else None,
    }


@nomenclature_router.get("/{track_id}")
def track_card(track_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Карточка трека: ВСЕ поля выгрузки.

    В таблице каталога их столько, сколько нужно, чтобы трек опознать, —
    остальное живёт здесь: альбом, жанр, авторы слов и музыки, каталог, доли
    на уровне трека и дата прав.

    `share_author` / `share_related` отдаются рядом со строками прав
    намеренно, хотя иногда им противоречат (доля смежных 0 при указанном
    владельце смежных — 45 617 треков в выгрузке от 16.09.2026). Показать
    только одно число значило бы выбрать за владельца, какое из них верное; у
    нас пока нет оснований выбирать.
    """
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Трек не найден")
    return _card(db, track)


# ---------------------------------------------------------------------------
# ПРАВКА КАРТОЧКИ РУКАМИ (17.09.2026)
# ---------------------------------------------------------------------------

# Подписи полей — и для отказов, и для журнала: «Наименование» понятно и
# человеку, читающему ошибку, и тому, кто через полгода смотрит в audit_log,
# а «title» — только нам.
FIELD_LABELS = {
    "sku": "Артикул",
    "code": "Код / ISRC / UPC",
    "title": "Наименование",
    "artist": "Исполнитель",
    "authors": "Автор слов/музыки",
    "album": "Альбом",
    "genre": "Жанр",
    "catalog": "Каталог",
    "share_author": "Доля авторских прав",
    "share_related": "Доля смежных прав",
    "royalty_percent": "Роялти",
    "rights_since": "Дата прав",
}

# Мест под правообладателя в выгрузке Dista ТРИ на каждый вид прав, и
# четвёртый молча не попал бы в файл: экспорт пишет фиксированные 18 ячеек
# (см. _rights_cells). Пока формат файла такой, отказ честнее потери строки.
MAX_RIGHTS_PER_TYPE = 3


class RightIn(BaseModel):
    """Строка прав из формы: вид права, имя владельца, доля и ставка."""

    right_type: str
    owner: str
    share: str | int | float | None = None
    royalty: str | int | float | None = None


class TrackIn(BaseModel):
    """
    Карточка трека ЦЕЛИКОМ, а не изменённые поля.

    Целиком — потому что правка замещает и состав прав тоже: присылай мы
    только изменённое, сервер гадал бы, убрал человек правообладателя или
    просто его не тронул. Тот же принцип, что у импорта, где строка файла
    несёт полное состояние трека.

    Числа и даты — СТРОКАМИ, как они и уходят наружу: доля в JSON-числе
    превращается в 33.329999999999998, а дата — в чужой часовой пояс. Читает
    их тот же разбор, что и файл (share_percent, parse_date), поэтому «80»,
    «80%» и «80,5» понимаются одинаково.
    """

    sku: str
    code: str | None = None
    title: str
    artist: str | None = None
    authors: str | None = None
    album: str | None = None
    genre: str | None = None
    catalog: str | None = None
    share_author: str | int | float | None = None
    share_related: str | int | float | None = None
    royalty_percent: str | int | float | None = None
    rights_since: str | None = None
    rights: list[RightIn] = Field(default_factory=list)
    # Заводить ли карточки контрагентов на незнакомые имена. По умолчанию НЕТ:
    # первый ответ сервера на незнакомое имя — вопрос человеку (409 со
    # списком и подсказками), а не тихо заведённая карточка.
    create_missing_owners: bool = False


def _text_in(value, label: str, field_name: str | None = None, required: bool = False):
    """
    Строка из формы. Длину проверяем ОТКАЗОМ, а не обрезкой, в отличие от
    импорта: там обрезать хвост длинной подписи лучше, чем не импортировать
    трек, а здесь человек стоит перед формой и может поправить сам — молча
    укоротить его название значило бы подменить введённое.
    """
    s = str(value or "").strip()
    if not s:
        if required:
            raise HTTPException(400, f"«{label}» не может быть пустым")
        return None
    limit = MAX_LEN.get(field_name) if field_name else None
    if limit and len(s) > limit:
        raise HTTPException(400, f"«{label}» длиннее {limit} символов")
    return s


def _percent_in(value, label: str):
    """
    Доля или ставка из формы — ПРОЦЕНТЫ 0–100.

    Гадать по формату ячейки здесь не надо и нельзя: в форме нет ячеек, есть
    то, что человек напечатал. «80», «80%» и «80,5» — одно и то же, а 0.8 это
    восемь десятых процента, а не 80%: в поле, подписанном «%», иначе и быть
    не может.
    """
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    parsed = share_percent(raw, False)
    if parsed is None:
        raise HTTPException(400, f"{label}: «{raw}» — это не число")
    if parsed < 0:
        raise HTTPException(400, f"{label} не может быть отрицательной")
    if parsed > 100:
        raise HTTPException(400, f"{label} больше 100%")
    return parsed


def _date_in(value):
    """Дата прав: и ISO из <input type=date>, и «01.09.2026», набранное руками."""
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise HTTPException(400, f"Дата прав: «{raw}» — это не дата")
    return parsed


def _rights_in(items: list) -> list[dict]:
    """Строки прав из формы → то же представление, в каком их даёт разбор файла."""
    rights = []
    for item in items:
        if item.right_type not in (AUTHOR, RELATED):
            raise HTTPException(400, f"Неизвестный вид права: «{item.right_type}»")
        owner = _text_in(item.owner, "Правообладатель", "owner", required=True)
        label = RIGHT_LABELS[item.right_type]
        rights.append(
            {
                "right_type": item.right_type,
                "owner": owner,
                "share": _percent_in(item.share, f"Доля {label} прав у «{owner}»"),
                "royalty": _percent_in(item.royalty, f"Роялти {label} прав у «{owner}»"),
            }
        )
    return rights


def _rights_problems(rights: list) -> list[str]:
    """Претензии к составу прав, которых у файла быть не может по построению."""
    problems = []
    for right_type, label in RIGHT_LABELS.items():
        same = [r for r in rights if r["right_type"] == right_type]
        if len(same) > MAX_RIGHTS_PER_TYPE:
            problems.append(
                f"{label} правообладателей больше трёх: в выгрузке Dista под них "
                f"отведено три места, и четвёртый не попал бы в файл"
            )
        seen = set()
        for right in same:
            key = right["owner"].casefold()
            if key in seen:
                problems.append(
                    f"правообладатель «{right['owner']}» указан дважды в {label} правах"
                )
            seen.add(key)
    return problems


@nomenclature_router.patch(
    "/{track_id}", dependencies=[Depends(require_role(*CAN_EDIT_NOMENCLATURE))]
)
def update_track(
    track_id: uuid.UUID,
    payload: TrackIn,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Правка карточки: метаданные, состав правообладателей, доли и ставки.

    СВЕРКА ДОЛЕЙ СО СПРАВОЧНЫМИ ОБЯЗАТЕЛЬНА (правило владельца 17.09.2026):
    сумма долей правообладателей должна совпадать с общей долей трека,
    отдельно по авторским и смежным. Проверку делает `check_shares` — тот же
    код, что проверяет файл импорта. Исторические расхождения (45 617 треков
    с нулевой общей долей смежных при владельце со стопроцентной) сохранены
    как есть, но СОХРАНИТЬ такую карточку теперь нельзя: если уж открыли и
    правите — оставьте сходящейся. Поправить можно с любой стороны: и долю
    правообладателя, и справочную долю трека — оба поля в той же форме.

    СОСТАВ ПРАВ ЗАМЕЩАЕТСЯ ЦЕЛИКОМ, как при импорте: пришедший список и есть
    новое состояние. Слоты нумеруются заново по порядку — номер из выгрузки
    не значит ничего, кроме порядка показа.

    НЕЗНАКОМОЕ ИМЯ ПРАВООБЛАДАТЕЛЯ — не ошибка, а вопрос: сервер отвечает 409
    со списком и подсказками («может быть, это…»), а `create_missing_owners`
    в повторном запросе означает «да, заведите карточки». Молча заводить
    нельзя: опечатка в имени тогда превращалась бы в новую пустую карточку,
    и деньги ушли бы мимо настоящей.

    `source_file` и `imported_at` правка НЕ ТРОГАЕТ: они отвечают на вопрос
    «из какой выгрузки приехала строка», и ручная правка этого не меняет. Кто
    и что поправил руками, отвечает журнал — там и поля перечислены.
    """
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Трек не найден")

    fields = {
        "sku": _text_in(payload.sku, FIELD_LABELS["sku"], "sku", required=True),
        "code": _text_in(payload.code, FIELD_LABELS["code"], "code"),
        "title": _text_in(payload.title, FIELD_LABELS["title"], "title", required=True),
        "artist": _text_in(payload.artist, FIELD_LABELS["artist"], "artist"),
        # У авторов слов и музыки в базе Text без предела: в выгрузке это одна
        # строка с перечислением через запятую, и она бывает длинной.
        "authors": _text_in(payload.authors, FIELD_LABELS["authors"]),
        "album": _text_in(payload.album, FIELD_LABELS["album"], "album"),
        "genre": _text_in(payload.genre, FIELD_LABELS["genre"], "genre"),
        "catalog": _text_in(payload.catalog, FIELD_LABELS["catalog"], "catalog"),
        "share_author": _percent_in(payload.share_author, FIELD_LABELS["share_author"]),
        "share_related": _percent_in(payload.share_related, FIELD_LABELS["share_related"]),
        "royalty_percent": _percent_in(payload.royalty_percent, FIELD_LABELS["royalty_percent"]),
        "rights_since": _date_in(payload.rights_since),
    }
    rights = _rights_in(payload.rights)

    # Правила — общие с импортом (см. nomenclature_import).
    problems = check_required(fields)
    no_share = [
        f"у правообладателя «{r['owner']}» не указана доля"
        for r in rights
        if r["share"] is None
    ]
    problems += no_share + _rights_problems(rights)
    # Пока у кого-то доля пуста, сумма не значит ничего, и второе сообщение
    # про несходящиеся доли только сбивало бы с толку.
    if not no_share:
        problems += check_shares(fields, rights)
    if problems:
        raise HTTPException(400, "; ".join(problems))

    taken = db.scalar(
        select(Track.sku).where(Track.sku == fields["sku"], Track.id != track_id)
    )
    if taken:
        raise HTTPException(
            409,
            f"Артикул «{fields['sku']}» уже занят другим треком: артикул — ключ "
            "каталога, двух позиций с одним номером быть не может",
        )

    index = _owner_index(db)
    unknown = []
    for name in sorted({r["owner"] for r in rights}):
        if index.contragent_for(name) is not None:
            continue
        verdict, suggestion = index.match(name)
        unknown.append({"name": name, "suggestion": suggestion if verdict == "similar" else None})
    if unknown and not payload.create_missing_owners:
        raise HTTPException(
            409,
            detail={
                "code": "unknown_owners",
                "message": "В базе нет карточек: "
                + ", ".join(item["name"] for item in unknown),
                "owners": unknown,
            },
        )

    created_ids: dict[str, uuid.UUID] = {}
    for item in unknown:
        card_id = uuid.uuid4()
        # Карточка пустая, с одним титлом — ровно как заводит импорт: страну,
        # тип и реквизиты заполняют в ML Docs, до тех пор она честно красная.
        db.add(Contragent(id=card_id, title=item["name"]))
        created_ids[item["name"]] = card_id
    if created_ids:
        db.flush()

    # Что поменялось — считаем ДО записи, пока объект держит прежние значения.
    changed = [FIELD_LABELS[key] for key, value in fields.items() if getattr(track, key) != value]
    before = {
        (r.right_type, r.owner, r.share, r.royalty)
        for r in db.scalars(
            select(TrackRight).where(TrackRight.track_id == track_id)
        ).all()
    }
    after = {(r["right_type"], r["owner"], r["share"], r["royalty"]) for r in rights}

    db.execute(update(Track).where(Track.id == track_id).values(**fields))
    db.execute(delete(TrackRight).where(TrackRight.track_id == track_id))

    rows = []
    slots = {AUTHOR: 0, RELATED: 0}
    for right in rights:
        slots[right["right_type"]] += 1
        owner = right["owner"]
        rows.append(
            {
                "id": uuid.uuid4(),
                "track_id": track_id,
                "contragent_id": created_ids.get(owner) or index.contragent_for(owner),
                "slot": slots[right["right_type"]],
                **right,
            }
        )
    if rows:
        db.execute(insert(TrackRight), rows)

    log_action(
        db,
        current_user,
        "nomenclature.track.update",
        entity_type="track",
        entity_id=track_id,
        meta={
            "sku": fields["sku"],
            "title": fields["title"],
            # Поля перечисляем поимённо: журнал должен отвечать на вопрос
            # «что именно правили», а не только «правили».
            "fields": changed,
            "rights_changed": before != after,
            "rights": len(rows),
            "owners_created": sorted(created_ids),
        },
    )
    db.commit()

    fresh = db.get(Track, track_id)
    return _card(db, fresh)
