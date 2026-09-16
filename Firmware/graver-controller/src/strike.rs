//! Strike engine: TIM1 channel 1 in one-pulse mode on PA8.
//!
//! One strike is one high pulse of `t_on` microseconds. The pulse length is
//! produced by the timer, not by software: once armed, the hardware ends the
//! pulse even if the CPU stalls. Firmware only arms the next strike, once per
//! period.
//!
//! The overcurrent comparator on PB12 (TIM1_BKIN) is wired to the timer's
//! break input. A break clears MOE in hardware within one timer clock and,
//! because automatic output enable is off, it stays cleared until firmware
//! re-enables it. That is the latch the "OVERCURRENT" message is built on.
//!
//! Register references are to RM0383 (STM32F411) chapter 12,
//! "Advanced-control timer (TIM1)".

use embassy_stm32::gpio::{AfType, Flex, OutputType, Pull, Speed};
use embassy_stm32::pac::timer::vals;
use embassy_stm32::peripherals::{PA8, PB12, TIM1};
use embassy_stm32::time::Hertz;
use embassy_stm32::timer::Channel;
use embassy_stm32::timer::low_level::{
    CountingMode, FilterValue, OutputCompareMode, OutputPolarity, Timer as LlTimer,
};
use embassy_stm32::Peri;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;
use embassy_sync::watch::Watch;
use embassy_time::{Duration, Instant, Timer};

/// Timer tick: 1 us. TIM1 runs from APB2 (84 MHz here), the prescaler is
/// computed from the live clock by `set_tick_freq`.
const TICK_HZ: u32 = 1_000_000;

/// Dead time between arming and the rising edge, in ticks (RM0383 12.3.9: the
/// output goes active when CNT reaches CCR1). A couple of microseconds keeps
/// the compare out of the counter-start corner case and costs nothing.
const PULSE_DELAY_TICKS: u16 = 2;

/// AF1 = TIM1_CH1 on PA8 and TIM1_BKIN on PB12 (DS10314 table 9).
const AF_TIM1: u8 = 1;

/// What the control task wants the strike engine to do.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct StrikeParams {
    /// Strike rate in Hz. Ignored when `firing` is false.
    pub f_hz: u16,
    /// Coil on-time per strike, microseconds.
    pub t_on_us: u32,
    /// Fire while true.
    pub firing: bool,
}

impl Default for StrikeParams {
    fn default() -> Self {
        Self {
            f_hz: 10,
            t_on_us: 2_000,
            firing: false,
        }
    }
}

/// Control task -> strike task.
pub static COMMAND: Watch<CriticalSectionRawMutex, StrikeParams, 2> = Watch::new();
/// Strike task -> control task: the break input has tripped.
pub static OVERCURRENT: Watch<CriticalSectionRawMutex, bool, 2> = Watch::new();
/// Control task -> strike task: the operator released the pedal, unlatch.
pub static CLEAR_FAULT: Signal<CriticalSectionRawMutex, ()> = Signal::new();

/// TIM1 one-pulse driver for the gate pin.
pub struct StrikeEngine {
    tim: LlTimer<'static, TIM1>,
    gate: Flex<'static>,
    _bkin: Flex<'static>,
    pulse_ticks: u16,
    armed: bool,
}

impl StrikeEngine {
    /// Configure TIM1 for one-pulse output on CH1 and arm the break input.
    ///
    /// The gate output is low from the first instruction: PA8 is driven low as
    /// a plain GPIO before the timer owns it, and the timer is left with MOE
    /// cleared (outputs forced to their idle level, which is low) until the
    /// first strike.
    pub fn new(tim1: Peri<'static, TIM1>, gate: Peri<'static, PA8>, bkin: Peri<'static, PB12>) -> Self {
        // --- gate pin, low before anything else ------------------------------
        let mut gate = Flex::new(gate);
        gate.set_low();
        gate.set_as_output(Speed::Low);

        // --- break input ------------------------------------------------------
        // The comparator drives this high on overcurrent. On the Blackpill the
        // net is not driven at all, so the internal pull-down keeps the bench
        // from tripping on noise. On the PCB the comparator wins over the
        // ~40 kohm pull-down.
        let mut bkin = Flex::new(bkin);
        bkin.set_as_af_unchecked(AF_TIM1, AfType::input(Pull::Down));

        let mut tim = LlTimer::new(tim1);
        let core = tim.regs_core();
        let adv = tim.regs_advanced();

        // RM0383 12.4.1 CR1: stop the counter before touching anything.
        tim.stop();
        tim.set_counting_mode(CountingMode::EdgeAlignedUp);

        // RM0383 12.4.11 PSC: one tick = 1 us, derived from the live APB2
        // timer clock so the same code is right at any core frequency.
        tim.set_tick_freq(Hertz(TICK_HZ));
        // set_tick_freq raises an update event to load the prescaler; drop the
        // flag it leaves behind (RM0383 12.4.5 SR.UIF).
        core.sr().modify(|w| w.set_uif(false));

        // RM0383 12.4.1 CR1.OPM: the counter clears CEN at the next update
        // event, so one arm = exactly one pulse. ARPE off: ARR is written
        // while the counter is stopped and must take effect immediately.
        core.cr1().modify(|w| {
            w.set_opm(true);
            w.set_arpe(false);
            w.set_urs(vals::Urs::COUNTER_ONLY);
        });

        // RM0383 12.4.7 CCMR1: PWM mode 2 = output inactive while CNT < CCR1,
        // active from CCR1 to the update event. With OPM that is a single
        // high pulse of (ARR - CCR1 + 1) ticks, delayed by CCR1 ticks.
        // No preload: the values are written while the counter is stopped.
        tim.set_output_compare_mode(Channel::Ch1, OutputCompareMode::PwmMode2);
        tim.set_output_compare_preload(Channel::Ch1, false);
        // RM0383 12.4.9 CCER: CC1P = 0, the gate driver input is active high.
        tim.set_output_polarity(Channel::Ch1, OutputPolarity::ActiveHigh);
        tim.set_compare_value(Channel::Ch1, PULSE_DELAY_TICKS);
        tim.set_max_compare_value(PULSE_DELAY_TICKS);

        // RM0383 12.4.18 BDTR:
        //  - OSSI = 1 with OIS1 = 0: while MOE is cleared the pin is actively
        //    driven to its idle level (low) instead of being released.
        //  - BKE = 1, BKP = 1: break input enabled, active high.
        //  - break filter: 8 timer clocks, so a spike cannot trip it, but a
        //    real overcurrent still cuts the pulse in under 100 ns.
        //  - AOE = 0: MOE is NOT restored at the next update event. A trip
        //    latches until firmware clears it. This is the safety property.
        tim.set_ois(Channel::Ch1, false);
        tim.set_ossi(vals::Ossi::IDLE_LEVEL);
        tim.set_ossr(vals::Ossr::DISABLED);
        tim.set_break_polarity(vals::Bkp::ACTIVE_HIGH);
        tim.set_break_filter(FilterValue::FCK_INT_N8);
        tim.set_automatic_output_enable(false);
        tim.set_break_enable(true);

        // RM0383 12.4.9 CCER.CC1E: connect OC1 to the pin. The output still
        // needs MOE (set in `arm`), so PA8 stays at the idle level for now.
        tim.enable_channel(Channel::Ch1, true);
        tim.set_moe(false);

        // Load PSC/ARR/CCR1 into the shadow registers without raising an
        // interrupt (RM0383 12.4.6 EGR.UG, URS already set above).
        core.egr().write(|w| w.set_ug(true));
        core.sr().modify(|w| w.set_uif(false));
        adv.sr().modify(|w| w.set_bif(0, false));

        // Only now does the timer take the pin over.
        gate.set_as_af_unchecked(
            AF_TIM1,
            AfType::output_pull(OutputType::PushPull, Speed::Low, Pull::Down),
        );

        defmt::info!("TIM1 one-pulse engine ready, tick = 1 us");
        Self {
            tim,
            gate,
            _bkin: bkin,
            pulse_ticks: 0,
            armed: false,
        }
    }

    /// Set the on-time of the next strike. Ignored while a pulse is running.
    pub fn set_pulse_us(&mut self, t_on_us: u32) {
        let ticks = t_on_us.clamp(1, u16::MAX as u32 - PULSE_DELAY_TICKS as u32 - 1) as u16;
        if ticks == self.pulse_ticks || self.is_busy() {
            return;
        }
        self.pulse_ticks = ticks;
        // Pulse width = ARR - CCR1 + 1 (RM0383 12.3.9), so ARR is
        // delay + width - 1.
        self.tim
            .set_max_compare_value(PULSE_DELAY_TICKS + ticks - 1);
        self.tim.set_compare_value(Channel::Ch1, PULSE_DELAY_TICKS);
    }

    /// Enable the outputs. Must be called once before the first strike and
    /// after clearing a break.
    pub fn enable_output(&mut self) {
        if !self.armed {
            self.tim.set_moe(true);
            self.armed = true;
        }
    }

    /// Force the gate low and keep it there (RM0383 12.4.18 BDTR.MOE).
    pub fn disable_output(&mut self) {
        self.tim.set_moe(false);
        self.tim.stop();
        self.armed = false;
    }

    /// Start one pulse. Returns false when the previous one is still running.
    pub fn strike(&mut self) -> bool {
        if self.is_busy() {
            return false;
        }
        self.tim.reset();
        self.tim.start();
        true
    }

    /// True while the counter is running, i.e. a pulse is in flight. OPM
    /// clears CEN at the update event that ends the pulse.
    pub fn is_busy(&self) -> bool {
        self.tim.regs_core().cr1().read().cen()
    }

    /// True when the break input has tripped since the last clear.
    pub fn tripped(&self) -> bool {
        self.tim.regs_advanced().sr().read().bif(0) || (self.armed && !self.tim.get_moe())
    }

    /// Clear a latched break so the next strike can be armed.
    pub fn clear_trip(&mut self) {
        self.tim.regs_advanced().sr().modify(|w| w.set_bif(0, false));
        self.armed = false;
    }

    /// Gate pin level, for the boot self-check.
    pub fn gate_is_low(&self) -> bool {
        self.gate.is_low()
    }
}

/// Arms one strike per period while the control task allows firing.
#[embassy_executor::task]
pub async fn strike_task(mut engine: StrikeEngine) {
    let mut rx = COMMAND.receiver().unwrap();
    let fault_tx = OVERCURRENT.sender();
    let mut params = StrikeParams::default();
    let mut faulted = false;
    let mut next = Instant::now();

    fault_tx.send(false);

    loop {
        if let Some(new) = rx.try_changed() {
            if new.firing != params.firing {
                defmt::debug!(
                    "strike: firing = {}, f = {} Hz, t_on = {} us",
                    new.firing,
                    new.f_hz,
                    new.t_on_us
                );
            }
            params = new;
        }

        if CLEAR_FAULT.signaled() {
            CLEAR_FAULT.reset();
            if faulted {
                defmt::info!("overcurrent latch cleared");
                engine.clear_trip();
                faulted = false;
                fault_tx.send(false);
            }
        }

        if !params.firing || faulted {
            engine.disable_output();
            next = Instant::now();
            // Idle: wake on the next command, but poll often enough to notice
            // a fault clear request.
            let _ = embassy_futures::select::select(rx.changed(), Timer::after_millis(20)).await;
            continue;
        }

        engine.set_pulse_us(params.t_on_us);
        engine.enable_output();
        if engine.strike() {
            defmt::debug!("strike f={} Hz t_on={} us", params.f_hz, params.t_on_us);
        }

        let period = Duration::from_micros(1_000_000 / params.f_hz.max(1) as u64);
        next += period;
        let now = Instant::now();
        if next <= now {
            // Overrun (a long flash write, or f raised while waiting): resync
            // instead of firing a burst.
            next = now + period;
        }
        Timer::at(next).await;

        if engine.tripped() {
            defmt::warn!("TIM1 break: overcurrent, outputs latched off");
            engine.disable_output();
            faulted = true;
            fault_tx.send(true);
        }
    }
}
