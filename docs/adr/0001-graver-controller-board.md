# 0001 - Graver Controller Board (STM32 + TFT, class batch)

**Status**: Accepted
**Date**: 2026-09-13
**Updated**: 2026-09-13 (coil measured at 141 ohm: power stage re-rated for a 24 V system;
review asks 1-4 all answered yes, schematic capture started)

---

## Context

The existing controller (Custom Board V2, EasyEDA, `Schematic/Custom Board V2/`) is an
Arduino Nano carrier with a separate button/pot panel. It works, but:

- IRL520 MOSFET driven directly from a Nano pin, no gate driver.
- 1N4004F (1 A, SMAF) in series with the supply as reverse-polarity protection; lossy and
  marginal.
- Plain-diode flyback: slowest possible coil turn-off, plunger stays energized after the
  pulse, limits usable strike rate and crispness.
- L7805 linear regulator from up to 24 V.
- Strike timing by `millis()` polling: 1 ms resolution, loop jitter.
- Wiring between two boards, panel parts and jacks is hand work.

New goal: a batch of **8-10 complete units** for a class of adult students. Each unit is one
box: external power brick + controller PCB + display + one 1335-solenoid handpiece + pedal.

Constraints:

- PCB fully assembled by a Chinese fab (JLCPCB-class SMT + THT). **No soldering by the
  builders**, no loose internal wiring except one pre-wired connector pigtail.
- Budget below **EUR 150 per complete unit** (board, display, pedal, brick, box, handpiece).
- Enclosure 3D printed (Creality K2 Max available).
- Firmware in Rust (embassy), developed first on a dev board before the PCB exists.
- **Solenoid**: ITS-LZ-1335, coil measured at **141 ohm DC**. That matches a 24 V coil of
  about 4 W continuous (24^2 / 141 = 4.1 W). A 12 V coil of the same power would be about
  36 ohm. Consequences:
  - At 12 V this coil draws only 85 mA (1 W), about a quarter of its rated force. A 12 V
    brick is not an option.
  - At 24 V it draws 170 mA; at 36 V, 255 mA. Currents are well under 1 A, so the power
    stage is small parts, not a high-current design.

---

## Decision

Build a single-board controller around an **on-board STM32F411CEU6**, the same chip as the
WeAct "Blackpill" dev board, so firmware developed on the Blackpill runs unmodified on the
production board. Every user-facing part (display, encoder, all jacks) is mounted on
this one PCB; the box is only a shell with holes.

Key elements:

1. **Power**: standard **24 V** barrel-jack brick. The electronics are rated **18-36 V**;
   the DC jack limits supported bricks to **18-30 V**. A 28-30 V brick can overdrive the
   coil for harder hits, and a 19-20 V laptop brick still works (weaker). Fuse, reverse-polarity P-FET, input TVS, bulk capacitance, buck to 5 V, LDO to
   3.3 V.
2. **Solenoid driver**: low-side 100 V logic-level N-MOSFET with a gate driver,
   hardware-timed pulses from TIM1 one-pulse mode, low-side current shunt with amplifier to
   the ADC and a hardware overcurrent comparator into TIM1_BKIN.
3. **Flyback**: fast decay through a diode + TVS clamp, with a firmware-controlled P-FET
   bypass for slow (diode-only) decay. Default: fast.
4. **UI**: 1.3" ST7789 240x240 SPI IPS module (3.3 V) and a single EC11 rotary encoder
   with push switch. No pot, no separate buttons.
5. **Pedal**: 6.35 mm stereo (TRS) jack for a standard musician's expression pedal
   (recommended: M-Audio EX-P).
6. **Handpiece**: 4-pin GX12 aviation connector on the box, pre-wired pigtail into a
   pluggable screw terminal on the PCB. Pins 1-2 coil, pins 3-4 optional NTC.
7. **Control model**: two modes, toggled by a short press of the encoder:
   - **Mode F**: pedal = strike frequency, knob = strength.
   - **Mode S**: pedal = strength, knob = strike frequency.
   "Strength" = energy per strike = coil on-time per pulse (see Firmware behaviour).
8. **Programming**: USB-C for DFU firmware updates (no probe needed), SWD header for
   development.

---

## Architecture Overview

```
  24 V brick            +-----------------------------------------------------------+
  5.5x2.1 -->[DC jack]--+--[fuse]--[rev-pol PFET]--+--[bulk C]--+-- VIN (18-36 V)     |
                        |                          |            |                   |
                        |                      [TVS in]    [buck 5V]--[LDO 3V3]      |
                        |                                       |        |          |
  USB-C (DFU) ---------[ESD]--[OR into 5V]----------------------+        |          |
                        |                                                |          |
                        |   STM32F411CEU6 <------------------------------+          |
                        |    TIM1_CH1 --> [gate driver] --> [N-FET] ---+            |
                        |    TIM1_BKIN <-- [comparator] <--+           |            |
                        |    ADC <-- [shunt amp] <---------+--[shunt]--+ (source)   |
                        |    ADC <-- pedal wiper / ring sense                        |
                        |    ADC <-- VIN divider, NTC                                |
                        |    SPI1 --> ST7789 TFT header                              |
                        |    TIM3 encoder <-- EC11 A/B, GPIO <-- EC11 push           |
                        |    GPIO --> decay-mode PFET                                |
                        |                                                            |
  GX12 pigtail -->[4-pin terminal]: COIL+ = VIN, COIL- = FET drain, NTC, NTC-GND     |
  Expression pedal --> [6.35 mm TRS jack]                                            |
                        +-----------------------------------------------------------+
```

### Component Breakdown

Parts named below are candidates that meet the spec; final picks happen at schematic time
against JLC stock (basic parts preferred).

#### 1. Power input

- **Connector**: PCB-mount 5.5 x 2.1 mm DC jack, centre positive, rated >= 2 A, on the rear
  board edge.
- **Brick**: 24 V, >= 1 A, certified (e.g. Mean Well GST25E24 class). Coil draw is
  ~0.2-0.3 A peak plus ~1-2 W of logic and display.
- **Fuse**: SMD slow-blow 1 A (1206/1812 class).
- **Reverse polarity**: P-channel MOSFET in the positive rail (-60 V, >= 2 A class), gate to
  GND via resistor, 12-15 V zener gate-source clamp. (It does not limit inrush: the body
  diode conducts before the gate turns on. With ~500 uF of bulk that is acceptable.)
- **Input TVS**: SMBJ36A class (standoff 36 V, clamp ~58 V at rated pulse current).
- **Bulk capacitance**: >= 470 uF, 63 V, low-ESR electrolytic, plus ceramics at the driver.
- **Operating range**: 18-36 V for the electronics, but the DC jack (DC-005 class) is rated
  30 V, so supported bricks are 18-30 V. A 36 V brick needs a higher-rated input
  connector. Below 18 V the firmware warns (weak hits); below 15 V it refuses to fire.
- **VIN sense**: divider to ADC, used for display and strike-energy compensation.

#### 2. Logic rails

- **5 V buck**: LM5164 (100 V, 1 A synchronous, SO-8 PowerPAD), set to 5.28 V so the rail
  is ~4.95 V after the ORing Schottky. EN divider starts it at ~14 V. Feeds the gate driver
  and the LDO.
- **3.3 V LDO**: AP2112K-3.3 (600 mA, ~0.25 V dropout). Dropout must stay <= 0.5 V so the
  board still runs from USB alone (~4.6 V after the Schottky). Feeds MCU, VDDA, display,
  encoder pull-ups, pedal, op-amp.
- **USB power path**: two Schottkys ORing buck output and USB VBUS into +5V: no backfeed
  into the buck, no brick voltage on VBUS. The board can be flashed and configured from a
  laptop without the brick. The gate driver may sit in UVLO on USB power alone, which is
  fine: firmware refuses to fire when VIN is below 15 V, which includes "no brick".

#### 3. MCU

- **STM32F411CEU6** (UFQFPN48), 25 MHz HSE crystal (10 pF load, 12 pF caps), same
  frequency as the Blackpill, so clock config is identical. No LSE crystal: nothing uses
  the RTC. PA10 gets a 10k pull-up so the ROM bootloader reliably picks USB DFU.
- **Programming**:
  - USB-C (data) to OTG_FS on PA11/PA12, USBLC6-2 ESD. DFU via the ROM bootloader.
  - BOOT0 and NRST tactile buttons on the board, reachable through small holes in the box.
  - Firmware also offers "hold the encoder pushed at power-up -> jump to bootloader" so
    the BOOT0 button is only a recovery path.
  - SWD 2.54 mm header (SWDIO, SWCLK, NRST, 3V3, GND) for development with probe-rs.
- **Status LED** on PC13, active low, matching the Blackpill LED.
- **Fallback part**: STM32F401CCU6 is pin compatible and cheaper; the firmware must not
  depend on F411-only features beyond clock speed.

#### 4. Solenoid driver

Sized for a 141 ohm coil at up to 36 V (255 mA steady). Supported coil range: >= ~100 ohm
(0.36 A at 36 V). Lower-resistance coils need a different shunt, fuse and trip threshold.

- **MOSFET**: logic-level N-channel, **Vds >= 100 V** (the flyback clamp stacks on top of
  VIN), >= 2 A, Rds(on) <= 0.3 ohm at Vgs = 4.5 V, SOT-223 or DPAK.
- **Gate driver**: single-channel low-side driver powered from 5 V (UCC27517 class), input
  from TIM1_CH1 (3.3 V logic), series gate resistor, 100k gate pulldown so the FET stays off
  during reset and while the MCU is unprogrammed.
- **Current sense**: 1 ohm 1206 shunt from FET source to power ground, Kelvin-routed to a
  rail-to-rail op-amp (gain ~10, so 0.26 A -> 2.6 V). Output to an ADC pin (PA6) for
  measurement and to the second op-amp half used as a comparator.
- **Overcurrent trip**: comparator threshold set by divider at ~0.8 A (3x the normal peak,
  well below the 1 A fuse), output to TIM1_BKIN. A shorted handpiece cable is cut by the
  timer hardware within one clock, independent of firmware.
- **Why hardware pulses**: TIM1 in one-pulse mode generates each strike with microsecond
  resolution and ends it even if firmware stalls. Firmware only arms the next strike.

#### 5. Flyback and decay mode

- **Fast decay (default)**: fast diode (1 A, >= 100 V Schottky or ES1-class, anode at drain)
  in series with a unidirectional TVS (SMBJ24A class, anode at VIN) from drain back to VIN.
  The coil sees about -28 V at turn-off instead of -0.7 V, so current collapses many times
  faster.
- **Slow decay (selectable)**: a P-FET (-60 V, SOT-23) across the TVS (source at the
  diode/TVS node, drain at VIN), gate pulled to source by a resistor, pulled down through a
  small N-FET level shifter with a zener Vgs clamp. MCU GPIO on = TVS shorted = classic
  diode flyback. The level shifter's drain sees VIN + clamp, so it is a 100 V part
  (BSS123), not a 60 V 2N7002.
- **Drain voltage budget**: VIN_max (36 V) + clamp (~30 V at working current) + diode
  = ~67 V, under 80% of the 100 V MOSFET rating. During an input surge while the input TVS
  is clamping (~58 V) the drain can briefly reach 86-97 V: still inside the 100 V rating,
  accepted as a transient-only exception to the 80% derating.
- **Energy budget**: at fast decay, the coil's stored energy (0.5 * L * I^2 per strike) is
  dumped in the TVS. With these currents it is small (e.g. L = 100 mH at 0.26 A = 3.4 mJ,
  0.2 W at 60 Hz), well inside an SMB package. Re-check once L is measured.

#### 6. Display

- **Module**: 1.3" ST7789 240x240 IPS SPI module, 3.3 V (OT3499 listing, about EUR 6.25).
  Most modules of this type have a 7-pin header (GND, VCC, SCL, SDA, RES, DC, BLK) and
  **no CS pin**. The controller is then permanently selected and must be driven in
  **SPI mode 3**. The pinout is verified on the actual module before the footprint is
  drawn.
- **Mounting**: PCB carries a matching female header (fab-assembled). These modules often
  have no mounting holes, so the printed enclosure bezel holds the glass edge down and the
  header takes the rest.
- **Sourcing**: one listing, **all units plus spares bought at once**, because pinout and
  outline vary between sellers.
- **Backlight**: PWM (TIM4) on the module's BLK pin through a 100 ohm series resistor.
  Common 1.3" modules switch the backlight with their own transistor on BLK, so no
  external FET is needed.
- **Bus**: SPI1 at up to 48 MHz with DMA, MOSI only (no MISO). SPI1 carries nothing else,
  because the module has no CS. The header is 1x7: 8-pin variants put CS between DC and
  BLK, so a 1x8 footprint would not line up anyway.

#### 7. Front-panel control

- **Encoder**: Alps EC11E15244G1, EC11-type with push switch, PCB-mount THT, **30 detents /
  15 pulses per revolution**, 6 mm shaft, fits the stock KiCad EC11E footprint. Rule: the
  detent count equals the pulse count or twice it, and the firmware divisor matches (here:
  one step per half quadrature cycle). No 20/20 part is stocked at LCSC.
- **Debounce**: 10k pull-ups plus 10 nF to GND on A and B, read by TIM3 in hardware
  encoder mode, so no counts are lost while the CPU is busy with the display. The push
  switch gets the same RC and a firmware debounce.
- **Knob**: 3D-printed or off-the-shelf aluminium knob for a 6 mm shaft.
- **Why no pot**: the display shows the value, so the knob's absolute position adds
  nothing. The last values are stored in flash and restored at power-up.

#### 8. Pedal input

An "expression pedal" is a potentiometer in a rocking foot pedal, connected with a
6.35 mm stereo (TRS) guitar-style plug. Pinout conventions differ by brand; the M-Audio
EX-P has a polarity switch and is the recommended pedal.

- **Jack**: Neutrik NMJ6HCD2, PCB-mount 6.35 mm stereo jack with tip, ring and sleeve
  normalling contacts, rear edge.
- **Wiring**: ring = 3.3 V through a 1k series resistor (a mono plug shorts ring to
  sleeve; the resistor makes that harmless), tip = wiper to ADC through RC filter,
  sleeve = GND. The ring-normal contact goes to GND.
- **Ring sense = plug detect**: with no plug, the ring-normal contact grounds the ring
  node; a mono plug does the same. An expression pedal lifts it to ~3 V (1k against the
  pedal pot). So one ADC reading tells "expression pedal present" apart from "nothing or
  mono plug". No separate detect GPIO.
- **Tip pull-up** (100k to 3.3 V) so a simple on/off footswitch on a mono plug also works
  as a fallback (nice to have).
- **ESD**: low-capacitance TVS array on tip and ring (PESD5V0S2BT).

#### 9. Handpiece connector

A GX12 is a small round metal "aviation" connector with a screw collar: cheap, locking,
and not confusable with the power plug.

- **Box side**: 4-pin GX12 female panel socket, bought as a **pre-wired pigtail** (no
  soldering), wires into a 4-pin 5.08 mm pluggable screw terminal on the PCB.
- **Pinout**: 1 = COIL+ (VIN), 2 = COIL- (drain), 3 = NTC, 4 = NTC return (GND).
- **Handpiece side**: GX12 4-pin male on a 2-core (+2 optional) cable to the 1335. The
  flyback lives on the board; the handpiece is just coil (+ optional NTC).
- **NTC**: optional 10k NTC glued to the solenoid body; firmware uses it when present and
  falls back to a duty-based thermal model when absent (pin 3 reads open).
- **Coil check**: at power-up and plug-in, firmware fires a sub-threshold test pulse and
  reads the current slope and plateau. That detects an open handpiece and estimates coil R
  (a ~0.4%/degC copper tempco also gives a temperature estimate without an NTC).
- **Handpiece cable** (decided 2026-09-16): 4-core on every handpiece, even without an
  NTC, so any handpiece fits any box and the NTC can be added later. Fine-stranded
  0.14-0.25 mm2 (26-24 AWG) per conductor, soft jacket (silicone 4-core preferred, LiYY
  4x0.14 acceptable), outer diameter 3.5-5 mm so the GX12 cable clamp grips it, 1.2-1.5 m,
  unshielded. Current is <= 0.26 A and the flyback clamp puts about 60 V peak on the coil
  wires, so flexibility and bend life decide the cable, not current or voltage. A shielded
  cable, if used anyway, has its shield on pin 4 at the plug end only. No coiled cord: its
  retraction force tugs a light handpiece.
- **Colour code** (same on all handpieces and pigtails): pin 1 COIL+ red, pin 2 COIL-
  black, pin 3 NTC white, pin 4 NTC return green. The coil pair and the NTC pair are each
  one adjacent pair in the cable.
- **Handpiece-side attachment** (strain relief, how the cable enters the printed body) is
  not decided; it is worked out by iteration on the first handpieces.

#### 10. Mechanical / enclosure interface

- The PCB forms the **top face** of a 3D-printed desk console (the box may tilt the board
  toward the user). Display and encoder on top; DC jack, pedal jack and the GX12 terminal
  on the **rear edge**; USB-C, BOOT0, NRST reachable from the rear or bottom.
- Four M3 mounting holes, ground-free keepout around them.
- Tallest top-side parts placed away from the display area and documented with a 3D STEP
  export for the enclosure design in FreeCAD.
- 2-layer, 1.6 mm, 1 oz copper. Currents are low; the main layout concern is keeping the
  switching loop (drain, flyback path, bulk cap) tight and away from the analog inputs.

### Preliminary pin map (STM32F411CEU6, verify against datasheet AF table)

Chosen from pins broken out on the Blackpill, avoiding PA0 (Blackpill KEY button),
PB2 (BOOT1), PA13/PA14 (SWD) and PA11/PA12 (USB). PB4 is JTAG NJTRST by default and is
free once the firmware configures SWD-only debug.

| Function            | Pin  | Peripheral       |
|---------------------|------|------------------|
| Strike gate         | PA8  | TIM1_CH1         |
| Overcurrent trip    | PB12 | TIM1_BKIN        |
| Pedal wiper         | PA1  | ADC1_IN1         |
| Pedal ring sense    | PA2  | ADC1_IN2         |
| Coil current        | PA6  | ADC1_IN6         |
| VIN sense           | PB0  | ADC1_IN8         |
| NTC                 | PB1  | ADC1_IN9         |
| LCD SCK             | PA5  | SPI1_SCK         |
| LCD MOSI            | PA7  | SPI1_MOSI        |
| LCD DC              | PB10 | GPIO             |
| LCD RST             | PB15 | GPIO             |
| LCD backlight       | PB6  | TIM4_CH1         |
| Encoder A           | PB4  | TIM3_CH1 (enc)   |
| Encoder B           | PB5  | TIM3_CH2 (enc)   |
| Encoder push        | PB7  | GPIO pull-up     |
| Decay mode select   | PB14 | GPIO             |
| DFU strap           | PA10 | 10k pull-up only |
| Status LED          | PC13 | GPIO, active low |
| USB D-/D+           | PA11/PA12 | OTG_FS      |
| SWD                 | PA13/PA14 | SWD         |

### Firmware behaviour (component contract; the firmware gets its own ADR)

- **Strike engine**: TIM1 one-pulse mode. A strike = one pulse of on-time `t_on` every
  period `1/f`. Firmware re-arms per period; hardware ends each pulse.
- **Ranges (defaults, all adjustable in the menu)**:
  - f = 1-60 Hz
  - t_on = 0.5-15 ms
  - duty cap `t_on * f <= 35%`
  - an average-power thermal budget for the coil (4 W nominal continuous at 24 V; the
    budget matters most on a 36 V brick)
- **Strength**: 0-100% on the display, mapped to t_on. When the duty cap clips t_on at high
  frequency, the display shows the clipped value.
- **Supply compensation**: t_on scaled by `V_nominal / VIN` (constant volt-seconds,
  V_nominal = 24 V), so a 36 V brick does not silently hit harder than a 24 V one at the
  same setting. A menu option can disable compensation for deliberate overdrive.
- **Knob and modes**:
  - turn = adjust the knob-controlled value (strength in mode F, frequency in mode S), with
    acceleration on fast turns
  - short press = toggle mode F / mode S
  - long press = menu (max frequency, duty cap, decay mode, supply compensation, pedal
    calibration, handpiece profile, brightness); turn to move, press to select
  - knob values and mode are saved to flash a few seconds after the last change
- **Safety rules**:
  - no firing until the pedal has been seen at rest after power-up or plug-in
  - pedal below a deadband = no firing
  - pedal unplugged = no firing
  - VIN < 15 V = no firing
  - independent watchdog enabled
  - overcurrent trip latches off until the pedal is released, and shows a message
  - NTC or coil-R over-temperature = refuse and show the temperature
- **Pedal calibration**: heel/toe min and max learned in the menu and stored in flash.
- **Display**: mode, frequency, strength, VIN, coil temperature (NTC or estimate), decay
  mode.
- **Future lever enabled by the hardware**: peak-current control (end the pulse when the
  ADC analog watchdog sees the target current) for strength that is independent of supply
  and coil temperature.

### Bench bring-up (before the PCB exists)

- Blackpill F411 + a MOSFET module + the 1.3" ST7789 module + an EC11 encoder + TRS jack
  on a breadboard, using the pin map above. Power from a 24 V brick.
- **The OPEN-SMART module is limited to 13.5 V**, where this coil draws only 85 mA and
  hits at roughly a quarter of its rated force. It is fine for checking timing and UI, but
  not for judging feel. For 24 V tests, use a module rated for it (the common "D4184"
  dual-MOSFET trigger modules, 5-36 V) or a 100 V logic-level FET on the breadboard.
  Currents are small, so either works at 3.3 V drive.
- Add a flyback diode (1N4007 or similar) directly across the coil on the bench; do not
  assume the module has one.
- Measure the coil's inductance if an LCR meter is available, or estimate it from the
  current rise on a scope with a 1 ohm shunt.
- The rig validates strike timing, pedal feel, UI, the control model and whether 24 V
  gives enough punch. It cannot test fast decay, current sense or the overcurrent trip;
  those wait for the first PCB.

---

## Alternatives Considered

### ESP32-C6 (dev board or on-board module)
- **The idea**: RISC-V + WiFi/BLE, flash over built-in USB-JTAG.
- **Optimizes for**: wireless tuning from a phone, no debug probe needed.
- **Sharpest tradeoff**: weaker, nonlinear ADC and less suitable timers for
  hardware-timed one-shot pulses; 3.3 V-only I/O.
- **Bets on**: users wanting app-based control more than precise, jitter-free strikes.

### Socket the Blackpill module on the production board
- **The idea**: female headers on the PCB, plug in a Blackpill.
- **Optimizes for**: the same hardware in dev and production, easy MCU swap.
- **Sharpest tradeoff**: headers are hand-soldered or extra THT cost, modules vary in
  quality (counterfeit F411s are common), and the board grows.
- **Bets on**: the class wanting to swap or reuse the MCU module.

### Keep the Arduino Nano / ATmega328 (V2 lineage)
- **The idea**: revise V2 with a better FET and power stage.
- **Optimizes for**: Arduino-IDE familiarity, upstream compatibility.
- **Sharpest tradeoff**: no room for a 320x240 TFT with a decent frame rate, and weaker
  timers/ADC.
- **Bets on**: the upstream Arduino community being the main audience.

### 12 V brick
- **The idea**: the most common brick, as originally planned.
- **Optimizes for**: availability and price.
- **Sharpest tradeoff**: with a 141 ohm coil it delivers 1 W and about a quarter of the
  rated force.
- **Bets on**: the coil being the 12 V variant. The measurement says it is not.

### On-board boost rail (e.g. 48-60 V overdrive from a 24 V brick)
- **The idea**: a boost converter charges a high-voltage reservoir; strikes fire from it
  for a fast current rise and a hard hit.
- **Optimizes for**: maximum punch (steel engraving, bezel work) from a standard brick.
- **Sharpest tradeoff**: a switching converter, 150 V-class FET and clamp, more coil
  heating, more to get wrong in a class batch.
- **Bets on**: 24-36 V not being enough punch. The bench rig at 24 V tests this bet
  before the schematic is frozen.

### USB-C PD power instead of a barrel jack
- **The idea**: a PD trigger negotiates 20 V (or 28 V with EPR) from a USB-C charger.
- **Optimizes for**: one universal cable, modern chargers.
- **Sharpest tradeoff**: standard PD stops at 20 V, below this coil's rating. 28 V needs
  EPR chargers and cables, which are rare and expensive.
- **Bets on**: EPR chargers becoming common.

### Plain-diode flyback only (as V2)
- **The idea**: one diode across the coil, no TVS, no bypass FET.
- **Optimizes for**: simplicity, lowest FET voltage stress.
- **Sharpest tradeoff**: slow release caps usable strike rate and blurs the hit.
- **Bets on**: the fast-decay difference not being perceptible in use. The bypass FET lets
  us test this bet on real hardware; if it holds, rev 2 drops the TVS path.

---

## Consequences

### Positive
- Zero-solder assembly: builders plug in the display, screw the GX12 pigtail into the
  terminal, mount the board in the box.
- Low coil current (< 0.3 A) means small, cheap power parts, low heat on the board and a
  harmless short-circuit current.
- Hardware-timed strikes, hardware overcurrent cut, gate pulldown and watchdog make a
  stuck-on coil unlikely.
- One firmware binary for the Blackpill bench rig and the production board.
- Current sense and VIN sense give real data for tuning feel, and enable later closed-loop
  strength control and coil temperature estimation.

### Negative
- More parts than V2 (gate driver, op-amp, decay-mode switch), so a larger JLC BOM and
  some extended-part fees.
- A 24 V brick is slightly less common than 12 V, though still standard.
- A display module bought from a marketplace is a sourcing risk (pinout/holes differ per
  seller).
- The handpiece cable still needs a GX12 plug fitted per handpiece (pre-made cables or one
  solder job per handpiece).

### Risks
- **24 V not punchy enough**: the board accepts up to 30 V bricks (36 V with a higher-rated
  input jack). Beyond that, the boost-rail
  alternative is the next step. The bench rig decides before the schematic is frozen.
- **Future handpieces with a different coil**: both current coils measure 141 ohm, but the
  batch will need 8-10 more. The handpiece profile and coil check absorb normal variation;
  a 36 ohm (12 V) coil would still be within the driver ratings but needs a lower supply or
  strict duty limits. Buy all solenoids from one listing.
- **STM32F411 stock at JLC**: fallback STM32F401CCU6 is pin compatible.
- **Inrush sparking / brick OCP** on hot-plug: small risk with ~500 uF of bulk; an NTC
  inrush limiter or a proper soft-start is the fix if a brick trips.

---

## What an Expert Would Ask

**Q: What stops the coil from being left on if firmware crashes mid-strike?**
A: The pulse comes from TIM1 one-pulse mode, so the timer ends it regardless of CPU state.
The gate driver input idles low with a pulldown on the FET gate. The IWDG resets a hung
MCU, and reset leaves PA8 as a floating input, which the pulldown holds off. The overcurrent
comparator acts through BKIN in hardware. The remaining failure is a shorted FET
(drain-source): then the coil runs at 170-255 mA continuous, which heats it but does not
blow the fuse. The coil-R/NTC over-temperature check cannot switch off a shorted FET.
Not handled in rev 1. A series high-side cut-off switch would fix it; accepted for now
because the result is a hot handpiece, not a fire, and the user notices immediately.

**Q: A student plugs a guitar cable, a mono jack or a sustain pedal into the pedal input.
What happens?**
A: The mono plug shorts ring to sleeve; the 1k series resistor limits that to 3.3 mA
and the ring-sense ADC detects it. Firmware then treats the input as an on/off footswitch
(tip pull-up) or refuses with a message. Nothing gets damaged, and it can't fire unexpectedly
because the pedal-at-rest rule still applies.

**Q: Is 24 V into a 141 ohm coil enough to engrave with?**
A: It is the coil's rated continuous operating point, so short pulses at 24 V give rated
force, not more. The original project ran a 12 V 1335 from an 18.5 V brick, which is
about 1.5x overdrive, and reported it engraves steel. The equivalent for this coil is
~36 V. The electronics support that; the stock DC jack stops at 30 V, which is already
1.25x overdrive. If that is still not enough, the boost-rail alternative
is the answer. This is the question the bench rig must answer first.

**Q: Why constant volt-seconds for supply compensation instead of constant energy?**
A: For pulses shorter than the coil's L/R time constant, current ramps roughly as V*t/L,
so constant V*t gives roughly constant peak current. For long pulses current saturates at
V/R and the compensation overshoots. It is a first-order fix. The current-sense path is
there so it can be replaced by peak-current control once there is data.

**Q: Ten identical boxes: how do you keep them behaving identically?**
A: Same brick model, same display listing, same pedal model, same firmware. Per-unit pedal
calibration is stored in flash. Coil variation between 1335s is absorbed by the handpiece
profile, the power-up coil check and, later, by current-based control.

---

## Implementation Plan

### Decisions you will probably want to tweak

- **Operating voltage 18-36 V, 24 V brick standard**
  - Alternative: boost rail for 48-60 V overdrive.
  - Cost to change later: adding a boost stage after layout is a respin. Decide from the
    bench test.
- **Firmware-selectable decay (P-FET bypass)**
  - Alternative: fixed fast decay, or a jumper.
  - Cost to change later: low. Leave the bypass parts unpopulated in the BOM.
- **Board as top panel, jacks on the rear edge**
  - Alternative: vertical board behind a front plate.
  - Cost to change later: moderate. Relayout plus a new enclosure.
- **4-pin GX12 with NTC pins**
  - Alternative: 2-pin, coil only, relying on the coil-R temperature estimate.
  - Cost to change later: low on the board. Existing handpieces stay compatible if the NTC
    stays optional.
- **1.3" 240x240 ST7789 module on a header**
  - Alternative: bare panel on an FPC connector (fab-assembled, no seller variance), or a
    larger 2.0" 240x320 module.
  - Cost to change later: moderate. Footprint and mechanics change; firmware layout
    changes with the resolution.
- **Single encoder, no pot, no buttons**
  - Alternative: encoder plus a pot, for a knob with an absolute position.
  - Cost to change later: low. A pot footprint can be added on a free ADC pin (PA3).

### Known unknowns and how the plan absorbs them

- **Punch at 24 V**
  - Default: 24 V brick, up to 30 V supported.
  - Pivot signal: bench hits too weak even at 30 V. Then add the boost rail before the
    schematic.
- **Coil inductance**
  - Default: assume a time constant of order 1 ms; the TVS energy has a large margin.
  - Pivot signal: measured L makes the current rise too slow for short pulses, which again
    points to a higher drive voltage.
- **Batch solenoids**
  - Default: all 141 ohm, like the two on hand.
  - Pivot signal: a delivered coil measures ~36 ohm (12 V variant). Then the supply and
    profile defaults need a per-handpiece setting.
- **Fast vs slow decay perceptibility**
  - Default: fast.
  - Pivot signal: nobody can feel the difference, so drop the TVS path in rev 2.
- **Display module variance**
  - Default: one listing, bulk buy.
  - Pivot signal: the chosen listing disappears, so move to the FPC bare-panel variant.

### The mechanical work

- KiCad project under `Hardware/graver-controller/`: schematic sheets for power, driver,
  MCU, UI and connectors; layout; JLC BOM/CPL export; STEP export.
- Rust firmware crate `firmware/` (embassy-stm32, thumbv7em-none-eabihf), with a separate
  firmware ADR.
- Enclosure in FreeCAD, next to the existing CAD files.
- Bench rig per the bring-up section; flash the same firmware on the first PCB.

### Review asks

1. 24 V brick as standard, board rated 18-36 V: yes/no?
2. Keep the firmware-selectable slow-decay bypass on rev 1, or fix it at fast decay?
3. Board as the top face of a desk console with jacks on the rear edge: yes, or do you
   picture a front-panel box?
4. 4-pin GX12 with optional NTC, or plain 2-pin?

---

## Open Questions

**Architecture-changers**
- [ ] Is 24-36 V enough punch, or is a boost rail needed? Answer on the bench rig with a
      24 V brick before the schematic is frozen.
- [ ] Part number printed on the solenoids, to confirm the 24 V variant and its duty
      rating. (Both coils measure 141 ohm.)
- [ ] Does anyone want wireless (phone) control? If yes, revisit ESP32.

**Behavior definers**
- [ ] Default strike ranges (1-60 Hz, 0.5-15 ms, 35% duty cap), to confirm on the bench rig
      with the real 1335.
- [ ] Handpiece NTC: fitted on all 10 handpieces, or rely on the coil-R estimate?
- [ ] Exact pinout and outline of the OT3499 module (7-pin without CS expected); measure
      one before drawing the footprint.
