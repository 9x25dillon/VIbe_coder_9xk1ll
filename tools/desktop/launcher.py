"""Isolated entry point for the private, relocatable desktop interpreter.

Run as: <bundle>/python/.../python -I <bundle>/launcher.py cli|smoke [args].
The only path admitted is the application directory next to this launcher.
"""
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / 'app'))
mode = sys.argv[1] if len(sys.argv) > 1 else 'cli'
sys.argv = [sys.argv[0], *sys.argv[2:]]
if mode == 'cli':
    runpy.run_module('vibecoder.cli', run_name='__main__')
elif mode == 'smoke':
    runpy.run_path(str(root / 'smoke.py'), run_name='__main__')
else:
    raise SystemExit('supported runtime entry points: cli, smoke')
