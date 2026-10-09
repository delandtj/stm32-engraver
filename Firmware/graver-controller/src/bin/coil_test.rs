//! Bench test: drive the FET module on PA8 as a plain GPIO, nothing else.
//!
//! No timer, no watchdog, no pedal or VIN checks. Repeats:
//!   - 5 clicks: 10 ms on, 190 ms off
//!   - 2 s steady on   (meter across the coil: should read ~ the PSU voltage)
//!   - 2 s off         (meter across the coil: should read ~0 V)
//! The Blackpill LED (PC13, active low) mirrors the gate.
//!
//! Steady on at 12 V puts ~85 mA / 1 W into the 141 ohm coil; fine for 2 s.
//! Never flash this on a unit that goes to a class.
//!
//!     cargo run --release --bin coil_test

#![no_std]
#![no_main]

use defmt_rtt as _;
use embassy_executor::Spawner;
use embassy_stm32::gpio::{Level, Output, Pull, Speed};
use embassy_time::Timer;
use panic_probe as _;

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_stm32::init(Default::default());

    let mut gate = Output::new(p.PA8, Level::Low, Speed::Low);
    let mut led = Output::new(p.PC13, Level::High, Speed::Low);
    // Keep the break net quiet, as in the main firmware.
    let _bkin = embassy_stm32::gpio::Input::new(p.PB12, Pull::Down);

    defmt::info!("coil test: PA8 plain GPIO");
    loop {
        defmt::info!("5 clicks, 10 ms");
        for _ in 0..5 {
            gate.set_high();
            led.set_low();
            Timer::after_millis(10).await;
            gate.set_low();
            led.set_high();
            Timer::after_millis(190).await;
        }

        defmt::info!("steady ON 2 s");
        gate.set_high();
        led.set_low();
        Timer::after_secs(2).await;

        defmt::info!("OFF 2 s");
        gate.set_low();
        led.set_high();
        Timer::after_secs(2).await;
    }
}
