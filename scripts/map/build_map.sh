#!/usr/bin/env bash
# Rebuild data/map/lebanon.pmtiles from OpenStreetMap data (needs internet;
# run on a laptop, then publish the file as a GitHub Release asset).
#
#   bash scripts/map/build_map.sh [YYYYMMDD]
#
# Source: the Protomaps daily planet build (OpenStreetMap data, ODbL), cut to
# Lebanon's bounding box with the official pmtiles tool. Only the parts of the
# planet file inside the box are downloaded (HTTP range requests).
# Uses a pmtiles tool on PATH if there is one; otherwise installs it with Go,
# or, without Go, downloads the official prebuilt tool (checksum-checked).
set -euo pipefail
cd "$(dirname "$0")/../.."

DAY="${1:-$(date -u -d '2 days ago' +%Y%m%d)}"     # daily builds appear with a short delay
SRC="https://build.protomaps.com/${DAY}.pmtiles"
BBOX="35.05,33.00,36.70,34.75"                      # Lebanon + a small margin (lon,lat,lon,lat)
MAXZOOM=15                                          # village lanes and paths are present at z14-15
OUT="data/map/lebanon.pmtiles"

PMTILES_VERSION=1.31.2
PMTILES="$(command -v pmtiles || true)"
[ -z "$PMTILES" ] && [ -x .tools/pmtiles ] && PMTILES="$PWD/.tools/pmtiles"

# Without Go: download the official prebuilt pmtiles tool and check it against
# the SHA-256 recorded here (the release publishes no checksum file).
fetch_pmtiles() {
  local os arch name sum url tmp
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os/$arch" in
    Linux/x86_64)  name="go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
                   sum=3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f ;;
    Linux/aarch64|Linux/arm64)
                   name="go-pmtiles_${PMTILES_VERSION}_Linux_arm64.tar.gz"
                   sum=f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1 ;;
    Darwin/x86_64) name="go-pmtiles-${PMTILES_VERSION}_Darwin_x86_64.zip"
                   sum=1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b ;;
    Darwin/arm64)  name="go-pmtiles-${PMTILES_VERSION}_Darwin_arm64.zip"
                   sum=40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d ;;
    *) echo "No prebuilt pmtiles for $os/$arch: install Go (https://go.dev/dl/) and run again." >&2
       exit 1 ;;
  esac
  url="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/$name"
  tmp="$(mktemp -d)"
  echo "==> Downloading the pmtiles tool ($name)"
  curl -fsSL "$url" -o "$tmp/$name"
  if command -v sha256sum >/dev/null; then got="$(sha256sum "$tmp/$name" | cut -d' ' -f1)"
  else got="$(shasum -a 256 "$tmp/$name" | cut -d' ' -f1)"; fi
  if [ "$got" != "$sum" ]; then
    echo "Checksum mismatch for $name; not using it." >&2; rm -rf "$tmp"; exit 1
  fi
  mkdir -p .tools
  case "$name" in
    *.zip) unzip -q -o "$tmp/$name" pmtiles -d .tools ;;
    *)     tar -xzf "$tmp/$name" -C .tools pmtiles ;;
  esac
  rm -rf "$tmp"
  chmod +x .tools/pmtiles
  PMTILES="$PWD/.tools/pmtiles"
}

if [ -z "$PMTILES" ]; then
  if command -v go >/dev/null; then
    echo "==> Installing the pmtiles tool (go install github.com/protomaps/go-pmtiles@v${PMTILES_VERSION})"
    GOBIN="$PWD/.tools" go install "github.com/protomaps/go-pmtiles@v${PMTILES_VERSION}"
    PMTILES="$PWD/.tools/go-pmtiles"
  else
    fetch_pmtiles
  fi
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
