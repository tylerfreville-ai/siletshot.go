#!/usr/bin/env bash
set -euo pipefail

RESULTS="${1:-smoke-results}"
APK="${2:-Veil-Smoke-Test.apk}"
PACKAGE="com.veil.browser"
ACTIVITY="com.veil.browser/.BrowserActivity"
mkdir -p "$RESULTS"

cleanup() {
  adb shell wm size reset >/dev/null 2>&1 || true
  adb shell wm density reset >/dev/null 2>&1 || true
}
trap cleanup EXIT

adb devices -l | tee "$RESULTS/adb-devices.txt"
adb shell getprop > "$RESULTS/device-properties.txt"
adb install -r "$APK" | tee "$RESULTS/install.txt"
grep -q 'Success' "$RESULTS/install.txt"

run_layout() {
  local name="$1"
  local size="$2"
  local density="$3"
  local expected="$4"

  adb shell wm size "$size"
  adb shell wm density "$density"
  adb shell am force-stop "$PACKAGE"
  adb logcat -c
  adb shell am start -W -n "$ACTIVITY" | tee "$RESULTS/${name}-start.txt"
  grep -q 'Status: ok' "$RESULTS/${name}-start.txt"
  sleep 7

  local pid
  pid="$(adb shell pidof "$PACKAGE" | tr -d '\r')"
  if [[ -z "$pid" ]]; then
    echo "Veil process did not remain alive in ${name} layout." >&2
    exit 1
  fi
  printf '%s\n' "$pid" > "$RESULTS/${name}-pid.txt"

  adb exec-out screencap -p > "$RESULTS/${name}.png"
  adb shell uiautomator dump "/sdcard/${name}.xml"
  adb pull "/sdcard/${name}.xml" "$RESULTS/${name}.xml" >/dev/null
  adb logcat -d --pid="$pid" -v threadtime > "$RESULTS/${name}-logcat.txt"

  if grep -Eq 'FATAL EXCEPTION|Process: com\.veil\.browser.*has died' "$RESULTS/${name}-logcat.txt"; then
    echo "Crash signature found in ${name} logcat." >&2
    exit 1
  fi

  file "$RESULTS/${name}.png" | tee "$RESULTS/${name}-image.txt"
  grep -q "$expected" "$RESULTS/${name}-image.txt"
}

run_layout compact 1080x2400 420 'PNG image data, 1080 x 2400'
run_layout expanded 2208x1840 420 'PNG image data, 2208 x 1840'

adb shell dumpsys package "$PACKAGE" > "$RESULTS/package.txt"
adb shell dumpsys activity activities > "$RESULTS/activity.txt"
grep -q 'versionCode=201' "$RESULTS/package.txt"
grep -q 'versionName=2.0.1' "$RESULTS/package.txt"

# Text availability differs slightly by WebView/emulator accessibility builds,
# so these are recorded for review without making launch success depend on them.
grep -Eo 'text="[^"]+"' "$RESULTS/compact.xml" | head -n 80 > "$RESULTS/compact-visible-text.txt" || true
grep -Eo 'text="[^"]+"' "$RESULTS/expanded.xml" | head -n 120 > "$RESULTS/expanded-visible-text.txt" || true

printf 'Veil Browser 2.0.1 smoke test passed for compact and expanded layouts.\n' \
  | tee "$RESULTS/RESULT.txt"
