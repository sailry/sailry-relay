#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'usage: package-linux.sh <amd64|arm64>' >&2
  exit 1
}

test "$#" -eq 1 || usage
case "$1" in amd64|arm64) ;; *) usage ;; esac

relay_dir=$(cd "$(dirname "$0")/.." && pwd)
repo_dir=$(dirname "$relay_dir")
command=./cmd/sailry-relay
program=github.com/sailry/sailry-relay/data-relay/cmd/sailry-relay

unset GOROOT
export GOTOOLCHAIN=go1.27.3 CGO_ENABLED=0 GOWORK=off GOOS=linux GOARCH="$1"
export LC_ALL=C TZ=UTC
umask 022

target=linux-$GOARCH
output=$repo_dir/.runtime/relay/$target
archive=sailry-relay-$target.tar.gz
checksum=SHA256SUMS-relay-$target
scratch=$(mktemp -d "${TMPDIR:-/tmp}/sailry-relay-XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
stage=$scratch/package
mkdir -p "$stage/licenses"

go -C "$relay_dir" build -mod=readonly -trimpath -o "$stage/sailry-relay" "$command"
go version -m "$stage/sailry-relay" |
  awk -v program="$program" -v arch="$GOARCH" '
    $1 == "path" && $2 == program { path_ok = 1 }
    $1 == "build" && $2 == "GOOS=linux" { os_ok = 1 }
    $1 == "build" && $2 == "GOARCH=" arch { arch_ok = 1 }
    END { exit !(path_ok && os_ok && arch_ok) }
  ' || { echo "Expected $program built for linux/$GOARCH" >&2; exit 1; }
chmod 755 "$stage/sailry-relay"
cp "$repo_dir/LICENSE" "$repo_dir/NOTICE" "$repo_dir/TRADEMARKS.md" "$stage/"
goroot=$(go -C "$relay_dir" env GOROOT)
cp "$goroot/LICENSE" "$stage/licenses/go-LICENSE"
cp "$goroot/PATENTS" "$stage/licenses/go-PATENTS"

go -C "$relay_dir" list -mod=readonly -deps \
  -f '{{with .Module}}{{if .Version}}{{.Path}}{{"\t"}}{{.Version}}{{"\t"}}{{.Dir}}{{end}}{{end}}' "$command" |
  awk 'NF' | sort -u > "$scratch/modules.tsv"
while IFS=$'\t' read -r name version directory; do
  destination=$stage/licenses/go/$name@$version
  find "$directory" -type f \( -name 'LICENSE*' -o -name 'LICENCE*' -o -name 'COPYING*' -o -name 'PATENTS*' \
    -o -name 'NOTICE*' -o -name 'THIRD_PARTY_NOTICES*' \) -print0 > "$scratch/notices"
  found=false
  while IFS= read -r -d '' notice; do
    dest_file=$destination/${notice#"$directory/"}
    mkdir -p "$(dirname "$dest_file")"
    cp "$notice" "$dest_file"
    found=true
  done < "$scratch/notices"
  printf '%s\t%s\t%s\n' "$name" "$version" "$found"
done < "$scratch/modules.tsv" > "$scratch/collected.tsv"
jq -Rs 'split("\n") | map(select(length > 0) | split("\t") | {name:.[0],version:.[1],notices:(.[2] == "true")})' \
  "$scratch/collected.tsv" > "$stage/licenses/go-modules.json"

case "$(tar --version)" in
  *'GNU tar'*) owner=(--owner=0 --group=0) ;;
  *bsdtar*) owner=(--uid 0 --gid 0 --uname root --gname root) ;;
  *) echo 'packaging requires GNU tar or bsdtar' >&2; exit 1 ;;
esac
find "$stage" -exec touch -t 198001010000 {} +
(
  cd "$stage"
  find sailry-relay LICENSE NOTICE TRADEMARKS.md licenses -print | sort > "$scratch/files"
  COPYFILE_DISABLE=1 tar "${owner[@]}" --numeric-owner --no-acls --no-xattrs --no-recursion -cf - -T "$scratch/files" |
    gzip -n > "$scratch/$archive"
)
(
  cd "$scratch"
  if command -v sha256sum > /dev/null; then
    sha256sum "$archive"
  else
    shasum -a 256 "$archive"
  fi > "$checksum"
)
mkdir -p "$output"
mv "$scratch/$archive" "$scratch/$checksum" "$output/"
cat "$output/$checksum"
