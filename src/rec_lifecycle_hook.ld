ENTRY(rec_lifecycle_hook)
SECTIONS {
  . = 0;
  .text : { *(.text.hook) *(.text.hook_state) *(.text*) *(.rodata*) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
