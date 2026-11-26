# SPDX-License-Identifier: GPL-3.0-or-later
"""The file name check: the rule, and a run over names."""

import pytest

from exit_code import ExitCode
from tools import check_all, check_file_names


@pytest.mark.parametrize(
    "name",
    [
        "café.py",  # not ASCII
        "with space.txt",  # a space
        "-oops.py",  # looks like an option
        "docs/-oops/notes.txt",  # the same, in a folder
    ],
)
def test_a_badly_named_file_is_reported(name: str) -> None:
    assert check_file_names.bad_file_names([name, "fine/name_1.2-3.py"]) == [
        name
    ]


def test_the_repositorys_own_names_pass() -> None:
    assert check_file_names.bad_file_names(check_all.repository_files()) == []


def test_a_run_reports_each_bad_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        check_file_names.main(["good.py", "bad name.py"]) == ExitCode.PROBLEMS
    )
    out = capsys.readouterr().out
    assert out.startswith("bad name.py: rename this file")
    assert "good.py" not in out
    assert check_file_names.main(["good.py"]) == ExitCode.OK


def test_a_name_that_looks_like_an_option_is_reported_after_dashes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check_file_names.main(["--", "-oops.py"]) == ExitCode.PROBLEMS
    assert capsys.readouterr().out.startswith("-oops.py: rename this file")
