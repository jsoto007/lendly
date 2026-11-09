from datetime import date

from app.services.schedule import (LoanTerms, PaymentLike, add_months, build_schedule, compute_state,
                                   period_end, validate_terms)

START = date(2026, 1, 31)


def terms(**kw):
    base = dict(principal_cents=100_000, interest_type="simple", rate_bps=1000, fixed_fee_cents=0,
                fixed_fee_per_period=False, schedule="monthly", term_periods=4, start_date=START)
    base.update(kw)
    return LoanTerms(**base)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)
    assert add_months(date(2026, 11, 15), 2) == date(2027, 1, 15)
    assert add_months(date(2026, 3, 1), -1) == date(2026, 2, 1)


def test_period_end_weekly_biweekly_monthly():
    assert period_end(START, "weekly", 2) == date(2026, 2, 14)
    assert period_end(START, "biweekly", 1) == date(2026, 2, 14)
    assert period_end(START, "monthly", 1) == date(2026, 2, 28)


def test_simple_interest_total_and_even_split():
    s = build_schedule(terms())
    # $1,000 + 10% flat = $1,100 over 4 → 275.00 each
    assert [i.amount_cents for i in s] == [27_500] * 4
    assert s[-1].cumulative_due_cents == 110_000
    assert [i.due_date for i in s] == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]


def test_even_split_pushes_remainder_cents_to_first_installments():
    s = build_schedule(terms(principal_cents=10_000, rate_bps=0, term_periods=3))
    assert [i.amount_cents for i in s] == [3_334, 3_333, 3_333]
    assert sum(i.amount_cents for i in s) == 10_000


def test_fixed_fee_once_and_per_period():
    once = build_schedule(terms(interest_type="fixed", rate_bps=0, fixed_fee_cents=5_000, term_periods=5))
    assert once[-1].cumulative_due_cents == 105_000
    per = build_schedule(terms(interest_type="fixed", rate_bps=0, fixed_fee_cents=5_000, fixed_fee_per_period=True, term_periods=5))
    assert per[-1].cumulative_due_cents == 125_000
    assert [i.amount_cents for i in per] == [25_000] * 5


def test_compound_amortized_installments_retire_balance_exactly():
    # $1,000 at 2%/period over 4 periods: pmt = 1000*0.02/(1-1.02^-4) = 262.62
    s = build_schedule(terms(interest_type="compound", rate_bps=200, term_periods=4))
    amounts = [i.amount_cents for i in s]
    assert amounts[:3] == [26_262, 26_262, 26_262]
    assert 26_200 <= amounts[3] <= 26_300
    total = sum(amounts)
    assert 105_000 <= total <= 105_100  # ≈ $1,050.49 total interest ~ $50.49
    # Paying exactly on schedule leaves zero balance after the last due date.
    pays = [PaymentLike(i.amount_cents, i.due_date) for i in s]
    st = compute_state(terms(interest_type="compound", rate_bps=200, term_periods=4), pays, s[-1].due_date)
    assert st.balance_cents == 0 and st.is_paid_off


def test_compound_zero_rate_is_even_split():
    s = build_schedule(terms(interest_type="compound", rate_bps=0, term_periods=4))
    assert [i.amount_cents for i in s] == [25_000] * 4


def test_compound_balance_accrues_on_unpaid_balance_only():
    t = terms(interest_type="compound", rate_bps=1000, term_periods=2)  # 10%/period
    # No payments after one period: 1000 * 1.10 = 1100
    st = compute_state(t, [], date(2026, 2, 28))
    assert st.balance_cents == 110_000
    # Pay 500 before the first period end: (1000-500)*1.10 = 550
    st = compute_state(t, [PaymentLike(50_000, date(2026, 2, 10))], date(2026, 2, 28))
    assert st.balance_cents == 55_000
    # Pay the full 1000 on day one → nothing accrues, never negative
    st = compute_state(t, [PaymentLike(100_000, START)], date(2026, 12, 31))
    assert st.balance_cents == 0 and st.is_paid_off


def test_compound_keeps_accruing_past_term_when_unpaid():
    t = terms(interest_type="compound", rate_bps=1000, term_periods=1)
    st = compute_state(t, [], date(2026, 4, 30))  # three period ends elapsed
    assert st.balance_cents == 133_100
    assert st.next_due_date is None  # past term → everything is due now
    assert st.overdue_cents == 110_000  # the scheduled installment that was missed


def test_overdue_and_next_due_for_simple_loan():
    t = terms()  # 4 × 275 due Feb 28, Mar 31, Apr 30, May 31
    st = compute_state(t, [], date(2026, 2, 1))
    assert st.overdue_cents == 0 and st.next_due_date == date(2026, 2, 28) and st.next_due_cents == 27_500
    st = compute_state(t, [], date(2026, 3, 1))
    assert st.overdue_cents == 27_500 and st.days_overdue == 1
    st = compute_state(t, [PaymentLike(10_000, date(2026, 2, 20))], date(2026, 4, 1))
    assert st.expected_to_date_cents == 55_000
    assert st.overdue_cents == 45_000
    assert st.days_overdue == (date(2026, 4, 1) - date(2026, 2, 28)).days
    assert st.next_due_date == date(2026, 4, 30)


def test_next_due_is_capped_by_remaining_balance():
    t = terms()
    st = compute_state(t, [PaymentLike(100_000, date(2026, 2, 1))], date(2026, 2, 2))
    assert st.balance_cents == 10_000
    assert st.next_due_cents == 10_000
    assert 0 < st.progress < 1


def test_overpayment_never_yields_negative_balance():
    t = terms()
    st = compute_state(t, [PaymentLike(200_000, date(2026, 2, 1))], date(2026, 2, 2))
    assert st.balance_cents == 0 and st.is_paid_off and st.progress == 1.0 and st.overdue_cents == 0


def test_validate_terms_rejects_bad_input():
    assert validate_terms(terms(principal_cents=0))
    assert validate_terms(terms(term_periods=0))
    assert validate_terms(terms(interest_type="fixed", fixed_fee_cents=100, rate_bps=100))
    assert validate_terms(terms(interest_type="simple", fixed_fee_cents=100))
    assert validate_terms(terms(schedule="daily"))
    assert not validate_terms(terms())
