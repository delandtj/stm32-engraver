# Graver controller - bring-up and test checklist

For the ADR 0005 board (4-layer, 85 x 60 mm, JLC assembled). Part A runs on
every bare board before any loom is soldered. Part B runs on every finished
box. Part C is done once, on the first board, and answers the open hardware
questions in HANDOFF.md.

Write a serial number (1-12) on each board's silk with a marker before you
start, and keep one results sheet per batch (grid at the end).

Stop rule: any step that fails stops that board. Do not continue "to see what
else happens"; the later steps put more energy in.

## Reference values

| What | Expected | Source |
|---|---|---|
| Brick input | 18-30 V (TVS D102 SMBJ36A) | ADR 0001 |
| Buck U101 start | about 14 V on VIN (EN divider R105/R106) | parts-power.md |
| +5V on brick | 4.93-4.95 V (5.28 V buck minus D105) | parts-power.md |
| +5V on USB only | 4.4-4.6 V (VBUS through D103) | parts-power.md |
| +3V3 | 3.30 V (U102 AP2112K) | |
| VIN_SENSE | VIN x 0.0758 (R102 100k / R103 8.2k) on PB0 | |
| OC trip | about 0.77 A through R204 1R (OC_REF 0.767 V) | |
| Coil | about 141 ohm, about 170 mA steady at 24 V | ADR 0001 |
| NTC | 10k at 25 C, B 3950 | |
| D104 green | on whenever +3V3 is up | |
| D301 red | PC13, active low; status LED | |
| Idle current | NOT KNOWN - record board 1 and use it as the reference | |

Note: U101 does not start below about 14 V, so the first power-up is at 20 V,
not 12 V.

## Part A - every board, no looms

### A1 Visual (loupe)

- [ ] U301 QFN48: no bridges, no tombstoned decoupling caps around it
- [ ] J301 USB-C: 16 SMD pins without bridges, 4 shell tabs soldered through
- [ ] C101 470 uF is fitted, + to VIN (polarity stripe = pin 2 = GND)
- [ ] J302 SWD header is fitted (it was a THT line item)
- [ ] D102, D202 (TVS), D101, D203 (zener), D103, D105, D201: band matches silk
- [ ] Q101, Q201, U101 (HSOP-8, exposed pad), U201, U202 seated, pin 1 correct
- [ ] Y301 crystal, F101 fuse present
- [ ] No solder balls or flux bridges across the wire pad rows

### A2 Resistance, unpowered (meter on ohms, black lead on GND)

Record the value. "Not a short" means well above 100 ohm after any cap has
charged; compare against the other boards, outliers are the finding.

- [ ] J101 pad 2 (+) to GND: not a short (reads through F101/Q101, open-ish)
- [ ] VIN (J201 pad 1) to GND: not a short, slowly rising as C101 charges
- [ ] +5V (top of C at U102 input) to GND: not a short
- [ ] +3V3 (J302 pad 1) to GND: not a short
- [ ] COIL_NEG (J201 pad 2) to GND: not a short (Q201 off)
- [ ] VBUS (J301 shell side, VBUS pin or D103 anode) to GND: not a short

### A3 First power from the lab PSU (no USB, no looms)

PSU on J101 (pad 1 G, pad 2 +). Set 20 V, current limit 100 mA.

- [ ] Inrush: PSU may sit in CC briefly while C101 charges, then drops out of CC
- [ ] Idle current at 20 V: ____ mA (board 1 sets the reference; others within about 20 %)
- [ ] D104 green on
- [ ] +5V: ____ V (4.93-4.95)
- [ ] +3V3: ____ V (3.25-3.35)
- [ ] VDDA (after FB301): same as +3V3
- [ ] Nothing warm after 1 minute (finger on U101, U102, Q101, Q201)
- [ ] Raise to 24 V, then 30 V: idle current about the same or lower, rails unchanged
- [ ] Gate stays low: COIL_NEG (J201 pad 2) has no path to GND - with a 10k
      resistor from VIN to COIL_NEG, COIL_NEG reads about VIN (FET off)

### A4 USB and flashing (PSU off, USB only)

A blank F411 does not start its bootloader by itself, so use the buttons.
They have no silk legend. Component side up, USB-C edge away from you:
the button next to J301 is SW302 RESET, the one further left is SW301
BOOT0 (J302 SWD sits below, between them).

- [ ] Plug USB-C: D104 on, +3V3 present, +5V about 4.4-4.6 V
- [ ] Hold SW301 BOOT0, tap SW302 RESET, release BOOT0
- [ ] `lsusb` shows 0483:df11 STM DFU (D+/D- pair works, CC resistors work)
- [ ] Flip the USB-C plug over and repeat (both CC paths)
- [ ] Flash: `Firmware/graver-controller/tools/dfu.sh` completes and the board restarts
- [ ] After the restart, D301 shows the firmware status pattern (note it on board 1)
- [ ] With SW301 not pressed, a RESET restarts the firmware, not DFU

### A5 SWD (only needed when DFU fails, or for logging)

PSU off; on the bench rig SWD failed through a shared coil-supply ground.

- [ ] J302: 1 3V3, 2 SWDIO, 3 SWCLK, 4 NRST, 5 GND
- [ ] `probe-rs info` finds STM32F411CEUx
- [ ] `cargo run --release` flashes and shows defmt logs

### A6 Function with a test harness (not soldered)

Make one harness: display module, encoder, pedal and a handpiece on 2.54 mm
male headers that are pushed into the pad rows (tilt them so they hold by
friction). J101 is 5.4 mm pitch; use clip leads there.

- [ ] Display lights, shows the start screen (backlight PB6, ST7789 on SPI1)
- [ ] Encoder A/B changes the value both ways, push works
- [ ] Holding the encoder push at power-up enters DFU (lsusb 0483:df11)
- [ ] Pedal: heel reads at rest, full travel reads full, smooth in between
- [ ] VIN shown on screen matches the PSU within 0.5 V at 24 V
- [ ] Below 15 V VIN the status bar shows the VIN block (sweep the PSU down to 16 V and 14.5 V)
- [ ] NTC: shows about room temperature with the handpiece NTC fitted
- [ ] Unplug the pedal: the status bar shows a block reason, no firing
      (see the "pedal unplug" finding in C5 before trusting this)
- [ ] Fire at 24 V, PSU limit 500 mA: handpiece strikes, rate follows the pedal
- [ ] Release the pedal: strikes stop immediately

## Part B - every finished box, after the looms

### B1 Loom continuity, box unpowered, no brick plugged

Reversed handpiece loom = 24 V on the NTC input; reversed display loom =
+3V3 on GND. These are the two that kill boards.

- [ ] J101: brick socket centre (+) to pad 2 "+", sleeve to pad 1 "G"
- [ ] J201: pad 1 VI to pad 2 CN about 141 ohm (the coil)
- [ ] J201: pad 3 NT to pad 4 G about 10k at room temperature (the NTC)
- [ ] J201: pad 1 to pad 3 open (coil and NTC are not shorted inside the handpiece)
- [ ] J401: pad 1 G to display GND pin, pad 2 3V to display VCC pin
- [ ] J401: pads 3-7 to SCL, SDA, RES, DC, BLK in that order (check the module's own legend; some swap RES/DC)
- [ ] J403: A, G, B, SW to the encoder lugs; push shorts SW to G
- [ ] J402: per the pedal table in HANDOFF.md; pad 2 RN unwired
- [ ] No pad shorted to its neighbour on any row

### B2 Power-up

- [ ] Brick plugged, no pedal: D104 on, display on, status bar shows a block reason
- [ ] Pedal plugged, heel down: status reads ready
- [ ] Light pedal press: strikes; full press: fastest rate; release: stops
- [ ] Unplug the pedal mid-session with the foot off: nothing fires
- [ ] 2 minutes at a working setting: handpiece warm, not hot; displayed temperature rises plausibly
- [ ] Settings survive a power cycle

## Part C - first board only

- [ ] C1 USB-C mouth direction against the real J301 part, for the enclosure opening
- [ ] C2 OT3499 module: real pin order, does BLK idle high on the module
- [ ] C3 Scope COIL_NEG during a strike at 24 V: peak below about 65 V
      (VIN + D202 clamp), Q201 is a 100 V part
- [ ] C4 OC trip: 27 ohm 10 W resistor in place of the coil at 24 V (about
      0.9 A), `--features bench` (20 x 3 ms): PB12 OC_TRIP goes high, pulses
      are cut, "overcurrent" latched on the screen, clears on pedal release
- [ ] C5 Pedal unplug: with the box socket wired per HANDOFF.md (100k TIP to
      SLV at the socket), unplug the pedal and measure J402 pad 1 TIP. R407
      on the board is a 100k pull-up to +3V3, so this reads about 1.65 V, not
      0 V, and ring stays at 3V3 so the firmware still thinks the pedal is
      present. Expected to FAIL until the pedal wiring is changed.
- [ ] C6 Reverse polarity: PSU reversed on J101, 20 V, 50 mA limit, 2 s: no
      current, board fine afterwards (Q101)
- [ ] C7 Measure coil inductance (current rise on the scope across R204)
- [ ] C8 Part number printed on the solenoid
- [ ] C9 Default strike ranges (1-60 Hz, 0.5-15 ms, 35 % duty cap) feel right

## Results grid

Mark P (pass), F (fail) or the measured value.

| Step | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 visual | | | | | | | | | | | | |
| A2 shorts | | | | | | | | | | | | |
| A3 idle mA @20V | | | | | | | | | | | | |
| A3 +5V | | | | | | | | | | | | |
| A3 +3V3 | | | | | | | | | | | | |
| A3 gate off | | | | | | | | | | | | |
| A4 DFU both ways | | | | | | | | | | | | |
| A4 flashed | | | | | | | | | | | | |
| A6 display | | | | | | | | | | | | |
| A6 encoder | | | | | | | | | | | | |
| A6 pedal | | | | | | | | | | | | |
| A6 VIN reading | | | | | | | | | | | | |
| A6 NTC | | | | | | | | | | | | |
| A6 fires | | | | | | | | | | | | |
| B1 looms | | | | | | | | | | | | |
| B2 box | | | | | | | | | | | | |
