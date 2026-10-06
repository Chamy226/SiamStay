# SiamStay Data Dictionary

**Phase 1 raw extract.** All files are synthetic. Nulls are empty CSV fields, never the tokens `NULL`, `NaN`, or `None`.

Money columns are integer Thai baht (no satang, no currency column). Dates are `YYYY-MM-DD`. Timestamps that follow the contract are ISO-8601 with an explicit ICT offset, `YYYY-MM-DDTHH:MM:SS+07:00`. ICT is UTC+7 and does not observe daylight saving. The session window is 1 January 2026 through 31 December 2026. Signup dates run from 1 July 2025 through 15 December 2026. Check-in dates may fall after the session, including into 2027.

Logical model: a **search** is one session; a **view** is `sessions.viewed = 1`; a **checkout** is one booking row; a **payment attempt** is one payment row. This extract has at most one booking per session and at most one payment attempt per booking. `payments.amount_thb` equals `bookings.gross_amount_thb` for that attempt. Failed attempts still carry the attempted amount; they are not revenue.

`sessions.viewed` is the only column beyond the brief. It is required so Search-to-View is observable. There is no separate event table.

Metrics that count searches or views must use **distinct** `session_id`. Deduplicate the session extract before measuring.

## users

One row per traveler account. File: `data/raw/users.csv`. 20,000 rows.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `user_id` | integer | no | PK | Surrogate account id. |
| `signup_date` | date | no | | Calendar date the account was created. Cohort month is this date truncated to `YYYY-MM`. |
| `country` | string | no | | ISO 3166-1 alpha-2 country of the account. Domain below. |
| `acquisition_channel` | string | no | | How the account was acquired. This is the channel cut for the repeat-rate KPI. It is not `sessions.utm_source`. |
| `promo_code` | string | yes | | Promo attached to the account. Blank if the account has none. |

**`country`:** `TH`, `SG`, `MY`, `ID`, `VN`, `PH`, `KH`, `LA`, `MM`, `AU`, `JP`, `KR`.

**`acquisition_channel`:** `organic`, `paid_search`, `paid_social`, `affiliate`, `email`, `direct`.

**`promo_code`:** blank, `FLASH50`, `WELCOME10`, `SUMMER25`.

Example (illustrative): `1042,2026-03-18,TH,paid_search,FLASH50`

## sessions

One intended row per search session. File: `data/raw/sessions.csv`. 60,000 distinct sessions. The raw file is an extract: deduplicate on `session_id` before treating the key as unique.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `session_id` | integer | no | PK (logical) | Search-session identifier. |
| `user_id` | integer | no | FK → `users.user_id` | Account that started the session. Session start is always on or after `signup_date`. |
| `session_start_ts` | string | no | | Session start. Contract form is ICT with a `+07:00` offset. |
| `device_type` | string | yes | | Client class. Blank when the client did not report a device. |
| `platform_version` | string | no | | App or web version string reported with the session. |
| `utm_source` | string | no | | Campaign source of this visit. Not the user’s acquisition channel. |
| `viewed` | integer | no | | `1` if the session opened a hotel listing, else `0`. |

**`device_type`:** `mobile`, `desktop`, `tablet`, or blank.

**`platform_version`:** `ios-18.2`, `ios-17.6`, `android-15.1`, `android-14.8`, `android-4.2.x`, `web-3.4.1`, `web-3.3.0`.

**`utm_source`:** `google`, `facebook`, `instagram`, `tiktok`, `line`, `email`, `direct`, `affiliate`, `organic`.

Example (illustrative): `88001,1042,2026-08-14T23:17:04+07:00,mobile,android-15.1,google,1`

## bookings

One row per checkout that wrote a booking. File: `data/raw/bookings.csv`. Volume is a result of the funnel, not a fixed insert.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `booking_id` | integer | no | PK | Surrogate booking id. |
| `session_id` | integer | no | FK → `sessions.session_id` | Session that checked out. At most one booking per session. |
| `user_id` | integer | no | FK → `users.user_id` | Must match the session’s `user_id`. |
| `hotel_id` | integer | no | FK → `hotels.hotel_id` | Property booked. |
| `checkin_date` | date | no | | Stay start. On or after the session’s ICT date. |
| `nights` | integer | no | | Length of stay, at least 1. |
| `gross_amount_thb` | integer | no | | Quoted booking value in THB, before knowing whether payment succeeded. |
| `created_ts` | string | yes | | Checkout timestamp, ICT with `+07:00`. Blank when the row was written without a timestamp. |

Example (illustrative): `501,88001,1042,88,2026-08-16,2,6400,2026-08-14T23:24:11+07:00`

## payments

One row per payment attempt. File: `data/raw/payments.csv`. There are no retries in this extract.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `payment_id` | integer | no | PK | Surrogate attempt id. |
| `booking_id` | integer | no | FK → `bookings.booking_id` | Booking this attempt charges. At most one attempt per booking. |
| `method` | string | no | | Instrument the traveler used. |
| `status` | string | no | | `success` or `failed`. |
| `attempted_ts` | string | no | | Attempt time, ICT with `+07:00`. Hour-of-day cuts use this column, not the session start. |
| `failure_reason` | string | yes | | Blank when `status = success`. Populated when `status = failed`. |
| `amount_thb` | integer | no | | Attempted amount. Equal to the booking’s `gross_amount_thb`. Counts as revenue only when `status = success`. |

**`method`:** `PromptPay`, `credit_card`, `debit_card`, `TrueMoney`, `GrabPay`, `ShopeePay`, `bank_transfer`.

**`failure_reason`:** `card_declined`, `insufficient_funds`, `user_cancelled`, `otp_timeout`, `bank_rejected`, `gateway_timeout`.

Example (illustrative): `900,501,PromptPay,failed,2026-08-14T23:26:02+07:00,gateway_timeout,6400`

## hotels

One row per property. File: `data/raw/hotels.csv`. 800 rows.

| Column | Type | Null | Key | Description |
| --- | --- | --- | --- | --- |
| `hotel_id` | integer | no | PK | Surrogate property id. |
| `city` | string | no | | City or destination name. |
| `district` | string | no | | Area inside the city. |
| `star_rating` | integer | no | | Official class from 2 to 5. |
| `avg_price_thb` | integer | no | | Typical nightly rate in THB. Booking gross is built from this rate, nights, and a small spread. It is not a live availability price. |

**`city`:** Bangkok, Chiang Mai, Phuket, Pattaya, Krabi, Koh Samui, Hua Hin, Singapore, Bali, Kuala Lumpur, Penang, Ho Chi Minh City, Hanoi, Da Nang, Hoi An, Jakarta, Yogyakarta, Siem Reap.

Example (illustrative): `88,Bangkok,Sukhumvit,4,3200`

## Relationships

- `sessions.user_id` → `users.user_id`
- `bookings.session_id` → `sessions.session_id`
- `bookings.user_id` → `users.user_id` (same account as the session)
- `bookings.hotel_id` → `hotels.hotel_id`
- `payments.booking_id` → `bookings.booking_id`

A booking is only created for a session with `viewed = 1`. A payment is only created for a booking whose `created_ts` is populated.
