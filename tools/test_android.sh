#!/usr/bin/env bash
# Run on the booted CI emulator. Validate the release APK itself, then run
# offline instrumentation against its debug twin (same sources/resources).
set -euo pipefail
RELEASE_APK=$1
DEBUG_APK=$2
TEST_APK=$3
REPORT_DIR=$4
mkdir -p "$REPORT_DIR"
failed() {
  local code=$1 line=$2 command=$3
  trap - ERR
  echo "::error title=Android runtime::line $line failed ($code): $command"
  adb logcat -d -b crash > "$REPORT_DIR/failure-crash.txt" 2>/dev/null || true
  for file in "$REPORT_DIR/failure-crash.txt" "$REPORT_DIR/instrumentation.txt" "$REPORT_DIR/release-launch.txt"; do
    if [ -f "$file" ]; then
      tail -45 "$file" | while IFS= read -r detail; do echo "::error title=Android failure detail::$detail"; done
    fi
  done
  exit "$code"
}
trap 'failed $? "$LINENO" "$BASH_COMMAND"' ERR
adb logcat -c
adb install -r "$RELEASE_APK"
API=$(adb shell getprop ro.build.version.sdk | tr -d '\r')
if [ "$API" -ge 33 ]; then adb shell pm grant com.soundcloudx.app android.permission.POST_NOTIFICATIONS; fi
adb shell am start -W -n com.soundcloudx.app/.MainActivity > "$REPORT_DIR/release-launch.txt"
cat "$REPORT_DIR/release-launch.txt"
grep -q 'Status: ok' "$REPORT_DIR/release-launch.txt"
# Wait through the first lifecycle/network callbacks and return from background.
sleep 3
adb shell input keyevent KEYCODE_HOME
adb shell am start -W -n com.soundcloudx.app/.MainActivity >> "$REPORT_DIR/release-launch.txt"
sleep 2
adb shell pidof com.soundcloudx.app > "$REPORT_DIR/release-pid.txt"
adb exec-out screencap -p > "$REPORT_DIR/release-screen.png"
adb logcat -d -b crash > "$REPORT_DIR/release-crash.txt"
if grep -q 'com.soundcloudx.app' "$REPORT_DIR/release-crash.txt"; then cat "$REPORT_DIR/release-crash.txt"; exit 1; fi
adb shell am force-stop com.soundcloudx.app
adb install -r "$DEBUG_APK"
adb install -r "$TEST_APK"
if [ "$API" -ge 33 ]; then adb shell pm grant com.soundcloudx.app.debug android.permission.POST_NOTIFICATIONS; fi
if [ "$API" -le 28 ]; then adb shell pm grant com.soundcloudx.app.debug android.permission.WRITE_EXTERNAL_STORAGE; fi
adb shell am instrument -w com.soundcloudx.app.debug.test/androidx.test.runner.AndroidJUnitRunner | tee "$REPORT_DIR/instrumentation.txt"
# adb returns zero even for failed tests: inspect the actual runner result.
grep -q 'OK (5 tests)' "$REPORT_DIR/instrumentation.txt"
if grep -Eq 'FAILURES|INSTRUMENTATION_FAILED|Process crashed' "$REPORT_DIR/instrumentation.txt"; then exit 1; fi
adb logcat -d > "$REPORT_DIR/logcat.txt"
echo "Release launch/resume and 5 real runtime tests passed on API $API" > "$REPORT_DIR/result.txt"
