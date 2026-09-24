"""Четыре параметра отчёта — и у строки тоже

У МТС и «101 и К» тип контента, тип и вид использования и территория одни на
весь файл, и снимка в шапке отчёта хватало. Но в настоящем отчёте
правообладателю (образец владельца 24.09.2026) видно, что у Believe в одном
отчёте 308 разных сочетаний, а территория идёт по странам: один снимок
склеил бы «NO» и «MX» в одну подпись.

Колонки NULLABLE: пусто значит «у этой площадки параметр общий» — тогда его
берут из шапки отчёта. Дублировать снимок в каждую из полумиллиона строк
незачем.

Revision ID: b8e3f04a7c12
Revises: a2d6f91c74be
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e3f04a7c12"
down_revision = "a2d6f91c74be"
branch_labels = None
depends_on = None

COLUMNS = ("content_type", "usage_type", "usage_kind", "territory")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(
            "partner_report_rows", sa.Column(name, sa.String(length=120), nullable=True)
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("partner_report_rows", name)
