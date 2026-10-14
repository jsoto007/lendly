import SwiftUI

enum Theme {
    static let overdue = Color.red
    static let good = Color.green
    static let warning = Color.orange
    static let neutral = Color.secondary

    static func tint(for type: InterestType) -> Color {
        switch type {
        case .compound: .purple
        case .simple: .blue
        case .fixed: .teal
        }
    }

    static func tint(forStatus status: LoanStatus, overdue: Bool) -> Color {
        if overdue { return overdue ? .red : .accentColor }
        switch status {
        case .active: return .accentColor
        case .paid: return .green
        case .cancelled: return .secondary
        }
    }

    static func tint(forInstallment status: String) -> Color {
        switch status {
        case "paid": .green
        case "overdue": .red
        default: .secondary
        }
    }
}

struct APIErrorAlert: ViewModifier {
    @Binding var error: APIError?
    func body(content: Content) -> some View {
        content.alert("Something went wrong", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }), presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { err in
            Text(err.message)
        }
    }
}

extension View {
    func apiErrorAlert(_ error: Binding<APIError?>) -> some View { modifier(APIErrorAlert(error: error)) }
}
