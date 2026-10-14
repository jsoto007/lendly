import SwiftUI

struct BorrowersView: View {
    @Environment(AppModel.self) private var model
    @State private var borrowers: [BorrowerDTO] = []
    @State private var loaded = false
    @State private var search = ""
    @State private var showForm = false
    @State private var showArchived = false
    @State private var error: APIError?

    private var filtered: [BorrowerDTO] {
        let base = borrowers.filter { showArchived || !$0.archived }
        guard !search.isEmpty else { return base }
        return base.filter { $0.name.localizedCaseInsensitiveContains(search) || ($0.email ?? "").localizedCaseInsensitiveContains(search) }
    }

    var body: some View {
        NavigationStack {
            List {
                if loaded && filtered.isEmpty {
                    ContentUnavailableView {
                        Label(search.isEmpty ? tr("No borrowers yet") : tr("No matches"), systemImage: "person.2")
                    } description: {
                        Text(search.isEmpty ? tr("Add the first person you lend to. You'll create their loan right after.") : tr("Try a different name."))
                    } actions: {
                        if search.isEmpty { Button("Add borrower") { showForm = true }.buttonStyle(.borderedProminent) }
                    }
                    .listRowBackground(Color.clear)
                }
                ForEach(filtered) { b in
                    NavigationLink(value: b) { row(b) }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $search, prompt: "Search borrowers")
            .navigationTitle("Borrowers")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showForm = true } label: { Image(systemName: "person.badge.plus") }
                }
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Toggle("Show archived", isOn: $showArchived)
                    } label: { Image(systemName: "line.3.horizontal.decrease.circle") }
                }
            }
            .refreshable { await load() }
            .task { await load() }
            .onChange(of: showArchived) { Task { await load() } }
            .navigationDestination(for: BorrowerDTO.self) { BorrowerDetailView(borrowerID: $0.id) }
            .sheet(isPresented: $showForm, onDismiss: { Task { await load() } }) { BorrowerFormView(existing: nil) }
            .apiErrorAlert($error)
        }
    }

    private func row(_ b: BorrowerDTO) -> some View {
        HStack(spacing: 14) {
            InitialsAvatar(name: b.name, size: 44)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(b.name).font(.body.weight(.medium))
                    if b.linked { Image(systemName: "checkmark.seal.fill").font(.caption).foregroundStyle(Color.accentColor) }
                    if b.archived { StatusPill(text: tr("Archived"), tint: .secondary) }
                }
                if let s = b.summary {
                    Group {
                        if s.activeLoans == 0 {
                            Text("No active loans")
                        } else {
                            Text("\(s.activeLoans) active · \(Money.format(s.outstandingCents, code: model.currency)) outstanding")
                        }
                    }
                    .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if let s = b.summary, s.overdueCents > 0 {
                StatusPill(text: tr("\(Money.format(s.overdueCents, code: model.currency)) late"), tint: Theme.overdue)
            }
        }
        .padding(.vertical, 2)
    }

    private func load() async {
        do { borrowers = try await model.api.borrowers(includeArchived: showArchived) }
        catch let e as APIError { if borrowers.isEmpty { error = e } } catch {}
        loaded = true
    }
}

struct BorrowerDetailView: View {
    @Environment(AppModel.self) private var model
    let borrowerID: String
    @State private var detail: APIClient.BorrowerDetail?
    @State private var showEdit = false
    @State private var showNewLoan = false
    @State private var error: APIError?
    @State private var inviteBusy = false

    private var currency: String { model.currency }

    var body: some View {
        ScrollView {
            if let d = detail {
                VStack(spacing: 20) {
                    header(d.borrower)
                    if let s = d.borrower.summary {
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                            StatTile(title: "Outstanding", value: Money.format(s.outstandingCents, code: currency), symbol: "clock.arrow.circlepath")
                            StatTile(title: "Overdue", value: Money.format(s.overdueCents, code: currency), symbol: "exclamationmark.triangle.fill",
                                     tint: s.overdueCents > 0 ? Theme.overdue : .secondary)
                            StatTile(title: "Paid so far", value: Money.format(s.paidCents, code: currency), symbol: "checkmark.seal.fill", tint: Theme.good)
                            StatTile(title: "Total lent", value: Money.format(s.lentCents, code: currency), symbol: "arrow.up.right.circle.fill", tint: .blue)
                        }
                    }
                    inviteCard(d)
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            SectionTitle(title: "Loans", subtitle: d.loans.isEmpty ? nil : tr("\(d.loans.count) total"))
                            Button { showNewLoan = true } label: { Label("New", systemImage: "plus") }
                                .buttonStyle(.bordered).controlSize(.small)
                        }
                        if d.loans.isEmpty {
                            EmptyCard(symbol: "banknote", title: "No loans yet", message: "Create the first loan for \(d.borrower.name).")
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
                    if let notes = d.borrower.notes, !notes.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            SectionTitle(title: "Notes")
                            Text(notes).font(.body).frame(maxWidth: .infinity, alignment: .leading)
                                .padding(16).background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
                        }
                    }
                }
                .padding(16)
            } else {
                ProgressView().padding(.top, 80)
            }
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(detail?.borrower.name ?? "Borrower")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button { showEdit = true } label: { Label("Edit profile", systemImage: "pencil") }
                    Button { showNewLoan = true } label: { Label("New loan", systemImage: "banknote") }
                    if let b = detail?.borrower {
                        Divider()
                        Button(role: b.archived ? nil : .destructive) {
                            Task { await setArchived(!b.archived) }
                        } label: {
                            Label(b.archived ? tr("Unarchive") : tr("Archive"), systemImage: b.archived ? "tray.and.arrow.up" : "archivebox")
                        }
                    }
                } label: { Image(systemName: "ellipsis.circle") }
            }
        }
        .refreshable { await load() }
        .task { await load() }
        .navigationDestination(for: LoanDTO.self) { LoanDetailView(loanID: $0.id, initial: $0) }
        .sheet(isPresented: $showEdit, onDismiss: { Task { await load() } }) { BorrowerFormView(existing: detail?.borrower) }
        .sheet(isPresented: $showNewLoan, onDismiss: { Task { await load() } }) { LoanFormView(borrower: detail?.borrower, existing: nil) }
        .apiErrorAlert($error)
    }

    private func header(_ b: BorrowerDTO) -> some View {
        VStack(spacing: 12) {
            InitialsAvatar(name: b.name, size: 84)
            Text(b.name).font(.title2.weight(.bold))
            HStack(spacing: 12) {
                if let phone = b.phone, let url = URL(string: "tel:" + phone.filter { $0.isNumber || $0 == "+" }) {
                    Link(destination: url) { Label("Call", systemImage: "phone.fill") }
                    if let sms = URL(string: "sms:" + phone.filter { $0.isNumber || $0 == "+" }) {
                        Link(destination: sms) { Label("Message", systemImage: "message.fill") }
                    }
                }
                if let email = b.email, let url = URL(string: "mailto:" + email) {
                    Link(destination: url) { Label("Email", systemImage: "envelope.fill") }
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .labelStyle(.titleAndIcon)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 8)
    }

    @ViewBuilder
    private func inviteCard(_ d: APIClient.BorrowerDetail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if d.borrower.linked {
                HStack(spacing: 12) {
                    Image(systemName: "checkmark.seal.fill").font(.title2).foregroundStyle(Color.accentColor)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Has access to Lendly").font(.headline)
                        Text("\(d.borrower.name) can see their loans, payments and receipts.").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
            } else if let invite = d.invite {
                HStack(spacing: 12) {
                    Image(systemName: "envelope.open.fill").font(.title2).foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Invite pending").font(.headline)
                        Text("Share this code. It expires \(Dates.localDay(invite.expiresAt)).").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Text(invite.code)
                        .font(.system(.title, design: .monospaced).weight(.semibold))
                        .tracking(3)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .glassEffect(.regular.tint(Color.accentColor.opacity(0.12)), in: .rect(cornerRadius: 14))
                }
                HStack(spacing: 10) {
                    ShareLink(item: inviteMessage(invite, d.borrower)) {
                        Label("Share invite", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glassProminent)
                    Button {
                        Task { await createInvite() }
                    } label: { Label("New code", systemImage: "arrow.clockwise") }
                        .buttonStyle(.glass)
                        .disabled(inviteBusy)
                }
            } else {
                HStack(spacing: 12) {
                    Image(systemName: "person.crop.circle.badge.plus").font(.title2).foregroundStyle(Color.accentColor)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Invite \(d.borrower.name)").font(.headline)
                        Text("Let them follow their progress and download receipts from their own phone.")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                Button {
                    Task { await createInvite() }
                } label: {
                    Label(inviteBusy ? "Creating…" : "Create invite code", systemImage: "link").frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                .disabled(inviteBusy)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 20))
    }

    private func inviteMessage(_ invite: InviteDTO, _ b: BorrowerDTO) -> String {
        tr("Hi \(b.name.split(separator: " ").first.map(String.init) ?? b.name), I'm tracking our loan in Lendly. Open the app and enter code \(invite.code) to see your balance, payments and receipts.") + "\n" + invite.link
    }

    private func load() async {
        do { detail = try await model.api.borrower(borrowerID) }
        catch let e as APIError { error = e } catch {}
    }

    private func createInvite() async {
        inviteBusy = true; defer { inviteBusy = false }
        do { _ = try await model.api.createInvite(borrowerID: borrowerID); await load() }
        catch let e as APIError { error = e } catch {}
    }

    private func setArchived(_ archived: Bool) async {
        do { _ = try await model.api.setBorrowerArchived(borrowerID, archived); await load() }
        catch let e as APIError { error = e } catch {}
    }
}

struct BorrowerFormView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let existing: BorrowerDTO?
    @State private var name = ""
    @State private var email = ""
    @State private var phone = ""
    @State private var notes = ""
    @State private var busy = false
    @State private var error: APIError?
    /// When set, the created borrower is handed back (used by the loan form).
    var onCreated: ((BorrowerDTO) -> Void)? = nil

    var body: some View {
        NavigationStack {
            Form {
                Section("Who") {
                    TextField("Full name", text: $name).textContentType(.name)
                }
                Section("Contact") {
                    TextField("Email", text: $email).textContentType(.emailAddress).keyboardType(.emailAddress).textInputAutocapitalization(.never)
                    TextField("Phone", text: $phone).textContentType(.telephoneNumber).keyboardType(.phonePad)
                }
                Section("Notes") {
                    TextField("Anything worth remembering", text: $notes, axis: .vertical).lineLimit(3...6)
                }
            }
            .navigationTitle(existing == nil ? tr("New borrower") : tr("Edit borrower"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", role: .cancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button(existing == nil ? tr("Add") : tr("Save")) { Task { await save() } }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .onAppear {
                if let existing {
                    name = existing.name; email = existing.email ?? ""; phone = existing.phone ?? ""; notes = existing.notes ?? ""
                }
            }
            .apiErrorAlert($error)
        }
    }

    private func save() async {
        busy = true; defer { busy = false }
        let fields: [String: String?] = [
            "name": name.trimmingCharacters(in: .whitespaces),
            "email": email.trimmingCharacters(in: .whitespaces).isEmpty ? nil : email.trimmingCharacters(in: .whitespaces),
            "phone": phone.trimmingCharacters(in: .whitespaces).isEmpty ? nil : phone.trimmingCharacters(in: .whitespaces),
            "notes": notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : notes,
        ]
        do {
            if let existing {
                _ = try await model.api.updateBorrower(existing.id, fields)
            } else {
                let b = try await model.api.createBorrower(fields)
                onCreated?(b)
            }
            dismiss()
        } catch let e as APIError { error = e } catch {}
    }
}
