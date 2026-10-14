import SwiftUI

struct LoansView: View {
    @Environment(AppModel.self) private var model
    @State private var loans: [LoanDTO] = []
    @State private var loaded = false
    @State private var filter: Filter = .active
    @State private var search = ""
    @State private var showNew = false
    @State private var error: APIError?

    enum Filter: String, CaseIterable, Identifiable {
        case active, overdue, paid, all
        var id: String { rawValue }
        var label: String {
            switch self {
            case .active: tr("Active")
            case .overdue: tr("Overdue")
            case .paid: tr("Paid")
            case .all: tr("All")
            }
        }
    }

    private var filtered: [LoanDTO] {
        var out = loans
        switch filter {
        case .active: out = out.filter { $0.status == .active }
        case .overdue: out = out.filter { $0.status == .active && $0.state.overdueCents > 0 }
        case .paid: out = out.filter { $0.status == .paid }
        case .all: break
        }
        if !search.isEmpty {
            out = out.filter { $0.title.localizedCaseInsensitiveContains(search) || $0.borrowerName.localizedCaseInsensitiveContains(search) }
        }
        return out
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Filter", selection: $filter) {
                        ForEach(Filter.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                }
                if loaded && filtered.isEmpty {
                    ContentUnavailableView {
                        Label(loans.isEmpty ? tr("No loans yet") : tr("Nothing here"), systemImage: "banknote")
                    } description: {
                        Text(loans.isEmpty ? tr("Create a loan to start tracking payments and receipts.") : tr("No loans match this filter."))
                    } actions: {
                        if loans.isEmpty { Button("New loan") { showNew = true }.buttonStyle(.borderedProminent) }
                    }
                    .listRowBackground(Color.clear)
                }
                ForEach(filtered) { loan in
                    NavigationLink(value: loan) { LoanRow(loan: loan, currency: model.currency) }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $search, prompt: "Search loans")
            .navigationTitle("Loans")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button { showNew = true } label: { Image(systemName: "plus") } }
            }
            .refreshable { await load() }
            .task { await load() }
            .navigationDestination(for: LoanDTO.self) { LoanDetailView(loanID: $0.id, initial: $0) }
            .sheet(isPresented: $showNew, onDismiss: { Task { await load() } }) { LoanFormView(borrower: nil, existing: nil) }
            .apiErrorAlert($error)
        }
    }

    private func load() async {
        do { loans = try await model.api.loans() }
        catch let e as APIError { if loans.isEmpty { error = e } } catch {}
        loaded = true
    }
}

struct LoanDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let loanID: String
    @State var initial: LoanDTO?
    @State private var loan: LoanDTO?
    @State private var tab: Tab = .schedule
    @State private var showPayment = false
    @State private var showEdit = false
    @State private var confirmCancel = false
    @State private var confirmDelete = false
    @State private var error: APIError?

    enum Tab: String, CaseIterable, Identifiable {
        case schedule, payments
        var id: String { rawValue }
        var label: String { self == .schedule ? tr("Schedule") : tr("Payments") }
    }

    private var currency: String { model.currency }
    private var canRecord: Bool { model.isAdmin && loan?.status == .active }

    var body: some View {
        ScrollView {
            if let loan {
                VStack(spacing: 20) {
                    hero(loan)
                    facts(loan)
                    Picker("Section", selection: $tab) {
                        ForEach(Tab.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    switch tab {
                    case .schedule: schedule(loan)
                    case .payments: payments(loan)
                    }
                }
                .padding(16)
                .padding(.bottom, canRecord ? 72 : 16)
            } else if initial == nil {
                ProgressView().padding(.top, 80)
            }
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(loan?.title ?? initial?.title ?? tr("Loan"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if model.isAdmin, let loan {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { showEdit = true } label: { Label("Edit loan", systemImage: "pencil") }
                        if loan.status == .cancelled {
                            Button { Task { await setStatus(.active) } } label: { Label("Reactivate", systemImage: "arrow.uturn.backward") }
                        } else if loan.status == .active {
                            Button(role: .destructive) { confirmCancel = true } label: { Label("Cancel loan", systemImage: "xmark.circle") }
                        }
                        if (loan.payments ?? []).isEmpty {
                            Button(role: .destructive) { confirmDelete = true } label: { Label("Delete loan", systemImage: "trash") }
                        }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            if canRecord {
                Button {
                    showPayment = true
                } label: {
                    Label("Record payment", systemImage: "plus.circle.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                }
                .buttonStyle(.glassProminent)
                .controlSize(.large)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)
            }
        }
        .task {
            if loan == nil, let initial, initial.installments != nil { loan = initial }
            await load()
        }
        .refreshable { await load() }
        .navigationDestination(for: PaymentDTO.self) { ReceiptView(paymentID: $0.id) }
        .sheet(isPresented: $showPayment, onDismiss: { Task { await load() } }) {
            if let loan { RecordPaymentView(loan: loan) }
        }
        .sheet(isPresented: $showEdit, onDismiss: { Task { await load() } }) {
            if let loan { LoanFormView(borrower: nil, existing: loan) }
        }
        .confirmationDialog("Cancel this loan?", isPresented: $confirmCancel, titleVisibility: .visible) {
            Button("Cancel loan", role: .destructive) { Task { await setStatus(.cancelled) } }
        } message: {
            Text("It stays in history and can be reactivated. No new payments can be recorded while cancelled.")
        }
        .confirmationDialog("Delete this loan?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { Task { await deleteLoan() } }
        } message: {
            Text("This loan has no payments, so it can be removed completely.")
        }
        .apiErrorAlert($error)
    }

    private func hero(_ loan: LoanDTO) -> some View {
        let overdue = loan.status == .active && loan.state.overdueCents > 0
        let tint = Theme.tint(forStatus: loan.status, overdue: overdue)
        return VStack(spacing: 16) {
            ZStack {
                ProgressRing(progress: loan.state.progress, lineWidth: 14, tint: tint)
                    .frame(width: 168, height: 168)
                VStack(spacing: 2) {
                    Text(loan.state.isPaidOff ? tr("Paid") : tr("Remaining")).font(.caption).foregroundStyle(.secondary).textCase(.uppercase)
                    Text(Money.format(loan.state.balanceCents, code: currency))
                        .font(.title2.weight(.bold)).monospacedDigit().contentTransition(.numericText())
                        .lineLimit(1).minimumScaleFactor(0.6).frame(maxWidth: 130)
                    Text("\(Int((loan.state.progress * 100).rounded()))% paid").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(.top, 8)
            HStack(spacing: 8) {
                NavigationLink(value: BorrowerDTO(id: loan.borrowerId, name: loan.borrowerName, linked: false, archived: false, createdAt: "")) {
                    HStack(spacing: 6) { InitialsAvatar(name: loan.borrowerName, size: 22); Text(loan.borrowerName) }
                }
                .buttonStyle(.plain)
                .disabled(!model.isAdmin)
                Text("·").foregroundStyle(.tertiary)
                StatusPill(text: loan.status == .active ? (overdue ? tr("Overdue") : tr("On track")) : loan.status.label, tint: tint)
            }
            .font(.subheadline)
            if loan.status == .active {
                if overdue {
                    Label("\(Money.format(loan.state.overdueCents, code: currency)) overdue · \(plural(loan.state.daysOverdue, one: "1 day late", other: "\(loan.state.daysOverdue) days late"))",
                          systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.medium)).foregroundStyle(Theme.overdue)
                } else if let d = loan.state.nextDueDate, let a = loan.state.nextDueCents {
                    Label("Next: \(Money.format(a, code: currency)) on \(Dates.medium(d))", systemImage: "calendar")
                        .font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .navigationDestination(for: BorrowerDTO.self) { BorrowerDetailView(borrowerID: $0.id) }
    }

    private func facts(_ loan: LoanDTO) -> some View {
        VStack(spacing: 10) {
            LabeledValue(label: "Lent", value: Money.format(loan.principalCents, code: currency))
            Divider()
            HStack {
                Label(loan.interestType.label, systemImage: loan.interestType.symbol)
                    .foregroundStyle(Theme.tint(for: loan.interestType))
                Spacer()
                Text(loan.termsSummary).monospacedDigit()
            }
            Divider()
            LabeledValue(label: "Interest", value: "+" + Money.format(loan.state.interestCents, code: currency))
            Divider()
            LabeledValue(label: "Total to repay", value: Money.format(loan.state.totalDueCents, code: currency))
            Divider()
            LabeledValue(label: "Payments", value: "\(loan.termPeriods) × \(Money.format(loan.state.installmentCents, code: currency)), \(loan.schedule.label.lowercased())")
            Divider()
            LabeledValue(label: "Started", value: Dates.medium(loan.startDate))
            if let notes = loan.notes, !notes.isEmpty {
                Divider()
                Text(notes).font(.subheadline).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .font(.subheadline)
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
    }

    @ViewBuilder
    private func schedule(_ loan: LoanDTO) -> some View {
        if let installments = loan.installments {
            VStack(spacing: 0) {
                ForEach(installments) { inst in
                    HStack(spacing: 14) {
                        Image(systemName: inst.status == "paid" ? "checkmark.circle.fill" : (inst.status == "overdue" ? "exclamationmark.circle.fill" : (inst.partial ? "circle.lefthalf.filled" : "circle")))
                            .foregroundStyle(Theme.tint(forInstallment: inst.status))
                            .font(.title3)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Payment \(inst.number) of \(installments.count)").font(.body.weight(.medium))
                            Text(Dates.long(inst.dueDate)).font(.subheadline).foregroundStyle(inst.status == "overdue" ? Theme.overdue : .secondary)
                        }
                        Spacer()
                        Text(Money.format(inst.amountCents, code: currency)).monospacedDigit()
                            .foregroundStyle(inst.status == "paid" ? .secondary : .primary)
                    }
                    .padding(.vertical, 10)
                    if inst.id != installments.last?.id { Divider() }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
        }
    }

    @ViewBuilder
    private func payments(_ loan: LoanDTO) -> some View {
        let list = loan.payments ?? []
        if list.isEmpty {
            if model.isAdmin {
                EmptyCard(symbol: "receipt", title: "No payments yet", message: "Record the first payment to generate a receipt.")
            } else {
                EmptyCard(symbol: "receipt", title: "No payments yet", message: "Payments will appear here once your lender records them.")
            }
        } else {
            VStack(spacing: 0) {
                ForEach(list) { p in
                    NavigationLink(value: p) { PaymentRow(payment: p, showLoan: false, currency: currency) }.buttonStyle(.plain)
                        .padding(.vertical, 6)
                    if p.id != list.last?.id { Divider() }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
        }
    }

    private func load() async {
        do { loan = try await model.api.loan(loanID) }
        catch let e as APIError { if loan == nil { error = e } } catch {}
    }

    private func setStatus(_ status: LoanStatus) async {
        do { loan = try await model.api.setLoanStatus(loanID, status) }
        catch let e as APIError { error = e } catch {}
    }

    private func deleteLoan() async {
        do { try await model.api.deleteLoan(loanID); dismiss() }
        catch let e as APIError { error = e } catch {}
    }
}
