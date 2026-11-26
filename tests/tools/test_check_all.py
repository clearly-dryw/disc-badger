# SPDX-License-Identifier: GPL-3.0-or-later
"""The script that runs every check: its parts, and how it reports."""

import pathlib
import shutil
import subprocess
from collections.abc import Callable

import pytest

from exit_code import ExitCode
from tools import check_all


def _git_repository(path: pathlib.Path) -> None:
    """Make an empty git repository at `path`."""
    git = shutil.which("git")
    assert git is not None
    # Only git, by full path, with fixed arguments, in a folder the test made.
    _ = subprocess.run(
        [git, "init", "--quiet", str(path)],
        capture_output=True,
        check=True,
    )


def _fake_checks(
    results: dict[str, bool],
    ran: list[str],
) -> Callable[[], list[tuple[str, Callable[[], bool]]]]:
    """Return a stand-in for `checks` that records which checks ran."""

    def check(name: str) -> Callable[[], bool]:
        def run() -> bool:
            ran.append(name)
            return results[name]

        return run

    return lambda: [(name, check(name)) for name in results]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("git isn't installed"),  # a missing tool
        TypeError("a bug in the check"),  # a bug fails it the same way
    ],
)
def test_a_check_that_cant_run_fails_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    def cant_run() -> bool:
        raise error

    def ran() -> bool:
        return True

    monkeypatch.setattr(
        check_all,
        "checks",
        lambda: [("Lock file", cant_run), ("Lint", ran)],
    )
    assert check_all.main([]) == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert "Lint" in out  # the next check still ran
    assert out.endswith("Failed: Lock file.\n")
    # The full error is reported, traceback included.
    assert "This check couldn't run" in caplog.text
    assert str(error) in caplog.text
    assert "Traceback" in caplog.text


def test_a_failing_git_command_shows_gits_reason(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Not a repository, so git ls-files fails, with its reason on stderr, in
    # English whatever this system's language.
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.check-text]\nexclude = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    monkeypatch.setenv("LC_ALL", "C")
    text = dict(check_all.checks())["Text"]
    monkeypatch.setattr(check_all, "checks", lambda: [("Text", text)])
    assert check_all.main([]) == ExitCode.PROBLEMS
    assert "not a git repository" in capsys.readouterr().out


def test_the_checks_run_in_ci_order() -> None:
    names = [name for name, _ in check_all.checks()]
    assert names == [
        "File names",
        "Lock file",
        "Formatting",
        "Lint",
        "Text",
        "Types (Windows)",
        "Types (Linux)",
        "Types (macOS)",
        check_all.TESTS,
    ]


def test_the_checks_get_every_file_git_doesnt_ignore(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_repository(tmp_path)
    for name, text in [
        (".gitignore", "ignored/\n"),
        ("top.py", ""),
        ("deep/down/module.py", ""),
        (".github/ci.yml", ""),
        ("ignored/skipped.py", ""),
        ("notes.txt", ""),
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(text, encoding="utf-8")
    _ = (tmp_path / "pyproject.toml").write_text(
        '[tool.check-text]\nexclude = ["notes.txt"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    assert check_all.repository_files() == [
        ".github/ci.yml",
        ".gitignore",
        "deep/down/module.py",
        "notes.txt",
        "pyproject.toml",
        "top.py",
    ]
    assert check_all.python_files() == ["deep/down/module.py", "top.py"]
    assert "notes.txt" not in check_all.text_files()


def test_unusual_names_are_listed_exactly(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # git would quote and escape these, unless asked not to.
    _git_repository(tmp_path)
    for name in ["café.py", "with space.txt"]:
        _ = (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    assert check_all.repository_files() == ["café.py", "with space.txt"]


def test_every_check_runs_and_the_failures_are_named(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran: list[str] = []
    results = {"Lint": False, "Formatting": True, check_all.TESTS: False}
    monkeypatch.setattr(
        check_all, "checks", _fake_checks(results=results, ran=ran)
    )
    assert check_all.main([]) == ExitCode.PROBLEMS
    assert ran == ["Lint", "Formatting", check_all.TESTS]
    assert capsys.readouterr().out.endswith("Failed: Lint, Tests.\n")


def test_no_tests_skips_only_the_tests(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran: list[str] = []
    results = {"Lint": True, check_all.TESTS: False}
    monkeypatch.setattr(
        check_all, "checks", _fake_checks(results=results, ran=ran)
    )
    assert check_all.main(["--no-tests"]) == ExitCode.OK
    assert ran == ["Lint"]
    assert capsys.readouterr().out.endswith("Every check passed.\n")


def test_github_actions_gets_folding_groups(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(
        check_all, "checks", _fake_checks(results={"Lint": True}, ran=ran)
    )
    monkeypatch.setattr(check_all, "_IN_GITHUB_ACTIONS", True)
    assert check_all.main([]) == ExitCode.OK
    assert capsys.readouterr().out.startswith("::group::Lint\n::endgroup::\n")


def test_elsewhere_each_check_gets_a_heading(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(
        check_all, "checks", _fake_checks(results={"Lint": True}, ran=ran)
    )
    monkeypatch.setattr(check_all, "_IN_GITHUB_ACTIONS", False)
    assert check_all.main([]) == ExitCode.OK
    assert capsys.readouterr().out.startswith("== Lint\n")
