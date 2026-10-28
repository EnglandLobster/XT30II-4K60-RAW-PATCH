/* Allocate/align/own/free private memory through the native libc pair.
 * Every allocation is freed before returning. No persistent hook installed.
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
    push {r4, r5, r6, lr}
    ldr r0, =0x00e20000
    ldr r1, =0x00e20040
    str r1, [r0]
    ldr r0, =0x01780594
    mov r1, #0
    str r1, [r0]
    mov r0, #0x2000
    ldr ip, =0x013d77a4
    blx ip
    mov r4, r0
    ldr r5, =0x06b95180
    str r4, [r5, #4]
    cmp r4, #0
    beq finish
    add r6, r4, #0x1000
    sub r6, r6, #1
    lsr r6, r6, #12
    lsl r6, r6, #12
    str r6, [r5, #8]
    mov r0, r6
    mov r1, #0
    mov r2, #0x1000
clear_owned_page:
    str r1, [r0], #4
    subs r2, r2, #4
    bne clear_owned_page
    mov r0, r4
    ldr ip, =0x013d77c4
    blx ip
    ldr r1, =0xfeeefeee
    str r1, [r5, #12]
    ldr r1, =0x50524f42
    str r1, [r5]
finish:
    pop {r4, r5, r6, lr}
    ldr r0, =0x06b95000
    mov r1, #0x1000
    mov r2, #3
    ldr ip, =0x0128bc9c
    bx ip
.ltorg
