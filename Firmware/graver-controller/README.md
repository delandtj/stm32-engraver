# graver-controller firmware

Rust (embassy) firmware for the solenoid graver controller described in
`docs/adr/0001-graver-controller-board.md`. The design of the firmware itself
is `docs/adr/0002-firmware.md`; read that before changing anything here.

One binary runs on two boards:

* the bench rig: a WeAct Blackpill (STM32F411CEU6, 25 MHz crystal) with the
  display, encoder, pedal jack and a FET module wired to the pin map below;
* the production PCB, which uses the same chip and the same pins.

## Pin map

| Function          | Pin  | Peripheral            |
|-------------------|------|-----------------------|
| Strike gate       | PA8  | TIM1_CH1, one-pulse   |
| Overcurrent trip  | PB12 | TIM1_BKIN, pull-down  |
| Pedal wiper       | PA1  | ADC1_IN1              |
| Pedal ring sense  | PA2  | ADC1_IN2              |
| Coil current      | PA6  | ADC1_IN6              |
| VIN sense         | PB0  | ADC1_IN8              |
| NTC               | PB1  | ADC1_IN9              |
| LCD SCK / MOSI    | PA5 / PA7 | SPI1, mode 3     |
| LCD DC / RST      | PB10 / PB15 | GPIO           |
| LCD backlight     | PB6  | TIM4_CH1 PWM          |
| Encoder A / B     | PB4 / PB5 | TIM3 quadrature  |
| Encoder push      | PB7  | GPIO, pull-up         |
| Decay mode        | PB14 | GPIO, low = fast      |
| Status LED        | PC13 | GPIO, active low      |
| DFU strap         | PA10 | untouched (floating)  |

PA0 (the Blackpill's KEY button) is deliberately unused so the bench pin map
and the PCB pin map are identical. PA11/PA12 (USB) are reserved for DFU.

## Build

The target is installed with `rustup target add thumbv7em-none-eabihf`. The
target, linker flags and runner are set in `.cargo/config.toml`, so:

    cd Firmware/graver-controller
    cargo build --release
    cargo clippy --release

## Flash with a debug probe (development)

With any probe-rs supported probe (ST-Link, CMSIS-DAP, J-Link) on SWD:

    cargo run --release          # flashes and then prints the defmt log
    probe-rs run --chip STM32F411CEUx \
        target/thumbv7em-none-eabihf/release/graver-controller

`cargo run` uses the runner in `.cargo/config.toml`, so it flashes, resets and
attaches the RTT log in one step. `Ctrl-C` detaches; the board keeps running.

Note: this repository builds into a shared target directory when
`CARGO_TARGET_DIR` is set in your environment. `cargo metadata --no-deps` tells
you where the ELF actually is.

## Flash over USB with DFU (no probe)

Two ways into the ROM bootloader:

1. hold the encoder pushed while powering up (this firmware detects PB7 low at
   boot and jumps to system memory), or
2. hold BOOT0 and tap NRST.

Then:

    tools/dfu.sh                  # build, objcopy, dfu-util, leave DFU

or by hand:

    cargo build --release
    llvm-objcopy -O binary \
        target/thumbv7em-none-eabihf/release/graver-controller graver.bin
    dfu-util -a 0 -s 0x08000000:leave -D graver.bin

`arm-none-eabi-objcopy` works the same way. With `cargo-binutils` and
`llvm-tools-preview` installed, `cargo bin` (alias in `.cargo/config.toml`)
does the objcopy step.

## Viewing defmt logs

probe-rs decodes the RTT stream itself:

    cargo run --release
    DEFMT_LOG=debug cargo run --release     # includes per-strike lines

`DEFMT_LOG` is compiled in, so changing it rebuilds. The default is `info`:
state changes, menu actions, settings loads. `debug` adds one line per strike
with the frequency and the on-time.

## Cargo features

| Feature   | Default | What it does |
|-----------|---------|--------------|
| `bench`   | off     | Fires a fixed burst at boot, without a pedal |
| `buttons` | off     | Three tactile buttons instead of the encoder |

### `bench`

    cargo run --release --features bench

Three seconds after boot the firmware fires 20 pulses of 3 ms at 5 Hz, with no
pedal and no safety interlock, so the strike path can be scoped with only a
Blackpill, a FET module and the coil. The constants are at the top of
`src/bench.rs`. After the burst the firmware behaves normally. Never ship a
unit built with this feature.

### `buttons`

    cargo run --release --features buttons

For bench work before an encoder is on hand: three tactile switches to ground
on the same pins the encoder will use, so nothing has to be rewired later.

* PB4 = one detent up
* PB5 = one detent down
* PB7 = push (short press toggles the mode, long press opens the menu)

Internal pull-ups, 20 ms debounce, auto-repeat after 400 ms at 10 detents per
second, and the step grows the longer a direction is held. The rest of the
firmware sees exactly the same events as with the encoder.

With the encoder backend (the default), `COUNTS_PER_DETENT` in `src/input.rs`
is 2, which matches the Alps EC11E15244G1 (30 detents / 15 pulses per turn,
x4 decoding). A 24-pulse/24-detent or 20/20 encoder needs 4.

## Operating notes

* No firing until the pedal has been seen at rest, and never with the pedal
  unplugged, below 15 V, above 70 C or after an overcurrent trip. The status
  bar always says which rule is blocking.
* The pedal jack's ring sense is what detects "pedal plugged in". A bench jack
  without a normalling contact leaves the ring floating; tie it to ground
  through 10k or the firmware may believe a pedal is present.
* Settings are written to flash three seconds after the last change and only
  while the coil is idle.
* On the bench the Blackpill runs from USB, so VIN sense only sees whatever is
  wired to PB0. With nothing there the status bar shows LOW VIN and the
  firmware refuses to fire: feed PB0 from the 100k/8.2k divider on the brick.
* Coil current assumes the PCB's gain-of-11 amplifier on a 1 ohm shunt. On a
  bench rig with PA6 straight across a 1 ohm resistor (gain 1) the reading is
  eleven times too low; see `SENSE_GAIN` in `src/analog.rs`. Nothing acts on
  that value yet, so it does not affect firing.

Full bench wiring is in `docs/bench-rig.md`.
