"""Отчёты партнёров: исполнитель в строке отчёта

Revision ID: e9c47b31d8a5
Revises: d4a71c9e52f8
Create Date: 2026-09-18

Исполнитель нужен не для расчёта, а для ПОДБОРА АРТИКУЛА по названию, когда
площадка код объекта не проставила (в отчёте МТС таких строк шесть, и все шесть
на самом деле есть в каталоге — просто исполнитель записан иначе: «ПОШЛАЯ
МОЛЛИ» против «Пошлая Молли», «Slim & Константа» против «Slim, Константа»).

Он же отвечает на вопрос «а что это за трек» в списке неразнесённых строк:
одного названия для этого мало — в каталоге пять разных «Азимутов».
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e9c47b31d8a5"
down_revision = "d4a71c9e52f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partner_report_rows", sa.Column("artist", sa.String(300)))


def downgrade() -> None:
    op.drop_column("partner_report_rows", "artist")
