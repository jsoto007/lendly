#!/usr/bin/env bash
# Archive the iOS app with automatic signing and upload it to App Store Connect (TestFlight).
#
# Auth, one of:
#   A) Xcode → Settings → Accounts signed in with the Apple ID that belongs to team TZZNAY63L5
#      (nothing else to set; xcodebuild uses that session).
#   B) An App Store Connect API key (Users and Access → Integrations → Team Keys, role App Manager
#      or Admin). Export before running:
#        export ASC_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8
#        export ASC_KEY_ID=XXXXXXXXXX
#        export ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
#
# Usage: scripts/testflight.sh            (build number = git commit count)
#        BUILD_NUMBER=42 scripts/testflight.sh
set -euo pipefail
cd "$(dirname "$0")/../ios"

BUILD_NUMBER="${BUILD_NUMBER:-$(git rev-list --count HEAD)}"
ARCHIVE="../.build/Lendly.xcarchive"
AUTH=()
if [[ -n "${ASC_KEY_PATH:-}" ]]; then
  AUTH=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
fi

echo "==> Generating project (build $BUILD_NUMBER)"
ORIGINAL_PROJECT_YML="$(cat project.yml)"
restore_project_yml() {  # leave the repo as we found it, whatever happens below
  printf '%s\n' "$ORIGINAL_PROJECT_YML" > project.yml
  xcodegen generate >/dev/null 2>&1 || true
}
trap restore_project_yml EXIT
sed -i '' "s/CFBundleVersion: \"[0-9]*\"/CFBundleVersion: \"$BUILD_NUMBER\"/" project.yml
xcodegen generate >/dev/null

echo "==> Archiving (Release, signed)"
rm -rf "$ARCHIVE"
xcodebuild -project Lendly.xcodeproj -scheme Lendly -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates "${AUTH[@]}" archive | grep -E "error:|ARCHIVE (SUCCEEDED|FAILED)" || true
[[ -d "$ARCHIVE" ]] || { echo "archive missing"; exit 1; }

echo "==> Uploading to App Store Connect"
xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist ExportOptions.plist \
  -exportPath ../.build/export -allowProvisioningUpdates "${AUTH[@]}" | grep -E "error:|EXPORT (SUCCEEDED|FAILED)|Upload" || true
echo "Done. The build appears in App Store Connect → TestFlight after Apple's processing (usually 5–15 min)."
