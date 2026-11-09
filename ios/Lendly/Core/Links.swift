import Foundation

/// Public pages linked from Welcome and Settings. App Store Connect also asks for the privacy
/// policy URL, so these pages must be live before the app is submitted.
enum Links {
    static let privacy = URL(string: "https://sotodev.com/lendly/privacy")!
    static let terms = URL(string: "https://sotodev.com/lendly/terms")!
    static let support = URL(string: "https://sotodev.com/lendly/support")!
}
