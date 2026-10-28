ENTRY(bootstrap_entry)
SECTIONS {
    . = 0x06b95400;
    .text : { *(.text.entry) *(.text.bootstrap) *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
