#!/usr/bin/env bash
# Rebuild data/map/lebanon.pmtiles from OpenStreetMap data (needs internet;
# run on a laptop, then publish the file as a GitHub Release asset).
#
#   bash scripts/map/build_map.sh [YYYYMMDD]
#
# Source: the Protomaps daily planet build (OpenStreetMap data, ODbL), cut to
# Lebanon's bounding box with the official pmtiles tool. Only the parts of the
# planet file inside the box are downloaded (HTTP range requests).
# Needs Go (to install the pmtiles tool) or a pmtiles binary on PATH.
set -euo pipefail
cd "$(dirname "$0")/../.."

DAY="${1:-$(date -u -d '2 days ago' +%Y%m%d)}"     # daily builds appear with a short delay
SRC="https://build.protomaps.com/${DAY}.pmtiles"
BBOX="35.05,33.00,36.70,34.75"                      # Lebanon + a small margin (lon,lat,lon,lat)
MAXZOOM=15                                          # village lanes and paths are present at z14-15
OUT="data/map/lebanon.pmtiles"

PMTILES="$(command -v pmtiles || true)"
if [ -z "$PMTILES" ]; then
  echo "==> Installing the pmtiles tool (go install github.com/protomaps/go-pmtiles@v1.31.2)"
  GOBIN="$PWD/.tools" go install github.com/protomaps/go-pmtiles@v1.31.2
  PMTILES="$PWD/.tools/go-pmtiles"
fi

mkdir -p data/map
echo "==> Extracting Lebanon from $SRC (max zoom $MAXZOOM)"
"$PMTILES" extract "$SRC" "$OUT.part" --bbox="$BBOX" --maxzoom="$MAXZOOM"
"$PMTILES" verify "$OUT.part"
mv "$OUT.part" "$OUT"
sha256sum "$OUT" | sed 's#  .*#  lebanon.pmtiles#' > "$OUT.sha256"
"$PMTILES" show "$OUT" | head -12
echo "==> Built $OUT ($(du -h "$OUT" | cut -f1)); checksum in $OUT.sha256 (commit that file)."
echo "    Publish $OUT as release asset 'lebanon.pmtiles' (tag map-lebanon-v1) so setup.sh can fetch it."
