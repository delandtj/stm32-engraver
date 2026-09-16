//! Bench helper, only compiled with `--features bench`.
//!
//! Fires a fixed burst at boot, with no pedal and no display needed, so the
//! strike path can be scoped with a Blackpill, a FET module and the coil. The
//! burst runs once, before the control loop takes over; after it the firmware
//! behaves normally (and, with no pedal plugged in, will not fire again).
//!
//! Safety: the burst ignores the pedal rules on purpose. Never build with this
//! feature for a unit that goes to a class.

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Sender;
use embassy_time::{Duration, Timer};

use crate::strike::StrikeParams;

/// Pulses in the burst.
pub const BENCH_PULSES: u32 = 20;
/// On-time of each pulse, microseconds.
pub const BENCH_T_ON_US: u32 = 3_000;
/// Burst rate, Hz.
pub const BENCH_F_HZ: u16 = 5;
/// Quiet time before the burst, so a scope can be armed.
const BENCH_DELAY: Duration = Duration::from_secs(3);

/// Run the burst once.
pub async fn run(strike: &Sender<'static, CriticalSectionRawMutex, StrikeParams, 2>) {
    defmt::warn!(
        "BENCH BUILD: firing {} pulses of {} us at {} Hz in {} s",
        BENCH_PULSES,
        BENCH_T_ON_US,
        BENCH_F_HZ,
        BENCH_DELAY.as_secs()
    );
    Timer::after(BENCH_DELAY).await;

    strike.send(StrikeParams {
        f_hz: BENCH_F_HZ,
        t_on_us: BENCH_T_ON_US,
        firing: true,
    });
    let millis = BENCH_PULSES as u64 * 1000 / BENCH_F_HZ as u64;
    Timer::after(Duration::from_millis(millis)).await;
    strike.send(StrikeParams {
        f_hz: BENCH_F_HZ,
        t_on_us: BENCH_T_ON_US,
        firing: false,
    });
    defmt::info!("BENCH BUILD: burst done");
}
