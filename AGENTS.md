# AGENTS.md

Doof (Heinz Doofenshmirtz) is MIT Open Learning's Slack release bot. It listens for
`@doof <command>` in Slack, maps each channel to a project via `repos_info.json`, and
drives the ODL release lifecycle: release notes -> `release-candidate` branch with a
version bump -> "Release X.Y.Z" PR with per-author checkboxes -> wait for RC deploy ->
wait for checkbox sign-off -> merge to `release`, tag, verify prod. Library projects
also publish to PyPI (twine) or npm.

`README.md` is accurate and current - read it for the human-facing side this file
does not cover: the full Doof command list, the release lifecycle in prose, and the
Heroku deployment. This file covers what you need to *change* the code.

## Setup and commands

Python 3.13, managed with **uv**. `npm install` is required, not optional - the
`git-release-notes` binary is invoked from `node_modules/.bin/`.

```bash
npm install            # JS deps (git-release-notes)
uv sync                # Python deps, including the dev group
uv run ruff check      # lint
uv run pytest .        # full suite; coverage is auto-applied via pytest.ini

uv run ruff format                           # format (not gated by CI)
uv run pytest bot_test.py::test_release -x   # single test
uv run python3 bot_local.py micromasters-eng release 4.5.6   # drive Doof from a shell
```

Never use `pip`, `poetry`, or a hand-rolled venv - always `uv`. Run everything through
`uv run` so it uses the project environment.

There is no typechecker and no pre-commit config. `pyproject.toml` has no `[tool.*]`
sections, so ruff runs on defaults.

CI (`.github/workflows/ci.yml`, `on: push`) runs exactly the first four commands -
`npm install`, `uv sync`, `uv run ruff check`, `uv run pytest .` - and nothing else.
A second workflow runs **zizmor** over `.github/workflows/**` - any new workflow step
must be SHA-pinned with least-privilege `permissions:` or it fails.

Two local gotchas:

- **`node` must be on your PATH**, not just installed under `node_modules/`. If your
  environment provides only python and uv (a nix devshell, a slim container), ~10 tests
  in `release_test.py` / `finish_release_test.py` / `version_test.py` fail with
  `FileNotFoundError: 'node'`. CI's `ubuntu-24.04` runner has node preinstalled, so
  this is a local-only gap - check for it before blaming your change.
- `lib.py` is not `ruff format`-clean. CI only gates `ruff check`, so a blind
  `uv run ruff format` adds an unrelated `lib.py` diff. Format only the files you
  touched.

## Layout

Flat modules at the repo root - no package directory, no `src/`. Each module has a
sibling `<module>_test.py`.

| File | Responsibility |
|---|---|
| `bot.py` | `Bot`: Slack I/O, command table, release lifecycle state machine, `get_envs()`, `main()` |
| `bot_local.py` | `ConsoleBot` - run one command from a shell instead of Slack |
| `web.py` | Tornado app: button/event handlers, HMAC `is_authenticated()` |
| `release.py` | Cut the release: notes, version bump, `generate_release_pr` |
| `finish_release.py` | Merge `release-candidate` -> `release`, tag, set release date |
| `publish.py` | `upload_to_pypi` (twine in a virtualenv), `upload_to_npm` |
| `version.py` | Read/write versions per versioning strategy |
| `github.py` | GitHub REST + GraphQL (`run_query`), PRs, labels |
| `slack.py` | Cursor pagination, channel info, Doof's user ID |
| `lib.py` | Shared helpers: `parse_checkmarks`, `get_release_pr`, `init_working_dir`, `load_repos_info` |
| `status.py` | Per-repo release status/emoji for `status` |
| `wait_for_deploy.py` | Poll a `hash.txt` URL until the deployed hash matches |
| `async_subprocess.py` | asyncio `check_call`/`check_output`/`call` - `cwd` is required |
| `client_wrapper.py` | `requests.Session` with retries, wrapped in async methods |
| `constants.py` | Project/versioning/deploy types, GitHub label names, tool paths |
| `exception.py` | `InputException`, `ReleaseException`, and friends |
| `repo_info.py` | The `RepoInfo` namedtuple |
| `repos_info.json` | Config: repo -> channel, URLs, project type, versioning strategy |

## Conventions

- **Async everywhere.** Subprocesses go through `async_subprocess`, which requires an
  explicit `cwd=` because `os.chdir` is not per-coroutine safe. Never call
  `subprocess` or `os.chdir` directly in a coroutine.
- **Never touch the working tree.** All repo work happens in a temp clone via the
  `init_working_dir` async context manager in `lib.py`.
- **Keyword-only args** are the norm:
  `async def finish_release(*, github_access_token, repo_info, version, timezone)`.
  Google-style docstrings (`Args:` / `Returns:`) on essentially every function.
- **`namedtuple`, not dataclasses**, for structs (`RepoInfo`, `Command`, `Parser`,
  `ReleasePR`).
- **Release state lives in GitHub PR labels**, not a database: `deploying to rc`,
  `waiting for checkboxes`, `all checkboxes checked`, `deploying to prod`,
  `deployed to prod` (see `RELEASE_LABELS`). Progress is also read from the release
  PR body's checkboxes via `lib.parse_checkmarks`.
- Bare `except:  # noqa: E722` in `bot.py`'s top-level handlers is **deliberate** -
  it keeps the bot alive. Errors surface to Slack as Doofenshmirtz-flavored quips;
  `InputException` / `ReleaseException` are the expected errors reported verbatim.
- Target repos' default branch is resolved at runtime by `lib.get_default_branch`
  (`main` and legacy `master` both supported). Do not hardcode it.

## Testing

- Test files are **`<module>_test.py`**, colocated at the repo root - *not* `test_*.py`.
- `pytest-asyncio` is in **strict mode**, so every async test module needs a
  module-level `pytestmark = pytest.mark.asyncio` or its tests silently do not run.
- Use **`mocker.async_patch(target, **kwargs)`**, the custom `pytest-mock` extension
  defined in `conftest.py`, instead of `AsyncMock`. It returns the underlying `Mock`
  so you can assert calls:
  `mocker.async_patch("bot.get_release_pr", return_value=None)`.
- An autouse `log_exception` fixture makes `bot.log.exception` / `bot.log.error` raise,
  so a swallowed exception fails the test loudly. Expect that if you add broad excepts.
- Repo fixtures in `conftest.py`: `test_repo`, `library_test_repo`,
  `npm_library_test_repo`, `timezone`. They build **real git repos** by
  `git fast-import`-ing `test-repo.gz` (see `test_util.make_test_repo`).
- No `responses` / `vcr` / `betamax`. Mock GitHub with
  `mocker.async_patch("github.run_query", return_value=<payload>)` using the canned
  JSON payloads; fake Slack with the `DoofSpoof(Bot)` subclass in `bot_test.py`, which
  records messages and exposes `doof.said(...)` for assertions.
- Use the `sleep_sync_mock` fixture (`bot_test.py`) so lifecycle tests do not
  actually wait.
- `@pytest.mark.parametrize` is used heavily - follow suit over copy-pasted cases.

## Environment

`bot.get_envs()` hard-fails at startup unless all of these are set:
`SLACK_ACCESS_TOKEN`, `BOT_ACCESS_TOKEN`, `GITHUB_ACCESS_TOKEN`, `NPM_TOKEN`,
`SLACK_SECRET`, `TIMEZONE`, `PORT`, `PYPI_USERNAME`, `PYPI_PASSWORD`,
`PYPITEST_USERNAME`, `PYPITEST_PASSWORD`. Optional: `SENTRY_SDK` (the Sentry *DSN*,
despite the name).

`BOT_ACCESS_TOKEN` and the `PYPITEST_*` pair are required but currently unused - a
known wart. `bot_local.py` enforces the same list, so fill in fakes for whatever your
command does not need.

Runtime deps are **exact-pinned** (`==`) in `pyproject.toml`; only `ruff` floats.
Keep it that way - Renovate manages the bumps.
