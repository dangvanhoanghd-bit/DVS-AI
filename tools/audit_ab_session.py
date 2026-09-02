from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def read_jsonl(path: Path, session_id: str) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    invalid = 0
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            if not line.endswith('\n'):
                invalid += 1
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if obj.get('session_id') == session_id:
                rows.append(obj)
    return rows, invalid


def summarize(bundle: Path) -> dict[str, Any]:
    manifests = sorted(bundle.glob('AB_TEST_MANIFEST_*.json'))
    if len(manifests) != 1:
        raise SystemExit(f'{bundle}: expected exactly one active AB_TEST_MANIFEST_*.json, found {len(manifests)}')
    manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
    sid = str(manifest['session_id'])
    metrics = bundle / f'runtime_metrics_{sid}.jsonl'
    if not metrics.exists():
        raise SystemExit(f'{bundle}: missing {metrics.name}')
    rows, invalid = read_jsonl(metrics, sid)
    if not rows:
        raise SystemExit(f'{bundle}: no valid metrics rows for session {sid}')
    cpu = [float(r['cpu_percent']) for r in rows if r.get('cpu_percent') is not None]
    ram = [float(r['rss_bytes']) / (1024 * 1024) for r in rows if r.get('rss_bytes') is not None]
    lag = [float(r.get('event_loop_lag_ms') or 0.0) for r in rows]
    duration_min = max(float(r.get('uptime_seconds') or 0.0) for r in rows) / 60.0
    return {
        'build': manifest.get('build'),
        'session_id': sid,
        'samples': len(rows),
        'duration_minutes': duration_min,
        'invalid_jsonl_lines': invalid,
        'cpu_avg': statistics.fmean(cpu) if cpu else None,
        'cpu_median': statistics.median(cpu) if cpu else None,
        'cpu_p95': percentile(cpu, .95),
        'cpu_max': max(cpu) if cpu else None,
        'ram_avg_mib': statistics.fmean(ram) if ram else None,
        'ram_p95_mib': percentile(ram, .95),
        'ram_max_mib': max(ram) if ram else None,
        'event_loop_p95_ms': percentile(lag, .95),
        'event_loop_p99_ms': percentile(lag, .99),
        'event_loop_max_ms': max(lag) if lag else None,
        'stall_count_final': max(int(r.get('event_loop_stall_count') or 0) for r in rows),
        'not_responding_count_final': max(int(r.get('not_responding_count') or 0) for r in rows),
        'writer_dropped_records': max(int(r.get('writer_dropped_records') or 0) for r in rows),
        'writer_errors': max(int(r.get('writer_errors') or 0) for r in rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Audit two DVS AI Performance Validation Standard v1.0 sessions.')
    ap.add_argument('g1_runtime_dir', type=Path)
    ap.add_argument('g2_runtime_dir', type=Path)
    args = ap.parse_args()
    g1 = summarize(args.g1_runtime_dir)
    g2 = summarize(args.g2_runtime_dir)
    shorter = min(g1['duration_minutes'], g2['duration_minutes'])
    longer = max(g1['duration_minutes'], g2['duration_minutes'])
    duration_diff_pct = 0.0 if longer == 0 else (longer - shorter) / longer * 100.0
    valid = (
        g1['duration_minutes'] >= 60.0
        and g2['duration_minutes'] >= 60.0
        and duration_diff_pct <= 15.0
        and g1['invalid_jsonl_lines'] == 0
        and g2['invalid_jsonl_lines'] == 0
    )
    comparison = {
        'standard': 'DVS AI Performance Validation Standard v1.0',
        'official_comparison_valid': valid,
        'duration_difference_percent': duration_diff_pct,
        'g1': g1,
        'g2': g2,
        'criteria': {
            'cpu_avg_increase_points': None if g1['cpu_avg'] is None or g2['cpu_avg'] is None else g2['cpu_avg'] - g1['cpu_avg'],
            'cpu_pass': None if g1['cpu_avg'] is None or g2['cpu_avg'] is None else g2['cpu_avg'] <= g1['cpu_avg'] + 10.0,
            'ram_pass': None if g1['ram_avg_mib'] is None or g2['ram_avg_mib'] is None else g2['ram_avg_mib'] <= g1['ram_avg_mib'],
            'event_loop_p95_pass': None if g1['event_loop_p95_ms'] is None or g2['event_loop_p95_ms'] is None else g2['event_loop_p95_ms'] < g1['event_loop_p95_ms'],
            'event_loop_p99_pass': None if g1['event_loop_p99_ms'] is None or g2['event_loop_p99_ms'] is None else g2['event_loop_p99_ms'] < g1['event_loop_p99_ms'],
            'not_responding_pass': g2['not_responding_count_final'] < g1['not_responding_count_final'],
            'jsonl_integrity_pass': g1['invalid_jsonl_lines'] == 0 and g2['invalid_jsonl_lines'] == 0,
            'writer_integrity_pass': all(x == 0 for x in [g1['writer_dropped_records'], g2['writer_dropped_records'], g1['writer_errors'], g2['writer_errors']]),
        },
    }
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0 if valid else 2


if __name__ == '__main__':
    raise SystemExit(main())
