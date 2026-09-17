# Handoff: graver controller board

Last updated 2026-09-17. Read this first in a new session; it says what
exists, what is decided, how to work on it and what comes next.

## What this is

A new controller for the ITS-LZ-1335 solenoid graver in this repo. Batch of
8-10 boxes for a class (adults), each box = 24 V brick + this PCB + 1.3"
ST7789 display + one handpiece + expression pedal. PCB fully assembled by
JLCPCB, no soldering by the builders, under EUR 150 per box, enclosure to be
3D printed (Creality K2 Max).

Upstream project: Savage-Sabrina/DIY_SolenoidGraver (Arduino Nano board);
Jan's fork of it is a separate repo. Since 2026-09-17 this controller lives in
its own repository, github.com/delandtj/stm32-engraver (`origin`), split out
with full history. Branch `master`.

## Where things are

| What | Path |
|---|---|
| Spec / decisions (Accepted) | `docs/adr/0001-graver-controller-board.md` |
| KiCad 10 project | `Hardware/graver-controller/` (root + power/driver/mcu/io sheets) |
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
signal flow), ERC 0 violations, every part has value, footprint and LCSC
number. Since 2026-09-17 it is edited in eeschema (generator retired); the
first edit made J401, the display connector, a JST XH B7B-XH-A header. No
PCB layout yet (the .kicad_pcb is empty).

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
  from PB6 through 100 R). On the production board it sits in the cover
  plate on a 7-way ribbon to the keyed JST XH header J401 (called J3 in
  ADR 0003 and parts-mcu.md). One Alps EC11E15244G1 encoder
  (30 detents / 15 pulses, TIM3 encoder mode, push on PB7).
- Pedal: Neutrik NMJ6HCD2 6.35 mm TRS jack. Ring = 3V3 through 1k, tip =
  wiper to PA1, ring sense on PA2; the jack's ring-normal contact grounds
  the ring when nothing is plugged, so one ADC reading detects "no pedal"
  and "mono plug". PESD5V0S2BT ESD on tip and ring.
- Handpiece: 4-pin GX12 aviation socket on the box (pre-wired pigtail) into a
  4-pin 5.08 mm pluggable terminal: 1 VIN, 2 coil, 3 NTC (optional), 4 GND.
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
  away from the keyboard. Commit while he is present. Never `git add -A`.
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
5. Footprints to check against real parts at layout: J101 DC-005-A200,
   J201 WJ2EDGRC terminal (KiCad drill 1.2 mm, needs 1.5-1.7 mm),
   NMJ6HCD2 normalling contacts (SN assumed a break contact), Bourns/Alps
   encoder lug spacing.
6. Known, accepted limits: I_SENSE saturates above ~0.3 A (trip uses the
   raw shunt), VIN_SENSE saturates during a surge clamp, comparator
   hysteresis is only ~3 mV, a shorted FET is not caught (coil just runs
   warm at 0.2 A).

Decisions still open (ADR "Open Questions"):

- NTC fitted on all handpieces, or rely on the coil-resistance estimate?
- Default strike ranges (1-60 Hz, 0.5-15 ms, 35 % duty cap) to be confirmed
  on the bench.

## Next steps, in order

1. PCB layout and the JLC order: ADR 0003 is the spec (board size, block
   placement, layer use, design rules, export set, first-article checks).
   Its review asks were answered 2026-09-17: cover plate over a hidden
   PCB, board 110 x 70 mm with the pedal jack at the far right of the rear
   edge, bulk cap upright under a dome in the cover, display in the cover
   on a 7-way ribbon, loose THT connectors ordered before layout. It
   starts with ordering those loose parts (list with LCSC numbers in
   parts-mcu.md section 14a). Done 2026-09-17: generator retired, J401
   footprint swapped. Still to do in project prep: project footprints for
   the encoder (12.0 mm lugs), the terminal (1.6 mm drills) and the
   Neutrik (SN pin), mounting holes as symbols, then update the PCB from
   the schematic.
2. JLC BOM + CPL export, order 10 + spares of the display module and
   encoder from single listings.
3. Firmware bring-up on the Blackpill bench rig (docs/bench-rig.md): flash,
   display, buttons/encoder, VIN divider + pot, then the coil at 12 V and
   24 V from the lab PSU. Fix what the hardware disagrees with.
4. Enclosure in FreeCAD next to the existing CAD files, from a STEP export
   of the board.
