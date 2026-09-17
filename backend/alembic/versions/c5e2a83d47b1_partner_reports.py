"""ML Finance: отчёты партнёров и правила их разбора

Revision ID: c5e2a83d47b1
Revises: b3d6f81a4c92
Create Date: 2026-09-18

Три таблицы под загрузку отчётов площадок:

  partner_report_rules — правило разбора: какой столбец чем является. Колонки
    хранятся ИМЕНАМИ, а не номерами (в Dista это была позиционная формула с
    пропусками, и перестановка столбцов ломала её молча). Формула нужна там,
    где отдельной колонки нет вовсе — например, смежные = общая сумма минус
    авторские. Правило одно на партнёра: у площадки один формат отчёта.

  partner_reports — загруженный отчёт за квартал: файл, период и ИТОГИ
    СНИМКОМ. Итоги не считаются на лету: по ним сверяют деньги, и число
    должно остаться тем, каким его увидели при загрузке. Ставка НДС тоже
    снимок — она меняется, а отчёт обязан объяснять свои суммы.

  partner_report_rows — строки в едином формате (артикул, количество, сумма
    авторских, сумма смежных). Исходная строка файла не хранится: она весит
    больше самих чисел, а вернуться к ней можно по имени файла и номеру
    строки. `track_id` проставляется по артикулу при загрузке; не нашёлся —
    строка попадает в счётчик неопознанных, а не исчезает.

partner_reports.partner_id — RESTRICT: удалить партнёра, по которому загружены
отчёты, нельзя (та же защита, что у контрагента с операциями). Строки, наоборот,
CASCADE: они часть отчёта и отдельно не живут.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c5e2a83d47b1"
down_revision = "b3d6f81a4c92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_report_rules",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "partner_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_file", sa.String(255)),
        sa.Column("sheet", sa.String(120)),
        sa.Column(
            "mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("vat_rate", sa.Numeric(5, 2)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_partner_report_rules_partner_id",
        "partner_report_rules",
        ["partner_id"],
        unique=True,
    )

    op.create_table(
        "partner_reports",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "partner_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("period_year", sa.SmallInteger, nullable=False),
        sa.Column("period_quarter", sa.SmallInteger, nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("sheet", sa.String(120)),
        sa.Column("rows_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unmatched_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_quantity", sa.Numeric(16, 2)),
        sa.Column("total_author", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_related", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("vat_rate", sa.Numeric(5, 2)),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_partner_reports_partner_id", "partner_reports", ["partner_id"])
    op.create_index(
        "ix_partner_reports_period",
        "partner_reports",
        ["period_year", "period_quarter"],
    )

    op.create_table(
        "partner_report_rows",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("partner_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_num", sa.Integer, nullable=False),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("title", sa.String(300)),
        sa.Column("quantity", sa.Numeric(16, 2)),
        sa.Column("amount_author", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("amount_related", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column(
            "track_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_partner_report_rows_report_id", "partner_report_rows", ["report_id"])
    op.create_index("ix_partner_report_rows_sku", "partner_report_rows", ["sku"])
    op.create_index("ix_partner_report_rows_track_id", "partner_report_rows", ["track_id"])


def downgrade() -> None:
    op.drop_table("partner_report_rows")
    op.drop_table("partner_reports")
    op.drop_table("partner_report_rules")
