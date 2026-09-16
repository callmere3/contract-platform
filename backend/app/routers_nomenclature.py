"""
Номенклатура — каталог треков лейбла (ML Finance).

  GET /nomenclature            — список с поиском и фильтрами
  GET /nomenclature/{track_id} — карточка трека: все поля выгрузки

ТОЛЬКО ЧТЕНИЕ. Каталог наполняется импортом выгрузки из Dista
(`ops/import_tracks.py`), а не руками через интерфейс: в день приезжает
несколько десятков строк, и каждая несёт полное состояние трека — доли,
ставки, правообладателей. Ручная правка одной ячейки рядом с таким импортом
означала бы, что следующая же выгрузка молча её затрёт.

ПОИСК ПО ПОДСТРОКЕ ДЕРЖИТСЯ НА ТРИГРАММНЫХ ИНДЕКСАХ (pg_trgm, миграция
d8c3e15a90f4). Без них `ILIKE '%текст%'` читает все 121 тысячу строк — так и
было в первой версии, поиск занимал секунду с лишним. Добавляя сюда новое
поле для поиска, заводите на него такой же индекс: одно поле без индекса
сводит на нет все остальные, потому что условия соединены через OR.

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
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Contragent, Track, TrackRight, User
from app.nomenclature_import import (
    AUTHOR,
    COLUMNS,
    RELATED,
    OwnerIndex,
    read_rows,
)
from app.roles import (
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


def _filtered_tracks(
    q: str | None,
    owner: str | None,
    catalog: str | None,
    include_archived: bool,
):
    """
    Общий сбор фильтров для списка и выгрузки: экспорт обязан отдавать ровно
    то, что человек видит на экране, — значит, и фильтровать тем же кодом.
    """
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
    return query


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

    `catalog` — точное совпадение, и в интерфейсе поля под него больше нет:
    выпадающий список на 502 каталога убран 17.09.2026, выбрать в нём что-то
    было нереально. Параметр остался как параметр API — им пользуется
    выгрузка и им удобно дёргать каталог целиком из скрипта.

    Архивные по умолчанию скрыты: трек, исчезнувший из выгрузки, не удаляется
    (по нему могли идти начисления), но и в рабочем списке ему делать нечего.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = _filtered_tracks(q, owner, catalog, include_archived)

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


@nomenclature_router.get(
    "/export", dependencies=[Depends(require_role(*CAN_EXPORT_NOMENCLATURE))]
)
def export_tracks(
    q: str | None = None,
    owner: str | None = None,
    catalog: str | None = None,
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

    ids = _filtered_tracks(q, owner, catalog, include_archived).with_only_columns(Track.id)
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
    Кого мы уже знаем: титлы карточек контрагентов плюс имена, встречавшиеся
    в каталоге. Контрагенты главные — в боевом каталоге 724 имени из 729
    совпадают с титлом буква в букву.
    """
    titles = db.scalars(select(Contragent.title)).all()
    owners = db.scalars(select(TrackRight.owner).distinct()).all()
    return OwnerIndex([*titles, *owners])


def _read_upload(file: UploadFile):
    """Загруженный .xlsx → разобранные строки. Ошибки формата — сразу 400."""
    if not (file.filename or "").endswith(".xlsx"):
        raise HTTPException(400, "Ожидается файл .xlsx — тот же, что выгружает Dista")
    content = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")
    rows = list(read_rows(wb[wb.sheetnames[0]]))
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            400,
            f"В файле {len(rows)} строк — это больше {MAX_IMPORT_ROWS}. "
            "Каталог такого размера заливают на сервере (ops/import_tracks.py), "
            "а через интерфейс — ежедневные выгрузки в несколько десятков строк.",
        )
    return rows


def _preview_row(row, existing_skus: set) -> dict:
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
    for right_type, slot in (
        (AUTHOR, 1),
        (AUTHOR, 2),
        (RELATED, 1),
        (RELATED, 2),
        (AUTHOR, 3),
        (RELATED, 3),
    ):
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
    return {
        # Колонки отдаёт СЕРВЕР, а не рисует фронт: формат файла живёт в
        # nomenclature_import.COLUMNS, и подписи в предпросмотре обязаны
        # совпадать с ним, иначе человек будет сверять глазами не то.
        "columns": list(COLUMNS),
        "preview": [_preview_row(r, existing_skus) for r in rows[:MAX_PREVIEW_ROWS]],
        "preview_limited": len(rows) > MAX_PREVIEW_ROWS,
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
    file: UploadFile = File(...), db: Session = Depends(get_session)
) -> dict:
    """
    Прогон файла БЕЗ записи: что заведётся, что обновится, что не пройдёт и
    кого из правообладателей мы не узнаём.

    Двухшаговый импорт («показать план → применить») здесь не
    перестраховка: строка выгрузки несёт полное состояние трека, и применение
    ЗАМЕЩАЕТ состав его прав. Человек, который заливает файл руками каждый
    день, должен видеть, что именно он сейчас переписывает.
    """
    return _plan(db, _read_upload(file))


@nomenclature_router.post(
    "/import/apply", dependencies=[Depends(require_role(*CAN_IMPORT_NOMENCLATURE))]
)
def import_apply(
    file: UploadFile = File(...),
    owner_map: str = Form("{}"),
    create_missing_owners: bool = Form(True),
    skip_rows: str = Form("[]"),
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
    """
    rows = _read_upload(file)
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
    if to_create:
        if not create_missing_owners:
            raise HTTPException(
                400,
                "В файле есть правообладатели, которых нет в базе: "
                + ", ".join(to_create[:5])
                + ("…" if len(to_create) > 5 else ""),
            )
        for name in to_create:
            db.add(Contragent(id=uuid.uuid4(), title=name))
            created_owners.append(name)
        db.flush()

    existing = {
        sku: track_id
        for sku, track_id in db.execute(
            select(Track.sku, Track.id).where(
                Track.sku.in_([r.track["sku"] for r in ready])
            )
        )
    } if ready else {}

    source = file.filename or "импорт"
    now = datetime.now(timezone.utc)
    created = updated = 0
    touched: list[uuid.UUID] = []
    rights_rows: list[dict] = []

    for row in ready:
        sku = row.track["sku"]
        track_id = existing.get(sku)
        if track_id is None:
            track_id = uuid.uuid4()
            db.add(
                Track(
                    id=track_id,
                    **row.track,
                    source_file=source,
                    imported_at=now,
                )
            )
            created += 1
        else:
            db.execute(
                update(Track)
                .where(Track.id == track_id)
                .values(**row.track, source_file=source, imported_at=now, archived_at=None)
            )
            updated += 1
        touched.append(track_id)
        for right in row.rights:
            rights_rows.append({"id": uuid.uuid4(), "track_id": track_id, **right})

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
            "created": created,
            "updated": updated,
            "skipped": len(skipped),
            "unchecked": len(skipped_by_hand),
            "owners_created": created_owners[:20],
            "owners_replaced": len(mapping),
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
