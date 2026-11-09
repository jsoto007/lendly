import SwiftUI

/// Shown after sign-in when the user has no workspace yet.
struct WorkspaceSetupView: View {
    @Environment(AppModel.self) private var model
    @State private var showCreate = false
    @State private var showJoin = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    VStack(spacing: 8) {
                        Text("Welcome, \(model.user?.displayName ?? "there")")
                            .font(.title.weight(.bold))
                        Text("How will you use Lendly?")
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 24)

                    choiceCard(symbol: "banknote.fill", tint: .accentColor, title: "I lend money",
                               text: "Set up a workspace, add the people you lend to, and track every loan and payment.") {
                        showCreate = true
                    }
                    choiceCard(symbol: "envelope.open.fill", tint: .orange, title: "I was invited",
                               text: "Enter the code your lender shared to see your loans, payments and receipts.") {
                        showJoin = true
                    }
                }
                .padding(20)
            }
            .background(Color(.systemGroupedBackground))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Sign out", role: .destructive) { model.signOut() }
                }
            }
        }
        .sheet(isPresented: $showCreate) { CreateWorkspaceView() }
        .sheet(isPresented: $showJoin) { JoinWorkspaceView(prefilledCode: "") }
    }

    private func choiceCard(symbol: String, tint: Color, title: LocalizedStringKey, text: LocalizedStringKey, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 16) {
                Image(systemName: symbol)
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(tint)
                    .frame(width: 56, height: 56)
                    .background(tint.opacity(0.12), in: .rect(cornerRadius: 16))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.headline).foregroundStyle(.primary)
                    Text(text).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
            }
            .padding(18)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

struct CreateWorkspaceView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var yourName = ""
    @State private var busy = false
    @State private var error: APIError?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Your name", text: $yourName).textContentType(.name)
                } footer: { Text("Shown on receipts and to the people you lend to.") }
                Section {
                    TextField("Workspace name", text: $name)
                } footer: { Text("For example \"Soto Lending\" or just your name.") }
            }
            .navigationTitle("New workspace")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Create") { Task { await create() } }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .onAppear { yourName = model.user?.name ?? "" }
            .apiErrorAlert($error)
        }
    }

    private func create() async {
        busy = true; defer { busy = false }
        do {
            let trimmedName = yourName.trimmingCharacters(in: .whitespaces)
            if !trimmedName.isEmpty, trimmedName != model.user?.name {
                _ = try await model.api.updateName(trimmedName)
            }
            _ = try await model.api.createTenant(name: name.trimmingCharacters(in: .whitespaces))
            await model.refreshMe()
            if let m = model.memberships.last(where: { $0.role == .admin }) { model.select(m) }
            dismiss()
        } catch let e as APIError { error = e } catch { self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription) }
    }
}

struct JoinWorkspaceView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State var prefilledCode: String
    @State private var busy = false
    @State private var error: APIError?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Invite code", text: $prefilledCode)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .font(.title2.monospaced())
                } footer: {
                    Text("The 8-character code your lender shared with you.")
                }
            }
            .navigationTitle("Join with a code")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Join") { Task { await join() } }
                            .disabled(prefilledCode.trimmingCharacters(in: .whitespaces).count < 6)
                    }
                }
            }
            .apiErrorAlert($error)
        }
        .presentationDetents([.medium])
    }

    private func join() async {
        busy = true; defer { busy = false }
        do {
            try await model.acceptInvite(prefilledCode.trimmingCharacters(in: .whitespaces))
            dismiss()
        } catch let e as APIError { error = e } catch { self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription) }
    }
}
