"""contragent requisites: JSONB-реквизиты в карточке контрагента

Revision ID: d7a3b9e4f1c2
Revises: c2e5a9f1d8b3
Create Date: 2026-08-04

Аддитивная nullable-колонка contragents.requisites (JSONB) — реквизиты для
документов (адреса, банк, паспорт СГ, ЭДО-почта/НДС), словарь {имя_метки:
значение}. См. app/models.py: Contragent.requisites. Существующие карточки не
трогает (NULL по умолчанию), безопасна при живом api. Накатывать ДО кода,
который колонку читает/пишет, — но код на аддитивную nullable-колонку и так не
падает (SELECT/INSERT её просто игнорируют, пока не появилась). Порядок деплоя:
миграция → код (см. CLAUDE.md про окно «код ↔ схема»).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "d7a3b9e4f1c2"
down_revision = "c2e5a9f1d8b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contragents", sa.Column("requisites", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("contragents", "requisites")
