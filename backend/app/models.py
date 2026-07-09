"""
Модели базы данных (SQLAlchemy).

  template_folders — дерево папок ПРОИЗВОЛЬНОЙ глубины (РУ → Договор → ...),
                      самоссылающаяся таблица, как обычная файловая структура
  templates         — шаблоны, каждый лежит в одной папке-листе
  template_fields   — метки, найденные в шаблоне при загрузке

Остальные таблицы (counterparties, generated_documents, users, audit_log)
добавятся на своих этапах.

ВАЖНО про doc_type: это НЕ то же самое, что папка. Папки — организация
для человека (как удобно ориентироваться в каталоге, глубина любая).
doc_type — явная классификация для бизнес-логики (автосвязка приложения/
акта с договором того же контрагента, этап 4). Она не зависит от того,
как называется или насколько глубоко вложена папка, где физически лежит
шаблон — иначе переименование папки или добавление уровня вложенности
сломает автосвязку.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TemplateFolder(Base):
    """
    Узел дерева папок. parent_id=None — папка верхнего уровня (напр. 'РУ').
    Глубина не ограничена: РУ -> Договор -> СГ-роялти -> ... сколько угодно.
    """
    __tablename__ = "template_folders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_folders.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # дочерние папки; при удалении папки удаляются и все вложенные (каскад)
    children: Mapped[list["TemplateFolder"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped["TemplateFolder | None"] = relationship(
        back_populates="children", remote_side=[id]
    )

    templates: Mapped[list["Template"]] = relationship(back_populates="folder")


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))  # путь в MinIO, не зависит от папки

    folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("template_folders.id", ondelete="RESTRICT")
    )
    # RESTRICT, не CASCADE: папку с шаблонами удалить нельзя, пока в ней
    # что-то лежит — иначе можно случайно снести целую ветку договоров

    # явная бизнес-классификация, независимая от папки (см. докстринг файла)
    doc_type: Mapped[str | None] = mapped_column(String(32))
    # 'contract' | 'appendix' | 'act' | None (прочие типы документов)

    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    folder: Mapped["TemplateFolder"] = relationship(back_populates="templates")
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
    maps_to: Mapped[str] = mapped_column(String(64), default="manual")

    template: Mapped["Template"] = relationship(back_populates="fields")


def folder_path(folder: TemplateFolder) -> list[str]:
    """
    Собирает путь от корня до папки: ['РУ', 'Договор', 'СГ-роялти'].
    Нужно для хлебных крошек в интерфейсе (этап 3) — идём вверх по parent,
    пока не дойдём до корня.
    """
    path = []
    node = folder
    while node is not None:
        path.append(node.name)
        node = node.parent
    return list(reversed(path))
