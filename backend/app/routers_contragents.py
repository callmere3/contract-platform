"""
Эндпоинты работы с контрагентами (этап 4, база контрагентов).

  POST /contragents                    — создать контрагента (title/contract_number
                                          вычисляются автоматически, см. брейншторм)
  GET  /contragents?q=...              — поиск по title/nickname (ILIKE, регистронезависимо).
                                          Без q — весь список (для стартового экрана/отладки).
  GET  /contragents/{id}               — карточка контрагента целиком
  GET  /contragents/{id}/templates     — подбор документов, совместимых с контрагентом
                                          по тегам (country/contragent_type/contract_family)
  POST /contragents/{id}/nicknames     — добавить псевдоним контрагенту

Дальнейшие шаги (см. «Брейншторм — база контрагентов.md»):
  импорт/экспорт Excel                 — отдельный шаг, там будет свой роутер/эндпоинты
"""
import uuid
from datetime import date as _date

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.context_builder import build_contract_number, build_contragent_title, parse_date
from app.db import get_session
from app.models import Contragent, ContragentNickname, Template
from app.tags import COUNTRIES, CONTRACT_FAMILIES, CONTRAGENT_TYPES, normalize_tag

contragents_router = APIRouter(prefix="/contragents", tags=["contragents"])


def _contragent_summary(c: Contragent) -> dict:
    """Краткое представление для списков поиска — title крупно, никнеймы мелко (см. брейншторм)."""
    return {
        "id": str(c.id),
        "title": c.title,
        "nicknames": [n.nickname for n in c.nicknames],
        "country": c.country,
        "type": c.type,
        "contract_family": c.contract_family,
    }


@contragents_router.get("")
def search_contragents(
    q: str | None = None,
    db: Session = Depends(get_session),
) -> dict:
    """
    Поиск по title ИЛИ nickname одновременно (см. брейншторм — SQL-запрос
    там же): не важно, по чему совпало, оператор в любом случае видит
    и title, и никнеймы сразу.

    Без q — отдаёт весь список (ограничен 200 записями). Пригодится и
    для стартового экрана без поискового запроса, и для отладки через
    Swagger, пока фронтенд ещё не переписан под контрагентов (этап 6-7
    брейншторма).
    """
    query = db.query(Contragent)
    if q:
        query = (
            query.outerjoin(
                ContragentNickname, ContragentNickname.contragent_id == Contragent.id
            )
            .filter(
                or_(
                    Contragent.title.ilike(f"%{q}%"),
                    ContragentNickname.nickname.ilike(f"%{q}%"),
                )
            )
            .distinct()
        )
    contragents = query.order_by(Contragent.title).limit(200).all()
    return {"contragents": [_contragent_summary(c) for c in contragents]}


@contragents_router.post("")
def create_contragent(
    name: str = Form(...),
    country: str = Form(...),           # 'РУ' | 'КЗ'
    contragent_type: str = Form(...),   # 'СГ' | 'ИП' | 'ООО'
    contract_family: str = Form(...),   # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'
    contract_date: str = Form(...),     # ISO из <input type="date">, напр. '2026-03-15'
    royalty_percent: float = Form(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Создаёт карточку контрагента. title и contract_number вычисляются
    автоматически и НЕ принимаются от клиента — см. брейншторм
    ("title... НЕ показывается и НЕ редактируется в форме создания").

    contract_date фиксируется здесь один раз и дальше только отображается
    при генерации "Договора" — не пересчитывается на лету (см. брейншторм,
    "Почему именно так, а не иначе").

    Мягкая проверка дублей (см. брейншторм) — задача фронтенда: перед
    сабмитом вызвать GET /contragents?q=<name> и показать похожие; сам
    этот эндпоинт ничего не блокирует (жёсткого constraint на title в БД
    нет, см. models.py).

    Это эндпоинт СОЗДАНИЯ ЧЕРЕЗ UI — все поля обязательны, как в
    UX-флоу брейншторма ("Новый контрагент"). Массовый импорт с неполными
    записями (только title/nickname) — отдельный будущий эндпоинт (шаг 5
    плана, работает по другим правилам: title берётся из файла как есть,
    без пересчёта).

    country/contragent_type/contract_family нормализуются к каноническому
    регистру (см. app/tags.py) — без этого 'ру' и 'РУ' в БД считались бы
    разными значениями, и подбор документов по тегам (шаг 4) молча не
    находил бы шаблоны для контрагента, введённого не в том регистре.
    """
    country = normalize_tag(country, COUNTRIES, "country")
    contragent_type = normalize_tag(contragent_type, CONTRAGENT_TYPES, "contragent_type")
    contract_family = normalize_tag(contract_family, CONTRACT_FAMILIES, "contract_family")

    parsed = parse_date(contract_date)
    if not parsed:
        raise HTTPException(
            status_code=400, detail=f"Не удалось распознать дату договора: {contract_date!r}"
        )
    day, month, year_full = parsed

    title = build_contragent_title(name, contragent_type)
    contract_number = build_contract_number(
        day=day,
        month=month,
        year=year_full[-2:],
        full_name=name,
        doc_kind=contragent_type,
    )

    contragent = Contragent(
        name=name,
        title=title,
        country=country,
        type=contragent_type,
        contract_family=contract_family,
        contract_date=_date(int(year_full), int(month), int(day)),
        contract_number=contract_number,
        royalty_percent=royalty_percent,
    )
    db.add(contragent)
    db.commit()

    return {
        "id": str(contragent.id),
        "title": contragent.title,
        "contract_number": contragent.contract_number,
        "contract_date": contragent.contract_date.isoformat(),
    }


@contragents_router.get("/{contragent_id}")
def get_contragent(contragent_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """Полная карточка контрагента — для экрана "после выбора контрагента" (см. брейншторм)."""
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    return {
        "id": str(contragent.id),
        "name": contragent.name,
        "title": contragent.title,
        "country": contragent.country,
        "type": contragent.type,
        "contract_family": contragent.contract_family,
        "contract_date": (
            contragent.contract_date.isoformat() if contragent.contract_date else None
        ),
        "contract_number": contragent.contract_number,
        "royalty_percent": (
            float(contragent.royalty_percent) if contragent.royalty_percent is not None else None
        ),
        "nicknames": [n.nickname for n in contragent.nicknames],
    }


@contragents_router.get("/{contragent_id}/templates")
def list_contragent_templates(
    contragent_id: uuid.UUID,
    db: Session = Depends(get_session),
) -> dict:
    """
    Подбор документов для контрагента (см. брейншторм, "После выбора
    контрагента: список документов, отфильтрованный по (country,
    contragent_type, contract_family) контрагента").

    Сравнение — строгое равенство трёх тегов, поэтому оно надёжно только
    благодаря нормализации регистра при создании контрагента (см.
    app/tags.py) и при ручном тегировании шаблонов — если где-то закрадётся
    несовпадающий регистр, документ просто не найдётся здесь без явной
    ошибки, это стоит держать в голове при отладке.

    Если у контрагента не заполнены country/type/contract_family
    (например, "неполная" карточка из будущего мягкого импорта, см.
    брейншторм) — возвращает пустой список, а не ошибку: карточка валидна,
    просто пока не участвует в подборе документов.
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    if not (contragent.country and contragent.type and contragent.contract_family):
        return {"contragent_id": str(contragent_id), "templates": []}

    templates = (
        db.query(Template)
        .filter(
            Template.country == contragent.country,
            Template.contragent_type == contragent.type,
            Template.contract_family == contragent.contract_family,
        )
        .order_by(Template.name)
        .all()
    )

    return {
        "contragent_id": str(contragent_id),
        "templates": [
            {"id": str(t.id), "name": t.name, "doc_type": t.doc_type} for t in templates
        ],
    }


@contragents_router.post("/{contragent_id}/nicknames")
def add_nickname(
    contragent_id: uuid.UUID,
    nickname: str = Form(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Добавляет псевдоним контрагенту. Никнеймов может быть несколько —
    на форме генерации они показываются выпадающим списком, не
    свободным текстом (см. брейншторм).
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    nick = ContragentNickname(contragent_id=contragent_id, nickname=nickname)
    db.add(nick)
    db.commit()

    return {"id": str(nick.id), "contragent_id": str(contragent_id), "nickname": nick.nickname}
