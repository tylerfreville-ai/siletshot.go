#!/usr/bin/env bash
set -euo pipefail

RESULTS="${1:-functional-results}"
APK="${2:-Veil-Smoke-Test.apk}"
PACKAGE="com.veil.browser"
ACTIVITY="com.veil.browser/.BrowserActivity"
mkdir -p "$RESULTS"

cleanup() {
  adb shell wm size reset >/dev/null 2>&1 || true
  adb shell wm density reset >/dev/null 2>&1 || true
}
trap cleanup EXIT

adb install -r "$APK" | tee "$RESULTS/install.txt"
grep -q 'Success' "$RESULTS/install.txt"
adb shell wm size 1080x2400
adb shell wm density 420
adb shell am force-stop "$PACKAGE"
adb logcat -c
adb shell am start -W \
  -a android.intent.action.VIEW \
  -d 'https://example.com/' \
  -n "$ACTIVITY" | tee "$RESULTS/https-start.txt"
grep -q 'Status: ok' "$RESULTS/https-start.txt"
sleep 12

PID="$(adb shell pidof "$PACKAGE" | tr -d '\r')"
test -n "$PID"
adb shell uiautomator dump /sdcard/https.xml
adb pull /sdcard/https.xml "$RESULTS/https.xml" >/dev/null
adb exec-out screencap -p > "$RESULTS/https.png"
grep -qi 'example.com' "$RESULTS/https.xml"

# Open the app menu and select Checkout Mode using accessibility bounds.
adb shell input tap 971 232
sleep 2
adb shell uiautomator dump /sdcard/menu.xml
adb pull /sdcard/menu.xml "$RESULTS/menu.xml" >/dev/null
read -r CHECKOUT_X CHECKOUT_Y < <(python3 - "$RESULTS/menu.xml" <<'PY'
import re, sys, xml.etree.ElementTree as ET
root=ET.parse(sys.argv[1]).getroot()
for node in root.iter('node'):
    if node.attrib.get('text') == 'Checkout Mode':
        m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib['bounds'])
        if not m: raise SystemExit(2)
        x1,y1,x2,y2=map(int,m.groups())
        print((x1+x2)//2, (y1+y2)//2)
        break
else:
    raise SystemExit('Checkout Mode menu item not found')
PY
)
adb shell input tap "$CHECKOUT_X" "$CHECKOUT_Y"
sleep 3
adb shell uiautomator dump /sdcard/checkout-enabled.xml
adb pull /sdcard/checkout-enabled.xml "$RESULTS/checkout-enabled.xml" >/dev/null

# Open the privacy dashboard and verify that Checkout Mode is reported active.
adb shell input tap 338 232
sleep 2
adb shell uiautomator dump /sdcard/dashboard.xml
adb pull /sdcard/dashboard.xml "$RESULTS/dashboard.xml" >/dev/null
grep -Eq 'Checkout Mode is active|Disable Checkout Mode' "$RESULTS/dashboard.xml"
adb exec-out screencap -p > "$RESULTS/checkout-dashboard.png"

adb logcat -d --pid="$PID" -v threadtime > "$RESULTS/app-logcat.txt"
if grep -Eq 'FATAL EXCEPTION|Process: com\.veil\.browser.*has died' "$RESULTS/app-logcat.txt"; then
  echo 'Crash signature found in functional logcat.' >&2
  exit 1
fi

file "$RESULTS/https.png" "$RESULTS/checkout-dashboard.png" > "$RESULTS/images.txt"
printf 'HTTPS navigation and Checkout Mode functional test passed.\n' | tee "$RESULTS/RESULT.txt"
