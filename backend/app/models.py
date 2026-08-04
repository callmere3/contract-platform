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

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, false, func
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

    country: Mapped[str | None] = mapped_column(String(16))          # 'РУ' | 'KZ'
    type: Mapped[str | None] = mapped_column(String(16))             # 'ФЛ' | 'СГ' | 'ИП' | 'ООО' | 'ТОО'
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


class CardSuggestion(Base):
    """
    Предложение дозаполнить/исправить карточку контрагента — вкладка
    "Уведомления" (только admin). Заводится автоматически при генерации
    документа: если менеджер вписал в форму значение поля, которое связано
    с карточкой (maps_to='contragent.*' или дата договора), и оно отличается
    от того, что сейчас в карточке — сюда падает запись, а админ решает
    галочкой применить её к карточке или крестиком отклонить.

    Смысл: у большинства карточек часть данных пуста (в первую очередь
    reg_number — он в каждом документе), менеджеры дозаполняют их прямо в
    форме генерации. Эти значения уже сохраняются в payload истории
    генерации; здесь мы их поднимаем на поверхность и даём в один клик
    перенести в карточку — actionable-двойник красной подсветки неполных
    карточек (_contragent_is_complete).

    field — какая колонка карточки: 'reg_number' | 'royalty_percent' |
    'name' | 'contract_number' | 'contract_date'. Никнейм НЕ предлагается
    (у контрагента их несколько, это не "недостающее поле"). title в
    список не входит намеренно — он и номер меняются только импортом
    (см. update_contragent), пересчёта нет.

    value — значение как его вписал менеджер, в каноничном для колонки
    виде (reg_number/name/contract_number — строка; royalty_percent — целое
    строкой; contract_date — ISO 'ГГГГ-ММ-ДД'). Применение пишет ровно эту
    колонку напрямую, МИНУЯ пересчёт title/номера.

    status — 'pending' | 'applied' | 'dismissed'. Как показывать pending
    (кнопки применить/отклонить или ⚠ "внимание, проверьте документ")
    решается НА МОМЕНТ ПОКАЗА против ТЕКУЩЕГО состояния карточки, а не
    замораживается здесь: карточку могли дозаполнить другим путём между
    генерацией и разбором, и разошедшееся значение могло уже сойтись
    (см. routers_notifications._classify).

    dismissed по конкретному (contragent, field, value) больше не всплывает;
    но если менеджер впишет ДРУГОЕ значение того же поля — заведётся новая
    запись (дедуп идёт по тройке contragent+field+value, см. capture).

    contragent_id — CASCADE: предложение живёт только пока жива карточка,
    к которой относится. suggested_by/resolved_by — SET NULL как и везде
    (пользователя могут деактивировать/удалить, запись остаётся читаемой
    по снимку username). source_generation_id — SET NULL: историю генерации
    могут почистить, предложение от этого не должно пропадать.
    """
    __tablename__ = "card_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    contragent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contragents.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(255))

    suggested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    suggested_by_username: Mapped[str | None] = mapped_column(String(255))
    # снимок логина того, кто вписал значение при генерации — переживает
    # деактивацию/удаление пользователя (как в AuditLog/GeneratedDocument)

    source_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="SET NULL")
    )

    status: Mapped[str] = mapped_column(String(16), default="pending")

    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
