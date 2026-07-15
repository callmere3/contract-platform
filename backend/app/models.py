"""
Модели базы данных (SQLAlchemy).

  template_folders      — дерево папок ПРОИЗВОЛЬНОЙ глубины (РУ → Договор → ...),
                           самоссылающаяся таблица, как обычная файловая структура
  templates              — шаблоны, каждый лежит в одной папке-листе
  template_fields        — метки, найденные в шаблоне при загрузке
  contragents             — контрагенты (этап 4, брейншторм "база контрагентов")
  contragent_nicknames    — псевдонимы контрагента (много на одного контрагента)

  users                   — пользователи и роли (этап 6, брейншторм ролей)
  refresh_tokens          — выданные refresh-токены (для logout/отзыва сессии)
  audit_log               — журнал действий (кто/что/когда), этап 6

Таблицы generated_documents сознательно НЕТ — см. брейншторм.

ВАЖНО про doc_type: это НЕ то же самое, что папка. Папки — организация
для человека (как удобно ориентироваться в каталоге, глубина любая).
doc_type — явная классификация для бизнес-логики (автосвязка приложения/
акта с договором того же контрагента, этап 4). Она не зависит от того,
как называется или насколько глубоко вложена папка, где физически лежит
шаблон — иначе переименование папки или добавление уровня вложенности
сломает автосвязку.

ВАЖНО про country/contragent_type/contract_family на Template: это теги
для фильтрации "контрагент → только совместимые с ним документы" (см.
брейншторм). Nullable, потому что 8 существующих шаблонов дозаполняются
тегами вручную уже ПОСЛЕ миграции — на момент ALTER TABLE значений ещё нет.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.roles import ROLES


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

    # теги для подбора документов через контрагента (этап 4, брейншторм).
    # Nullable: у 8 текущих шаблонов заполняются вручную ПОСЛЕ миграции.
    country: Mapped[str | None] = mapped_column(String(16))          # 'РУ' | 'КЗ'
    contragent_type: Mapped[str | None] = mapped_column(String(16))  # 'СГ' | 'ИП' | 'ООО'
    contract_family: Mapped[str | None] = mapped_column(String(32))  # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'

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


class Contragent(Base):
    """
    Контрагент (СГ/ИП/ООО), для которого генерируются документы.

    title и contract_number:
      - при создании через UI — вычисляются автоматически (см. брейншторм,
        формула build_contract_number из context_builder.py) и НЕ редактируются
        в форме создания; правит их вручную напрямую в БД только владелец сервиса.
      - при импорте из Excel — берутся из файла КАК ЕСТЬ, без пересчёта
        (исторические/юридически зафиксированные значения).

    contract_date фиксируется один раз при создании карточки и дальше только
    отображается при генерации "Договора" — не пересчитывается на лету, чтобы
    номер в шапке и дата в преамбуле никогда не разъехались (см. брейншторм,
    "Почему именно так, а не иначе").

    Осознанно НЕТ уникального constraint на title/name: защита от дублей по
    ним — мягкая (поиск + подсказка на лету в UI), не блокирующая на уровне
    БД. Точный идентификатор — reg_number (см. ниже).

    Большинство бизнес-полей nullable: контрагент может быть создан "неполным"
    через импорт (обязательны фактически только title/nickname) и просто не
    участвует в фильтрации документов, пока карточку не дозаполнят вручную.
    """
    __tablename__ = "contragents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str | None] = mapped_column(String(255))   # полное ФИО/название
    title: Mapped[str] = mapped_column(String(255))         # "Иванов И. И. (СГ)" — по нему поиск

    country: Mapped[str | None] = mapped_column(String(16))          # 'РУ' | 'КЗ'
    type: Mapped[str | None] = mapped_column(String(16))             # 'СГ' | 'ИП' | 'ООО'
    contract_family: Mapped[str | None] = mapped_column(String(32))  # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'

    # Единый рег. номер контрагента: ИНН для СГ, ОГРНИП для ИП, ОГРН для ООО.
    # Одна колонка, а не три — смысл определяется полем type (см.
    # app/tags.py: REG_NUMBER_META), а не отдельной колонкой на тип. Это и
    # есть точный идентификатор контрагента (unique) — статус контрагента
    # не меняется задним числом; при смене типа заводится новая карточка
    # (см. брейншторм), поэтому одно значение на всё время жизни записи.
    # Nullable: контрагент может быть заведён "неполным" через импорт.
    reg_number: Mapped[str | None] = mapped_column(String(15), unique=True)

    contract_date: Mapped[date | None] = mapped_column(Date)
    contract_number: Mapped[str | None] = mapped_column(String(64))

    royalty_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    nicknames: Mapped[list["ContragentNickname"]] = relationship(
        back_populates="contragent", cascade="all, delete-orphan"
    )


class ContragentNickname(Base):
    """
    Псевдоним контрагента. Один контрагент — несколько никнеймов;
    участвуют в поиске контрагента наравне с title (см. брейншторм),
    на форме генерации — выпадающий список, не свободный текст.
    """
    __tablename__ = "contragent_nicknames"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contragent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contragents.id", ondelete="CASCADE")
    )
    nickname: Mapped[str] = mapped_column(String(255))

    contragent: Mapped["Contragent"] = relationship(back_populates="nicknames")


class User(Base):
    """
    Пользователь сервиса (этап 6). Заводится ТОЛЬКО вручную другим Admin'ом
    через POST /users — формы саморегистрации сознательно нет (см. брейншторм):
    в компании ограниченный список сотрудников, и заводить аккаунт должен
    тот, кто отвечает за доступ, а не любой желающий по ссылке.

    username — обычный логин (не email, см. брейншторм), уникальный,
    без валидации формата "похоже на email" — просто непустая строка.

    role — одна из ROLES (app/roles.py), проверяется на уровне приложения
    (как и country/type у Contragent — не нативный Postgres ENUM, чтобы
    добавление новой роли было ALTER не типа, а просто данных).

    is_active — деактивация вместо удаления: у audit_log есть FK на
    user_id, и удаление пользователя оборвало бы историю его действий.
    Уволенному/отстранённому сотруднику выключают is_active, аккаунт и
    вся история за ним остаются в базе.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # см. app/roles.py: ROLES
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """
    Выданные refresh-токены — отдельной таблицей, а не просто "верим
    любому JWT с правильной подписью до истечения срока", чтобы logout
    и отзыв доступа (при деактивации пользователя) работали реально, а
    не только "перестать присылать новый access-токен через 30 минут".

    token_hash — хранится хэш (sha256), не сам токен: таблица утекла —
    токены всё равно бесполезны без исходного значения, как и с паролями.
    revoked_at — не удаляем строку при logout/rotate, а помечаем: полезно
    при разборе инцидентов ("кто и когда вышел / токен был отозван").
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class AuditLog(Base):
    """
    Журнал действий — кто/что/когда (этап 6, доступен Admin и Director).

    user_id nullable + ondelete="SET NULL": пользователя можно деактивировать
    (is_active=False), но если когда-нибудь понадобится всё же физически
    удалить аккаунт — история действий не должна обрываться каскадно вместе
    с ним, только потерять привязку к конкретному user_id.

    meta — jsonb, а не отдельные колонки под каждый action: у разных действий
    разный набор деталей (для generate_document — template_id и format, для
    contragent.update — какие поля изменились), и добавление нового вида
    события не должно требовать ALTER TABLE.
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_username: Mapped[str | None] = mapped_column(String(255))
    # копия логина на момент действия — переживает деактивацию/переименование
    # пользователя, не нужно джойнить users, чтобы прочитать лог осмысленно

    action: Mapped[str] = mapped_column(String(64))
    # напр. 'contragent.create', 'contragent.delete', 'document.generate'

    entity_type: Mapped[str | None] = mapped_column(String(32))  # 'contragent' | 'template' | 'user'
    entity_id: Mapped[str | None] = mapped_column(String(64))

    meta: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
