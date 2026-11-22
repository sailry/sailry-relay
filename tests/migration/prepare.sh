#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 ]]; then
  echo 'usage: bash tests/migration/prepare.sh HARNESS_CHECKOUT NEW_FIXTURE_DIRECTORY amd64|arm64' >&2
  exit 2
fi
case "$3" in arm64) other=amd64 ;; amd64) other=arm64 ;; *) exit 2 ;; esac
harness=$(cd "$1" && pwd)
relay=$(cd "$(dirname "$0")/../.." && pwd)
arch=$3
mkdir "$2"
fixture=$(cd "$2" && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/sailry-migration-build.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/old" "$scratch/relay"
# Build the shipped updater, not an adapter with the same import path.
commit=$(git -C "$harness" rev-parse 'v0.2.7^{commit}')
[[ $commit == 4d941fb9cd06b4d786c38cff326ab0acbdc12aa4 ]]
git -C "$harness" archive "$commit" -- go.mod go.sum internal cmd/sailry-libp2p-relay | tar -x -C "$scratch/old"
unset GOROOT
export GOTOOLCHAIN=go1.27.3 CGO_ENABLED=0 GOWORK=off
GOOS=linux GOARCH=$arch go -C "$scratch/old" build -mod=readonly -trimpath -buildvcs=false \
  -o "$fixture/v0.2.7" ./cmd/sailry-libp2p-relay
# Isolate the release packager's output from concurrent release builds.
cp -R "$relay/data-relay" "$relay/LICENSE" "$relay/NOTICE" "$relay/TRADEMARKS.md" "$scratch/relay/"
for target in "$arch" "$other"; do
  bash "$scratch/relay/data-relay/scripts/package-linux.sh" "$target" --harness-bridge
done
bash "$scratch/relay/data-relay/scripts/package-linux.sh" "$arch"
cp -R "$scratch/relay/.runtime/relay-bridge" "$scratch/relay/.runtime/relay" "$fixture/"
cp "$relay/tests/migration/guest.py" "$fixture/"
