ENTRY(private_exec_entry)
SECTIONS {
    . = 0x06b95400;
    .text : { *(.text.entry) *(.text.probe) *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
