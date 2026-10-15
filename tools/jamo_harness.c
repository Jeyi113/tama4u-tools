/* Run the jamo engine (HPROF keys) on tamaemu's CPU core, no screen needed.
 * cc -w -D_DARWIN_C_SOURCE -include stdlib.h -include time.h -I~/tamaemu/src -o h tools/jamo_harness.c \
 *    $(ls ~/tamaemu/src/*.c | grep -v main.c) ~/tamaemu/tools/{dlc,dlc_names_4u,swapreq}.c -lm
 * ./h ROM P_KEY_A P_KEY_B P_KEY_C P_GLYPH_OF keys   (hex labels from hangul_name.assemble; keys a/b/c)
 * Field = 배드민턴; prints locals and the glyph each step. */
#include "emu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static Emu e;
static uint8_t rom[PS_ROM_SIZE];
#define FIELD 0x3000
#define LOC 0x3100
#define SP0 0x3800
static void call(uint32_t fn, uint32_t r6){
  e.r[2]=FIELD; e.r[3]=LOC; e.r[6]=r6; e.sp=SP0; mem_write32(&e,SP0,0xDEAD0000); e.pc=fn;
  for(int i=0;i<200000 && e.pc!=0xDEAD0000 && !e.stopped;i++) cpu_step(&e);
  if(e.pc!=0xDEAD0000) printf("did not return pc=%08x %s\n",e.pc,e.stop_reason);
}
static void show(const char*t, uint32_t gof){
  call(gof, mem_read8(&e,LOC));
  printf("%-6s slot%d st%d ci%d ji%d ti%d glyph=%u\n",t,mem_read8(&e,LOC),mem_read8(&e,LOC+1),mem_read8(&e,LOC+2),mem_read8(&e,LOC+3),mem_read8(&e,LOC+4),e.r[8]);
}
int main(int c,char**v){
  e.dev=*device_default(); e.rom=rom; e.cmu.osc3_hz=20e6;
  FILE*f=fopen(v[1],"rb"); fread(rom,1,PS_ROM_SIZE,f); fclose(f);
  uint32_t KA=strtoul(v[2],0,16),KB=strtoul(v[3],0,16),KC=strtoul(v[4],0,16),G=strtoul(v[5],0,16);
  uint8_t fld[]={0xca,0xb7,0xc9,0x31,0xca,0x9d,0xcf,0x3d,0};
  for(int i=0;i<9;i++) mem_write8(&e,FIELD+i,fld[i]);
  for(int i=0;i<12;i++) mem_write8(&e,LOC+i,0);
  const char*seq=v[6];
  show("start",G);
  for(const char*p=seq;*p;p++){
    call(*p=='a'?KA:*p=='b'?KB:KC, 0);
    char t[4]={*p,0}; show(t,G);
  }
  for(int i=0;i<9;i++) printf("%02x",mem_read8(&e,FIELD+i)); printf("\n");
}
