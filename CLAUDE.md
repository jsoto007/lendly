# Lendly — project rules

- Monorepo: `api/` (Flask, Postgres) and `ios/` (SwiftUI, XcodeGen). The `.xcodeproj` is
  generated — edit `ios/project.yml` and run `xcodegen generate`; never hand-edit the pbxproj.
- Money is integer cents, rates are basis points. Schedule/balance math lives only in
  `api/app/services/schedule.py`; the iOS app never recomputes it (it calls `/api/loans/preview`).
- `api/migrations/versions/*` are frozen once applied anywhere; add a new revision.
- Local DB: `lendly_dev` / `lendly_test` on Postgres.app (127.0.0.1:5432). `seed.py` refuses
  non-local hosts. The API runs on port 5050 (Dishful/Live Msc use 5001/8081).
- Build + test: `cd api && .venv/bin/python -m pytest`; iOS via `xcodebuild … test` on an
  iOS 26 simulator. Verify UI changes in the simulator, not just by compiling.
- Any change to payments, voids, receipt numbering or interest math gets the
  `money-safety-review` treatment: real pytest run + adversarial review.
- Swift 6 language mode with default MainActor isolation; keep view models `@Observable`.
