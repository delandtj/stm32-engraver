//! Display: 240x240 ST7789 over SPI1, redrawn about ten times a second.
//!
//! The module has no CS pin, so the controller is permanently selected and the
//! bus must idle in SPI mode 3. An `ExclusiveDevice` with a no-op chip select
//! gives the mipidsi driver the `SpiDevice` it wants without a pin.
//!
//! Only fields whose text changed are repainted: a full 240x240 frame is
//! 115 kB over the wire, which would block the executor for tens of
//! milliseconds and stretch a strike period.

use core::fmt::Write;

use embassy_stm32::gpio::Output;
use embassy_stm32::mode::Blocking;
use embassy_stm32::peripherals::TIM4;
use embassy_stm32::spi::Spi;
use embassy_stm32::spi::mode::Master;
use embassy_stm32::timer::simple_pwm::SimplePwm;
use embassy_time::{Delay, Duration, Ticker};
use embedded_graphics::mono_font::{MonoTextStyle, MonoTextStyleBuilder};
use embedded_graphics::mono_font::ascii::FONT_9X18_BOLD;
use profont::{PROFONT_18_POINT, PROFONT_24_POINT};
use embedded_graphics::pixelcolor::Rgb565;
use embedded_graphics::prelude::*;
use embedded_graphics::primitives::{PrimitiveStyle, Rectangle};
use embedded_graphics::text::{Baseline, Text};
use embedded_hal::digital::{ErrorType, OutputPin};
use embedded_hal_bus::spi::{ExclusiveDevice, NoDelay};
use heapless::String;
use mipidsi::interface::SpiInterface;
use mipidsi::models::ST7789;
use mipidsi::options::ColorInversion;
use mipidsi::{Builder, Display};

use crate::control::{MENU_ROWS, MenuState, Status, UiState};
use crate::settings::{Lang, Mode, Settings};
use crate::text;

/// Panel size.
pub const WIDTH: u16 = 240;
pub const HEIGHT: u16 = 240;
/// Where the visible 240x240 window sits inside the ST7789's 240x320 frame
/// buffer. The common 1.3" IPS module starts at the origin; 1.14" 240x135 and
/// some 240x240 round modules do not, so this is a named constant to change.
pub const OFFSET_X: u16 = 0;
pub const OFFSET_Y: u16 = 0;

/// Pixel buffer for the SPI interface. One full row of 16-bit pixels.
pub const LCD_BUFFER_LEN: usize = 512;

/// Refresh rate.
const REFRESH: Duration = Duration::from_hz(10);
/// Shown supply voltage only moves in steps larger than this.
const VIN_HYST_MV: u32 = 200;
/// Shown on-time only moves in steps larger than this.
const T_ON_HYST_US: u32 = 50;

/// A chip select that does nothing: the module has no CS pin and is
/// permanently selected.
pub struct NoCs;

impl ErrorType for NoCs {
    type Error = core::convert::Infallible;
}

impl OutputPin for NoCs {
    fn set_low(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }
    fn set_high(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }
}

type LcdBus = Spi<'static, Blocking, Master>;
type LcdDevice = ExclusiveDevice<LcdBus, NoCs, NoDelay>;
type LcdInterface = SpiInterface<'static, LcdDevice, Output<'static>>;
/// The concrete display type, needed because tasks cannot be generic.
pub type Lcd = Display<LcdInterface, ST7789, Output<'static>>;

/// Build and initialise the panel. Blocks for about 0.3 s (ST7789 reset and
/// sleep-out timing), so call it before the watchdog is started.
pub fn init(
    spi: LcdBus,
    dc: Output<'static>,
    rst: Output<'static>,
    buffer: &'static mut [u8],
) -> Lcd {
    let device = ExclusiveDevice::new_no_delay(spi, NoCs).unwrap();
    let interface = SpiInterface::new(device, dc, buffer);
    let mut delay = Delay;
    let mut lcd = Builder::new(ST7789, interface)
        .display_size(WIDTH, HEIGHT)
        .display_offset(OFFSET_X, OFFSET_Y)
        // These panels are wired for inverted colours; without this the screen
        // comes up as a photographic negative.
        .invert_colors(ColorInversion::Inverted)
        .reset_pin(rst)
        .init(&mut delay)
        .unwrap();
    lcd.clear(Rgb565::BLACK).ok();
    lcd
}

/// Colours.
const BG: Rgb565 = Rgb565::BLACK;
const LABEL: Rgb565 = Rgb565::new(16, 32, 16);
const VALUE: Rgb565 = Rgb565::WHITE;
const ACCENT: Rgb565 = Rgb565::new(0, 48, 28);
const WARN: Rgb565 = Rgb565::new(31, 40, 0);
const ALARM: Rgb565 = Rgb565::new(31, 0, 0);
const OK: Rgb565 = Rgb565::new(0, 40, 0);

/// Run-screen field geometry: label position, value position, cell width.
///
/// Sized for people who switch between a microscope and the screen, or
/// wear reading glasses: the two steered values (rate, strength) are in a
/// 16x30 font, everything else in 12x22, labels in 9x18. The label text is
/// per-language and comes from `text::cell_label`, indexed by cell.
struct Cell {
    x: i32,
    y: i32,
    w: u32,
    big: bool,
}

const CELLS: [Cell; 6] = [
    Cell { x: 8, y: 32, w: 112, big: true },
    Cell { x: 124, y: 32, w: 112, big: true },
    Cell { x: 8, y: 92, w: 112, big: false },
    Cell { x: 124, y: 92, w: 112, big: false },
    Cell { x: 8, y: 140, w: 112, big: false },
    Cell { x: 124, y: 140, w: 112, big: false },
];
/// Value sits this far below its label (label font is 18 px high).
const VALUE_DY: i32 = 18;
/// Height of a value cell: font height plus a little air.
const CELL_H_BIG: u32 = 34;
const CELL_H: u32 = 24;
/// Header bar.
const HEADER_H: u32 = 28;
/// Status bar.
const BAR_Y: i32 = 190;
const BAR_H: u32 = 50;
/// Menu rows. Nine rows have to fit under the header:
/// MENU_Y + MENU_ROWS * MENU_PITCH = 32 + 9 * 23 = 239 <= HEIGHT.
const MENU_Y: i32 = 32;
const MENU_PITCH: i32 = 23;
const MENU_ROW_H: u32 = 22;

type Text12 = String<12>;

fn fmt_rate(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    let _ = write!(t, "{} Hz", s.f_hz);
    t
}

fn fmt_strength(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    let _ = write!(t, "{} %", s.strength_pct);
    t
}

fn fmt_t_on(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    let _ = write!(t, "{}.{:02} ms", s.t_on_us / 1000, (s.t_on_us % 1000) / 10);
    t
}

fn fmt_vin(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    let _ = write!(t, "{}.{} V", s.vin_mv / 1000, (s.vin_mv % 1000) / 100);
    t
}

fn fmt_temp(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    match s.temp_c {
        Some(c) => {
            let _ = write!(t, "{} C", c);
        }
        None => {
            let _ = write!(t, "--");
        }
    }
    t
}

fn fmt_decay(s: &UiState) -> Text12 {
    let mut t = Text12::new();
    let _ = write!(t, "{}", text::decay(s.decay_slow, s.lang));
    t
}

fn cell_text(index: usize, s: &UiState) -> Text12 {
    match index {
        0 => fmt_rate(s),
        1 => fmt_strength(s),
        2 => fmt_t_on(s),
        3 => fmt_vin(s),
        4 => fmt_temp(s),
        _ => fmt_decay(s),
    }
}

fn status_colour(status: Status, vin_mv: u32) -> Rgb565 {
    match status {
        Status::Overcurrent | Status::Hot | Status::LowVin => ALARM,
        Status::NoPedal | Status::PedalNotAtRest | Status::Booting => WARN,
        Status::Firing => ACCENT,
        Status::Ready if vin_mv < crate::control::VIN_WARN_MV => WARN,
        Status::Ready => OK,
    }
}

/// Menu value column text for one item.
fn menu_value(item: usize, s: &Settings, pedal_raw: u16) -> Text12 {
    let mut t = Text12::new();
    match item {
        0 => {
            let _ = write!(t, "{} Hz", s.f_max_hz);
        }
        1 => {
            let _ = write!(t, "{} %", s.duty_cap_pct);
        }
        2 => {
            let _ = write!(t, "{}", text::decay(s.decay_slow, s.lang));
        }
        3 => {
            let _ = write!(t, "{}", text::on_off(s.compensate, s.lang));
        }
        4 => {
            let _ = write!(t, "{}<{}", s.pedal_min, pedal_raw);
        }
        5 => {
            let _ = write!(t, "{}<{}", s.pedal_max, pedal_raw);
        }
        6 => {
            let _ = write!(t, "{} %", s.brightness_pct);
        }
        7 => {
            let _ = write!(t, "{}", text::lang_name(s.lang));
        }
        _ => {}
    }
    t
}

struct Painter {
    lcd: Lcd,
}

impl Painter {
    fn fill(&mut self, x: i32, y: i32, w: u32, h: u32, colour: Rgb565) {
        Rectangle::new(Point::new(x, y), Size::new(w, h))
            .into_styled(PrimitiveStyle::with_fill(colour))
            .draw(&mut self.lcd)
            .ok();
    }

    fn text(&mut self, x: i32, y: i32, s: &str, style: MonoTextStyle<'static, Rgb565>) {
        Text::with_baseline(s, Point::new(x, y), style, Baseline::Top)
            .draw(&mut self.lcd)
            .ok();
    }

    /// Static parts of the run screen. Static per language: a language change
    /// repaints the whole screen, like a mode change.
    fn draw_frame(&mut self, mode: Mode, lang: Lang) {
        self.lcd.clear(BG).ok();
        self.fill(0, 0, WIDTH as u32, HEADER_H, ACCENT);
        self.text(8, 3, "GRAVER", MonoTextStyle::new(&PROFONT_18_POINT, Rgb565::BLACK));
        let label = match mode {
            Mode::Frequency => "MODE F",
            Mode::Strength => "MODE S",
        };
        self.text(
            WIDTH as i32 - 8 - 6 * 12,
            3,
            label,
            MonoTextStyle::new(&PROFONT_18_POINT, Rgb565::BLACK),
        );
        let label_style = MonoTextStyle::new(&FONT_9X18_BOLD, LABEL);
        for (index, cell) in CELLS.iter().enumerate() {
            Text::with_baseline(
                text::cell_label(index, lang),
                Point::new(cell.x, cell.y),
                label_style,
                Baseline::Top,
            )
            .draw(&mut self.lcd)
            .ok();
        }
    }

    fn draw_cell(&mut self, index: usize, text: &str) {
        let cell = &CELLS[index];
        let y = cell.y + VALUE_DY;
        // Text is drawn with its own background in one pass, and only the
        // part of the cell to the right of it is wiped: no black flash.
        let (font, h, cw) = if cell.big {
            (&PROFONT_24_POINT, CELL_H_BIG, 16)
        } else {
            (&PROFONT_18_POINT, CELL_H, 12)
        };
        let style = MonoTextStyleBuilder::new()
            .font(font)
            .text_color(VALUE)
            .background_color(BG)
            .build();
        self.text(cell.x, y, text, style);
        let used = (text.len() as u32 * cw).min(cell.w);
        self.fill(cell.x + used as i32, y, cell.w - used, h, BG);
    }

    fn draw_status(&mut self, status: Status, vin_mv: u32, lang: Lang) {
        let colour = status_colour(status, vin_mv);
        self.fill(0, BAR_Y, WIDTH as u32, BAR_H, colour);
        let text = text::status(status, lang);
        let x = (WIDTH as i32 - text.len() as i32 * 16) / 2;
        self.text(
            x.max(0),
            BAR_Y + 10,
            text,
            MonoTextStyle::new(&PROFONT_24_POINT, Rgb565::BLACK),
        );
    }

    fn draw_menu_frame(&mut self, lang: Lang) {
        self.lcd.clear(BG).ok();
        self.fill(0, 0, WIDTH as u32, HEADER_H, ACCENT);
        self.text(8, 3, text::menu_title(lang), MonoTextStyle::new(&PROFONT_18_POINT, Rgb565::BLACK));
    }

    fn draw_menu_row(&mut self, row: usize, m: &MenuState) {
        let y = MENU_Y + row as i32 * MENU_PITCH;
        let selected = m.selected == row;
        let bg = if selected { ACCENT } else { BG };
        let fg = if selected { Rgb565::BLACK } else { VALUE };
        self.fill(0, y, WIDTH as u32, MENU_ROW_H, bg);
        self.text(
            6,
            y,
            text::menu_label(row, m.settings.lang),
            MonoTextStyle::new(&PROFONT_18_POINT, fg),
        );
        let value = menu_value(row, &m.settings, m.pedal_raw);
        if !value.is_empty() {
            let colour = if selected && m.editing { WARN } else { fg };
            let x = WIDTH as i32 - 6 - value.len() as i32 * 12;
            self.text(x, y, &value, MonoTextStyle::new(&PROFONT_18_POINT, colour));
        }
    }
}

/// Repaint the screen at 10 Hz, only where something changed.
#[embassy_executor::task]
pub async fn ui_task(lcd: Lcd, mut backlight: SimplePwm<'static, TIM4>) {
    let mut painter = Painter { lcd };
    let mut rx = crate::control::UI.receiver().unwrap();
    let mut shown: Option<UiState> = None;
    let mut brightness = 0u8;

    backlight.ch1().enable();

    let mut ticker = Ticker::every(REFRESH);
    loop {
        ticker.next().await;
        let Some(mut state) = rx.try_get() else { continue };

        // Display hysteresis: the slow readings keep their shown value until
        // they move by more than the noise, so the cells stay still.
        if let Some(prev) = shown.as_ref() {
            if state.vin_mv.abs_diff(prev.vin_mv) < VIN_HYST_MV {
                state.vin_mv = prev.vin_mv;
            }
            if state.t_on_us.abs_diff(prev.t_on_us) < T_ON_HYST_US {
                state.t_on_us = prev.t_on_us;
            }
            if let (Some(t), Some(p)) = (state.temp_c, prev.temp_c)
                && t.abs_diff(p) < 2
            {
                state.temp_c = Some(p);
            }
        }

        if state.brightness_pct != brightness {
            brightness = state.brightness_pct;
            let max = backlight.max_duty_cycle();
            backlight
                .ch1()
                .set_duty_cycle((max * brightness as u32 / 100).min(max));
        }

        match (&state.menu, shown.as_ref().and_then(|s| s.menu)) {
            // menu just opened, or the screen kind changed
            (Some(menu), None) => {
                painter.draw_menu_frame(state.lang);
                for row in 0..MENU_ROWS {
                    painter.draw_menu_row(row, menu);
                }
            }
            (Some(menu), Some(prev)) => {
                // A new language changes every label, so nothing is reusable.
                let lang_changed = prev.settings.lang != menu.settings.lang;
                if lang_changed {
                    painter.draw_menu_frame(menu.settings.lang);
                }
                for row in 0..MENU_ROWS {
                    let was_sel = prev.selected == row;
                    let is_sel = menu.selected == row;
                    let changed = lang_changed
                        || was_sel != is_sel
                        || (is_sel && prev.editing != menu.editing)
                        || menu_value(row, &prev.settings, prev.pedal_raw)
                            != menu_value(row, &menu.settings, menu.pedal_raw);
                    if changed {
                        painter.draw_menu_row(row, menu);
                    }
                }
            }
            (None, Some(_)) => {
                painter.draw_frame(state.mode, state.lang);
                for index in 0..CELLS.len() {
                    painter.draw_cell(index, &cell_text(index, &state));
                }
                painter.draw_status(state.status, state.vin_mv, state.lang);
            }
            (None, None) => {
                // The labels are part of the frame, so a language change needs
                // the same full repaint a mode change does.
                let full = match shown.as_ref() {
                    None => true,
                    Some(prev) => prev.mode != state.mode || prev.lang != state.lang,
                };
                if full {
                    painter.draw_frame(state.mode, state.lang);
                }
                for index in 0..CELLS.len() {
                    let text = cell_text(index, &state);
                    let redraw = full
                        || shown
                            .as_ref()
                            .map(|prev| cell_text(index, prev) != text)
                            .unwrap_or(true);
                    if redraw {
                        painter.draw_cell(index, &text);
                    }
                }
                let redraw_status = full
                    || shown
                        .as_ref()
                        .map(|prev| prev.status != state.status)
                        .unwrap_or(true);
                if redraw_status {
                    painter.draw_status(state.status, state.vin_mv, state.lang);
                }
            }
        }

        shown = Some(state);
    }
}
