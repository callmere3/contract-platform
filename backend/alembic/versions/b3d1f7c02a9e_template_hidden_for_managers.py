"""templates: колонка hidden_for_managers (скрытие шаблонов от менеджеров)

Revision ID: b3d1f7c02a9e
Revises: a1f0c8e5d3b7
Create Date: 2026-07-18

Скрытый шаблон не виден роли manager (нужно для проведения тестов), а
admin/director/top_manager/tester видят и генерируют его всегда. Переключает
видимость только admin (см. SEES_HIDDEN_TEMPLATES в app/roles.py).

NOT NULL с server_default false — все существующие шаблоны остаются видимыми,
скрытие включается точечно. Колонка добавляется ОТДЕЛЬНЫМ деплоем ДО кода,
который её читает (миграция накатывается раньше модели), чтобы не ловить окно
"код ↔ схема": пустой ALTER на таблице из 8 строк — операция мгновенная.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b3d1f7c02a9e"
down_revision = "a1f0c8e5d3b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "templates",
        sa.Column(
            "hidden_for_managers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("templates", "hidden_for_managers")
