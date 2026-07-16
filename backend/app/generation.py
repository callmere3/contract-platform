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

    ЗАЧЕМ. Таблице с tblLayout=auto LibreOffice пересчитывает ширины
    столбцов своим алгоритмом, и результат расходится с тем, что рисует
    Word. Явные fixed + tblW не оставляют ему свободы: рендерится ровно
    то, что записано в документе. (В шаблонах СГ часть таблиц уже
    объявлена fixed, но не все — например, шапка «ЕР ... год выпуска»
    идёт с auto, поэтому проход нужен.)

    ЧЕГО ЗДЕСЬ БОЛЬШЕ НЕТ (16.07.2026). Раньше функция вдобавок
    ПРОПОРЦИОНАЛЬНО УЖИМАЛА таблицы шире печатной области — у шаблонов СГ
    это 2.7–4.1% (объявлено 10342–10491 twips при печатной ширине 10064).
    Ужатие было костылём под настоящую причину: в контейнере конвертера
    не было Times New Roman, LibreOffice подменял его на DejaVu Serif —
    заметно более широкий, — и без ужатия последний столбец схлопывался
    до буквы на строку. Причина устранена в converter/Dockerfile (ставим
    настоящий TNR, Liberation вторым эшелоном), а ужатие убрано: Word
    такие таблицы НЕ сжимает, он спокойно пускает их на пару миллиметров
    в правое поле. Раз цель — PDF, неотличимый от .docx, значит и вести
    себя надо как Word, а не «аккуратнее» него.

    Применяется ТОЛЬКО к результату, уходящему в PDF — на скачивание
    .docx никак не влияет (там всё и так рендерится корректно в Word).
    """
    doc = Document(io.BytesIO(docx_bytes))

    for table in doc.tables:
        table.autofit = False  # tblLayout=fixed

        col_widths = [int(col.width) for col in table.columns if col.width is not None]
        if not col_widths or len(col_widths) != len(table.columns):
            continue  # ширины столбцов не заданы явно — нечего фиксировать
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
