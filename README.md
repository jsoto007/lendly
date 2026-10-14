# Lendly

Native iOS app (SwiftUI, iOS 26) plus a Flask + Postgres API for tracking money you lend to
people. A lender ("admin") creates a workspace, adds borrowers, gives out loans with compound,
flat-percentage or fixed-dollar interest, records every payment (each one becomes a numbered
receipt), and can invite each borrower to a read-only view of their own loans and receipts.

```
api/   Flask 3 · SQLAlchemy 2 · Alembic · PyJWT · pytest     → Render (render.yaml)
ios/   SwiftUI · Swift 6 · XcodeGen project spec (project.yml) → Xcode 26 / TestFlight
```

## Run it locally

Backend (needs local Postgres on 5432):

```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # DEV_RETURN_OTP=true returns login codes in the API response
createdb -h 127.0.0.1 -U postgres lendly_dev
FLASK_APP=wsgi.py .venv/bin/flask db upgrade
.venv/bin/python seed.py                  # demo lender + borrowers + loans (local DB only)
.venv/bin/python wsgi.py                  # http://127.0.0.1:5050
```

iOS:

```bash
cd ios
xcodegen generate                         # brew install xcodegen
open Lendly.xcodeproj                     # run the Lendly scheme on an iOS 26 simulator
```

Sign in with **Continue with Email** using `lender@lendly.test`; the 6-digit code is shown in
the sheet in Debug builds. Debug builds talk to `http://127.0.0.1:5050` (override in Settings →
Developer). Release builds use the URL in `APIClient.baseURL`.

Tests:

```bash
cd api && createdb -h 127.0.0.1 -U postgres lendly_test; .venv/bin/python -m pytest
cd ios && xcodebuild -project Lendly.xcodeproj -scheme Lendly -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

## How the money math works

All amounts are integer cents; rates are basis points. The schedule engine lives in
`api/app/services/schedule.py` and the API is the single source of truth (the loan form calls
`POST /api/loans/preview` for live numbers).

| Interest type | Meaning | Installments |
|---|---|---|
| `compound` | `rate_bps` per period on the unpaid balance; accrues at every period end, keeps accruing past the term while a balance remains | amortized payment, final one absorbs rounding |
| `simple` | flat `rate_bps` of principal, charged once | `(principal + interest) / n`, remainder cents on the first installments |
| `fixed` | `fixed_fee_cents` once, or every period when `fixed_fee_per_period` | `(principal + fees) / n` |

Schedules: `weekly` (7 days), `biweekly` (14 days), `monthly` (same day next month, clamped).
Installment *k* is due at the end of period *k*.

Day semantics ("today" = the lender's device date, sent as `X-Local-Date`, clamped to ±2 days of
server time): a compound period's interest is charged on its due date and a payment dated on
the due date is applied after that charge. An installment is **overdue** only once its due date
has passed, so the borrower has the whole due day; one due today is "next". **Upcoming** is the
next installment within 30 days. Cancelled loans are frozen (nothing due or overdue).

Payments: amount must be > 0, dated between the loan start and today, and must fit the balance
owed on that date; after insertion every live payment is replayed in date order and the request
is refused if the loan would end up overpaid (matters for back-dated compound payments). Each
payment takes the next per-tenant receipt number via an atomic `UPDATE … RETURNING` under the
loan's row lock and snapshots balance before/after as of the payment date. The client sends an
`idempotency_key` per attempt so a retried request returns the existing payment instead of a
duplicate. Payments are never deleted: they are **voided** (kept in history, receipt shows VOID,
balance restored); voided receipts can't be edited. Loan terms are locked once a live payment
exists (the loan row is locked for term edits, so a payment can't slip in underneath), and a
loan with live payments can't be cancelled (void first). Cents columns are `BigInteger`; inputs
are capped at $1B and 100% per period.

## Multi-tenancy

`tenants` = one lender workspace. `memberships` link users to tenants with role `admin` or
`borrower` (a borrower membership points at its `borrowers` row). Every tenant-scoped request
sends `X-Tenant-Id`; the server checks membership + role and borrowers can only read their own
loans/receipts, and never see the lender's private notes. Invites are 8-char codes
(`lendly://invite/CODE` deep link also works); a user can be linked to one borrower profile per
workspace.

## Auth

- Email one-time code (`/api/auth/email/request` → `/verify`). Email delivery is not wired yet:
  in dev the code is returned in the response. Production needs a mail provider in
  `app/auth.py::create_email_code` (Mailgun via the emailer project is the obvious choice).
- Sign in with Apple: the app sends the identity token, the server verifies it against Apple's
  JWKS for `APPLE_BUNDLE_ID`. Requires the capability on the App ID in the developer portal.

## Render

`render.yaml` defines the API web service (`lendly-api`). The Postgres instance already exists
and is not managed by the Blueprint: **lendly-db** (`dpg-db7pa5vavr4c7392taug-a`, Postgres 16,
basic 256MB, Oregon, database `lendly_zct3`, user `lendly`). Set `DATABASE_URL` on the service
to that instance's *internal* connection string; the pre-deploy command runs `flask db upgrade`.
Nothing has been deployed or migrated on Render yet.

## Not done / known gaps

- No push notifications or reminders for due dates.
- Email delivery of login codes (see above).
- App icon is a placeholder (asset catalog slot is wired, no artwork).
- Sign in with Apple was not exercised end to end (needs a signed-in Apple ID + paid team).
