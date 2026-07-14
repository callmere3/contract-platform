"""
Канонические роли пользователей (этап 6, брейншторм ролей).

  ADMIN     — полный доступ: пользователи и роли, шаблоны, контрагенты
              (включая удаление), импорт/экспорт, audit_log.
  DIRECTOR  — как MANAGER, плюс экспорт контрагентов в Excel и просмотр
              audit_log. Импорт — НЕТ (загрузку данных внутрь делает
              только Admin, см. брейншторм).
  MANAGER   — рабочая роль: генерация документов, создание/редактирование
              контрагентов. Без удаления, без импорта/экспорта, без
              шаблонов, без audit_log.

ROLES — единственный источник правды, как COUNTRIES/CONTRAGENT_TYPES в
app/tags.py: любая новая роль добавляется здесь и сразу используется во
всех проверках require_role(...) по всему коду.
"""
ADMIN = "admin"
DIRECTOR = "director"
MANAGER = "manager"

ROLES = (ADMIN, DIRECTOR, MANAGER)

# Общие сокращения для Depends(require_role(...)) в роутерах — чтобы не
# перечислять одни и те же тройки/пары ролей в каждом файле по-разному.
ANY_ROLE = ROLES                    # любой залогиненный пользователь
CAN_EXPORT = (ADMIN, DIRECTOR)      # экспорт контрагентов, просмотр audit_log
CAN_IMPORT = (ADMIN,)               # импорт контрагентов — только Admin
CAN_MANAGE_USERS = (ADMIN,)
CAN_MANAGE_TEMPLATES = (ADMIN,)
CAN_DELETE_CONTRAGENTS = (ADMIN,)
