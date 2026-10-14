"""Seed a local dev database with a lender, borrowers, loans and payments.

Usage:  .venv/bin/python seed.py
Refuses to run unless DATABASE_URL points at localhost.
"""
from datetime import date, timedelta
from urllib.parse import urlparse

from app import create_app
from app.extensions import db
from app.models import Borrower, Loan, Membership, Payment, Tenant, User
from app.serializers import state_of

app = create_app()
with app.app_context():
    host = urlparse(app.config["SQLALCHEMY_DATABASE_URI"]).hostname
    if host not in ("localhost", "127.0.0.1"):
        raise SystemExit(f"Refusing to seed non-local database host: {host}")

    if db.session.execute(db.select(User).where(User.email == "lender@lendly.test")).scalar_one_or_none():
        raise SystemExit("Already seeded. Drop and recreate lendly_dev to reseed.")

    today = date.today()
    lender = User(email="lender@lendly.test", name="Javier")
    db.session.add(lender)
    db.session.flush()
    tenant = Tenant(name="Soto Lending", owner_user_id=lender.id)
    db.session.add(tenant)
    db.session.flush()
    db.session.add(Membership(user_id=lender.id, tenant_id=tenant.id, role="admin"))

    def borrower(name, email=None, phone=None, notes=None):
        b = Borrower(tenant_id=tenant.id, name=name, email=email, phone=phone, notes=notes)
        db.session.add(b)
        db.session.flush()
        return b

    def loan(b, title, principal, itype, start, schedule="monthly", term=4, rate=0, fee=0, fee_per_period=False, notes=None):
        l = Loan(tenant_id=tenant.id, borrower_id=b.id, title=title, principal_cents=principal, interest_type=itype,
                 rate_bps=rate, fixed_fee_cents=fee, fixed_fee_per_period=fee_per_period, schedule=schedule,
                 term_periods=term, start_date=start, notes=notes)
        db.session.add(l)
        db.session.flush()
        return l

    def pay(l, amount, on, method="zelle", note=None):
        before = state_of(l)
        tenant.receipt_seq += 1
        p = Payment(tenant_id=tenant.id, loan_id=l.id, amount_cents=amount, paid_on=on, method=method, note=note,
                    receipt_number=tenant.receipt_seq, balance_before_cents=before.balance_cents,
                    balance_after_cents=before.balance_cents, created_by_user_id=lender.id)
        db.session.add(p)
        l.payments.append(p)
        db.session.flush()
        after = state_of(l)
        p.balance_after_cents = after.balance_cents
        l.status = "paid" if after.is_paid_off else "active"

    maria = borrower("Maria Lopez", "maria@example.com", "(917) 555-0142", "Cousin's friend. Pays on Fridays.")
    dan = borrower("Daniel Reyes", "dan.reyes@example.com", "(646) 555-0199")
    nina = borrower("Nina Patel", "nina.p@example.com", "(718) 555-0127")
    omar = borrower("Omar Haddad", None, "(347) 555-0163", "Paid off his first loan early.")

    l1 = loan(maria, "Car repair", 120_000, "simple", today - timedelta(days=75), rate=1000, term=4)
    pay(l1, 33_000, today - timedelta(days=45), "zelle", "First installment")
    pay(l1, 33_000, today - timedelta(days=14), "cash")

    l2 = loan(dan, "Rent gap", 80_000, "compound", today - timedelta(days=50), schedule="biweekly", term=6, rate=300)
    pay(l2, 14_000, today - timedelta(days=36), "venmo")
    pay(l2, 14_000, today - timedelta(days=22), "venmo")
    # Dan skipped the last one → overdue

    l3 = loan(nina, "Laptop", 150_000, "fixed", today - timedelta(days=10), schedule="weekly", term=10, fee=2_500, fee_per_period=True)
    pay(l3, 17_500, today - timedelta(days=3), "cashapp")

    l4 = loan(omar, "Moving costs", 50_000, "fixed", today - timedelta(days=120), term=2, fee=5_000)
    pay(l4, 27_500, today - timedelta(days=90), "cash")
    pay(l4, 27_500, today - timedelta(days=60), "cash", "Paid in full")

    l5 = loan(omar, "Tuition deposit", 200_000, "simple", today - timedelta(days=5), term=6, rate=800)

    db.session.commit()
    print("Seeded. Sign in with email lender@lendly.test (the code is returned by the API in dev).")
