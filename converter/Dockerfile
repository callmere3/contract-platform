FROM python:3.12-slim

# libreoffice-writer — минимальный набор для конвертации docx (не полный
# libreoffice со всеми компонентами: Calc/Impress тут не нужны, лишние
# сотни МБ). curl — для healthcheck в docker-compose.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8090

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
