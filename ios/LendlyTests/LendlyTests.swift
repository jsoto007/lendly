import Foundation
import Testing
@testable import Lendly

struct MoneyTests {
    @Test func formatsCents() {
        #expect(Money.format(123_456) == "$1,234.56")
        #expect(Money.format(0) == "$0.00")
    }

    @Test func percentFromBasisPoints() {
        #expect(Money.percent(1000) == "10%")
        #expect(Money.percent(250) == "2.5%")
    }

    @Test func decimalToCentsRoundsHalfUp() {
        #expect(Money.cents(from: Decimal(string: "19.995")!) == 2000)
        #expect(Money.cents(from: Decimal(string: "0.1")!) == 10)
        #expect(Money.bps(fromPercent: Decimal(string: "7.5")!) == 750)
    }
}

struct DateTests {
    @Test func parsesAndFormatsDays() {
        let d = Dates.day("2026-10-14")
        #expect(d != nil)
        #expect(Dates.dayString(d!) == "2026-10-14")
        #expect(Dates.day("2026-10-14T12:00:00+00:00") != nil)
    }
}

struct DecodingTests {
    @Test func decodesLoanFromSnakeCaseJSON() throws {
        let json = """
        {"id":"1","borrower_id":"b","borrower_name":"Maria","title":"Car","principal_cents":100000,"interest_type":"simple",
         "rate_bps":1000,"fixed_fee_cents":0,"fixed_fee_per_period":false,"schedule":"monthly","term_periods":4,
         "start_date":"2026-01-31","status":"active","notes":null,"created_at":"2026-01-31T00:00:00+00:00",
         "state":{"total_due_cents":110000,"interest_cents":10000,"installment_cents":27500,"paid_cents":0,"balance_cents":110000,
                  "expected_to_date_cents":0,"overdue_cents":0,"next_due_date":"2026-02-28","next_due_cents":27500,
                  "is_paid_off":false,"progress":0.0,"days_overdue":0}}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let loan = try decoder.decode(LoanDTO.self, from: Data(json.utf8))
        #expect(loan.interestType == .simple)
        #expect(loan.state.totalDueCents == 110_000)
        #expect(loan.termsSummary == "10% flat")
    }
}
