"""Profile a packed Mac app externally: process-tree RSS and CPU deltas, plus footprint snapshots."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

import psutil


def run(executable: Path, output: Path, soak_cycles: int = 0):
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / 'session.json'
    if status_path.exists():
        raise RuntimeError('Use a fresh output folder; do not overwrite a resource profile')
    command = [str(executable.resolve()), '--profile-resources', str(status_path.resolve())]
    if soak_cycles:
        command.append(f'--soak-cycles={soak_cycles}')
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)  # native macOS GUI, not offscreen raster-only measurement
    raw = []
    footprints = []
    previous = {}
    started = time.monotonic()
    with (output/'stderr.log').open('w') as errors:
        process = subprocess.Popen(command, env=env, stdout=errors, stderr=errors)
        root = psutil.Process(process.pid)
        pending_snapshot = None
        footprint_phases = set()
        try:
            while process.poll() is None:
                now = time.monotonic()
                status = {'phase':'startup'}
                if status_path.exists():
                    try: status = json.loads(status_path.read_text())
                    except (OSError,json.JSONDecodeError): pass
                phase = status.get('phase','startup')
                pids, rss, cpu_total = [], 0, 0.0
                rows = []
                try: tree = [root] + root.children(recursive=True)
                except psutil.Error: tree = []
                for item in tree:
                    try:
                        mem = item.memory_info().rss
                        cpu = item.cpu_times(); seconds=cpu.user+cpu.system
                        created = item.create_time()
                        key=(item.pid,created)
                        old=previous.get(key)
                        usage = 0.0 if old is None else max(0,seconds-old[1])/max(0.001,now-old[0])*100
                        previous[key]=(now,seconds)
                        rss += mem; cpu_total += usage; pids.append(item.pid)
                        rows.append({'pid':item.pid,'ppid':item.ppid(),'rss_bytes':mem,'cpu_percent':round(usage,3)})
                    except psutil.Error: pass
                raw.append({'elapsed':round(now-started,3),'phase':phase,'rss_tree_bytes':rss,
                            'cpu_tree_percent':round(cpu_total,3),'processes':rows})
                if phase in {'visible_idle','hidden_idle','active_checks','hidden_after_checks','repeated_checks'} and phase not in footprint_phases:
                    # Snapshot after steady-state settling, or while a request child is actually alive.
                    phase_age=sum(1 for sample in raw[-20:] if sample['phase']==phase)*0.2
                    if phase_age >= 3 and (phase!='active_checks' or len(pids)>=2):
                        if pending_snapshot is None or pending_snapshot.poll() is not None:
                            file=output/f'footprint-{phase}.json'
                            with (output/f'footprint-{phase}.log').open('w') as log:
                                pending_snapshot=subprocess.Popen(['/usr/bin/footprint','--noCategories','-f','bytes','-j',str(file.resolve())]+[str(pid) for pid in pids],stdout=log,stderr=log)
                            footprint_phases.add(phase); footprints.append(str(file.name))
                if now-started>260:
                    raise TimeoutError('Resource profiling exceeded its safety limit')
                time.sleep(0.2)
            code=process.wait()
            if code:
                raise RuntimeError(f'Profile child exited with code {code}; see stderr.log')
        finally:
            # Only the harness-created application is stopped on failure, never other running apps.
            if process.poll() is None:
                process.terminate()
                try:process.wait(4)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            if pending_snapshot is not None:
                try:pending_snapshot.wait(5)
                except subprocess.TimeoutExpired:pending_snapshot.terminate()
    summaries={}
    for phase in sorted({s['phase'] for s in raw}):
        samples=[s for s in raw if s['phase']==phase]
        memories=[s['rss_tree_bytes']/1048576 for s in samples]
        cpus=[s['cpu_tree_percent'] for s in samples]
        summaries[phase]={'samples':len(samples),'rss_median_mib':round(statistics.median(memories),2),
                          'rss_peak_mib':round(max(memories),2),'cpu_mean_percent':round(statistics.mean(cpus),3),
                          'cpu_peak_percent':round(max(cpus),3),'max_processes':max(len(s['processes']) for s in samples)}
    metadata=json.loads(status_path.read_text())
    result={'platform':platform.platform(),'machine':platform.machine(),'sampling_interval_seconds':0.2,
            'metric':'Sum of process-tree RSS (shared pages may be double-counted); CPU delta, 100%=one core',
            'scope':'native packaged macOS GUI; loopback-only requests; excludes external observer',
            'session':metadata,'phases':summaries,'footprint_files':footprints}
    (output/'samples.json').write_text(json.dumps(raw),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--soak-cycles',type=int,default=0)
    args=parser.parse_args()
    run(args.executable,args.output,args.soak_cycles)
