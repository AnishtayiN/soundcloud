#!/usr/bin/env bash
set -euo pipefail
collect_live_evidence() {
  timeout 20s adb logcat -d -s SoundCloudX:* AndroidRuntime:E ActivityManager:W > live-logcat.txt || true
  timeout 20s adb exec-out run-as com.soundcloudx.app.debug cat files/smoke-fa-24.png > live-smoke-fa-24.png || true
  timeout 20s adb exec-out run-as com.soundcloudx.app.debug cat files/smoke-fa-34.png > live-smoke-fa-34.png || true
  timeout 20s adb exec-out run-as com.soundcloudx.app.debug cat files/smoke-fa-36.png > live-smoke-fa-36.png || true
}
trap collect_live_evidence EXIT
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
debug_apk=$(find testing -maxdepth 1 -name '*-debug.apk' ! -name '*androidTest*' -print -quit)
if [ -z "$debug_apk" ]; then echo 'debug APK missing' >&2; exit 1; fi
adb install -r "$debug_apk"
adb install -r testing/app-debug-androidTest.apk
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
adb shell am instrument -w -r com.soundcloudx.app.debug.test/androidx.test.runner.AndroidJUnitRunner | tee instrumentation.txt
grep -q 'INSTRUMENTATION_CODE: -1' instrumentation.txt
if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|shortMsg=' instrumentation.txt; then exit 1; fi
package=com.soundcloudx.app.debug
collect_live_evidence
