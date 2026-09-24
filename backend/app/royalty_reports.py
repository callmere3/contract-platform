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
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Contragent, Partner, PartnerPayment, PartnerReport, PartnerReportRow, Track, TrackRight,
)

# Подписи Лицензиата — «своя организация» из Dista. Одна на все отчёты;
# понадобится менять — это строка здесь, а не настройка в интерфейсе.
LICENSEE_SIGNATURE = 'Генеральный директор\nООО "Медиа Лэнд"\nПаримбетова Д.Р.'
CITY = "г. Москва"
ATTRS = ("content_type", "usage_type", "usage_kind", "territory")
CENT = Decimal("0.01")
ZERO = Decimal(0)
HUNDRED = Decimal(100)


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
    titles = dict(
        db.execute(select(Contragent.id, Contragent.title).where(Contragent.id.in_(contragent_ids))).all()
    )

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
            res = results[cid] = Result(contragent_id=str(cid), title=titles.get(cid, ""))
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


def file_name(kind: str, s: Settings, title: str) -> str:
    """«Сводный отчет 2_квартал_2026_ИбараМЖ(СГ).xlsx» — как называет Dista."""
    who = re.sub(r'[\s.\\/:*?"<>|]', "", title or "")
    word = "Сводный" if kind == "summary" else "Детализированный"
    return f"{word} отчет {period_slug(s)}_{who}.xlsx"


_BOLD = Font(bold=True)
_TITLE = Font(bold=True, size=14)
_HEAD_FILL = PatternFill("solid", fgColor="EFEBE4")
_THIN = Side(style="thin", color="BFBFBF")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")


def _front_page(ws, res: Result, s: Settings, summary: bool) -> None:
    """«Страница 1» — отчётная ведомость с итогами и подписями."""
    total = cents(res.reward)
    ws["A1"] = "Отчетная ведомость"
    ws["A1"].font = _TITLE
    ws["A5"] = CITY
    ws["E5"] = date.today().strftime("%d.%m.%Y")
    ws["A6"], ws["B6"] = "Лицензиар", res.title
    ws["A7"], ws["B7"] = "Отчётный период", period_text(s)
    ws["A9"] = "Доход Лицензиара от использования Прав за отчетный период составил:"
    ws["C11"], ws["D11"] = "Кол-во", "Сумма"
    ws["C11"].font = ws["D11"].font = _BOLD
    ws["A12"] = "Доход от использования Произведений / Объектов"
    ws["C12"], ws["D12"], ws["E12"] = float(res.quantity), float(total), "руб."
    ws["A13"], ws["D13"], ws["E13"] = "Итого доход Лицензиара", float(total), "руб."
    ws["A13"].font = _BOLD
    row = 15
    if summary:
        # Баланс и выплаты пока не ведутся — нули, как в образце из Dista.
        ws[f"A{row}"], ws[f"D{row}"], ws[f"E{row}"] = "Баланс  на начало периода", 0.0, "руб."
        ws[f"A{row + 1}"], ws[f"D{row + 1}"], ws[f"E{row + 1}"] = "Выплачено Лицензиару за период", 0.0, "руб."
        row += 3
    ws[f"A{row}"], ws[f"D{row}"], ws[f"E{row}"] = "К выплате Лицензиару за период", float(total), "руб."
    ws[f"A{row}"].font = _BOLD
    ws[f"A{row + 1}"] = "НДС не облагается"
    ws[f"A{row + 3}"] = "Подписи сторон:"
    ws[f"A{row + 5}"], ws[f"D{row + 5}"] = "Лицензиат", "Лицензиар"
    ws[f"A{row + 6}"], ws[f"D{row + 6}"] = LICENSEE_SIGNATURE, "\n" + res.title
    ws[f"A{row + 6}"].alignment = ws[f"D{row + 6}"].alignment = _WRAP
    ws.row_dimensions[row + 6].height = 48
    ws[f"A{row + 8}"], ws[f"D{row + 8}"] = "МП", "МП"
    for r in range(12, row + 1):
        if isinstance(ws[f"D{r}"].value, float):
            ws[f"D{r}"].number_format = "#,##0.00"
    ws["C12"].number_format = "#,##0"
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 8


def _table(ws, s: Settings, header: list, rows: list, widths: list, money_cols: set,
           money_format: str) -> None:
    ws["A1"] = f"Детализация к отчетной ведомости за период {period_text(s)}"
    ws["A1"].font = _BOLD
    ws.append(header)
    for c in ws[2]:
        c.font, c.fill, c.border, c.alignment = _BOLD, _HEAD_FILL, _BOX, _WRAP
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for col in money_cols:
        letter = openpyxl.utils.get_column_letter(col)
        for c in ws[letter][2:]:
            c.number_format = money_format
    ws.freeze_panes = "A3"


def _num(value) -> float | None:
    return None if value is None else float(value)


def _share(value: Decimal) -> str:
    """Доля — «100», «50», «33.33»: без хвоста «.00», как в Dista."""
    text = format(value.normalize(), "f") if value else "0"
    return text


def summary_xlsx(res: Result, s: Settings) -> bytes:
    """Сводный отчёт: по строке на трек, суммы до копеек."""
    wb = openpyxl.Workbook()
    _front_page(wb.active, res, s, summary=True)
    wb.active.title = "Страница 1"
    by_track: dict = {}
    for ln in res.lines:
        acc = by_track.setdefault(ln.sku, {"line": ln, "q": ZERO, "real": ZERO, "a": ZERO, "r": ZERO})
        acc["q"] += ln.quantity
        acc["real"] += ln.realization
        acc["a"] += ln.reward_author
        acc["r"] += ln.reward_related
    rows = []
    for sku in sorted(by_track):
        acc = by_track[sku]
        ln = acc["line"]
        a, r = cents(acc["a"]), cents(acc["r"])
        rows.append([
            ln.sku, ln.title, ln.artist, _num(ln.share_author), _num(ln.share_related),
            float(acc["q"]), float(cents(acc["real"])),
            _num(ln.royalty_author), float(a), _num(ln.royalty_related), float(r),
            float(cents((acc["a"] + acc["r"]))),
        ])
    ws = wb.create_sheet("Страница 2")
    _table(ws, s, [
        "Код", "Название", "Исполнитель", "Доля Авторских прав", "Доля Смежных прав",
        "Количество", "Сумма реализации Лицензиара", "Роялти авторские права",
        "Лицензиар вознаграждение авторские", "Роялти смежные права",
        "Лицензиар вознаграждение смежные", "Лицензиар вознаграждение итого",
    ], rows, [11, 36, 28, 11, 11, 12, 16, 11, 16, 11, 16, 16], {7, 9, 11, 12}, "#,##0.00")
    return _save(wb)


def detailed_xlsx(res: Result, s: Settings) -> bytes:
    """Детализированный отчёт: строки как в отчётах площадок, суммы без округления."""
    wb = openpyxl.Workbook()
    _front_page(wb.active, res, s, summary=False)
    wb.active.title = "Страница 1"
    rows = [[
        ln.sku, ln.code, ln.title, ln.artist, ln.authors,
        _share(ln.share_author), _share(ln.share_related), ln.partner,
        ln.content_type, ln.usage_type, ln.usage_kind, ln.territory,
        ln.period_from, ln.period_to, float(ln.quantity), float(ln.realization),
        float(ln.commission), _num(ln.royalty_author), float(ln.reward_author),
        _num(ln.royalty_related), float(ln.reward_related), float(ln.reward),
    ] for ln in res.lines]
    ws = wb.create_sheet("Страница 2")
    _table(ws, s, [
        "Код", "ISRC", "Название", "Исполнитель", "Авторы слов/музыки", "Доля авторских прав",
        "Доля смежных прав", "Платформа", "Тип контента", "Тип использования",
        "Вид использования", "Территория", "Начало реализации", "Окончание реализации",
        "Количество", "Сумма реализации Лицензиара", "Комиссия Лицензиата",
        "Роялти авторские права", "Лицензиар вознаграждение авторские",
        "Роялти смежные права", "Лицензиар вознаграждение смежные",
        "Лицензиар вознаграждение итого",
    ], rows, [11, 15, 32, 26, 30, 10, 10, 20, 14, 18, 14, 11, 12, 12, 11, 14, 14, 10, 14, 10, 14, 14],
        {16, 17, 19, 21, 22}, "0.00######")
    for c in list(ws["M"][2:]) + list(ws["N"][2:]):
        c.number_format = "DD.MM.YYYY"
    return _save(wb)


def _save(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_files(results: list, s: Settings, kinds: list) -> list:
    """Файлы отчётов: [(имя, байты)] — по одному на правообладателя и вид."""
    out = []
    for res in results:
        if "summary" in kinds:
            out.append((file_name("summary", s, res.title), summary_xlsx(res, s)))
        if "detailed" in kinds:
            out.append((file_name("detailed", s, res.title), detailed_xlsx(res, s)))
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


def _gross(db: Session, s: Settings, by: str) -> dict:
    """
    Валовые суммы отчётов площадок по треку или площадке — ДО дележа.

    Берутся все строки попавших в период отчётов, в том числе «вне каталога»:
    это тоже пришедшие деньги, и сводка по площадке без них не сошлась бы с
    её отчётом. Выбор правообладателей и товарный фильтр сужают строки до
    треков, на которые у выбранных есть права.
    """
    R, Rep = PartnerReportRow, PartnerReport
    key = R.track_id if by == "track" else Rep.partner_id
    q = (
        select(
            key,
            func.coalesce(func.sum(R.quantity), 0),
            func.coalesce(func.sum(R.amount_author), 0),
            func.coalesce(func.sum(R.amount_related), 0),
            func.count(func.distinct(Rep.id)),
        )
        .select_from(R)
        .join(Rep, Rep.id == R.report_id)
        .where(_report_filter(s), _not_pending())
        .group_by(key)
    )
    if s.contragent_ids:
        q = q.where(R.track_id.in_(
            select(TrackRight.track_id).where(TrackRight.contragent_id.in_(s.contragent_ids))
        ))
    if s.track_ids:
        q = q.where(R.track_id.in_(s.track_ids))
    return {
        k: {"quantity": Decimal(str(qty)), "author": Decimal(str(a)),
            "related": Decimal(str(r)), "reports": int(n)}
        for k, qty, a, r, n in db.execute(q).all()
    }


def summary(db: Session, s: Settings, by: str) -> list:
    """
    Строки сводки: словари с Decimal-суммами, отсортированные по убыванию
    вознаграждения (для правообладателей) или суммы по отчётам.

    Вознаграждения — из того же `compute`, что и ведомости: сводка и
    ведомости обязаны сходиться, и считать их двумя путями значило бы однажды
    получить два разных числа.
    """
    results = compute(db, s)
    if by == "holder":
        rows = [{
            "key": r.contragent_id, "title": r.title, "tracks": r.tracks,
            "quantity": r.quantity, "gross": r.realization,
            "reward_author": r.reward_author, "reward_related": r.reward_related,
            "reward": r.reward, "left": r.realization - r.reward,
        } for r in results]
        return sorted(rows, key=lambda x: -x["reward"])

    reward: dict = {}
    for r in results:
        for ln in r.lines:
            k = ln.sku if by == "track" else ln.partner
            acc = reward.setdefault(k, [ZERO, ZERO])
            acc[0] += ln.reward_author
            acc[1] += ln.reward_related
    gross = _gross(db, s, by)
    rows = []
    if by == "track":
        ids = [k for k in gross if k is not None]
        tracks = {t.id: t for t in db.scalars(select(Track).where(Track.id.in_(ids)))} if ids else {}
        for tid, g in gross.items():
            t = tracks.get(tid)
            sku = t.sku if t else ""
            ra, rr = reward.get(sku, [ZERO, ZERO]) if t else (ZERO, ZERO)
            total = g["author"] + g["related"]
            rows.append({
                "key": str(tid) if tid else "", "sku": sku,
                "title": (t.title if t else "без привязки к треку") or "",
                "artist": (t.artist or "") if t else "",
                "quantity": g["quantity"], "gross_author": g["author"], "gross_related": g["related"],
                "gross": total, "reward_author": ra, "reward_related": rr,
                "reward": ra + rr, "left": total - ra - rr,
            })
    else:
        names = dict(db.execute(select(Partner.id, Partner.name)).all())
        for pid, g in gross.items():
            name = names.get(pid, "")
            ra, rr = reward.get(name, [ZERO, ZERO])
            total = g["author"] + g["related"]
            rows.append({
                "key": str(pid), "title": name, "reports": g["reports"],
                "quantity": g["quantity"], "gross_author": g["author"], "gross_related": g["related"],
                "gross": total, "reward_author": ra, "reward_related": rr,
                "reward": ra + rr, "left": total - ra - rr,
            })
    return sorted(rows, key=lambda x: -x["gross"])


# Колонки сводки для экрана и Excel: (поле, заголовок, это деньги?).
SUMMARY_COLUMNS = {
    "holder": [
        ("title", "Правообладатель", False), ("tracks", "Треков", False),
        ("quantity", "Количество", False), ("gross", "Сумма реализации Лицензиара", True),
        ("reward_author", "Вознаграждение авторские", True),
        ("reward_related", "Вознаграждение смежные", True),
        ("reward", "Вознаграждение итого", True), ("left", "Комиссия Лицензиата", True),
    ],
    "track": [
        ("sku", "Код", False), ("title", "Название", False), ("artist", "Исполнитель", False),
        ("quantity", "Количество", False), ("gross_author", "По отчётам: авторские", True),
        ("gross_related", "По отчётам: смежные", True), ("gross", "По отчётам: итого", True),
        ("reward", "Вознаграждение правообладателям", True), ("left", "Остаётся Медиа Лэнд", True),
    ],
    "partner": [
        ("title", "Площадка", False), ("reports", "Отчётов", False),
        ("quantity", "Количество", False), ("gross_author", "По отчётам: авторские", True),
        ("gross_related", "По отчётам: смежные", True), ("gross", "По отчётам: итого", True),
        ("reward", "Вознаграждение правообладателям", True), ("left", "Остаётся Медиа Лэнд", True),
    ],
}


def summary_totals(rows: list, by: str) -> dict:
    """Итог по всем строкам сводки: суммируются числа, кроме «треков» и «отчётов»."""
    out = {}
    for field_name, _, _ in SUMMARY_COLUMNS[by]:
        if field_name in ("quantity", "gross", "gross_author", "gross_related",
                          "reward_author", "reward_related", "reward", "left"):
            out[field_name] = sum((r.get(field_name, ZERO) for r in rows), ZERO)
    return out


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
