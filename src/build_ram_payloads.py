"""Reproducible ARM artifacts for the explicitly bounded RAM experiments."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import os

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'build'
OUT.mkdir(parents=True, exist_ok=True)


def main():
    clang=os.environ.get('CC') or shutil.which('clang')
    linker=shutil.which('ld.lld')
    objcopy=shutil.which('llvm-objcopy')
    nm=shutil.which('llvm-nm')
    if not all((clang,linker,objcopy,nm)): raise SystemExit('Put clang, ld.lld, llvm-objcopy and llvm-nm on PATH')
    flags=['--target=armv7-none-eabi','-march=armv7-a','-marm','-mfloat-abi=soft','-Os',
           '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables',
           '-fno-asynchronous-unwind-tables','-Wall','-Wextra','-Werror']
    builds=[('rec_lifecycle_hook',['rec_lifecycle_hook.c','rec_lifecycle_state.S'],'rec_lifecycle_hook.ld'),
            ('private_exec_probe',['private_exec_entry.S','private_exec_probe.c'],'private_exec_probe.ld'),
            ('rec_install_probe',['ram_bootstrap_entry.S','rec_install_probe.c'],'ram_bootstrap.ld'),
            ('rec_install_label_probe',['ram_bootstrap_entry.S','rec_install_label_probe.c'],'ram_bootstrap.ld'),
            ('movie_bitrate_label',['movie_bitrate_label.S'],'movie_bitrate_label.ld'),
            ('normal_fps_patch',['normal_fps_entry.S','normal_fps_patch.c'],'normal_fps_patch.ld'),
            ('normal_resource_patch',['normal_resource_entry.S','normal_resource_patch.c'],'normal_resource_patch.ld'),
            ('normal_bitrate_patch',['normal_bitrate_entry.S','normal_bitrate_patch.c'],'normal_bitrate_patch.ld'),
            ('normal_bitrate_menu_patch',['normal_bitrate_menu_entry.S','normal_bitrate_menu_patch.c'],'normal_bitrate_menu_patch.ld')]
    artifacts=[]
    for name,sources,script in builds:
        objects=[]
        for source in sources:
            obj=OUT/(Path(source).stem+'.o')
            subprocess.run([clang,*flags,'-c',str(ROOT/source),'-o',str(obj)],check=True)
            objects.append(str(obj))
        subprocess.run([linker,'-T',str(ROOT/script),*objects,'-o',str(OUT/(name+'.elf'))],check=True)
        subprocess.run([objcopy,'-O','binary',str(OUT/(name+'.elf')),str(OUT/(name+'.bin'))],check=True)
        binary=(OUT/(name+'.bin')).read_bytes()
        symbols={}
        for line in subprocess.check_output([nm,'--defined-only','--format=posix',str(OUT/(name+'.elf'))],text=True).splitlines():
            parts=line.split()
            if len(parts)>=3 and parts[1] in ('T','D','R'): symbols[parts[0]]=int(parts[2],16)
        if name=='rec_install_probe' and len(binary)>0x600: raise ValueError('Bootstrap overlaps hook image')
        if name=='rec_install_label_probe' and len(binary)>0x800: raise ValueError('Label bootstrap overlaps hook image')
        if name=='movie_bitrate_label' and (len(binary)!=0x200 or any(binary[0x140:0x1c0])):
            raise ValueError('Label provider exceeds its separate staging windows')
        if name.startswith('normal_') and len(binary)>0xc00:
            raise ValueError('Normal patch exceeds owned page')
        if name=='rec_lifecycle_hook' and (len(binary)>0x600 or binary.count(bytes.fromhex('efbeadde'))!=1):
            raise ValueError('Invalid hook layout')
        artifacts.append({'name':name,'bytes':len(binary),'sha256':hashlib.sha256(binary).hexdigest(),'symbols':symbols,
                          'sources':{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources+[script]}})
    (OUT/'build_manifest.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    accepted=json.loads((ROOT.parent/'payloads/build_manifest.json').read_text())
    expected={x['name']:x['sha256'] for x in accepted}
    for item in artifacts:
        if item['sha256']!=expected[item['name']]:raise ValueError('Rebuild differs from accepted binary: '+item['name'])
    print('Rebuilt',len(artifacts),'payloads; all accepted SHA256 values match')


if __name__=='__main__': main()
