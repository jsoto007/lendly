"""Loan schedule and balance math. Pure functions, integer cents, no DB access.

Interest types
--------------
compound : `rate_bps` is the rate PER PERIOD. Interest accrues on the unpaid
           balance at the end of every period. Installments are the amortized
           payment (P*r / (1-(1+r)^-n)), rounded to cents, with the final
           installment absorbing rounding so the schedule retires the balance
           exactly when paid on time.
simple   : `rate_bps` is a flat percentage of principal, charged once.
           total_due = principal + round(principal * rate). Split evenly.
fixed    : `fixed_fee_cents` added once, or once per period when
           `fixed_fee_per_period` is set. Split evenly.

Schedules: weekly (7 days), biweekly (14 days), monthly (same day next month,
clamped to month end). Installment k is due at the end of period k.

Day semantics (as_of = the lender's local calendar date):
- Compound interest for period k is charged ON its due date (end <= as_of). A payment dated
  on the due date is applied AFTER that charge; a payment dated before it is applied before.
- An installment is overdue only once its due date has passed (due_date < as_of), so the
  borrower has the whole due day to pay. An installment due today is "next".
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

MAX_ACCRUAL_PERIODS = 1200  # safety cap for the accrual loop (~23 years weekly)
BALANCE_CEILING = 10 ** 13   # stop accruing past $100B so Decimal math can never overflow
MAX_RATE_BPS = 10_000        # 100% per period / 100% flat


@dataclass(frozen=True)
class LoanTerms:
    principal_cents: int
    interest_type: str
    rate_bps: int
    fixed_fee_cents: int
    fixed_fee_per_period: bool
    schedule: str
    term_periods: int
    start_date: date


@dataclass(frozen=True)
class Installment:
    number: int
    due_date: date
    amount_cents: int
    cumulative_due_cents: int


@dataclass(frozen=True)
class PaymentLike:
    amount_cents: int
    paid_on: date


@dataclass
class LoanState:
    total_due_cents: int
    interest_cents: int
    installment_cents: int
    paid_cents: int
    balance_cents: int
    expected_to_date_cents: int
    overdue_cents: int
    next_due_date: date | None
    next_due_cents: int | None
    is_paid_off: bool
    progress: float
    days_overdue: int


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def period_end(start: date, schedule: str, k: int) -> date:
    """Date on which period k (1-based) ends, i.e. when installment k is due."""
    if schedule == "weekly":
        return start + timedelta(days=7 * k)
    if schedule == "biweekly":
        return start + timedelta(days=14 * k)
    if schedule == "monthly":
        return add_months(start, k)
    raise ValueError(f"unknown schedule {schedule!r}")


def validate_terms(t: LoanTerms) -> list[str]:
    errors = []
    if t.principal_cents <= 0:
        errors.append("principal must be greater than zero")
    if t.interest_type not in ("compound", "simple", "fixed"):
        errors.append("interest_type must be compound, simple or fixed")
    if t.schedule not in ("weekly", "biweekly", "monthly"):
        errors.append("schedule must be weekly, biweekly or monthly")
    if t.term_periods <= 0 or t.term_periods > 600:
        errors.append("term_periods must be between 1 and 600")
    if t.rate_bps < 0 or t.rate_bps > MAX_RATE_BPS:
        errors.append("rate must be between 0% and 100%")
    if t.principal_cents > 100_000_000_000 or t.fixed_fee_cents > 100_000_000_000:
        errors.append("amount is too large")
    if t.fixed_fee_cents < 0:
        errors.append("fixed fee cannot be negative")
    if t.interest_type == "fixed" and t.rate_bps:
        errors.append("fixed-fee loans do not take a rate")
    if t.interest_type != "fixed" and t.fixed_fee_cents:
        errors.append("only fixed-fee loans take a fee")
    return errors


def _split_even(total: int, n: int) -> list[int]:
    base, remainder = divmod(total, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def _compound_installments(t: LoanTerms) -> list[int]:
    n = t.term_periods
    principal = Decimal(t.principal_cents)
    r = Decimal(t.rate_bps) / Decimal(10_000)
    if r == 0:
        return _split_even(t.principal_cents, n)
    pmt = _round_cents(principal * r / (1 - (1 + r) ** (-n)))
    amounts = []
    balance = t.principal_cents
    for k in range(1, n + 1):
        balance = _round_cents(Decimal(balance) * (1 + r))
        if k == n:
            amounts.append(balance)  # final installment clears the balance exactly
            balance = 0
        else:
            paid = min(pmt, balance)
            amounts.append(paid)
            balance -= paid
    return amounts


def build_schedule(t: LoanTerms) -> list[Installment]:
    if t.interest_type == "compound":
        amounts = _compound_installments(t)
    elif t.interest_type == "simple":
        interest = _round_cents(Decimal(t.principal_cents) * Decimal(t.rate_bps) / Decimal(10_000))
        amounts = _split_even(t.principal_cents + interest, t.term_periods)
    elif t.interest_type == "fixed":
        fee = t.fixed_fee_cents * (t.term_periods if t.fixed_fee_per_period else 1)
        amounts = _split_even(t.principal_cents + fee, t.term_periods)
    else:
        raise ValueError(f"unknown interest_type {t.interest_type!r}")
    out, cumulative = [], 0
    for k, amount in enumerate(amounts, start=1):
        cumulative += amount
        out.append(Installment(k, period_end(t.start_date, t.schedule, k), amount, cumulative))
    return out


def _compound_balance(t: LoanTerms, payments: list[PaymentLike], as_of: date) -> int:
    """Roll the balance forward (unclamped; negative means overpaid). Payments reduce the
    balance when made; interest is charged on the outstanding balance at each period end on
    or before as_of. A payment dated on a period end is applied after that period's charge.
    Accrual keeps going past the term while a balance remains."""
    r = Decimal(t.rate_bps) / Decimal(10_000)
    pending = sorted(payments, key=lambda p: p.paid_on)
    idx = 0
    balance = t.principal_cents
    k = 1
    while k <= MAX_ACCRUAL_PERIODS:
        end = period_end(t.start_date, t.schedule, k)
        if end > as_of:
            break
        while idx < len(pending) and pending[idx].paid_on < end:
            balance -= pending[idx].amount_cents
            idx += 1
        if 0 < balance < BALANCE_CEILING and r > 0:
            balance = _round_cents(Decimal(balance) * (1 + r))
        while idx < len(pending) and pending[idx].paid_on == end:
            balance -= pending[idx].amount_cents
            idx += 1
        k += 1
    while idx < len(pending) and pending[idx].paid_on <= as_of:
        balance -= pending[idx].amount_cents
        idx += 1
    # payments dated in the future still count against the balance shown today
    while idx < len(pending):
        balance -= pending[idx].amount_cents
        idx += 1
    return balance


def raw_balance(t: LoanTerms, payments: list[PaymentLike], as_of: date) -> int:
    """Balance before clamping. Negative = the loan has been overpaid."""
    if t.interest_type == "compound":
        return _compound_balance(t, payments, as_of)
    return build_schedule(t)[-1].cumulative_due_cents - sum(p.amount_cents for p in payments)


def compute_state(t: LoanTerms, payments: list[PaymentLike], as_of: date) -> LoanState:
    schedule = build_schedule(t)
    total_due = schedule[-1].cumulative_due_cents
    paid = sum(p.amount_cents for p in payments)
    balance = max(raw_balance(t, payments, as_of), 0)
    expected_to_date = sum(i.amount_cents for i in schedule if i.due_date < as_of)
    overdue = max(expected_to_date - paid, 0)
    overdue = min(overdue, balance)
    days_overdue = 0
    if overdue > 0:
        # first installment whose cumulative due isn't covered by what's been paid
        for inst in schedule:
            if inst.due_date < as_of and inst.cumulative_due_cents > paid:
                days_overdue = (as_of - inst.due_date).days
                break
    next_inst = next((i for i in schedule if i.due_date >= as_of), None)
    is_paid_off = balance == 0
    if is_paid_off:
        next_due_date, next_due_cents = None, None
    elif next_inst is not None:
        next_due_date = next_inst.due_date
        # For compound loans the installment is settled after that period's charge.
        if t.interest_type == "compound" and next_inst.due_date > as_of:
            cap = _round_cents(Decimal(balance) * (1 + Decimal(t.rate_bps) / Decimal(10_000)))
        else:
            cap = balance
        next_due_cents = min(next_inst.amount_cents, cap)
    else:
        next_due_date, next_due_cents = None, None  # past term: whole balance is due now
    # Share of what will actually be paid, so late interest on a compound loan shows as unfinished.
    progress = 1.0 if is_paid_off else (paid / (paid + balance) if paid + balance else 0.0)
    return LoanState(
        total_due_cents=total_due,
        interest_cents=total_due - t.principal_cents,
        installment_cents=schedule[0].amount_cents,
        paid_cents=paid,
        balance_cents=balance,
        expected_to_date_cents=expected_to_date,
        overdue_cents=overdue,
        next_due_date=next_due_date,
        next_due_cents=next_due_cents,
        is_paid_off=is_paid_off,
        progress=round(progress, 4),
        days_overdue=days_overdue,
    )
