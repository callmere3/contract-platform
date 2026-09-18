"""Номенклатура: одно поле для поиска вместо четырёх

Revision ID: f4a6b2c98e71
Revises: b73f2a9c41d0
Create Date: 2026-09-18

ПОЧЕМУ. Поиск шёл по четырём колонкам через OR (артикул, код, название,
исполнитель), у каждой свой триграммный индекс — и планировщик Postgres
ВЫБИРАЛ SEQ SCAN: четыре bitmap-скана по GIN он оценивает в 5600 условных
единиц, а параллельное чтение всей таблицы — дешевле. На проде это 800 мс на
каждый символ в строке поиска (замер 18.09.2026, 132 тысячи строк). Тот же
запрос с принудительным индексом — 90 мс.

ЧТО ДЕЛАЕМ. Одна вычисляемая колонка `search_text` = все четыре поля через
перевод строки, и ОДИН триграммный индекс на неё. Одно условие вместо
четырёх — плану больше не из чего выбирать, и он берёт индекс.

Разделитель — перевод строки: поиск ищет подстроку по всей склейке, и с
пробелом «100 FRX» нашло бы трек, у которого артикул кончается на 100, а код
начинается на FRX. Перевод строки в поле поиска не наберёшь.

Колонка ВЫЧИСЛЯЕМАЯ (GENERATED ALWAYS … STORED), а не заполняется кодом:
иначе её пришлось бы обновлять в трёх местах (импорт из интерфейса, скрипт,
ручная правка карточки), и однажды одно из них забыли бы — поиск молча
перестал бы находить поправленный трек.
"""
from alembic import op

# Выражение берём из модели, а не переписываем: разойдись они, и на свежей
# базе (create_all) поиск искал бы по другой склейке, чем на проде.
from app.models import SEARCH_TEXT_SQL as EXPR


# revision identifiers, used by Alembic.
revision = "f4a6b2c98e71"
down_revision = "b73f2a9c41d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE tracks ADD COLUMN search_text text "
        f"GENERATED ALWAYS AS ({EXPR}) STORED"
    )
    op.execute(
        "CREATE INDEX ix_tracks_search_trgm ON tracks "
        "USING gin (search_text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracks_search_trgm")
    op.execute("ALTER TABLE tracks DROP COLUMN IF EXISTS search_text")
