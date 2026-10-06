# Product Requirements Document: Project SiamStay

**Phase 1 — measurement contract.** Status: approved for the synthetic extract. Date: 6 October 2026.

## 1. Context

SiamStay is a Southeast Asia online travel agency. Checkout is priced in Thai baht. In Q3 2026 (1 July–30 September) site sessions grew about 12% versus the prior quarter, while gross bookings stayed flat. Product and payments suspect friction at the payment step, concentrated on mobile wallets. Phase 1 does not decide that question. It freezes the definitions, the grain, and a fully synthetic extract so a later analysis can.

The business phrase **gross bookings** means collected booking value: the sum of `amount_thb` on payments with `status = success`. It is not the count of booking rows, and it is not the sum of `gross_amount_thb` on unpaid checkouts.

## 2. Objective

Ship a measurement contract and a deterministic synthetic extract that let an analyst do three things:

1. Quantify drop-off across Search → View → Checkout → Payment Success.
2. Isolate that drop-off by device and by payment method, so the mobile-wallet hypothesis can be confirmed or rejected with rates and volumes.
3. Measure 90-day repeat-booking retention by signup cohort and by acquisition channel.

Phase 1 stops at the raw files and their documentation. The readout itself is a later phase.

## 3. Personas

Personas are product lenses. The extract has no persona column; behavior has to show up through device, lead time, stay length, hotel class, channel, and payment method.

**Last-Minute Business Traveler.** Books inside a few days of check-in, usually for one or two nights, and leans toward upscale hotels. Often on desktop between meetings. A failed payment is a lost trip, not a postponed one. The KPI that matters is checkout-to-payment-success, split by device and method, plus revenue per successful booking.

**Budget Backpacker.** Mobile-first, longer stays, lower hotel class, and more responsive to promo codes and paid social. Compares several properties before checkout, so view-to-checkout can look weak even when search-to-view is healthy. Retention matters because a promo that buys the first booking can still destroy the second one.

**Weekend Family Planner.** Plans one to eight weeks ahead, travels two to four nights, and prefers a Friday or Saturday check-in at a mid-scale hotel. Mixes phone and desktop. Comparison shopping shows up as view-to-checkout loss. A 90-day repeat window is a high bar for this persona, because the next trip is often a term later, so a low repeat rate here is not automatically a product failure.

## 4. KPI definitions

All rates use a **cleaned session grain**: one row per `session_id`, timestamps normalized to ICT (UTC+7, no daylight saving). Stages map to the extract as follows. Search is a session. View is `sessions.viewed = 1`. Checkout is a row in `bookings` (at most one per session). Payment success is a row in `payments` with `status = success` (at most one attempt per booking).

Observation window for sessions: 1 January 2026 through 31 December 2026 ICT. A first success on or before **2 October 2026** has a full 90 days of follow-up before the extract ends; later first successes are immature and are excluded from the repeat-rate denominator.

| KPI | Formula | Grain |
| --- | --- | --- |
| Search-to-View Rate | `viewed sessions / sessions` | Distinct `session_id` |
| View-to-Checkout Rate | `sessions with a booking / viewed sessions` | Distinct `session_id` |
| Checkout-to-Payment-Success Rate | `bookings with a successful payment / bookings` | Booking |
| Overall Conversion | `sessions with a successful payment / sessions` | Distinct `session_id` |
| 90-day Repeat Booking Rate | `mature users with a later success within 90 days / mature users with a first success` | User |
| Revenue per Successful Booking | `sum(amount_thb where status = success) / count(status = success)` | Successful payment, THB |

**90-day Repeat Booking Rate, operationally.** Let the first success be the earliest payment with `status = success` for that user, ordered by `attempted_ts` in ICT. A user is mature when that timestamp’s ICT date is on or before 2 October 2026. The user counts in the numerator when another successful payment for the same user has an ICT date at least one day later and at most 90 days later. Report the rate by signup-month cohort (`users.signup_date` truncated to month) and by `users.acquisition_channel`. Session `utm_source` is a different cut (campaign of the visit, not how the user was acquired) and is not this KPI.

Device cuts use `sessions.device_type`. Payment-method cuts use `payments.method`. Both cuts are required for checkout-to-payment-success and for payment-attempt failure (`status = failed` divided by payment rows). Failure rate is not one of the six headline KPIs, but it is the direct test of the wallet hypothesis.

## 5. Scope

- This PRD, the data dictionary, and the private answer key.
- A deterministic generator and the raw CSV extract for users, sessions, bookings, payments, and hotels.
- Fixed seeds so a second run is byte-identical on the pinned stack.
- Synthetic identities only. The published schema has no name and no email.

## 6. Out of scope

- ETL, warehouse tables, and database load. That is Phase 2. Do not build them in Phase 1.
- Dashboards, the executive readout, and experiment design.
- Refunds, cancellations, booking modifications, multi-currency, and live inventory.
- Production instrumentation and any real customer data.
- A persona label, a household key, or identity resolution beyond `user_id`.

## 7. Stakeholders

| Stakeholder | Needs from this measurement |
| --- | --- |
| Head of Product | A single funnel, with device and payment-method cuts, that can explain flat gross bookings. |
| Payments lead | Failure rate by method, device, and hour, with `failure_reason` left intact. |
| Growth | Repeat rate by signup cohort and acquisition channel, separate from session `utm_source`. |
| Finance | Gross bookings and revenue per successful booking defined on successful payments only, in integer THB. |
| Data engineering | A raw contract: grains, keys, blank-field nulls, ICT timestamps, and a deduplicated session grain. |

## 8. Success criteria

Phase 1 is done when all of the following are true:

1. Each KPI above can be computed from the raw files using only the formulas in this PRD and the columns in the data dictionary.
2. Checkout-to-payment-success and payment failure can be split by `device_type` and by `method`.
3. The 90-day repeat rate can be split by signup month and by `acquisition_channel`, with immature users removed as defined above.
4. Re-running the generator on the pinned versions in `requirements.txt` produces byte-identical CSVs.
5. The mobile-wallet hypothesis can be answered with a rate gap and a count of affected payment attempts, not with an anecdote.
6. No real personal data appears anywhere in the extract.
