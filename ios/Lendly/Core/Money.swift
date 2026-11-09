import Foundation

enum Money {
    static func format(_ cents: Int, code: String = "USD") -> String {
        (Decimal(cents) / 100).formatted(.currency(code: code).locale(Lang.shared.locale))
    }

    static func compact(_ cents: Int, code: String = "USD") -> String {
        let dollars = Decimal(cents) / 100
        if abs(cents) >= 100_000_00 {
            return (dollars / 1000).formatted(.currency(code: code).precision(.fractionLength(1)).locale(Lang.shared.locale)) + "k"
        }
        return dollars.formatted(.currency(code: code).precision(.fractionLength(0)).locale(Lang.shared.locale))
    }

    static func percent(_ bps: Int) -> String {
        (Decimal(bps) / 10_000).formatted(.percent.precision(.fractionLength(0...2)).locale(Lang.shared.locale))
    }

    static func cents(from decimal: Decimal) -> Int {
        var value = decimal * 100
        var rounded = Decimal()
        NSDecimalRound(&rounded, &value, 0, .plain)
        return NSDecimalNumber(decimal: rounded).intValue
    }

    static func bps(fromPercent decimal: Decimal) -> Int {
        var value = decimal * 100
        var rounded = Decimal()
        NSDecimalRound(&rounded, &value, 0, .plain)
        return NSDecimalNumber(decimal: rounded).intValue
    }
}

enum Dates {
    nonisolated(unsafe) private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .iso8601)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func day(_ string: String) -> Date? {
        dayFormatter.date(from: String(string.prefix(10)))
    }

    static func dayString(_ date: Date) -> String {
        dayFormatter.string(from: date)
    }

    nonisolated(unsafe) private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds, .withColonSeparatorInTimeZone]
        return f
    }()
    nonisolated(unsafe) private static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withColonSeparatorInTimeZone]
        return f
    }()

    /// Parses the API's tz-aware timestamps (e.g. 2026-10-14T23:30:00.123456+00:00).
    static func timestamp(_ string: String) -> Date? {
        if let d = isoFractional.date(from: string) ?? isoPlain.date(from: string) { return d }
        // Python emits up to 6 fractional digits; ISO8601DateFormatter wants exactly 3.
        if let dot = string.firstIndex(of: "."), let tz = string[dot...].firstIndex(where: { $0 == "+" || $0 == "-" || $0 == "Z" }) {
            let trimmed = string[..<dot] + string[tz...]
            return isoPlain.date(from: String(trimmed))
        }
        return nil
    }

    /// A timestamp shown as a local calendar date ("Oct 14, 2026").
    static func localDay(_ string: String) -> String {
        guard let d = timestamp(string) ?? day(string) else { return string }
        return d.formatted(Date.FormatStyle(date: .abbreviated, time: .omitted).locale(Lang.shared.locale))
    }

    static func short(_ string: String) -> String {
        guard let d = day(string) else { return string }
        return d.formatted(.dateTime.month(.abbreviated).day().locale(Lang.shared.locale))
    }

    static func medium(_ string: String) -> String {
        guard let d = day(string) else { return string }
        return d.formatted(Date.FormatStyle(date: .abbreviated, time: .omitted).locale(Lang.shared.locale))
    }

    static func long(_ string: String) -> String {
        guard let d = day(string) else { return string }
        return d.formatted(Date.FormatStyle(date: .long, time: .omitted).locale(Lang.shared.locale))
    }

    /// "Today", "In 3 days", "Yesterday" or a short date. `inSentence` lowercases the relative
    /// phrases so they read naturally mid-sentence ("due in 3 days"); dates are left as they are.
    static func relative(_ string: String, inSentence: Bool = false) -> String {
        guard let d = day(string) else { return string }
        let days = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: .now), to: d).day ?? 0
        let phrase: String
        switch days {
        case 0: phrase = tr("Today")
        case 1: phrase = tr("Tomorrow")
        case -1: phrase = tr("Yesterday")
        case 2...6: phrase = tr("In \(days) days")
        case -6 ... -2: phrase = tr("\(-days) days ago")
        default: return d.formatted(.dateTime.month(.abbreviated).day().locale(Lang.shared.locale))
        }
        return inSentence ? phrase.prefix(1).lowercased() + phrase.dropFirst() : phrase
    }

    static func monthLabel(_ yyyymm: String) -> String {
        guard let d = day(yyyymm + "-01") else { return yyyymm }
        return d.formatted(.dateTime.month(.abbreviated).locale(Lang.shared.locale))
    }
}
