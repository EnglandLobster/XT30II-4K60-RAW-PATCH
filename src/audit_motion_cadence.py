"""Luma-difference and phase-correlation diagnostics for preserved video.

This flags near-repeats during motion; it does not establish sensor exposure
timestamps or compare stabilization efficacy across unmatched handheld scenes.
Requires NumPy; no camera access. Original files are read only.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

WIDTH, HEIGHT = 480, 270


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    command = [shutil.which('ffmpeg'), '-nostdin', '-hide_banner', '-v', 'error',
        '-threads', '4', '-i', str(args.video), '-map', '0:v:0', '-an', '-sn',
        '-vf', f'scale={WIDTH}:{HEIGHT}:flags=area,format=gray',
        '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1']
    window = np.outer(np.hanning(HEIGHT), np.hanning(WIDTH)).astype(np.float32)
    previous = previous_fft = None
    rows = []
    count = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as decoder:
        while raw := decoder.stdout.read(WIDTH * HEIGHT):
            if len(raw) != WIDTH * HEIGHT:
                raise ValueError('Partial decoded frame')
            frame = np.frombuffer(raw, np.uint8).reshape(HEIGHT, WIDTH).astype(np.float32)
            spectrum = np.fft.rfft2((frame - frame.mean()) * window)
            if previous is not None:
                delta = np.abs(frame - previous)
                cross = spectrum * previous_fft.conj()
                cross /= np.maximum(np.abs(cross), 1e-9)
                correlation = np.fft.irfft2(cross, s=frame.shape)
                y, x = np.unravel_index(np.argmax(correlation), correlation.shape)
                def refine(a, b, c):
                    denominator = a - 2 * b + c
                    return float(0.5 * (a - c) / denominator) if abs(denominator) > 1e-9 else 0.0
                dx = (int(x) if x <= WIDTH // 2 else int(x) - WIDTH) + refine(
                    correlation[y, (x - 1) % WIDTH], correlation[y, x], correlation[y, (x + 1) % WIDTH])
                dy = (int(y) if y <= HEIGHT // 2 else int(y) - HEIGHT) + refine(
                    correlation[(y - 1) % HEIGHT, x], correlation[y, x], correlation[(y + 1) % HEIGHT, x])
                rows.append({'frame': count, 'mean_absolute_luma_delta': float(delta.mean()),
                    'p95_luma_delta': float(np.percentile(delta, 95)),
                    'dx_at_480px': dx, 'dy_at_270px': dy,
                    'phase_peak': float(correlation[y, x]),
                    'phase_peak_to_rms': float(correlation[y, x] / np.sqrt(np.mean(correlation ** 2)))})
            previous, previous_fft = frame, spectrum
            count += 1
        error = decoder.stderr.read().decode()
        if decoder.wait() != 0:
            raise RuntimeError(error)
    values = np.array([r['mean_absolute_luma_delta'] for r in rows])
    suspects = []
    for i in range(1, len(rows) - 1):
        neighbors = max(values[i - 1], values[i + 1])
        if values[i] < 0.75 and neighbors >= 1 and values[i] < 0.1 * neighbors:
            suspects.append({'frame': rows[i]['frame'], 'delta': float(values[i]),
                             'neighbor_delta': float(neighbors)})
    result = {'source': str(args.video.resolve()), 'frames': count, 'analysis_size': [WIDTH, HEIGHT],
        'delta_percentiles': {str(p): float(np.percentile(values, p)) for p in (0, 1, 5, 50, 95, 99, 100)},
        'mean_delta_by_frame_parity': {str(p): float(np.mean([r['mean_absolute_luma_delta']
            for r in rows if r['frame'] % 2 == p])) for p in (0, 1)},
        'near_repeat_motion_suspects': suspects, 'rows': rows, 'decoder_command': command,
        'limitations': 'Heuristic on area-downsampled luma; compression, scene motion, focus and noise affect it. Phase correlation approximates translation only. No direct sensor timing or gyro/OIS measurements.'}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'decoder_command')}, indent=2))


if __name__ == '__main__':
    main()
