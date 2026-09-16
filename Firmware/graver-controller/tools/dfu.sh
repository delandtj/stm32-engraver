#!/bin/sh
# Build the firmware and flash it over USB with the STM32 ROM bootloader.
#
# Put the board in DFU first, either by holding the encoder at power-up (this
# firmware jumps to the ROM bootloader) or by holding BOOT0 while tapping NRST.
#
# Usage: tools/dfu.sh [extra cargo features]
set -eu

crate_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$crate_dir"

features=${1:-}
if [ -n "$features" ]; then
    cargo build --release --features "$features"
else
    cargo build --release
fi

elf=$(cargo metadata --no-deps --format-version 1 \
    | tr ',' '\n' | sed -n 's/.*"target_directory":"\([^"]*\)".*/\1/p')
elf="$elf/thumbv7em-none-eabihf/release/graver-controller"
bin="$crate_dir/graver-controller.bin"

if command -v arm-none-eabi-objcopy >/dev/null 2>&1; then
    objcopy=arm-none-eabi-objcopy
elif command -v llvm-objcopy >/dev/null 2>&1; then
    objcopy=llvm-objcopy
else
    echo "need arm-none-eabi-objcopy or llvm-objcopy" >&2
    exit 1
fi

"$objcopy" -O binary "$elf" "$bin"
ls -l "$bin"

dfu-util -a 0 -s 0x08000000:leave -D "$bin"
