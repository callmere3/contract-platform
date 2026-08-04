"""rename country tag КЗ -> KZ (контрагенты, шаблоны, папка)

Revision ID: e8b1c4a7f2d9
Revises: d7a3b9e4f1c2
Create Date: 2026-08-04

Переименование значения тега страны «КЗ» (кириллица) → «KZ» (латиница) — по
просьбе владельца, просто смена написания с сохранением смысла. Затрагивает
ТРИ места, где строка хранится как данные:
  - contragents.country     (тег страны контрагента)
  - templates.country       (тег страны шаблона — по нему идёт подбор)
  - template_folders.name    (папка верхнего уровня «КЗ» → «KZ»)

Подбор документов сравнивает contragents.country и templates.country НАПРЯМУЮ
(см. app/tags.py), поэтому обе колонки обязаны меняться одной транзакцией —
иначе КЗ-контрагент перестал бы находить свои KZ-шаблоны. Папка — чисто
организационный узел (подбор её имя не использует), переименовываем для
единообразия.

«РУ» НЕ трогаем — меняется только КЗ. Данные-only миграция (схему не меняет);
код источника правды (COUNTRIES/COMPANY_TYPE_BY_COUNTRY/COUNTRY_FILE_MARKER)
переведён на «KZ» этим же деплоем. Порядок: push кода → alembic upgrade сразу
(окно рассинхронизации минимально, см. CLAUDE.md).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e8b1c4a7f2d9"
down_revision = "d7a3b9e4f1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE contragents SET country = 'KZ' WHERE country = 'КЗ'")
    op.execute("UPDATE templates SET country = 'KZ' WHERE country = 'КЗ'")
    op.execute("UPDATE template_folders SET name = 'KZ' WHERE name = 'КЗ'")


def downgrade() -> None:
    op.execute("UPDATE contragents SET country = 'КЗ' WHERE country = 'KZ'")
    op.execute("UPDATE templates SET country = 'КЗ' WHERE country = 'KZ'")
    op.execute("UPDATE template_folders SET name = 'КЗ' WHERE name = 'KZ'")
