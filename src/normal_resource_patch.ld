ENTRY(normal_resource_entry)
SECTIONS {
    . = 0x01c1e400;
    .text : { *(.text.entry) *(.text.patch) *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
