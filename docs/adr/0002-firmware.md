# 0002 - Graver Controller Firmware (Rust, embassy)

**Status**: Accepted
**Date**: 2026-09-16
**Implements**: ADR 0001, sections "Preliminary pin map", "Firmware behaviour",
"Bench bring-up"

---

## Context

ADR 0001 fixes the hardware: STM32F411CEU6, 25 MHz crystal, TIM1 one-pulse
strikes into a gate driver, a hardware overcurrent comparator on TIM1_BKIN, an
ST7789 240x240 module with no CS pin, one EC11 encoder, an expression pedal on
a TRS jack, and flash for settings. The same binary has to run on the WeAct
Blackpill bench rig and on the production board, and it has to be safe in the
hands of a class: the coil must never be left energised, and nothing may fire
that the operator did not ask for.

This ADR is the component spec of that firmware: what the modules are, which
peripheral each one owns, what the state model is, and which rules are
non-negotiable.

---

## Decision

A single Rust binary, `Firmware/graver-controller`, built on embassy with one
thread-mode executor and six concurrent tasks. Every peripheral has exactly one
owner; everything shared crosses task boundaries through `embassy-sync`
primitives, never through mutable statics.

Crate versions in use: embassy-stm32 0.6, embassy-executor 0.10,
embassy-time 0.5, embassy-sync 0.8, mipidsi 0.10, embedded-graphics 0.8,
embedded-hal-bus 0.3, defmt 1, panic-probe 1, cortex-m 0.7, cortex-m-rt 0.7.

### Clocks

25 MHz HSE, PLL /25 x336 /4 = 84 MHz SYSCLK, PLLQ /7 = 48 MHz for a future USB
device. AHB /1, APB1 /2, APB2 /1, so TIM1 (APB2) and TIM3/TIM4 (APB1, doubled)
all tick at 84 MHz. This is the Blackpill's stock configuration, so the timing
constants are identical on both boards. embassy's time driver is TIM5, which
keeps TIM1, TIM3 and TIM4 free for the application.

### Modules and tasks

| Module | Owns | Task | Rate |
|---|---|---|---|
| `main.rs` | RCC, IWDG, PC13 | main loop | 10 Hz |
| `bootloader.rs` | nothing (pre-init PAC access) | - | boot only |
| `strike.rs` | TIM1, PA8, PB12 | `strike_task` | per strike |
| `analog.rs` | ADC1, PA1, PA2, PA6, PB0, PB1 | `analog_task` | 200 Hz |
| `input.rs` | TIM3, PB4, PB5, PB7 | `input_task` | 200 Hz |
| `control.rs` | settings, PB14 | `control_task` | 100 Hz or on event |
| `ui.rs` | SPI1, PA5, PA7, PB10, PB15, TIM4, PB6 | `ui_task` | 10 Hz |
| `settings.rs` | FLASH | - | called by control |
| `bench.rs` | nothing | - | feature `bench` |

Data flow, all `embassy-sync` types with a `CriticalSectionRawMutex`:

```
  analog_task --Watch<Readings>--> control_task --Watch<StrikeParams>--> strike_task
  input_task  --Channel<InputEvent, 16>--> control_task --Watch<UiState>--> ui_task
  strike_task --Watch<bool overcurrent>--> control_task --Signal<()> clear--> strike_task
  control_task --Watch<PedalCal>--> analog_task
```

### Strike engine (the part that must not be got wrong)

TIM1 CH1 in one-pulse mode, configured through embassy's `timer::low_level`
wrapper (a thin, typed layer over the PAC that also handles the RCC enable);
embassy's `SimplePwm` cannot do one-pulse mode, and its `OnePulse` driver is
built for a hardware trigger pin, not for software arming.

* prescaler from the live APB2 clock so one tick is 1 us
* CR1.OPM = 1: the counter clears CEN at the update event, so one arm is
  exactly one pulse
* PWM mode 2 with CCR1 = 2 us and ARR = 2 us + t_on - 1: output low until the
  compare, high until the update, then low and stopped
* BDTR: OSSI = 1 with OIS1 = 0, so while MOE is clear the pin is actively
  driven low instead of released; BKE = 1, BKP = 1 (comparator is active
  high), break filter 8 clocks, and AOE = 0 so a break latches MOE off until
  firmware clears it
* PA8 is driven low as a plain GPIO before TIM1 takes it over, and the AF
  configuration keeps an internal pull-down on the pin

`strike_task` re-arms once per period, checks the break flag after each pulse
and, on a trip, disables the output and publishes the fault. It never reads
the pedal or the settings: those decisions belong to `control_task`.

Ranges: f 1-60 Hz, t_on 500-15000 us in 10 us steps, duty cap t_on * f <= 35 %
(adjustable down to 5 %), supply compensation t_on * 24 V / VIN when enabled.
The display always shows the value actually used after clipping.

### Analog

One blocking sweep of five channels every 5 ms, each smoothed with a
first-order IIR. Scaling constants live at the top of `analog.rs`:
VIN = Vadc * 108.2 / 8.2; coil current = Vadc / (11 x 1 ohm); NTC is a 10k
B3950 against a 10k pull-up, solved with the beta equation, and reads as "no
NTC fitted" when the pin is open or shorted. Pedal travel is normalised to
0..1000 from the stored heel/toe calibration with a 4 % deadband. The ring
sense decides "expression pedal present": above 1.0 V is a pedal, at ground is
nothing or a mono plug.

### Input

Two backends behind one event type (`Turn(i32)`, `ShortPress`, `LongPress`):

* default: TIM3 in hardware quadrature mode (x4) on PB4/PB5 with internal
  pull-ups, `COUNTS_PER_DETENT = 2` for the Alps EC11E15244G1 (30 detents /
  15 pulses per turn; a 24/24 or 20/20 part needs 4). Leftover counts are
  accumulated, never discarded, so a slow detent is not lost between polls.
  Turning faster multiplies the step by 3 or 8.
* feature `buttons`: three tactile switches to ground on the same three pins
  (PB4 up, PB5 down, PB7 push), 20 ms debounce, auto-repeat after 400 ms at
  10 detents per second, for bench work before an encoder is available. No
  rewiring is needed when the encoder arrives.

Nothing outside `input.rs` knows which backend is compiled in. PB4 is NJTRST
at reset and is free because the firmware never enables JTAG. PA0, the
Blackpill's own KEY button, is left unused so the bench pin map equals the PCB
pin map.

### Control model and menu

Mode F: pedal sets frequency, knob sets strength. Mode S: pedal sets strength,
knob sets frequency. Short press toggles the mode. Long press (> 600 ms) opens
the menu: max frequency, duty cap, decay fast/slow, supply compensation on/off,
pedal heel, pedal toe, brightness, exit. Turning moves the selection; a press
enters or leaves edit mode for numeric items, toggles boolean items, captures
the live pedal reading for the calibration items and closes the menu on exit.
Firing is inhibited while the menu is open.

### Display

240x240, SPI mode 3 at 24 MHz, no CS (an `ExclusiveDevice` with a no-op chip
select gives mipidsi the `SpiDevice` it expects). The visible window sits at
offset (0, 0) inside the ST7789's 240x320 frame buffer; the offset is a named
constant because other modules of this size are shifted. Six value cells (rate,
strength, on-time, supply, handpiece temperature, decay) plus a coloured status
bar. Only cells whose formatted text changed are repainted: a full frame is
115 kB over the wire and would stretch a strike period. Backlight is TIM4_CH1
PWM at 1 kHz from the brightness setting.

### Flash layout

| Region | Address | Use |
|---|---|---|
| sectors 0-6 | 0x0800_0000 - 0x0805_FFFF (384 KB) | program, the FLASH region in memory.x |
| sector 7 | 0x0806_0000 - 0x0807_FFFF (128 KB) | settings journal, excluded from memory.x |

The journal is 4096 append-only 32-byte records: magic "GRV", a format
version, the payload and a CRC-16. A save writes the next free slot; a load
takes the last valid one and clamps every field into range, so a corrupt byte
cannot produce a dangerous strike setting. Compaction (erase plus one record)
happens at boot, before the watchdog is started, once the journal is three
quarters full. It is never done at runtime: erasing a 128 KB sector stalls the
core for up to two seconds, which a 1 s watchdog would not survive. If the
journal fills during a single session, the change stays in RAM and a warning is
logged.

Settings are written three seconds after the last change and only while the
coil is idle.

### Safety rules

These are implemented in `control_task` and are the reason it is the only task
allowed to ask for fire:

1. no firing until the pedal has been seen at rest (below the deadband) after
   power-up or after being plugged in
2. pedal below the deadband: no firing
3. pedal unplugged, or a mono plug (ring at ground): no firing
4. VIN below 15 V: no firing, "LOW VIN" on the screen; below 18 V it warns
5. NTC above 70 C: no firing, "HOT"
6. a TIM1 break event latches "OVERCURRENT" until the pedal is released
7. the independent watchdog (about 1 s) is fed by the main loop only while the
   control task keeps incrementing its heartbeat; a stalled control task
   resets the chip, and reset releases PA8, which the external pull-down holds
   low
8. firing is inhibited while the menu is open

### Boot

`main` first checks PB7 with a pull-up, using the PAC directly and still at the
reset clock configuration. If it is low, interrupts are disabled, the NVIC is
cleared, SYSCFG maps system memory at zero, VTOR points at 0x1FFF_0000 and the
MSP and reset vector from that table are loaded: the ST ROM bootloader takes
over and enumerates as USB DFU. Otherwise the clocks are configured, the strike
engine is built first (so PA8 is driven low as early as possible), then the
display, then the settings, then the tasks, and only then is the watchdog
started.

### Logging

defmt over RTT, decoded by probe-rs. `info` covers state changes, mode and menu
changes, settings loads and saves; `debug` adds one line per strike with the
frequency and the on-time. The level is compiled in through `DEFMT_LOG`, set to
`info` in `.cargo/config.toml`.

### Build and flash

    cd Firmware/graver-controller
    cargo build --release          # thumbv7em-none-eabihf, set in .cargo/config.toml
    cargo clippy --release
    cargo run --release            # probe-rs run --chip STM32F411CEUx, then defmt logs

Without a probe: hold the encoder at power-up (or BOOT0 plus NRST), then
`tools/dfu.sh`, which builds, runs objcopy and calls
`dfu-util -a 0 -s 0x08000000:leave -D`.

Bench helpers: `--features bench` fires 20 pulses of 3 ms at 5 Hz three seconds
after boot with no pedal attached; `--features buttons` swaps the encoder for
three tactile buttons on the same pins. The rig itself is wired as described in
`docs/bench-rig.md`.

---

## Consequences

### Positive

- The pulse length is hardware, the overcurrent cut is hardware, and the
  watchdog covers the rest. A firmware bug can fail to fire; it cannot leave
  the coil on.
- One binary, two boards, one pin map, and a bench build that needs neither a
  pedal nor an encoder.
- All board-specific numbers are named constants in two files (`analog.rs` for
  scaling, `control.rs` for ranges), so a hardware revision is a small diff.
- Settings survive a power cycle without an EEPROM, and a corrupt record falls
  back to safe defaults.

### Negative

- SPI to the display is blocking. A menu repaint can occupy the executor for
  tens of milliseconds; that is why firing is inhibited while the menu is open.
  Moving the panel to DMA would remove the restriction.
- The strike period comes from the software timer, so the period (not the
  pulse) carries the executor's jitter, on the order of tens of microseconds.
- The settings journal cannot be compacted while the tool is running.
- Fonts are the embedded-graphics built-ins; the largest is 10x20, which is
  small for a value read at arm's length.

### Risks

- The 240x240 module's frame-buffer offset is taken from the common 1.3" part.
  If a sourced module is shifted, `OFFSET_X` / `OFFSET_Y` in `ui.rs` must be
  corrected once, per listing.
- Colour inversion is enabled, which is right for the usual ST7789 IPS module
  but wrong for some. One constant, one line.
- The NTC beta constants assume a 10k B3950 thermistor. A different part gives
  a wrong temperature and could refuse to fire.
- On the bench the Blackpill runs from USB, so VIN sense reads whatever is on
  PB0. Without the divider wired the firmware reports LOW VIN and will not
  fire, which is correct but surprising.

---

## What an Expert Would Ask

**Q: Why not embassy's `OnePulse` driver?**
A: It triggers from a pin (TI1, TI2 or ETR) and consumes a channel as an
input. The strike is armed by software once per period, so the timer is
configured directly: OPM, PWM mode 2, and CEN set per strike. The register
steps are commented against RM0383 chapter 12 in `src/strike.rs`.

**Q: What happens if the control task deadlocks with the pedal down?**
A: The strike task keeps re-arming, so the coil keeps pulsing at the last
commanded rate until the heartbeat stops being updated. Within 500 ms the main
loop stops feeding the watchdog, and within about a second the chip resets. On
reset PA8 is an input again and the pull-down holds the gate off.

**Q: Is a blocking flash write safe while the tool is in use?**
A: A 32-byte write is a handful of microseconds and only happens three seconds
after the last knob movement and only while not firing. The expensive
operation, the sector erase, is confined to boot.

**Q: Why a journal rather than one fixed record?**
A: A single record needs an erase on every save, which is both slow and hard on
the sector. 4096 slots per erase cycle means a unit that is adjusted twenty
times a day erases once every few years.

**Q: What stops the bench feature from reaching a student's unit?**
A: It is off by default, it logs a warning at boot, and it is the only code
path that can fire without a pedal. The release procedure is a plain
`cargo build --release` with no features.

---

## Open Questions

- Exact frame-buffer offset and colour inversion of the sourced 1.3" module;
  confirm on the first one and fix the constants if needed.
- Whether the handpiece NTC is fitted on all units. Without it the firmware
  shows "--" and has no thermal limit; the coil-resistance estimate from
  ADR 0001 is not implemented yet.
- Whether 200 Hz pedal sampling with a 4 % deadband feels right, or whether the
  pedal needs a shaped (non-linear) response.
- Peak-current control from the ADC analog watchdog, listed as a future lever
  in ADR 0001, is not implemented. The coil current is sampled and published
  for other tasks, but nothing acts on it yet and the screen does not show it.
