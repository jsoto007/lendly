import SwiftUI

struct RecordPaymentView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let loan: LoanDTO
    @State private var amount: Decimal?
    @State private var paidOn = Date.now
    @State private var method: PaymentMethod = .cash
    @State private var note = ""
    @State private var busy = false
    @State private var error: APIError?
    @State private var created: PaymentDTO?
    @State private var attemptKey = UUID().uuidString

    private var currency: String { model.currency }
    private var amountCents: Int { Money.cents(from: amount ?? 0) }
    private var remainingAfter: Int { max(loan.state.balanceCents - amountCents, 0) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Text("Amount")
                        Spacer()
                        DecimalField(placeholder: "0.00", value: $amount, prefix: "$", font: .title3.weight(.semibold))
                    }
                    HStack(spacing: 8) {
                        if let next = loan.state.nextDueCents, next > 0 {
                            chip("Installment", next)
                        }
                        if loan.state.overdueCents > 0 { chip("Overdue", loan.state.overdueCents) }
                        chip("Pay off", loan.state.balanceCents)
                    }
                    .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 10, trailing: 16))
                } header: {
                    Text("\(loan.borrowerName) · \(loan.title)")
                } footer: {
                    if amountCents > loan.state.balanceCents {
                        Text("That's more than the \(Money.format(loan.state.balanceCents, code: currency)) remaining.").foregroundStyle(Theme.overdue)
                    } else if amountCents > 0 {
                        if loan.interestType == .compound, Dates.dayString(paidOn) < Dates.dayString(.now) {
                            Text("About \(Money.format(remainingAfter, code: currency)) will remain; a back-dated payment on a compound loan reduces interest, so the receipt may show less.")
                        } else {
                            Text(remainingAfter == 0 ? "This pays the loan off. 🎉" : "\(Money.format(remainingAfter, code: currency)) will remain after this payment.")
                        }
                    } else {
                        Text("Remaining balance: \(Money.format(loan.state.balanceCents, code: currency))")
                    }
                }
                Section("Details") {
                    DatePicker("Date", selection: $paidOn, in: (Dates.day(loan.startDate) ?? .distantPast)...Date.now, displayedComponents: .date)
                    Picker("Method", selection: $method) {
                        ForEach(PaymentMethod.allCases) { Label($0.label, systemImage: $0.symbol).tag($0) }
                    }
                    TextField("Note (optional)", text: $note, axis: .vertical)
                }
            }
            .navigationTitle("Record payment")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Save") { Task { await save() } }
                            .disabled(amountCents <= 0 || amountCents > loan.state.balanceCents)
                    }
                }
            }
            .navigationDestination(item: $created) { p in
                ReceiptView(paymentID: p.id, justCreated: true, onDone: { dismiss() })
            }
            .apiErrorAlert($error)
        }
    }

    private func chip(_ label: String, _ cents: Int) -> some View {
        Button {
            amount = Decimal(cents) / 100
        } label: {
            VStack(spacing: 1) {
                Text(label).font(.caption2).foregroundStyle(.secondary)
                Text(Money.format(cents, code: currency)).font(.caption.weight(.semibold)).monospacedDigit()
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
        }
        .buttonStyle(.bordered)
        .buttonBorderShape(.capsule)
    }

    private func save() async {
        busy = true; defer { busy = false }
        do {
            let r = try await model.api.recordPayment(loanID: loan.id, PaymentBody(
                amountCents: amountCents, paidOn: Dates.dayString(paidOn), method: method,
                note: note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : note,
                idempotencyKey: attemptKey))
            created = r.payment
        } catch let e as APIError { error = e } catch {}
    }
}
