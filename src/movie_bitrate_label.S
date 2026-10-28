/* Per-menu resource view. Other uses of MSG_VALM_ISO_400 stay native.
 * The two original 2.06 prologues contain no PC-relative instructions.
 * Installation is allowed only in cold Jig, before REC/UI activation.
 */
.syntax unified
.arch armv7-a
.arm
.section .text.label
.global movie_bitrate_width
.global movie_bitrate_record
.global movie_bitrate_resource
movie_bitrate_width:
    push {r0-r4, lr}
    bl movie_bitrate_context
    cmp r0, #0
    pop {r0-r4, lr}
    beq 1f
    /* Keep the native explicit width override, when one is active. */
    ldr r3, =0x0393c9e4
    ldr r3, [r3]
    cmp r0, r3
    beq 1f
    mov r0, #120
    bx lr
1:  str fp, [sp, #-4]!
    add fp, sp, #0
    ldr pc, =0x03eb6cc4

.org 0x40
movie_bitrate_record:
    push {r0-r4, lr}
    bl movie_bitrate_context
    cmp r0, #0
    pop {r0-r4, lr}
    beq 2f
    ldr r0, =movie_bitrate_resource
    bx lr
2:  str fp, [sp, #-4]!
    add fp, sp, #0
    ldr pc, =0x03eb6d30

.org 0x80
movie_bitrate_context:
    movw r1, #0x86c
    cmp r0, r1
    bne 9f
    ldr r1, =0x01a4117c
    ldrb r1, [r1]
    cmp r1, #1
    bne 9f
    ldr r1, =0x01a405c4
    ldr r1, [r1]
    tst r1, #3
    bne 9f
    ldr r2, =0x01525740
    cmp r1, r2
    blo 9f
    ldr r2, =0x01526208
    cmp r1, r2
    bhi 9f
    ldrh r2, [r1]
    cmp r2, #0x88
    bne 9f
    ldrb r2, [r1, #2]
    cmp r2, #4
    bne 9f
    mov r0, #1
    bx lr
9:  mov r0, #0
    bx lr
    .ltorg

.org 0x1c0
movie_bitrate_resource:
    .hword 120
    .byte 1, 0
    .word movie_bitrate_resource + 8
    .word movie_bitrate_resource + 20
    .hword 100, 100
    .word 0
    .hword 0x34, 0x30, 0x30, 0x4d, 0x62, 0x70, 0x73, 0
.org 0x1e8
    .word 0x4c414231, 0x03eb6cbc, 0x03eb6d28, 0x00000206
.org 0x200
