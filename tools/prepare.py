"""Reconstruct PRIVATE offline inputs from an exact, user-provided official DAT.
No download and no camera access. Never flash the 2.04 reference to the camera.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, struct, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fujitools.dat import DatFile
from fujitools.fflz_sections import read_header, decode_section

def sha(data): return hashlib.sha256(data).hexdigest()
def materialize(recipe, images):
    if 'image' in recipe:
        d=bytearray(images[recipe['image']][recipe['offset']:recipe['offset']+recipe['bytes']])
        for c in recipe.get('word_changes',[]):
            if struct.unpack_from('<I',d,c['offset'])[0]!=c['old']: raise ValueError('Relocation baseline differs')
            struct.pack_into('<I',d,c['offset'],c['new'])
        d=bytes(d)
    elif 'payload' in recipe:
        d=bytearray((ROOT/'payloads'/recipe['payload']).read_bytes())
        needle=struct.pack('<I',0xdeadbeef)
        if d.count(needle)!=1: raise ValueError('Ambiguous hook relocation')
        struct.pack_into('<I',d,d.index(needle),recipe['relocate_state']);d=bytes(d)
    else: d=struct.pack('<%dI'%len(recipe['words_le']),*recipe['words_le'])
    if len(d)!=recipe['bytes'] or sha(d)!=recipe['sha256']:raise ValueError('Reference recipe identity differs')
    return d

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('firmware',type=Path);a=ap.parse_args()
    spec=json.loads((ROOT/'metadata/reference-recipes.json').read_text())
    dat=DatFile.open(a.firmware)
    if dat.sha256!=spec['firmware']['sha256']:raise SystemExit('Wrong reference DAT SHA256. See docs/INSTALL.md; do not bypass this check.')
    xor=dat.xor_view();images={'xor':xor}
    for name,expected in spec['images'].items():
        if 'kernel' in name:
            offset=spec['kernel_offset'];d=xor[offset:offset+expected['bytes']]
        else:
            offset=int(name.split('_section_')[1].split('.')[0],16)
            d=decode_section(xor,read_header(xor,offset))
        if sha(d)!=expected['sha256']:raise ValueError('Decoded image mismatch: '+name)
        images[name]=d
    source=ROOT/'src/offline_20261011';out=ROOT/'src/normal_route_20261012'
    if (out/'rec_v2_acceptance.json').exists() or list(out.glob('rec_install_label_probe_20*')):
        raise SystemExit('Existing live installation workspace. Cold-restart and archive src/normal_route_20261012 before re-preparing.')
    source.mkdir(exist_ok=True);out.mkdir(exist_ok=True)
    for name,d in images.items():
        if name!='xor':(source/name).write_bytes(d)
    for name,recipe in spec['windows'].items():
        d=materialize(recipe,images);f=source/name;f.write_bytes(d)
        f.with_suffix('.json').write_text(json.dumps({'status':'success','origin':'reconstructed_offline_reference','not_live_camera_evidence':True,'sha256':sha(d)})+'\n')
    for name,recipe in spec['fixtures'].items():(ROOT/'tests/fixtures'/name).write_bytes(materialize(recipe,images))
    for name,recipe in spec['test_settings'].items():
        f=out/name;f.parent.mkdir(exist_ok=True);f.write_bytes(materialize(recipe,images))
    for base in ('payloads','validation'):
        for f in (ROOT/base).iterdir():shutil.copy2(f,out/f.name)
    sys.path.insert(0,str(ROOT/'src'))
    from verify_loader_probe import build_page,capture,TABLE,PROBES
    for payload in PROBES:
        page=build_page(capture(TABLE,396),payload)
        report=json.loads((out/(payload+'_emulation.json')).read_text())
        if sha(page)!=report['scratch_page_sha256']:raise ValueError('Staged page differs from accepted page: '+payload)
        (out/(payload+'_page.bin')).write_bytes(page)
    print('Prepared exact local references and accepted payloads. No camera access. Run python tools/check.py.')
if __name__=='__main__':main()
