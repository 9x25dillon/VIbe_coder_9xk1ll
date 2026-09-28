# Engine API inventory — existing code

Snapshot: `7a5940c8c95ed3dbe5c1f21d8b475241ea867644`, inspected 2026-09-28.
This inventories module-defined public functions/classes, dataclass fields, public methods and properties. Imported aliases are omitted; the package export list is recorded separately. Signatures are extracted from the Python AST, so defaults remain symbolic. These are Python interfaces, **not an existing versioned GUI protocol**. Private orchestration in `cli.py` and `editor.py` is discussed in [the proposal](ADR-001-desktop.md).

## `__init__`

Source: [implementation](../../vibecoder/__init__.py).

Explicit package exports:

```text
Difficulty, Level, Mastery, RunResult, ScoreBreakdown, StepScore, TagMastery, TestCase, TestOutcome, VibeVector, Weights, BOSS_WEIGHTS, LEVEL_WEIGHTS, Session, accuracy_score, all_levels, boss_step_benchmark, functional_score, get_level, profile_path, recommend, reference_benchmark, run_code, run_submission, score_fight, score_submission, speed_score, stars_for, worlds, __version__
```

## `models`

Source: [implementation](../../vibecoder/models.py).

```python
class Source(Enum):
    PLAYER = "player"
    BUNDLED = "bundled"
    THIRD_PARTY = "third_party"
    @property
    def requires_isolation(self) -> bool
```

```python
class TestCase:
    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    def to_json(self) -> dict[str, Any]
```

```python
class Level:
    id: str
    world: int
    world_title: str
    index: int
    title: str
    brief: str
    func_name: str
    starter: str
    reference: str
    make_tests: Callable[[random.Random], Sequence[TestCase]]
    par_seconds: float = 180.0
    tags: tuple[str, ...] = ()
    style_goals: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    source: 'Source' = Source.BUNDLED
    def tests_for(self, seed: int, difficulty: 'Difficulty | None'=None) -> list[TestCase]
    def hints_after(self, failed_attempts: int) -> list[str]
    @property
    def multiplier(self) -> float
```

```python
class TestOutcome:
    name: str
    passed: bool
    got: str = ''
    expected: str = ''
    error: str = ''
```

```python
class RunResult:
    outcomes: list[TestOutcome] = field(default_factory=list)
    wall_seconds: float = 0.0
    ops: int = 0
    peak_bytes: int = 0
    stdout: str = ''
    error: str = ''
    error_type: str = ''
    trace: list[dict[str, Any]] = field(default_factory=list)
    @property
    def fatal(self) -> bool
    @property
    def passed_count(self) -> int
    @property
    def total_count(self) -> int
    @property
    def all_passed(self) -> bool
    def to_json(self) -> dict[str, Any]
```

```python
class ScoreBreakdown:
    accuracy: float = 0.0
    speed: float = 0.0
    functional: float = 0.0
    subtotal: float = 0.0
    bonuses: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    stars: int = 0
    def to_json(self) -> dict[str, Any]
```

```python
class BossStep:
    id: str
    title: str
    brief: str
    func_name: str
    starter: str
    reference: str
    make_tests: Callable[[random.Random], Sequence[TestCase]]
    hints: tuple[str, ...] = ()
    style_goals: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()
    def tests_for(self, seed: int, difficulty: 'Difficulty | None'=None) -> list[TestCase]
```

```python
class BossLevel:
    id: str
    world: int
    world_title: str
    index: int
    title: str
    brief: str
    steps: tuple[BossStep, ...]
    par_seconds: float = 900.0
    tags: tuple[str, ...] = ()
    source: 'Source' = Source.BUNDLED
    @property
    def step_count(self) -> int
    def step(self, index: int) -> BossStep
    def index_of(self, step_id: str) -> int
    def starter_source(self, upto: int=0, *, solved: Sequence[str]=()) -> str
    def reference_source(self, upto: int | None=None) -> str
```

```python
class Difficulty:
    level: float = 0.5
    def scale(self, gentlest: float, hardest: float) -> float
    @property
    def band(self) -> str
```

```python
accepts_difficulty(generator: Callable) -> bool
```

```python
generate_tests(generator: Callable, seed: int, difficulty: 'Difficulty | None'=None) -> list['TestCase']
```

```python
migrate_vector(data: dict[str, Any], version: int) -> dict[str, Any]
```

```python
class VibeVector:
    files: int = 0
    functions: int = 0
    code_lines: int = 0
    libraries: dict[str, int] = field(default_factory=dict)
    patterns: dict[str, float] = field(default_factory=dict)
    exceptions_caught: dict[str, int] = field(default_factory=dict)
    avg_function_lines: float = 0.0
    max_complexity: int = 0
    docstring_ratio: float = 0.0
    naming: dict[str, float] = field(default_factory=dict)
    conventions: dict[str, float] = field(default_factory=dict)
    median_complexity: float = 0.0
    p90_complexity: float = 0.0
    avg_nesting: float = 0.0
    max_nesting: int = 0
    comment_density: float = 0.0
    partial: bool = False
    partial_reason: str = ''
    files_seen: int = 0
    tags: list[str] = field(default_factory=list)
    version: int = VECTOR_VERSION
    unknown: dict[str, Any] = field(default_factory=dict)
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'VibeVector'
    @property
    def from_a_newer_build(self) -> bool
```

## `levels.__init__`

Source: [implementation](../../vibecoder/levels/__init__.py).

```python
all_levels() -> tuple[Level, ...]
```

```python
get_level(level_id: str) -> Level
```

```python
worlds() -> dict[int, list[Level]]
```

```python
all_bosses() -> tuple[BossLevel, ...]
```

```python
get_boss(boss_id: str) -> BossLevel
```

## `scoring`

Source: [implementation](../../vibecoder/scoring.py).

```python
class Weights:
    accuracy: float
    speed: float
    functional: float
    def without_speed(self) -> 'Weights'
```

```python
accuracy_score(result: RunResult) -> float
```

```python
speed_score(elapsed_seconds: float, par_seconds: float) -> float
```

```python
functional_score(user_ops: int, ref_ops: int, user_peak_bytes: int, ref_peak_bytes: int) -> float
```

```python
stars_for(total: float) -> int
```

```python
score_submission(result: RunResult, *, elapsed_seconds: float, par_seconds: float, ref_ops: int, ref_peak_bytes: int, attempt: int, style_goals_met: bool, first_run_clean: bool, weights: Weights=LEVEL_WEIGHTS) -> ScoreBreakdown
```

```python
class StepScore:
    passed: int
    total: int
    ops: int
    ref_ops: int
    peak_bytes: int
    ref_peak_bytes: int
    style_met: bool = True
```

```python
score_fight(steps: Sequence[StepScore], *, elapsed_seconds: float, par_seconds: float, repairs_spent: int, crashed_first_run: bool, weights: Weights=BOSS_WEIGHTS) -> ScoreBreakdown
```

```python
streak_multiplier(streak: int) -> float
```

## `runner`

Source: [implementation](../../vibecoder/runner.py).

```python
run_code(code: str, func_name: str, tests: Sequence[TestCase], *, source: Source, timeout: float=DEFAULT_TIMEOUT, mem_limit_mb: int=DEFAULT_MEM_LIMIT_MB, record_trace: bool=False, filename: str=SUBMISSION_FILENAME, on_progress: 'ProgressHook | None'=None) -> RunResult
```

```python
run_submission(level: Level, code: str, tests: Sequence[TestCase], *, record_trace: bool=False, source: Source=Source.PLAYER, on_progress: 'ProgressHook | None'=None) -> RunResult
```

```python
reference_benchmark(level: Level, seed: int, difficulty: 'Difficulty | None'=None) -> tuple[int, int]
```

```python
boss_step_benchmark(boss: BossLevel, index: int, seed: int) -> tuple[int, int]
```

```python
class Step:
    index: int
    line: int
    func: str
    locals: dict[str, str]
    error: str = ''
    @property
    def failed(self) -> bool
    def to_trace(self) -> dict
```

```python
class LiveRun:
    def __init__(self, code: str, func_name: str, test: TestCase, *, source: Source, timeout: float=DEFAULT_TIMEOUT, mem_limit_mb: int=DEFAULT_MEM_LIMIT_MB, filename: str=SUBMISSION_FILENAME) -> None
    def start(self) -> None
    def close(self) -> None
    def step(self) -> Step | None
    def back(self) -> Step | None
    def forward(self) -> Step | None
    @property
    def browsing(self) -> bool
    @property
    def cursor(self) -> int
    def edit(self, code: str) -> Divergence | None
    def resume(self) -> None
    def abort(self) -> None
    def drain(self) -> RunResult
    def result(self) -> RunResult
    @property
    def steps(self) -> list[Step]
    @property
    def code(self) -> str
    @property
    def origin(self) -> list[Step]
    @property
    def divergence(self) -> 'Divergence | None'
    @property
    def finished(self) -> bool
```

## `sandbox`

Source: [implementation](../../vibecoder/sandbox.py).

```python
class SandboxUnavailable:
```

```python
class Launch:
    argv: list[str]
    pass_fds: tuple[int, ...] = ()
    hardening: tuple[str, ...] = field(default=())
```

```python
class Backend:
    name: str = ''
    isolating: bool = False
    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]
    @property
    def hardening(self) -> tuple[str, ...]
    def available(self) -> bool
```

```python
class SubprocessBackend:
    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]
```

```python
class BwrapBackend:
    @staticmethod
    def guest_interpreter() -> str
    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]
    @property
    def hardening(self) -> tuple[str, ...]
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]
```

```python
class DockerBackend:
    @property
    def hardening(self) -> tuple[str, ...]
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]
    @property
    def image(self) -> str
    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]
```

```python
select(*, untrusted: bool=False) -> Backend
```

```python
backend(name: str) -> Backend
```

```python
describe() -> list[tuple[str, bool, bool]]
```

## `seccomp`

Source: [implementation](../../vibecoder/seccomp.py).

```python
current_architecture() -> str | None
```

```python
available() -> bool
```

```python
blocked_syscalls(architecture: str | None=None) -> dict[str, int]
```

```python
build(architecture: str | None=None) -> bytes
```

```python
docker_profile() -> dict
```

## `profiler`

Source: [implementation](../../vibecoder/profiler.py).

```python
class ProfileBudget:
    max_files: int = 20000
    max_total_bytes: int = 64 * 1024 * 1024
    max_seconds: float = 60.0
    max_walk_files: int = 200000
```

```python
iter_python_files(root: Path) -> Iterator[Path]
```

```python
walk_python_files(root: Path, *, budget: ProfileBudget=DEFAULT_BUDGET, deadline: float | None=None) -> tuple[list[Path], str]
```

```python
profile_path(root: str | Path, *, budget: ProfileBudget=DEFAULT_BUDGET, top_libraries: int=15) -> VibeVector
```

```python
profile_archive(path: str | Path, *, limits: IngestLimits=DEFAULT_LIMITS, budget: ProfileBudget=DEFAULT_BUDGET, top_libraries: int=15) -> VibeVector
```

```python
profile_sources(sources: Iterable[tuple[str, str]], *, top_libraries: int=15, budget: ProfileBudget | None=None, deadline: float | None=None, files_seen: int=0, stopped: str='') -> VibeVector
```

```python
style_signature(vibe: VibeVector, *, limit: int=4) -> list[str]
```

```python
derive_tags(vibe: VibeVector) -> list[str]
```

```python
recommend(levels: list, vibe: VibeVector, *, comfort_weight: float=0.4, gap_weight: float=0.6) -> list
```

```python
class Signal:
    label: str
    value: float
    threshold: float
    at_most: bool = False
    @property
    def met(self) -> bool
    @property
    def margin(self) -> float
```

```python
class FunctionClass:
    name: str
    blurb: str
    signals: tuple[Signal, ...]
    @property
    def met(self) -> tuple[Signal, ...]
```

```python
all_classes(vibe: VibeVector) -> list[FunctionClass]
```

```python
derive_class(vibe: VibeVector) -> 'FunctionClass | None'
```

## `ingest`

Source: [implementation](../../vibecoder/ingest.py).

```python
class IngestLimits:
    max_archive_bytes: int = 200 * 1024 * 1024
    max_entries: int = 50000
    max_declared_bytes: int = 500 * 1024 * 1024
    max_file_bytes: int = 4 * 1024 * 1024
    max_ratio: float = 100.0
    ratio_floor: int = 1 * 1024 * 1024
```

```python
class ArchiveRejected:
    def __init__(self, reason: str, message: str) -> None
```

```python
class ArchivePlan:
    path: Path
    members: tuple[zipfile.ZipInfo, ...]
    entries: int
    declared_bytes: int
    compressed_bytes: int
    skipped: int
    @property
    def python_files(self) -> int
```

```python
looks_like_archive(path: str | Path) -> bool
```

```python
inspect_zip(path: str | Path, limits: IngestLimits=DEFAULT_LIMITS) -> ArchivePlan
```

```python
read_plan(plan: ArchivePlan, limits: IngestLimits=DEFAULT_LIMITS) -> Iterator[tuple[str, str]]
```

```python
iter_python_sources(path: str | Path, limits: IngestLimits=DEFAULT_LIMITS) -> Iterator[tuple[str, str]]
```

## `session`

Source: [implementation](../../vibecoder/session.py).

```python
home() -> Path
```

```python
class LevelRecord:
    level_id: str
    attempts: int = 0
    clears: int = 0
    best_total: float = 0.0
    best_stars: int = 0
    last_seed: int = 0
    seeds_played: list[int] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'LevelRecord'
```

```python
class Session:
    def __init__(self, path: Path | None=None) -> None
    @classmethod
    def load(cls, path: Path | None=None) -> 'Session'
    def save(self) -> None
    def daily_played(self, date: str) -> 'Attempt | None'
    def record_daily(self, date: str, level_id: str, seed: int, score: ScoreBreakdown) -> Attempt
    def current_mastery(self) -> Mastery
    def record(self, level_id: str) -> LevelRecord
    def next_seed(self, level_id: str) -> int
    def submit(self, level_id: str, score: ScoreBreakdown, *, seed: int, multipliers: dict[str, float] | None=None, tags: 'Sequence[str]'=()) -> dict[str, Any]
    def recompute_total(self, multipliers: dict[str, float] | None=None) -> float
    def runs_dir(self) -> Path
    def save_run(self, level_id: str, payload: dict[str, Any]) -> str
    def load_run(self, run_id: str) -> dict[str, Any]
    def list_runs(self) -> list[str]
```

## `mastery`

Source: [implementation](../../vibecoder/mastery.py).

```python
observation(accuracy: float, functional: float, first_try: bool) -> float
```

```python
remaining_force(age_days: float) -> float
```

```python
class TagMastery:
    value: float = UNSEEN
    observations: int = 0
    updated_at: str = ''
    @property
    def confident(self) -> bool
    @property
    def seen(self) -> bool
    def age_days(self, now: str) -> float
    def as_of(self, now: str) -> 'TagMastery'
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'TagMastery'
```

```python
class Mastery:
    tags: dict[str, TagMastery] = field(default_factory=dict)
    def value(self, tag: str) -> float
    def confident(self, tag: str) -> bool
    def known_tags(self) -> list[str]
    def confident_tags(self) -> list[str]
    def as_of(self, now: str) -> 'Mastery'
    def observe(self, tags: 'list[str] | tuple[str, ...]', observed: float, *, at: str='') -> dict[str, float]
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'Mastery'
```

## `policy`

Source: [implementation](../../vibecoder/policy.py).

```python
class Decision:
    difficulty: Difficulty
    source: str
    reason: str
    evidence: dict = field(default_factory=dict)
```

```python
choose_difficulty(tags: 'tuple[str, ...] | list[str]', mastery: Mastery, vibe: VibeVector | None=None) -> Decision
```

```python
class Drill:
    tag: str
    levels: tuple[str, ...]
    reason: str
    evidence: dict = field(default_factory=dict)
```

```python
choose_drill(levels, mastery: Mastery) -> 'Drill | None'
```

```python
limits(levels, mastery: Mastery) -> list[str]
```

## `daily`

Source: [implementation](../../vibecoder/daily.py).

```python
class Daily:
    date: str
    level_id: str
    seed: int
```

```python
digest(text: str) -> bytes
```

```python
choose(date: str, level_ids: 'list[str] | tuple[str, ...]') -> 'Daily | None'
```

```python
class Attempt:
    date: str
    level_id: str
    seed: int
    total: float
    stars: int
    ranked: bool = True
    at: str = ''
```

```python
streak(dates: 'list[str] | tuple[str, ...]', today: str) -> int
```

```python
board(attempts: 'list[Attempt] | tuple[Attempt, ...]', limit: int=10) -> list[Attempt]
```

## `fight`

Source: [implementation](../../vibecoder/fight.py).

```python
split_damage(total: int, parts: int) -> list[int]
```

```python
class Repair:
    healed: int
    accuracy: float
    remaining: int
```

```python
class Fight:
    steps: int
    hp: int = DEFAULT_HP
    repairs: int = DEFAULT_REPAIRS
    @property
    def remaining(self) -> int
    @property
    def down(self) -> bool
    @property
    def dealt(self) -> int
    @property
    def cleared(self) -> int
    @property
    def finished(self) -> bool
    @property
    def repairs_left(self) -> int
    @property
    def spent(self) -> int
    @property
    def can_repair(self) -> bool
    @property
    def flawless(self) -> bool
    @property
    def first_try(self) -> int
    def spent_on(self, index: int) -> int
    def damage_for(self, index: int) -> int
    def heal_for(self, accuracy: float) -> int
    def repair(self, accuracy: float=0.0) -> Repair | None
    def refund(self, count: int=1) -> int
    def concede(self, hp: int) -> int
    def waive_next_heal(self) -> None
    def bank_repairs(self, per_repair: int) -> tuple[int, int]
    def clear(self, index: int) -> int
```

## `abilities`

Source: [implementation](../../vibecoder/abilities.py).

```python
class Ability:
    key: str = ''
    name: str = ''
    blurb: str = ''
    cost: str = ''
    def available(self, fight: Fight) -> bool
    def use(self, fight: Fight) -> str
```

```python
class Refactor:
    def available(self, fight: Fight) -> bool
    def use(self, fight: Fight) -> str
```

```python
class SteadyHand:
    def available(self, fight: Fight) -> bool
    def use(self, fight: Fight) -> str
```

```python
class Overclock:
    def available(self, fight: Fight) -> bool
    def use(self, fight: Fight) -> str
```

```python
usable(fight: Fight, keys: 'list[str] | tuple[str, ...]') -> list[Ability]
```

```python
class Gate:
    tags: int
    at_least: float
    def met(self, mastery: Mastery) -> bool
```

```python
unlocked_by(class_name: 'str | None') -> tuple[str, ...]
```

```python
earned(class_name: 'str | None', mastery: Mastery) -> list[Ability]
```

```python
locked(class_name: 'str | None', mastery: Mastery) -> list[tuple[Ability, Gate]]
```

## `timeline`

Source: [implementation](../../vibecoder/timeline.py).

```python
class Timeline:
    def __init__(self, steps: Sequence[Any]=()) -> None
    @property
    def steps(self) -> list[Any]
    @property
    def cursor(self) -> int
    @property
    def current(self) -> Any | None
    @property
    def at_edge(self) -> bool
    @property
    def at_start(self) -> bool
    def back(self) -> Any | None
    def forward(self) -> Any | None
    def append(self, step: Any) -> Any
    def rewind(self) -> None
    def seek(self, index: int) -> Any | None
```

```python
class Divergence:
    index: int
    original: Any
    replayed: Any | None
    reason: str
```

```python
signature(step: Any) -> tuple[str, tuple[tuple[str, str], ...]]
```

```python
compare(original: Sequence[Any], replayed: Sequence[Any], *, upto: int | None=None) -> Divergence | None
```

## `style`

Source: [implementation](../../vibecoder/style.py).

```python
uses_comprehension(node: ast.AST) -> bool
```

```python
uses_generator_expr(node: ast.AST) -> bool
```

```python
no_explicit_loop(node: ast.AST) -> bool
```

```python
uses_enumerate(node: ast.AST) -> bool
```

```python
uses_recursion(node: ast.AST) -> bool
```

```python
single_return(node: ast.AST) -> bool
```

```python
has_type_hints(node: ast.AST) -> bool
```

```python
has_docstring(node: ast.AST) -> bool
```

```python
evaluate(code: str, func_name: str, goals: tuple[str, ...]) -> dict[str, bool]
```

```python
all_met(results: dict[str, bool]) -> bool
```

## `tips`

Source: [implementation](../../vibecoder/tips.py).

```python
class TipContext:
    code: str
    func_name: str
    tree: ast.AST | None
    result: RunResult
    ref_ops: int
    vibe: VibeVector | None
    style_results: dict[str, bool]
```

```python
rule(fn: Rule | None=None, *, kind: str=POLISH)
```

```python
accumulator_loop(ctx: TipContext) -> str | None
```

```python
range_len_indexing(ctx: TipContext) -> str | None
```

```python
range_len_off_by_one(ctx: TipContext) -> str | None
```

```python
manual_sum(ctx: TipContext) -> str | None
```

```python
string_concat_in_loop(ctx: TipContext) -> str | None
```

```python
bare_except(ctx: TipContext) -> str | None
```

```python
inefficient_versus_reference(ctx: TipContext) -> str | None
```

```python
nested_loop_lookup(ctx: TipContext) -> str | None
```

```python
missing_type_hints_for_typed_player(ctx: TipContext) -> str | None
```

```python
unused_style_goals(ctx: TipContext) -> str | None
```

```python
generate(code: str, func_name: str, result: RunResult, *, ref_ops: int=0, vibe: VibeVector | None=None, style_results: dict[str, bool] | None=None, limit: int=3) -> list[str]
```

## `replay`

Source: [implementation](../../vibecoder/replay.py).

```python
render_step(source_lines: Sequence[str], step: dict[str, Any], *, context: int=3, colour: bool=True, width: int | None=None) -> str
```

```python
iter_frames(trace: Sequence[dict[str, Any]]) -> Iterator[tuple[int, dict]]
```

```python
play(source: str, trace: Sequence[dict[str, Any]], *, delay: float=0.35, context: int=3, stream=None, interactive: bool=False) -> None
```

## `vision`

Source: [implementation](../../vibecoder/vision.py).

```python
class Part:
    kind: str
    label: str
    depth: int
    lines: tuple[int, ...]
    parent: int = -1
```

```python
class Machine:
    name: str
    args: str
    parts: tuple[Part, ...]
    by_line: dict[int, int]
    @property
    def title(self) -> str
    def part_for_line(self, line: int) -> int
```

```python
build_machine(source: str, function: str | None=None) -> Machine
```

```python
class Frame:
    step: int
    total: int
    part: int
    line: int
    where: str
    locals: dict[str, str] = field(default_factory=dict)
    iterations: dict[int, int] = field(default_factory=dict)
    changed: str = ''
```

```python
frames(machine: Machine, trace: Sequence[dict[str, Any]]) -> list[Frame]
```

```python
class Row:
    part: int
    role: str
    depth: int
```

```python
layout(machine: Machine) -> list[Row]
```

```python
render(machine: Machine, frame: Frame, *, rows: int=24, columns: int=80, styler: Styler | None=None, glyph: Callable[[str], str] | None=None, palette: dict[str, Any] | None=None) -> Screen
```

```python
palette_from(ui: Any) -> dict[str, Any]
```

```python
sample(built: Sequence[Frame], limit: int) -> list[Frame]
```

```python
still(source: str, trace: Sequence[dict[str, Any]], *, function: str | None=None, step: int | None=None, rows: int=24, columns: int=80, glyph: Callable[[str], str] | None=None) -> str
```

```python
play(source: str, trace: Sequence[dict[str, Any]], *, function: str | None=None, delay: float=0.08, stream: Any=None, interactive: bool=False, budget: float | None=None, limit: int=0) -> int
```

## `pulse`

Source: [implementation](../../vibecoder/pulse.py).

```python
class Reading:
    wpm: float
    evenness: float
    total: int
```

```python
class Pulse:
    window: float = WINDOW
    def press(self, at: float | None=None) -> None
    @property
    def total(self) -> int
    def energy(self, now: float | None=None) -> float
    def wpm(self, now: float | None=None) -> float
    def intervals(self, now: float | None=None) -> list[float]
    def evenness(self, now: float | None=None) -> float
    def state(self, now: float | None=None) -> str
    @property
    def last(self) -> float
    def summary(self) -> Reading
    def trail(self, width: int=24, now: float | None=None) -> list[float]
    def reset(self) -> None
```
