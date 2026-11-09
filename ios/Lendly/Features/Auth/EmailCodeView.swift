import SwiftUI

struct EmailCodeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var email = ""
    @State private var code = ""
    @State private var sent = false
    @State private var devCode: String?
    @State private var busy = false
    @State private var resendIn = 0
    @State private var cooldownTask: Task<Void, Never>?
    @State private var error: APIError?
    @FocusState private var focus: Field?
    enum Field { case email, code }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Email address", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focus, equals: .email)
                        .disabled(sent)
                } header: {
                    Text("Email")
                } footer: {
                    if sent { Text("We sent a 6-digit code to \(email).") } else { Text("We'll send you a one-time code. No password to remember.") }
                }
                if sent {
                    Section("Code") {
                        TextField("6-digit code", text: $code)
                            .textContentType(.oneTimeCode)
                            .keyboardType(.numberPad)
                            .focused($focus, equals: .code)
                            .font(.title2.monospacedDigit())
                        if let devCode {
                            Label("Dev build: your code is \(devCode)", systemImage: "hammer")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle(sent ? tr("Enter code") : tr("Sign in"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else if sent {
                        Button("Verify") { Task { await verify() } }.disabled(code.count < 6)
                    } else {
                        Button("Send code") { Task { await send() } }.disabled(!email.contains("@"))
                    }
                }
                if sent {
                    ToolbarItemGroup(placement: .bottomBar) {
                        Button("Use a different email") { sent = false; code = ""; devCode = nil; stopResendCooldown(); focus = .email }
                        Spacer()
                        Button(resendIn > 0 ? tr("Resend in \(resendIn)s") : tr("Resend code")) { Task { await send() } }
                            .disabled(busy || resendIn > 0)
                    }
                }
            }
            .onAppear { focus = .email }
            .onDisappear { cooldownTask?.cancel() }
            .apiErrorAlert($error)
        }
        .presentationDetents([.medium, .large])
    }

    private func send() async {
        busy = true; defer { busy = false }
        do {
            let r = try await model.api.requestEmailCode(email.trimmingCharacters(in: .whitespaces))
            devCode = r.devCode
            sent = true
            focus = .code
            startResendCooldown()
        } catch let e as APIError { error = e } catch { self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription) }
    }

    /// The server allows a few codes per address per window; the cooldown stops accidental double taps.
    private func startResendCooldown() {
        cooldownTask?.cancel()
        resendIn = 30
        cooldownTask = Task {
            while resendIn > 0, !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                if !Task.isCancelled { resendIn -= 1 }
            }
        }
    }

    private func stopResendCooldown() {
        cooldownTask?.cancel()
        cooldownTask = nil
        resendIn = 0
    }

    private func verify() async {
        busy = true; defer { busy = false }
        do {
            let session = try await model.api.verifyEmailCode(email.trimmingCharacters(in: .whitespaces), code: code)
            model.apply(session)
            dismiss()
        } catch let e as APIError { error = e } catch { self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription) }
    }
}
