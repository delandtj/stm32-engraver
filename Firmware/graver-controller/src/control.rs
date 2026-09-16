//! Control model, menu and safety state machine.
//!
//! This is the only task that decides whether the coil may be energised. It
//! owns the settings, reacts to input events, turns pedal travel into strike
//! parameters and publishes both the strike command and the screen contents.

use embassy_futures::select::{Either, select};
use embassy_stm32::gpio::Output;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Watch;
use embassy_time::{Duration, Instant, Timer};

use crate::analog::{self, PedalCal, Readings};
use crate::input::{EVENTS, InputEvent};
use crate::settings::{Mode, Settings, Store};
use crate::strike::{CLEAR_FAULT, COMMAND, OVERCURRENT, StrikeParams};

/// Strike rate limits, ADR 0001 "Ranges".
pub const F_MIN_HZ: u16 = 1;
pub const F_MAX_LIMIT_HZ: u16 = 60;
/// Coil on-time limits, microseconds.
pub const T_ON_MIN_US: u32 = 500;
pub const T_ON_MAX_US: u32 = 15_000;
/// On-time resolution.
pub const T_ON_STEP_US: u32 = 10;
/// Hard ceiling on t_on * f.
pub const DUTY_CAP_LIMIT_PCT: u32 = 35;
/// Supply compensation keeps t_on * VIN constant at this reference.
pub const V_NOMINAL_MV: u32 = 24_000;
/// Below this the firmware refuses to fire ("no brick").
#[cfg(not(feature = "low-vin"))]
pub const VIN_MIN_FIRE_MV: u32 = 15_000;
/// Bench rig with a 12 V test supply and a 30 V-class FET module: fire from
/// 10 V. Never for the production board. Selected with `--features low-vin`.
#[cfg(feature = "low-vin")]
pub const VIN_MIN_FIRE_MV: u32 = 10_000;
/// Below this the hits are weak and the screen says so.
pub const VIN_WARN_MV: u32 = 18_000;
/// Handpiece over-temperature cut-out.
pub const TEMP_MAX_C: i16 = 70;
/// Settle time before settings go to flash.
const SAVE_DELAY: Duration = Duration::from_secs(3);
/// Control loop period when no input event arrives.
const TICK: Duration = Duration::from_millis(10);

/// What the status line shows, worst case first.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Status {
    /// Waiting for the first measurements.
    Booting,
    /// The break input tripped; latched until the pedal is released.
    Overcurrent,
    /// Nothing plugged into the pedal jack, or a mono plug.
    NoPedal,
    /// VIN below 15 V: no brick, or a brick that collapsed.
    LowVin,
    /// NTC over the limit.
    Hot,
    /// The pedal was not at rest at power-up or plug-in.
    PedalNotAtRest,
    /// Armed, pedal down, striking.
    Firing,
    /// Armed and waiting for the pedal.
    Ready,
}

/// Menu entries, in display order.
pub const MENU_ITEMS: [&str; 8] = [
    "Max frequency",
    "Duty cap",
    "Decay",
    "Supply comp",
    "Heel cal",
    "Toe cal",
    "Brightness",
    "Exit",
];
const MENU_MAX_FREQ: usize = 0;
const MENU_DUTY: usize = 1;
const MENU_DECAY: usize = 2;
const MENU_COMP: usize = 3;
const MENU_HEEL: usize = 4;
const MENU_TOE: usize = 5;
const MENU_BRIGHT: usize = 6;
const MENU_EXIT: usize = 7;

/// Menu overlay state, or None for the run screen.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct MenuState {
    pub selected: usize,
    pub editing: bool,
    /// Copy of the live settings so the screen can render every value.
    pub settings: Settings,
    /// Live pedal counts, shown while calibrating.
    pub pedal_raw: u16,
}

/// Everything the display needs. Compared field by field by the UI task.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct UiState {
    pub mode: Mode,
    pub f_hz: u16,
    pub strength_pct: u8,
    pub t_on_us: u32,
    pub vin_mv: u32,
    pub temp_c: Option<i16>,
    pub decay_slow: bool,
    pub status: Status,
    pub brightness_pct: u8,
    pub menu: Option<MenuState>,
}

impl Default for UiState {
    fn default() -> Self {
        Self {
            mode: Mode::Frequency,
            f_hz: 0,
            strength_pct: 0,
            t_on_us: 0,
            vin_mv: 0,
            temp_c: None,
            decay_slow: false,
            status: Status::Booting,
            brightness_pct: 80,
            menu: None,
        }
    }
}

/// Control task -> UI task.
pub static UI: Watch<CriticalSectionRawMutex, UiState, 2> = Watch::new();

/// Map pedal travel (0..1000) onto an inclusive integer range.
fn map_pedal(travel: u16, lo: u32, hi: u32) -> u32 {
    let t = travel.min(analog::PEDAL_FULL) as u32;
    lo + (hi - lo) * t / analog::PEDAL_FULL as u32
}

/// Strength percent -> coil on-time, rounded to the step size.
fn t_on_from_strength(pct: u8) -> u32 {
    let span = T_ON_MAX_US - T_ON_MIN_US;
    let raw = T_ON_MIN_US + span * pct.min(100) as u32 / 100;
    (raw / T_ON_STEP_US) * T_ON_STEP_US
}

/// Apply supply compensation and the duty cap. Returns the on-time actually
/// used, which is what the display shows.
fn limit_t_on(t_on_us: u32, f_hz: u16, vin_mv: u32, compensate: bool, duty_cap_pct: u32) -> u32 {
    let mut t = t_on_us;
    if compensate {
        // Constant volt-seconds: a 30 V brick fires a shorter pulse than a
        // 24 V one for the same setting (ADR 0001, "Supply compensation").
        let vin = vin_mv.max(VIN_MIN_FIRE_MV);
        t = t * V_NOMINAL_MV / vin;
    }
    // t_on * f <= duty  =>  t_on_us <= duty_pct * 10_000 / f
    let cap = duty_cap_pct.min(DUTY_CAP_LIMIT_PCT) * 10_000 / f_hz.max(1) as u32;
    t.clamp(T_ON_MIN_US, T_ON_MAX_US.min(cap.max(T_ON_MIN_US)))
}

/// Strength percent that the given on-time corresponds to, for the display.
fn strength_from_t_on(t_on_us: u32) -> u8 {
    let span = T_ON_MAX_US - T_ON_MIN_US;
    ((t_on_us.saturating_sub(T_ON_MIN_US) * 100 + span / 2) / span).min(100) as u8
}

/// The control task. Owns settings, the decay-mode pin and the safety rules.
#[embassy_executor::task]
pub async fn control_task(
    mut store: Store,
    mut settings: Settings,
    mut decay: Output<'static>,
) {
    let mut analog_rx = analog::ANALOG.receiver().unwrap();
    let mut fault_rx = OVERCURRENT.receiver().unwrap();
    let cal_tx = analog::CALIBRATION.sender();
    let strike_tx = COMMAND.sender();
    let ui_tx = UI.sender();

    let mut menu: Option<MenuState> = None;
    let mut readings = Readings::default();
    let mut rest_seen = false;
    let mut faulted = false;
    let mut dirty_since: Option<Instant> = None;
    let mut last_ui = UiState::default();
    let mut last_status = Status::Booting;
    let mut last_command: Option<StrikeParams> = None;

    decay.set_level(settings.decay_slow.into());
    cal_tx.send(PedalCal {
        min: settings.pedal_min,
        max: settings.pedal_max,
    });
    ui_tx.send(last_ui);

    #[cfg(feature = "bench")]
    crate::bench::run(&strike_tx).await;

    loop {
        match select(EVENTS.receive(), Timer::after(TICK)).await {
            Either::First(event) => {
                if handle_event(event, &mut settings, &mut menu, readings.pedal_raw) {
                    dirty_since = Some(Instant::now());
                    decay.set_level(settings.decay_slow.into());
                    cal_tx.send(PedalCal {
                        min: settings.pedal_min,
                        max: settings.pedal_max,
                    });
                }
            }
            Either::Second(()) => {}
        }

        if let Some(r) = analog_rx.try_changed() {
            readings = r;
        }
        if let Some(f) = fault_rx.try_changed() {
            if f && !faulted {
                defmt::warn!("control: overcurrent latched");
            }
            faulted = f;
        }

        // --- safety rules, ADR 0001 "Safety rules" --------------------------
        if !readings.pedal_present {
            // Unplugged: the next plug-in has to prove the pedal is at rest.
            rest_seen = false;
        } else if readings.pedal == 0 {
            rest_seen = true;
            if faulted {
                // The operator lifted the foot: unlatch the overcurrent.
                CLEAR_FAULT.signal(());
            }
        }

        let vin_ok = readings.vin_mv >= VIN_MIN_FIRE_MV;
        let temp_ok = readings.temp_c.is_none_or(|t| t < TEMP_MAX_C);
        let armed = readings.pedal_present && rest_seen && vin_ok && temp_ok && !faulted;
        let firing = armed && readings.pedal > 0 && menu.is_none();

        // --- control model --------------------------------------------------
        let (f_hz, requested_t_on) = match settings.mode {
            Mode::Frequency => (
                map_pedal(readings.pedal, F_MIN_HZ as u32, settings.f_max_hz as u32) as u16,
                t_on_from_strength(settings.strength_pct),
            ),
            Mode::Strength => (
                settings.knob_f_hz.min(settings.f_max_hz),
                t_on_from_strength(map_pedal(readings.pedal, 0, 100) as u8),
            ),
        };
        let t_on_us = limit_t_on(
            requested_t_on,
            f_hz,
            readings.vin_mv,
            settings.compensate,
            settings.duty_cap_pct as u32,
        );

        // Only publish real changes: every send wakes the strike task.
        let command = StrikeParams {
            f_hz: f_hz.max(F_MIN_HZ),
            t_on_us,
            firing,
        };
        if Some(command) != last_command {
            strike_tx.send(command);
            last_command = Some(command);
        }

        let status = if faulted {
            Status::Overcurrent
        } else if !readings.pedal_present {
            Status::NoPedal
        } else if !vin_ok {
            Status::LowVin
        } else if !temp_ok {
            Status::Hot
        } else if !rest_seen {
            Status::PedalNotAtRest
        } else if firing {
            Status::Firing
        } else {
            Status::Ready
        };
        if status != last_status {
            defmt::info!("status: {} -> {}", last_status, status);
            last_status = status;
        }

        if let Some(m) = menu.as_mut() {
            m.settings = settings;
            m.pedal_raw = readings.pedal_raw;
        }

        let ui = UiState {
            mode: settings.mode,
            f_hz,
            strength_pct: strength_from_t_on(t_on_us),
            t_on_us,
            vin_mv: readings.vin_mv,
            temp_c: readings.temp_c,
            decay_slow: settings.decay_slow,
            status,
            brightness_pct: settings.brightness_pct,
            menu,
        };
        if ui != last_ui {
            ui_tx.send(ui);
            last_ui = ui;
        }

        // --- deferred flash write -------------------------------------------
        if let Some(at) = dirty_since {
            // Never write while the coil is being driven: a flash write stalls
            // the core and would stretch a strike period.
            if !firing && at.elapsed() >= SAVE_DELAY {
                store.save(settings);
                dirty_since = None;
            }
        }

        crate::heartbeat();
    }
}

/// Apply one input event. Returns true when a persisted setting changed.
fn handle_event(
    event: InputEvent,
    settings: &mut Settings,
    menu: &mut Option<MenuState>,
    pedal_raw: u16,
) -> bool {
    match (event, menu.is_some()) {
        // --- run screen ------------------------------------------------------
        (InputEvent::Turn(steps), false) => {
            match settings.mode {
                Mode::Frequency => {
                    let v = settings.strength_pct as i32 + steps;
                    settings.strength_pct = v.clamp(0, 100) as u8;
                }
                Mode::Strength => {
                    let v = settings.knob_f_hz as i32 + steps;
                    settings.knob_f_hz = v.clamp(F_MIN_HZ as i32, settings.f_max_hz as i32) as u16;
                }
            }
            true
        }
        (InputEvent::ShortPress, false) => {
            settings.mode = settings.mode.toggled();
            defmt::info!("mode: {}", settings.mode);
            true
        }
        (InputEvent::LongPress, false) => {
            *menu = Some(MenuState {
                selected: 0,
                editing: false,
                settings: *settings,
                pedal_raw,
            });
            defmt::info!("menu opened");
            false
        }
        // --- menu ------------------------------------------------------------
        (InputEvent::Turn(steps), true) => {
            let m = menu.as_mut().unwrap();
            if !m.editing {
                let n = MENU_ITEMS.len() as i32;
                let sel = (m.selected as i32 + steps).clamp(0, n - 1);
                m.selected = sel as usize;
                return false;
            }
            match m.selected {
                MENU_MAX_FREQ => {
                    let v = settings.f_max_hz as i32 + steps;
                    settings.f_max_hz = v.clamp(5, F_MAX_LIMIT_HZ as i32) as u16;
                    settings.knob_f_hz = settings.knob_f_hz.min(settings.f_max_hz);
                }
                MENU_DUTY => {
                    let v = settings.duty_cap_pct as i32 + steps;
                    settings.duty_cap_pct = v.clamp(5, DUTY_CAP_LIMIT_PCT as i32) as u8;
                }
                MENU_BRIGHT => {
                    let v = settings.brightness_pct as i32 + steps;
                    settings.brightness_pct = v.clamp(10, 100) as u8;
                }
                _ => return false,
            }
            true
        }
        (InputEvent::ShortPress, true) => {
            let m = menu.as_mut().unwrap();
            match m.selected {
                MENU_DECAY => {
                    settings.decay_slow = !settings.decay_slow;
                    defmt::info!("decay slow: {}", settings.decay_slow);
                    true
                }
                MENU_COMP => {
                    settings.compensate = !settings.compensate;
                    defmt::info!("supply compensation: {}", settings.compensate);
                    true
                }
                MENU_HEEL => {
                    settings.pedal_min = pedal_raw;
                    defmt::info!("pedal heel = {}", pedal_raw);
                    true
                }
                MENU_TOE => {
                    settings.pedal_max = pedal_raw;
                    defmt::info!("pedal toe = {}", pedal_raw);
                    true
                }
                MENU_EXIT => {
                    *menu = None;
                    defmt::info!("menu closed");
                    false
                }
                _ => {
                    m.editing = !m.editing;
                    false
                }
            }
        }
        (InputEvent::LongPress, true) => {
            *menu = None;
            defmt::info!("menu closed");
            false
        }
    }
}
