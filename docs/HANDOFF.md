# Handoff: graver controller board

Last updated 2026-10-01. Read this first in a new session; it says what
exists, what is decided, how to work on it and what comes next.

**Most recent change (2026-10-01): the connectors came off the board.** ADR
0003 Decision 9 replaced every board connector except USB-C with a row of
plated holes for a soldered wire loom, moved the rotary encoder off the board
into the cover plate, and shrank the board from 110 x 70 to 95 x 70 mm.
Jan's reasoning: sourcing the mating halves was the problem, soldering is
not. It also deleted the four unverified THT footprints in one go, which was
the largest open layout risk. The schematic is re-captured and ERC-clean; the
board is re-placed and re-poured; the route is the part still in flight - see
"State of the design".

## What this is

A new controller for the ITS-LZ-1335 solenoid graver in this repo. Batch of
8-10 boxes for a class (adults), each box = 24 V brick + this PCB + 1.3"
ST7789 display + one handpiece + expression pedal. PCB fully assembled by
JLCPCB, no soldering by the builders, under EUR 150 per box, enclosure to be
3D printed (Creality K2 Max). Since 2026-10-01 Jan solders five wire looms
per box when he assembles them; the class still receives finished boxes.

Upstream project: Savage-Sabrina/DIY_SolenoidGraver (Arduino Nano board);
Jan's fork of it is a separate repo. Since 2026-09-17 this controller lives in
its own repository, github.com/delandtj/stm32-engraver (`origin`), split out
with full history. Branch `master`.

## Where things are

| What | Path |
|---|---|
| Spec / decisions (Accepted) | `docs/adr/0001-graver-controller-board.md` |
| KiCad 10 project | `Hardware/graver-controller/` (root + power/driver/mcu/io sheets) |
| PCB placement script (board is generated) | `Hardware/graver-controller/tools/pcb/` (see its README) |
| Schematic checks; retired generator | `Hardware/graver-controller/tools/` (see its README) |
| Rev 0.1 reference sheets (history) | `Hardware/graver-controller/tools/ref/` |
| Part choices, LCSC numbers, datasheet gotchas | `Hardware/graver-controller/docs/parts-power.md`, `parts-mcu.md` |
| Net-by-net capture list | `Hardware/graver-controller/docs/capture-netlist.md` |
| Firmware spec (Accepted) | `docs/adr/0002-firmware.md` |
| PCB layout + production spec (Accepted) | `docs/adr/0003-pcb-layout-and-production.md` |
| Firmware (Rust, embassy-stm32) | `Firmware/graver-controller/` (see its README) |
| Bench rig wiring | `docs/bench-rig.md` |
| Old Arduino design (context only) | `Schematic/`, `Arduino Code/`, `README.md` |

## State of the design

Schematic rev 0.1 is complete, drawn properly (wires, decoupling at pins,
signal flow), ERC 0 violations, every real part has value, footprint and LCSC
number. Since 2026-09-17 it is edited in eeschema (generator retired); U101
uses the HSOP-8 footprint without the library's 0.2 mm thermal vias.

2026-10-01 schematic edits (ADR 0003 Decision 9), ERC 0 and netlist diffed
pad-by-pad against the previous export - every difference was an auto-
generated net *name* following its anchor pin, no connectivity changed:

| ref | was | is now |
|---|---|---|
| J101 | `Connector:Barrel_Jack_Switch` | `Conn_01x02`, pads GND / +24V |
| J201 | Screw terminal symbol, Phoenix footprint | same symbol, `PinHeader_1x04` |
| J401 | `Conn_01x07`, JST XH footprint | same symbol, `PinHeader_1x07` |
| J402 | `Connector_Audio:AudioJack3_SwitchTR` | `Conn_01x04`, pads T / RN / R / S |
| J403 | was `SW401`, `RotaryEncoder_Switch_MP` | `Conn_01x04`, pads A / GND / B / SW |

The five pad rows carry **no LCSC and no MPN property**. They are holes, not
parts; an empty field is dropped when place.py copies fields onto footprints,
which then reads as a schematic-parity mismatch, so the properties are gone
from the symbols rather than blanked. Three orphaned no-connect flags (the
old jack's switch pole, the jack's TN pin, the encoder's MP lugs) were
removed with them.

PCB: re-placed and re-routed on 95 x 70 mm as of 2026-10-01. State:
**0 DRC errors, 0 schematic parity, 3 unconnected pad pairs, 11 warnings**
(1 lib_footprint_mismatch on J301, 4 track_dangling, 6 via_dangling),
126 vias, all placement checks and ADR criteria PASS, all eight per-net
width floors PASS.

The three open pairs, all short same-net gaps, to be closed by hand in
pcbnew and then captured with `place.py --export-manual`:

| net | what |
|---|---|
| +5V | F.Cu track 6.00 mm to F.Cu track 0.07 mm |
| GND | F.Cu track 0.64 mm to F.Cu track 6.71 mm |
| GND | a GND via to an F.Cu track 0.85 mm |

That is the same shape of ending as the 110 x 70 board, which also finished
with three pairs drawn by hand (commit 0b21579).

Two tactile-switch bridges were added to `copper.py` BRIDGES on 2026-10-01
and are what took this from 6 open pairs to 3. SW301 and SW302 are XKB
TS-1187A parts whose four pads are numbered 1, 1, 2, 2: the two halves of
each pair are 6.00 mm apart and joined inside the switch, which KiCad's
connectivity cannot see, exactly like U302's die. On the old board the
router happened to reach both halves; here it did not, and SW302's NRST
pair came out open.

**A trap worth knowing about**, learned the hard way the same day: a bridge
on a Power-class net must carry that net's `.kicad_dru` floor, not `W_SIG`.
A +3V3 bridge drawn at W_SIG (0.25 mm, against a 0.30 mm floor) produced a
single track_width error, and one error is enough for `autoroute.py`'s
import gate to refuse the ENTIRE route - a 6-open board became a 72-open
one until the bridge was removed. The gate is right to do this; just do not
feed it undersized scripted copper.
`graver-controller.kicad_pcb` is GENERATED by the pipeline in `Hardware/graver-controller/tools/pcb/` (README there is the
manual):

    python3 tools/pcb/place.py --copper --silk --route   # ~45 min, --route is the slow part
    python3 tools/pcb/place.py --copper --silk           # ~1 min, no autorouting
    tools/pcb/render.sh                                  # PNGs in output/pcb/
    tools/pcb/routability.sh                             # placement test on a scratch copy

- place.py: board from the netlist (117 parts linked by UUID, parity 0),
  outline, placement as data tables, courtyard / keepout / ADR-distance
  checks with a PASS/FAIL table.
- copper.py: the critical copper, scripted and locked: GND pour and
  stitching, M3 and crystal keepouts, QFN escape fan, decoupling, crystal,
  VDDA, USB pair (37.9/37.9 mm, skew 0, bands on B.Cu), VIN and flyback
  loop at 1.0 mm, buck loops, shunt Kelvin, sense-side ground as one tie
  (checked tree), GATE_IN, I_SENSE, VIN_SENSE, +3V3 and +5V trunks. Prints
  a budgets table.
- silk.py: references off the pads, rear-edge labels, pin-1 marks.
- autoroute.py: KiCadRoutingTools on a SCRATCH COPY, strict, three
  attempts, best imported into the group 'autorouted' after kicad-cli
  grading against the committed .kicad_pro. The router is not
  deterministic: the same input gives 4-17 open pairs between runs.
- manual.py: `place.py --export-manual` keeps tracks drawn by hand in
  pcbnew across regeneration (tools/pcb/manual.json).

### Where this leaves the route (READ THIS)

The 2026-09-19 board was 0 unconnected with the last three pairs (VDDA, PB2,
+5V) hand-drawn in the 'manual' group. **That is all gone**, and deliberately:

- `tools/pcb/manual.json` was **emptied**. Its 38 hand-drawn items were
  absolute coordinates against the old placement; on the re-placed board they
  landed on different parts and shorted /MCU/VDDA to PEDAL_RING.
- **`close_pairs.py` no longer works and must not be trusted.** It is not a
  general pair-closer: it was written against the old board's exact geometry
  and names specific tracks and corridors ("the +3V3 B.Cu track at
  (41.55, 47.8)", "ENC_A's run across the corridor is the wall between PB2's
  escape and R303"). On the 95 x 70 board those tracks do not exist, and a
  `--dry` run ends in `FAIL: nothing ripped for ENC_A`. Whatever closes the
  last pairs now is either another route attempt, hand routing in pcbnew, or
  a rewritten closer - not this script as it stands. Once the pairs are
  closed by hand, `place.py --export-manual` still captures them into
  manual.json correctly; that half of the machinery is fine.
- The autorouter could not run at first: `autoroute.py` defaulted `SCRATCH` to
  one past session's `/tmp` scratchpad, which no longer existed, so it died
  with "KRT_DIR not found". Fixed 2026-10-01 - the default is now
  `~/.cache/graver-pcb`, overridable with `PCB_SCRATCH`, and
  KiCadRoutingTools plus its venv live there. If a future machine has neither,
  re-clone github.com/drandyhaas/KiCadRoutingTools into
  `~/.cache/graver-pcb/routetest/` and make a venv beside it with numpy,
  scipy, shapely and Pillow.
- The router is still nondeterministic (3-10 open pairs between runs), so the
  committed board file remains the artifact: do not regenerate unless
  placement or scripted copper changes.

The old warning that the mop-up re-lays 0.3 mm nets at 0.2 mm looks stale -
`autoroute.py` now runs one pass per width class at that class's `.kicad_dru`
floor and the import gate drops any net carrying undersized copper. Confirm
against the width-floor table before trusting it.
The old "right third of the board is empty" complaint is what the shrink to
95 x 70 answered: the connectors and the encoder were reserving that space,
not the electronics, which fit inside 84.5 x 64.0 mm. Design rules and net
classes live in the .kicad_pro (SaveBoard rewrites it, the scripts restore
it).

3D: only J301 (HRO USB-C) still lacks a model in any KiCad library, and it
needs a manufacturer STEP in a project 3d/ folder before the enclosure
export. SW401 and J402 left this list with the parts themselves; the cover
plate now carries the encoder and the box sockets, so the enclosure model
needs their geometry instead, plus a loom exit for each pad row.

Pad rows all read left to right in ascending pad order, pad 1 leftmost seen
from the front - the old "J201 is rotated 180, so it reverses" rule is gone.
J201: 1 VIN, 2 COIL_NEG, 3 NTC, 4 GND.

Key facts (details in the ADR):

- Coil: both 1335s measure 141 ohm = the 24 V / ~4 W variant. So: 24 V brick
  standard, electronics rated 18-36 V, DC jack rated 30 V (bricks 18-30 V).
  Coil current 0.17-0.26 A; driver scoped to coils >= ~100 ohm.
- MCU: STM32F411CEU6 on board (same chip as the WeAct Blackpill, used for
  firmware bring-up). USB-C for DFU updates, SWD header for development,
  PA10 pull-up so the ROM bootloader picks USB. No LSE crystal.
- Strike: TIM1 one-pulse on PA8 -> UCC27517 gate driver -> IRLR3410 low
  side. 1 ohm shunt -> TLV9062: one half is a x11 amplifier to PA6, the
  other a comparator (~0.77 A trip) into TIM1_BKIN (PB12).
- Flyback: SS110 + SMBJ24A fast decay by default; SI2309 P-FET across the
  TVS gives plain-diode slow decay when PB14 (DECAY_SLOW) is high.
- Power: fuse, DMP6023LE reverse-polarity P-FET, SMBJ36A, 470 uF, LM5164
  buck set to 5.28 V (EN starts ~14 V, BST cap 2.2 nF), two SS14 OR the buck
  and USB VBUS into +5V, AP2112K-3.3 LDO. USB alone runs the logic.
- UI: 1.3" ST7789 240x240 3.3 V module (no CS, SPI mode 3, backlight PWM
  from PB6 through 100 R). It sits in the cover plate on a 7-way loom
  soldered into the J401 pad row: 1 GND, 2 +3V3, 3 SCL, 4 SDA, 5 RES, 6 DC,
  7 BLK, pad 1 leftmost. The encoder (30 detents / 15 pulses, TIM3 encoder
  mode, push on PB7) also mounts in the cover plate and takes 4 wires into
  J403: 1 ENC_A, 2 GND, 3 ENC_B, 4 ENC_SW. The EC11's encoder common and
  switch common are the same net, so they join at the encoder body - run 5
  wires if that bridge is unwanted. The 10k pull-ups R402-R404 and the 10 nF
  debounce C401-C403 stay on the board at the MCU, so the A/B lines leave the
  board at 10k impedance: keep that loom away from the handpiece cable, and
  if it miscounts on the bench drop R402-R404 to 2.2k. Any EC11 now works -
  it is off the JLC BOM, so no footprint has to match it.
- Pedal: no jack on the board. J402 is a 4-pad row - 1 TIP, 2 RN, 3 RING,
  4 SLV - and the socket lives in the box. The circuit is unchanged: ring =
  3V3 through 1k, tip = wiper to PA1, ring sense on PA2, PESD5V0S2BT on tip
  and ring. Detection still depends on a socket whose ring-normal contact
  grounds the ring when nothing is plugged, which is exactly why there are
  four pads and not three. Which socket is an OPEN QUESTION, below.
- Handpiece: 4-pin GX12 aviation socket on the box (pre-wired pigtail), its
  four wires soldered into the J201 pad row: 1 VIN, 2 COIL_NEG, 3 NTC
  (optional), 4 GND, pad 1 leftmost. The 5.08 mm terminal and screw plug are
  gone.
- Power in: J101, two 1.4 mm holes, pad 1 GND and pad 2 +24V, brick leads
  soldered straight in. With no barrel jack the DC-005's 30 V ceiling no
  longer applies, so the 18-36 V electronics rating is the only limit left.
  The pair wants a strain-relief anchor so the solder is not the mechanical
  joint.
- Pin map: in the ADR, verified against the datasheet.

## State of the firmware

Written 2026-09-16, builds clean (release, clippy) for thumbv7em-none-eabihf,
NOT yet run on hardware. Tasks: analog (ADC 200 Hz), input (TIM3 encoder or
three buttons with `--features buttons`), control (modes, menu, safety),
strike (TIM1 one-pulse on PA8, break on PB12 latches), ui (ST7789 via
mipidsi, 10 Hz partial refresh), main (IWDG fed only while control
heartbeats). Settings journal in flash sector 7. Hold the encoder push at
power-up = ROM DFU bootloader. `--features bench` fires a fixed burst at
boot for scoping the strike path.

    cd Firmware/graver-controller
    cargo build --release [--features buttons,bench]
    cargo run --release            # probe-rs + defmt, needs an SWD probe
    tools/dfu.sh                   # USB DFU, no probe

Unverified on hardware: ST7789 offset / colour inversion for the OT3499
module, encoder detent divisor (2 counts per detent for the Alps 30/15),
flash journal, bootloader jump. Jan has no encoder yet (2026-09-16): use
the buttons feature, PB4 up, PB5 down, PB7 push.

## How to work on the schematic

The generator is RETIRED (ADR 0003, 2026-09-17). Edit the .kicad_sch sheets
in eeschema; `tools/build.py` refuses to run because it would overwrite them.

    cd Hardware/graver-controller
    tools/verify.sh                 # must print "Found 0 violations"; PNGs in output/verify/

- Keep the rev 0.1 drawing discipline by hand: wires not labels within a
  block, decoupling at the pins, signal flow left to right.
- Every part keeps value, footprint, LCSC and MPN fields; the JLC BOM is
  exported from them.
- Small field edits (footprint, LCSC) can be made in the file while
  eeschema is closed; verify afterwards.
- Rendering: the kicad MCP's sch_render_png is broken on this machine; use
  `kicad-cli sch export svg` + `rsvg-convert` (verify.sh does this).
- Commits are GPG-signed with a desktop pinentry; they fail when Jan is
  away from the keyboard. Commit while he is present, or unsigned only
  when he says so (2026-09-18 evening's commits are unsigned on his
  instruction). Never `git add -A`.
- Plain ASCII in files. No Claude attribution lines in commits.

## Open items (carry into the next session)

Hardware verification before layout is frozen:

1. Bench test with a 24 V brick: is 24-30 V enough punch? If not, the
   ADR's boost-rail alternative comes back. The OPEN-SMART module Jan has
   tops out at 13.5 V, so use a D4184-class module or the real FET for this.
2. Measure coil inductance (LCR meter or current-rise on a scope). Sizes the
   TVS energy and confirms the 0.5-15 ms pulse range.
3. Part number printed on the solenoids (confirms 24 V variant and duty).
4. OT3499 display: check the real pinout (7-pin, GND VCC SCL SDA RES DC
   BLK expected) and whether BLK idles high on the module.
5. VOID since 2026-10-01. This was the list of THT connector footprints to
   measure against loose parts before layout froze - DC-005 jack, WJ2EDGRC
   terminal drill, NMJ6HCD2 normalling contacts, encoder lug spacing. Every
   one of those parts left the board with ADR 0003 Decision 9, and their
   replacements are stock KiCad pad rows whose only dimension is a drill
   size. Nothing to buy, nothing to measure, no re-spin risk from this.
6. Known, accepted limits: I_SENSE saturates above ~0.3 A (trip uses the
   raw shunt), VIN_SENSE saturates during a surge clamp, comparator
   hysteresis is only ~3 mV, a shorted FET is not caught (coil just runs
   warm at 0.2 A).

Decisions still open (ADR "Open Questions"):

- **Pedal socket (new, 2026-10-01, blocks the loose-parts order).** Jan has
  not decided whether the boxes ship with a bought expression pedal or one he
  builds. A bought one has a moulded 6.35 mm TRS plug, so the box needs a TRS
  socket, and the plug detection of ADR 0001 section 8 keeps working as
  drawn - wire all four J402 pads. A GX12-3 instead means building or
  re-leading the pedals AND redesigning the detection (a pulldown on the
  wiper so an unplugged pedal reads heel-down and cannot fire: fail-safe, but
  it can no longer tell "unplugged" from "pedal at rest"). The board commits
  to neither; four pads serve both.
- **Keep JLC's THT assembly service? (new, 2026-10-01)** After the rework the
  parts needing it are C101 and J302; wire pads are holes with no part. Note
  J301 is not pure SMD either - the HRO TYPE-C-31-M-12 is 16 SMD pads + 4
  PLATED shell tabs + 2 NPTH pegs - so there is through-hole solder on the
  board regardless. It is a standard JLC SMT line item in practice; confirm
  how they bill it at order time. Options: keep the service (default, no
  change), move C101 to an SMD 470 uF and go SMT-only (needs a stock and
  ripple check), or hand-fit C101 on 12 boards (breaks the ADR 0001
  reproducibility rule for a tall electrolytic).
- NTC fitted on all handpieces, or rely on the coil-resistance estimate?
- Default strike ranges (1-60 Hz, 0.5-15 ms, 35 % duty cap) to be confirmed
  on the bench.

## Next steps, in order

1. **Finish the route on the 95 x 70 board.** This is the only thing standing
   between here and an orderable board. The placement, scripted copper and
   silkscreen are done and clean (0 DRC errors, 0 parity); the non-critical
   nets are not routed. Run
   `python3 tools/pcb/place.py --copper --silk --route`, then
   `python3 tools/pcb/close_pairs.py` for whatever pairs are left, then
   `python3 tools/pcb/place.py --export-manual` to capture the hand-drawn
   copper into manual.json. Read "Where this leaves the route" above first -
   manual.json is empty on purpose and the router needs
   `~/.cache/graver-pcb/routetest/` to exist, including the prebuilt
   `grid_router` module that `build_router.py` fetches.
2. **Jan reviews the board in pcbnew.** The old "decide on the empty right
   third" question is answered - the shrink to 95 x 70 took that space back.
   What is worth his eye now: whether the pad rows sit where the looms
   actually want to leave the box, and whether the silkscreen legend is
   readable enough to solder from, since with the keyed connectors gone that
   legend is the only thing preventing a reversed loom.
3. **Answer the two new open questions** (pedal socket, THT service) - the
   first blocks the loose-parts order and the box wall cutout.
4. **Export set**, ADR 0003 step 8: Gerber, drill, BOM with the LCSC column,
   CPL with rotation review, STEP, assembly PDF, per-board test sheet. Not
   scripted yet; `kicad-cli pcb export gerbers / drill / pos` plus a BOM from
   the netlist is the shape of it. The test sheet now needs a loom continuity
   and orientation check as its first line.
5. **JLC order**: 12 assembled, 5 bare. Loose parts are a much shorter list
   than before - display modules, encoders and knobs, GX12 pigtails and
   plugs, hook-up wire, and whatever the pedal question settles on. The XH
   housings, crimp contacts, ribbon leads, screw plugs and the XH crimp tool
   are all out of the project.
6. **Firmware bring-up** on the Blackpill bench rig (docs/bench-rig.md):
   flash, display, buttons/encoder, VIN divider + pot, then the coil at 12 V
   and 24 V from the lab PSU. Fix what the hardware disagrees with.
7. **Enclosure** in FreeCAD from a STEP export of the board. It now carries
   more than before: the encoder and its shaft, the display, the box sockets,
   and a loom exit for each pad row. In exchange all but one of the
   board-to-wall tolerances are gone - the exception is USB-C, still soldered
   to the board and still needing to line up with a hole in the printed rear
   wall. Its mouth direction against the real part is unverified.
