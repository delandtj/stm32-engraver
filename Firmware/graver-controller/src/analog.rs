//! ADC task: pedal, pedal ring sense, VIN, NTC and coil current.
//!
//! One blocking sweep of five channels every 5 ms (200 Hz). Everything is
//! averaged with a first-order IIR filter before it is published, so the
//! control task and the display see quiet numbers.
//!
//! Scaling constants come from ADR 0001 "Component Breakdown". They are the
//! only place where board values live; a hardware revision changes them here.

use embassy_stm32::Peri;
use embassy_stm32::adc::{Adc, SampleTime};
use embassy_stm32::peripherals::{ADC1, PA1, PA2, PA6, PB0, PB1};
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Watch;
use embassy_time::{Duration, Ticker};

/// ADC reference. The board runs VDDA off the 3.3 V LDO.
pub const VREF_MV: u32 = 3300;
/// 12-bit conversions.
pub const ADC_MAX: u32 = 4095;

/// VIN divider on the board: 100k over 8.2k, so VIN = Vadc * 108.2 / 8.2.
#[cfg(not(feature = "vin-div-10k"))]
pub const VIN_DIV_NUM: u32 = 1082;
#[cfg(not(feature = "vin-div-10k"))]
pub const VIN_DIV_DEN: u32 = 82;
/// Bench rig divider: 100k over 10k, VIN = Vadc * 110 / 10, saturates at
/// 36 V. Selected with `--features vin-div-10k`.
#[cfg(feature = "vin-div-10k")]
pub const VIN_DIV_NUM: u32 = 110;
#[cfg(feature = "vin-div-10k")]
pub const VIN_DIV_DEN: u32 = 10;

/// Coil current sense: 1 ohm shunt into a gain-of-11 amplifier.
/// 1 A would be 11 V, so the usable range stops at about 0.3 A.
pub const SHUNT_MILLIOHM: u32 = 1000;
pub const SENSE_GAIN: u32 = 11;

/// NTC divider: 10k from 3V3 to the pin, NTC from the pin to GND.
pub const NTC_PULLUP_OHM: f32 = 10_000.0;
/// Assumed handpiece thermistor: 10k at 25 C, B25/50 = 3950 (10k B3950).
pub const NTC_R25_OHM: f32 = 10_000.0;
pub const NTC_BETA: f32 = 3950.0;
const NTC_T0_K: f32 = 298.15;
const KELVIN_OFFSET: f32 = 273.15;
/// Above this the NTC pin is treated as open (no thermistor fitted).
pub const NTC_OPEN_MV: u32 = 3150;
/// Below this it is treated as shorted, which is also "do not trust it".
pub const NTC_SHORT_MV: u32 = 60;

/// Ring sense threshold. An expression pedal lifts the ring to about 3 V
/// through the 1k series resistor; the jack's normalling contact (or a mono
/// plug) ties it to ground. Anything below this is "no pedal".
///
/// Bench note: a cheap breadboard jack often has no normalling contact, so the
/// ring floats when nothing is plugged in. Wire ring to GND through 10k on the
/// bench, otherwise the firmware may believe a pedal is present.
pub const PEDAL_RING_PRESENT_MV: u32 = 1000;

/// Pedal travel is reported on this scale.
pub const PEDAL_FULL: u16 = 1000;
/// Counts below this fraction of travel are "at rest".
pub const PEDAL_DEADBAND: u16 = 40;

/// IIR smoothing: new = (old * (N-1) + sample) / N.
const FILTER_N: u32 = 8;
/// Pedal follows the foot, so it is filtered lighter than the rails.
const PEDAL_FILTER_N: u32 = 4;

/// Sample period.
const PERIOD: Duration = Duration::from_hz(200);

/// Pedal heel/toe calibration, published by the control task from settings.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct PedalCal {
    /// Raw ADC counts at the heel (rest) position.
    pub min: u16,
    /// Raw ADC counts at the toe (full) position.
    pub max: u16,
}

impl Default for PedalCal {
    fn default() -> Self {
        // Conservative default: ignore the bottom and top 5% of the range so
        // an uncalibrated pedal still reaches both ends.
        Self { min: 200, max: 3900 }
    }
}

/// One published set of measurements.
#[derive(Clone, Copy, Default, PartialEq, Eq, defmt::Format)]
pub struct Readings {
    /// Filtered raw pedal counts, for the calibration menu.
    pub pedal_raw: u16,
    /// Pedal travel, 0..PEDAL_FULL, after calibration and deadband.
    pub pedal: u16,
    /// True when the ring sense says an expression pedal is plugged in.
    pub pedal_present: bool,
    /// Supply voltage in millivolts.
    pub vin_mv: u32,
    /// Coil current in milliamps (saturates around 300 mA, by design).
    pub coil_ma: u32,
    /// Handpiece temperature, None when no NTC is fitted.
    pub temp_c: Option<i16>,
}

/// ADC task -> everyone else.
pub static ANALOG: Watch<CriticalSectionRawMutex, Readings, 4> = Watch::new();
/// Control task -> ADC task.
pub static CALIBRATION: Watch<CriticalSectionRawMutex, PedalCal, 2> = Watch::new();

/// Convert raw counts to millivolts at the pin.
pub const fn counts_to_mv(counts: u32) -> u32 {
    counts * VREF_MV / ADC_MAX
}

/// Convert pin millivolts to supply millivolts.
pub const fn vin_from_mv(mv: u32) -> u32 {
    mv * VIN_DIV_NUM / VIN_DIV_DEN
}

/// Convert amplifier output millivolts to coil milliamps.
pub const fn coil_ma_from_mv(mv: u32) -> u32 {
    mv * 1000 / (SENSE_GAIN * SHUNT_MILLIOHM)
}

/// Beta-equation thermistor conversion. None when the pin looks open or
/// shorted, which is how "no NTC in this handpiece" is detected.
pub fn ntc_temp_c(mv: u32) -> Option<i16> {
    if !(NTC_SHORT_MV..=NTC_OPEN_MV).contains(&mv) {
        return None;
    }
    let mv = mv as f32;
    let r = NTC_PULLUP_OHM * mv / (VREF_MV as f32 - mv);
    let inv_t = 1.0 / NTC_T0_K + libm::logf(r / NTC_R25_OHM) / NTC_BETA;
    Some((1.0 / inv_t - KELVIN_OFFSET) as i16)
}

/// Map raw pedal counts to 0..PEDAL_FULL with a deadband at the heel.
pub fn pedal_travel(raw: u16, cal: PedalCal) -> u16 {
    let (min, max) = (cal.min.min(cal.max), cal.max.max(cal.min));
    if max <= min + 100 {
        return 0;
    }
    let raw = raw.clamp(min, max);
    let span = (max - min) as u32;
    let travel = ((raw - min) as u32 * PEDAL_FULL as u32 / span) as u16;
    if travel <= PEDAL_DEADBAND {
        0
    } else {
        travel
    }
}

fn iir(state: &mut u32, sample: u32, n: u32) {
    *state = (*state * (n - 1) + sample) / n;
}

/// Sample the analog inputs forever.
#[allow(clippy::too_many_arguments)]
#[embassy_executor::task]
pub async fn analog_task(
    adc1: Peri<'static, ADC1>,
    pedal: Peri<'static, PA1>,
    ring: Peri<'static, PA2>,
    coil: Peri<'static, PA6>,
    vin: Peri<'static, PB0>,
    ntc: Peri<'static, PB1>,
) {
    let mut adc = Adc::new(adc1);
    let mut pedal = pedal;
    let mut ring = ring;
    let mut coil = coil;
    let mut vin = vin;
    let mut ntc = ntc;

    // 480 cycles at ~21 MHz ADC clock is about 23 us per channel: slow enough
    // for the 100k-class source impedance of the dividers, cheap enough at
    // 200 Hz.
    let st = SampleTime::CYCLES480;

    let tx = ANALOG.sender();
    let mut cal_rx = CALIBRATION.receiver().unwrap();
    let mut cal = cal_rx.try_get().unwrap_or_default();

    let mut f_pedal = adc.blocking_read(&mut pedal, st) as u32;
    let mut f_ring = adc.blocking_read(&mut ring, st) as u32;
    let mut f_vin = adc.blocking_read(&mut vin, st) as u32;
    let mut f_ntc = adc.blocking_read(&mut ntc, st) as u32;
    let mut f_coil = 0u32;

    let mut ticker = Ticker::every(PERIOD);
    loop {
        ticker.next().await;
        if let Some(new) = cal_rx.try_changed() {
            cal = new;
        }

        iir(&mut f_pedal, adc.blocking_read(&mut pedal, st) as u32, PEDAL_FILTER_N);
        iir(&mut f_ring, adc.blocking_read(&mut ring, st) as u32, FILTER_N);
        iir(&mut f_coil, adc.blocking_read(&mut coil, st) as u32, FILTER_N);
        iir(&mut f_vin, adc.blocking_read(&mut vin, st) as u32, FILTER_N);
        iir(&mut f_ntc, adc.blocking_read(&mut ntc, st) as u32, FILTER_N);

        let pedal_raw = f_pedal as u16;
        let ring_mv = counts_to_mv(f_ring);
        let readings = Readings {
            pedal_raw,
            pedal: pedal_travel(pedal_raw, cal),
            pedal_present: ring_mv >= PEDAL_RING_PRESENT_MV,
            vin_mv: vin_from_mv(counts_to_mv(f_vin)),
            coil_ma: coil_ma_from_mv(counts_to_mv(f_coil)),
            temp_c: ntc_temp_c(counts_to_mv(f_ntc)),
        };
        tx.send(readings);
    }
}
