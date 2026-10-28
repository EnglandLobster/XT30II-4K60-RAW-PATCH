ENTRY(movie_bitrate_width)
SECTIONS {
    . = 0x01c1d400;
    .text : { *(.text.label) }
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
