import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var workspaceName = ""
    @State private var showJoin = false
    @State private var showCreate = false
    @State private var confirmSignOut = false
    @State private var error: APIError?
    @State private var saved = false
    @AppStorage(APIClient.defaultsKey) private var apiBase = ""

    private var isInTabs: Bool { model.isAdmin }

    var body: some View {
        let content = Form {
            Section("You") {
                TextField("Your name", text: $name)
                    .onSubmit { Task { await saveName() } }
                LabeledContent("Email", value: model.user?.email ?? "—")
                if model.user?.hasApple == true {
                    LabeledContent("Sign in with Apple", value: "Linked")
                }
            }
            if model.isAdmin {
                Section {
                    TextField("Workspace name", text: $workspaceName)
                        .onSubmit { Task { await saveWorkspace() } }
                } header: { Text("Workspace") } footer: { Text("Shown on receipts and to your borrowers.") }
            }
            Section("Workspaces") {
                ForEach(model.memberships) { m in
                    Button {
                        model.select(m)
                        if !isInTabs { dismiss() }
                    } label: {
                        HStack {
                            Image(systemName: m.role == .admin ? "banknote.fill" : "person.fill")
                                .foregroundStyle(m.role == .admin ? Color.accentColor : .orange)
                            VStack(alignment: .leading) {
                                Text(m.tenantName).foregroundStyle(.primary)
                                Text(m.role == .admin ? "You lend" : "You borrow").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if m.id == model.current?.id { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
                        }
                    }
                }
                Button { showJoin = true } label: { Label("Join with an invite code", systemImage: "envelope.open") }
                if !model.memberships.contains(where: { $0.role == .admin }) {
                    Button { showCreate = true } label: { Label("Start lending", systemImage: "plus.circle") }
                }
            }
            #if DEBUG
            Section {
                TextField("http://127.0.0.1:5050", text: $apiBase)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            } header: { Text("Developer") } footer: { Text("API base URL override. Leave blank for the default.") }
            #endif
            Section {
                Button("Sign out", role: .destructive) { confirmSignOut = true }
            } footer: {
                Text("Lendly \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") · SotoDev")
                    .frame(maxWidth: .infinity).padding(.top, 8)
            }
        }
        .navigationTitle("Settings")
        .toolbar {
            if !isInTabs {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            ToolbarItem(placement: .topBarTrailing) {
                if saved { Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.good) }
            }
        }
        .onAppear { name = model.user?.name ?? ""; workspaceName = model.current?.tenantName ?? "" }
        .sheet(isPresented: $showJoin) { JoinWorkspaceView(prefilledCode: "") }
        .sheet(isPresented: $showCreate) { CreateWorkspaceView() }
        .confirmationDialog("Sign out of Lendly?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { model.signOut() }
        }
        .apiErrorAlert($error)

        if isInTabs { NavigationStack { content } } else { content }
    }

    private func flashSaved() {
        saved = true
        Task { try? await Task.sleep(for: .seconds(1.5)); saved = false }
    }

    private func saveName() async {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != model.user?.name else { return }
        do { _ = try await model.api.updateName(trimmed); await model.refreshMe(); flashSaved() }
        catch let e as APIError { error = e } catch {}
    }

    private func saveWorkspace() async {
        let trimmed = workspaceName.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != model.current?.tenantName else { return }
        do { _ = try await model.api.renameTenant(trimmed); await model.refreshMe(); flashSaved() }
        catch let e as APIError { error = e } catch {}
    }
}
