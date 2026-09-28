"""Run from the relocated bundle, with no source checkout on sys.path."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import tempfile
import time
import sys

import vibecoder
from vibecoder.levels import all_levels, all_bosses
from vibecoder.models import Source, TestCase as Case
from vibecoder.runner import LiveRun, reference_benchmark, run_code, run_submission
from vibecoder.scoring import score_submission
from vibecoder.sandbox import SandboxUnavailable


def main() -> None:
    root = Path(__file__).resolve().parent
    assert Path(vibecoder.__file__).resolve().is_relative_to(root / 'app')
    assert Path(sys.executable).resolve().is_relative_to(root / 'python')
    manifest = json.loads((root / 'runtime.json').read_text())
    assert platform.python_version() == manifest['python']
    os.environ['VIBECODER_SANDBOX'] = 'subprocess'
    report = {'platform': platform.platform(), 'python': platform.python_version(),
              'runtime_sha256': manifest['sha256'], 'checks': []}
    with tempfile.TemporaryDirectory(prefix='vibecoder-native-smoke-') as directory:
        os.environ['VIBECODER_HOME'] = directory
        level = all_levels()[0]
        tests = level.tests_for(1)
        progress = []
        started = time.monotonic()
        result = run_submission(level, level.reference, tests, source=Source.PLAYER,
                                record_trace=True,
                                on_progress=lambda *event: progress.append(event))
        elapsed = time.monotonic() - started
        assert result.all_passed, result.error
        assert len(progress) == len(tests) and result.trace
        ops, peak = reference_benchmark(level, 1)
        score = score_submission(result, elapsed_seconds=30, par_seconds=level.par_seconds,
                                 ref_ops=ops, ref_peak_bytes=peak, attempt=1,
                                 style_goals_met=True, first_run_clean=True)
        assert score.accuracy == 100 and score.speed == 100
        report['checks'].append({'level': level.id, 'score': asdict(score),
                                 'execution_ms': round(elapsed * 1000, 2)})
        broken = 'def solve(n):\n    value = n\n    raise ValueError("repair me")\n'
        fixed = 'def solve(n):\n    value = n\n    return value\n'
        with LiveRun(broken, 'solve', Case('repair', [7], expected=7),
                     source=Source.PLAYER, timeout=.5) as live:
            assert live.step() is not None
            time.sleep(.75)  # human pause must outlive the execution budget
            while True:
                event = live.step()
                assert event is not None, live.result().error
                if event.failed:
                    assert event.line == 3
                    break
            assert live.edit(fixed) is None
            live.resume()
            repaired = live.drain()
            assert repaired.all_passed, repaired.error
            assert live.code == fixed
        report['checks'].append('live pause beyond timeout, failing-line repair and resume')
        with LiveRun('import time\ndef solve():\n    time.sleep(60)\n',
                     'solve', Case('watchdog', []), source=Source.PLAYER,
                     timeout=.5) as live:
            assert live.step() is not None
            assert live.step() is None
            assert live.result().error_type == 'Aborted'
        report['checks'].append('native-call watchdog')
        result = run_code('def solve():\n    return len(bytearray(256*1024*1024))\n',
                          'solve', [Case('memory', [], expected=256*1024*1024)],
                          source=Source.PLAYER, mem_limit_mb=128, timeout=5)
        assert not result.all_passed, 'local memory limit was not enforced'
        report['checks'].append('memory exhaustion contained')
        try:
            run_code('def solve():\n    return 1\n', 'solve', [], source=Source.THIRD_PARTY)
        except SandboxUnavailable:
            report['checks'].append('unsafe provenance pin refused')
        else:
            raise AssertionError('third-party code reached the host')
        assert len(all_levels()) == 12 and len(all_bosses()) == 2
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
