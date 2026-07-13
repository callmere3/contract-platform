"""
Ядро этапа 2 — генерация документов из docx-шаблонов.

Работает на docxtpl (обёртка над python-docx + Jinja2). Метки в шаблоне
пишутся как {{ имя }} прямо в тексте Word-документа. Здесь три задачи:

  1. scan_placeholders — при загрузке шаблона найти все метки {{...}},
     чтобы система знала, какие поля нужно будет заполнить.
  2. render_document — подставить присланные данные в шаблон и вернуть
     готовый docx в виде байтов (чтобы сразу положить в MinIO).
  3. fix_tables_for_pdf — только для пути генерации в PDF (этап 5):
     принудительно фиксирует раскладку таблиц перед конвертацией через
     LibreOffice (см. докстринг самой функции — там разобрана причина).

Важно: docxtpl корректно обрабатывает случай, когда Word "разрезал" метку
на несколько внутренних фрагментов (runs) — отдельно склеивать их не нужно.
"""
import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu
from docxtpl import DocxTemplate


def scan_placeholders(docx_bytes: bytes) -> list[str]:
    """
    Возвращает отсортированный список всех меток шаблона без дубликатов.

    Используется при загрузке шаблона: результат ляжет в таблицу
    template_fields, чтобы потом построить форму для оператора.
    """
    doc = DocxTemplate(io.BytesIO(docx_bytes))
    # get_undeclared_template_variables находит все переменные Jinja2,
    # включая используемые в {% if %} / {% for %} — пригодится на шагах 2.2-2.3
    variables = doc.get_undeclared_template_variables()
    return sorted(variables)


def render_document(docx_bytes: bytes, context: dict) -> bytes:
    """
    Подставляет context в шаблон и возвращает готовый docx как байты.

    context — словарь {имя_метки: значение}. Метки, которых нет в context,
    docxtpl подставит как пустые строки (не упадёт) — это удобно, но на
    этапе валидации стоит проверять, что все обязательные поля заполнены.
    """
    doc = DocxTemplate(io.BytesIO(docx_bytes))
    doc.render(context)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def fix_tables_for_pdf(docx_bytes: bytes) -> bytes:
    """
    Принудительно фиксирует раскладку таблиц (tblLayout=fixed + явный
    tblW) перед конвертацией в PDF через LibreOffice headless.

    ПРИЧИНА (проверено экспериментально, не теоретически): если суммарная
    заявленная ширина столбцов таблицы (tracks/performers/videoclips)
    превышает реальную печатную ширину страницы (ширина минус поля),
    Word на экране это визуально терпит — таблица просто чуть шире, чем
    "положено", но читается нормально. LibreOffice же при конвертации в
    PDF пересчитывает и сжимает столбцы по-другому — НЕПРОПОРЦИОНАЛЬНО,
    из-за чего последний столбец может схлопнуться до одной буквы на
    строку. Причём tblLayout=fixed САМ ПО СЕБЕ проблему не решает — нужно
    ещё явно выставить tblW (общую ширину таблицы) вместо "auto", а если
    сумма ширин столбцов всё равно больше доступной ширины страницы —
    пропорционально ужать ВСЕ столбцы под неё (сохраняя соотношение),
    чтобы LibreOffice не делал это сам своим алгоритмом.

    Применяется ТОЛЬКО к результату, уходящему в PDF — на скачивание
    .docx никак не влияет (там всё и так рендерится корректно в Word).
    """
    doc = Document(io.BytesIO(docx_bytes))
    section = doc.sections[0]
    usable_width = int(section.page_width) - int(section.left_margin) - int(section.right_margin)

    for table in doc.tables:
        table.autofit = False  # tblLayout=fixed

        col_widths = [int(col.width) for col in table.columns if col.width is not None]
        if not col_widths or len(col_widths) != len(table.columns):
            continue  # ширины столбцов не заданы явно — нечего фиксировать
        total_width = sum(col_widths)

        if total_width > usable_width:
            scale = usable_width / total_width
            col_widths = [int(w * scale) for w in col_widths]
            for col, w in zip(table.columns, col_widths):
                col.width = Emu(w)
                for cell in col.cells:
                    cell.width = Emu(w)
            total_width = sum(col_widths)

        tbl_pr = table._tbl.tblPr
        tbl_w = tbl_pr.find(qn("w:tblW"))
        if tbl_w is None:
            tbl_w = OxmlElement("w:tblW")
            tbl_pr.append(tbl_w)
        tbl_w.set(qn("w:type"), "dxa")
        tbl_w.set(qn("w:w"), str(Emu(total_width).twips))

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
