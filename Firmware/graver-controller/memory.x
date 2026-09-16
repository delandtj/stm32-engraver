/* STM32F411CEU6 memory map.
 *
 * Flash: 512 KB at 0x0800_0000, in sectors
 *   0-3   16 KB   0x0800_0000 .. 0x0800_FFFF
 *   4     64 KB   0x0801_0000 .. 0x0801_FFFF
 *   5-7  128 KB   0x0802_0000 .. 0x0807_FFFF
 *
 * Sector 7 (0x0806_0000, 128 KB) is reserved for the settings journal
 * (see src/settings.rs) and is therefore NOT part of the FLASH region the
 * linker may use. Program flash is the first 384 KB, sectors 0-6.
 *
 * RAM: 128 KB at 0x2000_0000.
 */
MEMORY
{
  FLASH    : ORIGIN = 0x08000000, LENGTH = 384K
  RAM      : ORIGIN = 0x20000000, LENGTH = 128K
}

/* Kept in sync with SETTINGS_* in src/settings.rs. */
_settings_start = 0x08060000;
_settings_end   = 0x08080000;
