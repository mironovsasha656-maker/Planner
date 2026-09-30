"""Russian UI labels for enum-like codes stored in the database."""

MEMBER_STATUS = {
    "active": "Активен",
    "suspended": "Приостановлен",
    "unpaid": "Не оплачен взнос",
}
GENDER = {"M": "Мужской", "F": "Женский"}
GENDER_SHORT = {"M": "М", "F": "Ж"}
AGE_CATEGORY = {"junior": "Юниор", "adult": "Взрослый", "senior": "Сеньор"}

TEE_COLORS = {"white": "Белые", "yellow": "Жёлтые", "blue": "Синие", "red": "Красные"}

TOURNAMENT_FORMAT = {
    "stroke_gross": "Строкплей (гросс)",
    "stroke_net": "Строкплей (нетто)",
    "stableford": "Стейблфорд",
}
TOURNAMENT_STATUS = {
    "draft": "Черновик",
    "registration": "Регистрация открыта",
    "in_progress": "Идёт",
    "finished": "Завершён",
    "cancelled": "Отменён",
}
# Scoring categories a tournament may use.
SCORING_CATEGORY = {
    "men": "Мужчины",
    "women": "Женщины",
    "juniors": "Юниоры",
    "seniors": "Сеньоры",
}

REGISTRATION_STATUS = {
    "applied": "Заявка",
    "confirmed": "Подтверждена",
    "waitlist": "Лист ожидания",
    "rejected": "Отклонена",
}

PAYMENT_TYPE = {
    "membership": "Членский взнос",
    "tournament": "Турнирный взнос",
    "other": "Прочее",
}
PAYMENT_METHOD = {"card": "Карта", "invoice": "Счёт", "cash": "Наличные"}
PAYMENT_STATUS = {"pending": "Ожидает оплаты", "paid": "Оплачен", "overdue": "Просрочен"}

OFFICIAL_ROLE = {
    "coach": "Тренер",
    "referee": "Судья",
    "rules_committee": "Комитет по правилам",
}

MESSAGE_STATUS = {"sent": "Отправлено (имитация)"}

SEGMENTS = {
    "all": "Все игроки",
    "debtors": "Должники по членскому взносу",
    "juniors": "Юниоры",
    "seniors": "Сеньоры",
    "club": "Игроки клуба",
    "tournament": "Участники турнира",
}

ROLES = {
    "admin": "Администратор",
    "secretary": "Секретарь турниров",
    "accountant": "Бухгалтер",
}

AUDIT_ACTIONS = {
    "create": "Создание",
    "update": "Изменение",
    "status": "Смена статуса",
    "payment": "Оплата",
    "results": "Ввод результатов",
    "handicap": "Пересчёт гандикапа",
    "mailing": "Рассылка",
    "export": "Экспорт",
    "role": "Смена роли",
}

ENTITY_TYPES = {
    "member": "Игрок",
    "club": "Клуб",
    "tournament": "Турнир",
    "registration": "Заявка",
    "payment": "Платёж",
    "official": "Судья/тренер",
    "message": "Рассылка",
    "round": "Раунд",
    "session": "Сеанс",
}

MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
