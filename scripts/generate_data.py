#!/usr/bin/env python3
"""SiamStay Phase 1 synthetic extract.

Stochastic fields come from a NumPy Generator seeded with 42. The legacy
NumPy seed is set to 42 as well. Faker is seeded with 42 and is used only to
draw synthetic name/email samples, which are discarded: the published schema
has no identity columns.

Booking and payment volumes are emergent, not fixed inserts:
  P(view) = 0.55
  P(checkout | view) = 0.22, times 1.8 before a FLASH50 user's first booking
      and times 0.4 for a FLASH50 user within 90 days after that booking
  P(payment attempt | booking) = 0.92, except android-4.2.x silent crashes,
      which write a booking with a blank created_ts and no payment row
A second run on the pinned stack writes byte-identical CSVs.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
N_HOTELS = 800
N_USERS = 20_000
N_SESSIONS = 60_000
N_NULL_DEVICE = 1_200  # 2.0% of distinct sessions
N_UTC_TIMESTAMPS = 900  # 1.5% of distinct sessions
N_DUPLICATE_ROWS = 300  # 0.5% extra exact copies

P_VIEW = 0.55
P_CHECKOUT = 0.22
P_PAYMENT = 0.92
P_FAIL_BASE = 0.04
P_FAIL_A1 = 0.22
P_CRASH = 0.30
FLASH_FIRST_MULT = 1.8
FLASH_REPEAT_MULT = 0.4
FLASH_USERS = 2_400
WELCOME_USERS = 1_600
SUMMER_USERS = 1_000

ICT = timezone(timedelta(hours=7))
UTC = timezone.utc
WINDOW_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ICT)
WINDOW_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=ICT)
SIGNUP_START = date(2025, 7, 1)
SIGNUP_END = date(2026, 12, 15)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# Relative weights. Night hours 22, 23, 0, and 1 are elevated for the wallet case.
_HOUR_W = np.array(
    [
        2.6, 2.2, 0.30, 0.20, 0.20, 0.35, 0.70, 1.20,
        1.70, 2.10, 2.30, 2.50, 2.70, 2.40, 2.10, 2.00,
        2.15, 2.35, 2.60, 2.80, 2.70, 2.50, 2.80, 2.60,
    ],
    dtype=float,
)
HOUR_P = _HOUR_W / _HOUR_W.sum()
NIGHT_HOURS = {22, 23, 0, 1}

COUNTRIES = ["TH", "SG", "MY", "ID", "VN", "PH", "KH", "LA", "MM", "AU", "JP", "KR"]
COUNTRY_P = [0.42, 0.10, 0.10, 0.09, 0.09, 0.06, 0.03, 0.02, 0.02, 0.03, 0.02, 0.02]
CHANNELS = ["organic", "paid_search", "paid_social", "affiliate", "email", "direct"]
CHANNEL_P = [0.30, 0.25, 0.18, 0.12, 0.08, 0.07]
SEGMENTS = ["business", "backpacker", "family"]
SEGMENT_P = [0.22, 0.38, 0.40]

DEVICE_LABELS = ["mobile", "desktop", "tablet"]
DEVICE_P = {
    "business": [0.35, 0.58, 0.07],
    "backpacker": [0.84, 0.11, 0.05],
    "family": [0.72, 0.18, 0.10],
}
PLATFORM = {
    "mobile": (
        ["ios-18.2", "ios-17.6", "android-15.1", "android-14.8", "android-4.2.x"],
        [0.30, 0.14, 0.24, 0.16, 0.16],
    ),
    "tablet": (
        ["ios-18.2", "android-15.1", "android-4.2.x", "android-14.8"],
        [0.42, 0.28, 0.18, 0.12],
    ),
    "desktop": (["web-3.4.1", "web-3.3.0"], [0.72, 0.28]),
}
UTM = ["google", "facebook", "instagram", "tiktok", "line", "email", "direct", "affiliate", "organic"]
UTM_P = [0.22, 0.14, 0.10, 0.08, 0.07, 0.08, 0.12, 0.07, 0.12]
METHODS = {
    "mobile": (
        ["PromptPay", "credit_card", "TrueMoney", "debit_card", "GrabPay", "ShopeePay", "bank_transfer"],
        [0.42, 0.20, 0.12, 0.08, 0.08, 0.06, 0.04],
    ),
    "desktop": (
        ["credit_card", "debit_card", "PromptPay", "bank_transfer", "TrueMoney"],
        [0.46, 0.22, 0.12, 0.14, 0.06],
    ),
    "tablet": (
        ["credit_card", "PromptPay", "debit_card", "TrueMoney", "GrabPay"],
        [0.34, 0.28, 0.16, 0.12, 0.10],
    ),
    "": (
        ["credit_card", "PromptPay", "debit_card", "bank_transfer", "TrueMoney"],
        [0.40, 0.25, 0.15, 0.12, 0.08],
    ),
}
FAIL_REASONS = ["card_declined", "insufficient_funds", "user_cancelled", "otp_timeout", "bank_rejected"]
FAIL_REASON_P = [0.34, 0.22, 0.18, 0.14, 0.12]
SEGMENT_STARS = {"business": (4, 5), "backpacker": (2, 3), "family": (3, 4)}
STAR_P = [0.15, 0.40, 0.30, 0.15]
PRICE_BAND = {2: (800, 1800), 3: (1600, 3800), 4: (3500, 9000), 5: (8500, 28000)}

# (city, hotel count, districts). Counts sum to 800.
CITY_PLAN = [
    ("Bangkok", 140, ["Sukhumvit", "Silom", "Siam", "Riverside", "Sathorn", "Ari", "Thonglor", "Chatuchak", "Ratchadaphisek", "Phra Nakhon"]),
    ("Chiang Mai", 50, ["Old City", "Nimman", "Night Bazaar", "Riverside", "Hang Dong"]),
    ("Phuket", 70, ["Patong", "Kata", "Karon", "Kamala", "Rawai", "Phuket Town"]),
    ("Pattaya", 40, ["Central Pattaya", "Jomtien", "Naklua", "Pratumnak"]),
    ("Krabi", 30, ["Ao Nang", "Railay", "Krabi Town"]),
    ("Koh Samui", 36, ["Chaweng", "Lamai", "Bophut", "Mae Nam"]),
    ("Hua Hin", 24, ["Hua Hin Beach", "Khao Takiab", "Khao Tao"]),
    ("Singapore", 60, ["Marina Bay", "Orchard", "Chinatown", "Sentosa", "Bugis"]),
    ("Bali", 70, ["Seminyak", "Ubud", "Kuta", "Canggu", "Uluwatu", "Sanur"]),
    ("Kuala Lumpur", 50, ["Bukit Bintang", "KLCC", "Chinatown", "Bangsar"]),
    ("Penang", 24, ["George Town", "Batu Ferringhi"]),
    ("Ho Chi Minh City", 46, ["District 1", "District 3", "Thao Dien"]),
    ("Hanoi", 36, ["Hoan Kiem", "Old Quarter", "Tay Ho"]),
    ("Da Nang", 30, ["My Khe", "Son Tra"]),
    ("Hoi An", 16, ["Ancient Town", "Cam An"]),
    ("Jakarta", 40, ["Menteng", "Kemang", "Thamrin"]),
    ("Yogyakarta", 18, ["Malioboro", "Prawirotaman"]),
    ("Siem Reap", 20, ["Svay Dangkum", "Sala Kamreuk"]),
]
CITY_DEMAND = [
    ("Bangkok", 0.18),
    ("Phuket", 0.10),
    ("Chiang Mai", 0.07),
    ("Bali", 0.09),
    ("Singapore", 0.08),
    ("Pattaya", 0.05),
    ("Ho Chi Minh City", 0.06),
    ("Hanoi", 0.04),
    ("Da Nang", 0.03),
    ("Kuala Lumpur", 0.06),
    ("Krabi", 0.04),
    ("Koh Samui", 0.05),
    ("Hua Hin", 0.03),
    ("Jakarta", 0.04),
    ("Penang", 0.02),
    ("Hoi An", 0.02),
    ("Yogyakarta", 0.02),
    ("Siem Reap", 0.02),
]
# Multipliers in basis points (1050 = 1.050x) so prices stay integer.
CITY_MULT_BP = {
    "Bangkok": 1050,
    "Chiang Mai": 750,
    "Phuket": 1150,
    "Pattaya": 850,
    "Krabi": 1000,
    "Koh Samui": 1200,
    "Hua Hin": 950,
    "Singapore": 1550,
    "Bali": 800,
    "Kuala Lumpur": 900,
    "Penang": 850,
    "Ho Chi Minh City": 700,
    "Hanoi": 680,
    "Da Nang": 720,
    "Hoi An": 780,
    "Jakarta": 820,
    "Yogyakarta": 600,
    "Siem Reap": 650,
}
HOME_CITIES = {
    "TH": ["Bangkok", "Chiang Mai", "Phuket", "Pattaya", "Krabi", "Koh Samui", "Hua Hin"],
    "SG": ["Singapore"],
    "ID": ["Bali", "Jakarta", "Yogyakarta"],
    "MY": ["Kuala Lumpur", "Penang"],
    "VN": ["Ho Chi Minh City", "Hanoi", "Da Nang", "Hoi An"],
    "KH": ["Siem Reap"],
}
HOME_BIAS = {"TH": 0.62, "SG": 0.28, "ID": 0.40, "MY": 0.35, "VN": 0.45, "KH": 0.30}

USER_COLUMNS = ["user_id", "signup_date", "country", "acquisition_channel", "promo_code"]
SESSION_COLUMNS = [
    "session_id",
    "user_id",
    "session_start_ts",
    "device_type",
    "platform_version",
    "utm_source",
    "viewed",
]
BOOKING_COLUMNS = [
    "booking_id",
    "session_id",
    "user_id",
    "hotel_id",
    "checkin_date",
    "nights",
    "gross_amount_thb",
    "created_ts",
]
PAYMENT_COLUMNS = [
    "payment_id",
    "booking_id",
    "method",
    "status",
    "attempted_ts",
    "failure_reason",
    "amount_thb",
]
HOTEL_COLUMNS = ["hotel_id", "city", "district", "star_rating", "avg_price_thb"]


def _unit(name: str, weights: list[float]) -> None:
    total = float(sum(weights))
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"{name} probabilities sum to {total}")


def check_constants() -> None:
    _unit("country", COUNTRY_P)
    _unit("channel", CHANNEL_P)
    _unit("segment", SEGMENT_P)
    _unit("star", STAR_P)
    _unit("utm", UTM_P)
    _unit("fail_reason", FAIL_REASON_P)
    for key, weights in DEVICE_P.items():
        _unit(f"device:{key}", weights)
    for key, (_, weights) in PLATFORM.items():
        _unit(f"platform:{key}", weights)
    for key, (_, weights) in METHODS.items():
        _unit(f"method:{key}", weights)
    if sum(count for _, count, _ in CITY_PLAN) != N_HOTELS:
        raise ValueError("hotel counts must sum to 800")
    plan_cities = [city for city, _, _ in CITY_PLAN]
    demand_cities = [city for city, _ in CITY_DEMAND]
    if plan_cities != demand_cities and set(plan_cities) != set(demand_cities):
        raise ValueError("city plan and city demand diverged")
    if set(plan_cities) != set(demand_cities) or set(plan_cities) != set(CITY_MULT_BP):
        raise ValueError("city catalogs must match")
    _unit("city_demand", [weight for _, weight in CITY_DEMAND])
    if FLASH_USERS + WELCOME_USERS + SUMMER_USERS > N_USERS:
        raise ValueError("promo allocations exceed user count")
    if abs(float(HOUR_P.sum()) - 1.0) > 1e-9:
        raise ValueError("hour probabilities must sum to 1")


def pick_weighted(rng: np.random.Generator, labels: list, weights: list[float]):
    weights_arr = np.asarray(weights, dtype=float)
    weights_arr = weights_arr / weights_arr.sum()
    return labels[int(rng.choice(len(labels), p=weights_arr))]


def fmt_ict(ts: datetime) -> str:
    if ts.utcoffset() != timedelta(hours=7):
        raise ValueError("ICT formatter received a non-ICT timestamp")
    return ts.isoformat(timespec="seconds")


def fmt_utc_naive(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def parse_ts(value: str) -> datetime:
    if value.endswith("+07:00"):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    naive = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    return naive.replace(tzinfo=UTC).astimezone(ICT)


def discard_faker_identities() -> None:
    """Seed Faker and prove identity strings are available, then drop them."""
    Faker.seed(SEED)
    fake = Faker()
    fake.seed_instance(SEED)
    name = fake.name()
    email = fake.email()
    if not name or "@" not in email:
        raise RuntimeError("Faker did not produce a synthetic identity sample")


def build_hotels(rng: np.random.Generator) -> list[dict]:
    stars = rng.choice(np.array([2, 3, 4, 5]), size=N_HOTELS, p=np.array(STAR_P, dtype=float))
    hotels: list[dict] = []
    cursor = 0
    for city, count, districts in CITY_PLAN:
        for _ in range(count):
            star = int(stars[cursor])
            low, high = PRICE_BAND[star]
            raw_price = int(rng.integers(low, high))
            district = districts[int(rng.integers(0, len(districts)))]
            avg_price = max(1, (raw_price * CITY_MULT_BP[city] + 500) // 1000)
            cursor += 1
            hotels.append(
                {
                    "hotel_id": len(hotels) + 1,
                    "city": city,
                    "district": district,
                    "star_rating": star,
                    "avg_price_thb": avg_price,
                }
            )
    if cursor != N_HOTELS:
        raise RuntimeError("hotel cursor did not consume every star draw")
    return hotels


def hotel_indexes(hotels: list[dict]) -> tuple[dict, dict, dict]:
    by_city_star: dict[tuple[str, int], list[int]] = defaultdict(list)
    by_star: dict[int, list[int]] = {2: [], 3: [], 4: [], 5: []}
    price_by_id: dict[int, int] = {}
    for hotel in hotels:
        by_city_star[(hotel["city"], hotel["star_rating"])].append(hotel["hotel_id"])
        by_star[hotel["star_rating"]].append(hotel["hotel_id"])
        price_by_id[hotel["hotel_id"]] = hotel["avg_price_thb"]
    for star, ids in by_star.items():
        if not ids:
            raise RuntimeError(f"no hotels with star rating {star}")
    return by_city_star, by_star, price_by_id


def build_users(rng: np.random.Generator) -> list[dict]:
    span_days = (SIGNUP_END - SIGNUP_START).days
    offsets = rng.integers(0, span_days + 1, size=N_USERS)
    country_idx = rng.choice(len(COUNTRIES), size=N_USERS, p=np.array(COUNTRY_P, dtype=float))
    channel_idx = rng.choice(len(CHANNELS), size=N_USERS, p=np.array(CHANNEL_P, dtype=float))
    segment_idx = rng.choice(len(SEGMENTS), size=N_USERS, p=np.array(SEGMENT_P, dtype=float))
    promo = np.empty(N_USERS, dtype=object)
    promo[:FLASH_USERS] = "FLASH50"
    promo[FLASH_USERS : FLASH_USERS + WELCOME_USERS] = "WELCOME10"
    promo[FLASH_USERS + WELCOME_USERS : FLASH_USERS + WELCOME_USERS + SUMMER_USERS] = "SUMMER25"
    promo[FLASH_USERS + WELCOME_USERS + SUMMER_USERS :] = ""
    promo = promo[rng.permutation(N_USERS)]
    users = []
    for i in range(N_USERS):
        users.append(
            {
                "user_id": i + 1,
                "signup_date": SIGNUP_START + timedelta(days=int(offsets[i])),
                "country": COUNTRIES[int(country_idx[i])],
                "acquisition_channel": CHANNELS[int(channel_idx[i])],
                "promo_code": str(promo[i]),
                "segment": SEGMENTS[int(segment_idx[i])],
            }
        )
    return users


def cluster_bounds(rng: np.random.Generator, earliest: datetime, latest: datetime) -> tuple[datetime, datetime]:
    room_days = (latest.date() - earliest.date()).days - 90
    if room_days < 0:
        start_day = earliest.date()
        end_day = latest.date()
    else:
        off = int(rng.integers(0, room_days + 1))
        start_day = earliest.date() + timedelta(days=off)
        end_day = start_day + timedelta(days=90)
    start = datetime(start_day.year, start_day.month, start_day.day, 0, 0, 0, tzinfo=ICT)
    end = datetime(end_day.year, end_day.month, end_day.day, 23, 59, 59, tzinfo=ICT)
    return start, end


def draw_session_ts(rng: np.random.Generator, start: datetime, end: datetime) -> datetime:
    span_days = (end.date() - start.date()).days
    day = start.date() + timedelta(days=int(rng.integers(0, span_days + 1)))
    hour = int(rng.choice(24, p=HOUR_P))
    minute = int(rng.integers(0, 60))
    second = int(rng.integers(0, 60))
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ICT)


def choose_city(rng: np.random.Generator, country: str, demand_labels: list[str], demand_weights: list[float]) -> str:
    home = HOME_CITIES.get(country)
    if home and float(rng.random()) < HOME_BIAS[country]:
        if len(home) == 1:
            return home[0]
        weights = [dict(CITY_DEMAND)[city] for city in home]
        return pick_weighted(rng, home, weights)
    return pick_weighted(rng, demand_labels, demand_weights)


def choose_hotel(
    rng: np.random.Generator,
    city: str,
    segment: str,
    by_city_star: dict,
    by_star: dict,
) -> int:
    ids: list[int] = []
    for star in SEGMENT_STARS[segment]:
        ids.extend(by_city_star.get((city, star), []))
    if not ids:
        for star in SEGMENT_STARS[segment]:
            ids.extend(by_star[star])
    return int(rng.choice(np.asarray(ids, dtype=int)))


def stay_shape(rng: np.random.Generator, segment: str, session_day: date) -> tuple[date, int]:
    if segment == "business":
        lead = int(rng.integers(0, 5))
        nights = int(pick_weighted(rng, [1, 2, 3], [0.55, 0.35, 0.10]))
    elif segment == "backpacker":
        lead = int(rng.integers(3, 45))
        nights = int(rng.integers(3, 13))
    else:
        lead = int(rng.integers(7, 60))
        nights = int(pick_weighted(rng, [2, 3, 4, 5], [0.25, 0.40, 0.25, 0.10]))
    checkin = session_day + timedelta(days=lead)
    if segment == "family" and checkin.weekday() not in (4, 5) and float(rng.random()) < 0.75:
        days_to_friday = (4 - checkin.weekday()) % 7
        checkin = checkin + timedelta(days=days_to_friday)
    return checkin, nights


def build_activity(rng: np.random.Generator, users: list[dict], hotels: list[dict]):
    by_city_star, by_star, price_by_id = hotel_indexes(hotels)
    demand_labels = [city for city, _ in CITY_DEMAND]
    demand_weights = [weight for _, weight in CITY_DEMAND]
    probs = np.ones(N_USERS, dtype=float)
    probs /= probs.sum()
    counts = rng.multinomial(N_SESSIONS, probs)

    clusters: dict[int, tuple[datetime, datetime]] = {}
    for user_i, n_sessions in enumerate(counts):
        if int(n_sessions) == 0:
            continue
        signup_dt = datetime(
            users[user_i]["signup_date"].year,
            users[user_i]["signup_date"].month,
            users[user_i]["signup_date"].day,
            0,
            0,
            0,
            tzinfo=ICT,
        )
        earliest = signup_dt if signup_dt > WINDOW_START else WINDOW_START
        clusters[user_i] = cluster_bounds(rng, earliest, WINDOW_END)

    session_user: list[int] = []
    for user_i, n_sessions in enumerate(counts):
        session_user.extend([user_i] * int(n_sessions))
    if len(session_user) != N_SESSIONS:
        raise RuntimeError("session allocation did not sum to 60,000")

    session_dt: list[datetime] = []
    device: list[str] = []
    platform: list[str] = []
    utm: list[str] = []
    for user_i in session_user:
        start, end = clusters[user_i]
        session_dt.append(draw_session_ts(rng, start, end))
        segment = users[user_i]["segment"]
        chosen_device = pick_weighted(rng, DEVICE_LABELS, DEVICE_P[segment])
        device.append(chosen_device)
        labels, weights = PLATFORM[chosen_device]
        platform.append(pick_weighted(rng, labels, weights))
        utm.append(pick_weighted(rng, UTM, UTM_P))

    null_idx = rng.choice(N_SESSIONS, size=N_NULL_DEVICE, replace=False)
    for idx in null_idx:
        device[int(idx)] = ""

    viewed = [0] * N_SESSIONS
    bookings: list[dict] = []
    payments: list[dict] = []
    # Process each account in time order so the first booking is chronological.
    by_user_sessions: dict[int, list[int]] = defaultdict(list)
    for idx, user_i in enumerate(session_user):
        by_user_sessions[user_i].append(idx)

    for user_i in range(N_USERS):
        indexes = by_user_sessions.get(user_i, [])
        indexes.sort(key=lambda idx: (session_dt[idx], idx))
        first_booking_dt: datetime | None = None
        promo = users[user_i]["promo_code"]
        segment = users[user_i]["segment"]
        country = users[user_i]["country"]
        for idx in indexes:
            if float(rng.random()) >= P_VIEW:
                continue
            viewed[idx] = 1
            if first_booking_dt is None:
                checkout_p = P_CHECKOUT * (FLASH_FIRST_MULT if promo == "FLASH50" else 1.0)
            else:
                delta_days = (session_dt[idx].date() - first_booking_dt.date()).days
                if promo == "FLASH50" and delta_days <= 90:
                    checkout_p = P_CHECKOUT * FLASH_REPEAT_MULT
                else:
                    checkout_p = P_CHECKOUT
            if float(rng.random()) >= checkout_p:
                continue

            silent_crash = platform[idx] == "android-4.2.x" and float(rng.random()) < P_CRASH
            checkin, nights = stay_shape(rng, segment, session_dt[idx].date())
            city = choose_city(rng, country, demand_labels, demand_weights)
            hotel_id = choose_hotel(rng, city, segment, by_city_star, by_star)
            noise_bp = int(rng.integers(880, 1121))
            gross = max(1, (price_by_id[hotel_id] * nights * noise_bp + 500) // 1000)
            booking_id = len(bookings) + 1
            created_dt = None
            created_ts = ""
            if not silent_crash:
                created_dt = session_dt[idx] + timedelta(minutes=int(rng.integers(5, 46)))
                created_ts = fmt_ict(created_dt)
            bookings.append(
                {
                    "booking_id": booking_id,
                    "session_id": idx + 1,
                    "user_id": user_i + 1,
                    "hotel_id": hotel_id,
                    "checkin_date": checkin.isoformat(),
                    "nights": nights,
                    "gross_amount_thb": gross,
                    "created_ts": created_ts,
                }
            )
            if first_booking_dt is None:
                first_booking_dt = session_dt[idx]
            if silent_crash or created_dt is None:
                continue
            if float(rng.random()) >= P_PAYMENT:
                continue
            attempted_dt = created_dt + timedelta(minutes=int(rng.integers(1, 9)))
            method_labels, method_weights = METHODS[device[idx]]
            method = pick_weighted(rng, method_labels, method_weights)
            is_a1 = (
                device[idx] == "mobile"
                and method == "PromptPay"
                and attempted_dt.hour in NIGHT_HOURS
            )
            failed = float(rng.random()) < (P_FAIL_A1 if is_a1 else P_FAIL_BASE)
            if failed and is_a1:
                reason = "gateway_timeout"
            elif failed:
                reason = pick_weighted(rng, FAIL_REASONS, FAIL_REASON_P)
            else:
                reason = ""
            payments.append(
                {
                    "payment_id": len(payments) + 1,
                    "booking_id": booking_id,
                    "method": method,
                    "status": "failed" if failed else "success",
                    "attempted_ts": fmt_ict(attempted_dt),
                    "failure_reason": reason,
                    "amount_thb": gross,
                }
            )

    session_start_ts = [fmt_ict(ts) for ts in session_dt]
    utc_idx = rng.choice(N_SESSIONS, size=N_UTC_TIMESTAMPS, replace=False)
    for idx in utc_idx:
        session_start_ts[int(idx)] = fmt_utc_naive(session_dt[int(idx)])
    for idx, text in enumerate(session_start_ts):
        if parse_ts(text) != session_dt[idx]:
            raise RuntimeError(f"timestamp round-trip failed for session index {idx}")

    sessions = []
    for idx in range(N_SESSIONS):
        sessions.append(
            {
                "session_id": idx + 1,
                "user_id": session_user[idx] + 1,
                "session_start_ts": session_start_ts[idx],
                "device_type": device[idx],
                "platform_version": platform[idx],
                "utm_source": utm[idx],
                "viewed": viewed[idx],
            }
        )
    dup_idx = np.sort(rng.choice(N_SESSIONS, size=N_DUPLICATE_ROWS, replace=False))
    sessions.extend(dict(sessions[int(idx)]) for idx in dup_idx)
    return sessions, bookings, payments


def frames(users, sessions, bookings, payments, hotels):
    user_rows = [{key: row[key] for key in USER_COLUMNS} for row in users]
    users_df = pd.DataFrame(user_rows, columns=USER_COLUMNS)
    sessions_df = pd.DataFrame(sessions, columns=SESSION_COLUMNS)
    bookings_df = pd.DataFrame(bookings, columns=BOOKING_COLUMNS)
    payments_df = pd.DataFrame(payments, columns=PAYMENT_COLUMNS)
    hotels_df = pd.DataFrame(hotels, columns=HOTEL_COLUMNS)
    sessions_df = sessions_df.sort_values("session_id", kind="mergesort").reset_index(drop=True)
    bookings_df = bookings_df.sort_values("booking_id", kind="mergesort").reset_index(drop=True)
    payments_df = payments_df.sort_values("payment_id", kind="mergesort").reset_index(drop=True)
    for frame in (users_df, sessions_df, bookings_df, payments_df, hotels_df):
        for column in frame.columns:
            if frame[column].isna().any():
                raise RuntimeError(f"unexpected NA in {column}")
            if frame[column].dtype == object:
                bad = set(frame[column].unique()) & {"nan", "NaN", "None", "NULL", "<NA>"}
                if bad:
                    raise RuntimeError(f"null token leaked into {column}: {bad}")
    return users_df, sessions_df, bookings_df, payments_df, hotels_df


def validate(users_df, sessions_df, bookings_df, payments_df, hotels_df) -> None:
    distinct = sessions_df.drop_duplicates(subset=["session_id"], keep="first")
    if len(hotels_df) != N_HOTELS or len(users_df) != N_USERS:
        raise RuntimeError("hotel or user row count drifted")
    if len(distinct) != N_SESSIONS or len(sessions_df) != N_SESSIONS + N_DUPLICATE_ROWS:
        raise RuntimeError("session row count drifted")
    if int((distinct["device_type"] == "").sum()) != N_NULL_DEVICE:
        raise RuntimeError("null device count drifted")
    utc_distinct = int((~distinct["session_start_ts"].str.endswith("+07:00")).sum())
    offset_distinct = int(distinct["session_start_ts"].str.endswith("+07:00").sum())
    if utc_distinct != N_UTC_TIMESTAMPS or offset_distinct + utc_distinct != N_SESSIONS:
        raise RuntimeError("UTC timestamp count drifted")

    duplicated = sessions_df[sessions_df.duplicated(subset=["session_id"], keep=False)]
    if duplicated.empty or int(sessions_df["session_id"].duplicated().sum()) != N_DUPLICATE_ROWS:
        raise RuntimeError("duplicate session rows are not exact extras")
    for _, group in duplicated.groupby("session_id", sort=False):
        if len(group) != 2 or group.drop_duplicates().shape[0] != 1:
            raise RuntimeError("session_id collision is not an exact duplicate")

    session_user = dict(zip(distinct["session_id"].tolist(), distinct["user_id"].tolist()))
    session_platform = dict(zip(distinct["session_id"].tolist(), distinct["platform_version"].tolist()))
    session_device = dict(zip(distinct["session_id"].tolist(), distinct["device_type"].tolist()))
    session_viewed = dict(zip(distinct["session_id"].tolist(), distinct["viewed"].tolist()))
    user_ids = set(users_df["user_id"].tolist())
    hotel_ids = set(hotels_df["hotel_id"].tolist())
    if set(session_user) - set(distinct["session_id"].tolist()):
        raise RuntimeError("session key mismatch")
    if bookings_df["session_id"].duplicated().any():
        raise RuntimeError("more than one booking per session")
    if payments_df["booking_id"].duplicated().any():
        raise RuntimeError("more than one payment per booking")

    booking_ids = set(bookings_df["booking_id"].tolist())
    paid_ids = set(payments_df["booking_id"].tolist())
    created_by_booking = dict(zip(bookings_df["booking_id"].tolist(), bookings_df["created_ts"].tolist()))
    gross_by_booking = dict(zip(bookings_df["booking_id"].tolist(), bookings_df["gross_amount_thb"].tolist()))
    for row in bookings_df.itertuples(index=False):
        if row.session_id not in session_user or session_user[row.session_id] != row.user_id:
            raise RuntimeError("booking user does not match session user")
        if row.user_id not in user_ids or row.hotel_id not in hotel_ids:
            raise RuntimeError("booking foreign key missing")
        if session_viewed[row.session_id] != 1:
            raise RuntimeError("booking without a view")
        if row.created_ts == "":
            if session_platform[row.session_id] != "android-4.2.x" or row.booking_id in paid_ids:
                raise RuntimeError("blank created_ts is not a silent crash")
        elif session_platform[row.session_id] != "android-4.2.x" and row.created_ts == "":
            raise RuntimeError("non-android booking missing created_ts")
    for row in payments_df.itertuples(index=False):
        if row.booking_id not in booking_ids:
            raise RuntimeError("payment without a booking")
        if created_by_booking[row.booking_id] == "":
            raise RuntimeError("payment on a silent-crash booking")
        if int(row.amount_thb) != int(gross_by_booking[row.booking_id]):
            raise RuntimeError("payment amount diverged from booking gross")
        if row.status == "success" and row.failure_reason != "":
            raise RuntimeError("success row has a failure reason")
        if row.status == "failed" and row.failure_reason == "":
            raise RuntimeError("failed row is missing a failure reason")
        if row.status not in ("success", "failed"):
            raise RuntimeError("unknown payment status")
        attempted = parse_ts(row.attempted_ts)
        is_a1 = (
            session_device[bookings_df.set_index("booking_id").loc[row.booking_id, "session_id"]]
            == "mobile"
            and row.method == "PromptPay"
            and attempted.hour in NIGHT_HOURS
        )
        if row.failure_reason == "gateway_timeout" and not (is_a1 and row.status == "failed"):
            raise RuntimeError("gateway_timeout outside A1")
        if is_a1 and row.status == "failed" and row.failure_reason != "gateway_timeout":
            raise RuntimeError("A1 failure used a non-gateway reason")

    leaked = []
    for frame in (users_df, sessions_df, bookings_df, payments_df, hotels_df):
        for column in frame.columns:
            if frame[column].dtype == object and frame[column].astype(str).str.contains("@").any():
                leaked.append(column)
    if leaked:
        raise RuntimeError(f"identity-like values leaked into {leaked}")


def rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return float("nan")
    return numerator / denominator


def summarize(users_df, sessions_df, bookings_df, payments_df) -> dict:
    distinct = sessions_df.drop_duplicates(subset=["session_id"], keep="first").copy()
    distinct["dt"] = distinct["session_start_ts"].map(parse_ts)
    promo = dict(zip(users_df["user_id"].tolist(), users_df["promo_code"].tolist()))
    device = dict(zip(distinct["session_id"].tolist(), distinct["device_type"].tolist()))
    platform = dict(zip(distinct["session_id"].tolist(), distinct["platform_version"].tolist()))
    bookings_by_session = {int(row.session_id): row for row in bookings_df.itertuples(index=False)}
    sessions_by_user: dict[int, list] = defaultdict(list)
    for row in distinct.itertuples(index=False):
        sessions_by_user[int(row.user_id)].append(row)

    first_view = {"FLASH50": 0, "other": 0}
    first_co = {"FLASH50": 0, "other": 0}
    rep_view = {"FLASH50": 0, "other": 0}
    rep_co = {"FLASH50": 0, "other": 0}
    users_with_booking = {"FLASH50": 0, "other": 0}
    users_with_repeat = {"FLASH50": 0, "other": 0}
    group_users = {
        "FLASH50": int((users_df["promo_code"] == "FLASH50").sum()),
        "other": int((users_df["promo_code"] != "FLASH50").sum()),
    }

    for user_id, rows in sessions_by_user.items():
        rows.sort(key=lambda row: (row.dt, int(row.session_id)))
        bucket = "FLASH50" if promo[user_id] == "FLASH50" else "other"
        first_dt = None
        booking_dates = []
        for row in rows:
            if int(row.viewed) != 1:
                continue
            has_booking = int(row.session_id) in bookings_by_session
            if first_dt is None:
                first_view[bucket] += 1
                if has_booking:
                    first_co[bucket] += 1
                    first_dt = row.dt
                    booking_dates.append(row.dt.date())
            else:
                delta_days = (row.dt.date() - first_dt.date()).days
                if delta_days <= 90:
                    rep_view[bucket] += 1
                    if has_booking:
                        rep_co[bucket] += 1
                if has_booking:
                    booking_dates.append(row.dt.date())
        if booking_dates:
            users_with_booking[bucket] += 1
            later = [day for day in booking_dates[1:] if (day - booking_dates[0]).days <= 90]
            if later:
                users_with_repeat[bucket] += 1

    successes = int((payments_df["status"] == "success").sum())
    failures = int((payments_df["status"] == "failed").sum())
    viewed_n = int((distinct["viewed"] == 1).sum())
    booking_n = len(bookings_df)
    payment_n = len(payments_df)
    crash_n = int((bookings_df["created_ts"] == "").sum())
    android_booking_n = int(bookings_df["session_id"].map(platform).eq("android-4.2.x").sum())
    non_crash_n = booking_n - crash_n

    pay_session = bookings_df.set_index("booking_id")["session_id"]
    attempts = payments_df.copy()
    attempts["session_id"] = attempts["booking_id"].map(pay_session)
    attempts["device_type"] = attempts["session_id"].map(device)
    attempts["hour"] = attempts["attempted_ts"].map(lambda value: parse_ts(value).hour)
    a1 = attempts[
        (attempts["device_type"] == "mobile")
        & (attempts["method"] == "PromptPay")
        & (attempts["hour"].isin(NIGHT_HOURS))
    ]
    a1_fail = a1[a1["failure_reason"] == "gateway_timeout"]
    other_attempts = attempts.drop(index=a1.index)
    other_fail = other_attempts[other_attempts["status"] == "failed"]

    return {
        "hotels": N_HOTELS,
        "users": N_USERS,
        "session_rows": len(sessions_df),
        "sessions": N_SESSIONS,
        "viewed": viewed_n,
        "bookings": booking_n,
        "payments": payment_n,
        "successes": successes,
        "failures": failures,
        "search_to_view": rate(viewed_n, N_SESSIONS),
        "view_to_checkout": rate(booking_n, viewed_n),
        "checkout_to_attempt": rate(payment_n, booking_n),
        "attempt_given_non_crash": rate(payment_n, non_crash_n),
        "attempt_failure": rate(failures, payment_n),
        "baseline_failure": rate(len(other_fail), len(other_attempts)),
        "checkout_to_success": rate(successes, booking_n),
        "overall": rate(successes, N_SESSIONS),
        "revenue_per_success": (
            float(attempts.loc[attempts["status"] == "success", "amount_thb"].sum()) / successes
            if successes
            else float("nan")
        ),
        "a1_attempts": len(a1),
        "a1_failures": len(a1_fail),
        "a1_rate": rate(len(a1_fail), len(a1)),
        "a2_android_bookings": android_booking_n,
        "a2_crashes": crash_n,
        "a2_rate": rate(crash_n, android_booking_n),
        "a3_flash_users": group_users["FLASH50"],
        "a3_other_users": group_users["other"],
        "a3_first_view_flash": first_view["FLASH50"],
        "a3_first_co_flash": first_co["FLASH50"],
        "a3_first_view_other": first_view["other"],
        "a3_first_co_other": first_co["other"],
        "a3_rep_view_flash": rep_view["FLASH50"],
        "a3_rep_co_flash": rep_co["FLASH50"],
        "a3_rep_view_other": rep_view["other"],
        "a3_rep_co_other": rep_co["other"],
        "a3_users_booked_flash": users_with_booking["FLASH50"],
        "a3_users_booked_other": users_with_booking["other"],
        "a3_users_repeat_flash": users_with_repeat["FLASH50"],
        "a3_users_repeat_other": users_with_repeat["other"],
        "a4_null_device": N_NULL_DEVICE,
        "a4_utc": N_UTC_TIMESTAMPS,
        "a5_extra_rows": N_DUPLICATE_ROWS,
        "null_device_file_rows": int((sessions_df["device_type"] == "").sum()),
        "utc_file_rows": int((~sessions_df["session_start_ts"].str.endswith("+07:00")).sum()),
    }


def print_summary(stats: dict) -> None:
    def pct(value: float) -> str:
        return f"{100.0 * value:6.2f}%"

    def ratio(num: float, den: float) -> str:
        if den == 0:
            return "  n/a"
        return f"{num / den:6.3f}x"

    first_flash = rate(stats["a3_first_co_flash"], stats["a3_first_view_flash"])
    first_other = rate(stats["a3_first_co_other"], stats["a3_first_view_other"])
    rep_flash = rate(stats["a3_rep_co_flash"], stats["a3_rep_view_flash"])
    rep_other = rate(stats["a3_rep_co_other"], stats["a3_rep_view_other"])
    user_first_flash = rate(stats["a3_users_booked_flash"], stats["a3_flash_users"])
    user_first_other = rate(stats["a3_users_booked_other"], stats["a3_other_users"])
    user_rep_flash = rate(stats["a3_users_repeat_flash"], stats["a3_users_booked_flash"])
    user_rep_other = rate(stats["a3_users_repeat_other"], stats["a3_users_booked_other"])

    print("SiamStay generation summary")
    print("seed numpy=42 faker=42")
    print("")
    print("Rows")
    print(f"  hotels                          {stats['hotels']}")
    print(f"  users                           {stats['users']}")
    print(f"  sessions_file_rows              {stats['session_rows']}")
    print(f"  sessions_distinct               {stats['sessions']}")
    print(f"  viewed_sessions                 {stats['viewed']}")
    print(f"  bookings                        {stats['bookings']}")
    print(f"  payments                        {stats['payments']}")
    print(f"  payment_successes               {stats['successes']}")
    print(f"  payment_failures                {stats['failures']}")
    print("")
    print("Funnel (distinct session_id)")
    print(f"  search_to_view                  {pct(stats['search_to_view'])}  ({stats['viewed']} / {stats['sessions']})")
    print(f"  view_to_checkout                {pct(stats['view_to_checkout'])}  ({stats['bookings']} / {stats['viewed']})")
    print(f"  checkout_to_payment_attempt     {pct(stats['checkout_to_attempt'])}  ({stats['payments']} / {stats['bookings']})")
    print(f"  attempt_given_non_crash_booking {pct(stats['attempt_given_non_crash'])}")
    print(f"  payment_attempt_failure         {pct(stats['attempt_failure'])}  ({stats['failures']} / {stats['payments']})")
    print(f"  baseline_failure_excluding_a1   {pct(stats['baseline_failure'])}")
    print(f"  checkout_to_payment_success     {pct(stats['checkout_to_success'])}  ({stats['successes']} / {stats['bookings']})")
    print(f"  overall_conversion              {pct(stats['overall'])}  ({stats['successes']} / {stats['sessions']})")
    print(f"  revenue_per_successful_booking  {stats['revenue_per_success']:.2f} THB")
    print("")
    print("Injected anomalies")
    print("  A1 PromptPay + mobile + attempted hour in {22, 23, 0, 1} ICT")
    print(f"      attempts                    {stats['a1_attempts']}")
    print(f"      gateway_timeout failures    {stats['a1_failures']}")
    print(f"      failure rate                {pct(stats['a1_rate'])}  (target 22%)")
    print("  A2 platform_version android-4.2.x silent crash")
    print(f"      checkout bookings           {stats['a2_android_bookings']}")
    print(f"      blank created_ts, no payment {stats['a2_crashes']}")
    print(f"      crash rate                  {pct(stats['a2_rate'])}  (target 30%)")
    print("  A3 promo_code FLASH50")
    print(f"      users                       {stats['a3_flash_users']}")
    print(
        f"      checkout|view before first booking  flash {pct(first_flash)} "
        f"({stats['a3_first_co_flash']}/{stats['a3_first_view_flash']})  "
        f"other {pct(first_other)} ({stats['a3_first_co_other']}/{stats['a3_first_view_other']})  "
        f"ratio {ratio(first_flash, first_other)} (target 1.8x)"
    )
    print(
        f"      checkout|view within 90 days after  flash {pct(rep_flash)} "
        f"({stats['a3_rep_co_flash']}/{stats['a3_rep_view_flash']})  "
        f"other {pct(rep_other)} ({stats['a3_rep_co_other']}/{stats['a3_rep_view_other']})  "
        f"ratio {ratio(rep_flash, rep_other)} (target 0.4x)"
    )
    print(
        f"      user first-booking rate             flash {pct(user_first_flash)} "
        f"({stats['a3_users_booked_flash']}/{stats['a3_flash_users']})  "
        f"other {pct(user_first_other)} ({stats['a3_users_booked_other']}/{stats['a3_other_users']})  "
        f"ratio {ratio(user_first_flash, user_first_other)}"
    )
    print(
        f"      user 90-day repeat | first booking  flash {pct(user_rep_flash)} "
        f"({stats['a3_users_repeat_flash']}/{stats['a3_users_booked_flash']})  "
        f"other {pct(user_rep_other)} ({stats['a3_users_repeat_other']}/{stats['a3_users_booked_other']})  "
        f"ratio {ratio(user_rep_flash, user_rep_other)}"
    )
    print("  A4 dirty session extract")
    print(f"      null device_type, distinct  {stats['a4_null_device']}  (file rows {stats['null_device_file_rows']})")
    print(f"      UTC naive timestamps, distinct {stats['a4_utc']}  (file rows {stats['utc_file_rows']})")
    print("  A5 exact duplicate session rows")
    print(f"      extra copies                {stats['a5_extra_rows']}")
    print(f"      file rows                   {stats['session_rows']}")


def write_frames(users_df, sessions_df, bookings_df, payments_df, hotels_df) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        (users_df, USER_COLUMNS, RAW_DIR / "users.csv"),
        (sessions_df, SESSION_COLUMNS, RAW_DIR / "sessions.csv"),
        (bookings_df, BOOKING_COLUMNS, RAW_DIR / "bookings.csv"),
        (payments_df, PAYMENT_COLUMNS, RAW_DIR / "payments.csv"),
        (hotels_df, HOTEL_COLUMNS, RAW_DIR / "hotels.csv"),
    ]
    for frame, columns, path in targets:
        frame.loc[:, columns].to_csv(
            path,
            index=False,
            encoding="utf-8",
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )


def main() -> None:
    check_constants()
    np.random.seed(SEED)
    rng = np.random.default_rng(SEED)
    discard_faker_identities()
    hotels = build_hotels(rng)
    users = build_users(rng)
    sessions, bookings, payments = build_activity(rng, users, hotels)
    users_df, sessions_df, bookings_df, payments_df, hotels_df = frames(
        users, sessions, bookings, payments, hotels
    )
    validate(users_df, sessions_df, bookings_df, payments_df, hotels_df)
    write_frames(users_df, sessions_df, bookings_df, payments_df, hotels_df)
    print_summary(summarize(users_df, sessions_df, bookings_df, payments_df))


if __name__ == "__main__":
    main()
