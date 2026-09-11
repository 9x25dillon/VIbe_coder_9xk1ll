"""Export illustrative states through the real cell renderers, using only stdlib.

Run from the repository root: python3.11 tools/preview_ui.py
The SVG uses a sample dark terminal background; the app inherits the user's.
"""

from html import escape
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vibecoder.campaign import Campaign
from vibecoder.editor import Editor, RunOutcome
from vibecoder.encounter import compose
from vibecoder.fight import Fight
from vibecoder.levels import all_bosses, all_levels, get_level
from vibecoder.models import RunResult, ScoreBreakdown, TestOutcome
from vibecoder.repair import Repair
from vibecoder.screen import CONTINUATION
from vibecoder.session import Session
from vibecoder.ui import Capabilities, Depth, Renderer
from vibecoder import vision


def scenes():
    caps = Capabilities(Depth.TRUECOLOR, True, False, 120)
    ui = Renderer(caps)
    level = get_level('w2-l1-revenue')
    editor = Editor(level, caps=caps)
    editor.buffer.load(level.reference.replace('> threshold', '>= threshold'))
    editor.attempt = 2
    result = RunResult(outcomes=[TestOutcome('boundary_price', False, got='130.01', expected='70.01')]
                       + [TestOutcome(name, True) for name in ('empty_input', 'none_above_threshold', 'random_12', 'random_400')],
                       ops=2410, peak_bytes=8192)
    editor.outcome = RunOutcome(result, ScoreBreakdown(80, 92, 86, total=84.5, stars=2), 0, 120)
    editor.advice = 'Check the boundary: the price must be strictly above the threshold.'
    session = Session(ROOT / '.preview-not-saved.json')
    campaign = Campaign(list(all_levels()), list(all_bosses()), session, ui, 7)
    repair = Repair(editor.buffer.text, line=3,
                    error='expected 70.01, got 130.01', title='Drop the cheap stock',
                    func='total_revenue', values={'threshold': '20.0', 'total': '130.01'},
                    resources='BOSS 80/100 HP / repairs 3', brief=level.brief, caps=caps)
    machine = vision.build_machine(level.reference, level.func_name)
    frame = vision.frames(machine, [{'line': 3, 'func': level.func_name,
                                    'locals': {'threshold': '20.0', 'total': '70.01'}}])[-1]
    return [
        ('01 / CAMPAIGN', campaign.compose(26, 120)),
        ('02 / EDITOR + TEST FEEDBACK', editor.compose(26, 120)),
        ('03 / LIVE BOSS', compose(machine, frame, Fight(3), 'The Ledger', ui, 26, 120)),
        ('04 / REPAIR INSPECTOR', repair.compose(26, 120)),
    ]


def main():
    frames = scenes()
    cw, ch = 8, 18
    panel_height = 26 * ch + 70
    width, height = 1024, 95 + len(frames) * panel_height
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="VibeCoder terminal overhaul preview">',
           '<rect width="100%" height="100%" fill="#0b1018"/>',
           '<text x="32" y="35" fill="#e2e8f0" font-family="monospace" font-size="21">VIBECODER / TERMINAL COCKPIT</text>',
           '<text x="32" y="60" fill="#94a3b8" font-family="monospace" font-size="12">Illustrative states rendered by the actual application. 120 columns.</text>']
    for index, (label, screen) in enumerate(frames):
        top = 95 + index * panel_height
        out.append(f'<text x="32" y="{top}" fill="#67c4d7" font-family="monospace" font-size="12">{label}</text>')
        out.append(f'<rect x="24" y="{top + 12}" width="976" height="{26 * ch + 20}" rx="8" fill="#111923" stroke="#263444"/>')
        for row, cells in enumerate(screen.grid):
            for col, cell in enumerate(cells):
                if cell.char in (' ', CONTINUATION):
                    continue
                match = re.search(r'38;2;(\d+);(\d+);(\d+)', cell.style)
                color = '#e2e8f0' if not match else '#%02x%02x%02x' % tuple(map(int, match.groups()))
                bold = 'bold' if '\033[1m' in cell.style else 'normal'
                x, y = 32 + col * cw, top + 36 + row * ch
                out.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="monospace" font-size="13" font-weight="{bold}">{escape(cell.char)}</text>')
    out.append('</svg>')
    target = ROOT / 'docs' / 'visual-overhaul.svg'
    target.write_text('\n'.join(out), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
