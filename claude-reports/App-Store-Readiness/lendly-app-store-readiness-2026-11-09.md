# Lendly — App Store readiness audit — 2026-11-09

Scope: can Lendly v1 be submitted to the App Store, do the user workflows make sense, and does everything actually run.
Commit reviewed: `59108d8` on `feature/lendly-v1` (7 ahead of `origin/main`, 0 behind; PR jsoto007/lendly#1 open).
Working tree had two uncommitted changes (deleted `claude-reports/Money-Safety/…2026-10-14.md`, regenerated `ios/Lendly/Info.plist`).
Method: ran the API test suite, built and launched the iOS app on iPhone 17 Pro and iPad Pro 13" simulators against a local API,
ran a 69-call scripted end-to-end pass against the API, read every route and SwiftUI screen, checked submission requirements
against Apple's current rules. Report-only: no code was changed.

## Verdict

**Not ready to submit.** The app itself is in good shape: 50/50 API tests and 5/5 iOS tests pass, the simulator build runs, and every
lender workflow exercised (sign in, dashboard, loan detail, record payment, receipt + PDF, void, new loan with live preview, borrowers,
invite code, Spanish) behaved correctly with balances that match the database. What blocks submission is around the app, not in it:
(1) the production API is not deployed, so a Release build cannot work for anyone; (2) there is no account-deletion flow, which App
Review requires for any app with sign-up; (3) the privacy manifest Apple now requires for UserDefaults use is missing, so the upload itself
is at risk. Behind those: Mailgun is unset in production (email sign-in returns 503), Sign in with Apple has never been exercised, and
there is no privacy policy or reviewer demo account.

## Findings

| # | Sev | Area | Finding | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | Critical | Backend / ops | Production API is not deployed. The Release build hardcodes `https://lendly-api.onrender.com`; that host does not answer. Every real install shows "Can't reach Lendly" on first launch. | `curl https://lendly-api.onrender.com/health` → timeout after 15 s, 0 bytes (twice). `ios/Lendly/Core/APIClient.swift:25`. README "Render" section: "Nothing has been deployed or migrated on Render yet." | Deploy the Blueprint (`render.yaml`), set `DATABASE_URL` to lendly-db's internal URL, confirm `flask db upgrade` ran, verify `/health`. Needs your explicit OK (outward action). |
| 2 | Critical | App Review 5.1.1(v) | No way to delete an account. Apps that let users create accounts must offer in-app account deletion. There is no API route and no Settings control. | e2e: `DELETE /api/me` → 405 `method_not_allowed`. `api/app/routes/me.py` has only GET/PATCH `/me`. `SettingsView.swift` has Sign out only. | Add `DELETE /api/me` (remove or anonymize user, memberships, OTP rows; decide policy for tenants the user owns) + a destructive "Delete account" row in Settings with confirmation. |
| 3 | High | Submission | Missing `PrivacyInfo.xcprivacy`. The app uses `UserDefaults`, a "required reason" API; since May 2024 App Store Connect rejects uploads that do not declare it (ITMS-91053). | `find ios -name '*.xcprivacy'` → none. Usage: `Core/Session.swift:66,79,85`, `Core/APIClient.swift:22`, `Core/Lang.swift:25,29`, `Features/Settings/SettingsView.swift:13` (`@AppStorage`). | Add `ios/Lendly/PrivacyInfo.xcprivacy` declaring `NSPrivacyAccessedAPICategoryUserDefaults` with reason `CA92.1`, plus collected-data types (email, name, financial info, contacts of third parties). Wire it in `project.yml`. |
| 4 | High | Auth / ops | Email sign-in is unusable in production until Mailgun is configured; the API returns 503. Mailgun delivery has never been sent for real. | `render.yaml` marks `MAILGUN_API_KEY` / `MAILGUN_DOMAIN` `sync: false` (unset). `api/app/routes/auth.py:30-32` returns `503 email_unavailable` when unconfigured and `DEV_RETURN_OTP` is false. `tests/test_mailer.py` uses a fake transport. | Set the Mailgun key + domain on the Render service (dashboard), then send one real code to your own inbox before submitting. |
| 5 | High | Auth | Sign in with Apple has never been exercised end to end (needs the capability on the App ID and a real device). If it fails at review the app is rejected, since it is the headline button. | README "Not done"; `WelcomeView.swift:33-40`; server verifies audience `APPLE_BUNDLE_ID` (`api/app/auth.py:134-147`). | Enable the capability for `com.sotodev.lendly` in the developer portal, test on a device against the deployed API. |
| 6 | High | App Review 2.1 | Reviewers have no way in. Login is email one-time-code or Apple; a reviewer cannot read a code sent to a demo inbox they do not own. | `EmailCodeView.swift` only path; `DEV_RETURN_OTP` must be false in prod. | Provide App Review a demo lender account whose code is deterministic (e.g. an allow-listed review address with a fixed code, server-side), with seeded demo data; or document that Sign in with Apple creates a usable empty workspace. |
| 7 | Medium | Legal / metadata | No privacy policy or terms anywhere; App Store Connect requires a privacy policy URL and App Privacy labels. The welcome footer is a joke line, not a notice. The app stores third parties' names, phones and emails (borrowers) plus loan amounts. | `WelcomeView.swift:55` "By continuing you agree to keep your records honest…". `grep -ri "privacy\|terms"` → none. | Publish a privacy policy + terms page (sotodev.com), link both from Welcome and Settings, fill App Privacy labels (Contact info, Financial info, User content, Identifiers). |
| 8 | Medium | Security | No rate limit on code requests: anyone can trigger unlimited emails to any address (Mailgun cost, harassment vector). Verification is capped (5 attempts) but requests are not. | `api/app/routes/auth.py:25-44` (no throttle); `api/app/auth.py:116-119` caps attempts only. | Per-email and per-IP throttle (e.g. 3 requests / 10 min) before `create_email_code`. |
| 9 | Medium | UX | Loan rows truncate the one thing the lender needs: "Maria Lopez · $137.5…", "Nina Patel · $700….", dashboard "Rent gap · 20 days la…". The iPad shows the full text ("$137.50 due In 5 days"), so it is a width issue on iPhone. | Simulator screenshots, Loans tab and Dashboard "Needs attention". `LoanRow` in `Design/Components.swift`, dashboard row `DashboardView.swift:62`. | Let the subtitle wrap to 2 lines or drop the borrower name when it collides with the amount column. Also "due In 5 days" → "due in 5 days". |
| 10 | Medium | UX | The rate / amount fields only focus when you hit the ~44 pt number itself; tapping the row label does nothing. Reproduced twice in the simulator (typed "10", field stayed at 0 %). | `Design/DecimalField.swift:24-26` (`fixedSize(horizontal: true)`, `frame(minWidth: 44)`), used in `LoanFormView.swift:70,88,150`. | Make the whole row tappable (`contentShape` + focus on tap) or let the TextField take the trailing width. |
| 11 | Low | iPad | iPad is enabled (`TARGETED_DEVICE_FAMILY 1,2`, all orientations) and works in portrait and landscape, but it is the phone layout stretched to full width. Shipping iPad also means iPad screenshots in App Store Connect. | iPad Pro 13" simulator: Welcome, sign-in, Dashboard (both orientations), Loans, Borrower detail, Settings all rendered. `ios/project.yml` target settings. | Either accept as-is or set device family to iPhone-only for v1. |
| 12 | Low | UX | Changing language rebuilds the whole view tree and drops the user from Settings back onto the Dashboard tab. | `App/LendlyApp.swift:13` `.id(lang.choice)`; observed on iPad after choosing Español. | Keep tab selection outside the re-identified subtree, or re-select Settings after the switch. |
| 13 | Low | UX | After voiding from the just-recorded receipt, the header still says "Payment recorded" with a green check above a VOID receipt. | `ReceiptView.swift:23-27` (`justCreated` label not cleared on void); screenshot R-00009. | Hide the label when `receipt.payment.voided`. |
| 14 | Low | UX | A loan saved without a title is called "Loan" (one exists in the seed DB: "Loan — Maria Lopez"), and the email sheet has no "Resend code" action, only "Use a different email". | `api/app/routes/loans.py:98` default `"Loan"`; `EmailCodeView.swift:52-55`. | Require a title or default to the borrower's name + date; add a resend button with a cooldown. |
| 15 | Low | Docs / repo hygiene | README still says the app icon is a placeholder (real artwork exists). `scripts/testflight.sh` rewrites `project.yml`'s build number in place, leaving the tree dirty. `.build/` only holds an unsigned archive, so there is no evidence a signed TestFlight upload has happened. Two uncommitted changes sit in the tree (see header). | `README.md` "Not done" list; `scripts/testflight.sh:27`; `.build/Lendly-unsigned.xcarchive/Info.plist` (`Team = `, `SigningIdentity = `). | Update README; have the script restore `project.yml` (or set the build number via `xcodebuild` flags); commit or discard the two pending changes. |
| 16 | Info | Local dev | Port 5050 is held by the whatnot-ops Flask dev server (PIDs 79634/79674, started Nov 8 23:27), so the Debug build's default API URL hits the wrong app ("Request failed (405)"). The in-app override lives in Settings, which is only reachable after sign-in. | `lsof -iTCP:5050`; `APIClient.swift:22-24`. This audit ran Lendly on port 5055 and wrote `api_base_url` into the simulator app's preferences plist. | Read the override from a launch argument / environment variable in Debug, or expose it on the Welcome screen in Debug builds. |

## Verified vs not verified

**Verified by execution**
- `api`: `.venv/bin/python -m pytest` → **50 passed** in 2.9 s against local `lendly_test` (Postgres.app 15). DB target printed and confirmed local before running.
- `ios`: `xcodebuild … build` (iPhone 17 Pro, iOS 26.5) → BUILD SUCCEEDED; `xcodebuild … test` → **5 tests in 3 suites passed** (Swift Testing).
- Scripted end-to-end against the local API (`http://127.0.0.1:5055`, 69 calls): **68/69 as expected**; the one surprise is finding #2 (no delete route). Covered: invalid email / bad code; sign-up → workspace → borrower (email lower-cased); preview (simple $1,200 @10% × 4 = $1,320, 4 × $330); overdue detection; payment validation (0, over balance, future, before start); receipt numbering R-00001/R-00002 with no reuse after void; idempotent retry returns the same payment, different body → 409; terms locked after payment (title still editable); cancel/delete refused with payments; void restores balance and frees the key; pay-off sets `paid`; compound back-dated payment capped at the balance on that date; cancel → reactivate → delete on a clean loan; invite create → accept (lower-case code accepted, single use) → borrower portal hides notes and voided payments; borrower gets 403 on dashboard/borrowers/record-payment; lender gets 403 on the portal; other tenant gets 403; Spanish error message via `Accept-Language`.
- iPhone simulator, lender: email code sign-in; Dashboard (tiles, overdue, upcoming, chart, recent payments); receipt R-00005 and R-00006 with PDF share button; loan detail (Laptop); Record payment with the "Overdue $700" chip → receipt **R-00009, balance 1,575.00 → 875.00**, DB row `157500 → 87500`, idempotency key stored; void → VOID watermark, balance back to 1,575.00, DB `voided_at` set and key cleared; New loan "Dentist" for Omar Haddad ($500, 10 %, 4 monthly) with live preview ($550 total, 4 × $125 before the rate, first due Dec 9 2026, last Mar 9 2027) → created and listed; Borrowers list; Settings.
- iPad simulator, lender: Welcome, email sign-in, Dashboard portrait + landscape, Loans, Borrower detail with pending invite code `ZK2FWYAJ` (created via API) and Share/New code buttons, Settings, language switch to Español (all tabs and copy translated), sign out.
- Spanish string catalog: 270/275 strings translated; the 5 untranslated are format-only (`%@ · %@`, `%lld`, `Lendly`, `·`).
- App icon: real 1024 px artwork present (teal coin), contrary to the README.

**Not verified (and why)**
- First-run lender flow in the UI (Welcome → "I lend money" → Create workspace → empty dashboard): verified through the API only; the simulator pass was cut short before this step.
- Invited-borrower flow in the UI (Welcome → "I was invited" → code → read-only home) and the `lendly://invite/CODE` deep link: API-verified; the iPad run reached the code-verification step and was cut short.
- Share receipt (PDF) share sheet, iPhone in Spanish (iPad was), Sign in with Apple, real Mailgun delivery, Render deploy, TestFlight upload, App Store Connect state (no API key on this machine).
- Edit-loan form with locked terms (code read, not driven).

## What changed since the last report

Last report: `claude-reports/Money-Safety/lendly-v1-money-safety-review-2026-10-14.md` (now deleted in the working tree, still at `HEAD`).
Since then: tests grew from 38 to 50 (API) and iOS stayed at 5; commits added Mailgun delivery, Spanish, loan-title editing under locked terms, TestFlight prep (icon, team, build number 6, export options) and a Release-only isolation fix. The money-math findings from that review all stayed fixed: this audit's end-to-end pass re-exercised every one of its scenarios (due-date compound payment, back-dated overpayment, cancel with payments, void race) and found no regression. What is still exactly as it was: no deploy, no real email, no Apple sign-in test. New in this report: the submission blockers (#2, #3, #6, #7) that a money review would not look at.

## Recommended next steps (ranked)

1. **Deploy the API** to Render and set `DATABASE_URL`, `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`; verify `/health` and one real login email. (L — needs your OK for each outward step)
2. **Account deletion**: API route + Settings UI + test. (M)
3. **PrivacyInfo.xcprivacy** with the UserDefaults reason and data-collection types. (S)
4. **Privacy policy + terms** page and links; fill App Privacy labels in App Store Connect. (S)
5. **Reviewer demo account** with a deterministic code, documented in the review notes. (S–M)
6. **Rate-limit** `/api/auth/email/request`. (S)
7. **Sign in with Apple** on a device against the deployed API. (M)
8. UX polish before screenshots: row truncation (#9), DecimalField tap target (#10), language-switch tab reset (#12), void header (#13), resend code (#14). (S each)
9. Decide iPad support (#11) and update README / TestFlight script (#15). (S)

## Appendix

**Commands run**
```
git status -sb; git worktree list; git fetch; git rev-list --count origin/main..HEAD (7) / HEAD..origin/main (0)
curl -m 15 https://lendly-api.onrender.com/health            # timeout
cd api && .venv/bin/python -m pytest -q                       # 50 passed
PORT=5055 .venv/bin/python wsgi.py                            # local API (5050 busy)
.venv/bin/python -I <scratchpad>/e2e_api.py http://127.0.0.1:5055   # 68/69 expected
xcodebuild -project ios/Lendly.xcodeproj -scheme Lendly -destination 'platform=iOS Simulator,id=56AD85D9…' build
xcodebuild … -destination 'platform=iOS Simulator,id=D5912453…' test # 5 tests passed
xcrun simctl install/launch com.sotodev.lendly on iPhone 17 Pro (26.5) and iPad Pro 13-inch (M5)
psql lendly_dev: payments rows for receipt 9 before/after void
```
The end-to-end script, API log and simulator screenshots live in this session's scratchpad (not in the repo). Test data created in the
local `lendly_dev` DB only: tenant "E2E Lending", borrower "Ana Prueba", users `lender-1794203827@lendly.test`, `ana-1794203827@example.com`,
`other-1794203827@lendly.test`, `nina-test@lendly.test`; in "Soto Lending": loan "Dentist" (Omar Haddad), payment R-00009 (voided), invite `ZK2FWYAJ` for Nina Patel.

**Refuted / not findings**
- "App icon is a placeholder" (README) — refuted, artwork exists.
- `NSAllowsLocalNetworking` in the Release Info.plist — allowed by Apple, harmless.
- Two `navigationDestination(for: BorrowerDTO.self)` in the Borrowers stack (list + loan hero) — did not misbehave in the flows driven; left as a watch item, not a finding.

---

## Addendum — fixes applied on `fix/app-store-readiness` (2026-11-09, same day)

Branch created from `feature/lendly-v1` (`59108d8`). Nothing committed yet; all changes are in the working tree.

| # | Finding | Status | What changed | Proof |
|---|---|---|---|---|
| 1 | API not deployed | **Open — needs your OK** | Nothing deployed (outward action). | — |
| 2 | No account deletion | **Fixed** | `DELETE /api/me` (`api/app/routes/me.py`): one transaction that locks the user row `FOR NO KEY UPDATE` and the owned loans `FOR UPDATE`, deletes payments → invites → memberships → loans → borrowers → tenants for every owned workspace, reattributes payments the user recorded elsewhere to that workspace's owner, unlinks borrower profiles and invites, drops OTP rows, deletes the user. iOS: Settings → "Delete account" (destructive, confirmation dialog, footer explains scope), `AppModel.deleteAccount()` signs out afterwards. | 7 new tests in `api/tests/test_account_deletion.py` incl. two races (double delete → 204 + 401; 15 payments fired during a delete → no orphans, no 500). The first version of the race test **found a real deadlock** (FOR UPDATE on the user row vs the KEY SHARE a payment insert takes) — fixed by weakening to NO KEY UPDATE; race test then passed 5/5 runs. Driven in the simulator for a lender (workspace with borrower, loan, payment, invite → all rows gone, seeded workspace untouched) and for a borrower on iPad (user gone, profile unlinked, lender's receipts intact). |
| 3 | Missing privacy manifest | **Fixed** | `ios/Lendly/PrivacyInfo.xcprivacy`: UserDefaults reason CA92.1; collected types email, name, phone, other financial info, other user content, user ID (linked, not tracking). | `plutil -lint` OK; file present in the built `Lendly.app`. |
| 4 | Mailgun unset in prod | **Open — needs your OK** | Dashboard-only change. | — |
| 5 | Sign in with Apple untested | **Open** | Needs a device + Apple ID. | — |
| 6 | Reviewer login | **Fixed (code), needs config** | `REVIEW_LOGIN_EMAIL` + `REVIEW_LOGIN_CODE` env vars: that address gets the fixed code, nothing is e-mailed, works without Mailgun; attempts still capped at 5 per code and the request throttle still applies. Added to `render.yaml` (`sync: false`), `.env.example`, README. | `api/tests/test_auth_limits.py` (2 tests). Set both in Render and paste them into App Review notes; use 8+ digits. |
| 7 | No privacy / terms | **Fixed (app), pages pending** | `ios/Lendly/Core/Links.swift` → `https://sotodev.com/lendly/{privacy,terms,support}`; Welcome footer now "By continuing you agree to our Terms of Use and Privacy Policy" with tappable links (EN/ES); Settings → About section with the three links. | Seen in simulator (EN + ES). **The three pages must be published before submission**, or change the URLs. |
| 8 | No OTP rate limit | **Fixed** | Per-address limit (3 codes / 10 min, DB-counted) and per-IP limit (20 / 10 min, in-memory per worker, uses the proxy-appended `X-Forwarded-For` hop) → 429 `too_many_requests`, Spanish copy added. | 4 tests in `test_auth_limits.py`. |
| 9 | Row truncation | **Fixed** | Loan/payment/dashboard subtitles wrap to 2 lines; relative dates lowercase mid-sentence ("due in 5 days"). | Simulator: "Maria Lopez · $137.50 vence en 5 días", "Rent gap · 20 days late" fully visible. |
| 10 | Number-field tap target | **Fixed** | `DecimalField` takes the row's trailing width and focuses on tap anywhere in it. | Simulator: tap on empty row area → field focused, "12 %" typed. |
| 12 | Language switch resets tab | **Fixed** | Tab selection moved to `AppModel.adminTab` (reset on sign-out). | Simulator: switch to Español stays on Ajustes. |
| 13 | "Payment recorded" over a void | **Fixed** | Banner hidden when the receipt is voided. | Code; not re-driven. |
| 14 | No resend code | **Fixed** | "Resend code" with a 30 s cooldown in the code sheet (EN/ES). | Simulator (iPad): "Reenviar en 16 s" → "Reenviar código". Default loan title "Loan" left as is. |
| 15 | README / script hygiene | **Fixed** | README: env vars, account deletion, legal pages, known-gaps list; `scripts/testflight.sh` restores `project.yml` on exit. | Read. |
| 11, 16 | iPad layout, local port | Unchanged | Noted only. | — |

Also verified after the changes: API suite **63 passed**; iOS unit tests **5 passed**; simulator build succeeded; Spanish catalog complete (only format-only keys untranslated); first-run lender flow (Welcome → "Presto dinero" → create workspace) and invited-borrower flow (Welcome → "Me invitaron" → code → read-only home) driven end to end on iPhone / iPad.

Still to do before submission (outside this branch): deploy the API and set `DATABASE_URL`, Mailgun and the review login on Render; publish the three legal pages; test Sign in with Apple on a device; fill App Privacy labels in App Store Connect; decide iPad support.

### Money-safety / adversarial review of the fixes (same day)

Two independent reviewers (backend adversarial, iOS client) went over the branch. Everything they could reproduce was fixed on the spot; the rest is listed.

**Backend — reproduced by the reviewer with scratch tests, now fixed**
- Deletion 500'd when a child row or a new workspace was inserted by the same account mid-delete (FK violation on commit). Fix: lock the owned tenant rows after the loan rows (same order as `record_payment`, so no deadlock), and turn any lost race (`IntegrityError` / deadlock `OperationalError`) into **409 `retry`** with nothing removed; the iOS client retries one 409 automatically. My own first attempt at this fix (tenants locked *before* loans) deadlocked against payment recording in ~50 % of suite runs — caught by the race test, reordered, then 6/6 green runs.
- Per-mailbox limit was bypassable with Gmail aliases (`victim+1@gmail.com`, `v.ictim@gmail.com`) and overshot under a concurrent burst (count-then-insert). Fix: new `otp_codes.inbox` column (migration `7ad35be8c5ce`, round-tripped up/down/up on a scratch DB with an existing row) holding the canonical mailbox (gmail dots and `+tags` collapsed, `+tags` collapsed everywhere), counted under `pg_advisory_xact_lock` so 8 parallel requests yield exactly one code.
- `REVIEW_LOGIN_CODE` longer than 12 characters was silently unusable (the verify route truncates at 12). Fix: config refuses to start unless the code is 8–12 digits; README / `.env.example` say so.
- Deletion copy now tells borrowers the lender keeps their own record of the loan (EN/ES).

**Backend — noted, not changed (decide later)**
- Per-IP throttle trusts the last `X-Forwarded-For` hop; whether Render appends the real client address is undocumented. Check once on the deployed service before relying on it (locally, without a proxy, a forged header bypasses it). The per-mailbox limit does not depend on this.
- Deletion needs only the 90-day bearer token, no re-auth or grace period. Design choice.
- Anyone who knows the review address can burn its 3-codes-per-10-min budget; use an address nobody can guess and re-seed the demo account if a reviewer deletes it.
- `void_payment` racing a deletion can 500 in a tiny window (pre-existing shape).

**iOS — fixed**
- Resend cooldown task is now owned by the view (cancelled on restart and on dismiss), so it can't double-run.
- Sign-out clears a pending invite code and banner (pre-existing leak into the next user's session).
- A 401 during delete no longer shows a pointless alert (the client already signed out).
- Tapping the row label ("Amount", "Fee", rate label) now focuses the number field too.

**iOS — checked and found fine by the reviewer:** Swift 6 isolation of the new tasks and `@Bindable` use, string-catalog keys vs. compiler-extracted keys, privacy-manifest identifiers (UserDefaults → CA92.1; six collected data types; `Contacts` correctly not declared), `DecimalField` focus behaviour, 204-with-empty-body handling.

**Final verification after all review fixes:** API **67 passed** (6 consecutive runs, incl. 3 race tests); migration round-trip OK; iOS build + **5 tests** pass; delete flow driven again in the simulator earlier today (lender and borrower paths). Local dev DB migrated to `7ad35be8c5ce`.

**Verdict for this branch: SAFE TO MERGE** as code. **NOT YET SAFE TO SUBMIT** until the API is deployed with `DATABASE_URL`, Mailgun, `REVIEW_LOGIN_*` set, the three legal pages are live, and Sign in with Apple is tested on a device.
