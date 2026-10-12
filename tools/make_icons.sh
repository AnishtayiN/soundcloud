#!/usr/bin/env bash
# Regenerates every icon used by the Android app and the Windows app.
# Requires ImageMagick (the `convert` command).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RES="$ROOT/android/app/src/main/res"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

E="convert"

# ---------------------------------------------------------------- base art ----
# 512x512 brand gradient
$E -size 512x512 "gradient:#FF7A2F-#FF3D00" "$TMP/bg.png"

# white cloud on transparent background (drawn on the gradient directly)
draw_cloud() {
  $E "$1" \
    -fill 'rgba(255,255,255,0.97)' \
    -draw "circle 185,302 185,240" \
    -draw "circle 288,262 288,172" \
    -draw "circle 372,312 372,257" \
    -draw "rectangle 185,318 372,366" \
    -fill '#FF3D00' \
    -draw "polygon 249,252 249,332 318,292" \
    "$2"
}

draw_cloud "$TMP/bg.png" "$TMP/base.png"

# round (circular) version for launchers that ask for it
$E -size 512x512 xc:none -fill white -draw "circle 256,256 256,2" "$TMP/mask.png"
$E "$TMP/base.png" "$TMP/mask.png" -alpha off -compose CopyOpacity -composite "$TMP/round.png"

# adaptive-icon foreground: cloud only, scaled to ~62% and centered
$E -size 512x512 xc:none -fill white -draw "circle 185,302 185,240" \
   -draw "circle 288,262 288,172" -draw "circle 372,312 372,257" \
   -draw "rectangle 185,318 372,366" -fill '#FF3D00' \
   -draw "polygon 249,252 249,332 318,292" "$TMP/fg512.png"
$E "$TMP/fg512.png" -resize 62% -background none -gravity center -extent 512x512 "$TMP/fg.png"

# ------------------------------------------------------------------ android ----
for spec in "mdpi:48" "hdpi:72" "xhdpi:96" "xxhdpi:144" "xxxhdpi:192"; do
  d="${spec%%:*}"; s="${spec##*:}"
  mkdir -p "$RES/mipmap-$d"
  $E "$TMP/base.png"  -resize "${s}x${s}" "$RES/mipmap-$d/ic_launcher.png"
  $E "$TMP/round.png" -resize "${s}x${s}" "$RES/mipmap-$d/ic_launcher_round.png"
done

for spec in "mdpi:108" "hdpi:162" "xhdpi:216" "xxhdpi:324" "xxxhdpi:432"; do
  d="${spec%%:*}"; s="${spec##*:}"
  $E "$TMP/fg.png" -resize "${s}x${s}" "$RES/mipmap-$d/ic_launcher_foreground.png"
done

mkdir -p "$RES/mipmap-anydpi-v26"
for name in ic_launcher ic_launcher_round; do
  cat > "$RES/mipmap-anydpi-v26/$name.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_bg" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
XML
done

# ------------------------------------------------------------------ windows ----
mkdir -p "$ROOT/windows/assets"
$E "$TMP/base.png" -define icon:auto-resize=256,128,64,48,32,24,16 "$ROOT/windows/assets/icon.ico"
$E "$TMP/base.png" -resize 128x128 "$ROOT/windows/assets/icon.png"
$E "$TMP/base.png" -resize 512x512 "$ROOT/docs/icon.png"

echo "icons generated ✔"
