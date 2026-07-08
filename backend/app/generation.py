"""
Ядро этапа 2 — генерация документов из docx-шаблонов.

Работает на docxtpl (обёртка над python-docx + Jinja2). Метки в шаблоне
пишутся как {{ имя }} прямо в тексте Word-документа. Здесь две задачи:

  1. scan_placeholders — при загрузке шаблона найти все метки {{...}},
     чтобы система знала, какие поля нужно будет заполнить.
  2. render_document — подставить присланные данные в шаблон и вернуть
     готовый docx в виде байтов (чтобы сразу положить в MinIO).

Важно: docxtpl корректно обрабатывает случай, когда Word "разрезал" метку
на несколько внутренних фрагментов (runs) — отдельно склеивать их не нужно.
"""
import io

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
