"""Read a preserved clip; retain packet timing and strict software decode proof."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    video=args.video.resolve();out=args.output.resolve();out.mkdir(exist_ok=False)
    ffprobe=shutil.which('ffprobe');ffmpeg=shutil.which('ffmpeg')
    if not ffprobe or not ffmpeg:raise RuntimeError('ffprobe and ffmpeg are required')
    probe=subprocess.run([ffprobe,'-v','warning','-show_format','-show_streams',
        '-show_packets','-select_streams','v:0','-show_entries',
        'packet=pts_time,dts_time,duration_time,size,flags:stream:format',
        '-of','json',str(video)],capture_output=True,text=True,timeout=120)
    (out/'ffprobe.json').write_text(probe.stdout)
    (out/'probe_stderr.txt').write_text(probe.stderr)
    if probe.returncode:raise RuntimeError(f'ffprobe failed; see {out}')
    data=json.loads(probe.stdout);stream=data['streams'][0]
    packets=data.get('packets',[])
    pts=[float(p['pts_time']) for p in packets if 'pts_time' in p]
    ordered=sorted(pts);deltas=[b-a for a,b in zip(ordered,ordered[1:])]
    report={'source':str(video),'bytes':video.stat().st_size,
        'sha256':hashlib.file_digest(video.open('rb'),'sha256').hexdigest(),
        'stream':{k:stream.get(k) for k in ('codec_name','profile','level','width','height',
            'pix_fmt','r_frame_rate','avg_frame_rate','time_base','duration','nb_frames','bit_rate',
            'field_order','refs','has_b_frames','color_range','color_space','color_transfer','color_primaries')},
        'packets':{'count':len(packets),'video_bytes':sum(int(p['size']) for p in packets),
            'pts_span':ordered[-1]-ordered[0] if len(ordered)>1 else None,
            'median_pts_delta':statistics.median(deltas) if deltas else None,
            'min_pts_delta':min(deltas) if deltas else None,'max_pts_delta':max(deltas) if deltas else None},
        'ffmpeg_version':subprocess.check_output([ffmpeg,'-version'],text=True).splitlines()[0]}
    print(json.dumps({'video':video.name,'metadata':report['stream']},indent=2),flush=True)
    command=[ffmpeg,'-nostdin','-hide_banner','-v','warning','-xerror','-err_detect','explode',
        '-threads','4','-i',str(video),'-map','0:v:0','-an','-sn','-dn',
        '-fps_mode','passthrough','-f','framemd5',str(out/'decoded.framemd5')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=240)
    (out/'decode_stderr.txt').write_text(result.stderr)
    (out/'decode_command.json').write_text(json.dumps(command,indent=2)+'\n')
    hashes=[];timestamps=[];tb=None
    for line in (out/'decoded.framemd5').read_text().splitlines():
        match=re.fullmatch(r'#tb 0: (\d+/\d+)',line)
        if match:tb=Fraction(match[1])
        if not line or line.startswith('#'):continue
        parts=[p.strip() for p in line.split(',')]
        if len(parts)!=6:raise ValueError('Invalid framemd5 output')
        timestamps.append(int(parts[2]));hashes.append(parts[5])
    repeats=[i for i in range(1,len(hashes)) if hashes[i]==hashes[i-1]]
    effective=None
    if tb and len(timestamps)>1 and timestamps[-1]>timestamps[0]:
        effective=float(Fraction(len(timestamps)-1,1)/(tb*(timestamps[-1]-timestamps[0])))
    report['decode']={'strict_return_code':result.returncode,'frames':len(hashes),
        'time_base':str(tb),'effective_fps':effective,'unique_hashes':len(set(hashes)),
        'consecutive_duplicate_count':len(repeats),'first_duplicate_indices':repeats[:20],
        'stderr_nonempty':bool(result.stderr.strip()),
        'limitations':'Exact frame hashes detect identical decoded frames, not sensor readout correctness. A successful decode can still contain an image defect encoded into a valid bitstream.'}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'video':video.name,'decode':report['decode'],'report':str(out/'report.json')},indent=2),flush=True)
    if result.returncode:
        raise RuntimeError(f'Strict decode failed; partial evidence retained in {out}')


if __name__=='__main__':main()
