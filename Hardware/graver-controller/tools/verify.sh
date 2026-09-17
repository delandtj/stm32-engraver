#!/bin/sh
# Check the schematic: 1. ERC (must be 0 violations)  2. PNG renders for eyeballing.
# The netlist comparison against tools/ref/ went away with the generator
# (ADR 0003): eeschema is the source of truth, ref/ is history.
# Usage: tools/verify.sh [outdir]
set -u
STATUS=0
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$HERE")
OUT=${1:-$PROJ/output/verify}
mkdir -p "$OUT"

kicad-cli sch erc --exit-code-violations -o "$OUT/erc.rpt" "$PROJ/graver-controller.kicad_sch" | grep -i 'violation'
[ $? -eq 0 ] || STATUS=1
grep -q 'ERC messages: 0 ' "$OUT/erc.rpt" || STATUS=1
grep -E '^\[' "$OUT/erc.rpt" | sort | uniq -c || true

kicad-cli sch export svg -o "$OUT" "$PROJ/graver-controller.kicad_sch" >/dev/null
for f in "$OUT"/graver-controller-*.svg; do
    rsvg-convert -b white -w 2400 "$f" -o "${f%.svg}.png"
done
echo "renders in $OUT"
exit $STATUS
