import Foundation
import Observation

@Observable
final class AppModel {
    enum Phase: Equatable { case loading, signedOut, needsWorkspace, ready, offline }

    private static let tokenKey = "session_token"
    private static let tenantKey = "selected_tenant_id"

    let api = APIClient()
    var phase: Phase = .loading
    var user: UserDTO?
    var memberships: [MembershipDTO] = []
    var current: MembershipDTO?
    var pendingInviteCode: String?
    var banner: String?

    init() {
        api.onUnauthorized = { [weak self] in
            Task { @MainActor in self?.signOut() }
        }
    }

    var isAdmin: Bool { current?.role == .admin }
    var currency: String { current?.currency ?? "USD" }

    // MARK: Lifecycle
    func bootstrap() async {
        guard let token = Keychain.get(Self.tokenKey) else { phase = .signedOut; return }
        api.token = token
        do {
            let me = try await api.me()
            user = me.user
            memberships = me.memberships
            chooseWorkspace()
        } catch let error as APIError where error.status == 401 {
            signOut()
        } catch {
            // Can't reach the server: keep the token and offer a retry instead of guessing a state.
            banner = error.localizedDescription
            phase = memberships.isEmpty ? .offline : .ready
        }
    }

    func apply(_ session: SessionResponse) {
        Keychain.set(session.token, for: Self.tokenKey)
        api.token = session.token
        user = session.user
        memberships = session.memberships
        chooseWorkspace()
    }

    func refreshMe() async {
        guard let me = try? await api.me() else { return }
        user = me.user
        memberships = me.memberships
        if let current, let fresh = memberships.first(where: { $0.id == current.id }) {
            self.current = fresh
        } else {
            chooseWorkspace()
        }
    }

    func chooseWorkspace() {
        let saved = UserDefaults.standard.string(forKey: Self.tenantKey)
        if let m = memberships.first(where: { $0.tenantId == saved }) ?? memberships.first {
            select(m)
        } else {
            current = nil
            api.tenantID = nil
            phase = .needsWorkspace
        }
    }

    func select(_ membership: MembershipDTO) {
        current = membership
        api.tenantID = membership.tenantId
        UserDefaults.standard.set(membership.tenantId, forKey: Self.tenantKey)
        phase = .ready
    }

    func signOut() {
        Keychain.delete(Self.tokenKey)
        UserDefaults.standard.removeObject(forKey: Self.tenantKey)
        api.token = nil
        api.tenantID = nil
        user = nil
        memberships = []
        current = nil
        phase = .signedOut
    }

    // MARK: Invites
    func handle(url: URL) {
        // lendly://invite/CODE
        guard url.scheme == "lendly", url.host() == "invite" else { return }
        let code = url.lastPathComponent.uppercased()
        guard code.count >= 6 else { return }
        pendingInviteCode = code
    }

    @discardableResult
    func acceptInvite(_ code: String) async throws -> MembershipDTO {
        let m = try await api.acceptInvite(code: code)
        pendingInviteCode = nil
        await refreshMe()
        if let fresh = memberships.first(where: { $0.id == m.id }) { select(fresh) } else { select(m) }
        return m
    }
}
