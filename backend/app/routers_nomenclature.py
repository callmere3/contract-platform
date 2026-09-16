"""
Номенклатура — каталог треков лейбла (ML Finance).

  GET /nomenclature            — список с поиском и фильтрами
  GET /nomenclature/catalogs   — справочник каталогов для фильтра
  GET /nomenclature/{track_id} — карточка трека: все поля выгрузки

ТОЛЬКО ЧТЕНИЕ. Каталог наполняется импортом выгрузки из Dista
(`ops/import_tracks.py`), а не руками через интерфейс: в день приезжает
несколько десятков строк, и каждая несёт полное состояние трека — доли,
ставки, правообладателей. Ручная правка одной ячейки рядом с таким импортом
означала бы, что следующая же выгрузка молча её затрёт.

ПОРЯДОК МАРШРУТОВ ВАЖЕН: `/catalogs` зарегистрирован РАНЬШЕ `/{track_id}` —
иначе FastAPI попробует разобрать «catalogs» как uuid и вернёт 422. Та же
грабля, что с `/import` и `/export` у контрагентов и с `/sent` у уведомлений.

ЧЕГО ЗДЕСЬ НЕТ: расчёта роялти. Каталог знает, кому какая доля принадлежит,
но деньги по нему пока не считаются — это следующий этап (см. брейншторм по
номенклатуре).
"""
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.models import Track, TrackRight
from app.roles import CAN_VIEW_NOMENCLATURE

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

AUTHOR = "author"
RELATED = "related"


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
        "rights": {
            "author": rights.get(AUTHOR, []),
            "related": rights.get(RELATED, []),
        },
    }


@nomenclature_router.get("")
def list_tracks(
    q: str | None = None,
    owner: str | None = None,
    catalog: str | None = None,
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

    `owner` — подстрока имени правообладателя, а не выбор из списка: их 729,
    и выпадающий список такой длины листают дольше, чем набирают фамилию.

    Архивные по умолчанию скрыты: трек, исчезнувший из выгрузки, не удаляется
    (по нему могли идти начисления), но и в рабочем списке ему делать нечего.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = select(Track)
    if not include_archived:
        query = query.where(Track.archived_at.is_(None))

    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Track.sku.ilike(like),
                Track.code.ilike(like),
                Track.title.ilike(like),
                Track.artist.ilike(like),
            )
        )
    if owner and owner.strip():
        # EXISTS, а не JOIN: у трека несколько строк прав, и join размножил бы
        # его в выдаче — пришлось бы городить DISTINCT и ломать пагинацию.
        owner_like = f"%{owner.strip()}%"
        query = query.where(
            select(TrackRight.id)
            .where(
                TrackRight.track_id == Track.id,
                TrackRight.owner.ilike(owner_like),
            )
            .exists()
        )
    if catalog and catalog.strip():
        query = query.where(Track.catalog == catalog.strip())

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
    return {
        "tracks": [_summary(t, rights.get(t.id, {})) for t in tracks],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@nomenclature_router.get("/catalogs")
def list_catalogs(db: Session = Depends(get_session)) -> dict:
    """
    Каталоги, встречающиеся у треков, — для фильтра.

    Справочник считается ПО ДАННЫМ, а не задан списком в `tags.py`: каталог —
    это не наша классификация, а поле, которое приезжает из Dista, и любой
    зафиксированный список разошёлся бы с ним на первом же импорте.
    """
    values = db.scalars(
        select(Track.catalog)
        .where(Track.catalog.is_not(None), Track.archived_at.is_(None))
        .distinct()
        .order_by(Track.catalog)
    ).all()
    return {"catalogs": list(values)}


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
