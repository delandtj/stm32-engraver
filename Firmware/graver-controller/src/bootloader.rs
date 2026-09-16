//! Entry into the STM32 ROM bootloader (USB DFU).
//!
//! Holding the encoder push button (PB7, active low) at power-up hands control
//! to the system-memory bootloader at 0x1FFF_0000, so a unit can be reflashed
//! over USB-C without opening the box and without a debug probe. The BOOT0
//! button stays as the recovery path.
//!
//! This must run as the very first thing in `main`, before
//! `embassy_stm32::init`: at that point the chip is still in its reset clock
//! configuration (HSI 16 MHz, no PLL), which is what the ROM code expects.
//!
//! References: RM0383 section 2.4 (boot configuration), AN2606 section on the
//! STM32F411 bootloader, PM0214 section 2.3.4 (vector table, MSP).

use cortex_m::peripheral::{NVIC, SCB};
use embassy_stm32::pac;

/// Base of the system memory (ROM bootloader) on STM32F411.
const SYSTEM_MEMORY: u32 = 0x1FFF_0000;

/// Cycles to wait for the PB7 pull-up to settle, at the 16 MHz reset clock.
/// 32_000 cycles is about 2 ms, far more than an RC of 10k x 10 nF.
const PULLUP_SETTLE_CYCLES: u32 = 32_000;

/// Jump to the ROM bootloader if the encoder push button is held at boot.
///
/// # Safety
///
/// Must be called before any peripheral is configured (before
/// `embassy_stm32::init`) and before interrupts are enabled.
pub unsafe fn maybe_enter_dfu() {
    if !button_held() {
        return;
    }
    defmt::info!("encoder held at boot: entering ROM bootloader");
    unsafe { jump_to_bootloader() }
}

/// Read PB7 with its internal pull-up enabled. Returns true when the button
/// pulls the pin low.
fn button_held() -> bool {
    // RM0383 section 6.3.9: enable the GPIOB clock in RCC_AHB1ENR.
    pac::RCC.ahb1enr().modify(|w| w.set_gpioben(true));
    // Two dummy reads: the clock takes effect one cycle after the write.
    let _ = pac::RCC.ahb1enr().read();

    // RM0383 section 8.4.1/8.4.4: MODER = input (00), PUPDR = pull-up (01).
    pac::GPIOB
        .moder()
        .modify(|w| w.set_moder(7, pac::gpio::vals::Moder::INPUT));
    pac::GPIOB
        .pupdr()
        .modify(|w| w.set_pupdr(7, pac::gpio::vals::Pupdr::PULL_UP));

    cortex_m::asm::delay(PULLUP_SETTLE_CYCLES);
    let held = pac::GPIOB.idr().read().idr(7) == pac::gpio::vals::Idr::LOW;

    // Leave the pin as we found it; the input backend configures it again.
    pac::GPIOB
        .pupdr()
        .modify(|w| w.set_pupdr(7, pac::gpio::vals::Pupdr::FLOATING));
    held
}

/// Hand over to the system-memory bootloader. Never returns.
///
/// # Safety
///
/// Only valid from reset state: no DMA running, no interrupt handler active.
unsafe fn jump_to_bootloader() -> ! {
    // 1. No interrupt may fire between here and the jump.
    cortex_m::interrupt::disable();

    // 2. Disable and clear every peripheral interrupt that reset left enabled.
    //    (Nothing should be enabled this early, but a warm restart through
    //    this path must not inherit anything.)
    let mut cp = unsafe { cortex_m::Peripherals::steal() };
    cp.SYST.disable_counter();
    cp.SYST.disable_interrupt();
    for reg in 0..8 {
        unsafe {
            (*NVIC::PTR).icer[reg].write(0xFFFF_FFFF);
            (*NVIC::PTR).icpr[reg].write(0xFFFF_FFFF);
        }
    }

    // 3. Release the GPIOB clock taken by button_held().
    pac::RCC.ahb1enr().modify(|w| w.set_gpioben(false));

    // 4. RM0383 section 7.2.1: SYSCFG_MEMRMP = 01 maps system memory at
    //    address 0x0000_0000, which is where the ROM code expects to run from.
    pac::RCC.apb2enr().modify(|w| w.set_syscfgen(true));
    let _ = pac::RCC.apb2enr().read();
    pac::SYSCFG.memrm().modify(|w| w.set_mem_mode(0b01));

    // 5. Point the vector table at the bootloader's table.
    unsafe { (*SCB::PTR).vtor.write(SYSTEM_MEMORY) };

    // 6. The first word of the table is the initial MSP, the second is the
    //    reset vector (PM0214 section 2.3.4). cortex_m::asm::bootstrap takes
    //    those two values (as pointers), sets MSP and branches; it never
    //    returns.
    let msp = unsafe { core::ptr::read_volatile(SYSTEM_MEMORY as *const u32) };
    let reset = unsafe { core::ptr::read_volatile((SYSTEM_MEMORY + 4) as *const u32) };
    unsafe { cortex_m::asm::bootstrap(msp as *const u32, reset as *const u32) }
}
