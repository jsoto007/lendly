import SwiftUI

/// Read-only home for someone who was invited to follow their loans.
struct BorrowerHomeView: View {
    @Environment(AppModel.self) private var model
    @State private var data: PortalDTO?
    @State private var loadedOnce = false
    @State private var error: APIError?
    @State private var showSettings = false

    private var currency: String { data?.lender.currency ?? model.currency }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let d = data {
                    content(d)
                } else if loadedOnce {
                    EmptyCard(symbol: "wifi.exclamationmark", title: "Couldn't load", message: "Pull to try again.").padding(20)
                } else {
                    ProgressView().padding(.top, 80)
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Your loans")
            .navigationSubtitle(data.map { "with \($0.lender.name)" } ?? "")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "person.crop.circle") }
                }
            }
            .refreshable { await load() }
            .task { await load() }
            .navigationDestination(for: LoanDTO.self) { LoanDetailView(loanID: $0.id, initial: $0) }
            .navigationDestination(for: PaymentDTO.self) { ReceiptView(paymentID: $0.id) }
            .sheet(isPresented: $showSettings) { NavigationStack { SettingsView() } }
            .apiErrorAlert($error)
        }
    }

    @ViewBuilder
    private func content(_ d: PortalDTO) -> some View {
        let s = d.borrower.summary
        VStack(spacing: 24) {
            VStack(spacing: 10) {
                Text("Hi \(d.borrower.name.split(separator: " ").first.map(String.init) ?? d.borrower.name)")
                    .font(.title2.weight(.bold))
                if let s {
                    Text(s.outstandingCents == 0 ? "You're all paid up." : "You owe \(Money.format(s.outstandingCents, code: currency)) in total.")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 8)

            if let s {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    StatTile(title: "Remaining", value: Money.format(s.outstandingCents, code: currency), symbol: "clock.arrow.circlepath")
                    StatTile(title: "Paid so far", value: Money.format(s.paidCents, code: currency), symbol: "checkmark.seal.fill", tint: Theme.good)
                    if s.overdueCents > 0 {
                        StatTile(title: "Overdue", value: Money.format(s.overdueCents, code: currency), symbol: "exclamationmark.triangle.fill", tint: Theme.overdue)
                    }
                    StatTile(title: "Borrowed", value: Money.format(s.lentCents, code: currency), symbol: "arrow.down.left.circle.fill", tint: .blue)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionTitle(title: "Loans")
                if d.loans.isEmpty {
                    EmptyCard(symbol: "banknote", title: "No loans yet", message: "When \(d.lender.name) creates a loan for you it shows up here.")
                } else {
                    VStack(spacing: 8) {
                        ForEach(d.loans) { loan in
                            NavigationLink(value: loan) { LoanRow(loan: loan, showBorrower: false, currency: currency) }.buttonStyle(.plain)
                            if loan.id != d.loans.last?.id { Divider() }
                        }
                    }
                    .padding(16)
                    .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionTitle(title: "Receipts", subtitle: d.payments.isEmpty ? nil : "\(d.payments.count) payment\(d.payments.count == 1 ? "" : "s")")
                if d.payments.isEmpty {
                    Text("Receipts appear here as payments are recorded.").font(.subheadline).foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 8) {
                        ForEach(d.payments) { p in
                            NavigationLink(value: p) { PaymentRow(payment: p, currency: currency) }.buttonStyle(.plain)
                            if p.id != d.payments.last?.id { Divider() }
                        }
                    }
                    .padding(16)
                    .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
                }
            }
        }
        .padding(16)
        .padding(.bottom, 24)
    }

    private func load() async {
        do { data = try await model.api.portal() }
        catch let e as APIError { if data == nil { error = e } } catch {}
        loadedOnce = true
    }
}
