"""Optional, read-only GPU sampling and fit-grading performance logs."""
from contextvars import ContextVar
import csv
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import statistics
import sys
import threading
import time
import uuid

from job_miner.paths import PROJECT_DIR

CURRENT_MONITOR = ContextVar('fit_grade_monitor', default=None)
METRIC_FIELDS = ('total_duration', 'load_duration', 'prompt_eval_count',
                 'prompt_eval_cached_count', 'prompt_eval_duration', 'eval_count',
                 'eval_duration', 'done_reason')
GPU_FIELDS = ('power_w', 'power_limit_w', 'temperature_c', 'gpu_util_pct',
              'memory_util_pct', 'vram_used_mib', 'vram_total_mib', 'fan_pct',
              'sm_clock_mhz', 'memory_clock_mhz', 'thermal_throttled', 'power_throttled')


def record_ollama_metrics(result):
    monitor = CURRENT_MONITOR.get()
    if monitor is not None:
        fields = {key: result[key] for key in METRIC_FIELDS if key in result}
        duration = result.get('eval_duration')
        count = result.get('eval_count')
        if isinstance(duration, (int, float)) and duration > 0 and isinstance(count, (int, float)):
            fields['tokens_per_second'] = count * 1e9 / duration
        monitor.event('ollama_result', **fields)


class NvmlReader:
    """All calls are read-only. Unsupported sensors are explicitly null."""
    def __init__(self):
        import pynvml as nvml
        self.nvml = nvml
        nvml.nvmlInit()
        try:
            self.handle = nvml.nvmlDeviceGetHandleByIndex(0)
            self.metadata = {'gpu_uuid': nvml.nvmlDeviceGetUUID(self.handle),
                             'gpu_name': nvml.nvmlDeviceGetName(self.handle),
                             'driver_version': nvml.nvmlSystemGetDriverVersion()}
        except Exception:
            nvml.nvmlShutdown()
            raise

    def sample(self):
        n, h = self.nvml, self.handle
        values, errors = {}, {}

        def read(name, fn):
            try:
                values[name] = fn()
            except Exception as error:
                values[name] = None
                errors[name] = str(error)

        read('power_w', lambda: n.nvmlDeviceGetPowerUsage(h) / 1000)
        read('power_limit_w', lambda: n.nvmlDeviceGetEnforcedPowerLimit(h) / 1000)
        read('temperature_c', lambda: n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
        read('gpu_util_pct', lambda: n.nvmlDeviceGetUtilizationRates(h).gpu)
        read('memory_util_pct', lambda: n.nvmlDeviceGetUtilizationRates(h).memory)
        read('vram_used_mib', lambda: n.nvmlDeviceGetMemoryInfo(h).used / 1024**2)
        read('vram_total_mib', lambda: n.nvmlDeviceGetMemoryInfo(h).total / 1024**2)
        read('fan_pct', lambda: n.nvmlDeviceGetFanSpeed(h))
        read('sm_clock_mhz', lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM))
        read('memory_clock_mhz', lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM))
        read('thermal_throttled', lambda: bool(n.nvmlDeviceGetCurrentClocksThrottleReasons(h) & (
            n.nvmlClocksThrottleReasonSwThermalSlowdown | n.nvmlClocksThrottleReasonHwThermalSlowdown)))
        read('power_throttled', lambda: bool(n.nvmlDeviceGetCurrentClocksThrottleReasons(h) & (
            n.nvmlClocksThrottleReasonSwPowerCap | n.nvmlClocksThrottleReasonHwPowerBrakeSlowdown)))
        return values, errors

    def close(self):
        self.nvml.nvmlShutdown()


def summarize(samples):
    result = {'sample_count': len(samples)}
    for field in ('power_w', 'temperature_c', 'gpu_util_pct', 'vram_used_mib'):
        values = [s[field] for s in samples if s.get(field) is not None]
        result[field] = {'mean': statistics.fmean(values), 'max': max(values)} if values else None
    energy = thermal = covered = thermal_covered = 0.0
    for left, right in zip(samples, samples[1:]):
        seconds = right['elapsed_s'] - left['elapsed_s']
        if not 0 < seconds <= 5:
            continue
        if left.get('power_w') is not None and right.get('power_w') is not None:
            energy += (left['power_w'] + right['power_w']) / 2 * seconds / 3600
            covered += seconds
        if left.get('thermal_throttled') is not None:
            thermal_covered += seconds
            if left['thermal_throttled']:
                thermal += seconds
    result.update(estimated_gpu_wh=energy if covered else None,
                  energy_covered_seconds=covered,
                  observed_thermal_throttling_seconds=thermal if thermal_covered else None,
                  thermal_covered_seconds=thermal_covered,
                  samples_with_errors=sum(bool(s.get('errors')) for s in samples))
    return result


class GradeMonitor:
    def __init__(self, model, root=None, reader_factory=NvmlReader):
        self.model = model
        self.root = Path(root) if root else PROJECT_DIR / 'generated_search_requests/grading_logs'
        self.reader_factory = reader_factory
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.phase, self.job_id = 'baseline', None
        self.samples, self.jobs, self.errors = [], [], []
        self.metadata = {}
        self.cooldown_started = None
        self.events_file = self.csv_file = self.reader = self.thread = None
        self.created = time.monotonic()
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
        self.directory = self.root / self.run_id

    def warn(self, error):
        self.errors.append(str(error))
        print(f'GPU monitoring error: {error}', file=sys.stderr, flush=True)

    def event(self, event, **fields):
        try:
            with self.lock:
                if self.events_file:
                    row = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                               elapsed_s=time.monotonic() - self.created,
                               batch_id=self.run_id, phase=self.phase, job_id=self.job_id,
                               event=event, **fields)
                    self.events_file.write(json.dumps(row) + '\n')
                    self.events_file.flush()
        except Exception as error:
            self.warn(error)

    def start(self):
        try:
            self.directory.mkdir(parents=True)
            # The batch lock ensures old runs are inactive, including interrupted ones.
            cutoff = time.time() - 30 * 86400
            for directory in self.root.iterdir():
                if not re.fullmatch(r'\d{8}T\d{6}-[0-9a-f]{8}', directory.name):
                    continue
                for name in ('gpu.csv', 'events.jsonl'):
                    path = directory / name
                    try:
                        if path.exists() and path.stat().st_mtime < cutoff:
                            path.unlink()
                    except OSError as error:
                        self.warn(error)
            self.events_file = (self.directory / 'events.jsonl').open('w', buffering=1)
            self.csv_file = (self.directory / 'gpu.csv').open('w', newline='', buffering=1)
            self.writer = csv.DictWriter(self.csv_file, fieldnames=(
                'timestamp', 'elapsed_s', 'batch_id', 'phase', 'job_id', *GPU_FIELDS, 'errors'))
            self.writer.writeheader()
            self.event('batch_start', model=self.model, sample_interval_seconds=1)
            print(f'Grading monitoring logs: {self.directory}', flush=True)
            try:
                self.reader = self.reader_factory()
                self.metadata = self.reader.metadata
                self.event('gpu_device', **self.metadata)
                self.thread = threading.Thread(target=self._sample_loop, daemon=True, name='fit-gpu-monitor')
                self.thread.start()
            except Exception as error:
                self.event('monitor_error', error=str(error))
                self.warn(error)
        except Exception as error:
            self.warn(error)

    def _sample_loop(self):
        try:
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(1)
        finally:
            try:
                self.reader.close()
            except Exception as error:
                self.warn(error)

    def sample(self):
        try:
            values, errors = self.reader.sample()
            with self.lock:
                row = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                           elapsed_s=time.monotonic() - self.created, batch_id=self.run_id,
                           phase=self.phase, job_id=self.job_id, **values, errors=errors)
                self.samples.append(row)
                self.writer.writerow({**row, 'errors': json.dumps(errors) if errors else ''})
                self.csv_file.flush()
        except Exception as error:
            self.event('monitor_error', error=str(error))
            self.warn(error)

    def begin_job(self, job_id):
        with self.lock:
            self.phase, self.job_id = 'grading', job_id
            self.job_started = time.monotonic()
            self.event('job_start')

    def end_job(self, status, error=None):
        with self.lock:
            fields = dict(status=status, duration_seconds=time.monotonic() - self.job_started)
            if error:
                fields['error'] = error
            self.event('job_end', **fields)
            self.jobs.append(dict(job_id=self.job_id, **fields))
            self.phase, self.job_id = 'between_jobs', None

    def cooldown(self, seconds):
        with self.lock:
            self.phase, self.job_id = 'cooldown', None
            self.cooldown_started = time.monotonic() - self.created
            self.event('cooldown_start', duration_seconds=seconds)
        self.stop.wait(seconds)
        self.event('cooldown_end')

    def finish(self, completed):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.event('batch_end', completed=completed)
        try:
            with self.lock:
                summary = dict(batch_id=self.run_id, model=self.model, completed=completed,
                               duration_seconds=time.monotonic() - self.created,
                               whole_gpu_measurements=True, device=self.metadata,
                               monitoring_errors=list(self.errors), all_phases=summarize(self.samples),
                               grading=summarize([s for s in self.samples if s['phase'] == 'grading']),
                               cooldown=summarize([s for s in self.samples if s['phase'] == 'cooldown']))
                summary['jobs'] = [dict(job, gpu=summarize([
                    s for s in self.samples if s['job_id'] == job['job_id']])) for job in self.jobs]
                attempted = len([j for j in self.jobs if j['status'] != 'skipped'])
                succeeded = sum(j['status'] == 'graded' for j in self.jobs)
                energy = summary['grading']['estimated_gpu_wh']
                summary.update(attempted=attempted, succeeded=succeeded,
                    estimated_grading_wh_per_attempt=energy / attempted if energy is not None and attempted else None,
                    estimated_grading_wh_per_success=energy / succeeded if energy is not None and succeeded else None)
                cooldown_samples = [s for s in self.samples if s['phase'] == 'cooldown']
                summary['cooldown_temperature_c'] = {}
                for seconds in (60, 300, 600):
                    candidates = [s for s in cooldown_samples if s['elapsed_s'] >= self.cooldown_started + seconds - 1
                                  and s['elapsed_s'] <= self.cooldown_started + seconds + 2
                                  and s.get('temperature_c') is not None]
                    summary['cooldown_temperature_c'][str(seconds)] = candidates[0]['temperature_c'] if candidates else None
                (self.directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        except Exception as error:
            self.warn(error)
        finally:
            for handle in (self.csv_file, self.events_file):
                if handle:
                    try:
                        handle.close()
                    except Exception as error:
                        self.warn(error)
