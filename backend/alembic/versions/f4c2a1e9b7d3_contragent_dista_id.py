"""contragent dista_id (связка с базой Dista Music)

Revision ID: f4c2a1e9b7d3
Revises: e8b1c4a7f2d9
Create Date: 2026-08-08

Внешний ключ связки контрагента с записью в Dista Music (вкладка «Dista
Connect»). Dista по контрагенту хранит только внутренний id + название;
`dista_id` — этот внутренний id, сохранённый у нас, чтобы сопоставлять наши
карточки с записями Dista НАПРЯМУЮ (а не по имени, которое расходится).

Связь 1:1 (один id Dista = одна наша карточка), поэтому UNIQUE. Nullable:
у большинства карточек связки ещё нет (проставляется сверкой во вкладке), а
несколько NULL в unique-индексе Postgres разрешает. String, а не integer, —
по тем же соображениям гибкости, что и остальные внешние теги (не завязываемся
на числовой формат чужой системы).

Аддитивная nullable-колонка — код, который её читает, приезжает этим же
деплоем; порядок: push → alembic upgrade сразу (см. CLAUDE.md про окно
«код ↔ схема»).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4c2a1e9b7d3"
down_revision = "e8b1c4a7f2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contragents", sa.Column("dista_id", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_contragents_dista_id", "contragents", ["dista_id"])


def downgrade() -> None:
    op.drop_constraint("uq_contragents_dista_id", "contragents", type_="unique")
    op.drop_column("contragents", "dista_id")
