# tools/pcb - board generation, placement, the scripted copper and the silk

Scripted placement, scripted critical copper and a scripted silkscreen for
`graver-controller.kicad_pcb`, per ADR 0003 decision 8. Placement is data in
`place.py`, which regenerates the whole board from the schematic every run;
the critical copper is data in `copper.py`, which draws it on top of that and
locks it; the silkscreen is `silk.py`, which searches rather than tabulates.
None of them routes the rest.

## Where the board stands (seventh pass)

Commit-independent, from `kicad-cli pcb drc --schematic-parity --severity-all`
with `graver-controller.kicad_dru` beside the board:

| | after `copper.py` + `silk.py` | after `autoroute.py` |
|---|---|---|
| errors (incl. `track_width`) | **0** | **0** |
| schematic parity | **0** | **0** |
| unconnected pad pairs | **71** | **10** |
| of those, on GND | **0** | **2** |
| vias on the board | 99 scripted | 219 |

**The committed `graver-controller.kicad_pcb` is still the sixth pass's routed
board (3 open: VDDA 2 mm, PB2 6 mm, +5V 40 mm; 0 on GND, 233 vias).** The
seventh pass's scripted copper (VDDA and PB2 closed by script, escapes for
C202 and C309) is in `copper.py` but its route run came out worse (10 open,
2 on GND), so that board was not committed; the next `--route` run starts
from the new scripted copper. The table's right column describes that
uncommitted run. Read "Where it came out" before anything else: three of
the ten are an `autoroute.py` mop-up bug with a named one-file fix, two are
the GND pour-island mechanism of "What is still rough" item -7, and one - +5V
- has been open in every pass and is a placement question.

What the seventh pass bought is on the other side of the router and does not
move between runs: `/MCU/VDDA` pin 9 and `Net-(U301-PB2)` are **closed by the
script**, at 2.95 mm / 2 vias and 6.71 mm / 1 new via, every segment at its
own `.kicad_dru` floor; no Power-class net enters a 0.25 mm pad anywhere; and
every scripted budget below still passes.

## Run it

    cd Hardware/graver-controller
    python3 tools/pcb/place.py --export-manual   # keep your hand routes FIRST
    python3 tools/pcb/place.py          # rebuild + place + check
    python3 tools/pcb/copper.py         # zones, keepouts, critical copper
    python3 tools/pcb/silk.py           # references, connector labels, title
    python3 tools/pcb/autoroute.py      # route the rest, grade it, import it
    python3 tools/pcb/manual.py --restore   # hand routes back on
    tools/pcb/render.sh                 # PNGs into output/pcb/

or in one go:

    python3 tools/pcb/place.py --export-manual
    python3 tools/pcb/place.py --copper --silk --route

The second line runs the restore itself as its last step. `--export-manual`
has to come first and separately, because the rebuild is what would destroy
the copper it collects - see "Hand routes survive a regeneration" below.

`place.py`, `copper.py` and `silk.py` need plain `python3` with the system
KiCad 10 `pcbnew` bindings - no venv, no extra packages. `autoroute.py` also
needs the KiCadRoutingTools checkout and its venv (see "Routing the rest").
`place.py` exits non-zero if any placement check or ADR distance criterion
fails, and prints a table of every criterion with its measured value.

`--no-netlist` skips the `kicad-cli sch export netlist` step and reuses
`output/pcb/netlist.xml`. Use it while iterating on placement numbers.

Verify independently with:

    kicad-cli pcb drc --schematic-parity --severity-all graver-controller.kicad_pcb

run from the board's own directory, so that `graver-controller.kicad_pro`
**and `graver-controller.kicad_dru`** sit beside it - without the rules file
the per-class track-width minimums are not checked at all, which is how the
fifth pass shipped 237 undersized segments and reported none.

Expected after `place.py` alone: 0 schematic parity issues, ~250 unconnected
items, and silkscreen warnings. After `copper.py`: 0 errors, 0 parity, 71
unconnected items **and 0 of them on GND** - see "GND is closed by the
script" below. After `silk.py`: no silkscreen warnings at all. After
`autoroute.py`: 0 errors, 0 parity, and the remainder in "Where it came out"
below - the router is not deterministic, so that number moves between runs.
See "Known DRC output" below.

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
  edge, outward, rotation)`. They are placed as one RIGID group, and the
  rotation is DICTATED rather than searched: which of the crystal's four pads
  faces the MCU decides whether the two oscillator legs can be drawn at all,
  which a distance search cannot see. See "The crystal island lives in the
  corner" below.
- `KELVIN_TAPS` and `OPAMP_WEST` - two more rigid groups, R209/R213 off the
  shunt's sense pad and R210/C204/R211 off the op-amp's pin 1. Both were
  satellites in the second pass and both got thrown 12-16 mm away by the row
  search; see "The analog corner is placed, not resolved" below.
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
- `graver-controller.kicad_pcb` is derived: everything on it except a hand
  route belongs to a script, so change the script and re-run rather than
  editing the board. Hand routes are the one exception and they are safe now -
  `place.py --export-manual` collects them and the pipeline puts them back,
  see "Hand routes survive a regeneration". Run the export **before** the
  pipeline, because the rebuild is what would destroy them.

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

`kicad-cli pcb drc --schematic-parity --severity-all` on the finished board -
placement, scripted copper, scripted silk and the router's copper:

The grade is run **with `graver-controller.kicad_dru` beside the board**, which
is what makes the per-class track-width minimums part of it. Before the sixth
pass it was not, and the answer was wrong by 237 violations - see
"Why `--power-nets-widths` was not enough".

| type | after copper + silk | after autoroute.py | why |
|------|--------------------|--------------------|-----|
| schematic parity | 0 | 0 | clean |
| errors | 0 | 0 | clean, **including `track_width` against the .kicad_dru** (237 before this pass) |
| unconnected_items | 71 | 10 | VBUS 3, GND 2, Net-(U301-BOOT0) 2, +5V 1, LED_STAT 1, LCD_SCK 1, named pad by pad in "Where it came out". **0 of the 71 are on GND; 2 of the 10 are**, and that is the seventh pass's worst number |
| silk_overlap | 0 | 0 | was 92 before `silk.py` |
| silk_over_copper | 0 | 0 | was 92 |
| silk_edge_clearance | 0 | 0 | was 17 |
| lib_footprint_mismatch | 4 | 4 | J101, J201, J301, J402 - `silk.py` trims their library silkscreen back to the board outline, see "Silkscreen" below |
| track_dangling | 14 | 5 | QFN escape stubs whose net the router never reached |
| via_dangling | 8 | 7 | escape and stitching vias the router never reached, now including the +5V and NRST escape vias of step 7c. The 17 edge-stitching vias are **not** among them - the F.Cu rib between them is what keeps them off this list |

223 warnings before the silk pass, 25 after, 16 once the router's copper is
in: the remaining deliberate dangling ends plus the 4 trimmed connectors.
The router is not deterministic, so the two right-hand columns move between
runs - the numbers here are from the run `output/pcb/route-summary.txt`
records. **The sixth pass's board was 3 open with 0 on GND; this one is 10
with 2 on GND, and the left-hand column is the one that got better.** See
"Where it came out" for what each of the seven extra pairs is and which of
them is a copper decision rather than router noise.

**`kicad-cli` caps its report at 199 violations per type** and does not say so.
That is not a detail here: the fifth pass's board was reported as having "199
`track_width` errors" and had 237. `autoroute.py` prints a NOTE whenever a
type lands on 199, because such a count is a floor and not a total.

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
| 2 | U301 QFN fanout | 0.20 mm radial stubs on the pads that do not need more; a 12-pad **escape fan** on the east and west rows (45 degrees at 1.35 mm, own lane at 0.70/0.90 mm pitch, reach 2.6-2.9 mm) with the 4 vias 0.6/0.3 out at 2.90 mm on pads 18/20/42/44; a 0.97 mm same-net jumper on pad 1 and a 6.56 mm channel lane + via on pad 2, the two the island shadows |
| 2 | U301 GND pins 8/23/35/47 | 0.20 mm, 0.64 mm into the EP copper |
| 2 | U301 EP | 4 vias 0.6/0.3 inside the pad |
| 3 | decoupling | 13 pin-to-cap traces on F.Cu |
| 3b | GND stitching | 58 of 58 top-side ground pads get a 0.25-0.40 mm stub and a 0.6/0.3 via of their own, placed by search; 17 edge vias at 10 mm pitch with 15 F.Cu ribs; 20 spine hops. **GND is closed here and is not in the router's scope at all** |
| 3 | U101 PowerPAD | 4 thermal vias 0.6/0.3 |
| 4 | crystal | OSC_IN 6.47 mm, OSC_OUT 7.24 mm (both including the load-cap tap), F.Cu only, 0 vias; F.Cu ground guard bracket, 3 of 3 legs + 2 stitching vias |
| 5 | VDDA | FB301 -> C306/C307 at 0.40 mm; pin 9 -> C306 is 2.95 mm over **two layers with 2 vias**, every segment at the Power floor (0.30 mm) - the pad has no F.Cu lane at any width, see "A 0.25 mm pad is a 0.25 mm track" |
| 6 | USB | D+ 37.88 mm, D- 37.88 mm, skew 0.00 mm, **0 vias on either net**; 17 User.2 bands 0.15 mm off the centre line so the router cannot cross under the pair on B.Cu |
| 6b | same-net pad bridges | U302's two duplicate I/O pin pairs (1-6 D-, 3-4 D+, 1.35 mm each) and SW401's two MP lugs (11.20 mm) - three pad pairs no router can close |
| 7 | power | VIN chain 0.8 mm, flyback loop 1.0 mm, gate 0.4 mm, shunt 1.0 mm, Kelvin taps 0.5 mm off the shunt pad's own copper edge, buck, +5 V/+3V3 0.5 mm; sense-side ground tree 0.20/0.25 mm; CLAMP's tap to the bypass FET 12.66 mm over two layers |
| 7b | power rails as trees | +3V3 as a Kruskal tree with taps into the trunk, 0.5/0.35/0.30 mm |
| 6c | five explicit signal paths | GATE_IN pad 29 -> the driver 16.67 mm, VCAP1 pad 22 -> C308 10.79 mm, VIN_SENSE's divider + filter + ADC pin 20.20 mm over four legs, I_SENSE's filter + ADC pin 7.74 mm over two - all F.Cu, 0 vias, waypoints dictated; plus PB2 pad 20 -> R303 6.71 mm over **two layers with 1 new via**, the one signal path with no F.Cu lane |
| 7c | escapes out of boxed-in pads | NRST off C309 pad 1, 0.74 mm at 0.25 mm + a via; +5V off C202 pad 1, 2.50 mm at 0.50 mm + a via. See "Two escapes out of boxed-in pads" |
| 8 | ADC filters | the RC parts at the MCU pins, 0.25 mm, only where the part is within 6.5 mm |

### Budgets, and how they came out

| budget | source | measured |
|--------|--------|----------|
| USB pair <= 40 mm, 0 vias, <= 1 mm skew | ADR 0003 component breakdown 3 | 37.88 / 37.88 mm, 0 vias, 0.00 mm skew - PASS with 2.1 mm of margin. The U302 -> MCU legs are octilinear now instead of L-shaped, which is worth 4.7 mm each and is what absorbed the MCU moving 4 mm back from the receptacle to make room for the Kelvin taps |
| USB coupled 0.2 mm / 0.15 mm | ADR + Jan 2026-09-18 | 0.15 mm gap on the long connector segment; 0.30 mm on the two U302 -> MCU lanes, which U302's own 1.9 mm pin pitch forces |
| flyback loop closed within ~15 mm | ADR decision 4 | 21.38 mm of real copper over its four legs (20.26 before the octilinear preference below, which is worth 1.12 mm over the four and is the right trade), parts inside a 10 x 12 mm block under the terminal |
| buck CIN within 3 mm of the VIN pin | ADR component breakdown 2 | 2.88 / 2.74 mm pad to pad, 6.95 mm of copper |
| crystal keepout clean | ADR decision 8 | clean: only OSC_IN, OSC_OUT and the ground guard are inside it (VDDA no longer needs to be) |
| GND closed by the script, 0 pad pairs for the router | this brief | **0 - PASS.** 58 of 58 top-side ground pads have a stub and a via of their own, 17 edge vias with 15 ribs tie the pour along the two long edges, and 20 spine hops take GND from 63 pieces of F.Cu copper to 43. `kicad-cli` reports 0 GND pad pairs after `copper.py` and GND is therefore not in the net list `autoroute.py` hands the router. It was 2 pairs and 9 router vias before |
| GND stitching: 0.25-0.40 mm stub, <= 1.5 mm, 0.15 mm clearance | this brief | every one of the 58 came out inside 1.5 mm and 0.30 mm or wider; the search tries the widest that clears at each of 16 directions |
| shunt is the single ground tie of the sense side | ADR decision 4 | CHECKED, row per pad, and the run exits non-zero on a FAIL: C204.2, R211.2, R216.2, C206.2 and U202.4 each reach R204 pad 2 over scripted F.Cu with no via of their own, and R204 pad 2 carries the 2-via cluster that is the sense side's only path into the pour. C203.2 and C205.2 are deliberately NOT in that set - see below |
| VIN 0 vias | this brief | the long VIN link is NOT scripted - see below |
| flyback loop perimeter | ADR | 21.38 mm; buck CIN 6.95 mm; OSC_IN 6.47 mm, OSC_OUT 7.24 mm |
| Kelvin traces from the shunt PADS to the op-amp | ADR component breakdown 4 | 1.15 mm and 1.23 mm of bare laminate between R204's sense pad and each tap's own pad, 0.50 mm traces drawn from the pad EDGE, not from the 1.0 mm power trace. 0.50 and not 0.20 since the sixth pass: SHUNT_HI is a HighCurrent net and the .kicad_dru holds every track on it to 0.50 mm. A Kelvin tap carries no current, so the width is free and the EDGE is the whole point |
| +3V3 <= 120 mm total, <= 8 vias | this brief | **0 vias - PASS. 120 mm is not reachable and the run says so**: the straight-line minimum spanning tree over the net's 29 pads is 182.95 mm, which is the floor for any routing of it. The scripted tree is 169.63 mm of copper over 14 hops and leaves 8 islands / 7 pad pairs (unchanged by the 0.30 mm floor on its narrow rung, which is how we know the 0.25 mm rung never closed anything); read it against 182.95, not against 120. It was 240.22 mm over 18 hops and 3 pairs before the explicit signal paths went in - they take four lanes the tree was using and it gives back four joins for 70 mm of copper, see "Five explicit signal paths". The router closes all seven |
| +5V trunk and its escape | this brief | the block U101 -> L101 -> ORing diodes -> U102 is scripted at 0.5 mm with 0 vias; the one pad pair left open is U201's supply, C201.1 <-> D105.1 at **39.93 mm** across the whole board (x 51, y 23.5 to x 25, y 54). The trunk itself is **not** scripted and the corridor search says why - see "The +5V trunk is an escape, not a trunk". What is scripted is a 2.50 mm escape at 0.50 mm out of C202 with a **0.6/0.3 via at its end**, because the reason the router produced no copper at all for this net was never the 40 mm, it was that the endpoint was boxed in by locked copper |
| VDDA pin 9 closed | this brief | **2.95 mm over two layers, 2 vias, every segment at the 0.30 mm Power floor** against a 2.50 mm straight line. There is no F.Cu lane at any width and the two single-layer alternatives were measured and rejected - see "A 0.25 mm pad is a 0.25 mm track". It is not free: the two vias boxed NRST's cluster in, which is why step 7c now scripts NRST's escape too |
| PB2 pad 20 closed | this brief | **6.71 mm over two layers, 1 new via** (the fanned escape already carried one) against a 6.23 mm straight line, 5.71 mm of it on B.Cu. The F.Cu route is short by 0.075 mm in the one slot that could take it - see "Five explicit signal paths" |
| GATE_IN short and explicit | this brief | 16.67 mm of 0.20 mm F.Cu, 0 vias, against a 15.26 mm straight line - pad 29 -> R202 pad 1, and R202 -> U201 pin 3 is the 3.69 mm scripted leg that was already there. The router had produced no copper for it at all |
| VCAP1 pad 22 -> C308 | ADR / STM32F4 | 10.79 mm of 0.20 mm F.Cu, 0 vias, against a 7.79 mm straight line. Long for a regulator cap and the lever is placement, not copper: C308 is a second-ring part and the only way to it is the 0.55 mm slot between C302 pad 2 and C104 pad 1 |
| I_SENSE closed | this brief | 7.74 mm of 0.25 mm F.Cu over two legs, 0 vias: pad 16's escape -> R212 pad 2 (5.80 mm, through the 0.80 mm slot between FB301 pad 1 and R217 pad 2) and R212 -> C205 (1.94 mm). Drawable all along; what changed is that GND no longer contends for the same corner, see "GND is closed by the script" |
| VIN_SENSE closed | this brief | 20.20 mm of 0.25 mm F.Cu over four legs, 0 vias: pad 18's escape -> a lane at x = 55.25 -> C104 (5.91 mm) and -> R103 (2.14 mm), then R103 -> R102 (9.24 mm). Not a board crossing - all three parts are in the x 54..56 column and `RC_MAX` (6.5 mm) had put the three hops 0.24, 0.36 and 1.43 mm out of the filter step's reach |
| CLAMP tap to the bypass FET | this brief | 12.66 mm, 8.91 mm of it on F.Cu, 2 vias - see "The one path that changes layer". Was ~50 mm of the router's copper down the right-hand edge and back |
| flyback loop unchanged by the CLAMP tap | ADR decision 4 | 21.38 mm, same four legs; the B.Cu slot the tap costs is at y 21.6, SOUTH of the loop (y 14..20), not under it |

### The .kicad_dru width floors, and who reads them

`graver-controller.kicad_dru` (sixth pass) turns ADR 0003 decision 5's net
class widths into rules, because in KiCad a class's `track_width` is the
DEFAULT for new copper and not a limit - nothing in a stock setup complains
about a 0.2 mm track on a 0.8 mm net:

    (rule "HighCurrent tracks" (condition "A.NetClass == 'HighCurrent'")
      (constraint track_width (min 0.5mm)))
    (rule "Power tracks"      (condition "A.NetClass == 'Power'")
      (constraint track_width (min 0.3mm)))

`copper.py` **reads that file** (`class_floors` / `net_floors`) instead of
repeating its numbers, exposes the two floors as `W_RAIL_MIN` (0.30) and
`W_HC_MIN` (0.50), and `width_floor_table` checks every scripted segment
against the floor for its net and exits non-zero on a FAIL. `autoroute.py`
imports the same two functions, so the router's passes, the import gate and
the width table in the final report all use one set of numbers.

What it changed, and none of it cost a pad pair or a millimetre of anything
that is measured:

| what | was | now | why it is safe |
|------|-----|-----|----------------|
| the Kelvin taps off R204's sense pad | 0.20 | 0.50 | they are on `/Driver/SHUNT_HI`, a HighCurrent net. A Kelvin tap carries **no current at all**, so its width is free; what matters is that it leaves the shunt pad's own copper EDGE, and it still does |
| `EN/UVLO top to VIN`, `buck CIN 3` | 0.40 | 0.50 | both are VIN. The first still cannot be drawn on this pose either way (R106's own pad is on the only lane); the second draws |
| the three QFN VDD pads' first-ring traces | 0.25 | 0.30 | +3V3 is Power class. 0.30 mm leaves 0.025 mm to the GND pad next door at 0.5 mm pitch - drawable, and the run says so; a pad whose trace does not clear keeps its radial stub |
| the three rail bypasses at U201 / U202 | 0.25 | 0.30 | +5V and +3V3, same reason |
| `RAILS`' narrow rung | 0.25 | 0.30 | the rail trees came out with the SAME 14 hops, 169.63 mm and 8 islands, so the 0.25 mm rung was never the one that closed anything |
| pad 1's same-net jumper | 0.20 | 0.30 | tried at the floor first, falls back to 0.20 with a note if it cannot clear. It clears |

### A 0.25 mm pad is a 0.25 mm track, and that is where the floor runs out

One net cannot satisfy a flat floor by any amount of routing, and it is worth
being exact about why. `/MCU/VDDA` reaches the MCU at pad 9, which is
**0.25 mm wide**; so are the +3V3 pads 1, 24, 36 and 48. KiCadRoutingTools'
via-to-pad bridge is built at `min(track width, pad.size_x, pad.size_y)`
(`pcb_modification.py`), which is the right rule - copper wider than the pad
it enters is pointless - and it means that whatever `--track-width` the router
is given, copper it lays INTO one of those pads is 0.25 mm. The .kicad_dru's
own comment says "necking down at small pads is allowed to half the class
width" and the rule does not implement it, so a 0.25 mm entry into a 0.25 mm
pad is a `track_width` error with nothing wrong with it.

The four +3V3 pads are not exposed to this: `copper.py` already owns all four
(three first-ring traces and pad 1's jumper), so the router never enters them.
Pad 9 was the one exception - `step5_vdda`'s 2.5 mm run to C306 cannot be
drawn on this pose and the pad was left bare, so the router had to enter the
pad itself. The sixth pass gave it `power_escape` (0.85 mm of 0.30 mm copper
with no via, because the first ring has no 0.75 mm clear radius) and left the
2 mm gap to C306 for the router, which closed it in one run out of six.

**The seventh pass draws the whole hop instead, over two layers.** Pad 9 is
not "blocked on the lane C309 owns", it is boxed in on all four sides, and
that is worth writing down because it is what decides the answer:

| side | what is there | the number |
|------|---------------|-----------|
| south | C309's pad (NRST's cap), box top at y = 48.775 | a southward stub stops at y = 48.425 |
| west / east, first ring | pad 8 (GND) and pad 10 (unconnected), 0.5 mm away | the corridor out of the pad is 0.75 mm wide |
| east | PEDAL_TIP's radial stub down x = 48.250 to y = 48.587, PEDAL_RING's down x = 48.750 to y = 48.438 | the slot between C309's pad and the first of them is **0.525 mm**, and a 0.30 mm track needs 0.35 to the pad plus 0.45 to the stub = 0.80 mm. A 0.20 mm one needs 0.70 |
| south-east, round the stubs | crossing x = 48.250 needs y >= 49.037 | every route from pad 9 to there runs into C309's pad |

Both single-layer fixes were measured and both cost more than they buy.
Shortening the two pedal stubs to open a 0.30 mm lane at y = 48.425 leaves
them 0.10 mm of copper past their own pad edge, which is no escape at all for
two real signals. Moving C309 south far enough is **0.80 mm, not "a few
tenths"**: it puts C309 pad 2 0.19 mm from C405's pad and it takes NRST's own
first-ring trace into the crystal ground guard at x = 46.200, which is 0.425 mm
of air where 0.05 is left.

So `VDDA_LAYERED` changes layer: 0.79 mm of F.Cu out of the pad, 1.41 mm of
B.Cu, 0.75 mm of F.Cu into C306, **2.95 mm and 2 vias, every segment at the
0.30 mm floor**. The vias sit in the one window that exists - (47.250, 48.225)
clears pads 8 and 10 by 0.513 mm where 0.500 is needed, C309's pad by 0.550
and NRST's own diagonal by 0.646 where 0.625 is needed, and that window is
**0.048 mm tall in y**, which is why `power_escape`'s 0.85 mm ladder rung
missed it by 0.06 mm and reported "no room for a via".

The rule exception is still the other way to do it and still not this pass's
to make: a `(condition "A.NetClass == 'Power' && A.Length < 1mm")` in the
.kicad_dru would let a 0.20 mm neck enter the pad, and then the 2 mm gap is a
0.20 mm F.Cu hop with no vias at all.

### How the geometry is made

Explicit straight and 45-degree segments computed from real pad positions.
Every candidate is now sorted **octilinear first**: `oct_route`'s 'hd' and
'vd' modes only come out at 45 degrees when the axis they run along is the
longer one, so they used to emit slants like (49.0, 34.2) -> (42.0, 12.4).
Those candidates are still kept as a last resort - on a crowded board a slant
that clears beats nothing - but they sort behind every octilinear one. That
took the run's "non-octilinear segment" notes from 35 to 0 and cost 1.12 mm
on the flyback loop and 0.14 mm on OSC_IN.
Every candidate path - two-segment octilinear, then three-segment detours at
22 perpendicular offsets - is clearance-checked against every pad, every
piece of copper already drawn, the board edge and the keepouts BEFORE it is
committed, at the pairwise net-class clearance read out of the committed
`.kicad_pro` (Default 0.15, Power 0.2, HighCurrent 0.4). A path that cannot
be made to clear is **reported, not drawn**: the run prints a
"COULD NOT DRAW" list and those nets are left to the router.

Order matters and is deliberate: the crystal island and the VDDA lane inside
it have exactly one way out each, so they claim their space first; the four
explicit signal paths (step 6c) go before the power block, the filters and the
rails, because each of their lanes is one a later step would otherwise take;
the ground stitching runs **last**, because its stubs would otherwise close
escape routes a signal needed. The brief for the fifth pass asked for the
stitching before the rails and it is still last, deliberately: it is 58 stubs,
17 edge vias and 20 spine hops now, which is the largest single step in the
file, and every one of those pieces of copper would be competing with a rail
trunk or a filter link for the same 1 mm gap. Running it last costs GND
nothing at all - it is the one net that always has the pour underneath - and
the measurement is that GND still comes out at 0 pad pairs from there.

### The crystal island lives in the corner, and two pads pay for it

Third pass. The island used to sit in front of pads 5-12 and leave a 0.51 mm
channel - one 0.20 mm trace, which VDDA needed - so pad 7 (NRST), pad 11
(PEDAL_TIP) and pad 12 (PEDAL_RING) had no escape at all. It now sits in the
corner at the LOW pin numbers, where the pads it covers are pad 1 (VBAT), pad
2 (PC13, the status LED), pads 3 and 4 (unconnected on this design) and the two
OSC pins that want to be there anyway. Pads 7-12 get plain radial stubs and
their first-ring parts: NRST's cap is 2.05 mm from pin 7 and VDDA's 1 uF
2.50 mm from pin 9, both of which used to be 6-8 mm out and advisory.

Three things had to be true at once, and none of them is a distance:

- **The crystal's rotation, not its distance.** At 270 degrees the 3225 puts
  XIN on its near-west pad and XOUT on its far-east one, which is the only one
  of the four rotations where OSC_IN is both nearest the MCU and west of
  OSC_OUT - the order pads 5 and 6 come in. At 0 degrees (second pass) XIN is
  the far south-west pad with a GND pad directly north of it, and the only way
  in is the crystal's own 0.8 mm centre slot, which OSC_OUT's load cap needs
  too. The old flip search scored distance and could not see this, so
  `XTAL_ISLAND` now carries the rotation and the search is gone.
- **The load caps go outside the crystal, not between it and the MCU.** One
  west of it, one behind it, both standing on end, so the face the QFN sees is
  the crystal's own 2.9 mm of pads and nothing wider. Each cap is 1.7 mm from
  the crystal pin it damps.
- **The corner has to be free when the island is placed.** The escape annulus
  reserved a 3 mm band on three sides INCLUDING the corners of the crystal's
  side, and a cap parked at pad 1 was placed before the island and took the
  rest. So the two bands perpendicular to the crystal's side are clipped back
  to the courtyard there, and C301 is pushed 3.25 mm along the pin row to sit
  against C304, pad 48's own 100 nF. That costs C301's 2 mm criterion (2.93 mm,
  advisory): pad 1 is VBAT, tied to VDD on a part with no battery, and it also
  gets a 0.97 mm jumper to pad 48 so it is decoupled by C304 whatever happens.

What is left is a 1.03 mm channel between the pin-row copper and the island's
keepout - two 0.20 mm lanes at 0.21 mm, not one. The outer lane carries OSC_IN
across to XIN; the inner one carries LED_STAT out past the island's west flank
to a via at (37.94, 48.19), which is a real escape on B.Cu clear of the
keepout rather than a stub that dies against the island. OSC_OUT never enters
the channel: it leaves pad 6 straight out, 0.20 mm clear of the crystal's near
GND pad and 0.30 mm clear of pad 7's stub, and turns once into XOUT.

`copper.py` works out which pads the island shadows from the real geometry
(a pad whose radial stub cannot be drawn, on the island's side of the part)
and gives each one a same-net jumper if one is available and a channel lane
plus a via if not. There is no hand-written list of shadowed pads any more.

### The analog corner is placed, not resolved

Three rigid groups now, for the same reason the crystal island is one: the
satellite resolver walks a row outward from a host pad, and when the first
ring is full it keeps walking. In the second pass that put R209 and R213 - the
shunt's Kelvin taps - 12.5 mm away on the far side of the op-amp, because pad
1's outward normal points east straight into Q201's 11 mm DPAK courtyard.

- `KELVIN_TAPS`: R209 flat and R213 on end, 2.5 and 3.25 mm south of R204's
  sense pad, which is the floor (the 1206's courtyard reaches 1.175 mm south
  of its pad centre, group air is 0.15 mm, and an 0603 is 0.775 mm half
  height lying down). That leaves 1.15 mm and 1.23 mm of bare laminate
  between the shunt pad's copper and each tap's own pad. The centre-to-centre
  figure cannot be under 2 mm with a 1206 and an 0603, so the criteria table
  measures the copper EDGES.
  R213 stands on end rather than lying beside R209 because flat it is 3.05 mm
  wide and its far pad lands on x 51.5-52.3 - the only lane between the MCU's
  east fanout vias and the shunt, which the sense-side ground trunk needs.
- `OPAMP_WEST`: R210, C204 and R211 down the column at U202's west pads, on
  end, 3.6 mm apart. The 3.6 is 0.4 mm more than they need: it leaves 1.1 mm
  between each pair of pads, and the ground trunk crosses this column.
- U202 itself moved from 5.0 to 7.0 mm off the shunt's sense pad. At 5.0 the
  Kelvin taps and the op-amp between them left a column one part wide and
  R210 and R211 ended up 12-14 mm north, next to the handpiece terminal. The
  ADR limit is 10 mm part to part; it is 4.47 mm.

The taps are why the MCU sits 4 mm further from the USB receptacle than in the
second pass: they are inside its 5 mm halo at every closer pose, the halo
check is what makes the pose legal, and the Kelvin requirement is an ADR one
while the pose is not. The USB pair paid for it in the copper instead, by
going octilinear.

### The sense-side ground is a checked tree, not a star

ADR 0003 decision 4 says the sense side of R204 joins the pour only at the
shunt. `copper.py` draws the trunk from U202 pin 4 to R204's ground pad first
and then chains each remaining sense pad to whichever pad is already on the
trunk and nearest to it. A star at pin 4 asked the OC_REF pads, which sit on
the op-amp's east face, to go right round the part; chained, each hop is a
couple of millimetres. When the ordinary two-segment search fails, `zroute`
SCANS the middle line of a Z-shaped path in 0.05 mm steps - the lanes through
the feedback column and between the two Kelvin taps are about 1.1 mm and
0.8 mm wide and the offset that works is not on any fixed ladder.

It is then CHECKED, pad by pad, by walking the copper the run actually drew:
`sense_ground_table` builds a graph of the scripted F.Cu GND segments, finds
which of them land on each pad, and asks whether the pad reaches R204's ground
pad through that graph and whether any scripted via sits in its copper. The
run exits non-zero if a row fails. All five rows pass.

**C203.2 and C205.2 are deliberately not in that set.** C203 is the op-amp's
+3V3 bypass: its ground carries the supply's return current, not a
measurement, and tying it to the single point instead of to the plane directly
under it turns 15 mm of 0.20 mm trace around the op-amp into the bypass's
return path - worse for the op-amp than the thing the rule protects against.
C205 is the I_SENSE RC cap at the MCU pin, 20 mm away at the other end of the
board. Both take an ordinary stitching via.

### GND is closed by the script, and the router never sees it

Fifth pass, step 3b, and it is the one change that makes the rest of this pass
possible. On a 2-layer board with a solid bottom plane, a ground net the
router has to *solve* is both electrically wrong and the most expensive thing
that can happen to every other net: GND has more pads than the next three nets
put together, so whatever order the router picks it up in, it spends corridors
on it. The fix is that GND is finished before the router runs and is not in its
scope at all - `autoroute.py` asks kicad-cli what is still open and GND is not
in the answer, so it is not in the net list the router is given.

Three mechanisms, all of them searched rather than tabulated:

| what | how |
|------|-----|
| **pad stitching** | every top-side GND pad gets a stub and a 0.6/0.3 via of its own. Sixteen directions - the pad's own outward normal, the other three axes, the diagonals, then the half-diagonals - at 0.85 to 2.6 mm, and at each position the **widest** stub that clears, from `STITCH_W` = 0.40 / 0.30 / 0.25 mm. Short and fat is what a decoupling cap's ground wants; the narrow rungs exist so that a pad in a corridor gets a tie at all. 58 of 58, all of them inside the 1.5 mm `STITCH_MAX` |
| **edge stitching** | a via row along the two long edges, 10 mm pitch, 1.20 mm in from the outline: 8 on the rear edge (x 15..95, three positions refused - two M3 rings and J302's THT pads) and 9 on the front. Consecutive vias are joined by a 0.30 mm **F.Cu rib**, which is the point: a bare via in the pour is connected on one layer and kicad-cli calls that a dangling via, so the rib turns 17 holes into two 80 mm ground ribs and adds nothing to the `via_dangling` count |
| **the spine** | 20 hops, 38.32 mm, tying GND's separate F.Cu pieces to each other - see below |

Four sets are excluded and the run names every one of them with its reason:
the sense-side reference pads, which must keep their single tie at the shunt
(ADR 0003 decision 4); the QFN, whose perimeter GND pins run into the EP and
whose EP carries four vias; the four pads inside the crystal keepout, where
the rule area forbids vias and which are tied to the F.Cu ground guard; and
the 13 THT pads, which reach the pour through the zone's own thermal reliefs.

**A pad NUMBER is not a key, and that cost two passes.** SW301 and SW302 each
carry two pads numbered 2 and SW401 two numbered MP, so a loop that builds
`"%s.%s" % (ref, num)` stitches the first of each pair twice and the second
never. SW302's second pad 2 is the `Pad 2 [GND] of SW302` that kicad-cli
reported on every run of the fourth pass. The spec is `REF.NUM#i` wherever the
number repeats, the same form `copper.py` already used for the pad bridges.

**The other one was hiding behind a line that said it had worked.** The
crystal's two GND pads are inside the keepout, cannot have a via, and were
tied to *each other* and to nothing else - a 2.90 mm piece of copper that
reached the pour nowhere, while the run printed "3 of 3 island ground ties
onto the guard". The tie list is one entry per **piece** now, with the
candidates that would satisfy it, and Y301.2's leg to the guard is what
closes it (Y301.4's own leg runs into OSC_IN on this rotation and is allowed
to fail). The report that found it is `gnd_islands`, which does union-find
over real **geometry** rather than over shared endpoints: a tie that lands in
the middle of a guard leg is connected, and keyed on endpoints it is not.

#### The spine, and why a via of its own is not enough

A stitching stub with a via is connected - as long as the pour island it lands
in is connected. It is not always, and this is measured rather than feared.
The fifth pass's **first** route run came back with two GND pad pairs on a
board that `copper.py` had left at zero, both of them in the crystal corner:
the router lays B.Cu tracks in parallel at 0.5 mm pitch, the pour's 0.25 mm
clearance leaves no neck between two of them, and the island's own User.2
keepout plus the M3 ring plus the QFN squeeze the pour there into slivers. One
sliver, one via, one pad pair.

So `gnd_spine` ties GND's F.Cu pieces to each other **on F.Cu**, where a short
hop clears: a cluster that is one piece on top cannot be orphaned one stub at
a time, whatever the router does underneath. Kruskal again - shortest hop
first between two pieces that are not yet one - over pieces computed with the
pour deliberately **ignored**, because what the pour joins is exactly what the
router can take away again.

- Candidates are **octilinear**, not just the chord. That is not a nicety: the
  hop that closes the crystal corner is C301.2's stub to the ground guard, and
  the straight 1.48 mm line does not clear - C301's own +3V3 pad sits 0.24 mm
  off it where 0.30 is needed. The L shape is 1.57 mm and clears.
- **Three** sweeps, each `(cap, lone stubs only, may enter the QFN annulus)`:
  `(2.00, no, no)`, `(2.50, yes, no)`, `(3.00, yes, yes)`. The second and
  third only fire off a **lone stub** (under `GND_SPINE_LONE` = 3.0 mm of
  copper of its own), because a lone stub is the whole population at risk - a
  big piece already holds several vias in several pour islands - and the
  second one is also refused inside 6.5 mm of the QFN centre, which is where
  the escape annulus is.
  The third sweep is the sixth pass's targeted fix for the two GND pad pairs
  the fifth pass shipped, and its shape is the point: it only ever sees a
  piece that is STILL alone after the other two, which on this board is a
  couple of stubs rather than a population, so it cannot draw the fourteen
  long hops that simply raising sweep 2's cap to 4.50 does. For a stub with
  nothing at all holding it to the rest of GND, a 3 mm hop through the annulus
  is worth more than the escape lane it costs. It drew 3 hops, 8.08 mm.
- The run now also NAMES what is still a lone piece, with the distance to its
  nearest neighbour and the reason the hop was refused
  (`GND lone piece at (x, y) ... nearest piece 2.89 mm away ..., C205.1
  (I_SENSE) 0.000 < 0.250`). There are 30 of them, each holding one via, and
  every one is a place where a diced pour could reopen a GND pad pair - which
  is why `autoroute.py` now scores an open GND pad pair ahead of everything
  but an error.
- **2.50 mm and not 4.50, measured.** At 4.50 the sweep draws 14 long hops and
  62.59 mm of extra GND copper, two of them diagonals across the USB corner at
  y 8..12 and two through the clamp corner. That is a bigger perturbation of
  the router's corridors than it buys, and it buys almost nothing: what closed
  the crystal corner is the short L-shaped hop above.

20 hops and 38.32 mm take GND from **63 pieces of F.Cu copper to 43**.

**One tie still depends on its pour island: C304.2's stub.** Everything south
of it has to cross LED_STAT's channel lane and everything north is inside the
QFN's escape annulus, so no hop at any cap reaches it. It keeps its own via
and it is the single place on this board where a diced pour could reopen a GND
pad pair.

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

### The QFN escape fan, and why the vias moved out of the first ring

A via in the FIRST ring is not zero-sum, it is negative. At 0.5 mm pitch a
0.6 mm via 1.55 mm out of its pad denies **both** its neighbours any radial
escape past about 1.15 mm: a 0.20 mm track 0.5 mm to the side clears the via
by 0.50 mm where it needs 0.55. That is exactly what NTC (pad 19, between the
fanout vias of 18 and 20) and ENC_SW (pad 43, between 42 and 44) were stuck
behind, and the router said so - it reported both `boxed_in_static` and named
only copper `copper.py` had already locked as the blocker.

So the two rows that carry more signals than the first ring has lanes are
**fanned**. `QFN_ESCAPE` in `copper.py` gives a pad three numbers:

| field | what it means |
|-------|---------------|
| `fan` | the lateral step in mm, signed +y for a row facing east or west and +x for one facing north or south. The entries of one row must be monotonic in the lane they start from, or two escapes cross |
| `reach` | where the escape ends, from the pad centre - 2.60 or 2.90 mm |
| `via` | drop a 0.6/0.3 via there |

Each escape leaves its pad radially, turns 45 degrees at `QFN_FAN_R` =
1.35 mm and lands on a lane of its own in a second, wider ring:

- **east row** (pads 15-21), lane pitch **0.70 mm**, fanned towards the lanes
  of pads 13 and 14;
- **west row** (pads 40-44), lane pitch **0.90 mm**, fanned into the lanes of
  pads 38/39 one way and 45/46 the other. It stops at y = 45.75 and not
  46.25 because C304, pad 48's own 100 nF, sits on that lane.

The room comes from the pads that are unconnected on this design - 3, 4, 10,
13, 14, 26, 30, 38, 39, 45, 46 - which get no copper at all and so leave their
lanes free. The script works that out from the netlist; there is no list.

At 0.70 mm pitch a via clears a neighbouring lane's 0.20 mm track by 0.15 mm,
and two vias on lanes 1.4 mm apart clear each other's holes by 0.6 mm, so the
four vias (18 VIN_SENSE, 20 PB2, 42 LCD_BL, 44 BOOT0 - the same four nets as
before) now sit 2.90 mm out where they block nobody. Every used pad on both
rows keeps a straight top-layer lane of its own from the pad to the second
ring. The escape is drawn biggest-fan-first and every variant is
clearance-checked before it is committed; if the tabulated one does not
clear, the run backs the reach off in 0.30 mm steps, then drops the via, then
falls back to the old plain radial stub, and says in the notes which it took.

A pad whose `FIRST_RING` trace cannot be drawn now keeps the plain radial
stub it would otherwise have had. Without that, pad 22 (VCAP1) was left with
no copper at all and the router had nothing to pick up.

### Three pad pairs the netlist asks for and no router can close

`BRIDGES` in `copper.py`. Two footprints carry pad pairs that are one node on
the schematic and two separate pieces of copper on the board, so kicad-cli
counts each as an unconnected pad pair for ever and there is no ratsnest
route for a router to find.

| what | why | drawn |
|------|-----|-------|
| U302 pins 1-6 (D-) and 3-4 (D+) | the USBLC6-2SC6 brings each data line out on two pins and joins them on the die | 1.35 mm straight across the package, 0.20 mm, starting 0.2 mm inside each pad; it clears pins 2 and 5 by 0.55 mm |
| SW401's two MP lugs | both mounting lugs carry the pad number `MP`, so KiCad invents the net `unconnected-(SW401-PadMP)` for them. Nothing else is on it | 11.20 mm straight down x = 88 under the encoder's body, 0.25 mm, 7.5 mm clear of every other pad of the part |

The U302 bridges cost the USB pair **no length**: the run is still
J301 -> pin 3 -> die -> pin 4 -> MCU and the bridge is a stub off it, not a
detour in it. Both budgets are still 37.88 / 37.88 mm with 0 vias.

Because a pad number is not a key on this board any more, `copper.py` takes
`REF.NUM#i` as a pad spec (`SW301.2#0`, `SW301.2#1`).

### The three paths that change layer

There are three lists of dictated waypoints that leave F.Cu, and they exist
for the same reason each time: the F.Cu route is not congested, it is
**walled**, and the wall is either this script's own locked copper or a pad.
`layered()` draws all three, checks every run and every via in full before it
commits anything, and puts a via at the point two consecutive runs share.

| list | path | F.Cu | B.Cu | vias | drawn in |
|------|------|------|------|------|----------|
| `POWER_LAYERED` | CLAMP D202 -> the bypass FET | 8.91 mm | 3.75 mm | 2 | step 7 |
| `SIGNAL_LAYERED` | PB2 pad 20's escape -> R303 | 1.00 mm | 5.71 mm | 1 new (the escape already had one) | step 6c |
| `VDDA_LAYERED` | pin 9 -> C306 | 1.54 mm | 1.41 mm | 2 | step 5 |

The two new ones are the seventh pass. PB2 is described under "Five explicit
signal paths" and VDDA under "A 0.25 mm pad is a 0.25 mm track"; CLAMP's is
below.

`POWER_LAYERED`, and CLAMP's tap to the bypass FET is the only entry in it.
D202 (the SMBJ24A) sits with VIN on its east pad, and both ways east out of
its west pad are blocked by copper this script drew first:

- the band between D202 and Q201's DPAK tab (y 20.65..22.60) runs into the
  1.0 mm COIL_NEG trunk at x = 67, which drops from the SS110 into the FET
  tab and is a wall from y = 15 to y = 22.6. The slot east of that trunk is
  0.40 mm wide and a HighCurrent net needs 0.40 mm of air on each side alone;
- the corridor north of the terminal (y ~ 13) is crossed by the 1.0 mm VIN
  leg from J201 pin 1 to C102.

Left to the router this tap came out about 50 mm, down the right-hand edge of
the board and back west. It is now **8.91 mm of F.Cu, 3.75 mm of B.Cu and two
vias** - 12.66 mm in all. The slot it costs the pour is at y = 21.6, south of
the flyback loop rather than under it, so the loop's return path is untouched
and the scripted loop is still 21.38 mm.

### Five explicit signal paths

`SIGNAL_EXPLICIT` in `copper.py`, drawn by step 6c. Same shape as
`POWER_EXPLICIT`: every waypoint is a pad spec, `ESCAPE.<QFN pad>` (the far
end of that pad's fanned escape, so the path follows the placement instead of
a hard-coded number) or a literal `(x, y)`, consecutive points are H, V or
exactly 45 degrees apart, and the whole polyline is clearance-checked as one
before anything is drawn. A path that fails falls back to the plain radial
stub for its QFN pad, so a pad is never left bare.

These three are the remainder the third pass handed the router and the router
did not close. Only one of them was ever reported as blocked, and that report
was wrong in a way worth remembering: `trace` prints the reason its LAST
candidate failed, not the reason its best one did, so "pin 22 -> C308 blocked
by FB301's VDDA pad, 0.04 mm" came from a detour candidate that passes 7 mm
from the direct path. FB301 was never in the way. The real blocker was the
+3V3 tree, which runs after the first-ring step and had already been given
the lane. VIN_SENSE was never attempted at all - `RC_MAX` skipped its three
hops by 0.24, 0.36 and 1.43 mm - and neither was GATE_IN, which is not a
filter link and had no table to be in.

| net | what it is | where it goes |
|-----|-----------|---------------|
| GATE_IN | MCU pad 29 to R202, the gate driver's input pulldown | 16.67 mm down the east side of R307 at x = 49.90, 0.20 mm. See below - the lane is a choice between two, not a search |
| VCAP1 | MCU pad 22 to C308, the internal regulator's 2.2 uF | east at y = 42.25 to x = 53.50, then straight north into the pad: the 0.55 mm slot between C302 pad 2 and C104 pad 1, which takes a 0.20 mm track with 0.025 mm to spare on each side |
| VIN_SENSE | R102/R103 divider, C104 filter, MCU pad 18 | pad 18's escape east to a lane at x = 55.25 (the 0.65 mm slot between C207's two pads), branching north over C104 and south to R103; then R103 -> R102 down x = 57.25 |
| I_SENSE | the op-amp's output filter at the ADC pin: pad 16's escape, R212, C205 | 5.80 mm through the 0.80 mm slot between FB301 pad 1 and R217 pad 2, then 1.94 mm to the cap. In again this pass - see below |
| PB2 | pad 20's escape to R303, the LCD's series resistor | `SIGNAL_LAYERED`, seventh pass: 5.71 mm of B.Cu under the C207 / C104 column and 1.00 mm of F.Cu into the pad, one new via. There is no F.Cu lane - see below |

**PB2 is the one signal path that cannot stay on top, and the wall is this
script's own copper.** Pad 20's fanned escape ends at (52.338, 43.450) with a
via of its own already there; R303 pad 1 is 6.23 mm away at (54.175, 37.500).
Every F.Cu way north is closed:

- VCAP1's path runs east along y = 42.250 from pad 22 to x = 53.500 and then
  turns north, so the escape sits SOUTH of a wall spanning the whole x 49.4..53.5
  band. Getting round its corner means staying east of x = 53.850 (0.35 mm of
  air between two 0.20 mm tracks).
- The only slot north of there is the 0.80 mm gap between C302 pad 2 (right
  edge 53.225) and C207 pad 1 (left edge 54.025) - and VCAP1's own x = 53.500
  lane is in it. What is left on its east side reaches x = 53.775 and PB2 needs
  x >= 53.850: **short by 0.075 mm**.
- The next slot east, between C207's two pads, is VIN_SENSE's x = 55.250 lane,
  and east of C207 again means crossing VIN_SENSE's y = 44.850 trunk or NTC's
  diagonal from pad 19's escape into C207 pad 1.

So PB2 drops to B.Cu **at the via its escape already carries** - no new via at
the MCU end - crosses under the column, and comes back up in the 1.05 mm gap
between R303 pad 1 (bottom edge 37.975) and C104 pad 1 (top edge 39.025),
where a 0.6/0.3 via clears both by 0.525 mm and VCAP1's lane by 0.675 mm. The
B.Cu leg is drawn diagonal-then-vertical on purpose: the mirror image
(vertical at x = 52.338 first) would put its slot in the pour directly under
C302 pad 2, the MCU's own VDD decoupling ground, where this one runs under two
signal pads whose return path nothing needs.

**GATE_IN has exactly two lanes and neither is free.** It has to cross the
14 mm between the QFN's north row and the driver block, and PA10's pull-up
(pad 31 -> R307, a 45-degree run out to x = 49.0) lies across the way:

- `x = 46.75`, straight north out of the pad. Clears, 16.92 mm - and walls
  PA10 off from its own resistor and blocks LCD_RST's way west to the LCD
  header. Two local links for one.
- `x = 49.90`, east of R307. PA10's run ends up parallel to GATE_IN's
  diagonal 0.67 mm away and survives; so does LCD_RST. The one thing it costs
  is +3V3's EAST approach to R307 pad 2.

The second is taken. Its diagonal is pinned inside a 0.11 mm window: the line
`x + y = 86.11` clears R307 pad 1's corner by 0.29 mm (0.25 needed) and pad
28's radial stub by 0.39 mm (0.35 needed), and one of the two bounds moves the
wrong way if the trace is widened past 0.20 mm.

**What the paths cost, honestly.** They close seven pad pairs the router
could not (VIN_SENSE 3, I_SENSE 2, GATE_IN 1, VCAP1 1) and they open four on +3V3,
because every one of their lanes is one the `+3V3` tree had been using: the
tree drops from 18 hops / 240.22 mm / 4 islands (third pass, no explicit
paths) to 14 / 169.63 / 8. The new islands are `C302.1 + U301.24`,
`C304.1 + U301.1 + U301.48`, `C114.1 + U102.5`, `FB301.1` and `R217.1` -
I_SENSE's lane is what separates the last two. That is a fair trade only
because it is a trade of
*unroutable* pairs for *routable* ones - +3V3 is a Power-class net with a via
budget of 8 and 0 used, so the router can cross any of the three lanes on
B.Cu, and it closed the whole +3V3 remainder in the third pass. The scripted
paths cannot: VCAP1 and GATE_IN are the two nets on this board with nowhere
to put a via (no 0.75 mm clear radius exists in the QFN's first or second
ring).

**The fourth path is I_SENSE, and it is in again.** In the fourth pass it was
drawn, measured well (5.80 + 1.94 mm, both clear) and made the board **worse**:
7 open pad pairs instead of 4, because both winning net orderings then failed
to finish GND and the completeness gate dropped GND whole. The diagnosis at
the time was right about the mechanism and wrong about the cause. The lane
I_SENSE takes is the 0.80 mm slot between FB301 pad 1 and R217 pad 2, the only
way through that corner, and it splits FB301 from R217 on the +3V3 tree - that
was the expected cost and it is a fair one. The unexpected cost was GND, and
GND was only exposed to it because **GND was the router's job**.

It is not any more (step 3b), so the corner is I_SENSE's to take: 7.74 mm of
0.25 mm F.Cu over two legs, 0 vias, and the two I_SENSE pad pairs that were
open on every attempt of both fourth-pass runs are closed by the script. The
general lesson survives its own correction: a lane through a corner is not
free even when the clearance check says it is - but the right response was to
take the contended net out of the contest, not to give up the lane.

`RC_MAX` is also worth a note, because it is why I_SENSE is not drawn by the
filter step: it measures from the **pad**, and pad 16 to R212 pad 2 is
7.29 mm. But pad 16 is a fanned pad whose escape already ends 2.60 mm out,
and from there R212 is 5.11 mm - inside `RC_MAX`. Step 8 routes from the
escape end and gates on the pad, so for a fanned pad it measures the wrong
distance. Fixing that gate is its own pass, not a table entry.

The VIN_SENSE leg down to R102 runs at `x = 57.25` and not at 56.60, which is
the shortest lane that clears. At 56.60 it sits 0.375 mm off R217 pad 1 and
walls the rail tree out of that pad as well; 57.25 leaves a 0.65 mm slot
there and costs the leg 0.54 mm. It did not give the island back on this
placement - the tree is greedy and the hops it takes first moved - but the
lane is the right one to leave open.

**VIN_SENSE and NTC have to cross somewhere.** They come off adjacent QFN
pads (18 and 19) and their filter caps are the other way round - C104 is
north of C207 while pad 18 is south of pad 19 - so on one layer the two
filter links cross. NTC's link keeps the diagonal it had; VIN_SENSE goes
round it to the east, 1.26 mm clear, which is what the x = 55.25 lane is for.

### Power rails are trees, not rings

`RAILS` in `copper.py`. The router has no notion of a rail: it takes the pad
pairs of +3V3 in whatever order its net ordering hands them and joins each to
the nearest copper it has already laid, which came out as 229 mm and a ring
round the MCU. `rail_tree` draws the rail as a tree instead - repeatedly the
shortest hop between two pieces of that net's copper that are not yet one
piece, which is Kruskal with a clearance check in place of the cycle test.

Two things make it a trunk with branches rather than a chain of pads:

- a hop may end on any **corner of a piece of that net's copper that already
  reaches a pad**, not only on another pad. That is what a tap is: R404's
  +3V3 does not walk to another pad, it joins the run going past it. Pad to
  pad alone the same tree stopped at 16 hops and 6 islands; with the taps it
  is 18 hops and 4 - two more pad pairs closed for 22.5 mm of copper;
- two sweeps. The first only takes a hop whose real copper is within 1.35x
  the straight line between its ends, so a pair that happens to be nearest
  but has to go round the MCU does not become the trunk; the second takes
  what is left at 2.5x. Nothing longer than `RAIL_MAX_HOP` (26 mm) is
  scripted at all - past that it is a board-crossing run with a dozen ways
  round, which is a routing decision.

The QFN's own +3V3 pads are never hop endpoints (at 0.5 mm pitch no rail
width fits, and all four are already on their first-ring cap), and every hop
is clearance-checked and tried at 0.50, then 0.35, then 0.25 mm.

The run prints every hop with its straight-line distance beside the copper it
actually took, the islands it could not join, and the net's minimum spanning
tree as the floor to read the total against.

### Nothing routed by the tool is imported without a kicad-cli grade

The autorouter never runs on a repo file, and no track it produces is copied
into `graver-controller.kicad_pcb` unless `kicad-cli pcb drc` against the
**committed** `.kicad_pro` and `.kicad_dru` passes on the candidate board and
the net meets a stated budget. The `.kicad_dru` half of that sentence is the
sixth pass's: the grade was run without the rules file for five passes, and a
rules file that is not beside the board it grades is not a rule.

### What is left for the router, and the exact command

After `copper.py` the board has 71 unconnected pad pairs over 39 nets (it was
73 over 41 before VDDA and PB2 went over two layers, 76 over 43 before the GND
stitching and I_SENSE, 78 over 46 before the three
explicit signal paths, and 101 over 49 before the escape fan, the pad bridges,
the CLAMP crossing and the rail trees) - the GPIO, SPI, UI and long power
links ADR 0003 decision 8 hands to KiCadRoutingTools. **GND is not among
them**, which is the fifth pass's whole point; it still appears in the
`--power-nets` list below, which now only fixes a width the router never uses.
Run it on a **copy**, never on the repo:

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

This one call with `--track-width 0.2` for everything is also why
`routability.sh` is a **placement** test and not a routing step: at one track
width the neck-down ladder puts a Power or HighCurrent net on the board at
0.2 mm wherever the wide route is blocked, and its grade does not look at the
`.kicad_dru` at all. Read its open-net count, not its copper. `autoroute.py`
splits the call by width class - see "Why `--power-nets-widths` was not
enough".

### The long VIN link is deliberately not scripted

VIN has to get from the bulk capacitor (x 12) to the terminal's pin 1
(x 69.5) and the USB pair has to get from the receptacle (x 28) to the MCU
(x 47): the two runs are opposite diagonals across the same rear half and
they cross. The reserved VIN corridor at y 14..17 is exactly where the pair
crosses it. Something has to change layer, and the ADR says the pair does
not ("no vias, over unbroken bottom ground"), so the pair is scripted
via-free and the VIN link is handed to the router with
`--power-nets-widths 0.8`.

What the router did with it, and what is committed: **VIN is 193.91 mm with 6
vias, and its narrowest segment is 0.50 mm** - the HighCurrent floor, not the
0.8 mm the flag asks for. The difference is the neck-down ladder and it is now
visible instead of hidden: in the fifth pass 97 mm of this net was 0.2 mm
copper. It is not via-free and on this placement it cannot be - the rear edge
has no second corridor - so the vias are the price of keeping the USB pair
via-free, which is the ADR requirement of the two.
None of them is under the pair: the pair is on F.Cu over unbroken B.Cu pour
for its whole 37.88 mm, checked by `autoroute.py` and enforced by the User.2
bands `copper.py` draws along it. The fix if Jan wants VIN flat is a
placement one (the DC jack and the terminal on the same side of the USB-C,
or the pedal jack's slot reused), not a routing one.

### Two escapes out of boxed-in pads

Seventh pass, `ESCAPES` and step 7c. Both entries are the same shape as
`power_escape` and as every QFN escape - a short piece of copper off a pad with
a **via** at its far end, so that what the router picks up is a track end in
open copper rather than a pad it cannot reach - and in both cases the direction
is dictated rather than searched, because the one corridor out is known and a
search would take the wrong one first.

#### NRST off C309, and what VDDA's two vias cost

This one is `VDDA_LAYERED`'s bill, and it is the clearest measurement of the
whole pass. NRST's four pads are U301 pad 7 and C309 pad 1 - one piece of
copper, joined by the first-ring trace - plus SW302's two halves at y = 19.125
and J302 pad 4 at the rear edge, so the cluster in the MCU's south-west corner
has to reach y = 19. In the sixth pass the router did it by dropping to B.Cu at
(46.800, 49.850), south-west of C309, the one direction that is neither the
crystal island nor the pin row, and running down to (46.800, 52.300).

Putting VDDA's two vias at (47.250, 48.225) and (48.250, 49.225) added
`/MCU/VDDA` to the ring of LOCKED copper round that cluster, and the p10 run is
what that cost:

    ROUTE FAILED - no rippable blockers found
    Hint: the box also includes PROTECTED net(s) ... '/MCU/VDDA' (locked) ...
    within 3mm of the failing endpoint(s). The router will NEVER rip these.

NRST failed on **all three orderings and on the mop-up**, and because the
mop-up pass runs at `--track-width 0.20` it also ripped VBUS and re-laid it at
0.20 mm, which the size gate then dropped whole. One boxed-in cluster, six pad
pairs: NRST 3, VBUS 3.

So the corridor is scripted instead of hoped for: 0.74 mm of 0.25 mm F.Cu
south-west out of C309 pad 1, and a 0.6/0.3 via at (46.850, 49.800) which
clears the crystal ground guard at x = 46.200 by 0.650 mm where 0.600 is needed
and C309 pad 2 by 0.525 where 0.450 is. It goes in before the ground stitching,
so C309 pad 2's own stub has to find another direction rather than this one -
and it does, the run still ties 58 of 58 top-side ground pads.

**The general lesson, and it is the seventh pass's one real lesson.** A
scripted via does not only occupy its own 0.6 mm. It adds its net to the list
of locked copper the router will never rip, and if it lands inside 3 mm of
another net's only escape, that other net is finished - no ordering, no rip and
no number of attempts will recover it. Two vias closed a 2 mm gap and opened
six pad pairs somewhere else, and neither the clearance check nor the DRC could
see it. The only thing that could was routing the board and reading the
router's own hint.

#### The +5V trunk is an escape, not a trunk

`C201.1 <-> D105.1` - the gate
driver's supply cap to the ORing diode - is 39.93 mm and is the one pad pair
the router had produced **no copper at all** for in four of six passes. The
reason it printed was not congestion: *"the failing endpoint is boxed in by
copper `copper.py` LOCKED"*. That is exactly right, and it is measurable.
C201 has two ways out of the driver block and no more:

- **north**, up the empty column at x = 51.275 between J302 pad 5 (right edge
  48.010) and the driver;
- **west**, along the 1.05 mm lane at y = 24.500 between C201's own pads and
  R202's, which takes a 0.50 mm track with 0.075 mm to spare on each side.

South of it there is nothing. GATE_IN's pulldown leg runs east along
y = 26.500 from x = 49.175 to 51.812, GATE_IN's main lane is a wall at
x = 49.900 from y = 26.225 to 36.210, and the two ground stitching vias at
(50.487, 28.000) and (51.087, 28.950) close the 2.1 mm slot east of that lane
(a 0.50 mm track needs 0.75 mm to a via centre and the two leave 0.117 mm).

**The trunk is not scripted, and the corridor search is why.** A grid search
over `copper.py`'s own clearance model, with the flyback loop and the USB pair
each carrying an extra 1 mm:

| route | length | what it costs |
|-------|--------|---------------|
| F.Cu at 0.50 mm | **111.6 mm** | up the rear, along y = 4.5 past the receptacle, and all the way down the LEFT edge at x = 7 - the x = 23.5 lane between the receptacle and the buck only takes 0.30 mm |
| F.Cu at 0.30 mm (the `.kicad_dru` floor) | **94.96 mm** | diagonally across the rear right, which walls J302's four signal pads and SW301's +3V3 from the south and cuts +3V3's own rear branch |
| B.Cu, direct | 40 mm | crosses **under the USB pair** at (41.89, 33.74). ADR 0003 component breakdown 3 forbids it and the User.2 bands enforce it, for the router too |
| B.Cu, legal | ~84 mm | the pair's F.Cu run is one unbroken wall from (28.250, 7.245) to (45.250, 40.562), so the only legal crossings are north of J301 (y < 6) or south of the MCU. Both are the long way round again, and the return is a 50 mm slot in the pour |

2.4 to 2.8 times the straight line, for one pad pair, through corridors that
half a dozen other nets want. So step 7c draws the **escape** instead: 2.50 mm
of 0.50 mm F.Cu north out of C202 - the northernmost +5V pad, tied to C201 by
the scripted bypass leg - and a 0.6/0.3 via at its end in open copper 2.0 mm
clear of anything. The endpoint the router called boxed in is then a track END
with a via on it, in exactly the position every QFN escape is in, and the
40 mm crossing is the router's to make the way it makes VIN's and VBUS's.

It stops at y = 19.000 on purpose: the reserved VIN corridor is y 14..17 and
+3V3's own rear branch comes up x = 48.000.

## Routing the rest

`autoroute.py` is the routing step. `routability.sh` is the placement test
and imports nothing; this one produces the copper that ships.

    cd Hardware/graver-controller
    python3 tools/pcb/autoroute.py            # route, grade, import, report
    python3 tools/pcb/autoroute.py --strip    # undo: remove it and refill
    python3 tools/pcb/place.py --copper --silk --route      # the whole board

It needs the KiCadRoutingTools checkout and its venv (`--system-site-packages`
plus numpy, scipy, shapely, Pillow, so `pcbnew` stays importable). Both are
found through `KRT_DIR` / `KRT_PY`, which default into the scratch directory
`PCB_SCRATCH` points at. The stage refuses to run if its work directory is
inside the git repository.

Options: `--strip`, `--no-import` (route and grade, touch nothing),
`--reuse` (grade and import the copy already routed), `--ordering NAME` (one
attempt with that ordering instead of the three), `--first A,B,...`,
`--nets ...`, `--label NAME`, `--rip`, `--no-drc`.

**KiCadRoutingTools is not deterministic.** Part positions are identical run
to run but the `.kicad_pcb` serialisation order is not - KiCad regenerates
item UUIDs and writes footprints in a UUID-dependent order - the net ordering
ties break on it, and two runs of this stage on the same placement have come
out 13 and 20 open pad pairs apart. So the stage routes the same input
`ATTEMPTS` = **3** times and imports the best of them, and prints all three
with their scores so the spread is visible rather than hidden. The attempts
take different net orderings while the pool lasts (`ORDERINGS` = mps, bus,
inside_out, original) because a different ordering is a bigger perturbation
than the serialisation noise, and repeat the pool after that. Three is the
useful number: mps, bus and now `inside_out` have all won, `original` has
never won by more than the noise, and a fourth attempt costs a few minutes
for about one pad pair. It is not a luxury - in the p9 run mps and bus both
came back with 2 open GND pad pairs and `inside_out` with none, and the
score's first tie-break after the error count is **open GND pairs**, because
`copper.py` closes GND before the router runs and a GND pair on the candidate
therefore means the router's B.Cu cut a pour island.

The chosen copy's summary is written to `output/pcb/route-summary.txt` - the
attempt table, open / vias / errors / tracks / nets, the nets the router
produced nothing for, and the longest ten. Nothing in `$PCB_SCRATCH` is ever
committed, so that file is the only thing that survives a run.

### What the stage does

1. **Removes** the group `autorouted` from the board, refills the zones and
   saves. That is what makes it idempotent and what `--strip` stops after:
   the router's copper is never edited in place, it is thrown away and
   redone.
2. **Asks kicad-cli what is still open** on that stripped board. Those nets,
   minus `NO_ROUTE` and the auto-named `unconnected-*` ones, are the scope,
   and nothing outside the scope is ever imported.
3. **Routes a copy** outside the repository, in passes - one per
   `.kicad_dru` width floor, widest first, and each split into the nets in
   `FIRST` and the rest:
   - `w50-first` / `w50`: the HighCurrent nets, at `--track-width 0.5`;
   - `w30-first` / `w30`: the Power nets, at `--track-width 0.3`;
   - `first`: the `FIRST` signals, so the QFN escapes get first pick of the
     corridors;
   - `rest`: everything else, each pass on the last one's output;
   - up to two mop-up passes for whatever is still short, split by class the
     same way, with `--rip-existing-nets '*'`.

   The `--track-width` per pass is the width fix - see "Why
   `--power-nets-widths` was not enough".

   The whole chain is run `ATTEMPTS` times and the best-scoring attempt is
   the one that gets imported. The score is errors, then open pad pairs, then
   **vias**, then how many nets were taken.
4. **Grades** - see below - and writes `output/pcb/route-summary.txt`.
5. **Imports** the surviving nets' tracks and vias into the repo board, not
   locked (they are the router's and regenerable) but grouped `autorouted`,
   and refills the zones with pcbnew's `ZONE_FILLER` so the pour closes round
   the new copper.
6. **Reports**: kicad-cli on the repo board, vias total and per net, the
   longest ten nets, the keepout check and the ADC-versus-switching
   parallel-run check.

The exact router call, per pass:

    route.py <in> <out> --nets <this pass's nets> \
        --track-width <this pass's floor> \
        --clearance 0.15 --via-size 0.6 --via-drill 0.3 \
        --grid-step 0.05 --escalation off --strict-sizes \
        --keepout --keepout-layer User.2 --keep-input-copper \
        --ordering <mps|inside_out|bus|original> \
        --power-nets GND +3V3 +5V VBUS /MCU/VDDA VIN /Driver/COIL_NEG \
            /Driver/CLAMP /Driver/SHUNT_HI \
        --power-nets-widths 0.4 0.5 0.5 0.5 0.5 0.8 0.8 0.8 0.8

and the **pristine `.kicad_pro` and `.kicad_dru` are copied next to every
scratch board** the stage writes - the input of each pass, its output, and the
candidate it grades. Both, and always: the router finds them by basename
beside its input (`design_rules.DesignRules.from_project`) and uses them for
the per-net draw width, the cross-class clearance map and the rescue ladder's
floors, and `kicad-cli` reads them beside whatever board it grades. A
candidate graded without the `.kicad_dru` is graded without the width rules,
which is exactly how the fifth pass imported 237 undersized segments and
reported 0 errors.

The widths come out of the committed `.kicad_pro` net classes (Power 0.5,
HighCurrent 0.8); GND is a Default-class net and gets 0.4 because its job
here is the return path between two pour islands, not a signal. `--clearance`
stays at 0.15 in every pass and the Power / HighCurrent clearances are NOT
passed: the tool auto-reads the cross-class map from the sibling `.kicad_pro`
when `--net-clearances` is omitted and prices every foreign obstacle at
`max(this pass's floor, that net's own class clearance)`, which is what KiCad
grades against. There is **no `--write-fill`**: the pour is `copper.py`'s, and
the router's own refill of it does not apply the 0.25 mm hole clearance to
J301's two NPTH pegs - that is the pair of `hole_clearance` errors
`routability.sh` has always reported. The candidate board is filled by pcbnew
instead, which does.

### Why `--power-nets-widths` was not enough, and the fix

The fifth pass's board carried **237 `track_width` errors** against the
`.kicad_dru` - VIN with 97 mm of 0.2 mm copper inside a 0.8 mm net, +3V3 with
82 undersized segments, VBUS 62, VDDA all 10 - and the reason is not that the
flag was ignored. It was honoured: the router's log prints the assignment
table (`0.8mm: VIN, /Driver/CLAMP, ...`) and the glob, the order and the
pairing are all as documented.

`--power-nets-widths` is what the router **tries**. When a wide route is
blocked it prints `Wide route blocked - retrying at default track width
(neck-down)`, re-routes the whole net at the layer's default width, and then
re-widens only the segments where the wide clearance happens to fit
(`single_ended_routing._neck_width_for_net` returns
`config.get_track_width(layer)` - that is `--track-width`, with no reference
to the net's own floor; the 0.26 / 0.32 / 0.38 / 0.44 mm segments on VBUS are
its four-step taper, visible in the board). With one `--track-width` of
0.2 mm for the whole board, every necked segment of a Power or HighCurrent net
is a rules violation, and nothing in the stage was looking: the size gate
checked the board minimum (0.20 mm) rather than the net's floor, and the
candidate was graded without the `.kicad_dru`.

So the stage routes **one pass per width floor, with `--track-width` set to
that floor**:

| pass | nets | `--track-width` | why |
|------|------|-----------------|-----|
| `w50-first`, `w50` | the open HighCurrent nets | 0.50 | the HighCurrent floor. The neck-down may now neck to 0.50, which is legal |
| `w30-first`, `w30` | the open Power nets | 0.30 | the Power floor |
| `first` | the `FIRST` signals | 0.20 | the QFN escapes' one lane each |
| `rest` | everything else | 0.20 | |

Each width class is split by `FIRST` the same way the signal class always was,
each pass runs on the last one's output, and the mop-up passes are split by
class too. Wide first is also the right order for its own sake: a 0.8 mm trunk
has far fewer places to go than a 0.2 mm signal.

Three things make it stick rather than hope:

- the size gate now drops a net whose copper is under **its own** floor
  (`undersized(items, floor_of(net))`), not just under 0.20 mm;
- the candidate carries the `.kicad_dru`, so a `track_width` error is
  attributable to the net that caused it and the error gate drops that net;
- the final report prints a per-net **minimum** width table against the
  floors, because a 0.8 mm trunk with one 0.2 mm neck is a 0.2 mm net to both
  DRC and the current.

**`kicad-cli` stops reporting a violation type at 199 markers** and says
nothing about it, which is worth knowing because the fifth pass's headline was
"199 track_width errors". It was 237: widening 40 of the +3V3 segments made 38
previously invisible ones appear (VBUS 24, VDDA 10, SHUNT_HI 4). Any count
that lands exactly on 199 is a floor and not a total; the stage prints a NOTE
when it sees one.

### The grading rule

The router's own pass messages are ignored, and so is `kicad-cli` on the
router's **output file**: its writer re-emits the GND pour, and a run that
routed nothing at all still graded 433 errors, all of them the zone. What is
graded is the board the stage **would commit**: the stripped repo board plus
the copper about to be imported, filled by `ZONE_FILLER`, with the pristine
`.kicad_pro` **and `.kicad_dru`** beside it. Nothing is written to the repo
until that candidate passes.

Four gates, in order, each of which only ever **removes** a net from the
import:

| gate | rule |
|------|------|
| size | a net with any track under **its own `.kicad_dru` floor** (0.50 HighCurrent, 0.30 Power, 0.20 otherwise) or any via under 0.6/0.3 is dropped whole. `--strict-sizes` is not enough, and neither was the flat 0.20 mm this gate used for five passes: the tool's "net rescue" narrows a via to 0.45/0.20 and then writes the relaxed floor into the sibling `.kicad_pro` so its own check passes, and the neck-down ladder emits 0.20 mm copper on a 0.80 mm net without calling it a narrowing at all |
| complete | a net still showing an unconnected pad pair on the candidate is dropped whole; its partial copper is not worth the dangling ends |
| errors | every kicad-cli error whose items include a track or via of a net being imported takes that net out, one net at a time, **cheapest first** - a violation names two nets and dropping +3V3 to save GND costs twenty-one pad pairs to save two |
| final | any error left on the candidate refuses the whole import and the board is not written |

Imported copper is **not locked**. `copper.py`'s copper is, and that is what
keeps the router off it; the router's own copper is regenerable and the point
of the `autorouted` group is that step 1 can find it again.

### What never gets imported

- Anything on a net that was not already open before the run. The stage only
  ever adds copper, so a net the scripted copper finished is untouchable.
- The USB pair. `NO_ROUTE` holds `/MCU/USB_DP` and `/MCU/USB_DM`: ADR 0003
  wants them via-free and length-matched, `copper.py` draws them that way and
  locks them. U302's own duplicate I/O pins used to show up here as two open
  pad pairs; `copper.py` bridges them now - see "Three pad pairs the netlist
  asks for and no router can close".
- Any auto-named `unconnected-*` net. `unconnected-(SW401-PadMP)` used to be
  one of the remainder; `copper.py` links the two lugs now, and the stage
  still never hands the router a net of that kind.
- Zones. The stage imports tracks and vias only; the pour is `copper.py`'s.

### Where it came out

71 unconnected pad pairs before, **10 after**, over 6 nets, with **0 errors
against the `.kicad_dru`** and 0 schematic parity issues on the repo board.
34 nets routed, 1142 tracks and 120 vias imported (219 vias on the board in
all, of which 99 are scripted and 87 are GND's).

**The sixth pass's board was 3 open with 0 on GND and this one is 10 with 2,
so the routed board got worse.** That is the seventh pass's headline and it is
not a sentence to bury. What got better is the half that does not depend on
the router: the scripted copper leaves 71 pad pairs instead of 73, VDDA's
pin 9 and PB2 are closed by the script at their own width floors and stay
closed on every future run, and GND is still 0 after `copper.py`. What got
worse is everything the router then did with the corridors those two paths
took, and the accounting is below.

#### The seventh pass, run by run

| run | what changed | attempts (errors / open GND / open / vias / nets) | imported |
|-----|--------------|---------------------------------------------------|----------|
| p10 | `VDDA_LAYERED`, `SIGNAL_LAYERED` (PB2), the +5V escape | mps 0/0/8/118/35, bus 0/0/8/118/35, inside_out 0/1/9/131/35 | mps, **8 open**: VBUS 3, NRST 3, +5V 1, LCD_RST 1 |
| p11 | + the NRST escape of step 7c | mps 0/4/10/125/36, bus 0/4/10/125/36, inside_out **0/2/10/120/34** | inside_out, **10 open**: VBUS 3, GND 2, BOOT0 2, +5V 1, LED_STAT 1, LCD_SCK 1 |

VDDA and PB2 are closed in both, which is what the two runs were for. The rest
of the movement has two causes and both are worth carrying forward:

**1. A scripted via is not a local decision.** VDDA's two vias put
`/MCU/VDDA` inside 3 mm of NRST's only escape, and the router will never rip a
locked net - so NRST failed on all three orderings of p10, the mop-up ran, and
the mop-up runs with `--rip-existing-nets '*'` at `--track-width 0.20`. It
ripped VBUS, re-laid one 0.200 mm segment of it at (39.80, 24.80), and the
size gate then dropped VBUS **whole**, three pad pairs, for one segment.
Scripting NRST's escape (step 7c) fixed NRST in p11 - and VBUS still went,
because p11's winning attempt also needed a mop-up, for LED_STAT and BOOT0.
**Any mop-up costs VBUS on this board**, and the fix is in `autoroute.py`, not
in the copper: the mop-up pass should be split by width class the way the main
chain already is, or it should not rip a net whose floor is above its own
`--track-width`. That is the first thing to do in an eighth pass and it is
worth three pad pairs on its own.

**2. GND is still one re-route away, and this time it moved.** p10 came back
with 0 open GND pairs on two of three orderings; p11 with 4, 4 and 2. The two
that were imported are both `Track [GND] 0.85 mm <-> Track [GND] 0.85 mm` -
two stitching stubs whose pour islands the router's B.Cu separated, exactly
the mechanism "What is still rough" item -7 describes and exactly the
population (30 lone pieces holding one via each) it names. Nothing about GND's
own copper changed between p9, p10 and p11; what changed is the B.Cu around
it.

The sixth pass's two runs, for comparison:

| run | what changed | attempts (errors / open GND / open / vias / nets) | imported |
|-----|--------------|---------------------------------------------------|----------|
| p8 | the width fix: a pass per `.kicad_dru` floor, the floor in the size gate, the rules file beside every scratch board | mps 0/0/4/126/38, bus 0/0/4/126/38, inside_out 0/0/5/126/37 | mps, **4 open**: ENC_A 2, +5V 1, LCD_RST 1 |
| p9 | + each width class split by `FIRST`, and ENC_A / ENC_B promoted into it (the one targeted fix) | mps 0/2/7/142/37, bus 0/2/7/142/37, inside_out **0/0/3/139/38** | inside_out, **3 open**: /MCU/VDDA 1, Net-(U301-PB2) 1, +5V 1 |

**The targeted fix half worked and the other half backfired, and both halves
are the same measurement.** Promoting the encoder pair did what it was meant
to - ENC_A closed at 68.66 mm and ENC_B at 88.48 mm, the first pass in which
both are routed - but splitting the Power class into `w30-first` (+3V3,
/MCU/VDDA) and `w30` (+5V, VBUS) moved +3V3's trunk, and on **two of the three
orderings that reopened GND**: mps and bus came back with 2 GND pad pairs
each. Only `inside_out` did not, and it is the attempt that got imported -
which is exactly what three attempts and a score that puts GND ahead of
everything but an error are for. The honest reading is that this board's GND
is one +3V3 re-route away from an open pour island at any time, and that the
attempt-and-score machinery, not the spine, is what caught it this time.

It is also the first time `inside_out` has won anything: it lost by 9 and 11
pad pairs in the fifth pass and by 1 in p8.

Named exactly, from `kicad-cli`'s own item descriptions:

| net | pairs | the two ends, and why |
|-----|-------|-----------------------|
| VBUS | 3 | D103.2 <-> U302.5, J301.A4 <-> J301.A9 and U302.5 <-> J301.A4 - the **whole net**, dropped by the size gate for one 0.200 mm segment at (39.80, 24.80) that the mop-up pass laid after ripping it. It routes: the routed copy carries 67.8 mm of it at 0.30/0.50 mm and nothing else is wrong with it. See cause 1 above; this is an `autoroute.py` bug, not a copper decision |
| GND | 2 | two pairs of 0.85 mm stitching stubs whose pour islands the router's B.Cu separated. See cause 2 above and "What is still rough" item -7 |
| Net-(U301-BOOT0) | 2 | R302 pad 1 and R301 pad 1 to pad 44's escape - the router laid 1.35 mm and 0.55 mm of it and then LED_STAT's mop-up took the corridor. Closed in p9 and p10 |
| +5V | 1 | C201.1 <-> D105.1, **39.93 mm** across the whole board, and the only entry here that has been open in every pass. The endpoint is no longer boxed in - step 7c gives C202 a 2.50 mm escape with a via - and the router still produced no copper for it, which is the measurement that matters: the crossing itself is the problem, not the escape. See "The +5V trunk is an escape, not a trunk" for the four routes and what each costs |
| LED_STAT | 1 | pad 2's channel lane out of the crystal island to D301. Closed in p9 and p10 |
| LCD_SCK | 1 | pad 15's escape to J401 pin 3. Closed in p9 and p10 |

**ENC_A, ENC_B, NRST, LCD_RST, DECAY_SLOW, I_SENSE, VCAP1, GATE_IN, VIN_SENSE,
/MCU/VDDA and Net-(U301-PB2) are all closed.** The last two are the seventh
pass's own, and they are closed by the script rather than by the router, which
is the difference that survives a re-run.

**The headline numbers, honestly.** 5 open pad pairs in the fifth pass, 3 in
the sixth and 10 here; 2 on GND there, 0 there and 2 here. The routed board is
worse, and pretending otherwise would be the one thing this file has never
done. Three of the ten are an `autoroute.py` mop-up bug with a named fix, two
are the GND pour-island mechanism that has been on the "still rough" list
since the fifth pass, and three (BOOT0 2, LED_STAT 1, LCD_SCK 1) are the
corridors the mop-up took. What the pass bought is on the other side of the
router: 71 pad pairs out of `copper.py` instead of 73, no Power-class net
entering a 0.25 mm pad anywhere, and two gaps that no longer depend on which
ordering wins.

**The USB band is free now.** It used to cost three pad pairs (10 open
without it, 13 with); on this board the router finds its way round it and
`usb_reference_check` reports no crossing at all.
`USB_KEEP = 0` in `copper.py` still turns the band off.

Levers tried on NTC and ENC_SW in the **third** pass, and what each cost.
All of these were measured before the USB band went in, so compare them
against 10, not 13, and not against the fourth pass's 4:

| lever | result |
|-------|--------|
| net ordering | mps and bus agree and win, inside_out and original both lose by 4 to 7 pad pairs. The tool is not reproducible across board files whose only difference is the serialisation order, which is why several attempts are run and the best kept |
| `--rip-existing-nets` on the blockers, named exactly | refused: the tool protects a whole NET as soon as any of its copper is KiCad-locked, and `copper.py` locks an escape on nearly every net at the QFN. Unlocking the router's own copper between passes (the stage does this) is the only rip that works |
| `QFN_VIA_PADS = ()` | closes NTC, opens LCD_BL and VCAP1: 12 open, 40 nets |
| `QFN_VIA_PADS = ("42", "44")` | closes NTC and ENC_B, opens VCAP1, and lets a +3V3 via land 0.18 mm from a GND track: 12 open, 41 nets |
| a User.2 band round the crystal ground guard | the router treats any User.2 polygon as a hard block whatever its size, and a 0.05 mm band closes the west corridor: 12 open |
| GND at 0.20 mm clearance via `--net-clearances` | same, 12 open - and the flag REPLACES the whole cross-class map, so the file has to carry the Power and HighCurrent nets too or they route at 0.15 |
| **the escape fan** (the one that worked) | none of the above moved NTC or ENC_SW because all of them keep asking WHICH pads get a first-ring via. Fanning the two rows to 0.70 / 0.90 mm lane pitch and putting the same four vias out at 2.90 mm takes the question away: 78 open pad pairs after `copper.py` instead of 101, with NTC, ENC_SW and ENC_B each holding a clear straight lane of their own |

`QFN_VIA_PADS` is no longer a hand-written tuple - it is derived from
`QFN_ESCAPE`, so a pad's via and the lane it sits in cannot disagree.
`SWCLK` appears and disappears from the remainder between attempts, which is
the ordering noise the three attempts are there to sample. `DECAY_SLOW` used
to do the same and no longer does: it is open on every attempt of both
fourth-pass runs, which makes it a real 42 mm problem rather than noise.

### What the renders show

`tools/pcb/render.sh` after the stage; `top.png`, `bottom.png` and
`both.png` are the three to look at.

- **The bottom pour survives everywhere except round the MCU, and that is
  where the two GND pairs come from.** The router's B.Cu copper is a knot
  round the MCU, one long diagonal out to the USB receptacle and a handful of
  runs to the driver block and the front edge; the left third, the right
  third and both long edges are solid. Inside the knot, `bottom.png` shows
  what the numbers say: closed loops of routed track, and the pour inside one
  of those loops is an island of its own. In the fifth pass two of those
  islands held one GND stitching via and nothing else, which is where its two
  GND pad pairs came from; the sixth pass had none, and **this one has two
  again** - the same shape in the same place, visible in `bottom.png` as
  closed loops of routed B.Cu east and south of the QFN with pour trapped
  inside them.
- **The two edge ribs are the clearest new thing on `top.png`.** A 0.30 mm
  F.Cu line 1.20 mm in from the rear edge and another in from the front, each
  running x 15..95 with a via every 10 mm, both stopping clear of the M3
  rings; the rear row also skips x = 45, where J302's through-holes are. They
  sit in board margin that nothing else uses, and they are what turns 17 bare
  stitching holes into two real ground ribs.
- **The GND stitching reads as a field of dots over the pour in
  `bottom.png`**, one per top-side ground pad: 87 GND vias, all of them
  scripted, against 9 the router used to add.
- **The `D202 -> Q202` clamp tap is fixed.** It was about 50 mm of the
  router's copper down the right-hand side of the board and back west; it is
  now a scripted 12.66 mm over two vias, and the flyback loop is untouched at
  21.38 mm. `/Driver/CLAMP` is 57.86 mm and 4 vias in all, but the rest of
  that is D203 at x 75 and R205 at x 80, which are 14 and 20 mm away by
  placement and not a detour.
- **The QFN escape fan is tidy and it is the thing to look at in
  `cu-qfn.png`.** Both fanned rows leave their pads radially, turn once, and
  run out to a second ring where the lanes are 0.70-0.90 mm apart; the four
  vias sit in that ring and none of them is in front of a neighbour.
- **Nothing crosses the crystal island but GND**, and nothing at all is in an
  M3 ring.
- **Nothing crosses under the USB pair on B.Cu.** It did on the first run of
  the second pass - a +3V3 track straight under D-, which is exactly the
  broken reference ADR 0003 component breakdown 3 forbids - so `copper.py`
  draws a User.2 band along every segment of the pair (`USB_KEEP`, 0.15 mm
  off the centre line) and `autoroute.py` checks it afterwards.
- **The five explicit signal paths read as intended in `cu-qfn.png` and in
  the x 43..69 / y 22..58 crop.** GATE_IN leaves pad 29, turns once and runs
  straight down x = 49.90 past R307 to the driver; VCAP1 runs east along the
  pad-22 lane and then straight north through the C302 / C104 slot; the
  VIN_SENSE column at x = 55.25 / 57.25 is three parallel lanes with the
  0.4 mm gaps the table claims; and I_SENSE leaves pad 16's escape, steps
  once at 45 degrees through the FB301 / R217 slot and lands on R212 and its
  cap. PB2 is the one that is not on `cu-qfn.png` at all - it leaves pad 20's
  escape via straight down on to B.Cu, so `bottom.png` is where to look for
  it: a 5.71 mm diagonal-then-vertical run to a via between R303 and C104.
- **VDDA's two vias are 2 mm apart in `cu-xtal.png` and that picture is the
  whole seventh pass.** Pad 9 goes 0.79 mm south, drops, crosses 1.41 mm of
  B.Cu under the two pedal stubs and comes back up beside C306. It is three
  short pieces of copper and it reads as nothing at all - and it is what
  boxed NRST in. The third via in that crop, 1.5 mm south-west of C309, is
  the escape step 7c had to add to give NRST its corridor back.
- **The power nets are visibly wider, and that is the sixth pass in one
  picture.** Every Power and HighCurrent net now carries its class width for
  its whole length except where the .kicad_dru's own floor allows less, so
  `both.png` shows `VIN` as a continuous 0.5-1.0 mm run instead of a 0.8 mm
  trunk that thins to a signal trace halfway. It came with a length and via
  dividend nobody asked for: `+3V3` 270.04 mm / 9 vias (was 299.86 / 13),
  `VIN` 193.91 / 6 (was 197.59 / 8), `/Driver/CLAMP` 51.40 / 4 (was 57.86 /
  4). `VBUS` was 67.87 / 7 in the sixth pass and is 0 in this one, for the
  reason under "Where it came out". Routing the wide nets in their
  own pass, first, is why: they get the corridors while the corridors are
  empty instead of squeezing through what the signals left.
- **What is still ugly:** `+3V3` is 270.04 mm against a 182.95 mm floor,
  `NRST` is 79.98 mm / 8 vias and `ENC_B` 88.48 mm / 6. The right-hand third
  of the board (x 78..100, y 30..50) is still empty and most of these long
  runs walk round it rather than through it. `VBUS` has **no copper at all**
  on the committed board, which is not congestion - see "Where it came out".
- **The 42 mm board crossing stays gone, and so is the encoder's.**
  DECAY_SLOW is routed (60.12 mm, 8 vias), LED_STAT with it (52.28 mm), and
  both ENC_A (68.66 mm) and ENC_B (88.48 mm) are closed for the first time in
  six passes. What is left in the remainder is not a board crossing at all
  but two short gaps - /MCU/VDDA's 1.98 mm and PB2's 6.22 mm - plus the 40 mm
  +5V run nothing has ever routed. See "Where it came out".

### How the committed board was actually produced

The seventh pass's board is the straightforward thing and not a re-import:

1. `VDDA_LAYERED`, `SIGNAL_LAYERED` (PB2) and the +5V escape in `copper.py`,
   then `place.py --copper --silk` - 0 errors, **71** open pad pairs, GND 0.
2. `autoroute.py --label p10` - three attempts, mps won at 8 open. VDDA and
   PB2 closed; NRST boxed in by VDDA's vias, and the mop-up that followed
   took VBUS with it.
3. The one targeted fix the brief allowed - NRST's own escape in step 7c -
   then `place.py --copper --silk` again (still 71 open, GND 0) and
   `autoroute.py --label p11`: three attempts, `inside_out` won at **10**.
4. `PXMM=24 tools/pcb/render.sh`.

The sixth pass's board, for the record:

1. `copper.py`'s widths taken to the `.kicad_dru` floors, the GND spine's
   third sweep and `power_escape` for pad 9, then
   `place.py --copper --silk` - 0 errors, 73 open pad pairs, GND 0.
2. The width fix in `autoroute.py` (a pass per floor, the floor in the size
   gate, the rules file beside every scratch board), then
   `autoroute.py --label p8` - three attempts, mps won at 4 open.
3. Each width class split by `FIRST` and the encoder pair promoted into it,
   then `autoroute.py --label p9`:
   three attempts, `inside_out` won at **3**. No `copper.py` change between
   p8 and p9, so the scripted copper is the same board in both.

For the record, the **fourth** pass's board was a re-import, and the
mechanism is worth keeping in mind: `place.py --copper --silk` reproduces a
board exactly, because the placement and the scripted copper are both
deterministic, so `autoroute.py --reuse --label <old>` can re-grade an old
set of routed copies against it in 13 seconds instead of 45 minutes.
`--reuse` is only safe when the scripted copper it is graded against is
byte-equivalent to the one it was routed against; it is not a shortcut to use
after changing `copper.py` or `place.py`, which is why the fifth pass did not
use it.

### How to redo it

    python3 tools/pcb/autoroute.py --strip     # board back to scripted-only
    python3 tools/pcb/autoroute.py             # route it again

A re-run does the strip itself, so the second line alone is enough. Changing
`copper.py` or `place.py` means re-running those first, because the stage
starts from what is on the board:

    python3 tools/pcb/place.py --copper --silk --route

Artefacts for one run land in `$PCB_SCRATCH/autoroute/<label>/<ordering>/`:
one `route-<stage>.log` and JSON summary per pass (`w50`, `w30-first`, `w30`,
`first`, `rest`, `m1-0` ...), the `stage-<name>.kicad_pcb` each pass handed on,
`routed.kicad_pcb`, and `candidate.kicad_pcb` with the DRC report that graded
it - each with its own `.kicad_pro` and `.kicad_dru` copy beside it. None of
it is ever committed.

## Hand routes survive a regeneration

`manual.py`. `place.py` rebuilds the board from the schematic on every run, so
anything drawn by hand in pcbnew used to be gone the next time the pipeline
ran - which is why the README used to say the script "stops being safe to
re-run" once routing starts by hand. It does not any more.

    python3 tools/pcb/place.py --export-manual   # board -> tools/pcb/manual.json
    python3 tools/pcb/manual.py --export         # the same, standalone
    python3 tools/pcb/manual.py --restore        # manual.json -> board

**There is no marker to set and nothing to remember in the GUI.** Every piece
of generated copper on this board belongs to a PCB group that its own script
strips and remakes - `scripted-copper`, `scripted-silk`, `autorouted` - so a
track that is in none of them is by definition a hand route, and that is the
whole rule. Draw it in pcbnew, anywhere, any net, any layer; the export finds
it.

Tracks, arcs and vias are collected, as geometry and net **names** rather than
UUIDs, because a UUID does not survive `place.py` rebuilding the footprint it
hangs off. Coordinates are mm from the board's top-left corner, the same
convention as the placement tables, so `manual.json` is readable and editable
by hand. A stored item whose net no longer exists on the board is reported and
skipped, not silently dropped.

The restore runs as the **last** step of a pipeline run - `place.py` calls it
itself after copper.py, silk.py and autoroute.py - puts everything into a group
named `manual`, and refills the zones so the pour closes round it. The group
name is what makes the next export find the same items again, and the restore
is idempotent the same way the other stages are: it drops the previous
`manual` group's members before adding, so it never stacks copper.

`manual.json` is the **source of truth**, in both directions. An absent or
empty store means the board must not carry a `manual` group either, so the
way to take a hand route out again is to delete it from the file (or delete
the file) and re-run - and the common case, nothing stored and nothing on the
board, does not rewrite the board at all.

Order matters and only one way round works: **export before regenerating**,
because the regeneration is what destroys them. `--export-manual` therefore
does nothing else - it reads the board, writes the file and exits.

Round-tripped before it was documented: a 4 mm 0.30 mm GND track at
(86, 46)-(90, 46) plus a via drawn into the board with pcbnew in no group,
exported (2 items), `place.py --copper --silk` run, and both came back in the
group `manual`; then `manual.json` removed and `manual.py --restore` took them
off again and left the board with `scripted-copper` and `scripted-silk` only.
`manual.json` is absent in the repo, which is what an empty store looks like.

## Silkscreen

`silk.py` runs after `copper.py` (or as `place.py --copper --silk`) and
touches **F.Silkscreen only**: it creates no copper item, moves none and
deletes none, and it leaves F.Fab exactly as `place.py` made it. The run
prints a before/after copper census (tracks, vias, zones) and exits non-zero
if any of the three numbers moved.

    python3 tools/pcb/silk.py             # place + DRC before/after
    python3 tools/pcb/silk.py --no-drc    # skip both kicad-cli DRC runs
    python3 tools/pcb/silk.py --verbose   # one line per reference

It is idempotent in two different ways, because there are two kinds of silk.
Everything it **creates** - the rear-edge connector labels, the two pin
legends, the pin-1 markers and the board title - goes into a PCB group named
`scripted-silk`, and the first thing a run does is delete that group's
members, exactly as `copper.py` does with `scripted-copper`. Everything it
**moves** - every footprint's reference field - is positioned absolutely from
the part's own body box and never relative to where the field currently
sits, so a second run computes the same answer. Verified: re-running on an
already-silked board gives a byte-for-byte identical set of 739 silk items.

### What the stage does

1. **Clips the library silkscreen to the board outline.** All four rear
   connectors are right-angle parts that overhang the rear edge on purpose
   (`EDGE_PARTS` in `place.py`), and their library outlines overhang with
   them - that is 15 of the 17 `silk_edge_clearance` warnings. A graphic that
   still has a piece inside the board is shortened in place, one that is
   wholly outside is removed: 15 shortened, 11 dropped. Clipping an already
   clipped segment is a no-op, which is what keeps this idempotent. The price
   is 4 `lib_footprint_mismatch` warnings, one per trimmed connector; there
   is no way to trim a footprint's own graphics and keep it byte-identical to
   the library, and the alternative is silk printed over the board edge.
2. **Resets every reference** to 1.0 mm text at 0.15 mm stroke on
   F.Silkscreen, upright, `keep_upright` off (ADR 0003 decision 5 minimum).
   The four mounting-hole references (`MH401`-`MH404`) are hidden instead -
   brief item 4, they do not need a silk label. The other 2 edge-clearance
   warnings were two of those.
3. **Places the labels first**, before any reference: they are the ones that
   have to be somewhere specific.
4. **Places the 113 references** by searching.

### The obstacle set, and the search

Every candidate position is tested as the text's **real** bounding box -
`PCB_TEXT::GetBoundingBox()` after actually setting the position and angle,
not a width estimate - against:

- every **mask opening** on the front, taken as the pad's bounding box grown
  by 0.05 mm, with 0.03 mm of air required. That is KiCad's `silk_over_copper`
  rule ("silkscreen clipped by solder mask"); vias are tented on this board
  so they have no opening and do not count.
- every **silk graphic** of every footprint, decomposed to segments
  (rectangles to four edges, circles to 16 chords, arcs through their mid
  point, polygons to their outline), 0.03 mm of air past the line's own half
  width. That is `silk_overlap`.
- every **silk text already placed**, same 0.03 mm.
- the **board outline** with its 2 mm corner radii, 0.5 mm of clearance,
  which is the brief's number and stricter than `silk_edge_clearance` needs.

The box is always larger than the glyphs it contains - about 0.25 mm on each
side at 1.0 mm text - so a box that clears by 0.03 mm has a quarter of a
millimetre of real ink clearance. 1024 obstacles go into a 4 mm spatial hash,
because the search probes tens of thousands of positions and a linear scan
would be minutes.

Candidate order per part, first legal wins:

1. **inside its own body outline** for a part whose F.Fab body is 20 mm2 or
   more - the connectors, the QFN, the DPAK, the SO-8s, the inductor, the
   buttons and the encoder. 10 references land here. The part's own outline
   is still an obstacle, so this only succeeds where the body really is
   empty: the QFN's exposed pad and the USB receptacle's shell pads push
   those two back out.
2. **ring by ring outwards**, 0.15 mm to 1.50 mm in 0.15 mm steps, and inside
   a ring above, below, left, right, then the four corners - the brief's
   order. Text runs across the part above and below it and along the part at
   its two sides, which is what stops a row of standing 0603s fighting for
   one lane.
3. the same ladder out to 3.0 mm.
4. **a 0.25 mm grid sweep** out to 12 mm round the body centre, nearest
   first. The eight ring directions are a ladder and a ladder misses pockets
   that are not on an axis; where a whole block is this tight what comes out
   of the sweep is a line of references above or below the row of parts,
   which is the brief's "reference row".

Parts are placed big bodies first (they are the ones that can carry their
reference inside their own outline), then small parts **most crowded first**:
the tightest neighbourhood gets first pick, because a part with room to spare
still has room after its neighbour has taken the one lane that was left.

### A legal label is not a readable one

DRC cannot ask which part a label belongs to. A reference that sits nearer
someone else's body than its own reads as that other part's, which is worse
than a reference 4 mm out in clear space. So the search runs twice: the first
pass requires the part's own body to be the nearest body, give or take
`OWN_SLACK` (0.25 mm, without which two 0603s 1.6 mm apart could never both
be labelled); the second pass drops that test for the 12 parts that are boxed
in on all sides, and for those it does **not** take the first legal position
but collects the legal candidates at roughly the best distance available and
picks the one with the most air round it. Without that, R210's reference
landed 7.15 mm from R210 and 0.20 mm from U202 and read as the op-amp's; it
is now 6.52 mm out with 0.70 mm of air.

The run prints every label that is still nearer another body than its own,
worst first. 28 of 113 are, but 21 of those are ties inside a quarter of a
millimetre between two adjacent passives, which context resolves. The ones
worth knowing about:

| ref | from itself | nearest other | why |
|-----|-------------|---------------|-----|
| R210 | 6.52 | 0.70 (U202) | the `OPAMP_WEST` column: three 0603s on end at 3.6 mm pitch between the op-amp and the ground trunk, no gap anywhere near them |
| C308 | 4.27 | 1.35 (U301) | second ring behind the QFN's east pin row |
| R211 | 4.35 | 1.69 (R408) | as R210 |
| C102 | 2.27 | 0.00 (J201) | inside the terminal's outline, above C102. The 1.8 mm band in front of J201 is 0.01 mm too narrow for 1.0 mm text and D202 owns everything past it |
| C405, R212 | 5.10, 4.80 | 4.85, 4.57 | both out in clear space below the MCU; ambiguous but not misleading |

### Where the counts came out

| bucket | count |
|--------|-------|
| inside its own body outline | 10 |
| ring 1, <= 1.5 mm of air | 87 |
| ring 2, <= 3.0 mm of air | 7 |
| reference row, > 3.0 mm | 9 |
| own-part test relaxed (boxed in) | 12 of the above |
| no legal position anywhere | 0 |
| silk label dropped | 4 (MH401-404) |

The nine in a reference row are Y301 3.75, R212 4.80, R211 4.35, C311 3.50,
C405 5.10, C308 4.27, R210 6.52, R407 3.85, R405 3.49 mm - the VDDA / crystal
fan below the QFN and the op-amp column, the same two blocks the placement's
own "What is still rough" list already calls out.

### How to nudge a label

`REF_OVERRIDE` at the top of `silk.py`, same shape as the placement tables in
`place.py`: `ref -> (dx, dy, rot)` puts that reference at the footprint
**origin** plus `(dx, dy)` mm at `rot` degrees and skips the search entirely.

    REF_OVERRIDE = {
        "C102": (0.0, -2.5, 0),      # 2.5 mm above C102's origin, upright
        "R210": (1.6, 0.0, 90),      # 1.6 mm east, running along the part
    }

The run counts these separately, and because it still tests them it prints
`OVERRIDE <ref> is not legal: <what it hits>` when a nudge lands on a pad or
on another label. It does not move it back - a nudge is an instruction, not a
suggestion - so read the line.

Everything else is a table too:

- `REAR_LABELS` - `(ref, text, seed (x, y), size)` for the five rear names.
  The seed is intent, not a coordinate: the label is searched outwards from it
  on a 0.1 mm grid and the run prints how far off the seed it ended up (all
  five landed on their seed).
- `PIN_LEGEND` - `(ref, pad, text, offset from that pad, rot, size)`. The
  offset is from the **pad**, so the legend follows the connector if
  `place.py` moves it.
- `PIN1_MARKS` - `(ref, pad, seed, direction the tip points)` for the filled
  triangles.
- `TITLE` - the board title lines.
- `EDGE_CLR`, `PAD_CLR`, `SILK_CLR`, `OWN_SLACK`, `BIG_AREA`, `FREE_R` - the
  numbers behind the search, one comment each.

### The rear edge, and the two connectors that are their own label

ADR 0003's "Polish" item, plus SWD:

| ref | text | at | note |
|-----|------|----|------|
| J101 | `DC 24V` | 17.60, 1.58 | inside the jack outline, between the rear edge and the +24 V pad. 1.2 mm text in a 2.17 mm band, which is why the label size is the bottom of the brief's 1.2-1.5 mm range |
| J301 | `USB` | 29.00, 4.20 | inside the receptacle outline, between the two rows of shell pads |
| J302 | `SWD` | 43.60, 5.60 | in front of the header, with a filled triangle at 37.00, 4.95 pointing at pin 1 |
| J201 | `HANDPIECE` | 61.90, 4.60 | plus `4 GND` / `3 NTC` / `2 COIL` / `1 VIN` at 1.0 mm on the pin pitch at y = 7.00, and a triangle at 71.85, 10.05 pointing west at pin 1 |
| J402 | `PEDAL` | 88.00, 1.75 | inside the Neutrik outline |
| J401 | pin names | y = 66.90 | `G 3V3 SCK SDA RST DC BL` rotated 90 degrees along the pins, in front of the body, plus a triangle at 20.00, 57.30 pointing down at pin 1 |

The J201 legend follows the **board** order, not the schematic's: J201 is
forced to rotation 180 because its four wire-entry funnels are drawn on its
+y side, which reverses the pins. Seen from the front, left to right, it is
4 GND / 3 NTC / 2 COIL_NEG / 1 VIN. See "Connector orientation" above.

Two of the six labels are honest compromises and worth stating. J201's and
J402's names sit **inside their own connector body outline**, because both
parts are right-angle types that cover the board from the rear edge inwards
and the space in front of them is occupied (D201, D202, C102, U401 for the
terminal; U401, D203, C103, Q202 for the jack). The brief asks for the label
"just inside the rear edge next to each connector", which is where they are;
they will be under the part once it is mounted. The same is true of `DC 24V`
and `USB`. If Jan wants them visible on an assembled board the fix is
mechanical - the names belong on the rear wall of the cover plate - not a
silkscreen one.

`J401`'s pin-1 triangle is the one marker that is not next to its pin name
row: the name row is in front of the connector and C111/C112 sit under pins
1 and 2 there, so the triangle went into the 1.7 mm band **above** the
connector at pin 1's own x. Pin 1's name, `G`, is also 1.1 mm further out
than the other six for the same reason.

The board title is `GRAVER CTRL r0.1` at 57.00, 67.30 and `2026-09` at
74.00, 67.30, both 1.4 mm, in the empty front-centre strip.

## Routability test

`tools/pcb/routability.sh [label]` is a **placement test, not the routing
step** - `autoroute.py` is the routing step, see "Routing the rest". Run this
one to compare two placements; it is a single strict autoroute with no
passes, no mop-up and no import, so its open-net count is a lower bound on
what the placement can do, not what the board ends up with. It copies the board and the project into a scratch directory outside
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
| p3final | third pass: island in the corner, Kelvin taps, sense ground | **6** | **120** | **2** |

Third pass, the two rows that matter (`p3before` is `after2` re-run on the
same day for a fair comparison):

| iteration | open nets | vias | kicad-cli errors |
|-----------|-----------|------|------------------|
| p3before | 7: NTC, LED_STAT, PEDAL_TIP, NRST, PEDAL_RING, LCD_DC, LCD_MOSI | 130 | 2 hole_clearance |
| p3final | 6: /MCU/VDDA, NTC, LCD_DC, LCD_RST, PEDAL_TIP, LCD_MOSI | 120 | 2 hole_clearance |

NRST, PEDAL_RING and LED_STAT close because the crystal island stopped
standing in front of their pads. /MCU/VDDA and LCD_RST open instead: VDDA's
own 2.5 mm hop is now the router's (see the table in "What is still rough"),
and LCD_RST is second-ring congestion on the MCU's new pose. PEDAL_TIP has a
radial stub now and is congestion rather than a trap. Ten fewer vias, and the
two remaining errors are the same router pour artefact at J301's NPTH pegs as
in the second pass - `copper.py`'s own fill applies the 0.25 mm hole clearance
and the committed board reports 0 errors.

The second pass's rows: the scripted copper took a strict autoroute from 9
open nets / 189 vias / 24 errors to 7 / 140 / 2. The
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

## 3D models

`MODEL_SUB` in `place.py`, applied by `substitute_models` right after the
placement checks. Six footprints on this board name a `.step` file KiCad 10
does not ship, so the part is missing from the 3D view, from
`kicad-cli pcb render` and from a STEP export. Three of them have a stand-in
of the right body size in the library and get it; three do not.

This is **cosmetic and board-only**: the footprint libraries, the pads and the
courtyards are untouched, the footprint's own model entry is kept and only its
path is rewritten, so the offset, rotation and scale come along unchanged. The
run prints one line per substitution and one line naming whatever is still
model-less.

| ref | footprint asks for | gets | why |
|-----|--------------------|------|-----|
| U301 | `QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm.step` | `QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm.step` | same QFN-48 7 x 7 mm 0.5 mm-pitch body; the two differ only in how big the exposed pad under it is drawn |
| SW301, SW302 | `SW_Push_1P1T_XKB_TS-1187A.step` | `SW_Push_1TS009xxxx-xxxx-xxxx_6x6x5mm.step` | the TS-1187A's own F.Fab body is 5.8 x 4.8 mm, so the 6 x 6 x 5 mm 1TS009 is the nearest body in `Button_Switch_SMD.3dshapes`. The other candidate, `SW_SPST_TS-1088`, is a 3.9 x 3.0 mm part and a third too small |

**Three parts still have no model anywhere** and render as bare pads:

| ref | part | what is needed |
|-----|------|----------------|
| J301 | HRO TYPE-C-31-M-12 USB-C receptacle | manufacturer STEP |
| SW401 | Alps EC11E rotary encoder, vertical, 20 mm shaft | manufacturer STEP |
| J402 | Neutrik NMJ6HCD2 6.35 mm jack | manufacturer STEP |

`/usr/share/kicad/3dmodels` has no file for any of the three and nothing in
the library is the right shape to stand in - a USB-C receptacle, an encoder
with a 20 mm shaft and a chassis jack with a 3 mm ferrule are all parts whose
whole point is their mechanical outline. They have to come from the
manufacturers into a project `3d/` folder, and `MODEL_SUB` has to point at it,
**before** the enclosure STEP export (ADR 0003 mechanical step 2): those are
exactly the three parts the cover plate has to clear. The same three are the
ones in "TODO for Jan" item 3 whose dimensions are still unmeasured, so the
caliper session and the STEP hunt are one job.

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
| `silk-*.png` | crops of `silk.png` | the silkscreen one block at a time: rear-l, rear-r, mcu, front, power |

`render.sh` draws layers. The raytraced 3D view is a separate call and is what
checks the models in "3D models" above:

    kicad-cli pcb render --side top --width 1400 --height 900 \
        -o output/pcb/render-top.png graver-controller.kicad_pcb


`PXMM=24 tools/pcb/render.sh` is worth it for the silk crops - the default 18
pixels per mm is marginal for reading 1.0 mm references.

The crop windows in `render.sh` are tied to the current MCU pose (46, 44) and
to the crystal island being south-west of the part. Move the MCU and they need
moving too - they are plain mm rectangles at the bottom of the script.

`critical.png` is rendered from `output/pcb/critical.kicad_pcb`, a
**review-only** copy that `place.py` writes with the nets in `CRITICAL_NETS`
drawn as straight User.1 segments (flyback loop, buck SW and BST, crystal, USB
pair, I_SENSE, shunt, gate). The committed `.kicad_pcb` carries none of them.

## What is still rough

Honest list, worst first. Items -7..-1 are copper and routing; the rest are
placement and the numbers in them are from the second pass.

-7. **GND is closed by the script and it is one re-route away from not being -
    and in the seventh pass it stopped being.** 0 open GND pad pairs after
    `copper.py`, on every pass; **2 on the routed board**, against 0 in the
    sixth pass and 2 in the fifth. Nothing about GND's own copper changed: the
    p11 attempts came back with 4, 4 and 2 GND pairs where p10's came back
    with 0, 0 and 1, on the same 87 scripted GND vias and the same 20 spine
    hops. Both of the two that were imported are a pair of 0.85 mm stitching
    stubs whose pour islands the router's B.Cu separated. Read the rest of
    this item as the standing description of a mechanism that has now fired
    twice in three passes. The spine's
    third sweep is what closed C309.2 (the hop the fifth pass missed by
    0.02 mm) and the score change is what caught the rest: in the p9 run
    **two of the three orderings came back with 2 GND pad pairs each**, on a
    board where nothing about GND had changed - moving +3V3's trunk was
    enough. The stage imports the attempt with the fewest GND pairs first and
    the count second, so it took the one that has none.
    What has not gone away is the mechanism. 30 pieces of scripted GND F.Cu
    copper are still **lone pieces holding one via each**, and the run now
    names every one of them with the reason its hop was refused. Each is a
    place where the router's B.Cu can cut the pour island under that via and
    reopen a pad pair. The real fixes are a second via per lone stub (needs
    1.1 mm of room that mostly is not there) or a B.Cu keepout band under the
    worst of them; the cheap one, if it happens on a future run, is the 2 mm
    hand route `manual.py` exists to keep.

-6. **237 `track_width` errors, and five passes of not seeing them.** The
    fifth pass's board had 97 mm of 0.2 mm copper inside the 0.8 mm VIN net,
    82 undersized segments on +3V3, 62 on VBUS and every one of VDDA's 10 -
    legal-looking copper that the router's neck-down ladder had quietly
    downgraded when a wide route was blocked. It is 0 now: each width class
    routes in a pass whose `--track-width` IS its `.kicad_dru` floor, the
    size gate checks the net's own floor instead of the board's 0.20 mm, and
    the `.kicad_dru` is copied next to every scratch board so the grade
    includes the rule at all. Two things are worth carrying forward from it.
    The first is that a rules file is only a rule where it sits: five passes
    of `kicad-cli pcb drc` ran without it. The second is that `kicad-cli`
    caps its report at 199 per violation type and says nothing - the headline
    was "199" and the truth was 237.
    What is left is one class of violation that no routing can fix: a
    Power-class net entering a 0.25 mm QFN pad. See "A 0.25 mm pad is a
    0.25 mm track"; it costs a rule change or a placement change, and no pad
    on the board is exposed to it any more - the only one that was, VDDA's
    pin 9, is owned end to end by `VDDA_LAYERED` at the 0.30 mm floor, so the
    router never enters it.

-5. **Ten pad pairs are open and two of them are GND, which is worse than the
    sixth pass.** `VBUS` (3), `GND` (2), `Net-(U301-BOOT0)` (2), `+5V` (1),
    `LED_STAT` (1) and `LCD_SCK` (1) - named pad by pad in "Where it came
    out". The two the seventh pass set out to close, `/MCU/VDDA` and
    `Net-(U301-PB2)`, are closed, by the script and not by the router, so they
    stay closed. What it cost is on this list, and only one of the ten is a
    copper decision:
    - **VBUS 3 is an `autoroute.py` bug and the first thing to fix.** The
      mop-up pass rips with `--rip-existing-nets '*'` at `--track-width 0.20`,
      re-lays a 0.30 mm Power net at 0.20, and the size gate then drops it
      whole. Split the mop-up by width class the way the main chain already
      is, or refuse to rip a net whose floor is above the pass's own width.
      Worth three pad pairs and probably a re-run of nothing else.
    - **GND 2** is item -7's mechanism, unchanged and still unfixed.
    - **BOOT0 2, LED_STAT 1, LCD_SCK 1** are the corridors the mop-up took;
      all three were closed in p9 and p10 and none is a new geometric
      problem.
    - **+5V 1** is the 39.93 mm C201 <-> D105 crossing, open in every pass.
      The endpoint is no longer boxed in - step 7c gives it an escape with a
      via - and the router still produces nothing, so the remaining answer is
      a hand route or a placement change, not a copper-script one. The
      corridor numbers are in "The +5V trunk is an escape, not a trunk".

-4. **+3V3 is 270.04 mm long and 120 mm was asked for.** The brief's budget
    is below the floor: the straight-line minimum spanning tree over the
    net's 29 pads is 182.95 mm, so nothing can route it under that. The
    scripted tree is 169.63 mm with **0 vias** and the router adds 100 mm and
    9 vias for the eight islands left; the router alone did it in 229 mm,
    with a ring round the MCU and more vias. It was 299.86 mm and 13 vias in
    the fifth pass, and the difference is the width fix: routed in a pass of
    its own at its own floor, before the signals, the rail takes shorter ways
    round. It was 240.22 mm scripted / 2
    router vias in the third pass and the difference is the four explicit
    signal paths: they take four of the tree's lanes, so four joins the tree
    used to make become the router's. So the tree still buys the topology and
    a trunk that does not move between runs, but it buys less of the via
    count than it did. If Jan wants the length back, the levers are placement,
    not routing: J302's +3V3 pin is 60 mm from the LDO, SW301's two halves
    are at the rear edge, and R304/R104 are front-right - four satellites
    that between them are most of the 183 mm floor.

-3. **The crystal island: done.** It sits in the corner at the low pin
    numbers, the OSC legs are 3.24 and 4.75 mm (were 4.99 and 4.13), the
    channel is 1.03 mm and takes two lanes (was 0.51 mm and one), and no pad
    is trapped: pads 7-12 have plain radial stubs, pad 1 has a 0.97 mm
    same-net jumper and pad 2 a 6.56 mm channel lane and a via. What it cost
    is C301, VBAT's 100 nF, which is now 2.93 mm from pad 1 instead of 1.79
    and prints OVER (advisory) with the reason. See "The crystal island lives
    in the corner" above.

-2. **The Kelvin taps: done.** R209 and R213 are 1.15 and 1.23 mm of bare
    laminate from R204's sense pad and the 0.50 mm taps are drawn from that
    pad's copper EDGE, not from its centre and not off the 1.0 mm power
    trace. 0.50 and not 0.20 since the sixth pass, because SHUNT_HI is a
    HighCurrent net and the `.kicad_dru` holds every track on it to 0.50 mm;
    a Kelvin tap carries no current, so its width was never the point and the
    EDGE still is. The follow-on run R213 pad 2 -> U202 pin 5 is still not drawn (it
    is 14 mm, across the gate drive) and is left to the router; that segment
    carries no measurement current, only the comparator's high-impedance
    input after the series resistor.

-1. **Eight local traces still could not be drawn** (29 in the second pass, 12
    before the escape fan and the CLAMP crossing, 10 before the explicit
    signal paths, 9 before VDDA changed layer; the numbers below are from the
    current run's
    "COULD NOT DRAW" list). The sense-side ground is not among them - all
    five rows of the checked table pass - and neither is the op-amp's
    feedback network, the crystal guard's west leg, the CLAMP tap, NTC's
    filter cap, PA10's pull-up or any of VCAP1 / GATE_IN / VIN_SENSE. What is
    left, with the blocker:

    | trace | blocked by | verdict |
    |-------|-----------|---------|
    | R213 -> U202 pin 5 | R307's pad | router; 14 mm, see -2 |
    | U202 pin 7 -> R214 (OC_TRIP) | R215's pad, 0.16 mm | router; R214/R215/R216 are stacked at 2 mm pitch off three adjacent op-amp pins and their pads interleave |
    | C109 -> R109 (FB feed-forward) | R110's ground pad | router |
    | R105 -> U101 pin 3, R105 -> C105 (EN/UVLO) | U102's +5V pad, R106's own pad | router; the EN/UVLO divider ended up on the far side of the LDO from the buck. Placement lever, not copper: it is the one part of the buck block that is still resolved rather than placed |
    | D103 -> J301 A4 (VBUS) | D105's +5V pad | router by design: 28 mm from the ORing diode to the receptacle, across the rear half |
    | pin 11 -> C405, pin 12 -> C404 | C306's VDDA pad | router; both parts are in the second ring behind a first-ring cap |

    `pin 9 -> C306` (VDDA) came off this list in the seventh pass and is
    2.95 mm of explicit copper over two layers now. Its old entry read
    "blocked by C309's pad, router, 2.5 mm, from a scripted escape" - true,
    and only a third of the story: pad 9 is boxed in on all four sides and the
    two ways to open it on one layer both cost more than they buy. The whole
    measurement is under "A 0.25 mm pad is a 0.25 mm track".

    `pin 22 -> C308` (VCAP1) came off this list with step 6c and is 10.79 mm
    of explicit copper now. Its old entry here read "blocked by FB301's VDDA
    pad, 0.04 mm", which was wrong in a way worth remembering: `trace` prints
    the reason its LAST candidate failed, not its best one, and that report
    came from a detour candidate 7 mm from the direct path. The real blocker
    was the +3V3 tree. See "Five explicit signal paths".

    `pin 19 -> C207` (NTC's filter cap) came off this list with the escape
    fan: it was blocked by VIN_SENSE's old first-ring via, and it is drawn
    now. A filter link that starts on a pad with a fanned escape carries on
    from the **escape end** rather than re-leaving the pad radially, or it
    runs straight back into the lane it was fanned away from.

    The buck's FB divider no longer folds back over the part (`R109` used to
    be chained off `R110` and landed across the SW node, which ADR 0003
    explicitly wants kept clear); both now hang off the FB pin and march
    south along U101's east face. `RC_MAX` came down from 12 to 6.5 mm for
    the same kind of reason: a "filter at the MCU pin" 8 mm away is not a
    filter link, and drawn as one straight trace across the corner of the
    part it cut five QFN escapes.

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
4. **ENC_SW is 66 mm of ratsnest, ENC_A/B 52-54 mm, DECAY_SLOW ~50 mm.**
   Inherent: the encoder is front-right by ADR decision and the MCU is
   centre-left, and Q203 sits with the bypass circuitry it switches. None is
   speed-critical. Routed, the router pays more than that for the pair -
   ENC_A 70.74 mm and ENC_B 88.48 mm against a 52 and a 54 mm ratsnest, and
   NRST 79.98 mm - so those are the first candidates for a hand route now
   that they are closed rather than open. Both encoder lines are only closed
   because they are in `FIRST` (sixth pass): left in the bulk pass, one of
   the two loses the corridor every time, and which one is a coin flip - it
   was ENC_B in p7 and ENC_A in p8.
5. **U202.7 -> PB12 (OC_TRIP) is ~20 mm**, not the "short track" the ADR asks
   for. The op-amp has to be within 10 mm of the shunt (it is, 1.5 mm) and the
   shunt is ~20 mm from the MCU, so the two rules fight. Keep it away from the
   coil node when routing.
6. **C111/C112 (buck output caps) drift to y ~64**, below J401, about 10 mm
   from D105. They are the last of the "oring" group to be placed and the
   front-left is full by then.
7. **Silkscreen: done.** `silk.py` takes the three silk warning types from
   92 / 92 / 17 to 0 / 0 / 0. What it cannot fix is that 12 parts are boxed
   in hard enough that their reference has to leave its own neighbourhood -
   the VDDA / crystal fan below the QFN and the three-part op-amp column -
   and 4 footprints now differ from their library copy because their
   overhanging silk was trimmed to the board edge. See "Silkscreen" above.
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
