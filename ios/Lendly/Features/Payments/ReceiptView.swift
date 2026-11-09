import SwiftUI
import UIKit

struct ReceiptView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let paymentID: String
    var justCreated = false
    /// Dismisses the enclosing sheet when the receipt was pushed right after recording a payment.
    var onDone: (() -> Void)? = nil
    @State private var receipt: ReceiptDTO?
    @State private var pdfURL: URL?
    @State private var confirmVoid = false
    @State private var voidReason = ""
    @State private var error: APIError?

    private var currency: String { receipt?.payment.currency ?? model.currency }

    var body: some View {
        ScrollView {
            if let r = receipt {
                VStack(spacing: 20) {
                    if justCreated, !r.payment.voided {
                        Label("Payment recorded", systemImage: "checkmark.circle.fill")
                            .font(.headline).foregroundStyle(Theme.good)
                            .padding(.top, 8)
                    }
                    ReceiptCard(receipt: r, currency: currency)
                        .padding(.horizontal, 4)
                    if let pdfURL {
                        ShareLink(item: pdfURL, preview: SharePreview(tr("Receipt \(r.payment.receiptCode)"), image: Image(systemName: "doc.richtext"))) {
                            Label("Share receipt (PDF)", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity).frame(height: 36)
                        }
                        .buttonStyle(.glassProminent)
                        .controlSize(.large)
                    }
                }
                .padding(16)
            } else {
                ProgressView().padding(.top, 80)
            }
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(receipt?.payment.receiptCode ?? tr("Receipt"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if justCreated {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { if let onDone { onDone() } else { dismiss() } } }
            }
            if model.isAdmin, let r = receipt, !r.payment.voided {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(role: .destructive) { confirmVoid = true } label: { Label("Void payment", systemImage: "xmark.circle") }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
        }
        .task { await load() }
        .alert("Void this payment?", isPresented: $confirmVoid) {
            TextField("Reason (optional)", text: $voidReason)
            Button("Void", role: .destructive) { Task { await void() } }
            Button("Keep", role: .cancel) {}
        } message: {
            Text("The receipt stays in history marked as void and the balance goes back up.")
        }
        .apiErrorAlert($error)
    }

    private func load() async {
        do {
            receipt = try await model.api.receipt(paymentID)
            if let receipt { pdfURL = ReceiptPDF.render(receipt, currency: currency) }
        } catch let e as APIError { error = e } catch {}
    }

    private func void() async {
        do {
            _ = try await model.api.voidPayment(paymentID, reason: voidReason.isEmpty ? nil : voidReason)
            await load()
        } catch let e as APIError { error = e } catch {}
    }
}

/// The receipt itself. Rendered on screen and into the PDF.
struct ReceiptCard: View {
    let receipt: ReceiptDTO
    var currency: String

    var body: some View {
        let p = receipt.payment
        VStack(spacing: 0) {
            VStack(spacing: 6) {
                Text(receipt.lender.name).font(.title3.weight(.bold))
                Text("Payment receipt").font(.subheadline).foregroundStyle(.secondary)
            }
            .padding(.top, 24).padding(.bottom, 16)
            Text(Money.format(p.amountCents, code: currency))
                .font(.system(size: 40, weight: .bold, design: .rounded)).monospacedDigit()
                .strikethrough(p.voided)
            Text(Dates.long(p.paidOn)).font(.subheadline).foregroundStyle(.secondary).padding(.top, 2)
            if p.voided {
                Text("VOIDED \(Dates.localDay(p.voidedAt ?? "").uppercased())\(p.voidReason.map { " · \($0)" } ?? "")")
                    .font(.caption.weight(.bold)).foregroundStyle(Theme.overdue)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(Theme.overdue.opacity(0.12), in: .capsule)
                    .padding(.top, 8)
            }
            dashedDivider.padding(.vertical, 18)
            VStack(spacing: 10) {
                row("Receipt", p.receiptCode)
                row("Received from", receipt.borrower.name)
                row("For", receipt.loan.title)
                row("Method", p.method.label)
                if let note = p.note, !note.isEmpty { row("Note", note) }
            }
            dashedDivider.padding(.vertical, 18)
            VStack(spacing: 10) {
                row("Balance before", Money.format(p.balanceBeforeCents, code: currency))
                row("This payment", "− " + Money.format(p.amountCents, code: currency))
                row("Balance after", Money.format(p.balanceAfterCents, code: currency), bold: true)
            }
            dashedDivider.padding(.vertical, 18)
            VStack(spacing: 6) {
                Text("Loan of \(Money.format(receipt.loan.principalCents, code: currency)) · \(termsLine) · \(receipt.loan.termPeriods) payments, \(receipt.loan.schedule.label.lowercased())")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Text("Started \(Dates.medium(receipt.loan.startDate)) · Recorded \(Dates.localDay(p.createdAt))")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            .padding(.bottom, 24)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 24))
        .overlay {
            if p.voided {
                Text("VOID")
                    .font(.system(size: 72, weight: .black))
                    .foregroundStyle(Theme.overdue.opacity(0.18))
                    .rotationEffect(.degrees(-18))
            }
        }
    }

    private var termsLine: String {
        switch receipt.loan.interestType {
        case .compound: tr("\(Money.percent(receipt.loan.rateBps)) per period compound")
        case .simple: tr("\(Money.percent(receipt.loan.rateBps)) flat interest")
        case .fixed: receipt.loan.fixedFeePerPeriod ? tr("\(Money.format(receipt.loan.fixedFeeCents, code: currency)) fee per period") : tr("\(Money.format(receipt.loan.fixedFeeCents, code: currency)) fee")
        }
    }

    private func row(_ label: LocalizedStringKey, _ value: String, bold: Bool = false) -> some View {
        HStack(alignment: .top) {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).fontWeight(bold ? .semibold : .regular).multilineTextAlignment(.trailing).monospacedDigit()
        }
        .font(.subheadline)
    }

    private var dashedDivider: some View {
        Line().stroke(style: StrokeStyle(lineWidth: 1, dash: [4, 4])).foregroundStyle(.quaternary).frame(height: 1)
    }
}

private nonisolated struct Line: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.midY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        return p
    }
}

enum ReceiptPDF {
    /// Renders the receipt card to a single-page PDF in the temporary directory.
    static func render(_ receipt: ReceiptDTO, currency: String) -> URL? {
        let width: CGFloat = 420
        let card = ReceiptCard(receipt: receipt, currency: currency)
            .frame(width: width)
            .padding(24)
            .background(Color.white)
            .environment(\.colorScheme, .light)
        let renderer = ImageRenderer(content: card)
        renderer.proposedSize = ProposedViewSize(width: width + 48, height: nil)
        let url = FileManager.default.temporaryDirectory.appending(path: "Lendly-Receipt-\(receipt.payment.receiptCode).pdf")
        var ok = false
        renderer.render { size, draw in
            var box = CGRect(origin: .zero, size: size)
            guard let consumer = CGDataConsumer(url: url as CFURL),
                  let context = CGContext(consumer: consumer, mediaBox: &box, nil) else { return }
            context.beginPDFPage(nil)
            draw(context)
            context.endPDFPage()
            context.closePDF()
            ok = true
        }
        return ok ? url : nil
    }
}
