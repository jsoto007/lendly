import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .loading:
                ProgressView().controlSize(.large)
            case .signedOut:
                WelcomeView()
            case .needsWorkspace:
                WorkspaceSetupView()
            case .ready:
                if model.isAdmin { AdminTabs() } else { BorrowerHomeView().id(model.current?.id) }
            case .offline:
                ContentUnavailableView {
                    Label("Can't reach Lendly", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(model.banner ?? "Check your connection and try again.")
                } actions: {
                    Button("Try again") { model.phase = .loading; Task { await model.bootstrap() } }
                        .buttonStyle(.borderedProminent)
                    Button("Sign out", role: .destructive) { model.signOut() }
                }
            }
        }
        .animation(.smooth, value: model.phase)
        .task { await model.bootstrap() }
        .sheet(isPresented: Binding(get: { model.pendingInviteCode != nil && model.phase != .signedOut && model.phase != .loading },
                                    set: { if !$0 { model.pendingInviteCode = nil } })) {
            JoinWorkspaceView(prefilledCode: model.pendingInviteCode ?? "")
        }
    }
}

struct AdminTabs: View {
    @Environment(AppModel.self) private var model
    @State private var selection: Tab = .dashboard
    enum Tab: Hashable { case dashboard, borrowers, loans, settings }

    var body: some View {
        TabView(selection: $selection) {
            SwiftUI.Tab("Dashboard", systemImage: "chart.pie.fill", value: Tab.dashboard) {
                DashboardView()
            }
            SwiftUI.Tab("Borrowers", systemImage: "person.2.fill", value: Tab.borrowers) {
                BorrowersView()
            }
            SwiftUI.Tab("Loans", systemImage: "list.bullet.rectangle.portrait.fill", value: Tab.loans) {
                LoansView()
            }
            SwiftUI.Tab("Settings", systemImage: "gearshape.fill", value: Tab.settings) {
                SettingsView()
            }
        }
        .tabBarMinimizeBehavior(.onScrollDown)
        .id(model.current?.id)
    }
}
