"""Demo data generator. All names, clubs and courses are fictional.

Dates are generated relative to the day the database is created so the demo
always shows an "in progress" tournament, open registrations etc.
Randomness is seeded (config.SEED), so the data is reproducible for a given date.

Usage: python seed.py        (recreates golf_crm.db)
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import Base, SessionLocal, engine
from app.models import (
    AuditLog,
    Club,
    Course,
    CourseTee,
    Member,
    Notification,
    Message,
    Official,
    Payment,
    Registration,
    Result,
    Round,
    Tournament,
    User,
    age_category,
)
from app.services import handicap, leaderboard, payments, segmentation
from app.services import tasks as task_service
from app.services.users import DIRECTOR_ID, ROLE_DEFAULT_USER, ensure_users
from app.services.registration import default_tee
from app import timeutil as msk

CLUBS = [
    # name, district, city, address, website slug, weight, courses [(name, holes, par)]
    ("Гольф-клуб «Ясная Поляна»", "г. о. Истра", "Истра", "д. Лужки, ул. Полевая, 12", "yasnaya-polyana",
     1.6, [("Чемпионское поле", 18, 72), ("Академия", 9, 70)]),
    ("Гольф-клуб «Берёзовая Роща»", "Дмитровский г. о.", "Дмитров", "пос. Берёзки, Лесная ул., 3", "berezovaya-roscha",
     1.2, [("Берёзовое поле", 18, 72)]),
    ("Гольф-клуб «Озёрный Край»", "г. о. Солнечногорск", "Солнечногорск", "д. Заречье, Озёрная ул., 1", "ozerny-krai",
     1.5, [("Озёрное поле", 18, 71), ("Северное поле", 18, 70)]),
    ("Гольф-клуб «Старая Мельница»", "Наро-Фоминский г. о.", "Наро-Фоминск", "с. Мельниково, ул. Мельничная, 8", "staraya-melnitsa",
     1.0, [("Мельничное поле", 18, 72)]),
    ("Гольф-клуб «Княжьи Луга»", "Одинцовский г. о.", "Одинцово", "д. Княжино, Луговая ул., 20", "knyazhi-luga",
     1.3, [("Луговое поле", 18, 73)]),
    ("Гольф-клуб «Серебряные Ключи»", "Рузский г. о.", "Руза", "д. Ключи, Родниковая ул., 5", "serebryanye-klyuchi",
     0.9, [("Ключевое поле", 18, 72)]),
    ("Гольф-клуб «Тихая Заводь»", "г. о. Красногорск", "Красногорск", "пос. Заводь, Береговая ул., 2", "tikhaya-zavod",
     0.5, [("Поле «Заводь»", 9, 70)]),
]

CITIES = ["Москва"] * 8 + [
    "Истра", "Красногорск", "Одинцово", "Химки", "Дмитров", "Солнечногорск", "Наро-Фоминск",
    "Руза", "Звенигород", "Мытищи", "Королёв", "Подольск", "Балашиха", "Долгопрудный",
]

MEMBER_NOTES = [
    "Предпочитает утренние стартовые времена.",
    "Выступал за сборную области в прошлом сезоне.",
    "Интересуется юниорской программой для ребёнка.",
    "Левша: при прокате инвентаря нужен левосторонний комплект.",
    "Просил присылать уведомления только по электронной почте.",
    "Готов помогать волонтёром на областных турнирах.",
    "Занимается в академии клуба с начала сезона.",
    "Запрашивал справку об участии в турнирах для работодателя.",
]
SUSPENDED_NOTES = [
    "Членство приостановлено по заявлению игрока (длительная командировка).",
    "Членство приостановлено решением дисциплинарного комитета до конца сезона.",
    "Приостановлено по медицинским показаниям, игрок планирует вернуться весной.",
]

# Common modern first names and patronymics (Faker's ru_RU lists include many archaic ones).
MALE_FIRST = ("Александр Алексей Андрей Антон Артём Борис Вадим Валерий Виктор Виталий Владимир Владислав "
              "Глеб Григорий Даниил Денис Дмитрий Евгений Егор Иван Игорь Илья Кирилл Константин Максим "
              "Матвей Михаил Никита Николай Олег Павел Роман Руслан Сергей Степан Тимофей Фёдор Юрий Ярослав").split()
FEMALE_FIRST = ("Алина Алла Анастасия Анна Валентина Вера Виктория Галина Дарья Екатерина Елена Елизавета "
                "Ирина Карина Ксения Лариса Любовь Людмила Маргарита Марина Мария Надежда Наталья Нина Ольга "
                "Полина Светлана София Татьяна Юлия").split()
PATRONYMIC_ROOTS = ("Александр Алексе Андре Анатоль Борис Валерь Васил Викто Владимир Геннадь Дмитри Евгень "
                    "Иван Игор Константин Михайл Никола Олег Павл Серге Юрь").split()
_PATR_M = {"Алексе": "Алексеевич", "Андре": "Андреевич", "Анатоль": "Анатольевич", "Валерь": "Валерьевич",
           "Васил": "Васильевич", "Викто": "Викторович", "Геннадь": "Геннадьевич", "Дмитри": "Дмитриевич",
           "Евгень": "Евгеньевич", "Игор": "Игоревич", "Михайл": "Михайлович", "Никола": "Николаевич",
           "Павл": "Павлович", "Серге": "Сергеевич", "Юрь": "Юрьевич"}


def patronymic(root: str, male: bool) -> str:
    m = _PATR_M.get(root, root + "ович")
    return m if male else m[:-2] + "на"


TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
     "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


def translit(text: str) -> str:
    return "".join(TRANSLIT.get(ch, ch) for ch in text.lower())


class Seeder:
    def __init__(self, session: Session, today: date):
        self.s = session
        self.today = today
        self.rng = random.Random(config.SEED)
        Faker.seed(config.SEED)
        self.fake = Faker("ru_RU")
        self.ability: dict[int, float] = {}
        self.history: dict[int, list[tuple[date, float]]] = {}

    # ------------------------------------------------------------------ helpers
    def phone(self) -> str:
        r = self.rng
        return f"+7 ({r.choice(['903', '905', '909', '915', '916', '917', '925', '926', '977', '985'])}) " \
               f"{r.randint(100, 999)}-{r.randint(10, 99)}-{r.randint(10, 99)}"

    def person(self, male: bool) -> tuple[str, str, str]:
        r = self.rng
        middle = patronymic(r.choice(PATRONYMIC_ROOTS), male)
        if male:
            return r.choice(MALE_FIRST), self.fake.last_name_male(), middle
        return r.choice(FEMALE_FIRST), self.fake.last_name_female(), middle

    def full_name(self, male: bool) -> str:
        first, last, middle = self.person(male)
        return f"{last} {first} {middle}"

    def in_season(self, start: date, end: date) -> date:
        """Random date between start and end, preferring the golf season (Apr-Oct)."""
        span = (end - start).days
        if span <= 0:
            return start
        for _ in range(40):
            d = start + timedelta(days=self.rng.randint(0, span))
            if 4 <= d.month <= 10:
                return d
        return start + timedelta(days=self.rng.randint(0, span))

    def simulate_score(self, ability: float, tee: CourseTee, pressure: float = 0.0) -> int:
        expected = tee.course_rating + ability * tee.slope_rating / 113
        score = round(expected + self.rng.gauss(3.0 + pressure, 3.2))
        return max(tee.par - 5, min(score, tee.par + 62))

    def index_at(self, member: Member, on: date) -> float:
        prior = [d for played, d in sorted(self.history[member.id]) if played < on]
        value = handicap.handicap_index(prior)
        return value if value is not None else round(self.ability[member.id], 1)

    # ------------------------------------------------------------------ clubs
    def clubs(self) -> None:
        r = self.rng
        self.club_list: list[Club] = []
        self.club_weights: list[float] = []
        self.club_city: dict[int, str] = {}
        for name, district, city, address, slug, weight, courses in CLUBS:
            club = Club(
                name=name,
                district=district,
                address=f"Московская обл., {district}, {address}",
                contact_person=self.full_name(r.random() < 0.7),
                phone=self.phone(),
                website=f"https://{slug}.example",
                holes=sum(c[1] for c in courses),
                description="Вымышленный клуб для демонстрации системы.",
            )
            for cname, holes, par in courses:
                course = Course(name=cname, holes=holes)
                yellow_cr = round(par - 0.8 + r.uniform(0, 1.6), 1)
                yellow_slope = r.randint(118, 131)
                red_cr = round(par + 0.2 + r.uniform(0, 1.6), 1)
                red_slope = r.randint(120, 132)
                if holes == 9:  # 2 x 9 holes, 18-hole equivalent ratings
                    yellow_cr, yellow_slope = round(par - 1.6 + r.uniform(0, 0.6), 1), r.randint(106, 114)
                    red_cr, red_slope = round(par - 0.6 + r.uniform(0, 0.6), 1), r.randint(108, 116)
                tees = {
                    "white": (yellow_cr + round(r.uniform(1.4, 2.2), 1), yellow_slope + r.randint(4, 8)),
                    "yellow": (yellow_cr, yellow_slope),
                    "blue": (red_cr + round(r.uniform(1.2, 1.8), 1), red_slope + r.randint(3, 6)),
                    "red": (red_cr, red_slope),
                }
                for color, (cr, slope) in tees.items():
                    course.tees.append(
                        CourseTee(color=color, course_rating=round(min(max(cr, 68.0), 75.0), 1),
                                  slope_rating=min(max(slope, 105), 140), par=par)
                    )
                club.courses.append(course)
            self.s.add(club)
            self.club_list.append(club)
            self.club_weights.append(weight)
        self.s.flush()
        for club, (_, _, city, *_rest) in zip(self.club_list, CLUBS):
            self.club_city[club.id] = city

    # ------------------------------------------------------------------ members
    def members(self, count: int = 204) -> None:
        r, today = self.rng, self.today
        self.member_list: list[Member] = []
        for n in range(count):
            gender = "M" if r.random() < 0.72 else "F"
            roll = r.random()
            if roll < 0.10:
                age = r.randint(10, 17)
            elif roll < 0.31:
                age = r.randint(50, 76)
            else:
                age = r.randint(19, 49)
            birth = today - timedelta(days=age * 365 + r.randint(10, 350))
            first, last, middle = self.person(gender == "M")

            # Join date: steady growth, ~25% joined within the last 12 months.
            earliest = max(date(2016, 3, 1), birth + timedelta(days=8 * 365))
            if r.random() < 0.25 and earliest < today - timedelta(days=365):
                if r.random() < 0.7:
                    join = self.in_season(today - timedelta(days=364), today - timedelta(days=3))
                else:  # some join off-season (indoor academies, winter sign-ups)
                    join = today - timedelta(days=r.randint(3, 364))
            else:
                join = self.in_season(earliest, max(earliest, today - timedelta(days=366)))

            club = r.choices(self.club_list, weights=self.club_weights)[0]
            city = self.club_city[club.id] if r.random() < 0.35 else r.choice(CITIES)
            email = f"{translit(first)}.{translit(last)}{r.randint(1, 99)}@example.com"
            m = Member(
                last_name=last, first_name=first, middle_name=middle, birth_date=birth, gender=gender,
                phone=self.phone(), email=email if r.random() > 0.03 else "", city=city, club=club,
                status="active", join_date=join, license_number=f"TMP-{n}", pd_consent=r.random() > 0.06,
                notes=r.choice(MEMBER_NOTES) if r.random() < 0.18 else "",
            )
            self.s.add(m)
            self.member_list.append(m)
        self.s.flush()
        # Licenses are numbered by seniority in the federation.
        for i, m in enumerate(sorted(self.member_list, key=lambda x: (x.join_date, x.id)), start=1):
            m.license_number = f"MO-{today.year}-{i:04d}"
        for m in self.member_list:
            self.history[m.id] = []

    def assign_abilities(self) -> None:
        # Playing ability: the "true" handicap level rounds are simulated from.
        r = random.Random(config.SEED + 1)
        for m in self.member_list:
            a = r.random()
            if a < 0.035:
                ability = r.uniform(0.8, 4.8)
            elif a < 0.14:
                ability = r.uniform(5, 15)
            elif a < 0.86:
                ability = r.uniform(15, 36)
            else:
                ability = r.uniform(36, 46)
            if m.gender == "F":
                ability = min(ability + r.uniform(0, 4), 48)
            if age_category(m.birth_date, self.today) == "senior":
                ability = min(ability + r.uniform(0, 3), 48)
            self.ability[m.id] = ability

    def home_tee(self, m: Member, course: Course) -> CourseTee:
        color = default_tee(m)
        if self.ability[m.id] < 8:
            color = "white" if m.gender == "M" else "blue"
        return course.tee(color)

    def casual_rounds(self) -> None:
        r = self.rng
        all_courses = [c for club in self.club_list for c in club.courses]
        for m in self.member_list:
            home = m.club.courses[0]
            n = r.randint(5, 18)
            start = max(m.join_date, self.today - timedelta(days=720))
            for _ in range(n):
                course = home if r.random() < 0.7 else r.choice(all_courses)
                tee = self.home_tee(m, course)
                played = self.in_season(start, self.today - timedelta(days=2))
                self.add_round(m, tee, played, self.simulate_score(self.ability[m.id], tee))

    def add_round(self, m: Member, tee: CourseTee, played: date, score: int, result: Result | None = None,
                  round_no: int | None = None) -> None:
        diff = handicap.score_differential(score, tee.course_rating, tee.slope_rating)
        m.rounds.append(Round(tee=tee, played_on=played, adjusted_gross=score, differential=diff,
                              result_id=result.id if result else None, round_no=round_no))
        self.history[m.id].append((played, diff))

    # ------------------------------------------------------------------ tournaments
    def tournaments(self) -> None:
        d = self.today
        courses = {c.name: c for club in self.club_list for c in club.courses}
        spec = [
            # name, start offset, days, rounds, format, categories, fee, limit, status, course, participants, filter
            ("Открытие сезона", -150, 1, 1, "stroke_net", "men,women", 3000, 72, "finished", "Чемпионское поле", 48, None),
            ("Кубок «Берёзовой Рощи»", -122, 1, 1, "stableford", "men,women,seniors", 3500, 60, "finished", "Берёзовое поле", 42, None),
            ("Первенство Московской области среди юниоров", -101, 2, 2, "stroke_gross", "men,women", 1500, 40, "finished", "Озёрное поле", 18, "junior"),
            ("Летний Кубок «Старой Мельницы»", -80, 1, 1, "stableford", "men,women", 3500, 72, "finished", "Мельничное поле", 55, None),
            ("Чемпионат Московской области", -61, 3, 3, "stroke_gross", "men,women", 6000, 60, "finished", "Луговое поле", 44, "low"),
            ("Кубок Федерации среди сеньоров", -44, 2, 2, "stroke_net", "men,women", 3000, 48, "finished", "Северное поле", 30, "senior"),
            ("Кубок «Тихой Заводи»", -30, 1, 1, "stableford", "men,women", 2000, 36, "cancelled", "Поле «Заводь»", 0, None),
            ("Кубок «Княжьих Лугов»", -20, 1, 1, "stroke_net", "men,women,juniors,seniors", 4000, 72, "finished", "Луговое поле", 50, None),
            ("Осенний Кубок Федерации", -1, 3, 3, "stroke_net", "men,women,seniors", 5000, 54, "in_progress", "Чемпионское поле", 40, None),
            ("Кубок «Серебряных Ключей»", 10, 1, 1, "stableford", "men,women", 4500, 24, "registration", "Ключевое поле", 28, None),
            ("Турнир «Золотая осень»", 17, 1, 1, "stroke_net", "men,women,seniors", 3500, 60, "registration", "Озёрное поле", 23, None),
            ("Закрытие сезона", 25, 2, 2, "stroke_gross", "men,women,juniors,seniors", 5000, 72, "registration", "Берёзовое поле", 31, None),
            (f"Открытие сезона {d.year + 1}", 200, 1, 1, "stroke_net", "men,women", 3000, 72, "draft", "Чемпионское поле", 0, None),
        ]
        descriptions = {
            "cancelled": "Турнир отменён: реконструкция грин-зоны на поле клуба. Взносы не принимались.",
            "draft": "Черновик календаря следующего сезона. Даты уточняются.",
        }
        self.tournament_list: list[Tournament] = []
        for (name, off, days, rounds, fmt, cats, fee, limit, status, cname, n, flt) in spec:
            start = d + timedelta(days=off)
            t = Tournament(
                name=name, start_date=start, end_date=start + timedelta(days=days - 1), course=courses[cname],
                format=fmt, categories=cats, rounds_count=rounds, entry_fee=fee, max_participants=limit,
                registration_deadline=start - timedelta(days=5), status=status,
                description=descriptions.get(status, "Официальный турнир календаря Федерации гольфа Московской области."),
            )
            self.s.add(t)
            self.tournament_list.append((t, n, flt))
        self.s.flush()

        # Process chronologically so handicaps at tournament time come from earlier rounds.
        for t, n, flt in sorted(self.tournament_list, key=lambda x: x[0].start_date):
            if n:
                self.fill_tournament(t, n, flt)
        self.tournament_list = [t for t, _, _ in self.tournament_list]

    def eligible(self, t: Tournament, flt: str | None) -> list[Member]:
        out = []
        for m in self.member_list:
            if m.join_date > t.registration_deadline - timedelta(days=3) or m.status == "suspended":
                continue
            cat = age_category(m.birth_date, t.start_date)
            if flt == "junior" and cat != "junior":
                continue
            if flt == "senior" and cat != "senior":
                continue
            if flt == "low" and self.ability[m.id] > 20:
                continue
            if flt is None and cat == "junior" and self.ability[m.id] > 40:
                continue
            out.append(m)
        return out

    def fill_tournament(self, t: Tournament, n: int, flt: str | None) -> None:
        r = self.rng
        pool = self.eligible(t, flt)
        chosen = r.sample(pool, min(n, len(pool)))
        chosen.sort(key=lambda m: r.random())
        for i, m in enumerate(chosen):
            applied = t.registration_deadline - timedelta(days=r.randint(1, 30))
            if t.status == "registration":
                applied = min(applied, self.today - timedelta(days=r.randint(0, 12)))
            tee_color = self.home_tee(m, t.course).color
            reg = Registration(tournament=t, member=m, applied_on=applied, tee=tee_color, status="confirmed", fee_paid=True,
                               category=leaderboard.assign_category(m, t.category_codes, t.start_date))
            self.s.add(reg)
            if t.status == "registration":
                if i >= t.max_participants:
                    reg.status, reg.fee_paid = "waitlist", False
                elif r.random() < 0.45:
                    reg.status, reg.fee_paid = "applied", r.random() < 0.5
        if t.status == "registration":
            # Waitlist order follows application date: the latest applicants wait.
            regs = sorted(t.registrations, key=lambda x: x.applied_on)
            for j, reg in enumerate(regs):
                if j >= t.max_participants and reg.status != "waitlist":
                    reg.status, reg.fee_paid = "waitlist", False
                elif j < t.max_participants and reg.status == "waitlist":
                    reg.status = "applied"
            open_regs = [x for x in t.registrations if x.status == "applied"]
            if len(open_regs) > 6 and t.max_participants > 30:
                r.choice(open_regs).status = "rejected"
        self.s.flush()

        if t.status not in ("finished", "in_progress"):
            return
        for reg in t.registrations:
            m = reg.member
            tee = t.course.tee(reg.tee)
            idx = self.index_at(m, t.start_date)
            res = Result(course_handicap=handicap.course_handicap(idx, tee.slope_rating, tee.course_rating, tee.par))
            reg.result = res
            played_rounds = t.rounds_count
            if t.status == "in_progress":
                # Round 1 done yesterday, round 2 underway today, round 3 tomorrow.
                played_rounds = 2 if r.random() < 0.6 else 1
            for k in range(1, played_rounds + 1):
                setattr(res, f"r{k}", self.simulate_score(self.ability[m.id], tee, pressure=0.8))
        self.s.flush()
        leaderboard.recalculate(t)
        if t.status == "finished":
            for reg in t.registrations:
                tee = t.course.tee(reg.tee)
                for k, score in enumerate(reg.result.scores[: t.rounds_count], start=1):
                    self.add_round(reg.member, tee, t.start_date + timedelta(days=k - 1), score, reg.result, k)
        self.s.flush()

    def finalize_handicaps(self) -> None:
        for m in self.member_list:
            rounds = sorted(m.rounds, key=lambda x: x.played_on)
            # Keep the history within 25 rounds (drop the oldest casual rounds).
            while len(rounds) > 25:
                oldest = next(x for x in rounds if x.result_id is None)
                rounds.remove(oldest)
                m.rounds.remove(oldest)
            handicap.recalculate_member(m)
            m.handicap_updated_at = datetime.combine(self.today, time(7, 0))

    # ------------------------------------------------------------------ payments
    def payments(self) -> None:
        r, today = self.rng, self.today
        year = today.year
        methods = ["card"] * 11 + ["invoice"] * 6 + ["cash"] * 3

        # Choose statuses: ~12% overdue membership (status "unpaid"), ~3% suspended.
        candidates = [m for m in self.member_list if max(date(year, 1, 15), m.join_date) <= today - timedelta(days=45)]
        overdue = set(m.id for m in r.sample(candidates, round(len(self.member_list) * 0.12)))
        rest = [m for m in self.member_list if m.id not in overdue]
        suspended = set(m.id for m in r.sample(rest, 6))

        for m in self.member_list:
            if m.id in suspended:
                m.status = "suspended"
                m.notes = r.choice(SUSPENDED_NOTES)
            # previous season
            if m.join_date < date(year, 1, 1):
                issued = max(date(year - 1, 1, 15), m.join_date)
                paid = issued + timedelta(days=r.randint(0, 28))
                self.s.add(Payment(member=m, type="membership", amount=payments.membership_fee(m, issued),
                                   issued_on=issued, due_date=issued + timedelta(days=config.MEMBERSHIP_PAYMENT_TERM_DAYS),
                                   paid_on=paid, method=r.choice(methods), status="paid", period_year=year - 1,
                                   comment=f"Членский взнос за {year - 1} год"))
            # current season
            issued = max(date(year, 1, 15), m.join_date)
            if issued > today:
                continue
            due = issued + timedelta(days=config.MEMBERSHIP_PAYMENT_TERM_DAYS)
            p = Payment(member=m, type="membership", amount=payments.membership_fee(m, issued), issued_on=issued,
                        due_date=due, method=r.choice(methods), status="paid", period_year=year,
                        comment=f"Членский взнос за {year} год")
            if m.id in overdue:
                p.status, p.method = "overdue", "invoice"
                m.status = "unpaid"
            elif due >= today and r.random() < 0.5:
                p.status = "pending"
            else:
                p.paid_on = min(today, issued + timedelta(days=r.randint(0, 25)))
            self.s.add(p)

        for t in self.tournament_list:
            if t.entry_fee == 0:
                continue
            for reg in t.registrations:
                if reg.status in ("waitlist", "rejected"):
                    continue
                if reg.fee_paid:
                    paid = min(today, reg.applied_on + timedelta(days=r.randint(0, 4)))
                    self.s.add(Payment(member=reg.member, type="tournament", amount=t.entry_fee, issued_on=reg.applied_on,
                                       due_date=t.registration_deadline, paid_on=paid, method=r.choice(["card"] * 4 + ["cash"]),
                                       status="paid", registration=reg, comment=f"Взнос: {t.name}"))
                else:
                    self.s.add(Payment(member=reg.member, type="tournament", amount=t.entry_fee, issued_on=reg.applied_on,
                                       due_date=t.registration_deadline, method="card", status="pending",
                                       registration=reg, comment=f"Взнос: {t.name}"))

        others = [("Аренда шкафчика на сезон", 6000), ("Курс «Правила гольфа для начинающих»", 4500),
                  ("Благотворительный взнос в фонд юниорского гольфа", 10000), ("Дубликат членской карты", 500),
                  ("Семинар для судей-стажёров", 3500)]
        active = [m for m in self.member_list if m.status == "active"]
        for _ in range(16):
            m = r.choice(active)
            text, amount = r.choice(others)
            day = self.in_season(today - timedelta(days=360), today - timedelta(days=1))
            self.s.add(Payment(member=m, type="other", amount=amount, issued_on=day, due_date=day + timedelta(days=14),
                               paid_on=day, method=r.choice(methods), status="paid", comment=text))
        self.s.flush()

    # ------------------------------------------------------------------ officials, mailings, audit
    def officials(self) -> None:
        r, d = self.rng, self.today
        spec = [
            ("referee", "Судья всероссийской категории", 540), ("referee", "Судья I категории", 18),
            ("referee", "Судья I категории", 410), ("referee", "Судья II категории", 45),
            ("coach", "Тренер высшей категории", 720), ("coach", "Тренер I категории", 300),
            ("coach", "Тренер-инструктор", -12), ("rules_committee", "Председатель комитета по правилам", 880),
            ("rules_committee", "Член комитета по правилам", 150),
        ]
        for role, qual, days in spec:
            male = r.random() < 0.7
            name = self.full_name(male)
            first = name.split()[1]
            self.s.add(Official(full_name=name, role=role, qualification=qual, cert_expiry=d + timedelta(days=days),
                                phone=self.phone(), email=f"{translit(first)}.{translit(name.split()[0])}@example.com",
                                club=r.choice(self.club_list) if role == "coach" else None))

    def mailings_and_audit(self) -> None:
        r, d = self.rng, self.today
        by_name = {t.name: t for t in self.tournament_list}
        mails = [
            (-40, "all", None, "Открыта регистрация на Кубок «Княжьих Лугов»",
             "Уважаемые члены Федерации!\n\nОткрыта регистрация на Кубок «Княжьих Лугов». Заявки принимаются в разделе турниров до окончания срока регистрации.\n\nДо встречи на поле!"),
            (-25, "debtors", None, "Напоминание об оплате членского взноса",
             f"Добрый день!\n\nНапоминаем, что членский взнос Федерации за {d.year} год не оплачен. Оплатить взнос можно картой, по счёту или наличными в офисе Федерации.\n\nСпасибо!"),
            (-12, "juniors", None, "Сбор юниорской сборной области",
             "Приглашаем юниоров на учебно-тренировочный сбор сборной области. Подробности — у тренеров вашего клуба."),
            (-2, "tournament", "Осенний Кубок Федерации", "Стартовый протокол Осеннего Кубка Федерации",
             "Уважаемые участники!\n\nСтартовый протокол первого раунда опубликован. Просим прибыть на регистрацию не позднее чем за 40 минут до старта."),
        ]
        for off, seg, tname, subject, body in mails:
            param = by_name[tname].id if tname else None
            res = segmentation.resolve(self.s, seg, param, d)
            when = datetime.combine(d + timedelta(days=off), time(r.randint(9, 17), r.randint(0, 59)))
            msg = Message(subject=subject, body=body, segment=seg, segment_param=param, segment_label=res.label,
                          sent_at=when, status="sent", recipients_count=len(res.recipients), sent_by=self.s.get(User, DIRECTOR_ID).label)
            self.s.add(msg)
            self.s.flush()
            self.audit(when, "admin", "mailing", "message", msg.id,
                       f"Рассылка «{subject}» (сегмент: {res.label}), получателей: {len(res.recipients)}")

        # A plausible trail of recent actions.
        members = self.member_list
        for _ in range(22):
            m = r.choice(members)
            when = datetime.combine(d - timedelta(days=r.randint(1, 30)), time(r.randint(9, 19), r.randint(0, 59)))
            kind = r.random()
            if kind < 0.35:
                p = next((p for p in m.payments if p.status == "paid"), None)
                if p:
                    self.audit(when, "accountant", "payment", "payment", p.id,
                               f"Платёж №{p.id} ({m.full_name}) отмечен как оплаченный")
            elif kind < 0.6:
                self.audit(when, "secretary", "update", "member", m.id, f"Обновлены контактные данные игрока {m.full_name}")
            elif kind < 0.8:
                reg = next((x for x in m.registrations if x.status == "confirmed"), None)
                if reg:
                    self.audit(when, "secretary", "status", "registration", reg.id,
                               f"Заявка {m.full_name} на турнир «{reg.tournament.name}»: статус «Подтверждена»")
            else:
                self.audit(when, "admin", "handicap", "member", m.id,
                           f"Пересчитан гандикап игрока {m.full_name}: {m.handicap_index}")
        for t in self.tournament_list:
            if t.status == "finished":
                when = datetime.combine(t.end_date, time(19, 30))
                self.audit(when, "secretary", "results", "tournament", t.id, f"Введены результаты турнира «{t.name}»")
                self.audit(when + timedelta(minutes=5), "secretary", "status", "tournament", t.id,
                           f"Турнир «{t.name}»: статус «Завершён»")
        self.audit(datetime.combine(d, time(7, 0)), "admin", "create", "member", None,
                   "Загружены демонстрационные данные (все данные вымышлены)")

    def audit(self, when, role, action, etype, eid, text) -> None:
        user = self.s.get(User, ROLE_DEFAULT_USER[role])
        self.s.add(AuditLog(created_at=when, user=user.label, action=action, entity_type=etype, entity_id=eid,
                            description=text))

    # ------------------------------------------------------------------ tasks
    def tasks(self) -> None:
        """Director's tasks for the managers in every state; history is replayed through the task service."""
        d = self.today
        day0 = datetime.combine(d, time(0, 0))

        def at(days: int, hh: int, mm: int = 0) -> datetime:
            return day0 + timedelta(days=days, hours=hh, minutes=mm)

        director = self.s.get(User, DIRECTOR_ID)
        by_name = {t.name: t for t in self.tournament_list}
        clubs = {c.name: c for c in self.club_list}
        star = min(self.member_list, key=lambda m: m.handicap_index or 54)
        ivan, maria, alexey = (self.s.get(User, uid) for uid in (2, 3, 4))
        spec = [
            # assignee, title, description, priority, created, due, related, history
            (ivan, "Подготовить стартовый протокол Кубка «Серебряных Ключей»",
             "Сформировать группы по гандикапу, согласовать время стартов с клубом (интервал 10 минут), "
             "разослать протокол участникам за 3 дня до турнира.", "high", at(-3, 10, 5), at(4, 18),
             ("tournament", by_name["Кубок «Серебряных Ключей»"].id), [("start", at(-1, 10, 15))]),
            (ivan, "Согласовать судейскую бригаду на турнир «Золотая осень»",
             "Нужны главный судья и два судьи на поле. Проверить, что у всех действует аттестация.", "normal",
             at(-1, 16, 20), at(9, 12), ("tournament", by_name["Турнир «Золотая осень»"].id), []),
            (ivan, "Разослать итоговый протокол Кубка «Княжьих Лугов» клубам",
             "PDF протокола — всем клубам-участникам и на сайт Федерации.", "normal", at(-19, 11), at(-12, 18),
             ("tournament", by_name["Кубок «Княжьих Лугов»"].id),
             [("start", at(-18, 9, 40)), ("complete", at(-14, 16, 40), "Разослано 7 клубам, опубликовано на сайте.")]),
            (ivan, "Проверить заявки юниоров на «Закрытие сезона»",
             "Сверить возраст и гандикап юниоров, подавших заявки, уточнить зачёт.", "normal", at(-6, 12, 30),
             at(-1, 18), ("tournament", by_name["Закрытие сезона"].id), [("start", at(-4, 11))]),
            (ivan, "Проверить корректность раундов лучшего игрока области",
             "Перед публикацией рейтинга сверить карточки последних раундов и пересчитать индекс.", "normal",
             at(-2, 9, 30), at(1, 18), ("member", star.id),
             [("start", at(-2, 14)), ("complete", at(-1, 17, 30), "Раунды сверены, индекс пересчитан — ошибок нет.")]),
            (maria, "Напомнить должникам об оплате членского взноса",
             "Сделать рассылку должникам и обзвонить тех, у кого просрочка больше 60 дней.", "high", at(0, 9, 10),
             at(2, 17), None, []),
            (maria, "Сверить турнирные взносы Осеннего Кубка Федерации",
             "Все подтверждённые участники должны быть с оплаченным взносом; расхождения — в комментарий.", "normal",
             at(-2, 15), at(1, 15), ("tournament", by_name["Осенний Кубок Федерации"].id), [("start", at(-1, 11, 45))]),
            (maria, "Подготовить отчёт о поступлениях за месяц",
             "Сводка по членским и турнирным взносам, сравнение с прошлым месяцем.", "normal", at(-8, 10),
             at(-3, 12), None, [("start", at(-6, 10)), ("complete", at(-4, 18, 5), "Отчёт в папке «Финансы», итог выше плана.")]),
            (maria, "Выставить счета за аренду шкафчиков",
             "Счета всем арендаторам на следующий сезон.", "low", at(-10, 14), at(-6, 18), None,
             [("start", at(-7, 9)), ("complete", at(-5, 11, 20), "")]),
            (alexey, "Обновить контакты клуба «Тихая Заводь»",
             "Сменился управляющий клуба — обновить контактное лицо и телефон.", "low", at(-1, 10), at(14, 18),
             ("club", clubs["Гольф-клуб «Тихая Заводь»"].id), []),
            (alexey, "Согласовать с клубом «Озёрный Край» даты весеннего турнира",
             "Предложить 2–3 варианта дат в мае, учесть календарь соседних клубов.", "normal", at(-9, 12),
             at(-2, 12), ("club", clubs["Гольф-клуб «Озёрный Край»"].id), []),
            (alexey, "Собрать согласия на обработку ПДн у новых игроков",
             "У части игроков нет согласия — без него они не попадают в рассылки.", "high", at(-4, 9), at(5, 18),
             None, [("start", at(-3, 10, 30))]),
            (alexey, "Подготовить поздравление победителям Чемпионата области",
             "Текст для сайта и соцсетей, фото награждения.", "low", at(-60, 10), at(-55, 18),
             ("tournament", by_name["Чемпионат Московской области"].id),
             [("start", at(-59, 11)), ("complete", at(-58, 15, 10), "Опубликовано.")]),
            (alexey, "Организовать фотосъёмку на Кубке «Тихой Заводи»",
             "Договориться с фотографом, согласовать площадку для награждения.", "normal", at(-40, 12), at(-31, 9),
             ("tournament", by_name["Кубок «Тихой Заводи»"].id), [("cancel", at(-36, 17))]),
        ]
        for assignee, title, desc, prio, created, due, related, history in spec:
            data = dict(title=title, description=desc, assignee=assignee, priority=prio, due_at=due,
                        related_type=related[0] if related else None, related_id=related[1] if related else None)
            task = task_service.create(self.s, director, data, created)
            for step in history:
                if step[0] == "start":
                    task_service.start(self.s, task, assignee, step[1])
                elif step[0] == "complete":
                    task_service.complete(self.s, task, assignee, step[2], step[1])
                else:
                    task_service.cancel(self.s, task, director, step[1])
        self.s.flush()
        task_service.sync_overdue(self.s, max(msk.now(), day0 + timedelta(hours=7)))
        # Older notifications have been read; the last three days stay unread.
        for n in self.s.scalars(select(Notification)):
            n.is_read = n.created_at < day0 - timedelta(days=3)

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self.clubs()
        self.members()
        self.assign_abilities()
        self.casual_rounds()
        self.s.flush()
        self.tournaments()
        self.finalize_handicaps()
        self.payments()
        self.officials()
        self.s.flush()
        ensure_users(self.s)
        self.mailings_and_audit()
        self.tasks()
        self.s.commit()


def seed(session: Session, today: date | None = None) -> None:
    Seeder(session, today or msk.today()).run()


def reset_database(bind=None) -> None:
    from app import models  # noqa: F401

    bind = bind or engine
    Base.metadata.drop_all(bind)
    Base.metadata.create_all(bind)


if __name__ == "__main__":
    reset_database()
    with SessionLocal() as s:
        seed(s)
    print(f"Демо-данные созданы: {config.DB_PATH}")
