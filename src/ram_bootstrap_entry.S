.syntax unified
.arch armv7-a
.arm
.section .text.entry
.global bootstrap_entry
bootstrap_entry:
    push {r4, lr}
    ldr r0, =0x00e20000
    ldr r1, =0x00e20040
    str r1, [r0]
    ldr r0, =0x01780594
    mov r1, #0
    str r1, [r0]
    bl bootstrap_main
    pop {r4, lr}
    ldr r0, =0x06b95000
    mov r1, #0x1000
    mov r2, #3
    ldr ip, =0x0128bc9c
    bx ip
    .ltorg
