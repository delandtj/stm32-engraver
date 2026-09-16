//! Every user-visible string, in English, Dutch and French.
//!
//! Nothing else in the firmware contains display text: the UI asks this module
//! for a `&'static str` with the language from the settings. Adding a language
//! means adding a variant to `Lang` and one column here.
//!
//! The strings are written against the screen geometry in `src/ui.rs` and must
//! stay inside it, because nothing clips or wraps:
//!
//!   cell labels   FONT_9X18_BOLD, 9 px/char, 112 px cell  -> 12 chars
//!   cell values   PROFONT_18_POINT, 12 px/char, 112 px    ->  9 chars
//!   menu rows     PROFONT_18_POINT, label at x = 6, value right-aligned to
//!                 x = 240 - 6 - len * 12, so
//!                 label_len * 12 + 6 + value_len * 12 + 6 <= 240
//!   status bar    PROFONT_24_POINT, 16 px/char, centred   -> 14 chars
//!
//! Plain ASCII only, like the rest of the tree: the font has no accented
//! glyphs, so "Francais" and "Luminosite" are spelled without them.

use crate::control::Status;
use crate::settings::Lang;

/// Pick one column of the table.
fn pick(lang: Lang, en: &'static str, nl: &'static str, fr: &'static str) -> &'static str {
    match lang {
        Lang::En => en,
        Lang::Nl => nl,
        Lang::Fr => fr,
    }
}

/// Run-screen cell labels, in the order of `ui::CELLS`.
pub fn cell_label(index: usize, lang: Lang) -> &'static str {
    match index {
        0 => pick(lang, "RATE", "FREQUENTIE", "CADENCE"),
        1 => pick(lang, "STRENGTH", "KRACHT", "FORCE"),
        2 => pick(lang, "ON TIME", "PULSDUUR", "IMPULSION"),
        3 => pick(lang, "SUPPLY", "VOEDING", "TENSION"),
        4 => pick(lang, "HANDPIECE", "HANDSTUK", "PIECE A MAIN"),
        _ => pick(lang, "DECAY", "DEMPING", "RETOMBEE"),
    }
}

/// Decay value, on the run screen and on the menu row.
pub fn decay(slow: bool, lang: Lang) -> &'static str {
    if slow {
        pick(lang, "SLOW", "TRAAG", "LENTE")
    } else {
        pick(lang, "FAST", "SNEL", "RAPIDE")
    }
}

/// Value of a yes/no setting.
pub fn on_off(on: bool, lang: Lang) -> &'static str {
    if on {
        pick(lang, "ON", "AAN", "OUI")
    } else {
        pick(lang, "OFF", "UIT", "NON")
    }
}

/// Status bar text.
pub fn status(status: Status, lang: Lang) -> &'static str {
    match status {
        Status::Booting => pick(lang, "STARTING", "OPSTARTEN", "DEMARRAGE"),
        Status::Overcurrent => pick(lang, "OVERCURRENT", "OVERSTROOM", "SURINTENSITE"),
        Status::NoPedal => pick(lang, "PEDAL?", "PEDAAL?", "PEDALE?"),
        Status::LowVin => pick(lang, "LOW VIN", "VOEDING LAAG", "TENSION BASSE"),
        Status::Hot => pick(lang, "HOT", "TE HEET", "TROP CHAUD"),
        Status::PedalNotAtRest => pick(lang, "RELEASE PEDAL", "PEDAAL OMHOOG", "LACHER PEDALE"),
        Status::Firing => pick(lang, "FIRING", "ACTIEF", "ACTIF"),
        Status::Ready => pick(lang, "READY", "KLAAR", "PRET"),
    }
}

/// Menu row labels, in display order. Rows are `control::MENU_ROWS` deep.
pub fn menu_label(row: usize, lang: Lang) -> &'static str {
    match row {
        0 => pick(lang, "Max frequency", "Max freq.", "Freq. max"),
        1 => pick(lang, "Duty cap", "Duty max", "Cycle max"),
        2 => pick(lang, "Decay", "Demping", "Retombee"),
        3 => pick(lang, "Supply comp", "Voedingscomp.", "Comp. tension"),
        4 => pick(lang, "Heel cal", "Hiel cal", "Talon"),
        5 => pick(lang, "Toe cal", "Teen cal", "Pointe"),
        6 => pick(lang, "Brightness", "Helderheid", "Luminosite"),
        7 => pick(lang, "Language", "Taal", "Langue"),
        _ => pick(lang, "Exit", "Terug", "Quitter"),
    }
}

/// The language itself, shown as the value on the Language row. Always in the
/// language it names, so it reads the same whichever one is selected.
pub fn lang_name(lang: Lang) -> &'static str {
    pick(lang, "English", "Nederlands", "Francais")
}

/// Menu header.
pub fn menu_title(lang: Lang) -> &'static str {
    pick(lang, "SETTINGS", "INSTELLINGEN", "REGLAGES")
}
