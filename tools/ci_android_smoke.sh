#!/usr/bin/env bash
set -euo pipefail
# Release install/launch check first; fixture UI tests use the debug app's
# loopback-only test seam and cannot affect the production SoundCloud endpoints.
release_apk=$(find release -name '*.apk' -print -quit)
adb install -r "$release_apk"
# Pre-grant the optional notification prompt so it cannot obscure the UI assertion.
adb shell pm grant com.soundcloudx.app android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb shell am start -W -n com.soundcloudx.app/.MainActivity
adb shell pidof com.soundcloudx.app
adb shell uiautomator dump /sdcard/release-ui.xml
adb pull /sdcard/release-ui.xml release-ui.xml
python - <<'PY'
from pathlib import Path
text = Path('release-ui.xml').read_text(encoding='utf-8')
assert 'جستجو' in text and 'ترندها' in text, 'release did not launch with Persian RTL UI'
PY
adb uninstall com.soundcloudx.app
adb install -r testing/SoundCloudX-1.0.0-debug.apk
adb install -r testing/app-debug-androidTest.apk
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
adb shell am instrument -w -r com.soundcloudx.app.debug.test/androidx.test.runner.AndroidJUnitRunner | tee instrumentation.txt
grep -q 'INSTRUMENTATION_CODE: -1' instrumentation.txt
if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|shortMsg=' instrumentation.txt; then exit 1; fi
package=com.soundcloudx.app.debug
for sdk in 24 34 36; do
  timeout 15s adb pull "/sdcard/Android/data/$package/files/smoke-fa-$sdk.png" "scx-smoke-fa-$sdk.png" 2>/dev/null || true
done
