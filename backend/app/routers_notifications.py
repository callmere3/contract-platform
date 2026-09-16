"""
Уведомления: админ пишет команде, остальные читают.

  GET    /notifications             — мои уведомления (любая роль)
  GET    /notifications/count       — сколько непрочитанных, для значка в шапке
  POST   /notifications/read        — отметить мои прочитанными
  DELETE /notifications/mine/{id}   — убрать уведомление У СЕБЯ (любая роль)
  POST   /notifications             — написать (только admin)
  GET    /notifications/sent        — что я отправил, с отметками прочтения (admin)
  DELETE /notifications/{id}        — удалить отправленное у всех (admin)

ЧТО БЫЛО ЗДЕСЬ РАНЬШЕ. До 16.09.2026 вкладка показывала предложения
дозаполнить карточку контрагента значениями из формы генерации. Механизм
признан бесполезным и убран целиком вместе с app/suggestions.py и захватом
при генерации. Таблица card_suggestions осталась в базе нетронутой —
удалять историю ради смены экрана несоразмерно, а вернуть логику можно из
git.

ЗАГОЛОВОК обязателен у новых уведомлений и NULL у отправленных до
16.09.2026: в панели они лежат списком, и по первым словам текста не всегда
понятно, о чём объявление. У старых заголовка нет и взяться ему неоткуда —
фронт показывает их как раньше, одним текстом.

ДВА РАЗНЫХ УДАЛЕНИЯ, не перепутать. «У себя» (DELETE /mine/{id}) прячет
уведомление у одного человека и никого больше не касается. «Удалить»
админом (DELETE /{id}) сносит объявление целиком, у всех сразу.

ПОРЯДОК МАРШРУТОВ ВАЖЕН: /count, /read и /sent зарегистрированы РАНЬШЕ
/{announcement_id} — иначе FastAPI попробует разобрать слово «sent» как
uuid и вернёт 422 вместо обработчика (та же грабля, что с /import и
/export в контрагентах).

КТО ЧТО МОЖЕТ. Читать и убирать у себя — любой залогиненный, и только СВОИ
строки: чужие уведомления не отдаются ни по какому параметру, потому что
параметра нет вовсе, а скрытие ищет строку по паре (объявление, я). Писать
и удалять у всех — только admin (CAN_SEND_NOTIFICATIONS).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Announcement, AnnouncementRecipient, User
from app.roles import CAN_SEND_NOTIFICATIONS

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])

# Предел длины текста. 2000 символов — это примерно страница: объявление на
# десять человек длиннее и не бывает, а ограничение защищает вкладку от
# случайной вставки всего договора.
MAX_TEXT = 2000

# Заголовок. 120 символов — строка, которая целиком видна в панели: длиннее
# он перестаёт быть заголовком и становится вторым текстом.
MAX_TITLE = 120


class NewAnnouncement(BaseModel):
    # Обязателен, хотя в БД колонка nullable: NULL там только у уведомлений,
    # отправленных до появления заголовка, и заполнить их задним числом нечем.
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    # to_all=True — всем действующим сотрудникам, кроме самого автора.
    # Иначе адресаты берутся из user_ids (тоже без автора и без отключённых).
    to_all: bool = True
    user_ids: list[uuid.UUID] = []


def _mine(db: Session, user: User):
    return (
        db.query(AnnouncementRecipient, Announcement)
        .join(Announcement, Announcement.id == AnnouncementRecipient.announcement_id)
        .filter(
            AnnouncementRecipient.user_id == user.id,
            # Убранные получателем не показываем — но строка жива, и админ
            # по-прежнему видит его в списке адресатов.
            AnnouncementRecipient.hidden_at.is_(None),
        )
        .order_by(Announcement.created_at.desc())
    )


@notifications_router.get("")
def list_my_notifications(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Мои уведомления, новые сверху. Только свои — чужие сюда не попадают."""
    return [
        {
            "id": str(note.id),
            "title": note.title,
            "text": note.text,
            "author": note.author_username,
            "created_at": note.created_at.isoformat(),
            "read_at": row.read_at.isoformat() if row.read_at else None,
        }
        for row, note in _mine(db, current_user).all()
    ]


@notifications_router.get("/count")
def notifications_count(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Счётчик для значка в шапке. Опрашивается всеми раз в минуту."""
    unread = (
        db.query(AnnouncementRecipient)
        .filter(
            AnnouncementRecipient.user_id == current_user.id,
            AnnouncementRecipient.read_at.is_(None),
            AnnouncementRecipient.hidden_at.is_(None),
        )
        .count()
    )
    return {"unread": unread}


@notifications_router.post("/read")
def mark_read(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Отметить всё моё прочитанным — вызывается при открытии панели.

    Панель и есть прочтение: отмечать каждое уведомление отдельной кнопкой
    для десятка объявлений — лишний ритуал. Возвращаем, сколько отметили,
    чтобы фронт знал, менять ли значок.
    """
    now = datetime.now(timezone.utc)
    marked = (
        db.query(AnnouncementRecipient)
        .filter(
            AnnouncementRecipient.user_id == current_user.id,
            AnnouncementRecipient.read_at.is_(None),
            AnnouncementRecipient.hidden_at.is_(None),
        )
        .update({AnnouncementRecipient.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"marked": marked}


@notifications_router.delete("/mine/{announcement_id}")
def hide_my_notification(
    announcement_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Убрать уведомление У СЕБЯ. Чужих не касается и объявление не удаляет —
    для этого есть админский DELETE /{id}.

    Строка получателя остаётся, проставляется hidden_at: она же служит
    отметкой «кому отправляли» и «прочитал ли», и админское «прочитали 3 из
    7» не должно меняться от того, что кто-то прибрал у себя в панели.

    Ищем строку по паре (объявление, я) — поэтому подставить чужой id
    нечем: уведомление, адресованное другому, просто не найдётся.
    """
    row = (
        db.query(AnnouncementRecipient)
        .filter(
            AnnouncementRecipient.announcement_id == announcement_id,
            AnnouncementRecipient.user_id == current_user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")

    if row.hidden_at is None:
        row.hidden_at = datetime.now(timezone.utc)
        db.commit()
    return {"hidden": str(announcement_id)}


@notifications_router.get("/sent", dependencies=[Depends(require_role(*CAN_SEND_NOTIFICATIONS))])
def list_sent(db: Session = Depends(get_session)) -> list[dict]:
    """
    Отправленные уведомления с отметками прочтения.

    Отдаём полный список получателей, а не только счётчик: во вкладке он
    раскрывается по нажатию, и второй запрос ради десяти имён не нужен.
    """
    notes = db.query(Announcement).order_by(Announcement.created_at.desc()).all()
    users = {u.id: u for u in db.query(User).all()}

    out = []
    for note in notes:
        people = []
        for row in note.recipients:
            person = users.get(row.user_id)
            people.append(
                {
                    "id": str(row.user_id),
                    "username": person.username if person else "—",
                    "full_name": person.full_name if person else None,
                    "read_at": row.read_at.isoformat() if row.read_at else None,
                }
            )
        people.sort(key=lambda p: (p["read_at"] is None, (p["full_name"] or p["username"]).lower()))
        out.append(
            {
                "id": str(note.id),
                "title": note.title,
                "text": note.text,
                "author": note.author_username,
                "created_at": note.created_at.isoformat(),
                "read_count": sum(1 for p in people if p["read_at"]),
                "total": len(people),
                "recipients": people,
            }
        )
    return out


@notifications_router.post("", dependencies=[Depends(require_role(*CAN_SEND_NOTIFICATIONS))])
def create_announcement(
    body: NewAnnouncement,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Написать уведомление всем или выбранным.

    Адресаты раскладываются строками ПРЯМО СЕЙЧАС и больше не меняются: это
    и есть смысл «отправил» — список получателей не должен переписываться
    задним числом, если кого-то потом отключили или завели нового.

    Отключённые в адресаты не попадают (читать всё равно некому), сам автор
    — тоже: писать себе незачем. Если после этих отсечений не осталось
    никого — 400, иначе объявление молча уходило бы в пустоту.
    """
    title = body.title.strip()
    text = body.text.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Заголовок уведомления пуст")
    if not text:
        raise HTTPException(status_code=400, detail="Текст уведомления пуст")

    query = db.query(User).filter(User.is_active.is_(True), User.id != current_user.id)
    if not body.to_all:
        if not body.user_ids:
            raise HTTPException(status_code=400, detail="Выберите, кому отправить")
        query = query.filter(User.id.in_(body.user_ids))

    recipients = query.all()
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="Некому отправить: среди выбранных нет действующих сотрудников",
        )

    note = Announcement(
        author_id=current_user.id,
        author_username=current_user.full_name or current_user.username,
        title=title,
        text=text,
    )
    db.add(note)
    db.flush()   # нужен note.id до вставки адресатов

    for person in recipients:
        db.add(AnnouncementRecipient(announcement_id=note.id, user_id=person.id))
    db.commit()

    return {
        "id": str(note.id),
        "created_at": note.created_at.isoformat(),
        "total": len(recipients),
    }


@notifications_router.delete(
    "/{announcement_id}", dependencies=[Depends(require_role(*CAN_SEND_NOTIFICATIONS))]
)
def delete_announcement(
    announcement_id: uuid.UUID, db: Session = Depends(get_session)
) -> dict:
    """
    Удалить отправленное У ВСЕХ — для опечаток и отменённых новостей.
    Не путать с DELETE /mine/{id}, которым получатель прячет уведомление
    только у себя.

    Адресные строки уходят каскадом (см. модель), поэтому уведомление
    исчезает и из чужих панелей, и из счётчиков. Это осознанно: «отозвать»
    для внутреннего объявления полезнее, чем хранить вечно.
    """
    note = db.get(Announcement, announcement_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    db.delete(note)
    db.commit()
    return {"deleted": str(announcement_id)}
