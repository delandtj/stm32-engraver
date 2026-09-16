//! Solenoid graver controller firmware.
//!
//! Target: STM32F411CEU6 with a 25 MHz crystal. The same binary runs on the
//! WeAct Blackpill bench rig and on the production board (ADR 0001), because
//! the pin map is identical on both.
//!
//! Task layout (ADR 0002):
//!   analog_task   200 Hz ADC sweep, publishes Readings
//!   input_task    200 Hz encoder/button poll, publishes InputEvent
//!   control_task  modes, menu, safety, publishes StrikeParams and UiState
//!   strike_task   arms one TIM1 one-pulse per period
//!   ui_task        10 Hz partial screen refresh
//!   main          watchdog, status LED, boot self-check

#![no_std]
#![no_main]

mod analog;
#[cfg(feature = "bench")]
mod bench;
mod bootloader;
mod control;
mod input;
mod settings;
mod strike;
mod text;
mod ui;

use core::sync::atomic::{AtomicU32, Ordering};

use defmt_rtt as _;
use panic_probe as _;

use embassy_executor::Spawner;
use embassy_stm32::gpio::{Level, Output, OutputType, Speed};
use embassy_stm32::time::Hertz;
use embassy_stm32::timer::low_level::CountingMode;
use embassy_stm32::timer::simple_pwm::{PwmPin, SimplePwm};
use embassy_stm32::wdg::IndependentWatchdog;
use embassy_stm32::{Config, spi};
use embassy_time::{Duration, Instant, Timer};
use static_cell::StaticCell;

use crate::strike::StrikeEngine;

/// Watchdog period. The main loop feeds it five times faster than this.
const WATCHDOG_US: u32 = 1_000_000;
/// The control task must have run within this long, or the watchdog is not
/// fed and the chip resets with the gate pin released (and pulled low).
const HEARTBEAT_TIMEOUT: Duration = Duration::from_millis(500);
/// Backlight PWM frequency: well above flicker, well below the LED driver's
/// limits.
const BACKLIGHT_HZ: Hertz = Hertz(1_000);
/// SPI clock for the panel. 24 MHz = 84 MHz / 4, the fastest divider the
/// ST7789 is specified for on a short cable.
const LCD_HZ: Hertz = Hertz(24_000_000);

static HEARTBEAT: AtomicU32 = AtomicU32::new(0);
static LCD_BUFFER: StaticCell<[u8; ui::LCD_BUFFER_LEN]> = StaticCell::new();

/// Called by the control task on every pass; watched by the main loop.
pub fn heartbeat() {
    HEARTBEAT.fetch_add(1, Ordering::Relaxed);
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    // Before the clocks are touched: hold the encoder down at power-up to get
    // the ROM bootloader (USB DFU) instead of this firmware.
    unsafe { bootloader::maybe_enter_dfu() };

    // 25 MHz HSE -> /25 -> 1 MHz -> x336 -> 336 MHz -> /4 = 84 MHz SYSCLK,
    // /7 = 48 MHz for USB. Identical to the Blackpill's stock configuration,
    // so TIM1 (APB2) ticks at 84 MHz on both boards.
    let mut config = Config::default();
    {
        use embassy_stm32::rcc::*;
        config.rcc.hse = Some(Hse {
            freq: Hertz(25_000_000),
            mode: HseMode::Oscillator,
        });
        config.rcc.pll_src = PllSource::HSE;
        config.rcc.pll = Some(Pll {
            prediv: PllPreDiv::DIV25,
            mul: PllMul::MUL336,
            divp: Some(PllPDiv::DIV4),
            divq: Some(PllQDiv::DIV7),
            divr: None,
        });
        config.rcc.ahb_pre = AHBPrescaler::DIV1;
        config.rcc.apb1_pre = APBPrescaler::DIV2;
        config.rcc.apb2_pre = APBPrescaler::DIV1;
        config.rcc.sys = Sysclk::PLL1_P;
    }
    let p = embassy_stm32::init(config);
    defmt::info!("graver controller starting");

    // PA10 is deliberately left untouched: it is the DFU strap and must stay
    // a floating input. PA11/PA12 (USB) are unused for now.

    // Status LED, active low on PC13.
    let mut led = Output::new(p.PC13, Level::High, Speed::Low);

    // Decay mode select: low = fast decay (TVS clamp), high = slow.
    let decay = Output::new(p.PB14, Level::Low, Speed::Low);

    // Strike engine first, so the gate pin is driven low as early as possible.
    let engine = StrikeEngine::new(p.TIM1, p.PA8, p.PB12);
    if !engine.gate_is_low() {
        defmt::error!("gate pin is not low after init");
    }

    // Display: SPI1 TX only, mode 3 (the module has no CS pin).
    let mut spi_config = spi::Config::default();
    spi_config.frequency = LCD_HZ;
    spi_config.mode = spi::MODE_3;
    let lcd_spi = spi::Spi::new_blocking_txonly(p.SPI1, p.PA5, p.PA7, spi_config);
    let lcd_dc = Output::new(p.PB10, Level::Low, Speed::VeryHigh);
    let lcd_rst = Output::new(p.PB15, Level::High, Speed::Low);
    let lcd_buffer = LCD_BUFFER.init([0u8; ui::LCD_BUFFER_LEN]);
    let lcd = ui::init(lcd_spi, lcd_dc, lcd_rst, lcd_buffer);

    // Backlight on TIM4_CH1 (PB6).
    let backlight = SimplePwm::new(
        p.TIM4,
        Some(PwmPin::new(p.PB6, OutputType::PushPull)),
        None,
        None,
        None,
        BACKLIGHT_HZ,
        CountingMode::EdgeAlignedUp,
    );

    // Settings live in flash sector 7. Loading may compact the journal, which
    // erases a sector, so it happens before the watchdog is started.
    let (store, stored) = settings::Store::new(p.FLASH);
    defmt::info!("settings loaded: {}", stored);

    spawner.spawn(defmt::unwrap!(analog::analog_task(
        p.ADC1, p.PA1, p.PA2, p.PA6, p.PB0, p.PB1
    )));
    spawner.spawn(defmt::unwrap!(input::input_task(
        p.TIM3, p.PB4, p.PB5, p.PB7
    )));
    spawner.spawn(defmt::unwrap!(strike::strike_task(engine)));
    spawner.spawn(defmt::unwrap!(ui::ui_task(lcd, backlight)));
    spawner.spawn(defmt::unwrap!(control::control_task(store, stored, decay)));

    // From here on a stalled control task resets the chip. Reset releases PA8,
    // where the external pull-down (and the gate driver's own pulldown on the
    // board) holds the FET off.
    let mut watchdog = IndependentWatchdog::new(p.IWDG, WATCHDOG_US);
    watchdog.unleash();

    let mut last_beat = HEARTBEAT.load(Ordering::Relaxed);
    let mut last_change = Instant::now();
    loop {
        Timer::after_millis(100).await;

        let beat = HEARTBEAT.load(Ordering::Relaxed);
        if beat != last_beat {
            last_beat = beat;
            last_change = Instant::now();
        }
        if last_change.elapsed() < HEARTBEAT_TIMEOUT {
            watchdog.pet();
        } else {
            defmt::error!("control task stalled, letting the watchdog bite");
        }

        led.toggle();
    }
}
