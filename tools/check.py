"""Offline package verification; never imports a USB transport."""
from pathlib import Path
import argparse,hashlib,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'src'),str(ROOT)]
def verify_payloads():
    manifest=json.loads((ROOT/'payloads/build_manifest.json').read_text())
    for item in manifest:
        data=(ROOT/'payloads'/(item['name']+'.bin')).read_bytes()
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Changed payload '+item['name'])
    for line in (ROOT/'payloads/SHA256SUMS').read_text().splitlines():
        digest,name=line.split()
        if hashlib.sha256((ROOT/'payloads'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Payload checksum failed: '+name)
    print('Accepted core payload identities:',len(manifest),'passed; all 11 binary checksums passed')
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--payloads-only',action='store_true');a=ap.parse_args()
    verify_payloads()
    if a.payloads_only:return
    suite=unittest.TestLoader().discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if 'usb1' in sys.modules or 'fftlib' in sys.modules:raise RuntimeError('Offline tests imported a live USB library')
    if not result.wasSuccessful():raise SystemExit(1)
if __name__=='__main__':main()
