import SwiftUI

@main
struct LendlyApp: App {
    @State private var model = AppModel()
    @State private var lang = Lang.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(\.locale, lang.locale)
                .id(lang.choice)  // rebuild every view when the language changes
                .onOpenURL { model.handle(url: $0) }
        }
    }
}
