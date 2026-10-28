/* Single-shot probe for the verified X-T30 II 2.06 loading ABI.
 * Borrowed log page: 0x06b95000, only while logging is uninitialized.
 * This is not a video patch. No storage, UI, sensor, or recording calls.
 * The original loader makes this already-small page executable. Restore
 * the global descriptor root and CMD callback before doing anything else.
 * Tail-call the native protection API to restore RW/XN without returning
 * to a now non-executable page. The host restores the saved page contents.
 */
.syntax unified
.arch armv7-a
.arm
.section .text
.global probe_page
probe_page:
    .word 0, 0x06b95000, 0x1000, 0x06b95020
    .word 0, 0, 0, 0
probe_entry:
    push {r4, lr}
    ldr r0, =0x00e20000
    ldr r1, =0x00e20040
    str r1, [r0]
    ldr r0, =0x01780594
    mov r1, #0
    str r1, [r0]
    ldr r0, =0x06b95180
    ldr r1, =0x50524f42
    str r1, [r0]
    pop {r4, lr}
    ldr r0, =0x06b95000
    mov r1, #0x1000
    mov r2, #3
    ldr ip, =0x0128bc9c
    bx ip
.ltorg
