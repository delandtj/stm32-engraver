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

Expected after `place.py` alone: 0 schematic parity issues, ~250 unconnected
items, and silkscreen warnings. After `copper.py`: 0 errors, 0 parity, 101
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
| unconnected_items | 101 | what the router still has to finish (107 in the second pass) |
| silk_overlap | 92 | silkscreen is a later pass |
| silk_over_copper | 92 | ditto |
| silk_edge_clearance | 17 | ditto |
| track_dangling | 18 | the QFN fanout stubs, dangling on purpose |
| via_dangling | 7 | fanout and stitching vias the router has not reached yet |

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
| 2 | U301 QFN fanout | 0.20 mm radial stubs on 21 pads, 0.56-1.11 mm of new copper past each pad edge; 4 vias 0.6/0.3 at 1.55 mm on pads 18/20/42/44; a 0.97 mm same-net jumper on pad 1 and a 6.56 mm channel lane + via on pad 2, the two the island shadows |
| 2 | U301 GND pins 8/23/35/47 | 0.20 mm, 0.64 mm into the EP copper |
| 2 | U301 EP | 4 vias 0.6/0.3 inside the pad |
| 3 | decoupling | 13 pin-to-cap traces on F.Cu; 61 of 63 SMD ground pads get their own via into the pour |
| 3 | U101 PowerPAD | 4 thermal vias 0.6/0.3 |
| 4 | crystal | OSC_IN 6.33 mm, OSC_OUT 7.23 mm (both including the load-cap tap), F.Cu only, 0 vias; F.Cu ground guard bracket, 3 of 3 legs + 2 stitching vias |
| 5 | VDDA | FB301 -> C306/C307 at 0.40 mm; pin 9 -> C306 is now a 2.5 mm radial escape, left to the router on this pose (see below) |
| 6 | USB | D+ 37.88 mm, D- 37.88 mm, skew 0.00 mm, **0 vias on either net** |
| 7 | power | VIN chain 0.8 mm, flyback loop 1.0 mm, gate 0.4 mm, shunt 1.0 mm, Kelvin taps 0.2 mm off the shunt pad's own copper edge, buck, +5 V/+3V3 0.5 mm; sense-side ground tree 0.20/0.25 mm |
| 8 | ADC filters | the RC parts at the MCU pins, 0.25 mm, only where the part is within 6.5 mm |

### Budgets, and how they came out

| budget | source | measured |
|--------|--------|----------|
| USB pair <= 40 mm, 0 vias, <= 1 mm skew | ADR 0003 component breakdown 3 | 37.88 / 37.88 mm, 0 vias, 0.00 mm skew - PASS with 2.1 mm of margin. The U302 -> MCU legs are octilinear now instead of L-shaped, which is worth 4.7 mm each and is what absorbed the MCU moving 4 mm back from the receptacle to make room for the Kelvin taps |
| USB coupled 0.2 mm / 0.15 mm | ADR + Jan 2026-09-18 | 0.15 mm gap on the long connector segment; 0.30 mm on the two U302 -> MCU lanes, which U302's own 1.9 mm pin pitch forces |
| flyback loop closed within ~15 mm | ADR decision 4 | 20.26 mm of real copper over its four legs, parts inside a 10 x 12 mm block under the terminal |
| buck CIN within 3 mm of the VIN pin | ADR component breakdown 2 | 2.88 / 2.74 mm pad to pad, 6.95 mm of copper |
| crystal keepout clean | ADR decision 8 | clean: only OSC_IN, OSC_OUT and the ground guard are inside it (VDDA no longer needs to be) |
| shunt is the single ground tie of the sense side | ADR decision 4 | CHECKED, row per pad, and the run exits non-zero on a FAIL: C204.2, R211.2, R216.2, C206.2 and U202.4 each reach R204 pad 2 over scripted F.Cu with no via of their own, and R204 pad 2 carries the 2-via cluster that is the sense side's only path into the pour. C203.2 and C205.2 are deliberately NOT in that set - see below |
| VIN 0 vias | this brief | the long VIN link is NOT scripted - see below |
| flyback loop perimeter | ADR | 20.26 mm; buck CIN 6.95 mm; OSC_IN 6.33 mm, OSC_OUT 7.23 mm |
| Kelvin traces from the shunt PADS to the op-amp | ADR component breakdown 4 | 1.15 mm and 1.23 mm of bare laminate between R204's sense pad and each tap's own pad, 0.20 mm traces drawn from the pad EDGE, not from the 1.0 mm power trace |

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

After `copper.py` the board has 101 unconnected pad pairs over 49 nets -
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

The crop windows in `render.sh` are tied to the current MCU pose (46, 44) and
to the crystal island being south-west of the part. Move the MCU and they need
moving too - they are plain mm rectangles at the bottom of the script.

`critical.png` is rendered from `output/pcb/critical.kicad_pcb`, a
**review-only** copy that `place.py` writes with the nets in `CRITICAL_NETS`
drawn as straight User.1 segments (flyback loop, buck SW and BST, crystal, USB
pair, I_SENSE, shunt, gate). The committed `.kicad_pcb` carries none of them.

## What is still rough

Honest list, worst first. Items -3..-1 are copper; the rest are placement
and the numbers in them are from the second pass.

-3. **The crystal island: done.** It sits in the corner at the low pin
    numbers, the OSC legs are 3.24 and 4.75 mm (were 4.99 and 4.13), the
    channel is 1.03 mm and takes two lanes (was 0.51 mm and one), and no pad
    is trapped: pads 7-12 have plain radial stubs, pad 1 has a 0.97 mm
    same-net jumper and pad 2 a 6.56 mm channel lane and a via. What it cost
    is C301, VBAT's 100 nF, which is now 2.93 mm from pad 1 instead of 1.79
    and prints OVER (advisory) with the reason. See "The crystal island lives
    in the corner" above.

-2. **The Kelvin taps: done.** R209 and R213 are 1.15 and 1.23 mm of bare
    laminate from R204's sense pad and the 0.20 mm taps are drawn from that
    pad's copper EDGE, not from its centre and not off the 1.0 mm power
    trace. The follow-on run R213 pad 2 -> U202 pin 5 is still not drawn (it
    is 14 mm, across the gate drive) and is left to the router; that segment
    carries no measurement current, only the comparator's high-impedance
    input after the series resistor.

-1. **Twelve local traces still could not be drawn** (was 29 in the second
    pass, and the numbers below are from the current run's "COULD NOT DRAW"
    list). The sense-side ground is no longer among them - all five rows of
    the new checked table pass - and neither is the op-amp's feedback network
    or the crystal guard's west leg. What is left, with the blocker:

    | trace | blocked by | verdict |
    |-------|-----------|---------|
    | pin 22 -> C308 (VCAP1) | FB301's VDDA pad, 0.04 mm | router; both are first-ring parts on the same 2 mm of edge |
    | pin 9 -> C306 (VDDA) | C309's pad | router, 2.5 mm. The island's courtyard pushes the NRST cap 1.0 mm east onto pin 9's own slot, and the corridor between C309's pad and pad 11's stub is 0.53 mm where 0.85 is needed. Both parts are inside their 3 mm criteria, so this is a 2.5 mm job for the router, not a trap |
    | D202 -> Q202 (CLAMP) | Q201's drain tab | router; the 0.5 mm clamp tap has to go round an 11 mm DPAK |
    | R213 -> U202 pin 5 | R307's pad | router; 14 mm, see -2 |
    | U202 pin 7 -> R214 (OC_TRIP) | R215's pad, 0.16 mm | router; R214/R215/R216 are stacked at 2 mm pitch off three adjacent op-amp pins and their pads interleave |
    | C109 -> R109 (FB feed-forward) | the buck's own SW pad | router |
    | R105 -> U101 pin 3, R105 -> C105 (EN/UVLO) | U102's +5V pad, R106's own pad | router; the EN/UVLO divider ended up on the far side of the LDO from the buck. Placement lever, not copper: it is the one part of the buck block that is still resolved rather than placed |
    | D103 -> J301 A4 (VBUS) | D105's +5V pad | router by design: 28 mm from the ORing diode to the receptacle, across the rear half |
    | pin 19 -> C207, pin 11 -> C405, pin 12 -> C404 | VIN_SENSE's fanout via, C306's VDDA pad | router; all three parts are in the second ring behind a first-ring cap |

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
