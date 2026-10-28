.syntax unified
.arch armv7-a
.arm
.section .text.hook_state
.global hook_state
.global hook_state_pointer
hook_state:
    ldr r0, hook_state_pointer
    bx lr
hook_state_pointer:
    .word 0xdeadbeef

.section .text.usb_guard
.global usb_attach_guard
usb_attach_guard:
    /* Preserve all volatile registers. The stock function saved its caller LR
     * in its own frame; both continuations use that frame unchanged. */
    push {r0-r5, r12, lr}
    bl usb_attach_allowed
    cmp r0, #0
    beq original_path
    pop {r0-r5, r12, lr}
    ldr pc, =0x02240d88
original_path:
    pop {r0-r5, r12, lr}
    ldr pc, =0x02240d14
    .ltorg
