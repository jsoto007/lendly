import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var workspaceName = ""
    @State private var showJoin = false
    @State private var showCreate = false
    @State private var confirmSignOut = false
    @State private var confirmDelete = false
    @State private var deleting = false
    @State private var error: APIError?
    @State private var saved = false
    @AppStorage(APIClient.defaultsKey) private var apiBase = ""
    @State private var lang = Lang.shared

    private var isInTabs: Bool { model.isAdmin }

    var body: some View {
        let content = Form {
            Section("You") {
                TextField("Your name", text: $name)
                    .onSubmit { Task { await saveName() } }
                LabeledContent("Email", value: model.user?.email ?? "—")
                if model.user?.hasApple == true {
                    LabeledContent("Sign in with Apple", value: tr("Linked"))
                }
            }
            Section {
                Picker("Language", selection: $lang.choice) {
                    ForEach(AppLanguage.allCases) { Text($0.label).tag($0) }
                }
            } header: { Text("Language") } footer: { Text("Applies immediately. \"Match device language\" follows the language set in iOS Settings.") }
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
                                Text(m.role == .admin ? tr("You lend") : tr("You borrow")).font(.caption).foregroundStyle(.secondary)
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
            Section("About") {
                Link(destination: Links.privacy) { Label("Privacy Policy", systemImage: "hand.raised") }
                Link(destination: Links.terms) { Label("Terms of Use", systemImage: "doc.text") }
                Link(destination: Links.support) { Label("Contact support", systemImage: "envelope") }
            }
            Section {
                Button("Sign out", role: .destructive) { confirmSignOut = true }
            }
            Section {
                Button(role: .destructive) { confirmDelete = true } label: {
                    if deleting {
                        HStack(spacing: 10) { ProgressView(); Text("Deleting…") }
                    } else {
                        Text("Delete account")
                    }
                }
                .disabled(deleting)
            } footer: {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Deleting your account removes your data from our servers. Workspaces you own, including every borrower, loan, payment and receipt, are deleted too. Where you are a borrower, only your access is removed; the lender keeps their own record of the loan.")
                    Text("Lendly \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") · SotoDev")
                        .frame(maxWidth: .infinity)
                }
                .padding(.top, 4)
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
        .confirmationDialog("Delete your account?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete account", role: .destructive) { Task { await deleteAccount() } }
        } message: {
            Text("This permanently deletes your account. Workspaces you own, with all their borrowers, loans, payments and receipts, are deleted too, and anyone you invited loses access. This can't be undone.")
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

    private func deleteAccount() async {
        deleting = true; defer { deleting = false }
        do { try await model.deleteAccount() }
        catch let e as APIError where e.status != 401 { error = e }  // a 401 already signed us out
        catch is APIError {}
        catch { self.error = APIError(status: 0, code: "unknown", message: error.localizedDescription) }
    }

    private func saveWorkspace() async {
        let trimmed = workspaceName.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != model.current?.tenantName else { return }
        do { _ = try await model.api.renameTenant(trimmed); await model.refreshMe(); flashSaved() }
        catch let e as APIError { error = e } catch {}
    }
}
