import SwiftUI

struct StatTile: View {
    var title: LocalizedStringKey
    var value: String
    var symbol: String
    var tint: Color = .accentColor
    var caption: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(title).font(.subheadline).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
            Text(value)
                .font(.title2.weight(.semibold))
                .monospacedDigit()
                .contentTransition(.numericText())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            if let caption {
                Text(caption).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
    }
}

struct ProgressRing: View {
    var progress: Double
    var lineWidth: CGFloat = 10
    var tint: Color = .accentColor

    var body: some View {
        ZStack {
            Circle().stroke(tint.opacity(0.15), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: max(0.003, min(progress, 1)))
                .stroke(tint, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.snappy, value: progress)
        }
    }
}

struct InitialsAvatar: View {
    var name: String
    var size: CGFloat = 44
    private var initials: String {
        name.split(separator: " ").prefix(2).map { String($0.prefix(1)).uppercased() }.joined()
    }
    private var hue: Double {
        Double(abs(name.hashValue) % 360) / 360
    }
    var body: some View {
        Text(initials.isEmpty ? "?" : initials)
            .font(.system(size: size * 0.38, weight: .semibold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Color(hue: hue, saturation: 0.55, brightness: 0.75).gradient, in: .circle)
    }
}

struct StatusPill: View {
    var text: String
    var tint: Color
    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(tint.opacity(0.14), in: .capsule)
            .foregroundStyle(tint)
    }
}

struct SectionTitle: View {
    var title: LocalizedStringKey
    var subtitle: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.title3.weight(.semibold))
            if let subtitle { Text(subtitle).font(.subheadline).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct LoanRow: View {
    var loan: LoanDTO
    var showBorrower = true
    var currency: String = "USD"

    private var statusText: String {
        if loan.status == .paid { return tr("Paid off") }
        if loan.status == .cancelled { return tr("Cancelled") }
        if loan.state.overdueCents > 0 { return tr("\(Money.format(loan.state.overdueCents, code: currency)) overdue") }
        if let d = loan.state.nextDueDate, let amt = loan.state.nextDueCents {
            return tr("\(Money.format(amt, code: currency)) due \(Dates.relative(d))")
        }
        return tr("Balance due now")
    }
    private var tint: Color {
        Theme.tint(forStatus: loan.status, overdue: loan.state.overdueCents > 0 && loan.status == .active)
    }

    var body: some View {
        HStack(spacing: 14) {
            ProgressRing(progress: loan.state.progress, lineWidth: 5, tint: tint)
                .frame(width: 40, height: 40)
                .overlay {
                    Image(systemName: loan.interestType.symbol).font(.caption2.weight(.bold)).foregroundStyle(tint)
                }
            VStack(alignment: .leading, spacing: 3) {
                Text(loan.title).font(.body.weight(.medium))
                Text(showBorrower ? "\(loan.borrowerName) · \(statusText)" : statusText)
                    .font(.subheadline).foregroundStyle(loan.state.overdueCents > 0 && loan.status == .active ? Theme.overdue : .secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                Text(Money.format(loan.state.balanceCents, code: currency)).font(.body.weight(.semibold)).monospacedDigit()
                Text("of \(Money.format(loan.state.totalDueCents, code: currency))").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
        .contentShape(.rect)
    }
}

struct PaymentRow: View {
    var payment: PaymentDTO
    var showLoan = true
    var currency: String = "USD"
    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: payment.voided ? "xmark.circle" : payment.method.symbol)
                .font(.body.weight(.semibold))
                .foregroundStyle(payment.voided ? Color.secondary : Color.accentColor)
                .frame(width: 40, height: 40)
                .background(Color(.secondarySystemGroupedBackground), in: .circle)
            VStack(alignment: .leading, spacing: 3) {
                Text(showLoan ? (payment.borrowerName ?? payment.loanTitle ?? tr("Payment")) : payment.method.label)
                    .font(.body.weight(.medium))
                Text(showLoan ? "\(payment.receiptCode) · \(Dates.short(payment.paidOn)) · \(payment.loanTitle ?? "")"
                              : "\(payment.receiptCode) · \(Dates.medium(payment.paidOn))")
                    .font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Text(Money.format(payment.amountCents, code: currency))
                .font(.body.weight(.semibold)).monospacedDigit()
                .strikethrough(payment.voided)
                .foregroundStyle(payment.voided ? .secondary : .primary)
        }
        .padding(.vertical, 4)
        .contentShape(.rect)
    }
}

struct EmptyCard: View {
    var symbol: String
    var title: LocalizedStringKey
    var message: LocalizedStringKey
    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: symbol)
        } description: {
            Text(message)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
    }
}

struct LabeledValue: View {
    var label: LocalizedStringKey
    var value: String
    var body: some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).monospacedDigit().multilineTextAlignment(.trailing)
        }
    }
}
