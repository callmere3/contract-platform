"""
Отчёты правообладателям: расчёт вознаграждения и сборка ведомостей .xlsx.

ОТКУДА ЧИСЛА (восстановлено по образцам владельца 24.09.2026 — сводному и
детализированному отчёту Ибара М.Ж. за II квартал 2026 из Dista):

- «Сумма реализации Лицензиара» = авторские строки отчёта площадки × доля
  авторских + смежные × доля смежных. Доля — из прав на трек
  (`track_rights.share`) именно этого правообладателя.
- «Лицензиар вознаграждение авторские» = авторские × доля × роялти авторских
  (`track_rights.royalty`); смежные — так же.
- «Комиссия Лицензиата» = сумма реализации − вознаграждение итого.
- «Количество» — как в отчёте площадки, на долю НЕ умножается.

Сводный отчёт — те же числа, сложенные по треку и округлённые до копеек.
Первая страница («Отчетная ведомость») — итоги и подписи.

ЧТО СЧИТАЕТСЯ: строки загруженных отчётов площадок, привязанные к треку, на
который у правообладателя есть права. Приёмник «Вне каталога» прав не имеет и
в отчёты не попадает сам собой. Валютные отчёты БЕЗ КУРСА пропускаются: их
суммы ещё не рубли (см. `rate_pending`), и сервер называет их отдельно.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from copy import copy
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.drawing.image import Image as _XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Contragent, ContragentNickname, Partner, PartnerPayment, PartnerReport, PartnerReportRow,
    Track, TrackRight,
)

# Город и Лицензиат в ведомости — одни на все отчёты; понадобится менять —
# это строки здесь, а не настройка в интерфейсе.
CITY = "г. Москва"
LICENSEE = "ООО «Медиа Лэнд»"
ATTRS = ("content_type", "usage_type", "usage_kind", "territory")
CENT = Decimal("0.01")
ZERO = Decimal(0)
HUNDRED = Decimal(100)
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря")
# Налоговый статус Лицензиара под подписью. Известен только для СГ:
# самозанятый — это и есть плательщик НПД. Для остальных типов строку не
# пишем, а не угадываем: ошибка в налоговом статусе в документе хуже пустоты.
TAX_NOTE = {"СГ": "Плательщик НПД"}


def cents(value) -> Decimal:
    """До копеек, половина — вверх, как в Excel. У Decimal по умолчанию
    «банковское» округление к чётному: 0,025 дало бы 0,02."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Settings:
    period_from: date
    period_to: date
    # 'period' — по дате реализации: отчёты, привязанные к поступлениям за
    # выбранный период (правило владельца 24.09.2026);
    # 'report' — по дате формирования отчёта: его собственный период внутри.
    date_basis: str = "period"
    contragent_ids: list | None = None      # None — все, у кого есть начисления
    partner_ids: list | None = None         # None — все площадки
    track_ids: list | None = None           # None — все треки правообладателя
    group_detail: bool = True


@dataclass
class Line:
    """Строка детализации."""
    sku: str
    code: str
    title: str
    artist: str
    authors: str
    share_author: Decimal
    share_related: Decimal
    partner: str
    content_type: str
    usage_type: str
    usage_kind: str
    territory: str
    period_from: date | None
    period_to: date | None
    quantity: Decimal
    realization: Decimal
    royalty_author: Decimal | None
    reward_author: Decimal
    royalty_related: Decimal | None
    reward_related: Decimal

    @property
    def reward(self) -> Decimal:
        return self.reward_author + self.reward_related

    @property
    def commission(self) -> Decimal:
        return self.realization - self.reward


@dataclass
class Result:
    """Всё, что насчитано одному правообладателю."""
    contragent_id: str
    title: str
    lines: list = field(default_factory=list)
    # Из карточки контрагента — для шапки ведомости и имени файла.
    contract_number: str = ""
    contract_date: date | None = None
    name: str = ""              # полное ФИО: «Лицензиар: Ибара Мишель Жоржевич»
    kind: str = ""              # тип контрагента: СГ, ИП, ООО…
    nicknames: list = field(default_factory=list)

    @property
    def contract_text(self) -> str:
        """
        «МЛ-23/10/24-СГ-ИМЖ от «23» октября 2024 г.» — как в ведомости юриста.
        Заполнено одно из двух — печатаем его; пусто оба — пустая строка, и
        строки «к Лицензионному договору» в ведомости нет.
        """
        parts = []
        if self.contract_number:
            parts.append(self.contract_number)
        if self.contract_date:
            d = self.contract_date
            parts.append(f"от «{d.day:02d}» {MONTHS_GEN[d.month - 1]} {d.year} г.")
        return " ".join(parts)

    @property
    def label(self) -> str:
        """«Ибара М.Ж. (СГ) - RE3»: титл и псевдонимы, как у юриста."""
        return f"{self.title} - {', '.join(self.nicknames)}" if self.nicknames else self.title

    @property
    def quantity(self) -> Decimal:
        return sum((ln.quantity for ln in self.lines), ZERO)

    @property
    def realization(self) -> Decimal:
        return sum((ln.realization for ln in self.lines), ZERO)

    @property
    def reward_author(self) -> Decimal:
        return sum((ln.reward_author for ln in self.lines), ZERO)

    @property
    def reward_related(self) -> Decimal:
        return sum((ln.reward_related for ln in self.lines), ZERO)

    @property
    def reward(self) -> Decimal:
        return self.reward_author + self.reward_related

    @property
    def tracks(self) -> int:
        return len({ln.sku for ln in self.lines})


def _report_filter(s: Settings):
    """Какие отчёты площадок идут в расчёт."""
    if s.date_basis == "report":
        # Период отчёта ЦЕЛИКОМ внутри выбранного: отчёт за июнь в II квартал
        # входит, за июнь—июль — нет, иначе его деньги легли бы в два квартала.
        cond = and_(
            PartnerReport.period_from >= s.period_from,
            PartnerReport.period_to <= s.period_to,
        )
    else:
        # КВАРТАЛ ОТЧЁТА — ЭТО КВАРТАЛ ПОСТУПЛЕНИЯ, к которому он привязан
        # (правило владельца 24.09.2026). Площадки платят не квартал в квартал:
        # за апрель—июнь деньги приходят в июле, и ведомость III квартала —
        # это то, за что в III квартале заплатили. Отчёт без привязки к
        # поступлению в такую ведомость не попадает (см. unlinked_reports).
        paid = select(PartnerPayment.id).where(
            PartnerPayment.occurred_on >= s.period_from,
            PartnerPayment.occurred_on <= s.period_to,
        )
        cond = PartnerReport.payment_id.in_(paid)
    if s.partner_ids:
        cond = and_(cond, PartnerReport.partner_id.in_(s.partner_ids))
    return cond


def _not_pending():
    """Отчёт в рублях или с курсом — его суммы уже рубли."""
    return or_(
        PartnerReport.currency.is_(None),
        PartnerReport.currency == "RUB",
        PartnerReport.currency_rate.isnot(None),
    )


def pending_reports(db: Session, s: Settings) -> list:
    """Валютные отчёты без курса, попавшие в период: их пропускаем и называем."""
    rows = db.execute(
        select(Partner.name, PartnerReport.period_from, PartnerReport.period_to,
               PartnerReport.file_name, PartnerReport.currency)
        .join(Partner, Partner.id == PartnerReport.partner_id)
        .where(_report_filter(s), ~_not_pending())
    ).all()
    return [
        {"partner": r[0], "period_from": r[1].isoformat(), "period_to": r[2].isoformat(),
         "file_name": r[3], "currency": r[4]}
        for r in rows
    ]


def unlinked_reports(db: Session, s: Settings) -> list:
    """
    Отчёты, НЕ привязанные к поступлению, чей период лежит в выбранном: при
    расчёте по дате реализации они в ведомость не попадают, и человек должен
    это видеть — скорее всего, их просто забыли привязать.
    """
    if s.date_basis == "report":
        return []
    cond = and_(
        PartnerReport.payment_id.is_(None),
        PartnerReport.period_to <= s.period_to,
    )
    if s.partner_ids:
        cond = and_(cond, PartnerReport.partner_id.in_(s.partner_ids))
    rows = db.execute(
        select(Partner.name, PartnerReport.period_from, PartnerReport.period_to,
               PartnerReport.file_name)
        .join(Partner, Partner.id == PartnerReport.partner_id)
        .where(cond)
        .order_by(PartnerReport.period_from)
    ).all()
    return [
        {"partner": r[0], "period_from": r[1].isoformat(), "period_to": r[2].isoformat(),
         "file_name": r[3]}
        for r in rows
    ]


def compute(db: Session, s: Settings) -> list:
    """Насчитать вознаграждение: список `Result`, по одному на правообладателя."""
    rights_q = select(TrackRight.track_id, TrackRight.contragent_id).where(
        TrackRight.contragent_id.isnot(None)
    )
    if s.contragent_ids:
        rights_q = rights_q.where(TrackRight.contragent_id.in_(s.contragent_ids))
    if s.track_ids:
        rights_q = rights_q.where(TrackRight.track_id.in_(s.track_ids))
    owners = rights_q.distinct().subquery()

    R, Rep = PartnerReportRow, PartnerReport
    attrs = [func.coalesce(getattr(R, a), getattr(Rep, a)).label(a) for a in ATTRS]
    keys = [owners.c.contragent_id, R.track_id, Rep.partner_id, Rep.period_from, Rep.period_to, *attrs]
    if not s.group_detail:
        keys.append(R.id)
    q = (
        select(
            *keys,
            func.coalesce(func.sum(R.quantity), 0),
            func.coalesce(func.sum(R.amount_author), 0),
            func.coalesce(func.sum(R.amount_related), 0),
        )
        .select_from(R)
        .join(Rep, Rep.id == R.report_id)
        .join(owners, owners.c.track_id == R.track_id)
        .where(_report_filter(s), _not_pending())
        .group_by(*keys)
    )
    groups = db.execute(q).all()
    if not groups:
        return []

    n = len(keys)
    track_ids = {g[1] for g in groups}
    contragent_ids = {g[0] for g in groups}

    # Доли и ставки — по (трек, правообладатель, вид права). Если у человека
    # на одно право несколько мест (бывает при слиянии дублей), доли
    # складываются, а ставка берётся первая: она у них одна.
    rights: dict = {}
    for tid, cid, rtype, share, royalty in db.execute(
        select(TrackRight.track_id, TrackRight.contragent_id, TrackRight.right_type,
               TrackRight.share, TrackRight.royalty)
        .where(TrackRight.track_id.in_(track_ids), TrackRight.contragent_id.in_(contragent_ids))
        .order_by(TrackRight.slot)
    ):
        slot = rights.setdefault((tid, cid), {}).setdefault(rtype, [ZERO, None])
        slot[0] += Decimal(share or 0)
        if slot[1] is None and royalty is not None:
            slot[1] = Decimal(royalty)

    tracks = {
        t.id: t for t in db.scalars(select(Track).where(Track.id.in_(track_ids)))
    }
    partners = dict(db.execute(select(Partner.id, Partner.name)).all())
    cards = {
        row[0]: row[1:]
        for row in db.execute(
            select(Contragent.id, Contragent.title, Contragent.contract_number,
                   Contragent.contract_date, Contragent.name, Contragent.type)
            .where(Contragent.id.in_(contragent_ids))
        ).all()
    }
    nicks: dict = {}
    for cid, nick in db.execute(
        select(ContragentNickname.contragent_id, ContragentNickname.nickname)
        .where(ContragentNickname.contragent_id.in_(contragent_ids))
    ).all():
        if nick and nick.strip():
            nicks.setdefault(cid, []).append(nick.strip())

    results: dict = {}
    for g in groups:
        cid, tid, pid, pfrom, pto = g[0], g[1], g[2], g[3], g[4]
        attr_values = g[5:9]
        qty, amount_a, amount_r = (Decimal(str(x)) for x in g[n:n + 3])
        r = rights.get((tid, cid), {})
        share_a, royalty_a = r.get("author", [ZERO, None])
        share_r, royalty_r = r.get("related", [ZERO, None])
        if not share_a and not share_r:
            continue
        base_a = amount_a * share_a / HUNDRED
        base_r = amount_r * share_r / HUNDRED
        t = tracks.get(tid)
        line = Line(
            sku=t.sku if t else "", code=(t.code or "") if t else "",
            title=(t.title or "") if t else "", artist=(t.artist or "") if t else "",
            authors=(t.authors or "") if t else "",
            share_author=share_a, share_related=share_r,
            partner=partners.get(pid, ""),
            content_type=attr_values[0] or "", usage_type=attr_values[1] or "",
            usage_kind=attr_values[2] or "", territory=attr_values[3] or "",
            period_from=pfrom, period_to=pto, quantity=qty,
            realization=base_a + base_r,
            royalty_author=royalty_a, reward_author=base_a * (royalty_a or ZERO) / HUNDRED,
            royalty_related=royalty_r, reward_related=base_r * (royalty_r or ZERO) / HUNDRED,
        )
        res = results.get(cid)
        if res is None:
            title, number, cdate, name, kind = cards.get(cid, ("", "", None, "", ""))
            res = results[cid] = Result(
                contragent_id=str(cid), title=title or "",
                contract_number=(number or "").strip(), contract_date=cdate,
                name=(name or "").strip(), kind=kind or "",
                nicknames=sorted(nicks.get(cid, []), key=str.casefold),
            )
        res.lines.append(line)

    for res in results.values():
        res.lines.sort(key=lambda ln: (ln.partner, ln.period_from or date.min, ln.sku,
                                       ln.content_type, ln.usage_type, ln.territory))
    return sorted(results.values(), key=lambda r: r.title.casefold())


# ---------------------------------------------------------------- xlsx

def period_text(s: Settings) -> str:
    return f"с  {s.period_from:%d.%m.%Y} по {s.period_to:%d.%m.%Y}"


def period_slug(s: Settings) -> str:
    """«2_квартал_2026» для ровного квартала, иначе даты — как в Dista."""
    import calendar

    f, t = s.period_from, s.period_to
    q = (f.month - 1) // 3 + 1
    start = date(f.year, (q - 1) * 3 + 1, 1)
    end = date(f.year, q * 3, calendar.monthrange(f.year, q * 3)[1])
    if (f, t) == (start, end):
        return f"{q}_квартал_{f.year}"
    return f"{f:%d.%m.%Y}-{t:%d.%m.%Y}"


def report_period(s: Settings) -> str:
    """«2-Q-2026» для ровного квартала, иначе «01.04.2026-15.05.2026» — как у юриста."""
    import calendar

    f, t = s.period_from, s.period_to
    q = (f.month - 1) // 3 + 1
    start = date(f.year, (q - 1) * 3 + 1, 1)
    end = date(f.year, q * 3, calendar.monthrange(f.year, q * 3)[1])
    if (f, t) == (start, end):
        return f"{q}-Q-{f.year}"
    return f"{f:%d.%m.%Y}-{t:%d.%m.%Y}"


def safe_name(text: str) -> str:
    """Имя файла без знаков, которых не терпит Windows."""
    return re.sub(r'[\\/:*?"<>|]+', " ", text or "").strip()


def base_name(res: Result, s: Settings) -> str:
    """
    «Ибара М.Ж. (СГ)_RE3 (2-Q-2026)» — титл_псевдоним (период), как юрист
    называет готовые отчёты (просьба владельца 25.09.2026). Псевдонимов
    несколько — через запятую; нет ни одного — только титл.
    """
    who = res.title + (f"_{', '.join(res.nicknames)}" if res.nicknames else "")
    return safe_name(f"{who} ({report_period(s)})")


def file_name(kind: str, s: Settings, res: Result) -> str:
    """
    Сводный — «<титл>_<псевдоним> (<период>).xlsx», ровно как у юриста;
    детализированный — то же с « детализация»: в одном архиве у одного
    правообладателя их два, и одно имя на двоих затёрло бы файл.
    """
    return f"{base_name(res, s)}{'' if kind == 'summary' else ' детализация'}.xlsx"


def zip_name(s: Settings, results: list) -> str:
    """
    Имя архива. Правообладатель ОДИН (сводный и детализированный вместе) —
    так же, как его файлы; иначе — общий архив за период.
    """
    if len(results) == 1:
        return f"{base_name(results[0], s)}.zip"
    return f"Отчеты правообладателям ({report_period(s)}).zip"


_BOLD = Font(bold=True)
_TITLE = Font(bold=True, size=14)
_HEAD_FILL = PatternFill("solid", fgColor="E4E4E4")  # как у Dista (Fill 15000804)
_THIN = Side(style="thin", color="BFBFBF")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")


# ВЕДОМОСТЬ — В ОФОРМЛЕНИИ ЮРИСТА (25.09.2026, просьба владельца: «сделаем
# сразу оформление как финальный отчёт у юриста»; образец — «Ибара
# М.Ж.(СГ)_RE3 (2-Q-2026).xlsx» в «Примеры отчетов от партнеров»). До этого
# собиралась ведомость Dista, которую юрист потом перекладывал руками.
#
# ОБРАЗЕЦ ЮРИСТА И ЕСТЬ ШАБЛОН (`assets/royalty_statement.xlsx` — его файл,
# из которого вычищены данные). Первый вариант повторял оформление кодом и
# разошёлся с образцом в десятке мелочей, которые видно глазом: рамки
# двойные против одинарных, шрифт книги по умолчанию (Arial 8 — от него
# Excel считает ширину колонок в пикселях), толщина линий под шапкой.
# Переписывать сорок ячеек по свойствам — значит однажды разойтись опять;
# шаблон переносит всё разом, а код только подставляет значения.
#
# «Сверка расчётов» — ФОРМУЛАМИ из шаблона: предыдущий накопительный итог и
# выплаченное у нас нигде не хранятся и приходят нулями, а юрист вписывает
# их руками — и «Накопительный итог» с «Итого по Отчёту» пересчитываются
# сами. Книга помечена «пересчитать при открытии».
ASSETS = Path(__file__).parent / "assets"
STATEMENT_TEMPLATE = ASSETS / "royalty_statement.xlsx"
LOGO = ASSETS / "logo.png"
# Размер логотипа как в образце юриста: 1591194 × 542591 EMU.
LOGO_SIZE = (167, 57)
HEADER_HEIGHT = 46
_MONEY = '#,##0.00\\ "₽"'


class _Logo(_XlImage):
    """
    Картинка без Pillow: openpyxl зовёт его ради размеров и перекодирования,
    а в образе api его нет. PNG кладём как есть, размер задаём сами.
    """

    def __init__(self, data: bytes, width: int, height: int):
        self.ref = data
        self.width, self.height = width, height
        self.format = "png"

    def _data(self) -> bytes:
        return self.ref


def _png_ok(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) > (0, 0)


def sheet_title(s: Settings) -> str:
    """Имя первого листа — «26Q(2)», как у юриста; не квартал — «Ведомость»."""
    p = report_period(s)
    if "-Q-" in p:
        q, _, y = p.split("-")
        return f"{y[2:]}Q({q})"
    return "Ведомость"


def _front_page(ws, res: Result, s: Settings, quantity, realization, royalty) -> None:
    """
    Лист 1 из шаблона — подставляем значения. `realization` и `royalty` —
    те же числа, что в итоге листа 2: документ не должен расходиться сам с
    собой на копейку.
    """
    ws.title = sheet_title(s)
    if res.contract_text:
        ws["D3"] = f" {res.contract_text}    "
    else:
        # Договора в карточке нет — нет и строк «к Лицензионному договору».
        ws["D2"] = None
        for col in "BCD":
            ws[f"{col}3"].border = Border()
    ws["B5"] = s.period_from
    ws["D5"] = s.period_to          # в образце EOMONTH(B5,2) — годится только для квартала
    ws["A8"] = res.label
    ws["B8"] = float(quantity)
    ws["C8"] = float(realization)
    ws["D8"] = float(royalty)
    ws["A21"] = f"Лицензиар: {res.name or res.title}"
    ws["C21"] = f"Лицензиат: {LICENSEE}"
    ws["A22"] = TAX_NOTE.get(res.kind)
    ws["D4"] = CITY
    try:
        data = LOGO.read_bytes()
    except OSError:
        data = b""
    if _png_ok(data):
        logo = _Logo(data, *LOGO_SIZE)
        logo.anchor = "A1"
        ws.add_image(logo)


def _grid(ws, header: list | None, rows: list, s: Settings, text_cols: set, money_cols: set,
          money_format: str, sum_cols: set, date_cols: set = frozenset(),
          widths: list | None = None) -> None:
    """
    Лист 2 из шаблона. Стиль строки берётся с образца юриста (строка 2
    шаблона): код, текст, число и сумма — по ячейке-образцу, дальше каждая
    строка копирует готовый стиль первой (так быстрее: у детализации тысячи
    строк). `header` — своя шапка (детализированный); None — шапка шаблона.
    Внизу — итог формулами и, через строку, «Детализация к отчётной
    ведомости за период…», как у юриста.
    """
    sample = {
        "code": copy(ws["A2"]._style), "text": copy(ws["B2"]._style),
        "num": copy(ws["D2"]._style), "money": copy(ws["G2"]._style),
    }
    head_style = copy(ws["A1"]._style)
    bold = copy(ws["B2"].font)
    bold.b = True
    ws.delete_rows(2)
    if header:
        for i, title in enumerate(header, 1):
            c = ws.cell(row=1, column=i, value=title)
            c._style = copy(head_style)
    # Шапка выше, чем в образце (31.2): «Сумма реализации Лицензиара» и
    # «Лицензиар Роялти авторские» в узкой колонке переносятся на четыре
    # строки и в три не влезали (замечание владельца 25.09.2026).
    ws.row_dimensions[1].height = HEADER_HEIGHT
    width = len(header) if header else ws.max_column
    if widths:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    kinds = []
    for i in range(1, width + 1):
        if i in text_cols:
            kinds.append(("text", None))
        elif i in money_cols:
            kinds.append(("money", money_format))
        elif i in date_cols:
            kinds.append(("num", "DD.MM.YYYY"))
        elif i == 1:
            kinds.append(("code", None))
        else:
            kinds.append(("num", None))
    protos = None
    for n, r in enumerate(rows, 2):
        ws.append(r)
        cells = ws[n][:width]
        if protos is None:
            for c, (kind, fmt) in zip(cells, kinds):
                c._style = copy(sample[kind])
                if fmt:
                    c.number_format = fmt
            protos = [c._style for c in cells]
        else:
            for c, st in zip(cells, protos):
                c._style = copy(st)

    last = len(rows) + 1
    total = last + 1
    for col in sum_cols:
        letter = openpyxl.utils.get_column_letter(col)
        c = ws.cell(row=total, column=col, value=f"=SUM({letter}2:{letter}{last})")
        c.font, c.alignment = copy(bold), Alignment(horizontal="left", vertical="center")
        if col in money_cols:
            c.number_format = money_format
    note = total + 2
    ws.merge_cells(start_row=note, start_column=1, end_row=note, end_column=10)
    c = ws.cell(row=note, column=1, value=f"Детализация к отчетной ведомости за период {period_text(s)}")
    c.font = copy(bold)
    c.alignment = Alignment(horizontal="left", vertical="center")


def _statement_book():
    return openpyxl.load_workbook(STATEMENT_TEMPLATE)


def _num(value) -> float | None:
    return None if value is None else float(value)


def _share(value: Decimal) -> str:
    """Доля — «100», «50», «33.33»: без хвоста «.00», как в Dista."""
    text = format(value.normalize(), "f") if value else "0"
    return text


def summary_xlsx(res: Result, s: Settings) -> bytes:
    """
    Сводный отчёт — ровно ведомость юриста: по строке на трек, суммы до
    копеек. Итог ведомости — СУММА ОКРУГЛЁННЫХ СТРОК (у юриста 9 413,26 при
    точной сумме 9 413,25): лист 1 ссылается на итог листа 2, и копейка
    между ними читалась бы как ошибка в документе.
    """
    by_track: dict = {}
    for ln in res.lines:
        acc = by_track.setdefault(ln.sku, {"line": ln, "q": ZERO, "real": ZERO, "a": ZERO, "r": ZERO})
        acc["q"] += ln.quantity
        acc["real"] += ln.realization
        acc["a"] += ln.reward_author
        acc["r"] += ln.reward_related
    rows = []
    real_total = royalty_total = ZERO
    for sku in sorted(by_track):
        acc = by_track[sku]
        ln = acc["line"]
        a, r, real = cents(acc["a"]), cents(acc["r"]), cents(acc["real"])
        total = cents(acc["a"] + acc["r"])
        real_total += real
        royalty_total += total
        rows.append([
            ln.sku, ln.title, ln.artist, _num(ln.share_author), _num(ln.share_related),
            float(acc["q"]), float(real),
            _num(ln.royalty_author), float(a), _num(ln.royalty_related), float(r), float(total),
        ])
    wb = _statement_book()
    _front_page(wb.worksheets[0], res, s, res.quantity, real_total, royalty_total)
    # Шапка — шаблонная: колонки сводного и есть колонки юриста.
    _grid(wb.worksheets[1], None, rows, s, text_cols={2, 3}, money_cols={7, 9, 11, 12},
          money_format=_MONEY, sum_cols={6, 7, 12})
    return _save(wb)


def detailed_xlsx(res: Result, s: Settings) -> bytes:
    """
    Детализированный отчёт: строки как в отчётах площадок, суммы без
    округления. Оформление и лист 1 — те же, что у сводного; итог ведомости —
    точная сумма, округлённая один раз.
    """
    rows = [[
        ln.sku, ln.code, ln.title, ln.artist, ln.authors,
        _num(ln.share_author), _num(ln.share_related), ln.partner,
        ln.content_type, ln.usage_type, ln.usage_kind, ln.territory,
        ln.period_from, ln.period_to, float(ln.quantity), float(ln.realization),
        float(ln.commission), _num(ln.royalty_author), float(ln.reward_author),
        _num(ln.royalty_related), float(ln.reward_related), float(ln.reward),
    ] for ln in res.lines]
    wb = _statement_book()
    _front_page(wb.worksheets[0], res, s, res.quantity, cents(res.realization), cents(res.reward))
    _grid(wb.worksheets[1], [
        "Код", "ISRC", "Название", "Исполнитель", "Авторы слов/музыки", "Доля Авторских прав",
        "Доля Смежных прав", "Платформа", "Тип контента", "Тип использования",
        "Вид использования", "Территория", "Начало реализации", "Окончание реализации",
        "Количество", "Сумма реализации Лицензиара", "Комиссия Лицензиата",
        "Ставка авторские права", "Лицензиар Роялти авторские", "Ставка смежные права",
        "Лицензиар Роялти смежные", "Лицензиар Роялти итого",
    ], rows, s, text_cols={2, 3, 4, 5, 8, 9, 10, 11}, money_cols={16, 17, 19, 21, 22},
        money_format='#,##0.00######\\ "₽"', sum_cols={15, 16, 17, 22}, date_cols={13, 14},
        widths=[8, 13, 19.14, 16, 16, 9.14, 8.43, 13, 10, 10, 10, 9, 10.29, 10.29,
                10.29, 13.57, 12, 9, 10.29, 8.14, 11.29, 13.43])
    return _save(wb)


def _save(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_files(results: list, s: Settings, kinds: list) -> list:
    """Файлы отчётов: [(имя, байты)] — по одному на правообладателя и вид."""
    out, seen = [], set()

    def add(name, content):
        # Два правообладателя с одинаковым титлом и псевдонимом — законно
        # (см. «title не уникален»), а в архиве второй затёр бы первого.
        stem, n = name[:-5], 2
        while name in seen:
            name, n = f"{stem} ({n}).xlsx", n + 1
        seen.add(name)
        out.append((name, content))

    for res in results:
        if "summary" in kinds:
            add(file_name("summary", s, res), summary_xlsx(res, s))
        if "detailed" in kinds:
            add(file_name("detailed", s, res), detailed_xlsx(res, s))
    return out


def zip_files(files: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            z.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------- сводные отчёты

# Сводка «по чему» — правообладателю, объекту (треку) или площадке
# (24.09.2026, просьба владельца: вместо трёх отдельных вкладок Dista — одна
# «Сводные отчёты» с выбором). Смысл у всех один: количество и суммы за
# период, разложенные по выбранному признаку.
SUMMARY_BY = {
    "holder": "правообладателям",
    "track": "объектам",
    "partner": "площадкам",
}


def _quantities(db: Session, s: Settings, by: str) -> dict:
    """
    Количество и число отчётов по треку или площадке — из строк отчётов,
    ОДИН раз на строку.

    Из расчёта вознаграждения количество брать нельзя: там строка трека
    повторяется у каждого его правообладателя, и у трека с двумя владельцами
    прослушивания посчитались бы дважды. Строки — только треков, у которых
    есть Лицензиар (с учётом выбора правообладателей и товарного фильтра):
    сводка отвечает на вопрос «сколько причитается Лицензиарам», и «вне
    каталога» к нему не относится.
    """
    R, Rep = PartnerReportRow, PartnerReport
    key = R.track_id if by == "track" else Rep.partner_id
    # Доля больше нуля: права с нулевой долей в сводку не попадают (строки
    # вознаграждения по ним нет), и их прослушивания не должны попадать в
    # количество — иначе объект и площадка разошлись бы по количеству.
    owners = select(TrackRight.track_id).where(
        TrackRight.contragent_id.isnot(None), TrackRight.share > 0
    )
    if s.contragent_ids:
        owners = owners.where(TrackRight.contragent_id.in_(s.contragent_ids))
    q = (
        select(key, func.coalesce(func.sum(R.quantity), 0), func.count(func.distinct(Rep.id)))
        .select_from(R)
        .join(Rep, Rep.id == R.report_id)
        .where(_report_filter(s), _not_pending(), R.track_id.in_(owners))
        .group_by(key)
    )
    if s.track_ids:
        q = q.where(R.track_id.in_(s.track_ids))
    return {k: (Decimal(str(qty)), int(n)) for k, qty, n in db.execute(q).all()}


def summary(db: Session, s: Settings, by: str) -> list:
    """
    Строки сводки: словари с Decimal-суммами, по убыванию вознаграждения.

    КОЛОНКИ ОДНИ И ТЕ ЖЕ во всех разрезах (правка 24.09.2026, замечание
    владельца): сумма реализации Лицензиара, вознаграждение авторские,
    смежные и итого, комиссия Лицензиата. Различаются только первые,
    опознавательные колонки. Суммы — из того же `compute`, что и ведомости,
    поэтому итоги совпадают во всех разрезах и с ведомостями.
    """
    results = compute(db, s)
    if by == "holder":
        rows = [{
            "key": r.contragent_id, "title": r.title, "tracks": r.tracks,
            "quantity": r.quantity, "realization": r.realization,
            "reward_author": r.reward_author, "reward_related": r.reward_related,
            "reward": r.reward, "commission": r.realization - r.reward,
        } for r in results]
        return sorted(rows, key=lambda x: -x["reward"])

    acc: dict = {}
    for r in results:
        for ln in r.lines:
            k = ln.sku if by == "track" else ln.partner
            a = acc.setdefault(k, {"line": ln, "realization": ZERO, "ra": ZERO, "rr": ZERO,
                                   "holders": set()})
            a["realization"] += ln.realization
            a["ra"] += ln.reward_author
            a["rr"] += ln.reward_related
            a["holders"].add(r.contragent_id)

    counts = _quantities(db, s, by)
    if by == "track":
        by_sku = {t.sku: t.id for t in db.scalars(select(Track).where(Track.sku.in_(list(acc))))}
    else:
        by_name = {name: pid for pid, name in db.execute(select(Partner.id, Partner.name)).all()}

    rows = []
    for k, a in acc.items():
        ln = a["line"]
        qty, reports = counts.get(by_sku.get(k) if by == "track" else by_name.get(k), (ZERO, 0))
        row = {
            "quantity": qty, "realization": a["realization"],
            "reward_author": a["ra"], "reward_related": a["rr"], "reward": a["ra"] + a["rr"],
            "commission": a["realization"] - a["ra"] - a["rr"],
        }
        if by == "track":
            row.update({"key": k, "sku": ln.sku, "title": ln.title, "artist": ln.artist,
                        "holders": len(a["holders"])})
        else:
            row.update({"key": k, "title": k, "reports": reports})
        rows.append(row)
    return sorted(rows, key=lambda x: -x["reward"])


# Колонки сводки для экрана и Excel: (поле, заголовок, это деньги?). Общая
# часть одна на все разрезы — она и есть «сводка»; спереди только то, по
# чему строку опознают.
_MONEY_COLUMNS = [
    ("quantity", "Количество", False),
    ("realization", "Сумма реализации Лицензиара", True),
    ("reward_author", "Вознаграждение авторские", True),
    ("reward_related", "Вознаграждение смежные", True),
    ("reward", "Вознаграждение итого", True),
    ("commission", "Комиссия Лицензиата", True),
]
SUMMARY_COLUMNS = {
    "holder": [("title", "Правообладатель", False), ("tracks", "Треков", False), *_MONEY_COLUMNS],
    "track": [("sku", "Код", False), ("title", "Название", False),
              ("artist", "Исполнитель", False), ("holders", "Правообладателей", False),
              *_MONEY_COLUMNS],
    "partner": [("title", "Площадка", False), ("reports", "Отчётов", False), *_MONEY_COLUMNS],
}
_SUMMED = {f for f, _, _ in _MONEY_COLUMNS}


def summary_totals(rows: list, by: str) -> dict:
    """Итог по всем строкам сводки: количество и суммы."""
    return {f: sum((r.get(f, ZERO) for r in rows), ZERO) for f in _SUMMED}


def summary_file_name(s: Settings, by: str) -> str:
    return f"Сводка по {SUMMARY_BY[by]} {period_slug(s)}.xlsx"


def summary_table_xlsx(rows: list, s: Settings, by: str) -> bytes:
    """Сводка одним листом: шапка, строки, итог."""
    cols = SUMMARY_COLUMNS[by]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сводка"
    ws["A1"] = f"Сводный отчёт по {SUMMARY_BY[by]} за период {period_text(s)}"
    ws["A1"].font = _TITLE
    ws.append([])
    ws.append([c[1] for c in cols])
    for c in ws[3]:
        c.font, c.fill, c.border, c.alignment = _BOLD, _HEAD_FILL, _BOX, _WRAP
    for r in rows:
        ws.append([
            float(cents(r[f])) if money else (float(r[f]) if isinstance(r.get(f), Decimal) else r.get(f, ""))
            for f, _, money in cols
        ])
    totals = summary_totals(rows, by)
    ws.append([
        "Итого" if i == 0 else (float(cents(totals[f])) if f in totals and money
                                else (float(totals[f]) if f in totals else ""))
        for i, (f, _, money) in enumerate(cols)
    ])
    for c in ws[ws.max_row]:
        c.font = _BOLD
    for i, (f, title, money) in enumerate(cols, 1):
        letter = openpyxl.utils.get_column_letter(i)
        ws.column_dimensions[letter].width = 36 if f in ("title", "artist") else (12 if not money else 18)
        if money:
            for c in ws[letter][3:]:
                c.number_format = "#,##0.00"
    ws.freeze_panes = "A4"
    return _save(wb)
