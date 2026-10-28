.syntax unified
.arch armv7-a
.arm
.section .text.entry
.global normal_bitrate_entry
normal_bitrate_entry:
    push {r4, lr}
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
    bl normal_bitrate_main
    pop {r4, lr}
    /* Restore the owned staging page to XN from original executable code. */
    ldr r0, =0x01c1e000
    mov r1, #0x1000
    mov r2, #3
    ldr ip, =0x0128bc9c
    bx ip
    .ltorg
