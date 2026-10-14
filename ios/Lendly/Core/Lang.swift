import Foundation
import Observation
import SwiftUI

/// Which language the app shows. `.system` follows the device (and the per-app language in
/// iOS Settings); the other two force a language without relaunching.
enum AppLanguage: String, CaseIterable, Identifiable {
    case system, en, es
    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: tr("Match device language")
        case .en: "English"
        case .es: "Español"
        }
    }
}

@Observable
final class Lang {
    static let shared = Lang()
    static let defaultsKey = "app_language"

    var choice: AppLanguage {
        didSet { UserDefaults.standard.set(choice.rawValue, forKey: Self.defaultsKey) }
    }

    init() {
        choice = AppLanguage(rawValue: UserDefaults.standard.string(forKey: Self.defaultsKey) ?? "") ?? .system
    }

    /// Two-letter code actually in effect.
    var code: String {
        switch choice {
        case .en: return "en"
        case .es: return "es"
        case .system: return Bundle.main.preferredLocalizations.first.map { String($0.prefix(2)) } ?? "en"
        }
    }

    /// Locale for formatting. Spanish keeps US number and currency conventions because the
    /// lenders and borrowers are in the US; only the wording changes.
    var locale: Locale {
        switch choice {
        case .system: return Locale.autoupdatingCurrent
        case .en: return Locale(identifier: "en_US")
        case .es: return Locale(identifier: "es_US")
        }
    }

    /// Bundle to pull strings from: the main bundle (device language) or a forced .lproj.
    var bundle: Bundle {
        guard choice != .system,
              let path = Bundle.main.path(forResource: code, ofType: "lproj"),
              let bundle = Bundle(path: path) else { return .main }
        return bundle
    }
}

/// Localized copy for strings assembled in code (enum labels, captions, messages).
/// SwiftUI `Text("literal")` localizes by itself through the environment locale.
func tr(_ key: String.LocalizationValue) -> String {
    String(localized: key, bundle: Lang.shared.bundle, locale: Lang.shared.locale)
}

/// Plural helper: `plural(n, one: "1 day late", other: "\(n) days late")`.
func plural(_ n: Int, one: String.LocalizationValue, other: String.LocalizationValue) -> String {
    n == 1 ? tr(one) : tr(other)
}
