#!/usr/bin/env bash
# Download the offline street map of Lebanon ONCE (called by setup.sh).
# After this, /map works with no internet. The file is not stored in git.
#
#   bash scripts/map/get_map.sh            # download if missing or damaged
#   SIRENS_MAP_URL=<url> bash scripts/map/get_map.sh   # use another copy
#
# The file is checked against data/map/lebanon.pmtiles.sha256 when that file
# exists (it is written by scripts/map/build_map.sh when the map is built).
set -euo pipefail
cd "$(dirname "$0")/../.."

DEST="data/map/lebanon.pmtiles"
SUMFILE="data/map/lebanon.pmtiles.sha256"
# Where the built file is published (a GitHub Release asset). Set once the
# file has been built and uploaded; see README "Offline street map".
URL="${SIRENS_MAP_URL:-https://github.com/eliesboutros/SirensProject/releases/download/map-lebanon-v1/lebanon.pmtiles}"

sum_ok() {   # $1 = file; true when no checksum is recorded, or when it matches
  [ -f "$SUMFILE" ] || return 0
  [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$(cut -d' ' -f1 "$SUMFILE")" ]
}

mkdir -p data/map
if [ -f "$DEST" ] && sum_ok "$DEST"; then
  echo "==> Offline map already installed ($DEST)"; exit 0
fi

echo "==> Downloading the offline street map (one time): $URL"
if ! curl -fL --retry 3 --retry-delay 2 -o "$DEST.part" "$URL"; then
  rm -f "$DEST.part"
  echo "!! Map download failed. Sirens still works; /map will say the map is not installed."
  echo "!! Try again later with: bash scripts/map/get_map.sh"
  exit 1
fi
if ! sum_ok "$DEST.part"; then
  rm -f "$DEST.part"
  echo "!! The downloaded file does not match $SUMFILE (damaged or wrong file). Not installed."
  exit 1
fi
[ -f "$SUMFILE" ] || echo "   (no checksum recorded yet in $SUMFILE, so the file could not be verified)"
mv "$DEST.part" "$DEST"
echo "==> Offline map installed: $DEST ($(du -h "$DEST" | cut -f1))"
