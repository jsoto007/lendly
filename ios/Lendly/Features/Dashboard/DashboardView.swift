import Charts
import SwiftUI

struct DashboardView: View {
    @Environment(AppModel.self) private var model
    @State private var data: DashboardDTO?
    @State private var error: APIError?
    @State private var loadedOnce = false
    @State private var showNewLoan = false
    @State private var showNewBorrower = false

    private var currency: String { model.currency }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let data {
                    content(data)
                } else if loadedOnce {
                    EmptyCard(symbol: "wifi.exclamationmark", title: "Couldn't load", message: "Pull to try again.")
                        .padding(20)
                } else {
                    ProgressView().padding(.top, 80)
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Dashboard")
            .navigationSubtitle(model.current?.tenantName ?? "")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { showNewLoan = true } label: { Label("New loan", systemImage: "banknote") }
                        Button { showNewBorrower = true } label: { Label("New borrower", systemImage: "person.badge.plus") }
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .refreshable { await load() }
            .task { await load() }
            .navigationDestination(for: LoanDTO.self) { LoanDetailView(loanID: $0.id, initial: $0) }
            .navigationDestination(for: PaymentDTO.self) { ReceiptView(paymentID: $0.id) }
            .navigationDestination(for: UpcomingDTO.self) { LoanDetailView(loanID: $0.loanId, initial: nil) }
            .sheet(isPresented: $showNewLoan, onDismiss: { Task { await load() } }) { LoanFormView(borrower: nil, existing: nil) }
            .sheet(isPresented: $showNewBorrower, onDismiss: { Task { await load() } }) { BorrowerFormView(existing: nil) }
            .apiErrorAlert($error)
        }
    }

    @ViewBuilder
    private func content(_ d: DashboardDTO) -> some View {
        VStack(spacing: 24) {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                StatTile(title: "Outstanding", value: Money.format(d.totals.outstandingCents, code: currency), symbol: "clock.arrow.circlepath",
                         caption: plural(d.totals.activeLoans, one: "1 active loan", other: "\(d.totals.activeLoans) active loans"))
                StatTile(title: "Overdue", value: Money.format(d.totals.overdueCents, code: currency), symbol: "exclamationmark.triangle.fill",
                         tint: d.totals.overdueCents > 0 ? Theme.overdue : .secondary,
                         caption: d.overdue.isEmpty ? tr("All caught up") : plural(d.overdue.count, one: "1 loan behind", other: "\(d.overdue.count) loans behind"))
                StatTile(title: "Collected", value: Money.format(d.totals.collectedCents, code: currency), symbol: "checkmark.seal.fill", tint: Theme.good,
                         caption: tr("\(d.totals.paidLoans) paid off"))
                StatTile(title: "Lent out", value: Money.format(d.totals.lentCents, code: currency), symbol: "arrow.up.right.circle.fill", tint: .blue,
                         caption: tr("+\(Money.format(d.totals.projectedInterestCents, code: currency)) interest expected"))
            }

            if !d.overdue.isEmpty {
                section("Needs attention", subtitle: tr("Payments that are behind schedule")) {
                    ForEach(d.overdue) { loan in
                        NavigationLink(value: loan) {
                            HStack(spacing: 14) {
                                InitialsAvatar(name: loan.borrowerName, size: 40)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(loan.borrowerName).font(.body.weight(.medium))
                                    Text("\(loan.title) · \(plural(loan.state.daysOverdue, one: "1 day late", other: "\(loan.state.daysOverdue) days late"))")
                                        .font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                                }
                                Spacer()
                                Text(Money.format(loan.state.overdueCents, code: currency))
                                    .font(.body.weight(.semibold)).monospacedDigit().foregroundStyle(Theme.overdue)
                                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                            }
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        if loan.id != d.overdue.last?.id { Divider() }
                    }
                }
            }

            section("Upcoming", subtitle: tr("Due in the next 30 days")) {
                if d.upcoming.isEmpty {
                    Text("Nothing due in the next 30 days.").font(.subheadline).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    ForEach(d.upcoming) { u in
                        NavigationLink(value: u) {
                            HStack(spacing: 14) {
                                VStack(spacing: 0) {
                                    Text(Dates.day(u.dueDate)?.formatted(.dateTime.month(.abbreviated)) ?? "")
                                        .font(.caption2.weight(.semibold)).textCase(.uppercase).foregroundStyle(.secondary)
                                    Text(Dates.day(u.dueDate)?.formatted(.dateTime.day()) ?? "")
                                        .font(.title3.weight(.bold)).monospacedDigit()
                                }
                                .frame(width: 44)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(u.borrowerName).font(.body.weight(.medium))
                                    Text("\(u.title) · \(Dates.relative(u.dueDate))").font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                                }
                                Spacer()
                                Text(Money.format(u.amountCents, code: currency)).font(.body.weight(.semibold)).monospacedDigit()
                                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                            }
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        if u.id != d.upcoming.last?.id { Divider() }
                    }
                }
            }

            section("Collected by month", subtitle: tr("Last 6 months")) {
                Chart(d.monthlyCollected) { point in
                    BarMark(x: .value("Month", Dates.monthLabel(point.month)),
                            y: .value("Collected", Double(point.cents) / 100))
                    .foregroundStyle(Color.accentColor.gradient)
                    .cornerRadius(6)
                }
                .chartYAxis {
                    AxisMarks(position: .leading) { value in
                        AxisGridLine()
                        AxisValueLabel {
                            if let v = value.as(Double.self) { Text(Money.compact(Int(v * 100), code: currency)) }
                        }
                    }
                }
                .frame(height: 160)
            }

            section("Recent payments", subtitle: nil) {
                if d.recentPayments.isEmpty {
                    Text("No payments recorded yet.").font(.subheadline).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    ForEach(d.recentPayments) { p in
                        NavigationLink(value: p) { PaymentRow(payment: p, currency: currency) }.buttonStyle(.plain)
                        if p.id != d.recentPayments.last?.id { Divider() }
                    }
                }
            }
        }
        .padding(16)
        .padding(.bottom, 24)
    }

    private func section<Content: View>(_ title: LocalizedStringKey, subtitle: String?, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: title, subtitle: subtitle)
            VStack(spacing: 8) { content() }
                .padding(16)
                .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
        }
    }

    private func load() async {
        do {
            data = try await model.api.dashboard()
        } catch let e as APIError {
            if data == nil { error = e }
        } catch {}
        loadedOnce = true
    }
}
