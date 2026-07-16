FROM python:3.12-slim

# libreoffice-writer — минимальный набор для конвертации docx (не полный
# libreoffice со всеми компонентами: Calc/Impress тут не нужны, лишние
# сотни МБ). curl — для healthcheck в docker-compose.
#
# ШРИФТЫ — это не «на всякий случай», а условие работоспособности.
# Договоры свёрстаны целиком в Times New Roman. Если его в контейнере нет,
# LibreOffice МОЛЧА подставляет другой шрифт — и если у замены другие
# ширины символов, разъезжается весь документ: строки переносятся в других
# местах, LibreOffice пересчитывает колонки таблиц, PDF перестаёт совпадать
# с тем, что показывает Word.
#
#   ttf-mscorefonts-installer — настоящий Times New Roman. Лежит в contrib
#     (отсюда отдельный sources.list), EULA принимается через debconf, сами
#     шрифты качаются с SourceForge на этапе сборки.
#   fonts-liberation — метрически совместимый клон TNR: ширины символов
#     повторяют оригинал точь-в-точь, отличается только форма букв. Стоит
#     вторым эшелоном на случай, если mscorefonts не поставится (SourceForge
#     недоступен) — тогда вёрстка всё равно не поплывёт.
#
# ГРАБЛЯ, из-за которой всё и сломалось: fonts-liberation у libreoffice
# прописан в Recommends, а --no-install-recommends его вырезает. В итоге в
# контейнере не оставалось НИ ОДНОГО метрически совместимого шрифта, и
# `fc-match 'Times New Roman'` отдавал DejaVu Serif — он заметно шире TNR.
# Поэтому шрифты перечислены явно, а не подтягиваются рекомендациями.
# Проверка после правки: docker compose exec converter fc-match 'Times New Roman'
# должен ответить Times New Roman, а не DejaVu/Liberation.
RUN echo "deb http://deb.debian.org/debian bookworm contrib" \
      > /etc/apt/sources.list.d/contrib.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
        curl \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections \
    && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8090

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
