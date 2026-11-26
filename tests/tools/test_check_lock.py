# SPDX-License-Identifier: GPL-3.0-or-later
"""The lock file check: uv's own check, and packages only from PyPI."""

import pathlib

import pytest

from exit_code import ExitCode
from tools import check_lock

PROJECT = "disc-badger"
HASH = f"{check_lock.HASH_PREFIX}{'a' * 64}"
WHEEL = f"{check_lock.PYPI_FILES}packages/py3/p/pytest/pytest-9.2.0.whl"
SDIST = f"{check_lock.PYPI_FILES}packages/source/p/pytest/pytest-9.2.0.tar.gz"
FROM_PYPI = f'{{ registry = "{check_lock.PYPI_INDEX}" }}'


def _lock(
    source: str = FROM_PYPI,
    files: str = f'wheels = [{{ url = "{WHEEL}", hash = "{HASH}" }}]',
) -> str:
    """Return a lock file holding the project and one package, pytest."""
    return (
        "version = 1\n"
        "\n"
        "[[package]]\n"
        f'name = "{PROJECT}"\n'
        'version = "0.0.0"\n'
        'source = { editable = "." }\n'
        "\n"
        "[[package]]\n"
        'name = "pytest"\n'
        'version = "9.2.0"\n'
        f"source = {source}\n"
        f"{files}\n"
    )


def _problems(lock: str) -> list[str]:
    """Return the problems the check finds in `lock`."""
    return check_lock.outside_pypi(lock_text=lock, project=PROJECT)


def _check_lock_with(
    path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    lock: str,
    *,
    matches_pyproject: bool,
) -> ExitCode:
    """Run the lock check on `lock`, with uv's own check giving its answer."""
    _ = (path / check_lock.LOCK_FILE).write_text(lock, encoding="utf-8")
    _ = (path / "pyproject.toml").write_text(
        f'[project]\nname = "{PROJECT}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(check_lock, "ROOT", path)
    monkeypatch.setattr(
        check_lock,
        "_matches_pyproject",
        lambda: matches_pyproject,
    )
    return check_lock.main([])


def test_packages_from_pypi_pass() -> None:
    sdist = f'sdist = {{ url = "{SDIST}", hash = "{HASH}" }}'
    wheel = f'wheels = [{{ url = "{WHEEL}", hash = "{HASH}" }}]'
    assert _problems(_lock(files=f"{sdist}\n{wheel}")) == []


def test_the_real_lock_file_takes_everything_from_pypi() -> None:
    lock = (check_lock.ROOT / check_lock.LOCK_FILE).read_text(encoding="utf-8")
    assert _problems(lock) == []


@pytest.mark.parametrize(
    "source",
    [
        '{ registry = "https://example.com/simple" }',  # another index
        '{ url = "https://example.com/pytest.whl" }',  # a file anywhere
        '{ editable = "." }',  # another package, from the repository
    ],
)
def test_a_package_from_elsewhere_is_reported(source: str) -> None:
    [problem] = _problems(_lock(source=source))
    assert problem.startswith("pytest comes from")
    assert problem.endswith("not from PyPI.")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/pytest-9.2.0.whl",  # another server
        "https://files.pythonhosted.org.example.com/pytest-9.2.0.whl",
        "http://files.pythonhosted.org/pytest-9.2.0.whl",  # not encrypted
    ],
)
def test_a_file_from_elsewhere_is_reported(url: str) -> None:
    files = f'wheels = [{{ url = "{url}", hash = "{HASH}" }}]'
    assert _problems(_lock(files=files)) == [
        f"pytest: {url!r} isn't a file on PyPI.",
    ]


def test_a_file_without_a_hash_is_reported() -> None:
    files = f'sdist = {{ url = "{SDIST}" }}'
    assert _problems(_lock(files=files)) == [
        f"pytest: {SDIST!r} has no SHA-256 hash.",
    ]


def test_a_lock_file_from_pypi_matching_pyproject_passes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code = _check_lock_with(
        path=tmp_path,
        monkeypatch=monkeypatch,
        lock=_lock(),
        matches_pyproject=True,
    )
    assert exit_code == ExitCode.OK


def test_a_lock_file_not_matching_pyproject_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_code = _check_lock_with(
        path=tmp_path,
        monkeypatch=monkeypatch,
        lock=_lock(),
        matches_pyproject=False,
    )
    assert exit_code == ExitCode.PROBLEMS


def test_a_package_from_elsewhere_fails_and_says_what_to_do(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _check_lock_with(
        path=tmp_path,
        monkeypatch=monkeypatch,
        lock=_lock(source='{ registry = "https://example.com/simple" }'),
        matches_pyproject=True,
    )
    assert exit_code == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert out.startswith(f"{check_lock.LOCK_FILE}: pytest comes from")
    assert "uv lock --refresh" in out
