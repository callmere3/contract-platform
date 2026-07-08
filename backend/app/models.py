"""
Модели базы данных (SQLAlchemy).

Этап 2 вводит две таблицы из общей схемы проекта:
  templates        — загруженные шаблоны с категоризацией (филиал / тип документа)
  template_fields   — метки, найденные в шаблоне при загрузке

Остальные таблицы (counterparties, generated_documents, users, audit_log)
добавятся на своих этапах. Здесь заводим только то, что нужно сейчас.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))  # путь в MinIO

    # категоризация из бизнес-логики: филиал (РУ/КЗ) и тип документа
    branch: Mapped[str] = mapped_column(String(8))          # 'РУ' | 'КЗ'
    doc_type: Mapped[str] = mapped_column(String(32))       # 'договор' | 'приложение' | 'акт'

    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # при удалении шаблона удаляются и его поля
    fields: Mapped[list["TemplateField"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateField(Base):
    __tablename__ = "template_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE")
    )
    placeholder: Mapped[str] = mapped_column(String(128))    # имя метки, напр. 'inn'

    # maps_to — откуда брать значение при генерации:
    #   'manual'  — оператор вводит вручную
    #   'counterparty.inn' и т.п. — берётся из справочника (этап 4)
    # на этапе 2 по умолчанию всё 'manual', связка со справочником настроится позже
    maps_to: Mapped[str] = mapped_column(String(64), default="manual")

    template: Mapped["Template"] = relationship(back_populates="fields")
