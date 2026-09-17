# Bench rig: Blackpill + FET module + coil

Bring-up rig for the firmware before the PCB exists. Uses the pin map of
ADR 0001 unchanged, so the wiring below is also the production wiring minus
the power stage.

## Power

Two independent supplies, ONE common ground.

| Rail | Source | Setting | Notes |
|---|---|---|---|
| Logic 3.3 V / 5 V | Blackpill USB-C from the PC | - | needed for DFU anyway |
| Coil 24 V | Lab PSU channel 1 | 24.0 V, current limit 0.30 A | coil draws 0.17 A at 24 V (141 ohm) |
| (optional) | Lab PSU channel 2 | 12-13.5 V | only if using the OPEN-SMART module, which is limited to 13.5 V |

- Tie PSU channel 1 negative to a Blackpill GND pin. Without that the gate
  signal has no reference and nothing switches cleanly.
- Do not feed 5 V from the PSU into the Blackpill while USB is plugged in.
- Set the CC limit before connecting the coil. If the FET shorts, 0.3 A into
  141 ohm cannot hurt anything; the limit protects the wiring on the bench.

## Solenoid + FET (low side, like the PCB)

    +24 V (PSU ch1 +) ----+---------------- coil ----+---- FET drain (module OUT-)
                          |                          |
                          +-- 1N4007 cathode (band)  +-- 1N4007 anode
    GND (PSU ch1 -) --------- FET source / module DC- --- Blackpill GND

- The 1N4007 goes directly across the coil, band towards +24 V. Do not
  assume the module has one. Diode-only flyback = the ADR's "slow decay";
  fine for timing, feel and UI, not for judging fast decay.
- Gate / signal input of the module <- PA8 (TIM1_CH1). Module signal GND <-
  Blackpill GND.

Module choice:

| Module | Load supply | Use for |
|---|---|---|
| OPEN-SMART single MOSFET (3.3 V logic OK) | 13.5 V max | timing, UI, scope of the pulse; hits are ~1/4 force |
| D4184 dual-MOSFET trigger module | 5-36 V | the real 24 V punch test |
| Bare logic-level N-FET (IRLZ44N, IRL540, IRLB8721) | any | best: gate <- PA8 through 100 R, 100k gate to GND, source to GND, drain to coil |

EG27324 + M3004D module (the one on the bench, 2026-09-16): the M3004D is a
30 V FET, so 12-13.5 V only, never 24 V. It has its own flyback diode
(RS3M), no 1N4007 needed.

| Module terminal | Goes to |
|---|---|
| J1 SIG | Blackpill A8 |
| J1 VCC | Blackpill 5V pin (the driver runs on 5 V, NOT 12 V, NOT 3V3) |
| J1 GND | Blackpill G |
| J2 POWER + / - | lab PSU 12 V / PSU negative (also to Blackpill G) |
| J3 LOAD | coil, either way round |

Wiring picture (photo orientation of the module: terminals at the top,
J1 header at the bottom reading GND VCC SIG from left to right):

                  lab PSU  12.0 V, limit 50 mA, later 0.3 A
                  (output FLOATING: no link between - and earth)
                      +                          -
                      |                          |
                      |      +---------------+   |
                      +------| POWER +       |   |
                      |      |        MODULE |   |
        100k          |      | POWER - ------+---+------------+
    B0 --/\/\/--------+      |               |                |
    |                        | LOAD  --------+--- coil ---+   |
   10k                       |               |            |   |
    |                        | LOAD  --------+------------+   |
    G                        |               |                |
                             | J1  GND VCC SIG               |
                             +------+---+---+-+               |
                                    |   |   |                 |
                                    |   |   +---- A8  strike  |
                                    |   +-------- 5V  driver  |
                                    +------------ G           |
                                                  |           |
                                     BLACKPILL    G  <--------+
                                              one common ground

Only two things ever touch the supply's +: the module's POWER + screw and
the 100k of the VIN divider. The supply's - goes to POWER - and from there
to Blackpill G. Nothing from the supply goes to 3V3 or 5V.

## Bring-up sequence (learned the hard way: one wrong wire on the module
## killed a Blackpill and an ST-Link on 2026-09-16)

1. Wire everything with the PSU off and the Blackpill unpowered.
2. Meter, continuity: PSU + must reach only the module POWER +, the coil
   side of the module, and the 100k of the VIN divider. Not 5V, not 3V3,
   not any signal pin. PSU - must beep to Blackpill G.
3. Never connect the ST-Link's 3V3 wire. SWDIO, SWCLK, GND only: a rail
   fault then cannot reach the probe.
4. PSU current limit at 50 mA, voltage up slowly. If it drops into
   current limit before the set voltage, stop and find the short.
5. Only then raise the limit to 0.3 A and plug the Blackpill's USB in.

With a bare FET, add a 1 ohm 1 W resistor between source and GND and scope
across it: the current rise gives the coil inductance (tau = L / R_total,
R_total = 141 + 1 ohm). That closes handoff open item 2. Tie PA6 to the
FET side of that resistor if you want the firmware to log current (1 ohm,
gain 1: 0.17 A reads 0.17 V, coarse but usable).

## VIN sense (required, or the firmware refuses to fire)

The firmware refuses to fire below 15 V measured on PB0. Build the PCB's
divider on the breadboard:

    +24 V ---- 100k ----+---- PB0
                        |
                       8.2k     (+ optional 100 nF to GND)
                        |
                       GND

24 V reads 1.82 V at PB0; the 3.3 V ADC saturates at 43.5 V.

No 8.2k at hand: use 10k and build with `--features vin-div-10k` (24 V reads
2.18 V, saturates at 36 V). The firmware's default constants are the board's
100k / 8.2k.

Testing at 12 V (the 30 V-rated M3004D module): build with
`--features low-vin`, which lowers the lockout to 10 V. Supply compensation
then doubles the on-time to keep the volt-seconds of a 24 V brick; switch
it off in the menu when you want the raw pulse length on the scope.

## Display (OT3499, 1.3" ST7789 240x240, 3.3 V, 7 pins, no CS)

| Module pin | Blackpill | Function |
|---|---|---|
| GND | GND | |
| VCC | 3V3 | 3.3 V only |
| SCL | PA5 | SPI1_SCK |
| SDA | PA7 | SPI1_MOSI |
| RES | PB15 | reset |
| DC | PB10 | data/command |
| BLK | PB6 | backlight PWM (TIM4_CH1) |

Handoff open item 4: read the silkscreen on the real module and confirm the
order before wiring; some 7-pin variants swap RES/DC. If BLK idles high on
the module (backlight on with the pin floating), PB6 still works.

## Encoder (Alps EC11 or similar, 3 + 2 pins)

| Encoder pin | Blackpill |
|---|---|
| A | PB4 |
| C (middle of the 3) | GND |
| B | PB5 |
| switch 1 | PB7 |
| switch 2 | GND |

Internal pull-ups are enabled in firmware. Optional: 100 nF from A and from
B to GND for cleaner counting.

No encoder yet: build with `--features buttons` and wire three tactile
buttons to GND on the same pins, nothing gets rewired later.

| Button | Blackpill | Function |
|---|---|---|
| up | PB4 | one detent up, auto-repeats when held |
| down | PB5 | one detent down, auto-repeats when held |
| push | PB7 | short press = mode, long press = menu |

## Pedal

Real expression pedal (6.35 mm TRS, e.g. M-Audio EX-P) through a TRS jack or
a cut-off cable:

| TRS | Blackpill |
|---|---|
| tip (wiper) | PA1 |
| ring | 3V3 through 1k, and PA2 through 1k |
| sleeve | GND |

No pedal yet: a 10k pot does the same job. Ends to 3V3 and GND, wiper to
PA1, and PA2 tied to 3V3 through 1k so the firmware sees "pedal present".
A bench jack without the normalling contact cannot report "unplugged"; only
the Neutrik NMJ6HCD2 on the PCB does that.

## Leave alone

- PB12 (TIM1_BKIN): unconnected; firmware pulls it down so the bench never
  trips. PB14 (DECAY_SLOW): unconnected on the bench.
- PA10: floating (DFU strap on the PCB). PA0: Blackpill KEY button, unused.
- PA11/PA12: USB, PA13/PA14: SWD.

## Flashing and logs

DFU over the Blackpill's USB-C, no probe needed: hold BOOT0, press and
release NRST, release BOOT0; `dfu-util -l` must list "STM32 BOOTLOADER".
Then `dfu-util -a 0 -s 0x08000000:leave -D firmware.bin`.

defmt logs need a debug probe (ST-Link V2 clone or a DAPLink) on the 4-pin
SWD header: SWDIO, SWCLK, GND, 3V3 (3V3 only as sense on an ST-Link, do not
power the board from it while USB is plugged). `probe-rs run` flashes and
streams logs. probe-rs on this machine currently warns about udev
permissions: install the `stlink` package (ships the udev rules) or add a
rule for the probe's VID:PID, then replug.

## Test order

1. Blackpill on USB, nothing else: LED blinks, defmt (if probe) shows boot.
2. Display + encoder: UI up, knob changes values, short/long press works.
3. VIN divider + pot: status goes from LOW VIN / PEDAL? to READY.
4. FET module + coil at 12 V (OPEN-SMART) or 24 V (D4184 / bare FET), CC
   limit 0.3 A: first the `bench` feature's fixed-pulse test with the scope
   on the gate and on the shunt, then pedal-driven strikes.
5. Punch judgement at 24 V, then 28-30 V, vs the old Arduino board.
