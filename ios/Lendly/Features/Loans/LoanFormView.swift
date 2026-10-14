import SwiftUI

struct LoanFormView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let borrower: BorrowerDTO?
    let existing: LoanDTO?

    @State private var borrowers: [BorrowerDTO] = []
    @State private var selectedBorrowerID: String?
    @State private var title = ""
    @State private var amount: Decimal?
    @State private var interestType: InterestType = .simple
    @State private var ratePercent: Decimal?
    @State private var fee: Decimal?
    @State private var feePerPeriod = false
    @State private var schedule: ScheduleKind = .monthly
    @State private var term = 4
    @State private var startDate = Date.now
    @State private var notes = ""
    @State private var preview: PreviewResponse?
    @State private var previewError: String?
    @State private var busy = false
    @State private var error: APIError?
    @State private var showNewBorrower = false

    private var currency: String { model.currency }
    private var termsLocked: Bool { !(existing?.payments ?? []).filter { !$0.voided }.isEmpty }

    private var terms: LoanTermsBody? {
        guard let amount, amount > 0 else { return nil }
        let rate = interestType == .fixed ? 0 : Money.bps(fromPercent: ratePercent ?? 0)
        let feeCents = interestType == .fixed ? Money.cents(from: fee ?? 0) : 0
        return LoanTermsBody(borrowerId: selectedBorrowerID, title: title.isEmpty ? nil : title, principalCents: Money.cents(from: amount),
                             interestType: interestType, rateBps: rate, fixedFeeCents: feeCents, fixedFeePerPeriod: interestType == .fixed && feePerPeriod,
                             schedule: schedule, termPeriods: term, startDate: Dates.dayString(startDate),
                             notes: notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? (existing == nil ? nil : "") : notes)
    }

    var body: some View {
        NavigationStack {
            Form {
                if existing == nil {
                    Section("Who") {
                        if let borrower {
                            Label(borrower.name, systemImage: "person.fill")
                        } else {
                            Picker("Borrower", selection: $selectedBorrowerID) {
                                Text("Choose…").tag(String?.none)
                                ForEach(borrowers) { Text($0.name).tag(String?.some($0.id)) }
                            }
                            Button { showNewBorrower = true } label: { Label("New borrower", systemImage: "person.badge.plus") }
                        }
                    }
                }
                Section("Loan") {
                    TextField("What is it for? (e.g. Car repair)", text: $title)
                    HStack {
                        Text("Amount")
                        Spacer()
                        DecimalField(placeholder: "0.00", value: $amount, prefix: "$")
                    }
                    DatePicker("Start date", selection: $startDate, displayedComponents: .date)
                }
                .disabled(termsLocked)

                Section {
                    Picker("Interest", selection: $interestType) {
                        ForEach(InterestType.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    switch interestType {
                    case .compound:
                        rateField(tr("Rate per \(schedule.periodNoun)"))
                    case .simple:
                        rateField(tr("Interest on the amount"))
                    case .fixed:
                        HStack {
                            Text("Fee")
                            Spacer()
                            DecimalField(placeholder: "0.00", value: $fee, prefix: "$")
                        }
                        Toggle("Charge every \(schedule.periodNoun)", isOn: $feePerPeriod)
                    }
                } header: {
                    Text("Interest")
                } footer: {
                    Text(interestType.explanation)
                }
                .disabled(termsLocked)

                Section {
                    Picker("Paid", selection: $schedule) {
                        ForEach(ScheduleKind.allCases) { Text($0.label).tag($0) }
                    }
                    Stepper(value: $term, in: 1...120) {
                        HStack { Text("Payments"); Spacer(); Text("\(term)").monospacedDigit().foregroundStyle(.secondary) }
                    }
                } header: {
                    Text("Repayment")
                } footer: {
                    if termsLocked {
                        Text("Terms are locked because a payment has been recorded. Void the payments to change them.")
                    } else {
                        Text("\(plural(term, one: "1 payment", other: "\(term) payments")), \(schedule.label.lowercased()), over \(schedule.termLabel(term)).")
                    }
                }
                .disabled(termsLocked)

                Section {
                    previewSection
                } header: { Text("Preview") }

                Section("Notes") {
                    TextField("Optional", text: $notes, axis: .vertical).lineLimit(2...5)
                }
            }
            .navigationTitle(existing == nil ? tr("New loan") : tr("Edit loan"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button(existing == nil ? tr("Create") : tr("Save")) { Task { await save() } }
                            .disabled(terms == nil || (existing == nil && selectedBorrowerID == nil))
                    }
                }
            }
            .task { await loadBorrowers() }
            .task(id: terms) { await refreshPreview() }
            .onAppear(perform: seed)
            .sheet(isPresented: $showNewBorrower) {
                BorrowerFormView(existing: nil) { created in
                    borrowers.append(created)
                    borrowers.sort { $0.name < $1.name }
                    selectedBorrowerID = created.id
                }
            }
            .apiErrorAlert($error)
        }
    }

    private func rateField(_ label: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            DecimalField(placeholder: "0", value: $ratePercent, suffix: "%").frame(maxWidth: 120)
        }
    }

    @ViewBuilder
    private var previewSection: some View {
        if let p = preview {
            LabeledValue(label: "Total to repay", value: Money.format(p.state.totalDueCents, code: currency))
            LabeledValue(label: "Interest", value: "+" + Money.format(p.state.interestCents, code: currency))
            LabeledValue(label: "Each payment", value: Money.format(p.state.installmentCents, code: currency))
            LabeledValue(label: "First due", value: Dates.medium(p.installments.first?.dueDate ?? ""))
            LabeledValue(label: "Last due", value: Dates.medium(p.endDate))
        } else if let previewError {
            Label(previewError, systemImage: "exclamationmark.circle").foregroundStyle(Theme.overdue).font(.subheadline)
        } else {
            Text("Enter an amount to see the repayment plan.").foregroundStyle(.secondary).font(.subheadline)
        }
    }

    private func seed() {
        if let borrower { selectedBorrowerID = borrower.id }
        guard let existing else { return }
        selectedBorrowerID = existing.borrowerId
        title = existing.title
        amount = Decimal(existing.principalCents) / 100
        interestType = existing.interestType
        ratePercent = existing.rateBps == 0 ? nil : Decimal(existing.rateBps) / 100
        fee = existing.fixedFeeCents == 0 ? nil : Decimal(existing.fixedFeeCents) / 100
        feePerPeriod = existing.fixedFeePerPeriod
        schedule = existing.schedule
        term = existing.termPeriods
        startDate = Dates.day(existing.startDate) ?? .now
        notes = existing.notes ?? ""
    }

    private func loadBorrowers() async {
        guard existing == nil, borrower == nil else { return }
        borrowers = (try? await model.api.borrowers()) ?? []
    }

    private func refreshPreview() async {
        guard let terms else { preview = nil; previewError = nil; return }
        try? await Task.sleep(for: .milliseconds(250))
        guard !Task.isCancelled else { return }
        do {
            preview = try await model.api.previewLoan(terms)
            previewError = nil
        } catch let e as APIError {
            preview = nil
            previewError = e.message
        } catch {}
    }

    private func save() async {
        guard let terms else { return }
        busy = true; defer { busy = false }
        do {
            if let existing {
                var body = terms
                body.borrowerId = nil
                if termsLocked {
                    // Only title/notes are editable once a payment exists; sending any term key is a 409.
                    _ = try await model.api.updateLoanMeta(existing.id, title: body.title ?? existing.title,
                                                           notes: notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : notes)
                } else {
                    _ = try await model.api.updateLoan(existing.id, body)
                }
            } else {
                _ = try await model.api.createLoan(terms)
            }
            dismiss()
        } catch let e as APIError { error = e } catch {}
    }
}
