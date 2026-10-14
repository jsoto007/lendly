import Foundation

// MARK: - Enums (raw values match the API)

enum InterestType: String, Codable, CaseIterable, Identifiable, Hashable {
    case compound, simple, fixed
    var id: String { rawValue }
    var label: String {
        switch self {
        case .compound: tr("Compound")
        case .simple: tr("Percentage")
        case .fixed: tr("Fixed amount")
        }
    }
    var symbol: String {
        switch self {
        case .compound: "chart.line.uptrend.xyaxis"
        case .simple: "percent"
        case .fixed: "dollarsign.circle"
        }
    }
    var explanation: String {
        switch self {
        case .compound: tr("Interest is charged every period on whatever is still owed. Pay early and you pay less.")
        case .simple: tr("A one-time percentage of the amount lent, added to the total and split across the payments.")
        case .fixed: tr("A flat dollar amount added on top of the loan, either once or every period.")
        }
    }
}

enum ScheduleKind: String, Codable, CaseIterable, Identifiable, Hashable {
    case weekly, biweekly, monthly
    var id: String { rawValue }
    var label: String {
        switch self {
        case .weekly: tr("Weekly")
        case .biweekly: tr("Every 2 weeks")
        case .monthly: tr("Monthly")
        }
    }
    var periodNoun: String {
        switch self {
        case .weekly: tr("week")
        case .biweekly: tr("2 weeks")
        case .monthly: tr("month")
        }
    }
    func termLabel(_ n: Int) -> String {
        switch self {
        case .weekly: plural(n, one: "1 week", other: "\(n) weeks")
        case .biweekly: tr("\(n * 2) weeks")
        case .monthly: plural(n, one: "1 month", other: "\(n) months")
        }
    }
}

enum PaymentMethod: String, Codable, CaseIterable, Identifiable, Hashable {
    case cash, zelle, venmo, cashapp, bank, check, other
    var id: String { rawValue }
    var label: String {
        switch self {
        case .cash: tr("Cash")
        case .zelle: "Zelle"
        case .venmo: "Venmo"
        case .cashapp: "Cash App"
        case .bank: tr("Bank transfer")
        case .check: tr("Check")
        case .other: tr("Other")
        }
    }
    var symbol: String {
        switch self {
        case .cash: "banknote"
        case .zelle, .venmo, .cashapp: "iphone"
        case .bank: "building.columns"
        case .check: "doc.text"
        case .other: "ellipsis.circle"
        }
    }
}

enum LoanStatus: String, Codable, Hashable {
    case active, paid, cancelled
    var label: String {
        switch self {
        case .active: tr("Active")
        case .paid: tr("Paid")
        case .cancelled: tr("Cancelled")
        }
    }
}

enum MemberRole: String, Codable, Hashable {
    case admin, borrower
}

// MARK: - DTOs

struct UserDTO: Codable, Hashable, Identifiable {
    var id: String
    var email: String?
    var name: String?
    var hasApple: Bool
    var displayName: String { name?.isEmpty == false ? name! : (email ?? tr("You")) }
}

struct MembershipDTO: Codable, Hashable, Identifiable {
    var id: String
    var tenantId: String
    var tenantName: String
    var role: MemberRole
    var borrowerId: String?
    var currency: String
}

struct SessionResponse: Codable {
    var token: String
    var user: UserDTO
    var memberships: [MembershipDTO]
}

struct MeResponse: Codable {
    var user: UserDTO
    var memberships: [MembershipDTO]
}

struct TenantDTO: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    var currency: String
    var createdAt: String
}

struct BorrowerSummary: Codable, Hashable {
    var activeLoans: Int
    var totalLoans: Int
    var outstandingCents: Int
    var overdueCents: Int
    var lentCents: Int
    var paidCents: Int
}

struct BorrowerDTO: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    var email: String?
    var phone: String?
    var notes: String?
    var linked: Bool
    var archived: Bool
    var createdAt: String
    var summary: BorrowerSummary?

    var initials: String {
        let parts = name.split(separator: " ").prefix(2)
        return parts.map { String($0.prefix(1)).uppercased() }.joined()
    }
}

struct InviteDTO: Codable, Hashable, Identifiable {
    var id: String
    var code: String
    var link: String
    var borrowerId: String
    var expiresAt: String
    var acceptedAt: String?
}

struct LoanState: Codable, Hashable {
    var totalDueCents: Int
    var interestCents: Int
    var installmentCents: Int
    var paidCents: Int
    var balanceCents: Int
    var expectedToDateCents: Int
    var overdueCents: Int
    var nextDueDate: String?
    var nextDueCents: Int?
    var isPaidOff: Bool
    var progress: Double
    var daysOverdue: Int
}

struct InstallmentDTO: Codable, Hashable, Identifiable {
    var number: Int
    var dueDate: String
    var amountCents: Int
    var cumulativeDueCents: Int
    var status: String   // paid | overdue | upcoming
    var partial: Bool
    var id: Int { number }
}

struct PaymentDTO: Codable, Hashable, Identifiable {
    var id: String
    var loanId: String
    var amountCents: Int
    var paidOn: String
    var method: PaymentMethod
    var note: String?
    var receiptNumber: Int
    var receiptCode: String
    var balanceBeforeCents: Int
    var balanceAfterCents: Int
    var voided: Bool
    var voidedAt: String?
    var voidReason: String?
    var createdAt: String
    var loanTitle: String?
    var borrowerName: String?
    var lenderName: String?
    var currency: String?
}

struct LoanDTO: Codable, Hashable, Identifiable {
    var id: String
    var borrowerId: String
    var borrowerName: String
    var title: String
    var principalCents: Int
    var interestType: InterestType
    var rateBps: Int
    var fixedFeeCents: Int
    var fixedFeePerPeriod: Bool
    var schedule: ScheduleKind
    var termPeriods: Int
    var startDate: String
    var status: LoanStatus
    var notes: String?
    var createdAt: String
    var state: LoanState
    var installments: [InstallmentDTO]?
    var payments: [PaymentDTO]?

    var termsSummary: String {
        switch interestType {
        case .compound: tr("\(Money.percent(rateBps)) per \(schedule.periodNoun), compounding")
        case .simple: tr("\(Money.percent(rateBps)) flat")
        case .fixed: fixedFeePerPeriod ? tr("\(Money.format(fixedFeeCents)) per \(schedule.periodNoun)") : tr("\(Money.format(fixedFeeCents)) once")
        }
    }
}

struct PreviewResponse: Codable {
    var state: LoanState
    var installments: [InstallmentDTO]
    var endDate: String
}

struct DashboardTotals: Codable, Hashable {
    var lentCents: Int
    var outstandingCents: Int
    var collectedCents: Int
    var projectedInterestCents: Int
    var overdueCents: Int
    var activeLoans: Int
    var paidLoans: Int
    var borrowers: Int
}

struct UpcomingDTO: Codable, Hashable, Identifiable {
    var loanId: String
    var title: String
    var borrowerId: String
    var borrowerName: String
    var dueDate: String
    var amountCents: Int
    var id: String { loanId + dueDate }
}

struct MonthPoint: Codable, Hashable, Identifiable {
    var month: String
    var cents: Int
    var id: String { month }
}

struct DashboardDTO: Codable {
    var totals: DashboardTotals
    var overdue: [LoanDTO]
    var upcoming: [UpcomingDTO]
    var recentPayments: [PaymentDTO]
    var monthlyCollected: [MonthPoint]
    var asOf: String
}

struct ReceiptLoan: Codable, Hashable {
    var id: String
    var title: String
    var principalCents: Int
    var interestType: InterestType
    var rateBps: Int
    var fixedFeeCents: Int
    var fixedFeePerPeriod: Bool
    var schedule: ScheduleKind
    var termPeriods: Int
    var startDate: String
    var status: LoanStatus
}

struct NamedParty: Codable, Hashable {
    var id: String
    var name: String
    var email: String?
}

struct ReceiptDTO: Codable, Hashable {
    var payment: PaymentDTO
    var loan: ReceiptLoan
    var borrower: NamedParty
    var lender: NamedParty
}

struct LenderInfo: Codable, Hashable {
    var id: String
    var name: String
    var currency: String
}

struct PortalDTO: Codable {
    var borrower: BorrowerDTO
    var lender: LenderInfo
    var loans: [LoanDTO]
    var payments: [PaymentDTO]
}

// MARK: - Request bodies

struct LoanTermsBody: Codable, Hashable {
    var borrowerId: String?
    var title: String?
    var principalCents: Int
    var interestType: InterestType
    var rateBps: Int
    var fixedFeeCents: Int
    var fixedFeePerPeriod: Bool
    var schedule: ScheduleKind
    var termPeriods: Int
    var startDate: String
    var notes: String?
}

struct PaymentBody: Codable {
    var amountCents: Int
    var paidOn: String
    var method: PaymentMethod
    var note: String?
    /// One key per attempt so a retried request never records the payment twice.
    var idempotencyKey: String
}

struct Empty: Codable {}
