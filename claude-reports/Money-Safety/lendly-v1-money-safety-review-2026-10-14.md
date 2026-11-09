## Money-safety review: Lendly v1 (loan math, payments, receipts, voids) — 2026-10-14 — uncommitted working tree

Scope: new app, so every layer is in scope: `api/app/services/schedule.py` (schedule / balance
math), `api/app/routes/payments.py` (record, void, edit, receipts, idempotency),
`api/app/routes/loans.py` (create / preview / edit / cancel / delete), `api/app/serializers.py`,
`api/app/routes/dashboard.py`, `api/app/routes/borrower_portal.py`, auth + tenancy in
`api/app/auth.py` / `routes/me.py`, and the iOS client (`ios/Lendly/**`). No payment provider:
money is recorded, not moved.

### Verified by execution
- `api`: `.venv/bin/python -m pytest -q` — **38 passed, 0 failed** (local Postgres `lendly_test`).
  Includes `tests/test_schedule.py` (13 pure-math cases), `tests/test_api.py` (6 end-to-end
  flows: tenant isolation, borrower read-only portal, receipts, voids, dashboard),
  `tests/test_concurrency.py` (2 real multi-thread races) and `tests/test_review_fixes.py`
  (17 regressions, one per review finding below).
- Concurrency, actually fired: two simultaneous $60 payments on a $100 loan → exactly one 201
  and one 422 `exceeds_balance`; four simultaneous $10 payments → receipts 1,2,3,4, balances
  chained 10000→9000→8000→7000; PATCH terms racing a payment → either the payment lands on the
  new terms or the PATCH is refused 409, never a silent rewrite; two simultaneous voids → one
  200, one 409.
- iOS: `xcodebuild … test` — **5 passed** (money formatting, rounding, date parsing, DTO decode).
  Driven in the iPhone 17 Pro simulator against the live local API: email-code sign-in,
  dashboard, borrower detail, invite creation, loan creation with live server preview, payment
  recording (receipt R-00008, PDF written and opened: 1 page, balances before/after correct),
  sign-out, borrower sign-in + invite acceptance, read-only portal, borrower receipt view.
- Worked examples (hand-traced, match code and screen):
  - Simple: $1,000 at 10% flat, 4 monthly from Jan 31 → $1,100 = 4 × $275.00, due Feb 28,
    Mar 31, Apr 30, May 31 (month-end clamping from the start date, no drift).
  - Compound: $800 at 3% per 2 weeks, 6 installments, paid $140 at the first two period ends,
    nothing at the third → balance after three periods $572.67, overdue $163.04 (3 × $147.68
    expected − $280 paid), amortized installment $147.68, total interest $86.07.
  - Compound amortized $1,000 at 2% × 4: installments 26262, 26262, 26262, 26264; paying each
    exactly on its due date retires the raw balance to **exactly 0** (regression test).
  - Fixed: $1,500 + $25 per week × 10 → $1,750 = 10 × $175.00.

### Not verified locally
- Sign in with Apple — needs a paid team + signed-in Apple ID on device; server-side JWKS
  verification is implemented but was not exercised. Email-code path is the verified one.
- Email delivery of login codes — not wired (dev mode returns the code in the response).
- Render deploy (`render.yaml`) — written, not deployed (user's rule: deploys need explicit OK).
- Device-date header under a real UTC server — covered by a unit test that spoofs the header,
  not by running the API in a UTC container.

### Findings (all fixed in this session, each with a regression test)
**High**
- Compound payment dated ON a due date was applied before that period's interest, so paying on
  the due date erased the period's interest (e.g. $1,000 at 10%: pay $1,000 on Feb 28 → balance
  0 instead of $100). Fix: payments dated before the period end apply before accrual, on the
  end date after it (`schedule.py::_compound_balance`).
- `PATCH /loans/<id>` and `DELETE` read the loan without the row lock `record_payment` takes,
  so terms could be rewritten under a concurrent payment (reproduced: principal rewritten to
  $100 while a $500 payment landed; status stale). Fix: `FOR UPDATE` + refresh in both routes.

**Medium**
- Back-dated compound payment was validated against today's balance, so an amount larger than
  what was owed on `paid_on` was accepted and the receipt showed balance 0 with $50 over-collected.
  Fix: validate against the balance on `paid_on`, snapshot before/after as of `paid_on`, and
  after insertion replay every live payment; refuse (422, rollback) if the raw balance goes negative.
- Loans with live payments could be cancelled, making collected money vanish from the dashboard
  and the borrower's portal. Fix: 409 `has_payments` on cancel; cancelled loans are frozen
  (no overdue / next due; installments `cancelled`); borrowers get 404 for cancelled loans.
- No idempotency on `POST /payments` — a mobile retry recorded the payment twice. Fix:
  `idempotency_key` column (unique per tenant); the iOS form generates one per attempt; a retry
  returns the existing payment with 200.
- Lender's private notes (borrower.notes, loan.notes) were returned to the borrower. Fix:
  serializers blank `notes` unless the viewer's membership is `admin`.
- Cents columns were int32 and inputs uncapped: $21.5M principal → 500; a delinquent compound
  loan could overflow and become unpayable. Fix: `BigInteger` (migration `034ebc173dae`),
  caps of $1B per amount and 100% per period, accrual stops at $100B so Decimal never overflows.
- Accepting a second invite in the same tenant re-linked the user and orphaned the first
  borrower profile (no way to re-invite). Fix: 409 `already_linked`.
- `progress` reported 100% and every installment `paid` while late compound interest remained.
  Fix: progress = paid / (paid + balance); last installment shows as partially overdue.
- All "today" logic used server-local date; on Render (UTC) a New York lender after 8pm would
  get tomorrow's dates. Fix: client sends `X-Local-Date`, server uses it when within ±2 days.
- Due-day semantics: an installment was overdue at 00:00 on its due date. Fix: overdue only
  once the due date has passed; due today is "next"/"upcoming".
- iOS: editing title/notes of a loan with payments always failed (client resent unchanged terms,
  server treats any term key as a change). Fix: locked loans send only title/notes.

**Low (fixed)**
- Double-void race (both 200) → lock before the voided check. `archived: "false"` archived the
  borrower → strict bool. `?limit=abc` → 500 → 422. `start_date: null` on PATCH reset to today →
  null means "keep". Archived borrowers could get loans/invites → 409. Voided receipts were
  editable → 409. Offline launch dropped into workspace setup (duplicate-workspace risk) →
  explicit offline screen with retry. Expired JWT mid-session never returned to sign-in →
  401 handler signs out. Switching between two borrower workspaces kept stale data → view keyed
  by membership. Timestamps displayed as UTC calendar day → parsed and shown in local time.
  Void date/reason missing from the shared PDF → moved into the receipt card. Currency text
  field reformatted on each keystroke ("500" → $5.00) → raw decimal field.

### Adversarial pass (independent agent, scratch tests only, 23 attack tests + 3,000-case fuzz)
Survived (verified, no change needed): due-date payment ordering (fuzz over all schedules incl.
Jan 31 / Feb 29 starts, split same-day payments, no post-term accrual on a retired loan);
PATCH/DELETE/cancel/void races against payments (never a silent term rewrite); cancel guard and
frozen cancelled state; notes hidden on every borrower-reachable endpoint; caps on every money
field (no Decimal overflow reachable); `X-Local-Date` cannot push a payment or overdue state
more than 2 days.

Refuted and then fixed in a second pass (each with a regression test, suite now 44 passed):
- **High** — `start_date: 9999-12-31` raised inside date math after the loan was committed, so
  one bad loan made every list/dashboard endpoint 500 for the tenant. Fix: `validate_terms`
  bounds the start year (2000–2100) and proves the schedule is computable; `create_loan`
  serializes before commit.
- **Medium** — idempotency key was scoped to the tenant only: the same key on another loan
  returned the first loan's payment with 200; concurrent reuse across loans → 500; a voided
  payment's key returned the voided row. Fix: key scoped to loan + live payments, different
  amount/date → 409 `idempotency_conflict`, duplicate-key errors at flush/commit answered like a
  retry, voiding frees the key.
- **Medium** — back-dated compound payments were checked and snapshotted against a balance
  that already subtracted later-dated payments, so valid amounts were refused with a wrong
  "owed on that date" and receipts read net of later payments. Fix: the as-of-`paid_on` state
  uses only payments dated on or before `paid_on`; the replay-at-today check remains the
  overpay gate.
- **Low** — `void_reason` was visible to borrowers → admin-only. Concurrent accept of two
  invites → 500 → user row locked + 409.
Refuted on challenge (no bug): tiny principals ending with 0-cent installments (rounding
artifact); accrual stop after 1,200 periods (~23 years weekly).

### Verdict
**SAFE TO SHIP for v1 as a lender's record-keeping tool**, given: every finding from three
review lenses and the adversarial pass is fixed with a regression test (44 backend tests, 2
real race tests, 5 iOS tests, full simulator walk-through of lender and borrower flows). Not
verified: Sign in with Apple end to end, email delivery of login codes, and the API under a
UTC server clock (covered by the header unit test only). No money moves through the system;
the risk is record accuracy, which is what the tests pin down.
