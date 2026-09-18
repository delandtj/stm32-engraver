#!/usr/bin/env bash
# PLACEMENT TEST - not the routing step.
#
# Autoroutes a throwaway copy of the board at the committed design rules with
# the router forbidden to relax them, and prints the three numbers that say
# whether the placement can be routed at all:
#
#   open nets      how many nets the router could not finish
#   vias           how many it needed
#   DRC errors     kicad-cli, graded against the ORIGINAL .kicad_pro
#
# Nothing it produces is ever committed and the router never sees a repo file.
# ADR 0003 risk "Autorouter rewrites the rules": KiCadRoutingTools relaxes the
# minimums in the sibling .kicad_pro to whatever it managed to build and then
# grades itself against them, so this script runs it with --escalation off
# --strict-sizes, copies the pristine project back over whatever the router
# wrote, and grades only with kicad-cli.
#
#   tools/pcb/routability.sh [label]
#
# Environment:
#   KRT_DIR   KiCadRoutingTools checkout   (default: see below)
#   KRT_PY    python with numpy/scipy/shapely and pcbnew
#   WORK      scratch directory; MUST be outside the git repo
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
proj="$(cd "$here/../.." && pwd)"
label="${1:-run}"

scratch_default="/tmp/claude-1000/-home-delandtj-Electronics-stm32-engraver/c35434fb-71f8-4fe0-a190-ed9924ac831a/scratchpad"
KRT_DIR="${KRT_DIR:-$scratch_default/routetest/KiCadRoutingTools}"
KRT_PY="${KRT_PY:-$scratch_default/routetest/venv/bin/python}"
WORK="${WORK:-$scratch_default/routability/$label}"

[ -d "$KRT_DIR" ] || { echo "KRT_DIR not found: $KRT_DIR" >&2; exit 2; }
[ -x "$KRT_PY" ]  || { echo "KRT_PY not executable: $KRT_PY" >&2; exit 2; }

# --- refuse to work inside the repository ---------------------------------
repo_root="$(git -C "$proj" rev-parse --show-toplevel 2>/dev/null || true)"
mkdir -p "$WORK"
work_abs="$(cd "$WORK" && pwd -P)"
if [ -n "$repo_root" ]; then
    root_abs="$(cd "$repo_root" && pwd -P)"
    case "$work_abs/" in
        "$root_abs"/*)
            echo "REFUSING: work dir $work_abs is inside the git repo $root_abs" >&2
            echo "Set WORK to a path outside the repository." >&2
            exit 3 ;;
    esac
fi
echo "work dir: $work_abs  (outside $root_abs)"

rm -f "$WORK"/*.kicad_pcb "$WORK"/*.kicad_pro "$WORK"/*.json "$WORK"/*.log
cp "$proj/graver-controller.kicad_pcb" "$WORK/p0.kicad_pcb"
cp "$proj/graver-controller.kicad_pro" "$WORK/p0.kicad_pro"
cp "$proj/graver-controller.kicad_pro" "$WORK/pristine.kicad_pro"

run() { ( cd "$KRT_DIR" && "$KRT_PY" "$@" ); }

echo "--- pour GND on B.Cu"
run py_router/route_planes.py "$WORK/p0.kicad_pcb" "$WORK/p1.kicad_pcb" \
    --nets GND --plane-layers B.Cu --clearance 0.15 --zone-clearance 0.25 \
    --via-size 0.6 --via-drill 0.3 >"$WORK/planes.log" 2>&1 || true
cp "$WORK/pristine.kicad_pro" "$WORK/p1.kicad_pro"

echo "--- USB differential pair"
run py_router/route_diff.py "$WORK/p1.kicad_pcb" "$WORK/p2.kicad_pcb" \
    --nets "*USB_DP" "*USB_DM" --track-width 0.2 --diff-pair-gap 0.15 \
    --clearance 0.15 --grid-step 0.05 --via-size 0.6 --via-drill 0.3 \
    --escalation off --strict-sizes \
    >"$WORK/diff.log" 2>&1 || true
cp "$WORK/pristine.kicad_pro" "$WORK/p2.kicad_pro"

echo "--- everything else, strict"
run py_router/route.py "$WORK/p2.kicad_pcb" "$WORK/p3.kicad_pcb" --nets "*" \
    --track-width 0.2 --clearance 0.15 --via-size 0.6 --via-drill 0.3 \
    --grid-step 0.05 --escalation off --strict-sizes --write-fill \
    --power-nets GND +3V3 +5V VBUS /MCU/VDDA VIN /Driver/COIL_NEG \
        /Driver/CLAMP /Driver/SHUNT_HI \
    --power-nets-widths 0.4 0.5 0.5 0.5 0.4 0.8 0.8 0.8 0.8 \
    --json-out "$WORK/route.json" >"$WORK/route.log" 2>&1 || true

# Grade against the COMMITTED rules, not whatever the router left behind.
cp "$WORK/p3.kicad_pcb" "$WORK/graded.kicad_pcb"
cp "$WORK/pristine.kicad_pro" "$WORK/graded.kicad_pro"
kicad-cli pcb drc --severity-all --format json \
    -o "$WORK/drc.json" "$WORK/graded.kicad_pcb" >/dev/null 2>&1 || true

python3 - "$WORK" <<'PY'
import collections, json, os, re, sys
w = sys.argv[1]
print("\n=== routability ===")
op = []
try:
    d = json.load(open(os.path.join(w, "route.json")))
    for key in ("open_single", "failed_single", "failed_nets"):
        for n in d.get(key) or []:
            if n not in op:
                op.append(n)
    print("routed %s, failed %s, vias %s, min clearance used %s"
          % (d.get("successful"), d.get("failed"), d.get("total_vias"),
             d.get("min_clearance_used")))
except Exception as e:
    print("route.json unreadable: %s" % e)
log = ""
try:
    log = open(os.path.join(w, "route.log"), errors="replace").read()
except Exception:
    pass
for m in re.finditer(r"boxed_in\w*", log):
    pass
names = sorted(set(re.findall(r"open nets?[^\n]*?:\s*([^\n]+)", log)))
if names:
    print("log open-net lines: %s" % "; ".join(names)[:400])
print("OPEN NETS (%d): %s" % (len(op), ", ".join(op) if op else "none"))
try:
    dd = json.load(open(os.path.join(w, "drc.json")))
    errs = [v for v in dd.get("violations", []) if v["severity"] == "error"]
    warns = [v for v in dd.get("violations", []) if v["severity"] != "error"]
    print("kicad-cli DRC errors %d  warnings %d  unconnected %d"
          % (len(errs), len(warns), len(dd.get("unconnected_items") or [])))
    print("  errors by type: %s"
          % dict(collections.Counter(v["type"] for v in errs)))
    print("  warnings by type: %s"
          % dict(collections.Counter(v["type"] for v in warns)))
except Exception as e:
    print("drc.json unreadable: %s" % e)
PY
echo "artifacts in $work_abs"
