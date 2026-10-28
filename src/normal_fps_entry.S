.syntax unified
.arch armv7-a
.arm
.section .text.entry
.global normal_fps_entry
normal_fps_entry:
    push {r4, lr}
    /* Native loader only reads base+12. This otherwise observational code_page
     * field is borrowed for that pointer; restore it before calling any C.
     * Resident USB/Jig hooks do not consume code_page. All other state remains
     * intact, including magic/version and the asynchronous USB observations. */
    ldr r0, =0x01c1e00c
    ldr r1, =0x01c1d000
    str r1, [r0]
    ldr r0, =0x00e20000
    ldr r1, =0x00e20040
    str r1, [r0]
    ldr r0, =0x01780594
    ldr r1, =0x020a0b54
    str r1, [r0]
    dsb sy
    bl normal_fps_main
    pop {r4, lr}
    /* Restore XN from stock code; never execute this page after this call. */
    ldr r0, =0x01c1e000
    mov r1, #0x1000
    mov r2, #3
    ldr ip, =0x0128bc9c
    bx ip
    .ltorg
