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
  generated_documents     — история генерации (этап 7), доступна Admin/Director

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

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
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
    country: Mapped[str | None] = mapped_column(String(16))          # 'РУ' | 'KZ'
    contragent_type: Mapped[str | None] = mapped_column(String(16))  # 'ФЛ' | 'СГ' | 'ИП' | 'ООО' | 'ТОО'
    contract_family: Mapped[str | None] = mapped_column(String(32))  # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'

    # Скрытый от менеджеров шаблон (для тестов): роль manager его не видит в
    # дереве и в подборе по контрагенту и не может сгенерировать. Остальные
    # роли (admin/director/top_manager/tester) видят и генерируют всегда,
    # переключает видимость только admin. См. SEES_HIDDEN_TEMPLATES в roles.py.
    hidden_for_managers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )

    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    folder: Mapped["TemplateFolder"] = relationship(back_populates="templates")
    fields: Mapped[list["TemplateField"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


# Порядок типов документов в списках — по важности: договор → приложение →
# акт (решение владельца). Раньше списки шли просто по имени, и алфавит ставил
# «Акт» первым. Единый источник правды на оба места, где показывается список
# шаблонов: дерево папок (browse_folder) и подбор по контрагенту
# (list_contragent_templates). None/прочие типы — в конце.
DOC_TYPE_SORT_ORDER = {"contract": 0, "appendix": 1, "act": 2}


def doc_type_sort_key():
    """
    SQLAlchemy-выражение для ORDER BY: договор→приложение→акт, прочее в конце.
    Использовать перед Template.name: .order_by(doc_type_sort_key(), Template.name).
    """
    from sqlalchemy import case

    return case(
        *[(Template.doc_type == dt, i) for dt, i in DOC_TYPE_SORT_ORDER.items()],
        else_=99,
    )


# Папки шаблонов пользователи называют по типу документа («Договор» /
# «Приложение» / «Акт»). Сортируем их в том же порядке важности, что и сами
# документы (см. DOC_TYPE_SORT_ORDER), — иначе алфавит ставит «Акт» первым.
# Папки с другими именами идут после, по алфавиту. Ключ — имя, а не doc_type:
# у папки типа документа нет, это просто узел дерева.
FOLDER_NAME_SORT_ORDER = {"Договор": 0, "Приложение": 1, "Акт": 2}


def folder_name_sort_key():
    """
    SQLAlchemy-выражение для ORDER BY подпапок: Договор→Приложение→Акт, прочие
    имена — после, по алфавиту. Использовать перед TemplateFolder.name:
    .order_by(folder_name_sort_key(), TemplateFolder.name).
    """
    from sqlalchemy import case

    return case(
        *[(TemplateFolder.name == n, i) for n, i in FOLDER_NAME_SORT_ORDER.items()],
        else_=99,
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

    Осознанно НЕТ уникального constraint на title/name/reg_number: у одного
    человека бывают отдельные карточки на аванс и роялти — один и тот же ИНН
    (reg_number) и одинаковый титл на нескольких карточках это норма. Точный
    уникальный идентификатор контрагента — dista_id (наш код из Dista), см.
    ниже; он и есть надёжный ключ для правки/сопоставления.

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

    country: Mapped[str | None] = mapped_column(String(16))          # 'РУ' | 'KZ'
    type: Mapped[str | None] = mapped_column(String(16))             # 'ФЛ' | 'СГ' | 'ИП' | 'ООО' | 'ТОО'
    contract_family: Mapped[str | None] = mapped_column(String(32))  # 'РОЯЛТИ' | 'АВАНС' | 'АВАНС_ОБЯЗАТЕЛЬСТВО'

    # Единый рег. номер контрагента: ИНН для СГ, ОГРНИП для ИП, ОГРН для ООО.
    # Одна колонка, а не три — смысл определяется полем type (см.
    # app/tags.py: REG_NUMBER_META), а не отдельной колонкой на тип.
    # НЕ уникален (index, не unique): у человека карточки на аванс и роялти
    # делят один ИНН/ОГРНИП. Уникальный идентификатор — dista_id, не reg_number.
    # Nullable: контрагент может быть заведён "неполным" через импорт.
    reg_number: Mapped[str | None] = mapped_column(String(15), index=True)

    contract_date: Mapped[date | None] = mapped_column(Date)
    contract_number: Mapped[str | None] = mapped_column(String(64))

    royalty_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    # Реквизиты для документов (адреса, банк, паспорт СГ, ЭДО-почта/НДС и т.п.).
    # ОДИН JSONB-словарь {имя_метки: значение}, а не колонка на поле: набор
    # реквизитов разный по типу контрагента и завязан на метки .docx, поэтому
    # добавление новой метки в шаблон не требует миграции. Ключи — те же имена
    # меток, что и в форме генерации (phone, rs, bik, legal_adress, vat…),
    # поэтому подстановка при генерации идёт по совпадению имени (см.
    # get_template_fields), без ручной настройки maps_to на каждом шаблоне.
    # reg_number сюда НЕ входит — он отдельная колонка-идентификатор выше.
    # nullable/пустой словарь — реквизиты необязательны (карточку заводят
    # неполной, дозаполняют позже).
    requisites: Mapped[dict | None] = mapped_column(JSONB)

    # Связка с базой контрагентов Dista Music (вкладка «Dista Connect»):
    # внутренний id записи в Dista. Наш сервис — мастер данных, а Dista держит
    # по контрагенту только id + название; dista_id хранит этот id, чтобы
    # сопоставлять карточки НАПРЯМУЮ по нему, а не по расходящемуся имени.
    # Связь 1:1 (unique), nullable — у большинства карточек связки ещё нет
    # (проставляется сверкой). См. routers_dista.py.
    dista_id: Mapped[str | None] = mapped_column(String(32), unique=True)

    # «Не заводить в Dista»: карточка без dista_id, помеченная этим флагом,
    # убирается из списка «Нет в Dista» и не считается несвязанной. Для тестовых
    # контрагентов (обкатка шаблонов), которых в Dista добавлять не нужно.
    dista_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )

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

    # Время последнего авторизованного запроса — обновляется в
    # get_current_user (с троттлингом ~60с, см. auth.py). По нему вкладка
    # "Пользователи" показывает "в сети" (< 5 мин) / "был(а) тогда-то".
    # Nullable: у пользователя, ни разу не заходившего после ввода фичи,
    # значения ещё нет.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    # напр. 'contragent.create', 'contragent.delete', 'user.update'.
    # generate_document сюда больше не пишет — см. GeneratedDocument ниже.

    entity_type: Mapped[str | None] = mapped_column(String(32))  # 'contragent' | 'template' | 'user'
    entity_id: Mapped[str | None] = mapped_column(String(64))

    meta: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GeneratedDocument(Base):
    """
    История генерации документов — вкладка "История генерации" (Admin, Director).

    Готовый .docx/.pdf НИГДЕ не хранится (ни в MinIO, ни где-либо ещё) —
    вместо этого запоминаем payload (сырые данные формы, ровно то, что
    пришло в теле POST /templates/{id}/generate) и template_id. Чтобы
    посмотреть документ повторно, он воссоздаётся на лету тем же
    render_document(), что и при первой генерации (см. app/generation.py) —
    это этап 2 фичи, само поле уже здесь, чтобы не делать вторую миграцию.

    template_id/contragent_id/user_id — nullable + ondelete="SET NULL":
    шаблон могут удалить, контрагента — тоже, пользователя — деактивировать
    (как и в AuditLog выше). Запись в истории не должна пропадать вместе с
    ними, только терять привязку к конкретной записи. Имя/название на
    момент генерации сохраняются отдельными колонками-снимками — история
    должна оставаться читаемой даже после переименования/удаления.

    Пересоздание документа по СТАРОМУ template_id, если шаблон с тех пор
    изменили (перезалит файл, другие метки) — вернёт другой результат,
    чем был исходно. Это осознанный компромисс: хранить сам файл шаблона
    на каждую генерацию было бы избыточно, а метки редко меняются настолько,
    чтобы старый payload перестал подходить.
    """
    __tablename__ = "generated_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_username: Mapped[str | None] = mapped_column(String(255))

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL")
    )
    template_name: Mapped[str] = mapped_column(String(255))

    contragent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contragents.id", ondelete="SET NULL")
    )
    contragent_title: Mapped[str | None] = mapped_column(String(255))
    # Nullable: шаблон можно сгенерировать и без привязки к контрагенту
    # (напрямую из "Папок", см. DocFormPage — contragentId там необязателен)

    nickname: Mapped[str | None] = mapped_column(String(255))
    # Псевдоним, ДЛЯ КОТОРОГО сгенерирован именно этот документ — берётся
    # прямо из payload формы (поле 'nickname'), а не из карточки контрагента:
    # у контрагента псевдонимов может быть несколько (см. ContragentNickname),
    # и разные генерации по одному контрагенту законно используют разные.
    # Nullable: не у каждого шаблона есть метка nickname.

    format: Mapped[str] = mapped_column(String(8))  # 'docx' | 'pdf'
    payload: Mapped[dict] = mapped_column(JSONB)  # сырые данные формы — для пересоздания (этап 2)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Announcement(Base):
    """
    Уведомление, которое админ написал команде — вкладка «Уведомления» у
    него и значок с непрочитанными в шапке у всех остальных.

    Заменило собой card_suggestions (предложения дозаполнить карточку):
    механизм признан бесполезным и убран целиком 16.09.2026, СТАРАЯ ТАБЛИЦА
    при этом осталась в базе нетронутой — удалять историю ради смены экрана
    несоразмерно.

    title — короткий заголовок, text — сам текст, оба без разметки.
    Заголовок добавлен 16.09.2026: в панели уведомления лежат списком, и по
    первым словам текста не всегда понятно, о чём объявление, — а разворачивать
    каждое, чтобы это выяснить, и есть та работа, которую заголовок снимает.
    NULLABLE только ради старых строк: у отправленных до этой даты заголовка
    нет и взяться ему неоткуда. Новые без него не создаются — проверка в
    NewAnnouncement, а не в схеме БД.

    Важности (срочное/обычное) по-прежнему нет намеренно: объявление на десять
    человек — это одна-две фразы, а лишние поля заставляют их выдумывать.

    author_id + author_username — как в AuditLog: снимок логина рядом с
    ссылкой, чтобы объявление осталось читаемым после деактивации автора.
    """
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_username: Mapped[str | None] = mapped_column(String(255))

    title: Mapped[str | None] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    recipients: Mapped[list["AnnouncementRecipient"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )


class AnnouncementRecipient(Base):
    """
    Кому адресовано уведомление и прочитано ли им.

    Строка на каждого получателя, а не флаг «всем» в самом объявлении.
    Почему так:
      - «прочитали 3 из 7» — это COUNT по строкам, а не догадка;
      - состав адресатов фиксируется НА МОМЕНТ ОТПРАВКИ: сотрудник,
        заведённый завтра, не увидит вчерашнее объявление, а отключение
        человека не переписывает список задним числом;
      - адресное «всем» и «выбранным» хранятся одинаково, и читающий код не
        разветвляется.

    read_at — когда человек открыл панель уведомлений (NULL = не читал).
    Отметка ставится на всё непрочитанное разом: панель и есть прочтение,
    отмечать каждое по отдельности незачем.
    """
    __tablename__ = "announcement_recipients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    announcement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Получатель убрал уведомление у себя. Именно ПОМЕТКА, а не удаление
    # строки: на строке держится и «кому адресовано», и «прочитал ли» —
    # админское «прочитали 3 из 7». Удали её физически, и у админа молча
    # уменьшился бы знаменатель, а человек пропал бы из списка получателей,
    # будто ему и не отправляли.
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    announcement: Mapped["Announcement"] = relationship(back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", name="uq_announcement_recipient"),
    )


class FinanceOperation(Base):
    """
    Поступление или расход по контрагенту — ML Finance.

    Баланс контрагента НЕ ХРАНИТСЯ отдельной колонкой, а считается суммой
    операций (app/finance.py: balances/totals). Хранимый баланс — это второй
    источник правды: его надо пересчитывать при каждой правке, и он тихо
    разъезжается с операциями ровно в тот день, когда кто-то поправит строку
    мимо приложения. Операций у одного контрагента десятки, не миллионы —
    считать их на лету дёшево.

    amount — ВСЕГДА ПОЛОЖИТЕЛЬНАЯ. Знак задаёт kind ('income' / 'expense'),
    а не минус в сумме: иначе одно и то же («вернули аванс») можно записать
    двумя способами, и любой отчёт по расходам придётся считать с оговорками.

    Numeric(14, 2), а не float: деньги в двоичной дроби расходятся в копейках,
    которые потом никто не найдёт. 14 знаков — это до 999 999 999 999.99.

    occurred_on — когда операция ПРОИЗОШЛА, created_at — когда её занесли.
    Это разные даты: операцию регулярно заносят задним числом, и баланс на
    дату должен считаться по первой, а «кто и когда внёс» — по второй.

    created_by + created_username — как в audit_log: снимок имени рядом со
    ссылкой, чтобы строка осталась читаемой после деактивации сотрудника.

    Удаления контрагента с операциями НЕТ: ondelete='RESTRICT' (см. также
    delete_contragent — он отвечает понятным 409). Каскад здесь означал бы,
    что удаление карточки молча стирает денежную историю.
    """
    __tablename__ = "finance_operations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    contragent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contragents.id", ondelete="RESTRICT"), index=True
    )

    # 'income' | 'expense' — см. OPERATION_KINDS в app/finance.py.
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Код категории из FINANCE_CATEGORIES (app/finance.py), не подпись:
    # подпись можно переписать, не трогая сохранённые строки.
    category: Mapped[str] = mapped_column(String(32))

    occurred_on: Mapped[date] = mapped_column(Date, index=True)

    # ПЕРИОД ПОСТУПЛЕНИЯ — за какие кварталы пришли деньги. Только у
    # поступлений: квартальный отчёт относится к кварталу, а не к дате
    # зачисления (за I квартал приходит в апреле), и одним платежом нередко
    # закрывают несколько кварталов сразу — отсюда пара «с» и «по».
    #
    # Четыре числа, а не строка «2026-Q1» и не даты: строку пришлось бы
    # разбирать везде, где нужно сравнение, а даты выглядели бы точнее, чем
    # есть («с 01.01 по 31.03» — не то, что вводил человек). У ОДНОГО квартала
    # начало и конец совпадают, чтобы читающий код не разбирал случай «пусто =
    # один квартал». У расходов всё четыре пустые.
    period_year_from: Mapped[int | None] = mapped_column(SmallInteger)
    period_quarter_from: Mapped[int | None] = mapped_column(SmallInteger)
    period_year_to: Mapped[int | None] = mapped_column(SmallInteger)
    period_quarter_to: Mapped[int | None] = mapped_column(SmallInteger)

    document_number: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_username: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserEvent(Base):
    """
    След действия в интерфейсе, которого нет в других таблицах.

    Заведена ради достижения «Разбитое сердце» (выйти из формы, не сохранив
    черновик): документ при этом не создан, черновик стёрт, в audit_log
    такое не пишется — журнал про работу с данными, а не про клики.
    Считать достижение не из чего, если не оставить строчку здесь.

    Таблица общая, а не «сброшенные черновики»: подобных событий будет
    больше, и таблица под каждое — расточительство. Имя события — строка,
    но сервер принимает только из белого списка (routers_profile.py),
    иначе клиент мог бы насыпать сюда что угодно.
    """
    __tablename__ = "user_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Partner(Base):
    """
    Партнёр — площадка или агрегатор, от которого приходят деньги (Яндекс
    Музыка, VK, дистрибьютор). Справочник ML Finance.

    У КАРТОЧКИ НЕТ СВОЙСТВ, и это не заготовка «пока так»: партнёр нужен,
    чтобы поступление можно было к кому-то отнести, а всё остальное про него —
    договор, реквизиты, ставки — живёт в карточках контрагентов и в самих
    отчётах. Понадобится поле — добавится колонкой; заводить их про запас
    значит заводить пустые поля, которые никто не заполняет.

    Имя уникально (без учёта регистра проверяет роутер): справочник, в котором
    «Яндекс Музыка» лежит трижды, перестаёт быть справочником.

    Отдельная таблица, а не тип контрагента: контрагент — тот, КОМУ мы платим,
    партнёр — тот, КТО платит нам. Их пути в расчёте расходятся полностью, и
    складывать их в одну таблицу ради экономии таблицы значит потом всюду
    писать «где type != …».
    """
    __tablename__ = "partners"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Код площадки в Dista — чтобы сверяться с ней по коду, а не по имени.
    # Имена площадок расходятся первыми («Яндекс Музыка» против «Yandex
    # Music»), а код не меняется. Та же роль, что у dista_id контрагента, и
    # те же свойства: связь 1:1 (unique) и nullable — у части партнёров кода
    # не будет, пока его не проставят.
    dista_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Выражение колонки поиска — ОДНО НА ДВА МЕСТА: модель (create_all на пустой
# базе и в прогонах на SQLite) и миграция, которая накатывает его на прод.
# Разделитель — НАСТОЯЩИЙ перевод строки, а не chr(10): так выражение понимают
# оба движка, а в поле поиска перевод строки не наберёшь, и совпадение через
# границу полей («100» + «FRX…») невозможно.
SEARCH_TEXT_SQL = (
    "coalesce(sku, '') || '\n' || coalesce(code, '') || '\n' || "
    "coalesce(title, '') || '\n' || coalesce(artist, '')"
)


class Track(Base):
    """
    Трек каталога лейбла — номенклатура ML Finance.

    Поля повторяют выгрузку из Dista ОДИН В ОДИН и хранятся как есть, без
    приведения к «правильному» виду. Причина простая: мы пока не знаем, что в
    этих данных значит каждое поле, и догадки лучше держать в коде показа, а
    не в схеме. Переименовать колонку потом дешевле, чем восстановить
    значение, которое импорт округлил или «исправил».

    КЛЮЧ — АРТИКУЛ (`sku`), наш внутренний код. Он уникален по построению и
    уникален по факту: в выгрузке от 16.09.2026 на 121 529 строк ни одного
    дубля. ISRC на эту роль не годится совсем — у него 11 643 повтора, а у
    26 треков он и вовсе 'TBA'. Тот же выбор, что у контрагентов: свой код
    (`dista_id`), а не чужой идентификатор.

    ДОЛИ ЖИВУТ В ДВУХ МЕСТАХ, и это не дублирование:
      - `share_author` / `share_related` — «Доля авторских прав» и «Доля
        смежных прав» из выгрузки, то есть доля НА УРОВНЕ ТРЕКА;
      - строки `TrackRight` — доли отдельных правообладателей.
    Они не всегда согласованы: у 45 617 треков доля смежных равна нулю, а
    владелец смежных прав при этом указан с долей 100%. Что из этого правда,
    выяснится на живом отчёте (см. брейншторм по номенклатуре, §3) — до тех
    пор храним оба числа и показываем оба.

    Треки не удаляются: исчезнувший из выгрузки помечается `archived_at`.
    Удалять позицию, по которой могли идти начисления, нельзя — та же логика,
    что у контрагента с операциями.
    """
    __tablename__ = "tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Артикул — строка, а не число: в выгрузке он строковый и ведущие нули в
    # нём терять нельзя.
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    code: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    artist: Mapped[str | None] = mapped_column(String(300), index=True)
    # «Автор слов/музыки» — в выгрузке это одна строка с перечислением через
    # запятую, а не список. Разбирать её на людей нечем: у авторов нет ни
    # кодов, ни отдельных колонок, и «Иванов И., Петров П.» от «Иванов И.
    # Петров» отличить можно только на глаз.
    authors: Mapped[str | None] = mapped_column(Text)
    share_author: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    share_related: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    catalog: Mapped[str | None] = mapped_column(String(255), index=True)
    album: Mapped[str | None] = mapped_column(String(300))
    genre: Mapped[str | None] = mapped_column(String(120))
    # Колонка «Роялти» выгрузки — общая ставка по треку. НЕ производная от
    # ставок правообладателей: в 295 строках она с ними расходится (80 против
    # 70), поэтому хранится отдельно, а не считается на лету.
    royalty_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # «Дата прав». У 116 450 треков это 01.01.2000 — очевидная заглушка
    # Dista, но чинить её за них мы не вправе: показываем как есть.
    rights_since: Mapped[date | None] = mapped_column(Date)

    # Откуда приехала строка. Файлов будет много (импорт ежедневный), и без
    # этого через полгода не ответить, из какой выгрузки взялась цифра.
    source_file: Mapped[str | None] = mapped_column(String(160))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # КАТАЛОГ или неКАТАЛОГ (18.09.2026). Изъятые позиции лежат в той же
    # таблице и отличаются только этим флагом: поля у них те же, права те же,
    # и весь код показа, поиска и выгрузки общий — отдельная таблица означала
    # бы вторую копию всего этого ради одного «где лежит».
    #
    # Это НЕ `archived_at`. Архив — «строка исчезла из выгрузки Dista», то
    # есть наблюдение; неКаталог — решение изъять позицию, и приезжает оно
    # отдельным файлом.
    in_catalog: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true(), default=True
    )

    # ПОЛЕ ПОИСКА — склейка тех четырёх полей, по которым ищут (артикул, код,
    # название, исполнитель), через перевод строки. Нужна она ради ОДНОГО
    # триграммного индекса вместо четырёх: с четырьмя условиями через OR
    # планировщик считал индексы дороже полного чтения таблицы и брал seq scan
    # — 800 мс на каждый символ в строке поиска (замер 18.09.2026).
    #
    # Вычисляемая БАЗОЙ, а не заполняется кодом: иначе её пришлось бы
    # обновлять в трёх местах (импорт из интерфейса, скрипт, ручная правка), и
    # однажды одно из них забыли бы — поиск молча перестал бы находить
    # поправленный трек.
    search_text: Mapped[str | None] = mapped_column(
        Text, Computed(SEARCH_TEXT_SQL, persisted=True)
    )

    rights: Mapped[list["TrackRight"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class TrackRight(Base):
    """
    Право на трек: кто, какой вид права, какая доля и по какой ставке роялти.

    СТРОКА, А НЕ КОЛОНКА. В выгрузке Dista это «Владелец авт.прав 1»,
    «Доля(%) авт.прав 1», «Роялти(%) авт. прав 1», затем то же для второго и
    третьего — таблица растёт вправо и обрывается на третьем месте (в файле
    от 16.09.2026 третий слот занят у 32 треков, и ничто не обещает, что
    завтра не появится четвёртый). У нас это строки: сколько правообладателей,
    столько и строк, а ключ — тройка (трек, правообладатель, вид права).

    `slot` хранит номер из выгрузки, чтобы карточка показывала
    правообладателей в том же порядке, в каком их видят в Dista. Смысла,
    кроме порядка, у него нет.

    Доля и роялти — ПРОЦЕНТЫ (100.00, 80.00), хотя в выгрузке лежат долями
    единицы (1, 0.8). Приведение делает импорт, один раз: иначе каждое место
    показа множило бы на сто самостоятельно, и однажды кто-нибудь забыл бы.
    """
    __tablename__ = "track_rights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), index=True
    )
    # 'author' — авторские (на произведение), 'related' — смежные (на
    # фонограмму). Виды независимы: у кавера фонограмма своя, а произведение
    # чужое, поэтому доли считаются по каждому виду отдельно.
    right_type: Mapped[str] = mapped_column(String(8))
    slot: Mapped[int] = mapped_column(SmallInteger)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    # ССЫЛКА НА КАРТОЧКУ КОНТРАГЕНТА (17.09.2026). До неё правообладатель жил
    # в каталоге просто строкой, и совпадал с карточкой только текстом: 99.46%
    # строк совпадали буква в букву, но переименование карточки молча рвало
    # связь, а у одного лейбла в каталоге встречалось по два написания («ООО
    # Густ Мьюзик» и «ООО ГУСТ МЬЮЗИК» — 26 609 и 1 132 трека). Считать по
    # таким совпадениям деньги нельзя, поэтому у права теперь настоящая
    # ссылка.
    #
    # ИМЯ ПРИ ЭТОМ ОСТАЁТСЯ. Оно не дубликат титла, а то, как правообладатель
    # записан в выгрузке Dista: по нему сверяют файл глазами, и затирать его
    # титлом карточки значило бы подменять источник.
    #
    # nullable: строка из выгрузки может прийти с именем, которого в базе
    # ещё нет. Импорт из интерфейса такие заводит сам, серверный скрипт —
    # только по флагу, и до тех пор право живёт без ссылки.
    contragent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contragents.id", ondelete="RESTRICT"), index=True
    )
    share: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    royalty: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    track: Mapped["Track"] = relationship(back_populates="rights")


class PartnerReportRule(Base):
    """
    ПРАВИЛО РАЗБОРА ОТЧЁТА ПАРТНЁРА — то самое «настроить по образцу»
    (18.09.2026). У каждой площадки свой файл, и правило говорит, какой
    столбец чем является.

    КОЛОНКИ ХРАНЯТСЯ ИМЕНАМИ, А НЕ НОМЕРАМИ. В Dista это была строка вида
    `-;-;АРТИКУЛ;-;-;КОЛИЧЕСТВО;…`: позиции с пропусками. Площадка меняет
    порядок столбцов — формула молча начинает читать соседние данные, и
    заметить это можно только по итогам. По имени такого не бывает: колонка
    либо есть, либо разбор честно говорит, что её нет.

    `mapping` — JSON: {поле: {"column": "Имя"} | {"formula": "[A] - [B]"}}.
    Формула нужна там, где отдельной колонки нет вовсе: у части площадок есть
    только общая сумма, а авторские и смежные надо посчитать (просьба
    владельца: «сейчас я пишу формулу руками»).

    `vat_rate` — ставка НДС, которую надо ВЫЧЕСТЬ из сумм отчёта. Свойство
    файла целиком, а не колонки: в одном отчёте суммы либо с налогом, либо
    без, и повторять `/1.2` в каждой колонке значит однажды поправить одну и
    забыть вторую.

    Правило ОДНО НА ПАРТНЁРА (unique): у площадки один формат отчёта. Начнут
    присылать два — здесь появится имя варианта, а не вторая таблица.
    """
    __tablename__ = "partner_report_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Имя файла-образца: по нему собирали правило, и через полгода это
    # единственный способ понять, какой отчёт имелся в виду.
    sample_file: Mapped[str | None] = mapped_column(String(255))
    sheet: Mapped[str | None] = mapped_column(String(120))
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # ПАРАМЕТРЫ ОТЧЁТА ПО УМОЛЧАНИЮ (18.09.2026). У площадки они из отчёта в
    # отчёт одни и те же — «музыка, публичное исполнение, стриминг, РФ», — и
    # вбивать их каждый раз заново незачем: правило помнит, форма подставляет,
    # человек при надобности правит.
    #
    # СТРОКИ, А НЕ СПРАВОЧНИК: какие значения бывают, знает площадка, а не мы.
    # Любой зафиксированный список разошёлся бы с первым же новым партнёром;
    # подсказки в поле собираются по тому, что уже вводили.
    content_type: Mapped[str | None] = mapped_column(String(120))
    usage_type: Mapped[str | None] = mapped_column(String(120))
    usage_kind: Mapped[str | None] = mapped_column(String(120))
    territory: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PartnerPayment(Base):
    """
    ПОСТУПЛЕНИЕ ОТ ПЛОЩАДКИ: деньги, которые реально пришли на счёт
    (19.09.2026, просьба владельца).

    Это НЕ `FinanceOperation` и не отчёт. Отчёт говорит, что площадка
    насчитала; поступление — что дошло до счёта, когда, по какому курсу и
    сколько из этого завели. Одним платежом нередко закрывают несколько
    отчётов, а курс и завод к отчёту отношения не имеют вовсе.

    ПРАВИТСЯ ПРЯМО В ТАБЛИЦЕ, в отличие от денежных операций контрагента, где
    правки нет вовсе. Причина в самой строке: «заведено» и «сумма
    фактического завода» проставляются ПОЗЖЕ платежа, иногда через недели.
    Строка тут не запись в книге, а живой лист, который дозаполняют.

    Деньги — Numeric и наружу строками, как везде в ML Finance: float в JSON
    превращает 1234.10 в 1234.0999999999999.
    """
    __tablename__ = "partner_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # НОМЕР СТРОКИ ВНУТРИ МЕСЯЦА — ИЗ ФАЙЛА, а не вычисленный (просьба
    # владельца 24.09.2026: «нумерация должна совпадать с файлом экселя»).
    # Раньше он считался порядком заведения, и это молча ломалось: весь файл
    # заводится одним импортом, у всех строк одинаковый `created_at`, и
    # порядок внутри месяца оставался на усмотрение сортировки по id.
    #
    # Номером ссылаются из вкладки «Отчёты» и называют строку вслух, поэтому
    # он обязан быть тем же, что в выписке на руках у человека. Nullable: у
    # строки, заведённой руками, номера из файла нет — он назначается
    # следующим свободным в её месяце.
    number: Mapped[int | None] = mapped_column(Integer)
    # Дата поступления. Она же определяет, в каком месяце строка видна: месяц
    # и квартал на экране — это отбор по ней, отдельного поля «период» нет.
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    # Площадка. NULLABLE намеренно: строку заводят по выписке, а чей это
    # платёж, иногда выясняют потом. Пустая площадка — честное «ещё не
    # разобрались», а не повод не дать завести строку.
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="RESTRICT"), index=True
    )
    # ПЛОЩАДКА, КОТОРОЙ НЕТ В СПРАВОЧНИКЕ (23.09.2026, просьба владельца):
    # мелкие партнёры по синхронизации отчётов не присылают, отдельно их не
    # заводят, а деньги от них приходят и подписать строку надо. Отдельное
    # поле, а не автозаведение партнёра: справочник площадок — это те, по кому
    # мы разбираем отчёты, и посторонние в нём сломали бы и выбор площадки при
    # загрузке, и сверку при привязке отчёта.
    #
    # Заполнено одно из двух: либо ссылка, либо имя. Ссылка главнее — если
    # площадку выбрали из справочника, набранное имя стирается.
    partner_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Сумма, как она пришла, и курс, по которому её заводят. Курс — шесть
    # знаков: у валют вроде тенге третьего знака не хватает.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    # СУММА В ВАЛЮТЕ — ТОЛЬКО ДЛЯ СПРАВКИ (23.09.2026, просьба владельца). У
    # части площадок (CHOIS, TikTok, Believe, Spotify, YouTube, Аманат) платёж
    # приходит в валюте, а на счёт падает уже в рублях; сверять строку с
    # письмом площадки удобнее по валютной сумме. В расчётах НЕ участвует.
    #
    # ТЕКСТ, А НЕ ЧИСЛО, и валюта прямо в нём: «8 247,81 доллар» (уточнение
    # владельца 23.09.2026). Разбирать это на число и код валюты незачем —
    # складывать, делить и сравнивать поле не с чем, а вставлять его человек
    # будет ровно в том виде, в каком оно написано в письме площадки.
    currency_amount: Mapped[str | None] = mapped_column(String(64))
    # КУРС БОЛЬШЕ НЕ ИСПОЛЬЗУЕТСЯ (23.09.2026): все суммы приходят сразу в
    # рублях, и в расчёте суммы завода он не участвует. Колонка оставлена с
    # уже занесёнными значениями — удалять данные ради чистоты схемы
    # несоразмерно; понадобится — уберём отдельной миграцией.
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    # НДС — СТАВКА В ПРОЦЕНТАХ (22 — это 22%, уточнение владельца 23.09.2026).
    # Не сумма и не коэффициент: коэффициент («1.22») человек не набирает, он
    # знает ставку. В расчёт идёт как (1 + vat_rate/100) — см. сверку суммы
    # завода в routers_payments. Складывать в итогах нечего: это ставка.
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    # Сколько должно завестись и сколько завелось на самом деле. Оба поля
    # хранятся, а не считаются: расхождение между ними и есть то, ради чего
    # эту таблицу ведут.
    transfer_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    # «ЗАВЕДЕНО» — НЕ ГАЛОЧКА, А ВЫБОР: пусто, «да» или «синхра» (уточнение
    # владельца 23.09.2026). В рабочей таблице там три положения дел, и
    # превращать «синхру» в «не заведено» значит терять то, ради чего колонку
    # и ведут. Пусто и значит «ещё не заведено» — отдельного слова для этого
    # не нужно.
    transfer_status: Mapped[str | None] = mapped_column(String(16))
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PartnerTrackAlias(Base):
    """
    ЗАПОМНЕННОЕ СОПОСТАВЛЕНИЕ: «в отчётах этой площадки такой трек — вот этот
    артикул» (просьба владельца 18.09.2026).

    Зачем. У площадки код объекта проставлен не всегда, а подбор по названию
    берёт только однозначное совпадение — «Азимут» в каталоге лежит пятью
    треками, и выбрать может лишь человек. Выбирать одно и то же каждый месяц
    он не должен: отчёты приходят регулярно, и позиции в них повторяются.

    КЛЮЧ — ПЛОЩАДКА + НАЗВАНИЕ + ИСПОЛНИТЕЛЬ, а не одно название: у разных
    артистов бывают одинаковые названия, и общий на всех «Азимут» отправил бы
    деньги не туда. Площадка в ключе потому, что пишут названия все по-своему:
    «ПОШЛАЯ МОЛЛИ» у одной и «Пошлая Молли» у другой — и сопоставление,
    сделанное для одной, для другой может не подойти.

    Ключи хранятся УЖЕ НОРМАЛИЗОВАННЫМИ (регистр, знаки препинания,
    разделители исполнителей), а рядом лежит исходное написание: по нему
    человек узнаёт строку в списке запомненного.

    Хранится АРТИКУЛ, а не ссылка на трек: артикул — наш код и переживает
    перезаливку каталога, а id трека при ней меняется.
    """
    __tablename__ = "partner_track_aliases"
    __table_args__ = (
        UniqueConstraint("partner_id", "title_key", "artist_key", name="uq_alias_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"), index=True
    )
    title_key: Mapped[str] = mapped_column(String(300))
    artist_key: Mapped[str] = mapped_column(String(300))
    # Как это было написано в отчёте — чтобы список запомненного читался.
    title: Mapped[str | None] = mapped_column(String(300))
    artist: Mapped[str | None] = mapped_column(String(300))
    sku: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PartnerReport(Base):
    """
    Загруженный отчёт площадки за квартал: заголовок и итоги.

    ПЕРИОД — ПАРА ДАТ, а не «год и квартал» (правка 18.09.2026). Площадки
    отчитываются по-разному: МТС присылает месяц («за период с 1 июля 2026 по
    31 июля 2026»), кто-то квартал, а бывает и произвольный отрезок. Пара дат
    вмещает всё это, а месяц и квартал в интерфейсе — просто кнопки, которые
    её заполняют. Обратное — хранить квартал и «как-нибудь» приписывать к нему
    месяцы — потребовало бы гадать при первом же нестандартном отчёте.

    Итоги хранятся СНИМКОМ (`total_*`), а не считаются на лету из строк: по
    ним сверяют деньги, и цифра в сверке должна остаться той, какой её
    увидели при загрузке, даже если завтра строки пересчитают.

    `vat_rate` — тоже снимок правила на момент загрузки: ставка меняется
    (20% стала 22%), а уже загруженный отчёт обязан объяснять свои числа.
    """
    __tablename__ = "partner_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id", ondelete="RESTRICT"), index=True
    )
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    file_name: Mapped[str] = mapped_column(String(255))
    sheet: Mapped[str | None] = mapped_column(String(120))
    rows_count: Mapped[int] = mapped_column(Integer, default=0)
    # Строк, у которых артикул не нашёлся в каталоге ИЛИ его нет в отчёте
    # вовсе. Не ошибка загрузки, а работа на потом: по таким строкам роялти не
    # посчитается, и они должны быть видны числом, а не потеряться.
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    # Строк, где сумма не прочиталась или формула дала пустоту. Такие строки
    # грузятся с нулями: терять из-за них весь квартальный отчёт нельзя, но и
    # молчать о них — тоже.
    problem_count: Mapped[int] = mapped_column(Integer, default=0)
    # НЕРАЗНЕСЁННАЯ СУММА, а не только число строк (просьба владельца
    # 18.09.2026): в отчёте важно, СКОЛЬКО ДЕНЕГ пока не на что отнести, —
    # десять строк по рублю и одна на сто тысяч выглядят одинаково, если
    # считать строки.
    unmatched_amount: Mapped[Decimal] = mapped_column(Numeric(16, 4), default=0)
    total_quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    total_author: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_related: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # ВАЛЮТА И КУРС К РУБЛЮ (24.09.2026, отчёты Believe KZ в EUR и AE в USD).
    # Суммы строк уже пересчитаны в рубли при разборе; здесь — снимок того,
    # в какой валюте был файл и по какому курсу его перевели, как у НДС:
    # отчёт обязан объяснять свои числа. Курс хранится как вписан — «76,75»
    # (умножали) или «0,012216938» (делили), см. currency_factor.
    currency: Mapped[str | None] = mapped_column(String(32))
    currency_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    # ИТОГ В ИСХОДНОЙ ВАЛЮТЕ — с ним сверяется «сумма в валюте» поступления
    # (просьба владельца 24.09.2026): курс, выведенный из того же платежа,
    # сделал бы сверку замкнутой, и неполный отчёт «сходился» бы всегда.
    currency_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # К КАКОМУ ПОСТУПЛЕНИЮ ОТНОСИТСЯ отчёт (19.09.2026). Связь со стороны
    # отчёта, а не платежа: одним платежом закрывают несколько отчётов, и
    # обратная ссылка потребовала бы третьей таблицы ради того же самого.
    #
    # SET NULL при удалении платежа: отчёт — документ площадки и живёт сам по
    # себе, а строку поступления могут завести заново.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partner_payments.id", ondelete="SET NULL"), index=True
    )
    # Параметры отчёта — СНИМКОМ, как и ставка НДС: в правиле они могут
    # смениться, а загруженный отчёт обязан объяснять себя сам. Дальше они
    # уйдут в отчёт правообладателю.
    content_type: Mapped[str | None] = mapped_column(String(120))
    usage_type: Mapped[str | None] = mapped_column(String(120))
    usage_kind: Mapped[str | None] = mapped_column(String(120))
    territory: Mapped[str | None] = mapped_column(String(120))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    partner: Mapped["Partner"] = relationship()
    rows: Mapped[list["PartnerReportRow"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class PartnerReportRow(Base):
    """
    Строка отчёта в ЕДИНОМ ФОРМАТЕ: артикул, количество, сумма авторских,
    сумма смежных (просьба владельца: «свести все отчёты к одному виду»).

    Исходная строка файла здесь НЕ хранится: она весит больше самих чисел, а
    вернуться к ней всё равно можно — файл лежит у владельца, а имя файла и
    номер строки записаны. `title` оставлен ровно для одного: понять, что за
    трек, когда артикул не опознан.

    `track_id` проставляется при загрузке по артикулу. Не нашлось — строка
    остаётся без ссылки и попадает в счётчик `unmatched_count`: деньги по ней
    пришли, а кому их делить, неизвестно, и молчать об этом нельзя.
    """
    __tablename__ = "partner_report_rows"
    # Строки читают ПО ПОРЯДКУ внутри отчёта (окно отчёта подгружает их
    # кусками при прокрутке) — составной индекс отдаёт их уже отсортированными.
    # Отдельного индекса по report_id нет: составной начинается с него.
    __table_args__ = (
        Index("ix_partner_report_rows_report_row", "report_id", "row_num"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partner_reports.id", ondelete="CASCADE")
    )
    row_num: Mapped[int] = mapped_column(Integer)
    # Артикул НЕОБЯЗАТЕЛЕН: у площадки он бывает не проставлен (в отчёте МТС
    # таких строк два десятка). Деньги по ним пришли, и выкидывать их нельзя —
    # они лежат без ссылки на трек и попадают в счётчик неразнесённых.
    sku: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    # ЧЕТЫРЕ ПАРАМЕТРА — И У СТРОКИ ТОЖЕ (24.09.2026). У МТС и «101 и К» они
    # одни на весь файл и лежат в шапке отчёта; у Believe в одном отчёте 308
    # разных сочетаний, а территория идёт по странам, — и там их место здесь.
    # Пусто значит «у этой площадки параметр общий», и читать его надо из
    # отчёта: дублировать снимок в каждую из полумиллиона строк незачем.
    content_type: Mapped[str | None] = mapped_column(String(120))
    usage_type: Mapped[str | None] = mapped_column(String(120))
    usage_kind: Mapped[str | None] = mapped_column(String(120))
    territory: Mapped[str | None] = mapped_column(String(120))
    # Исполнитель нужен не для расчёта, а для ПОДБОРА артикула по названию,
    # когда площадка код не проставила, и чтобы человек в списке «не
    # разнесено» понимал, о каком треке речь.
    artist: Mapped[str | None] = mapped_column(String(300))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    # ЧЕТЫРЕ ЗНАКА, а не копейки: площадки считают дробно (у МТС строка
    # «147.0456»), и округление каждой строки уводит итог отчёта от их же
    # «Итого» — на 668 строках набежало 84 копейки. Округляем один раз, в
    # итогах отчёта.
    # Восемь знаков, а не копейки: округляем один раз, на итогах отчёта (см.
    # PRECISION в partner_reports.py).
    amount_author: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    amount_related: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    track_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="SET NULL"), index=True
    )

    report: Mapped["PartnerReport"] = relationship(back_populates="rows")


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
