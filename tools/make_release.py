"""Package tracked files only; never include local firmware, captures or venvs."""
from pathlib import Path
import hashlib,json,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1]
TAG='v0.1.1-experimental'
def main():
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');files=[f for f in files if f]
    if not files:raise SystemExit('No tracked release files')
    for name in files:
        f=ROOT/name
        if f.is_symlink() or f.suffix.lower() in ('.dat','.mov','.mp4','.pem','.key') or name.startswith(('src/offline_20261011/','src/normal_route_20261012/','tests/fixtures/')) and f.suffix=='.bin':raise ValueError('Private or unreviewed input: '+name)
    out=ROOT/'dist';out.mkdir(exist_ok=True);archive=out/f'xt30ii-4k60-{TAG}.zip';prefix=f'xt30ii-4k60-{TAG}/'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info=zipfile.ZipInfo(prefix+name,(2026,10,29,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,(ROOT/name).read_bytes())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('Release ZIP failed CRC verification')
        if len(z.infolist())!=len(files):raise RuntimeError('Release inventory mismatch')
    sums=out/'SHA256SUMS';sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n'+''.join(hashlib.sha256((ROOT/'payloads'/f.name).read_bytes()).hexdigest()+'  payloads/'+f.name+'\n' for f in sorted((ROOT/'payloads').glob('*.bin'))))
    print(json.dumps({'archive':str(archive),'tracked_files':len(files),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'checksums':str(sums)},indent=2))
if __name__=='__main__':main()
