import Foundation

struct APIError: Error, LocalizedError, Equatable {
    var status: Int
    var code: String
    var message: String
    var errorDescription: String? { message }

    @MainActor static var offline: APIError { APIError(status: 0, code: "offline", message: tr("Can't reach the server. Check your connection.")) }
    @MainActor static var decoding: APIError { APIError(status: 0, code: "decoding", message: tr("The server sent something unexpected.")) }
}

final class APIClient {
    static let defaultsKey = "api_base_url"

    var token: String?
    var tenantID: String?
    /// Called when an authenticated request comes back 401 (expired/revoked session).
    var onUnauthorized: (() -> Void)?

    var baseURL: URL {
        if let raw = UserDefaults.standard.string(forKey: Self.defaultsKey), let url = URL(string: raw) { return url }
        #if DEBUG
        return URL(string: "http://127.0.0.1:5050")!
        #else
        return URL(string: "https://lendly-api.onrender.com")!
        #endif
    }

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 20
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    private struct ErrorEnvelope: Decodable {
        struct Inner: Decodable { var code: String; var message: String }
        var error: Inner
    }

    @discardableResult
    func send<T: Decodable>(_ method: String, _ path: String, body: (some Encodable)? = Optional<Empty>.none,
                            query: [URLQueryItem] = [], as type: T.Type = T.self) async throws -> T {
        var components = URLComponents(url: baseURL.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let tenantID { request.setValue(tenantID, forHTTPHeaderField: "X-Tenant-Id") }
        // The server treats this as "today" (due dates, defaults), so a 9pm New York lender isn't on tomorrow's UTC date.
        request.setValue(Dates.dayString(.now), forHTTPHeaderField: "X-Local-Date")
        request.setValue(Lang.shared.code, forHTTPHeaderField: "Accept-Language")  // server error messages come back in this language
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try encoder.encode(body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.offline
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            if status == 401, token != nil, !path.hasPrefix("/api/auth/") { onUnauthorized?() }
            if let env = try? decoder.decode(ErrorEnvelope.self, from: data) {
                throw APIError(status: status, code: env.error.code, message: env.error.message)
            }
            throw APIError(status: status, code: "http_\(status)", message: tr("Request failed (\(status))."))
        }
        if T.self == Empty.self { return Empty() as! T }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            #if DEBUG
            print("decode error:", error, String(data: data, encoding: .utf8) ?? "")
            #endif
            throw APIError.decoding
        }
    }

    // MARK: Auth
    struct EmailRequestResponse: Decodable { var sent: Bool; var devCode: String? }
    func requestEmailCode(_ email: String) async throws -> EmailRequestResponse {
        try await send("POST", "/api/auth/email/request", body: ["email": email])
    }
    func verifyEmailCode(_ email: String, code: String) async throws -> SessionResponse {
        try await send("POST", "/api/auth/email/verify", body: ["email": email, "code": code])
    }
    func signInWithApple(identityToken: String, name: String?) async throws -> SessionResponse {
        try await send("POST", "/api/auth/apple", body: ["identity_token": identityToken, "name": name ?? ""])
    }

    // MARK: Me / tenants / invites
    func me() async throws -> MeResponse { try await send("GET", "/api/me") }
    func updateName(_ name: String) async throws -> UserDTO {
        struct R: Decodable { var user: UserDTO }
        let r: R = try await send("PATCH", "/api/me", body: ["name": name])
        return r.user
    }
    func createTenant(name: String) async throws -> MembershipDTO {
        struct R: Decodable { var membership: MembershipDTO }
        let r: R = try await send("POST", "/api/tenants", body: ["name": name])
        return r.membership
    }
    func renameTenant(_ name: String) async throws -> TenantDTO {
        struct R: Decodable { var tenant: TenantDTO }
        let r: R = try await send("PATCH", "/api/tenants/current", body: ["name": name])
        return r.tenant
    }
    func acceptInvite(code: String) async throws -> MembershipDTO {
        struct R: Decodable { var membership: MembershipDTO }
        let r: R = try await send("POST", "/api/invites/accept", body: ["code": code])
        return r.membership
    }

    // MARK: Dashboard
    func dashboard() async throws -> DashboardDTO { try await send("GET", "/api/dashboard") }

    // MARK: Borrowers
    struct BorrowerDetail: Decodable { var borrower: BorrowerDTO; var loans: [LoanDTO]; var invite: InviteDTO? }
    func borrowers(includeArchived: Bool = false) async throws -> [BorrowerDTO] {
        struct R: Decodable { var borrowers: [BorrowerDTO] }
        let r: R = try await send("GET", "/api/borrowers", query: includeArchived ? [URLQueryItem(name: "include_archived", value: "true")] : [])
        return r.borrowers
    }
    func borrower(_ id: String) async throws -> BorrowerDetail { try await send("GET", "/api/borrowers/\(id)") }
    func createBorrower(_ fields: [String: String?]) async throws -> BorrowerDTO {
        struct R: Decodable { var borrower: BorrowerDTO }
        let r: R = try await send("POST", "/api/borrowers", body: fields)
        return r.borrower
    }
    func updateBorrower(_ id: String, _ fields: [String: String?]) async throws -> BorrowerDTO {
        struct R: Decodable { var borrower: BorrowerDTO }
        let r: R = try await send("PATCH", "/api/borrowers/\(id)", body: fields)
        return r.borrower
    }
    func setBorrowerArchived(_ id: String, _ archived: Bool) async throws -> BorrowerDTO {
        struct R: Decodable { var borrower: BorrowerDTO }
        let r: R = try await send("PATCH", "/api/borrowers/\(id)", body: ["archived": archived])
        return r.borrower
    }
    func createInvite(borrowerID: String) async throws -> InviteDTO {
        struct R: Decodable { var invite: InviteDTO }
        let r: R = try await send("POST", "/api/borrowers/\(borrowerID)/invites", body: Empty())
        return r.invite
    }

    // MARK: Loans
    func previewLoan(_ terms: LoanTermsBody) async throws -> PreviewResponse {
        try await send("POST", "/api/loans/preview", body: terms)
    }
    func loans(status: LoanStatus? = nil, borrowerID: String? = nil) async throws -> [LoanDTO] {
        struct R: Decodable { var loans: [LoanDTO] }
        var q: [URLQueryItem] = []
        if let status { q.append(URLQueryItem(name: "status", value: status.rawValue)) }
        if let borrowerID { q.append(URLQueryItem(name: "borrower_id", value: borrowerID)) }
        let r: R = try await send("GET", "/api/loans", query: q)
        return r.loans
    }
    func loan(_ id: String) async throws -> LoanDTO {
        struct R: Decodable { var loan: LoanDTO }
        let r: R = try await send("GET", "/api/loans/\(id)")
        return r.loan
    }
    func createLoan(_ terms: LoanTermsBody) async throws -> LoanDTO {
        struct R: Decodable { var loan: LoanDTO }
        let r: R = try await send("POST", "/api/loans", body: terms)
        return r.loan
    }
    func updateLoan(_ id: String, _ terms: LoanTermsBody) async throws -> LoanDTO {
        struct R: Decodable { var loan: LoanDTO }
        let r: R = try await send("PATCH", "/api/loans/\(id)", body: terms)
        return r.loan
    }
    func updateLoanMeta(_ id: String, title: String, notes: String?) async throws -> LoanDTO {
        struct R: Decodable { var loan: LoanDTO }
        let body: [String: String?] = ["title": title, "notes": notes]
        let r: R = try await send("PATCH", "/api/loans/\(id)", body: body)
        return r.loan
    }
    func setLoanStatus(_ id: String, _ status: LoanStatus) async throws -> LoanDTO {
        struct R: Decodable { var loan: LoanDTO }
        let r: R = try await send("PATCH", "/api/loans/\(id)", body: ["status": status.rawValue])
        return r.loan
    }
    func deleteLoan(_ id: String) async throws {
        let _: Empty = try await send("DELETE", "/api/loans/\(id)")
    }

    // MARK: Payments
    struct PaymentResult: Decodable { var payment: PaymentDTO; var loan: LoanDTO }
    func recordPayment(loanID: String, _ body: PaymentBody) async throws -> PaymentResult {
        try await send("POST", "/api/loans/\(loanID)/payments", body: body)
    }
    func voidPayment(_ id: String, reason: String?) async throws -> PaymentResult {
        try await send("POST", "/api/payments/\(id)/void", body: ["reason": reason ?? ""])
    }
    func receipt(_ paymentID: String) async throws -> ReceiptDTO {
        try await send("GET", "/api/payments/\(paymentID)/receipt")
    }
    func recentPayments(limit: Int = 50) async throws -> [PaymentDTO] {
        struct R: Decodable { var payments: [PaymentDTO] }
        let r: R = try await send("GET", "/api/payments", query: [URLQueryItem(name: "limit", value: String(limit))])
        return r.payments
    }

    // MARK: Borrower portal
    func portal() async throws -> PortalDTO { try await send("GET", "/api/borrower/overview") }
}
