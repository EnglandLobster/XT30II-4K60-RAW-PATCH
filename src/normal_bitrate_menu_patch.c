/* Publish four bitrate choices through existing movie menu descriptors.
 * The lists live only in the unused tail of the retained 12 KiB allocation.
 * Restore unpublishes all references but never frees reachable allocation data.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define WORD(a) (*(volatile u32 *)(a))
#define BYTE(a) (*(volatile u8 *)(a))
#define PROTECT(a,n,p) (((int (*)(u32,u32,u32))0x0128bc9c)(a,n,p))
#define BASE 0x01c1f000
#define VALUES (BASE+0x40)
#define DISPLAY (BASE+0x80)
#define RO 0x0151ec16
#define RW 0x01516c16

struct report {
    u32 magic, action, status, old_value, expected, replacement;
    u32 rw_result, ro_result, writes, value_verified, permissions_verified;
};
static const u32 targets[4] = {0x01525834,0x01525838,0x01525e1c,0x01525e20};
static const u32 originals[4] = {0x01525740,0x01525760,0x01525d28,0x01525d48};
static const u32 replacements[4] = {VALUES,DISPLAY,VALUES,DISPLAY};
static const u32 values[8] = {1,0,2,0,3,0,0x7ffffffe,0};

static int inactive(u32 value) { return value==0 || value==0xffffffff; }

static int sources_valid(void) {
    for (u32 i=0;i<8;i++)
        if (WORD(0x01525740+i*4)!=values[i] || WORD(0x01525d28+i*4)!=values[i]) return 0;
    for (u32 i=0;i<48;i++) {
        u32 expected=0;
        if (i>=36) expected=0xffffffff;
        else if (i%12==0) expected=0x91f;
        else if (i%12==2 || i%12==3) expected=0x926+i/12;
        if (WORD(0x01525760+i*4)!=expected || WORD(0x01525d48+i*4)!=expected) return 0;
    }
    return 1;
}

static void initialize_output(void) {
    for (u32 i=0;i<0x180;i+=4) WORD(BASE+i)=0;
    WORD(BASE)=0x4d4e5531; WORD(BASE+4)=1;
    WORD(BASE+8)=40; WORD(BASE+12)=240;
    for (u32 i=0;i<8;i++) WORD(VALUES+8+i*4)=values[i];
    for (u32 i=0;i<48;i++) WORD(DISPLAY+48+i*4)=WORD(0x01525760+i*4);
    for (u32 i=0;i<12;i++) WORD(DISPLAY+i*4)=WORD(0x01525760+i*4);
    WORD(DISPLAY+8)=0x86c; WORD(DISPLAY+12)=0x86c;
    __asm__ volatile("dsb sy" ::: "memory");
}

__attribute__((section(".text.patch")))
void normal_bitrate_menu_main(void) {
    volatile struct report *s=(void *)0x01c1e100;
    s->status=1;
    if (s->magic!=0x4d4e5531 || s->action>2 ||
        WORD(0x01c1e000)!=0x52454348 || WORD(0x01c1e004)!=2 ||
        WORD(0x01c1e008)!=0x01c1cf10 || WORD(0x01c1e00c)!=0x01c1d000 ||
        WORD(0x01c1e010)!=0x01c1e000 || WORD(0x01c1e014)!=0 ||
        WORD(0x01c1e018)!=3 || WORD(0x01c1e034)!=0 || WORD(0x01c1e03c)!=0 ||
        BYTE(0x01b7b518)!=3 || BYTE(0x01722b84)!=1 ||
        WORD(0x0011c054)!=RO || WORD(0x0011c070)!=0x000a0401 ||
        WORD(0x000a0478)!=0x01c1e5b6 || WORD(0x000a047c)!=0x01c1f5b7 ||
        WORD(0x0011c088)!=0x0221ec06 || WORD(0x02219ed0)!=0xe3a00006 ||
        WORD(0x013e1788)!=0x7ffffffe || WORD(0x013e13c4)!=0 ||
        BYTE(0x01a4117c)!=0 ||
        BYTE(0x02cdde60)!=2 || BYTE(0x02cdde61)!=7 || BYTE(0x02e94a30)!=7 ||
        !inactive(WORD(0x02e137e8)) || !inactive(WORD(0x02e137ec)) ||
        BYTE(0x0177f8eb)!=0 || BYTE(0x0177f8ed)!=3 ||
        BYTE(0x0177f934)!=1 || BYTE(0x0177f935)!=0 ||
        BYTE(0x0177f950)!=1 || BYTE(0x0177f961)!=1 || BYTE(0x01b85ad2)!=4 ||
        !sources_valid()) {
        s->status=0x80000001; return;
    }
    s->expected=s->action==2 ? replacements[0] : originals[0];
    s->replacement=s->action==1 ? replacements[0] : originals[0];
    s->old_value=WORD(targets[0]);
    for (u32 i=0;i<4;i++)
        if (WORD(targets[i])!=(s->action==2 ? replacements[i] : originals[i])) {
            s->status=0x80000002; return;
        }
    if (s->action==0) { s->status=2; return; }
    s->rw_result=(u32)PROTECT(0x01500000,0x100000,3);
    if (s->rw_result) { s->status=0x80000003; return; }
    if (WORD(0x0011c054)==RW && BYTE(0x01a4117c)==0) {
        if (s->action==1) initialize_output();
        s->value_verified=1;
        for (u32 i=0;i<4;i++) {
            u32 replacement=s->action==1 ? replacements[i] : originals[i];
            WORD(targets[i])=replacement;
            s->writes++;
            if (WORD(targets[i])!=replacement) s->value_verified=0;
        }
        __asm__ volatile("dsb sy" ::: "memory");
    }
    s->ro_result=(u32)PROTECT(0x01500000,0x100000,1);
    s->permissions_verified=WORD(0x0011c054)==RO;
    s->status=s->writes==4 && s->value_verified && !s->ro_result &&
        s->permissions_verified ? 2 : 0x80000004;
}
