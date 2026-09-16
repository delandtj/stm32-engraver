//! Front-panel input: one event stream, two possible backends.
//!
//! The rest of the firmware only ever sees [`InputEvent`]. Which backend
//! produces it is a build-time choice:
//!
//! * default: an EC11 rotary encoder read by TIM3 in hardware quadrature mode
//!   (PB4 = A, PB5 = B) plus the push switch on PB7.
//! * feature "buttons": three tactile switches to ground on the very same
//!   pins, for bench work before an encoder is available. PB4 = up,
//!   PB5 = down, PB7 = push. No rewiring is needed later.
//!
//! PB4 is NJTRST at reset. The firmware never enables JTAG (SWD only), and
//! configuring the pin as AF2/input releases it, so it is free to use.
//! The Blackpill's own KEY button on PA0 is deliberately unused so the bench
//! pin map and the PCB pin map are identical.

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use embassy_time::{Duration, Instant};

/// What the UI reacts to.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum InputEvent {
    /// Detents since the last event, signed. Already accelerated.
    Turn(i32),
    /// Push released before the long-press threshold.
    ShortPress,
    /// Push held past the long-press threshold.
    LongPress,
}

/// Input backend -> control task.
pub static EVENTS: Channel<CriticalSectionRawMutex, InputEvent, 16> = Channel::new();

/// Quadrature counts per detent.
///
/// The production encoder is an Alps EC11E15244G1: 30 detents, 15 pulses per
/// revolution. In x4 decoding that is 60 counts per revolution, so 2 counts
/// per detent. A 24-pulse / 24-detent part (Bourns PEC11R-4220F-S0024) or a
/// generic 20/20 EC11 gives 4 counts per detent instead.
#[cfg_attr(feature = "buttons", allow(dead_code))]
pub const COUNTS_PER_DETENT: i32 = 2;

/// Poll period for both backends.
const POLL: Duration = Duration::from_millis(5);
/// Push must be stable this long before an edge counts.
const DEBOUNCE_MS: u64 = 20;
/// Hold longer than this and it is a long press.
pub const LONG_PRESS_MS: u64 = 600;

/// Turn acceleration: detents inside this window are multiplied.
const FAST_TURN_MS: u64 = 40;
const MEDIUM_TURN_MS: u64 = 100;
const FAST_FACTOR: i32 = 8;
const MEDIUM_FACTOR: i32 = 3;

/// Multiply a detent step by how fast the knob is being turned.
fn accelerate(step: i32, since_ms: u64) -> i32 {
    let factor = if since_ms <= FAST_TURN_MS {
        FAST_FACTOR
    } else if since_ms <= MEDIUM_TURN_MS {
        MEDIUM_FACTOR
    } else {
        1
    };
    step * factor
}

/// Debounced active-low push button that emits short and long presses.
struct PushButton {
    stable_low: bool,
    last_edge: Instant,
    pressed_at: Option<Instant>,
    long_sent: bool,
}

impl PushButton {
    fn new() -> Self {
        Self {
            stable_low: false,
            last_edge: Instant::now(),
            pressed_at: None,
            long_sent: false,
        }
    }

    /// Feed the raw pin level; returns an event when one is due.
    fn update(&mut self, is_low: bool, now: Instant) -> Option<InputEvent> {
        if is_low != self.stable_low {
            if (now - self.last_edge).as_millis() >= DEBOUNCE_MS {
                self.stable_low = is_low;
                self.last_edge = now;
                if is_low {
                    self.pressed_at = Some(now);
                    self.long_sent = false;
                } else if let Some(at) = self.pressed_at.take()
                    && !self.long_sent
                    && (now - at).as_millis() < LONG_PRESS_MS
                {
                    return Some(InputEvent::ShortPress);
                }
            }
            return None;
        }
        self.last_edge = now;
        if let Some(at) = self.pressed_at
            && !self.long_sent
            && (now - at).as_millis() >= LONG_PRESS_MS
        {
            self.long_sent = true;
            return Some(InputEvent::LongPress);
        }
        None
    }
}

#[cfg(not(feature = "buttons"))]
mod backend {
    use embassy_stm32::Peri;
    use embassy_stm32::gpio::{Input, Pull};
    use embassy_stm32::peripherals::{PB4, PB5, PB7, TIM3};
    use embassy_stm32::timer::qei::{Config as QeiConfig, Qei, QeiMode};
    use embassy_time::{Instant, Ticker};

    use super::{COUNTS_PER_DETENT, EVENTS, InputEvent, POLL, PushButton, accelerate};

    /// Read the encoder with TIM3 and the push switch on PB7.
    #[embassy_executor::task]
    pub async fn input_task(
        tim3: Peri<'static, TIM3>,
        a: Peri<'static, PB4>,
        b: Peri<'static, PB5>,
        push: Peri<'static, PB7>,
    ) {
        // Hardware quadrature decoding (mode 3 = count on both edges of both
        // channels, x4). The 10k/10 nF RC on the board debounces A and B; the
        // internal pull-ups keep the open-collector-style contacts defined.
        let qei = Qei::new(
            tim3,
            a,
            b,
            QeiConfig {
                ch1_pull: Pull::Up,
                ch2_pull: Pull::Up,
                mode: QeiMode::Mode3,
                auto_reload: u16::MAX,
            },
        );
        let push = Input::new(push, Pull::Up);
        let mut button = PushButton::new();

        let mut last_count = qei.count();
        // Counts that did not add up to a whole detent yet. Never dropped, so
        // slow turns are not lost between polls.
        let mut remainder: i32 = 0;
        let mut last_turn = Instant::now();

        let mut ticker = Ticker::every(POLL);
        loop {
            ticker.next().await;
            let now = Instant::now();

            let count = qei.count();
            let delta = count.wrapping_sub(last_count) as i16 as i32;
            last_count = count;

            if delta != 0 {
                remainder += delta;
                let detents = remainder / COUNTS_PER_DETENT;
                remainder -= detents * COUNTS_PER_DETENT;
                if detents != 0 {
                    let step = accelerate(detents, (now - last_turn).as_millis());
                    last_turn = now;
                    let _ = EVENTS.try_send(InputEvent::Turn(step));
                }
            }

            if let Some(ev) = button.update(push.is_low(), now) {
                let _ = EVENTS.try_send(ev);
            }
        }
    }
}

#[cfg(feature = "buttons")]
mod backend {
    use embassy_stm32::Peri;
    use embassy_stm32::gpio::{Input, Pull};
    use embassy_stm32::peripherals::{PB4, PB5, PB7, TIM3};
    use embassy_time::{Instant, Ticker};

    use super::{EVENTS, InputEvent, POLL, PushButton, accelerate};

    /// Hold a direction button this long before it repeats.
    const REPEAT_DELAY_MS: u64 = 400;
    /// Then one detent every this many milliseconds (10 per second).
    const REPEAT_PERIOD_MS: u64 = 100;
    /// Same debounce as the push button.
    const DEBOUNCE_MS: u64 = 20;

    /// Debounced direction button with auto-repeat.
    struct Repeater {
        stable_low: bool,
        last_edge: Instant,
        pressed_at: Option<Instant>,
        next_repeat: Instant,
    }

    impl Repeater {
        fn new() -> Self {
            Self {
                stable_low: false,
                last_edge: Instant::now(),
                pressed_at: None,
                next_repeat: Instant::now(),
            }
        }

        /// Returns true when one detent should be emitted now.
        fn update(&mut self, is_low: bool, now: Instant) -> bool {
            if is_low != self.stable_low {
                if (now - self.last_edge).as_millis() < DEBOUNCE_MS {
                    return false;
                }
                self.stable_low = is_low;
                self.last_edge = now;
                if is_low {
                    self.pressed_at = Some(now);
                    self.next_repeat = now + embassy_time::Duration::from_millis(REPEAT_DELAY_MS);
                    return true;
                }
                self.pressed_at = None;
                return false;
            }
            self.last_edge = now;
            if self.pressed_at.is_some() && now >= self.next_repeat {
                self.next_repeat = now + embassy_time::Duration::from_millis(REPEAT_PERIOD_MS);
                return true;
            }
            false
        }

        /// Milliseconds the button has been held, 0 when released.
        fn held_ms(&self, now: Instant) -> u64 {
            self.pressed_at.map_or(0, |at| (now - at).as_millis())
        }
    }

    /// Read three tactile buttons on the encoder pins. TIM3 stays unused.
    #[embassy_executor::task]
    pub async fn input_task(
        _tim3: Peri<'static, TIM3>,
        up: Peri<'static, PB4>,
        down: Peri<'static, PB5>,
        push: Peri<'static, PB7>,
    ) {
        let up = Input::new(up, Pull::Up);
        let down = Input::new(down, Pull::Up);
        let push = Input::new(push, Pull::Up);

        let mut up_state = Repeater::new();
        let mut down_state = Repeater::new();
        let mut button = PushButton::new();

        defmt::info!("input backend: three buttons on PB4/PB5/PB7");

        let mut ticker = Ticker::every(POLL);
        loop {
            ticker.next().await;
            let now = Instant::now();

            // While a direction button is held the repeat rate is fixed, so
            // acceleration is derived from how long it has been down.
            if up_state.update(up.is_low(), now) {
                let held = up_state.held_ms(now);
                let _ = EVENTS.try_send(InputEvent::Turn(accelerate_hold(held)));
            }
            if down_state.update(down.is_low(), now) {
                let held = down_state.held_ms(now);
                let _ = EVENTS.try_send(InputEvent::Turn(-accelerate_hold(held)));
            }
            if let Some(ev) = button.update(push.is_low(), now) {
                let _ = EVENTS.try_send(ev);
            }
        }
    }

    /// Hold longer, move faster: same feel as turning the knob quickly.
    fn accelerate_hold(held_ms: u64) -> i32 {
        if held_ms >= 3000 {
            accelerate(1, 0)
        } else if held_ms >= 1500 {
            accelerate(1, 80)
        } else {
            1
        }
    }
}

pub use backend::input_task;
