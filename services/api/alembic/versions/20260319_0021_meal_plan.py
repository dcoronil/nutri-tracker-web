"""add weekly meal planner

Revision ID: 20260319_0021
Revises: 20260311_0020
Create Date: 2026-03-19 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260319_0021"
down_revision: str | None = "20260311_0020"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_plan_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=24), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("servings", sa.Float(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["user_recipe.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "planned_date", "meal_type", "slot_index", name="uq_meal_plan_entry_slot"),
    )
    op.create_index(op.f("ix_meal_plan_entry_user_id"), "meal_plan_entry", ["user_id"], unique=False)
    op.create_index(op.f("ix_meal_plan_entry_planned_date"), "meal_plan_entry", ["planned_date"], unique=False)
    op.create_index(op.f("ix_meal_plan_entry_recipe_id"), "meal_plan_entry", ["recipe_id"], unique=False)
    op.create_index(op.f("ix_meal_plan_entry_product_id"), "meal_plan_entry", ["product_id"], unique=False)
    op.create_index(op.f("ix_meal_plan_entry_created_at"), "meal_plan_entry", ["created_at"], unique=False)
    op.create_index(op.f("ix_meal_plan_entry_updated_at"), "meal_plan_entry", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_meal_plan_entry_updated_at"), table_name="meal_plan_entry")
    op.drop_index(op.f("ix_meal_plan_entry_created_at"), table_name="meal_plan_entry")
    op.drop_index(op.f("ix_meal_plan_entry_product_id"), table_name="meal_plan_entry")
    op.drop_index(op.f("ix_meal_plan_entry_recipe_id"), table_name="meal_plan_entry")
    op.drop_index(op.f("ix_meal_plan_entry_planned_date"), table_name="meal_plan_entry")
    op.drop_index(op.f("ix_meal_plan_entry_user_id"), table_name="meal_plan_entry")
    op.drop_table("meal_plan_entry")
