# Contributing to confy

Thanks for your interest in contributing! This document covers everything you need to know to develop on `confy`: setting up the environment, running and writing tests, the known library quirks you'll encounter, and the PR workflow.

If you find anything in here unclear, please open an issue — the docs are part of the contract.

---

## Table of contents

1. [Development setup](#development-setup)
2. [Running the test suite](#running-the-test-suite)
3. [Test suite architecture](#test-suite-architecture)
4. [Adding new tests](#adding-new-tests)
5. [Shared fixtures](#shared-fixtures)
6. [Known library quirks](#known-library-quirks)
7. [Coverage policy](#coverage-policy)
8. [Type checking and linting](#type-checking-and-linting)
9. [PR workflow](#pr-workflow)
10. [Commit message conventions](#commit-message-conventions)

---

## Development setup

`confy` targets **Python 3.10+**. Use a virtual environment so dev dependencies don't pollute your system.

```bash
git clone https://github.com/araray/confy.git
cd confy
python3 -m venv .venv
source .venv/bin/activate                      # POSIX
# .\.venv\Scripts\activate                     # Windows PowerShell
pip install -e ".[dev]"
```

The `[dev]` extra installs:

* `pytest >= 8` — the test runner.
* `pytest-cov >= 4` — coverage integration (`--cov=confy`).
* `coverage[toml] >= 7` — branch coverage with TOML config.

The runtime dependencies (`click`, `python-dotenv`, `tomli`, `tomli-w`) are pulled in by the editable install itself.

---

## Running the test suite

### Full suite

```bash
pytest                                  # 733 passed, 4 xfailed in ~1.6 s
```

### With coverage

```bash
pytest --cov=confy --cov-report=term-missing
```

The coverage gate (`fail_under = 90` in `pyproject.toml`) makes `pytest --cov=confy` exit with code 1 if total coverage drops below 90%. Current coverage is ~95.8%.

### One layer at a time

Tests are tagged with markers (declared in `pyproject.toml [tool.pytest.ini_options].markers`). Use `-m` to run a single layer:

| Marker | Purpose | Approx. count |
|---|---|---|
| `unit` | Pure-function tests — no I/O, no env mutation beyond `monkeypatch`. | ~374 |
| `integration` | Multi-component Config construction with files and env. | ~92 |
| `cli` | Click CLI exercises via `CliRunner`. | ~165 |
| `robustness` | Malformed inputs, optional-dep absence, defensive branches. | ~51 |
| `slow` | Tests >100 ms (reserved for future use). | 0 |

```bash
pytest -m unit                          # fastest layer
pytest -m "integration or cli"          # composite selection
pytest -m "not slow"                    # everything except slow tests
```

### Picking a single file or test

```bash
pytest tests/unit/test_parse_value.py
pytest tests/cli/test_cli_search.py::TestSearchGlob::test_star_wildcard
pytest -k "regex"                       # any test whose name contains "regex"
```

### Stopping at the first failure

```bash
pytest -x                               # exit on first failure
pytest --maxfail=3                      # exit after 3 failures
```

---

## Test suite architecture

The suite is layered by *purpose*, not by *module*. Each layer answers a different question.

```
tests/
├── conftest.py                          # project-wide autouse fixtures
├── test_loader.py                       # legacy monolithic tests (incl. 4 xfailed)
├── v040/                                # v0.4.0 phase tests (preserved)
│
├── unit/                                # "Does this function behave correctly in isolation?"
│   ├── test_parse_value.py              # _parse_value scalar coercion matrix
│   ├── test_dot_path.py                 # get_by_dot / set_by_dot semantics
│   ├── test_deep_merge.py               # _deep_merge precedence and edge cases
│   ├── test_utils.py                    # public utils
│   ├── test_env_collect.py              # _collect_env_vars prefix matching
│   ├── test_env_remap.py                # _remap_and_flatten_env_data heuristics
│   ├── test_config_init_sources.py      # Config init source priority
│   └── test_config_access.py            # __getattr__ / __setattr__ / __contains__
│
├── integration/                         # "Do these components compose correctly?"
│   ├── test_precedence_matrix.py        # full 5-layer pairwise matrix
│   ├── test_dotenv_integration.py       # .env file paths (incl. missing python-dotenv)
│   ├── test_multifile.py                # file_paths, key promotion, errors
│   ├── test_app_namespaces.py           # app_defaults + app_prefixes + app()
│   ├── test_mandatory_validation.py     # mandatory checks across sources
│   └── test_round_trip.py               # Config -> as_dict -> Config equality
│
├── cli/                                 # "Does the CLI behave as a user would expect?"
│   ├── conftest.py                      # CliRunner + json_config / toml_config factories
│   ├── test_cli_root.py                 # top-level group, --help, wiring stubs
│   ├── test_cli_get.py
│   ├── test_cli_set.py
│   ├── test_cli_exists.py
│   ├── test_cli_dump.py
│   ├── test_cli_search.py               # glob/regex/exact dispatch quirks
│   ├── test_cli_convert.py              # JSON <-> TOML
│   ├── test_cli_provenance.py           # --track-provenance reporting
│   ├── test_cli_overrides_parsing.py    # --overrides parsing edge cases
│   └── test_cli_defaults_loading.py     # --defaults file loading edge cases
│
├── argparse_integration/                # "Is the argparse helper API stable?"
│   └── test_argparse_integration.py
│
└── robustness/                          # "Does the library hold up under stress?"
    ├── test_optional_deps.py            # tomli / dotenv missing
    ├── test_loader_branches.py          # residual branch-coverage edges
    └── test_edge_cases.py               # deep nesting, unicode, empty, large data
```

### Why this layering?

1. **Failure localization.** If `test_parse_value.py` fails, you know it's a pure-function regression. If `test_precedence_matrix.py` fails but unit tests pass, it's a composition problem. The hierarchy of failures is informative.
2. **Speed gradient.** Unit tests run in milliseconds; integration in tens of ms; CLI in hundreds. `pytest -m unit` gives an editor-fast feedback loop during development.
3. **Coverage targets.** Each layer was designed to lift coverage in a specific module: unit → loader internals, integration → loader composition, cli → cli.py, argparse_integration → argparse_integration.py, robustness → branch coverage and import-fallback consequences.

---

## Adding new tests

### Decide which layer

* Is this a pure function with no I/O? → `tests/unit/`
* Does this exercise `Config()` construction across multiple sources? → `tests/integration/`
* Is this a CLI behavior or output format? → `tests/cli/`
* Is this an "edge case that doesn't fit normal usage"? → `tests/robustness/`

### Use the right marker

Every test module **must** declare its marker at module scope:

```python
import pytest

pytestmark = pytest.mark.unit       # or .integration, .cli, .robustness
```

`strict_markers = true` in `pyproject.toml` makes pytest fail loudly on undeclared markers. If you need a new marker, add it to the `markers = [...]` list in `pyproject.toml` first.

### Test style

* Prefer **class-based grouping** for related tests (`class TestParseValueIntegers:`). It keeps the test report readable.
* **Docstrings** for non-trivial tests should reference the spec section (`CONFY_DESIGN_SPECIFICATION.md §X.Y`) and the loader/cli line numbers they're pinning.
* **Parametrize** for matrix-style tests instead of writing N near-identical tests:

  ```python
  @pytest.mark.parametrize("input_,expected", [
      ("true", True),
      ("True", True),
      ("false", False),
      ("FALSE", False),
  ])
  def test_bool_parsing(input_, expected):
      assert _parse_value(input_) is expected
  ```

* For CLI tests, **assert on `result.exit_code`, `result.stdout`, and `result.stderr` separately** (Click 8.3+ keeps them distinct).
* **Never patch `logging.getLogger("confy.loader")`** — use `caplog` instead.

### Don'ts

* Do not introduce a real `time.sleep`, `requests.get`, or subprocess spawn in any test. The suite must stay deterministic and fast.
* Do not use `items` as a Config attribute name — it collides with `dict.items()`. (Burned three times during the build-up; documented here to save the fourth.)
* Do not call `Config(load_dotenv_file=True)` in tests unless `.env` behavior is what you're testing. Otherwise pass `load_dotenv_file=False` to keep tests hermetic.

---

## Shared fixtures

### Project-wide (`tests/conftest.py`)

These are **autouse** and run for every test, so you don't need to opt in:

* `_env_snapshot` — saves `os.environ` before each test and restores it after. Lets you use `monkeypatch.setenv(...)` freely without worrying about leakage between tests.
* `_cwd_snapshot` — same idea for the current working directory. Lets you `monkeypatch.chdir(tmp_path)` safely.

Together they make every test start from a clean environmental state.

### CLI factories (`tests/cli/conftest.py`)

* `runner` — a fresh `click.testing.CliRunner` per test.
* `json_config(content_dict)` — writes a JSON file in `tmp_path`, returns the path. Pass a Python dict; the fixture handles the serialization.
* `toml_config(raw_string)` — writes a TOML file in `tmp_path`, returns the path. Takes a raw TOML string (not a dict) so you can control exact format including malformed cases.
* `defaults_file(content_dict)` — writes a defaults JSON file for use with `--defaults`.

Use them like:

```python
def test_dump(runner, json_config):
    fp = json_config({"a": 1, "b": 2})
    result = runner.invoke(cli, ["-c", fp, "dump"])
    assert result.exit_code == 0
```

---

## Known library quirks

These are behaviors the suite pins as "current, intentional state". Some are legitimate design choices; others are documented imperfections we haven't fixed. Read this section before filing a bug.

### 1. `_remap_and_flatten_env_data` Heuristic 0 splits on first underscore only

For an env var like `MYAPP_FEATURE_FLAGS_BETA_FEATURE` where `feature_flags` is a known base key, the remap algorithm splits the reconstructed flat key on the *first* underscore (`feature` + `flags_beta_feature`), so the longest-prefix match against `feature_flags` is missed. The var ends up at flat top-level `feature_flags_beta_feature` instead of nesting under `feature_flags.beta_feature`.

**Impact:** 4 xfail-strict tests in `tests/test_loader.py`. Workaround: name your base keys without internal underscores when possible, or pre-create the nested structure in defaults.

**Fix sketch:** iterate from the longest-prefix candidate downward (similar to Attempt 2 but over reconstructed-flat candidates instead of dot candidates).

### 2. `~/path` is NOT expanded for `--defaults`

The CLI's `--defaults` option opens the path with raw `open()`, so `~/foo.json` is treated as a literal directory name. The `--config` option expands `~` correctly via the loader. This is inconsistent.

**Pinned in:** `tests/cli/test_cli_defaults_loading.py::TestPathExpansion`.

**Fix sketch:** add `os.path.expandvars(os.path.expanduser(path))` in the defaults-loading block of `confy/cli.py`.

### 3. Non-object JSON top-level in `--defaults` crashes with cryptic error

A `--defaults` file containing `[1, 2, 3]`, `"text"`, `42`, or `true` at the top level produces:

```
Error initializing configuration: 'list' object has no attribute 'items'
```

This leaks an internal type name. Users expect either "must be a JSON object" or silent acceptance.

**Pinned in:** `tests/cli/test_cli_defaults_loading.py::TestNonObjectTopLevel`.

**Fix sketch:** detect non-dict top-level in the defaults-loading block and emit a friendly error before passing to `Config()`.

### 4. JSON arrays/objects in `--overrides` values break the parser

`--overrides "arr:[1, 2, 3]"` is split on the comma BEFORE colon-parsing, so the array literal is shredded into three pseudo-pairs (one mangled, two malformed). Objects (`d:{"a": 1, "b": 2}`) are worse: both halves happen to contain colons, so the corruption is silent (no "Malformed" warning).

**Pinned in:** `tests/cli/test_cli_overrides_parsing.py::TestKnownLimitations`.

**Fix sketch:** add `--overrides-json '{"k": [1,2,3]}'` for compound values, or switch the pair separator (e.g., `;` instead of `,`).

### 5. `_parse_value` accepts `inf`, `nan`, `Infinity` as floats

This is a side effect of Python's `float()` constructor accepting those strings. So `export MYAPP_K=inf` sets `cfg.k` to `float('inf')`. Probably not intended but not harmful either.

**Pinned in:** `tests/unit/test_parse_value.py` and `tests/robustness/test_edge_cases.py::TestNumericEdgeCases::test_inf_via_parse_value`.

### 6. `load_dotenv_file` flag changes env-remap fallback behavior

When `load_dotenv_file=True` (Config's default), an env-var dot-key with no structural match falls back to its **original dot form**, producing a nested structure. When `load_dotenv_file=False`, the fallback is the **flat underscore form**. The argparse helper doesn't expose this flag, so its default (`True`) is in effect.

**Pinned in:** `tests/argparse_integration/test_argparse_integration.py::TestLoadConfigFromArgsFullChain::test_disjoint_keys_all_survive` (docstring).

**Fix sketch:** decouple the two behaviors — the fallback strategy should not depend on whether `.env` loading is enabled.

### 7. The argparse helper silently skips malformed `--overrides` pairs

The Click CLI prints a yellow warning when an `--overrides` pair has no colon. The argparse helper drops it silently. Inconsistent but defensible (the argparse helper is the "do-the-right-thing" embed).

**Pinned in:** `tests/argparse_integration/test_argparse_integration.py::TestLoadConfigFromArgsOverrides::test_overrides_malformed_pair_silently_skipped`.

### 8. CLI `search` glob-wins-over-regex dispatch

The `_match` function checks for glob chars (`*?[]`) first, regex chars (`.^$+|(){}`) second. Patterns containing both (e.g., `^foo.*$`) are classified as glob, and `fnmatch` treats `^`, `$`, `.` as literals — so the pattern matches almost nothing. Pure-regex patterns are restricted to alphanumerics plus `^$+|()`.

**Pinned in:** `tests/cli/test_cli_search.py::TestSearchGlob` and `TestSearchRegex`.

**Fix sketch:** add explicit `--regex` / `--glob` flags to disambiguate.

### 9. CLI `search` glob is always case-insensitive

`fnmatch` in `_match` lowercases both sides, so the `-i` flag is redundant for glob patterns (it has effect only for regex patterns).

**Pinned in:** `tests/cli/test_cli_search.py::TestSearchGlob::test_glob_case_insensitive_by_default`.

### 10. `Config.app()` raw-dict wrapping is in-place

When `cfg["myapp"]` is a raw `dict` (e.g., inserted post-construction via `dict.__setitem__`), `cfg.app("myapp")` wraps it into a `Config` *in place*. The original raw dict is replaced inside `cfg`. Documented behavior; the post-construction path is unusual but supported.

**Pinned in:** `tests/integration/test_app_namespaces.py::TestAppRawDictWrap`.

### 11. `Config()` deep-copies its `defaults` argument

Any nested `Config` you pass inside `defaults` is preserved by *value* but not by *identity* (a new `Config` instance is created during deep-copy). Code that does `cfg["nested"] is original_config` will fail. This is correct defensive behavior — defaults are insulated from caller mutation — but worth knowing.

**Pinned in:** `tests/robustness/test_loader_branches.py::TestNestedListsAndScalars::test_complex_structure`.

---

## Coverage policy

* The gate is `fail_under = 90` in `pyproject.toml`.
* Current achieved coverage is ~95.8% (loader 98.3%, CLI 87.6%, argparse helper 100%, everything else 100%).
* The ~5 percentage point gap between gate and reality is deliberate headroom for future small regressions. Don't tighten the gate unless you also accept the maintenance burden of keeping coverage that high.
* **Branch coverage is enabled** (`branch = true` in `[tool.coverage.run]`). A test that hits every line but only one direction of every `if` doesn't count as full coverage. When in doubt, write a second test for the "other" branch.
* The remaining uncovered lines (47 total) are catalogued at the end of `pyproject.toml [tool.coverage.report]`. Most are:
  * Import-time `ImportError` fallbacks for `tomli` / `python-dotenv` (would need a CI matrix job with deps uninstalled to cover).
  * `raise` / `return` after `ctx.exit()` in Click commands (unreachable type-checker fodder).
  * `except` clauses commented as "should not happen" (defensive against bugs introduced elsewhere).

If you find yourself wanting to write a test for one of these to chase coverage, ask first — they are sometimes intentionally unreachable.

---

## Type checking and linting

The project uses `basedpyright` for type checking and `ruff` for linting/formatting. Their configurations live in `pyproject.toml`. Running locally before committing is recommended:

```bash
pip install basedpyright ruff
basedpyright confy/ tests/
ruff check confy/ tests/
ruff format --check confy/ tests/
```

If type-check errors are spurious (e.g., from dynamic dot-notation attribute access), prefer `# pyright: ignore[ruleName]` comments over disabling rules globally.

---

## PR workflow

1. **Check existing issues** — your change may already be tracked.
2. **Fork the repo** on GitHub.
3. **Branch from `main`** — use prefixes like `feat/`, `fix/`, `docs/`, `test/`, `refactor/`:
   ```bash
   git checkout -b feat/short-description main
   ```
4. **Write code AND tests.** Tests are not optional for behavioral changes. For pure-doc PRs, tests aren't needed; mention "documentation only" in the PR description.
5. **Run the full suite locally:**
   ```bash
   pytest
   pytest --cov=confy             # must clear the 90% gate
   ```
6. **Update docs** — `README.md`, docstrings, this file (`CONTRIBUTING.md`), and `CONFY_DESIGN_SPECIFICATION.md` as appropriate. Documentation should match the implementation precisely; don't aspire.
7. **Commit** with clear messages (see below).
8. **Open the PR** against `main`. Include:
   * **What** the change does.
   * **Why** it's needed (link to issue if applicable).
   * **How** it's tested.
   * Any documented quirks or trade-offs.
9. **Respond to review** — be receptive to suggestions; the reviewers want your PR to land.

---

## Commit message conventions

Use conventional-commit-style prefixes:

```
feat:     <new feature or capability>
fix:      <bug fix>
docs:     <documentation only>
test:     <test changes only>
refactor: <code change with no behavioral effect>
perf:     <performance improvement>
chore:    <build, deps, tooling>
```

Examples:

```
feat: add --overrides-json flag for compound values
fix: expand ~ in --defaults file paths (closes #42)
test: pin behavior of env-remap fallback with load_dotenv_file=False
docs: explain glob-wins-over-regex dispatch in search subcommand
refactor: extract _resolve_dotenv_path() from _load_dotenv_file_action
```

Keep the subject line under 72 characters. Use the body (after a blank line) for context, motivation, and any trade-offs. Reference issues with `closes #N`, `refs #N`, etc.

---

Thanks again for contributing! If anything in this document is wrong, incomplete, or surprising, please open an issue or a docs PR — keeping these conventions accurate is part of the work.
