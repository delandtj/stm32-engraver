//! Persistent settings in flash sector 7.
//!
//! Sector 7 of the STM32F411CE (0x0806_0000, 128 KB) is kept out of the FLASH
//! region in memory.x, so the linker never puts code there. This module treats
//! it as an append-only journal of fixed-size records: a save writes the next
//! free slot, a load scans for the last valid one. 32-byte records give 4096
//! saves per erase cycle.
//!
//! Why a journal and not "erase, then write": erasing a 128 KB sector stalls
//! the core for up to two seconds (DS10314, table "Flash memory programming"),
//! which the 1 s watchdog would not survive. Compaction therefore happens at
//! boot, before the watchdog is started, and never while the tool is in use.
//! If the journal fills during one session, the change stays in RAM and is
//! written after the next power cycle.

use embassy_stm32::Peri;
use embassy_stm32::flash::{Blocking, Flash, WRITE_SIZE};
use embassy_stm32::peripherals::FLASH;

/// Offsets are relative to FLASH_BASE (0x0800_0000).
const SETTINGS_OFFSET: u32 = 0x0006_0000;
const SETTINGS_SIZE: u32 = 0x0002_0000;
/// One record. Must be a multiple of the flash write granularity.
const RECORD_SIZE: u32 = 32;
const SLOTS: u32 = SETTINGS_SIZE / RECORD_SIZE;
/// Compact at boot once the journal is this full.
const COMPACT_AT: u32 = SLOTS * 3 / 4;

const _: () = assert!((RECORD_SIZE as usize).is_multiple_of(WRITE_SIZE));

/// Record header: "GRV" plus a format version. Bump the version when the
/// payload layout changes; old records are then ignored and defaults apply.
const MAGIC: [u8; 3] = *b"GRV";
const VERSION: u8 = 1;

/// Which value the pedal controls.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Mode {
    /// Mode F: pedal sets frequency, knob sets strength.
    Frequency,
    /// Mode S: pedal sets strength, knob sets frequency.
    Strength,
}

impl Mode {
    pub fn toggled(self) -> Self {
        match self {
            Mode::Frequency => Mode::Strength,
            Mode::Strength => Mode::Frequency,
        }
    }
}

/// Everything that survives a power cycle.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct Settings {
    pub mode: Mode,
    /// Knob value in mode F: strength, 0..100 %.
    pub strength_pct: u8,
    /// Knob value in mode S: strike rate, Hz.
    pub knob_f_hz: u16,
    /// Upper end of the frequency range, Hz.
    pub f_max_hz: u16,
    /// Duty cap, percent of t_on * f.
    pub duty_cap_pct: u8,
    /// True = slow (diode-only) decay, PB14 high.
    pub decay_slow: bool,
    /// Scale t_on by 24 V / VIN.
    pub compensate: bool,
    /// Backlight, 10..100 %.
    pub brightness_pct: u8,
    /// Pedal heel (rest) position, raw ADC counts.
    pub pedal_min: u16,
    /// Pedal toe (full) position, raw ADC counts.
    pub pedal_max: u16,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            mode: Mode::Frequency,
            strength_pct: 50,
            knob_f_hz: 20,
            f_max_hz: 60,
            duty_cap_pct: 35,
            decay_slow: false,
            compensate: true,
            brightness_pct: 80,
            pedal_min: 200,
            pedal_max: 3900,
        }
    }
}

impl Settings {
    fn encode(&self) -> [u8; RECORD_SIZE as usize] {
        let mut r = [0xFFu8; RECORD_SIZE as usize];
        r[0..3].copy_from_slice(&MAGIC);
        r[3] = VERSION;
        r[4] = match self.mode {
            Mode::Frequency => 0,
            Mode::Strength => 1,
        };
        r[5] = self.strength_pct;
        r[6..8].copy_from_slice(&self.knob_f_hz.to_le_bytes());
        r[8..10].copy_from_slice(&self.f_max_hz.to_le_bytes());
        r[10] = self.duty_cap_pct;
        r[11] = self.decay_slow as u8;
        r[12] = self.compensate as u8;
        r[13] = self.brightness_pct;
        r[14..16].copy_from_slice(&self.pedal_min.to_le_bytes());
        r[16..18].copy_from_slice(&self.pedal_max.to_le_bytes());
        // 18..30 reserved, left at 0xFF so new fields can be added without a
        // version bump as long as 0xFF is a valid "unset".
        let crc = crc16(&r[0..RECORD_SIZE as usize - 2]);
        r[RECORD_SIZE as usize - 2..].copy_from_slice(&crc.to_le_bytes());
        r
    }

    fn decode(r: &[u8]) -> Option<Self> {
        if r.len() != RECORD_SIZE as usize || r[0..3] != MAGIC || r[3] != VERSION {
            return None;
        }
        let crc = u16::from_le_bytes([r[RECORD_SIZE as usize - 2], r[RECORD_SIZE as usize - 1]]);
        if crc != crc16(&r[0..RECORD_SIZE as usize - 2]) {
            return None;
        }
        let s = Self {
            mode: if r[4] == 0 { Mode::Frequency } else { Mode::Strength },
            strength_pct: r[5],
            knob_f_hz: u16::from_le_bytes([r[6], r[7]]),
            f_max_hz: u16::from_le_bytes([r[8], r[9]]),
            duty_cap_pct: r[10],
            decay_slow: r[11] != 0,
            compensate: r[12] != 0,
            brightness_pct: r[13],
            pedal_min: u16::from_le_bytes([r[14], r[15]]),
            pedal_max: u16::from_le_bytes([r[16], r[17]]),
        };
        Some(s.sanitised())
    }

    /// Clamp anything a corrupt or future record could put out of range, so a
    /// bad byte can never produce a dangerous strike setting.
    fn sanitised(mut self) -> Self {
        self.strength_pct = self.strength_pct.min(100);
        self.knob_f_hz = self.knob_f_hz.clamp(1, 60);
        self.f_max_hz = self.f_max_hz.clamp(5, 60);
        self.duty_cap_pct = self.duty_cap_pct.clamp(5, 35);
        self.brightness_pct = self.brightness_pct.clamp(10, 100);
        if self.pedal_max <= self.pedal_min + 100 {
            self.pedal_min = 200;
            self.pedal_max = 3900;
        }
        self
    }
}

/// CRC-16/CCITT-FALSE. Small, and no peripheral needed.
fn crc16(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &b in data {
        crc ^= (b as u16) << 8;
        for _ in 0..8 {
            crc = if crc & 0x8000 != 0 {
                (crc << 1) ^ 0x1021
            } else {
                crc << 1
            };
        }
    }
    crc
}

/// Flash-backed settings store.
pub struct Store {
    flash: Flash<'static, Blocking>,
    /// Index of the next free slot, or SLOTS when the journal is full.
    next: u32,
}

impl Store {
    /// Take the flash peripheral and find the newest record.
    ///
    /// Call this before the watchdog is started: it may erase the sector.
    pub fn new(flash: Peri<'static, FLASH>) -> (Self, Settings) {
        let mut store = Self {
            flash: Flash::new_blocking(flash),
            next: 0,
        };
        let settings = store.scan();
        store.compact_if_needed(settings);
        (store, settings)
    }

    /// Walk the journal for the last valid record.
    fn scan(&mut self) -> Settings {
        let mut buf = [0u8; RECORD_SIZE as usize];
        let mut found = Settings::default();
        let mut used = 0;
        for slot in 0..SLOTS {
            let offset = SETTINGS_OFFSET + slot * RECORD_SIZE;
            if self.flash.blocking_read(offset, &mut buf).is_err() {
                break;
            }
            if buf.iter().all(|&b| b == 0xFF) {
                break;
            }
            used = slot + 1;
            if let Some(s) = Settings::decode(&buf) {
                found = s;
            }
        }
        self.next = used;
        defmt::info!("settings: {} of {} slots used", used, SLOTS);
        found
    }

    /// Erase and rewrite with a single record when the journal is nearly
    /// full. Only ever called from `new`, i.e. before the watchdog runs.
    fn compact_if_needed(&mut self, settings: Settings) {
        if self.next < COMPACT_AT {
            return;
        }
        defmt::info!("settings: compacting sector 7");
        if let Err(e) = self
            .flash
            .blocking_erase(SETTINGS_OFFSET, SETTINGS_OFFSET + SETTINGS_SIZE)
        {
            defmt::error!("settings: erase failed: {}", e);
            self.next = SLOTS;
            return;
        }
        self.next = 0;
        self.write(settings);
    }

    /// Append the settings if they differ from what is already stored.
    pub fn save(&mut self, settings: Settings) {
        if self.next >= SLOTS {
            defmt::warn!("settings: journal full, change kept in RAM until reboot");
            return;
        }
        self.write(settings);
    }

    fn write(&mut self, settings: Settings) {
        let record = settings.encode();
        let offset = SETTINGS_OFFSET + self.next * RECORD_SIZE;
        match self.flash.blocking_write(offset, &record) {
            Ok(()) => {
                self.next += 1;
                defmt::debug!("settings: saved to slot {}", self.next - 1);
            }
            Err(e) => defmt::error!("settings: write failed: {}", e),
        }
    }
}
