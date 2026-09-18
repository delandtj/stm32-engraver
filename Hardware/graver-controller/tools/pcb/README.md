# tools/pcb - board generation, placement and the scripted copper

Scripted placement and scripted critical copper for
`graver-controller.kicad_pcb`, per ADR 0003 decision 8. Placement is data in
`place.py`, which regenerates the whole board from the schematic every run;
the critical copper is data in `copper.py`, which draws it on top of that and
locks it. Neither routes the rest.

## Run it

    cd Hardware/graver-controller
    python3 tools/pcb/place.py          # rebuild + place + check
    python3 tools/pcb/copper.py         # zones, keepouts, critical copper
    tools/pcb/render.sh                 # PNGs into output/pcb/

or in one go:

    python3 tools/pcb/place.py --copper

`place.py` needs plain `python3` with the system KiCad 10 `pcbnew` bindings -
no venv, no extra packages. It exits non-zero if any placement check or ADR
distance criterion fails, and prints a table of every criterion with its
measured value.

`--no-netlist` skips the `kicad-cli sch export netlist` step and reuses
`output/pcb/netlist.xml`. Use it while iterating on placement numbers.

Verify independently with:

    kicad-cli pcb drc --schematic-parity --severity-all graver-controller.kicad_pcb

Expected after `place.py` alone: 0 schematic parity issues, 258 unconnected
items, and silkscreen warnings. After `copper.py`: 0 errors, 0 parity, 106
unconnected items. See "Known DRC output" below.

## What it does

1. Exports the kicadxml netlist into `output/pcb/`.
2. Builds a board from all 117 components. Every footprint is linked back to
   its symbol with a KIID path `/<sheet uuid>/<symbol uuid>` taken from the
   netlist, and carries sheetname, sheetfile, Value, LCSC, MPN, Datasheet and
   Description, plus the `in_bom` / `dnp` flags read out of the `.kicad_sch`
   files. That is what makes "Update PCB from schematic" in the GUI a no-op.
3. Draws the 110 x 70 mm outline with 2 mm corner radii on Edge.Cuts and sets
   the aux and grid origin to the board's top-left corner at page (50, 50).
4. Places everything, checks it, and saves.

Orientation is KiCad top view: rear edge (connectors) at y = 0, front edge at
y = 70, x = 0 at the left as the seated user sees the console.

## How to nudge a part

Everything is in a handful of tables near the top of `place.py`.

- `EDGE_PARTS` - the four rear connectors: `(x, rotation, out_axis,
  overhang)`. Only `x` and `overhang` are normally worth changing; the script
  slides each part along y itself so the mating face lands `overhang` mm past
  the rear edge.
- `ANCHORS` - one entry per block, `(anchor_x, anchor_y)` plus rows of
  `(ref, dx, dy, rotation)`. Move a whole block by editing its anchor.
- `DECAPS` and `SATELLITES` - `(host pad, own pin, out, side)`. The part is
  put on the outward normal of the host pin, `out` mm away and `side` mm
  across. Two caps flanking one pin is `side = -1.5` and `side = +1.5`. The
  named pin is aimed at the host automatically: all four rotations are tried
  and the one that puts that pad nearest the host pad wins.
- `MCU_LINKS` / `MCU_SEARCH_X` / `MCU_SEARCH_Y` / `MCU_HALO` - the MCU pose
  search (below). `MCU_REFERENCE_POSE` is only there so the run prints how the
  winner compares with the first pass's hand-picked pose.
- `FLYBACK_CANDIDATES` - named arrangements for the clamp corner. The script
  tries each, scores it by clamp-loop perimeter, and keeps the best; add a
  candidate rather than editing the winner.
- `XTAL_ISLAND` - the crystal and its two load caps as offsets `(along the QFN
  edge, outward)`. They are placed as one RIGID group.
- `GROUP_SEED` / `GROUP_OVERRIDE` - which parts start a function group.
  Satellites inherit their host's group, and `COURTYARD_GAP` (0.5 mm) applies
  only between different groups; inside a group it is `GROUP_GAP` (0.15 mm).
  That is what lets a decoupling cap sit against its IC while unrelated blocks
  stay half a millimetre apart.

### MCU pose by search

The MCU plus everything that must sit at its pins is treated as one rigid
cluster. `place.py` places every block whose position does NOT depend on the
MCU first (rear connectors, power, driver, buttons, front furniture), then
scores all four rotations over a 2 mm grid in x 34..70 / y 24..48, rejecting
any pose whose `MCU_HALO` ring is not clear or that comes within 15 mm of the
buck. The score is a weighted sum of straight-line distances from MCU pads to
the fixed parts they have to reach: USB 3, LCD and the driver signals 2,
pedal/NTC/VIN_SENSE 1.5, encoder and SWD/NRST/BOOT0 1. The run prints the top
five poses, the per-link distances and the comparison with the first pass.

Every placement is snapped to a 0.5 mm grid (0.25 mm for the MCU decoupling)
and then spiral-searched outwards until its courtyard is clear, so a seed that
collides still lands somewhere sane - the script prints every nudge it made.
If you see a part nudged by more than about 2 mm, its table entry is wrong,
not the resolver.

`CRITERIA` holds the ADR distance rules that get measured and printed.
`WATCH_NETS` holds the nets whose ratsnest length (MST over the pads) is
printed every run - use it to tell whether a nudge helped.

## Rules

- **The autorouter never runs on these files.** ADR 0003 risk "Autorouter
  rewrites the rules": KiCadRoutingTools relaxes the minimums in the sibling
  `.kicad_pro` to whatever it managed to build and then grades itself against
  them. Copy the project elsewhere, run it there with `--escalation off
  --strict-sizes`, and grade only with `kicad-cli pcb drc` against the
  committed `.kicad_pro`.
- **`graver-controller.kicad_pro` is a committed file and must not move.**
  `pcbnew.SaveBoard` rewrites it as a side effect, so `place.py` snapshots it
  before saving and restores it afterwards, printing which of the two
  happened. If a run ever reports the project as changed and not restored,
  that is a bug - do not commit the result.
- `graver-controller.kicad_pcb` is derived. Until routing starts, do not hand
  edit it; change `place.py` and re-run. Once Jan starts routing, this script
  stops being safe to re-run and the board becomes the source of truth.

## Connector orientation

Each right-angle connector's mating direction was read off its own footprint
geometry rather than guessed:

| ref  | footprint evidence | local face | rot | overhang |
|------|--------------------|-----------|-----|----------|
| J101 | F.Fab -13.7..0.8 in x with a flange line at -10.2; the 3.5 mm beyond it is the barrel nose | -x | 270 | 3.5 mm |
| J301 | F.Fab body -3.65..3.65 in y, contact tails at y = -4.045 behind it | +y | 180 | 0.5 mm |
| J201 | silkscreen draws four wire-entry funnels at y = 8.61..10.11, one per contact | +y | 180 | 0 mm |
| J402 | F.Fab body ends at x = 16.7 with the 3 mm chrome ferrule out to 19.7 | +x | 90 | 3.0 mm |

Rotation 180 is **forced** for J201: the four wire-entry funnels are drawn on
its +y side, so nothing else points them out of the rear edge. That reverses
the pin order on the board. Seen from the front, left to right:

| board x | pin | net |
|---------|-----|-----|
| 54.26 | 4 | GND |
| 59.34 | 3 | NTC |
| 64.42 | 2 | COIL_NEG |
| 69.50 | 1 | VIN |

The silkscreen legend and the GX12 pigtail wiring both have to follow that
order, not the schematic's.

J302 (SWD) lies **along** the rear edge at rotation 90, pin 1 at x = 37.0 and
pin 5 at x = 47.16, all at y = 2.5. It fits there because J301 moved 3 mm left
(x 32.0 -> 29.0); at rotation 0 it stuck 14 mm down into the MCU's rear side.

## Known DRC output

`kicad-cli pcb drc --schematic-parity --severity-all` on the placed board
with the scripted copper:

| type | count | why |
|------|-------|-----|
| schematic parity | 0 | clean |
| errors | 0 | clean |
| unconnected_items | 107 | what the router still has to finish (258 after `place.py` alone) |
| silk_overlap | 125 | silkscreen is a later pass |
| silk_over_copper | 89 | ditto |
| silk_edge_clearance | 17 | ditto |
| track_dangling | 15 | the QFN fanout stubs, dangling on purpose |
| via_dangling | 6 | fanout and stitching vias the router has not reached yet |

Silkscreen has not been touched at all: every reference is still at its
library default offset, and the second pass packs parts tighter, so the count
went up. Cleaning it up is a pass of its own, after routing.

The assembly view instead gets its labels from F.Fab: `place.py` hides every
footprint's **Value** field (it was the "100nF 100V" text that buried
`placement.png`) and scales each footprint's F.Fab `${REFERENCE}` to fit the
body it sits in, which the library gets backwards - 0.4 mm on an 0603 and
1.0 mm on a QFN.

## Copper

`copper.py` draws the scripted, locked critical copper ADR 0003 decision 8
calls for. It runs after `place.py` and is idempotent: everything it makes
goes into a PCB group named `scripted-copper`, and the first thing a run does
is delete that group's members, so re-running replaces the copper instead of
stacking it. Every item it makes is **locked**, which is what keeps the
autorouter off it - KiCadRoutingTools refuses to rip KiCad-locked copper.

    python3 tools/pcb/copper.py              # draw + refill + DRC
    python3 tools/pcb/copper.py --no-drc     # skip the kicad-cli DRC step
    python3 tools/pcb/copper.py --no-refill  # skip the zone fill

Like `place.py` it snapshots `graver-controller.kicad_pro` before saving and
restores it afterwards, and prints which of the two happened.

### What is scripted and locked

| # | what | numbers |
|---|------|---------|
| 1 | GND pour on B.Cu over the whole outline | 0.25 mm clearance, 0.20 mm min width, thermal reliefs on THT, solid on SMD |
| 1 | four ground-free rule areas at the M3 holes | 6 mm diameter, both layers, no pour; User.2 copies for `--keepout` |
| 1 | crystal keepout over Y301/C310/C311 | rule area = no vias both layers; User.2 copy = no router tracks; the pour is kept (ADR: ground guard, no signal under it) |
| 2 | U301 QFN fanout | 0.20 mm radial stubs on 20 pads, 0.56-0.71 mm of new copper past each pad edge; 4 vias 0.6/0.3 at 1.55 mm on pads 18/20/42/44 |
| 2 | U301 GND pins 8/23/35/47 | 0.20 mm, 0.64 mm into the EP copper |
| 2 | U301 EP | 4 vias 0.6/0.3 inside the pad |
| 3 | decoupling | 13 pin-to-cap traces on F.Cu; 60 of 62 SMD ground pads get their own via into the pour |
| 3 | U101 PowerPAD | 4 thermal vias 0.6/0.3 |
| 4 | crystal | OSC_IN 5.95 mm, OSC_OUT 6.51 mm, F.Cu only, 0 vias; F.Cu ground guard bracket + 4 stitching vias |
| 5 | VDDA | FB301 -> C306/C307 at 0.40 mm, pin 9 -> C306 9.27 mm on F.Cu, 0 vias |
| 6 | USB | D+ 39.80 mm, D- 38.98 mm, skew 0.82 mm, **0 vias on either net** |
| 7 | power | VIN chain 0.8 mm, flyback loop 1.0 mm, gate 0.4 mm, shunt 1.0 mm, Kelvin taps 0.2 mm, buck, +5 V/+3V3 0.5 mm |
| 8 | ADC filters | the RC parts at the MCU pins, 0.25 mm, only where the part is within 12 mm |

### Budgets, and how they came out

| budget | source | measured |
|--------|--------|----------|
| USB pair <= 40 mm, 0 vias, <= 1 mm skew | ADR 0003 component breakdown 3 | 39.80 / 38.98 mm, 0 vias, 0.82 mm - PASS, and with almost no margin on the 40 mm |
| USB coupled 0.2 mm / 0.15 mm | ADR + Jan 2026-09-18 | 0.15 mm gap on the long connector segment; 0.30 mm on the two U302 -> MCU lanes, which U302's own 1.9 mm pin pitch forces |
| flyback loop closed within ~15 mm | ADR decision 4 | 20.26 mm of real copper over its four legs, parts inside a 10 x 12 mm block under the terminal |
| buck CIN within 3 mm of the VIN pin | ADR component breakdown 2 | 2.88 / 2.74 mm pad to pad, 6.95 mm of copper |
| crystal keepout clean | ADR decision 8 | clean: only OSC_IN, OSC_OUT, the ground guard and the VDDA lane are inside it |
| shunt is the single ground tie of the sense side | ADR decision 4 | C203/C204/C206/R211/R216/U202.4 are excluded from the ground stitching and wired to U202 pin 4; a 2-via cluster at R204 pad 2 |
| VIN 0 vias | this brief | the long VIN link is NOT scripted - see below |
| flyback loop perimeter | ADR | 20.26 mm; buck CIN 6.95 mm; OSC_IN 5.95 mm, OSC_OUT 6.51 mm |

### How the geometry is made

Explicit straight and 45-degree segments computed from real pad positions.
Every candidate path - two-segment octilinear, then three-segment detours at
22 perpendicular offsets - is clearance-checked against every pad, every
piece of copper already drawn, the board edge and the keepouts BEFORE it is
committed, at the pairwise net-class clearance read out of the committed
`.kicad_pro` (Default 0.15, Power 0.2, HighCurrent 0.4). A path that cannot
be made to clear is **reported, not drawn**: the run prints a
"COULD NOT DRAW" list and those nets are left to the router.

Order matters and is deliberate: the crystal island and the VDDA lane inside
it have exactly one way out each, so they claim their space first; the ground
stitching runs last, because its stubs would otherwise close escape routes a
signal needed.

### The USB-C's reversible duplicate contacts

The HRO TYPE-C-31-M-12 brings D+ out on A6 **and** B6 and D- on A7 **and**
B7, and on this footprint the four sit on one row, interleaved:
B6 28.25 | A7 28.75 | A6 29.25 | B7 29.75. Both duplicate pairs have to be
bridged and each bridge has to cross the other net.

The run therefore leaves from **B6 (D+) and A7 (D-)** - adjacent, and with
D+ on the low-x side, which is the order U302 (rotated 180 degrees by
`place.py`) and the MCU both want, so the pair never swaps sides. Both
duplicates then sit east of the run, and the two bridges can use opposite
sides of the pad row: D+ A6 <-> B6 3.39 mm **in front** of the pads, where A7
has no copper, and D- B7 <-> A7 3.06 mm **behind** them, where A6 has none.
That is why the whole USB section has **zero vias**. Take the run from A7/A6
instead and both bridges have to go behind, which four interleaved contacts
cannot do in one plane - it costs two vias and about 4 mm of B.Cu slot under
the connector, right under the pair's own reference.

Both legs turn 45 degrees at the same y (`USB_TURN_Y` = 13.4, the minimum
that keeps the diagonals clear of R305's pads and SW302's), which makes the
two diagonals automatically 0.354 mm apart - the 0.2 mm / 0.15 mm pair.
`place.py` puts R305 (CC1) east of the pair and R306 (CC2) west of it, one on
each side, so neither pull-down crosses it.

### Fanout vias are zero-sum at 0.5 mm pitch

`QFN_VIA_PADS` in `copper.py` is the list of pads that get a via at the end
of a longer stub. The geometry is hard: at 0.5 mm pitch a 0.6 mm via has to
sit **1.43 mm or more** out of the pad centre to keep 0.15 mm from a
neighbouring 1.15 mm stub's end cap, two vias need 0.75 mm of copper and
0.80 mm of hole-to-hole between them - so at most every second pad of a row -
and the via then denies BOTH its neighbours any radial escape past about
1.15 mm, because a 0.25 mm trace 0.5 mm to the side of it clears by 0.50 mm
where it needs 0.575 mm.

Measured, that is a wash. Adding vias on pads 18/20/42/44 closed VIN_SENSE,
Net-(U301-PB2), LCD_BL and Net-(U301-BOOT0), and opened ENC_SW, LED_STAT,
LCD_DC and PEDAL_RING: still 7 open nets, 9 unconnected items instead of 10.
The four are kept because the count is marginally better and because the two
ADC nets among them are the ones a via harms least, but **more of them will
not help**. What is left is second-ring congestion, not fanout.

### Nothing routed by the tool is imported without a kicad-cli grade

The autorouter never runs on a repo file, and no track it produces is copied
into `graver-controller.kicad_pcb` unless `kicad-cli pcb drc` against the
**committed** `.kicad_pro` passes on the routed copy and the net meets a
stated budget. In this pass no router output was imported at all: the one
candidate, the long VIN link, cannot be via-free (see below), so it was not
taken.

### What is left for the router, and the exact command

After `copper.py` the board has 107 unconnected pad pairs over 50 nets -
the GPIO, SPI, UI and long power links ADR 0003 decision 8 hands to
KiCadRoutingTools. Run it on a **copy**, never on the repo:

    tools/pcb/routability.sh after

which copies the board and the project outside the repo, detects that
`copper.py` has already run (it looks for the `scripted-copper` group), skips
the plane pour and the diff-pair step because both are scripted, and calls

    route.py <copy> <out> --nets "*" \
        --track-width 0.2 --clearance 0.15 --via-size 0.6 --via-drill 0.3 \
        --grid-step 0.05 --escalation off --strict-sizes --write-fill \
        --keepout --keepout-layer User.2 --keep-input-copper \
        --power-nets GND +3V3 +5V VBUS /MCU/VDDA VIN /Driver/COIL_NEG \
            /Driver/CLAMP /Driver/SHUNT_HI \
        --power-nets-widths 0.4 0.5 0.5 0.5 0.4 0.8 0.8 0.8 0.8

`--keepout` reads the User.2 polygons `copper.py` draws; `--keep-input-copper`
stops the cleanup passes rewriting the locked fanout stubs, whose far ends
are dangling on purpose. It then copies the pristine `.kicad_pro` back over
whatever the router wrote and grades only with `kicad-cli pcb drc`.

### The long VIN link is deliberately not scripted

VIN has to get from the bulk capacitor (x 12) to the terminal's pin 1
(x 69.5) and the USB pair has to get from the receptacle (x 28) to the MCU
(x 47): the two runs are opposite diagonals across the same rear half and
they cross. The reserved VIN corridor at y 14..17 is exactly where the pair
crosses it. Something has to change layer, and the ADR says the pair does
not ("no vias, over unbroken bottom ground"), so the pair is scripted
via-free and the VIN link is handed to the router with
`--power-nets-widths 0.8`. Its result is imported only if it is via-free,
which on this placement it will not be - the honest answer is that the rear
edge has no second corridor, and the fix is a placement one (the DC jack and
the terminal on the same side of the USB-C, or the pedal jack's slot reused).

## Routability test

`tools/pcb/routability.sh [label]` is a **placement test, not the routing
step**. It copies the board and the project into a scratch directory outside
the repo, autoroutes the copy at the committed design rules with the router
forbidden to relax them (`--escalation off --strict-sizes` on both routing
steps), copies the pristine `.kicad_pro` back over whatever the router wrote,
and grades only with `kicad-cli pcb drc`. It prints open nets, via count and
error counts by type. It refuses to run if its work directory is inside the
git repo.

    tools/pcb/routability.sh it1          # scratch dir named after the label
    WORK=/tmp/elsewhere tools/pcb/routability.sh probe

Nothing it produces is ever committed, and the router never sees a repo file.
Use the numbers to compare placements; do not read the routed copy as a
routing proposal.

Third-pass history (open nets / vias / kicad-cli errors):

| iteration | change | open | vias | errors |
|-----------|--------|------|------|--------|
| it0 | pass-2 placement, strict | 17 | 165 | 9 |
| it1 | 2 mm annulus + 4 corridors, VIN corridor, buttons moved | 13 | 168 | 12 |
| it2 | one-row crystal island outside the annulus | 14 | 186 | 14 |
| it3 | 3 mm annulus, 10 mm corridors, decaps out to 2.0 | **7** | 202 | 6 |
| it4 | 5 mm corridors | 14 | 205 | 12 |
| it5 | island biased off the VBAT decap | 10 | 180 | 15 |
| it6 | it3 geometry, criteria-passing crystal | 14 | 192 | 6 |
| it7 | fab-text/overhang fix, buttons stacked | 11 | 178 | 25 |
| before | it7 + the copper.py place.py changes, no copper | 9 | 189 | 24 |
| after | + all of copper.py, no fanout vias | 7 | 135 | 2 |
| after2 | + 4 fanout vias on pads 18/20/42/44 | **7** | 140 | **2** |

The last two rows are the ones that matter: the scripted copper takes a
strict autoroute from 9 open nets / 189 vias / 24 errors to 7 / 140 / 2. The
17 `track_width` errors are gone because the USB pair is now scripted at
exactly 0.2 mm instead of the router's 0.1996 mm, and five of the seven
`hole_clearance` errors are gone because of the M3 keepouts. The **two that
remain are a router artefact of a third kind**: the router's own
`--write-fill` refill of the scripted GND pour does not apply the 0.25 mm
hole clearance to J301's two NPTH pegs. `copper.py`'s own fill does, and the
committed board reports 0 errors. The two `hole_to_hole` warnings are two
+3V3 vias the router placed 0.4517 mm apart.

it3 routed best but missed the crystal's 5 mm limit by 0.16 mm, so the shipped
placement is it7: every ADR criterion passes and 11 nets are left open.

## Renders

`tools/pcb/render.sh` writes into `output/pcb/`:

| file | layers | for |
|------|--------|-----|
| `placement.png` | F.Fab + F.Courtyard + Edge.Cuts | judging placement |
| `copper.png` | F.Cu + Edge.Cuts | pads only |
| `silk.png` | F.Silkscreen + F.Cu + Edge.Cuts | what the top side will look like |
| `critical.png` | F.Fab + User.1 + Edge.Cuts | the loop/speed-critical nets as straight lines |
| `top.png` | F.Cu + User.2 + Edge.Cuts | the scripted top copper and the keepouts |
| `bottom.png` | B.Cu + User.2 + Edge.Cuts | the pour, its cut-outs and the M3 keepouts |
| `both.png` | B.Cu under F.Cu over F.Fab | both layers against the bodies |
| `zoom-*.png` | crops of `placement.png` | one block at a time |
| `cu-*.png` | crops of `top.png` | the scripted copper one block at a time: qfn, xtal, usb, driver, buck |

`critical.png` is rendered from `output/pcb/critical.kicad_pcb`, a
**review-only** copy that `place.py` writes with the nets in `CRITICAL_NETS`
drawn as straight User.1 segments (flyback loop, buck SW and BST, crystal, USB
pair, I_SENSE, shunt, gate). The committed `.kicad_pcb` carries none of them.

## What is still rough

Honest list, worst first. Items -3..-1 are copper; the rest are placement
and the numbers in them are from the second pass.

-3. **The crystal island denies the QFN's front row.** Y301/C310/C311 sit
    directly in front of pads 1-12 and leave a 0.81 mm channel between the
    pin row and the load-cap pads. That channel takes exactly one 0.20 mm
    trace (0.25 + 0.20 + 0.25 = 0.70 of the 0.81) and there is no second
    lane: the cap-to-cap gap is 1.98 mm and the crystal's own pad gap 0.80 mm,
    both only reachable from the middle of the row. VDDA gets the channel,
    OSC_IN crosses it at x = 47.15 and OSC_OUT at x 47.75..48.75. That leaves
    **pad 7 (NRST), pad 11 (PEDAL_TIP) and pad 12 (PEDAL_RING) with no escape
    at all** - they are trapped under other nets' copper, not merely
    congested, and no router can fix it. The fix is a placement one: put the
    island over pads 1-5 at the front-west corner (which needs C301 moved and
    the 2 mm VDD rule re-checked), or rotate the crystal 90 degrees so the
    island is 2.9 mm wide instead of 3.6 mm and re-run the criteria table.
    Everything else about the island is already at its limit - pulling the
    caps 0.45 mm further out to widen the channel pushes the worst OSC leg
    from 4.99 mm to 5.33 mm and breaks the ADR's 5 mm rule.

-2. **R209 and R213 are not Kelvin taps.** `SATELLITES` asks for them 2.4 mm
    off the shunt's sense pad; the resolver put them 12.5 mm away on the far
    side of the op-amp, so the two sense traces would have to cross the gate
    net. `copper.py` refuses to draw them and says so. The op-amp itself is
    within the ADR's 10 mm of the shunt; the taps are not, and that is the
    part of ADR 0003 decision 4 that is currently not honoured.

-1. **Twelve local traces around U202, U101 and the crystal ground guard
    could not be drawn** and are printed in the run's "COULD NOT DRAW" list -
    the op-amp's feedback and OC_REF network, the buck's FB divider and
    EN/UVLO divider, the VBUS link to the receptacle, five of the six
    sense-side ground ties and the crystal guard's west leg. None is
    speed-critical, all are short, and the router reaches all of them; but
    the sense-side ground ties failing means the single-point ground at the
    shunt is currently only U202 pin 4 -> R204 pad 2 plus that pad's via
    cluster, with C203/C204/C206/R211/R216 still relying on the router to
    bring them there rather than to the nearest via. Check that in pcbnew
    before ordering.

0. **A strict autoroute still leaves 11 nets open** (see the table above):
   /MCU/OSC_OUT, Net-(U301-PB2), /MCU/VDDA, VIN_SENSE, OC_TRIP, LCD_BL, SWDIO,
   NTC, LCD_RST, LCD_MOSI, LCD_SCK. All of them are QFN escapes. Two things
   cap what placement can do here: at 0.2 mm track / 0.15 mm clearance no
   track fits between two adjacent QFN pads (0.25 mm gap needs 0.5 mm), so
   every one of the 33 signals must escape radially; and a 0.6 mm via needs
   0.75 mm of clear radius, which does not exist anywhere in the first ring,
   so nothing can drop to B.Cu near the part. The remaining opens are
   congestion in the corridors, not parts in the way - the router reports
   them blocked by *previously routed nets*, not by footprints. Realistic
   fixes are a QFN fanout pass at a locally relaxed clearance (ADR 0003
   decision 5 already anticipates this) or routing these by hand; both are
   routing decisions, not placement.

1. **VDDA network and NRST cap are 4.9-6.8 mm from their pins**, not the 3 mm
   they are graded against. Those four rows print `OVER (advisory)` and do not
   fail the run, with the reason printed under the table: pads 1 and 5-12 sit
   on one 6 mm stretch of QFN edge and eleven parts want it (VBAT decoupling,
   crystal + two load caps, three-part VDDA network, NRST cap, two pedal
   filter caps). Four fit in the first ring. The crystal's hard 5 mm limit and
   the four VDD caps' 2 mm limit are satisfied first, so the filters give.
   Both are filters - VDDA behind a ferrite, NRST a slow node with a button on
   it - so this is the right thing to trade.
2. **Clamp loop is 25.9 mm of perimeter, flyback loop 46.5 mm**, against a
   16 mm target; both advisory with the arithmetic printed. The floor for the
   clamp loop is about 24 mm: J201's own pins are 5.08 mm apart, its body is
   12.6 mm deep so each leg touching those pads drops >= 3.4 mm before it
   reaches anything, and the SMA/SMB/0805 chain adds two ~5 mm hops. The
   parts do sit in a 10 x 12 mm block directly under the terminal, which is
   what ADR 0003's "closed within about 15 mm" is really about (loop area over
   solid bottom ground). The 6-vertex "flyback loop" figure additionally
   walks out to the FET and back to the terminal, so it is a comparison
   number between runs, not a target.
3. **About a fifth of the board is empty**: x 45..78 / y 45..70 and
   x 78..100 / y 30..50. The MCU search puts the cluster at (38, 30) because
   USB, the SWD header, the LCD connector and the driver all pull it up and
   left, and the encoder (weight 1) cannot pull it back. On a 2-layer board
   that space is routing room rather than waste, but if Jan wants it used the
   lever is `MCU_LINKS` weights or moving the encoder left.
4. **ENC_SW is 66 mm, ENC_A/B 52-54 mm, DECAY_SLOW ~50 mm.** Inherent: the
   encoder is front-right by ADR decision and the MCU is centre-left, and
   Q203 sits with the bypass circuitry it switches. None is speed-critical.
5. **U202.7 -> PB12 (OC_TRIP) is ~20 mm**, not the "short track" the ADR asks
   for. The op-amp has to be within 10 mm of the shunt (it is, 1.5 mm) and the
   shunt is ~20 mm from the MCU, so the two rules fight. Keep it away from the
   coil node when routing.
6. **C111/C112 (buck output caps) drift to y ~64**, below J401, about 10 mm
   from D105. They are the last of the "oring" group to be placed and the
   front-left is full by then.
7. **Silkscreen is untouched** - all 272 DRC warnings are references
   overlapping pads and each other.
8. **No keepouts drawn yet.** ADR 0003 wants a ground guard and no signal
   under the crystal; `place.py` only keeps other *parts* off the island
   (`XTAL_CLEAR`). Draw a User.2 polygon over Y301/C310/C311 before any
   routing and give the router `--keepout`.
9. The `.kicad_pcb` is not byte-stable between runs - KiCad regenerates item
   UUIDs and writes footprints in a UUID-dependent order. Part positions and
   rotations are identical run to run (verified); only the serialisation
   moves.

## TODO for Jan

1. **Mounting holes.** ADR 0003 wants them as schematic symbols - they already
   are (`MH401`-`MH404` on the IO sheet, `Mechanical:MountingHole`), so the
   script places them from the netlist like any other part and adds nothing of
   its own. They are currently `in_bom yes`; if you want them off the BOM and
   the CPL, set "Exclude from bill of materials" on the four symbols in
   eeschema. `place.py` copies whatever the schematic says.
2. **EP thermal vias** (0.3 mm drill / 0.6 mm pad, 4 of them) get added by
   the copper script. U101 now uses the plain
   `Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm` footprint, so the
   board no longer carries the library's 0.2 mm thermal vias and DRC reports
   zero errors.

3. **THT footprints pending caliper measurements** on the loose parts
   (ADR 0003 "Known unknowns"). All four are placed with the stock KiCad
   footprints, so the overhangs in the table above are the library's idea of
   the part, not a measured one:
   - `J201` handpiece terminal: drill needs to go from KiCad's 1.2 mm to
     1.6 mm.
   - `SW401` encoder: lug spacing unverified (currently the Alps EC11E
     12.0 mm variant).
   - `J402` Neutrik: normalling (SN/RN/TN) contacts unverified, and the
     footprint only draws 3 mm of ferrule. The rear wall is 3 mm at the jack,
     so there is no thread left for the nut if 3 mm is all there is - measure
     before ordering.
   - `J101` DC jack: body and slot dimensions unverified.
4. **Cover-plate reference export.** The positions this script produces are
   the input to the DXF/STEP reference for FreeCAD (ADR 0003 mechanical step
   2). Not written yet.
5. **Power block is provisional** until the 24 V punch test lands
   (ADR 0003 open question). It occupies x 4..32, y 14..62; if a boost stage
   comes back, that is the block to grow.
