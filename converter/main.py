"""
Отдельный лёгкий сервис конвертации docx -> pdf через LibreOffice headless.

Вынесен из основного API-контейнера отдельным сервисом сознательно:
libreoffice тяжёлая зависимость (сотни МБ), не хочется тащить её в
основной образ api и пересобирать его при каждой мелкой правке кода
только из-за пакета, который в остальной логике вообще не участвует.
Общаются по простому HTTP: POST /convert принимает docx, отдаёт pdf.

Почему LibreOffice headless, а не OnlyOffice Document Server: см.
обоснование в контексте проекта — редактор (OnlyOffice) снят с роадмапа,
Word есть у всех менеджеров, править документ там незачем через браузер.
Но иногда нужна именно готовая PDF-копия (для писем, для систем, куда
docx не примут) — для разовой конвертации headless LibreOffice на порядок
проще, чем поднимать полноценный Document Server с WOPI.
"""
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

app = FastAPI(title="docx->pdf converter")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/convert")
def convert(file: UploadFile = File(...)) -> Response:
    """
    Принимает .docx, возвращает .pdf. Синхронно, без очереди — сервис
    внутренний, объём генерации документов невелик (юридический отдел,
    не массовая рассылка), конвертация одного файла занимает секунды.

    Параллельные запросы безопасны: у каждого свой профиль LibreOffice,
    см. -env:UserInstallation ниже.
    """
    content = file.file.read()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docx_path = tmp_path / "input.docx"
        docx_path.write_bytes(content)

        try:
            # --headless: без GUI. --convert-to pdf: сразу в нужный формат.
            #
            # -env:UserInstallation — СВОЙ профиль на каждый запуск, внутри
            # временной папки этого же запроса (значит и убирается сам вместе
            # с ней). Без него все процессы делят один профиль и дерутся за
            # его блокировку: на двух одновременных запросах второй soffice
            # либо падает, либо молча цепляется к чужому экземпляру. Раньше
            # здесь стоял общий HOME=/tmp — ровно этот случай.
            #
            # HOME тоже уводим в свою папку: LibreOffice лезет писать в $HOME
            # при первом запуске, а без права на запись падает с ошибкой
            # доступа (исходная причина, по которой тут вообще появился HOME).
            #
            # Цена — профиль создаётся заново на каждую конвертацию, это
            # примерно секунда сверху. Осознанный размен: одновременные
            # конвертации важнее скорости одиночной.
            profile_dir = tmp_path / "lo_profile"
            result = subprocess.run(
                [
                    "soffice",
                    f"-env:UserInstallation=file://{profile_dir}",
                    "--headless", "--norestore",
                    "--convert-to", "pdf", "--outdir", str(tmp_path),
                    str(docx_path),
                ],
                capture_output=True,
                timeout=60,
                env={"HOME": str(tmp_path)},
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=504, detail="LibreOffice не ответил за 60 секунд"
            )

        pdf_path = tmp_path / "input.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            stderr = result.stderr.decode(errors="ignore")[:500]
            raise HTTPException(
                status_code=502,
                detail=f"LibreOffice не смог сконвертировать файл: {stderr}",
            )

        pdf_bytes = pdf_path.read_bytes()

    return Response(content=pdf_bytes, media_type="application/pdf")
