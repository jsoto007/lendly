import AuthenticationServices
import SwiftUI

struct WelcomeView: View {
    @Environment(AppModel.self) private var model
    @State private var showEmail = false
    @State private var error: APIError?
    @State private var busy = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color.accentColor.opacity(0.35), Color.accentColor.opacity(0.05), .clear],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            VStack(spacing: 28) {
                Spacer()
                VStack(spacing: 16) {
                    Image(systemName: "hand.raised.fingers.spread.fill")
                        .font(.system(size: 56, weight: .medium))
                        .foregroundStyle(Color.accentColor)
                        .frame(width: 112, height: 112)
                        .glassEffect(.regular.tint(Color.accentColor.opacity(0.2)), in: .circle)
                    Text("Lendly")
                        .font(.system(size: 44, weight: .bold, design: .rounded))
                    Text("Keep track of the money you lend, and let the people you lend to see exactly where they stand.")
                        .font(.body)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 32)
                }
                Spacer()
                VStack(spacing: 12) {
                    SignInWithAppleButton(.continue) { request in
                        request.requestedScopes = [.fullName, .email]
                    } onCompletion: { result in
                        Task { await handleApple(result) }
                    }
                    .signInWithAppleButtonStyle(.black)
                    .frame(height: 52)
                    .clipShape(.capsule)

                    Button {
                        showEmail = true
                    } label: {
                        Label("Continue with Email", systemImage: "envelope.fill")
                            .frame(maxWidth: .infinity)
                            .frame(height: 36)
                    }
                    .buttonStyle(.glassProminent)
                    .controlSize(.large)
                }
                .padding(.horizontal, 24)
                .disabled(busy)
                Text("By continuing you agree to keep your records honest and your borrowers informed.")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                    .padding(.bottom, 8)
            }
        }
        .sheet(isPresented: $showEmail) { EmailCodeView() }
        .apiErrorAlert($error)
    }

    private func handleApple(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .failure(let err):
            if (err as? ASAuthorizationError)?.code == .canceled { return }
            error = APIError(status: 0, code: "apple", message: "Sign in with Apple isn't available on this device right now. Try email instead.")
        case .success(let auth):
            guard let credential = auth.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken,
                  let token = String(data: tokenData, encoding: .utf8) else {
                error = APIError(status: 0, code: "apple", message: "Apple didn't return a usable credential.")
                return
            }
            let name = [credential.fullName?.givenName, credential.fullName?.familyName].compactMap { $0 }.joined(separator: " ")
            busy = true
            defer { busy = false }
            do {
                let session = try await model.api.signInWithApple(identityToken: token, name: name.isEmpty ? nil : name)
                model.apply(session)
            } catch let e as APIError {
                error = e
            } catch {
                self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription)
            }
        }
    }
}
