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

## Account deletion

`DELETE /api/me` (Settings → Delete account) removes the user and, in one transaction, every workspace
they own: borrowers, loans, payments, receipts, invites and memberships. Where the user is only a
borrower in someone else's workspace, just the link is removed (`borrowers.user_id` → NULL) so the
lender keeps their records and can re-invite. Required by App Store guideline 5.1.1(v).

## Legal pages

Welcome and Settings link to `https://sotodev.com/lendly/privacy`, `/terms` and `/support`
(`ios/Lendly/Core/Links.swift`). Those pages must be live before submission; App Store Connect asks for
the privacy policy URL too. `ios/Lendly/PrivacyInfo.xcprivacy` declares the collected data types and the
UserDefaults required-reason API (CA92.1).

## Auth

- Email one-time code (`/api/auth/email/request` → `/verify`), delivered through Mailgun
  (`app/mailer.py`, bilingual). Locally, `DEV_RETURN_OTP=true` returns the code in the response instead.
- Sign in with Apple: the app sends the identity token, the server verifies it against Apple's
  JWKS for `APPLE_BUNDLE_ID`. Requires the capability on the App ID in the developer portal.

## Languages

The app ships in English and Spanish. Every user-facing string lives in
`ios/Lendly/Resources/Localizable.xcstrings` (String Catalog, extracted at build time from
`Text("…")` literals and the `tr("…")` helper in `Core/Lang.swift`). Settings → Language offers
*Match device language* (default: follows iOS, including the per-app language in iOS Settings),
*English* and *Español*; the choice applies immediately without relaunching. Spanish keeps US
number and currency formatting (`es_US`) since the users are in the US. The app sends
`Accept-Language`, and the API translates every error message it returns (`api/app/i18n.py`).
To add a language: add translations in the catalog, add the code to `CFBundleLocalizations` in
`ios/project.yml`, add a case to `AppLanguage`, and extend `api/app/i18n.py`.

## Render

`render.yaml` defines the API web service (`lendly-api`). The Postgres instance already exists
and is not managed by the Blueprint: **lendly-db** (`dpg-db7pa5vavr4c7392taug-a`, Postgres 16,
basic 256MB, Oregon, database `lendly_zct3`, user `lendly`). Set `DATABASE_URL` on the service
to that instance's *internal* connection string; the pre-deploy command runs `flask db upgrade`.
Nothing has been deployed or migrated on Render yet.

## Environment variables

API (`api/.env` locally, Render dashboard in production; `render.yaml` marks the secrets `sync: false`):

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Postgres URL. Locally `postgresql+psycopg://postgres@127.0.0.1:5432/lendly_dev`; on Render the **internal** connection string of `lendly-db`. `postgres://` is normalized automatically. |
| `JWT_SECRET` | yes | Signs session tokens. `render.yaml` generates it; rotate it to sign everyone out. |
| `APPLE_BUNDLE_ID` | yes | `com.sotodev.lendly` — audience for Sign in with Apple token verification. |
| `DEV_RETURN_OTP` | no | `true` returns the email login code in the API response. **Must be unset/false in production.** |
| `MAILGUN_API_KEY` | prod | Mailgun private API key (same account as the emailer project). |
| `MAILGUN_DOMAIN` | prod | Sending domain, e.g. `mg.sotodev.com`. |
| `MAILGUN_FROM` | prod | Sender, e.g. `Lendly <no-reply@sotodev.com>`. |
| `MAILGUN_BASE_URL` | no | `https://api.mailgun.net` (default) or `https://api.eu.mailgun.net`. |
| `INVITE_LINK_BASE` | no | Prefix for invite links; default `lendly://invite`. |
| `OTP_TTL_MINUTES`, `JWT_TTL_DAYS`, `INVITE_TTL_DAYS` | no | Defaults 10 / 90 / 14. |
| `OTP_REQUEST_LIMIT`, `OTP_REQUEST_WINDOW_MINUTES`, `OTP_IP_LIMIT` | no | Login-code abuse limits: codes per **mailbox** per window (3 / 10 min; Gmail dots and `+tags` collapse to one mailbox, counted under an advisory lock) and requests per client IP per window (20; in-memory, per worker; the IP is the last `X-Forwarded-For` hop, so confirm Render appends the client address before relying on it). Over the limit → 429 `too_many_requests`. |
| `REVIEW_LOGIN_EMAIL`, `REVIEW_LOGIN_CODE` | review | App Review demo account: that address always receives that fixed code and nothing is e-mailed, so Apple's reviewers can sign in without an inbox. Set both (code **8–12 digits**, enforced at startup) and put them in the App Review notes; unset = disabled. Use an address nobody else owns. If a reviewer deletes the demo account, re-seed it. |
| `PORT` | no | Local dev server port (5050). Render sets its own. |

Without Mailgun configured and with `DEV_RETURN_OTP` off, email sign-in returns 503 `email_unavailable`
instead of silently failing.

iOS has no `.env`: the production API URL is the Release value of `APIClient.baseURL`
(`https://lendly-api.onrender.com`, change it if Render assigns a different hostname), Debug builds use
`http://127.0.0.1:5050` or the override in Settings → Developer. Sign in with Apple needs the capability
enabled on the App ID in the Apple Developer portal.

## TestFlight

`scripts/testflight.sh` archives a signed Release build (team `TZZNAY63L5`, automatic signing,
build number = git commit count) and uploads it to App Store Connect. It needs either Xcode signed
in with the team's Apple ID, or an App Store Connect API key exported as `ASC_KEY_PATH`,
`ASC_KEY_ID`, `ASC_ISSUER_ID` (see the script header). The first upload registers the App ID with
the Sign in with Apple capability and creates the app record. Release builds talk to the URL in
`APIClient.baseURL`, so deploy the API first or testers will see "Can't reach Lendly".

## Not done / known gaps

- No push notifications or reminders for due dates.
- Sign in with Apple was not exercised end to end (needs a signed-in Apple ID + paid team). Account
  deletion removes our user row but does not call Apple's token-revocation endpoint yet.
- Mailgun delivery is unit-tested against a fake transport, not sent for real (no key on this machine).
- The legal pages linked from the app (privacy, terms, support) still have to be published.
- iPad is enabled and works, but it is the phone layout stretched to full width.
