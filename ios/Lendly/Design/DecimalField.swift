import SwiftUI

/// A text field for money or percentages that keeps the raw digits the user typed
/// and only parses them. Formatted currency fields reformat on every keystroke,
/// which turns "500" into "$5.00"; this avoids that.
struct DecimalField: View {
    var placeholder: String
    @Binding var value: Decimal?
    var prefix: String? = nil
    var suffix: String? = nil
    var maxFractionDigits = 2
    var font: Font = .body

    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 2) {
            Spacer(minLength: 0)
            if let prefix { Text(prefix).font(font).foregroundStyle(text.isEmpty ? .tertiary : .primary) }
            TextField(placeholder, text: $text)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .font(font)
                .monospacedDigit()
                .fixedSize(horizontal: true, vertical: false)
                .frame(minWidth: 44, alignment: .trailing)
                .focused($focused)
                .onChange(of: text) { _, new in
                    let cleaned = Self.sanitize(new, maxFractionDigits: maxFractionDigits)
                    if cleaned != new { text = cleaned }
                    let parsed = Decimal(string: cleaned, locale: Locale(identifier: "en_US_POSIX"))
                    if parsed != value { value = cleaned.isEmpty ? nil : parsed }
                }
                .onChange(of: value) { _, new in
                    // External change (e.g. a quick-amount chip): mirror into the text unless the user is mid-edit.
                    guard !focused else { return }
                    text = Self.render(new, maxFractionDigits: maxFractionDigits)
                }
                .onChange(of: focused) { _, isFocused in
                    if !isFocused { text = Self.render(value, maxFractionDigits: maxFractionDigits) }
                }
                .onAppear { text = Self.render(value, maxFractionDigits: maxFractionDigits) }
            if let suffix { Text(suffix).foregroundStyle(.secondary) }
        }
    }

    static func sanitize(_ raw: String, maxFractionDigits: Int) -> String {
        var out = ""
        var seenDot = false
        var fraction = 0
        for ch in raw.replacingOccurrences(of: ",", with: ".") {
            if ch.isNumber {
                if seenDot {
                    guard fraction < maxFractionDigits else { continue }
                    fraction += 1
                }
                out.append(ch)
            } else if ch == ".", !seenDot, maxFractionDigits > 0 {
                seenDot = true
                out.append(ch)
            }
        }
        return out
    }

    static func render(_ value: Decimal?, maxFractionDigits: Int) -> String {
        guard let value else { return "" }
        return value.formatted(.number.precision(.fractionLength(0...maxFractionDigits)).grouping(.never).locale(Locale(identifier: "en_US_POSIX")))
    }
}
