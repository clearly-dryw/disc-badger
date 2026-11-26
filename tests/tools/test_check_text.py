# SPDX-License-Identifier: GPL-3.0-or-later
"""The text check: each convention, and a run over files."""

import pathlib

import pytest

from exit_code import ExitCode
from tools import check_text


def words(length: int) -> str:
    """Return words separated by spaces, `length` characters long."""
    text = " ".join(["word"] * (length // 5 + 1))
    return text[:length].rstrip() + "x" * (length - len(text[:length].rstrip()))


def comment(
    length: int,
    indent: str = "",
) -> str:
    """Return a comment line, `length` characters long in all."""
    return indent + "# " + words(length - len(indent) - 2)


def test_filled_comments_pass() -> None:
    source = f"{comment(78)}\n# end\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_a_comment_line_ending_early_is_found() -> None:
    source = f"{comment(60)}\n# fits\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == [1]


def test_a_blank_comment_line_separates_notes() -> None:
    source = f"{comment(60)}\n#\n# A separate note.\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_comment_blocks_at_different_depths_are_separate() -> None:
    source = f"{comment(60)}\n{comment(length=40, indent='    ')}\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_comments_at_the_end_of_code_are_left_alone() -> None:
    source = "x = 1  # short\ny = 2  # short\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_list_items_each_end_their_own_line() -> None:
    source = "# - one item\n# - another item\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_a_list_item_continuing_early_is_found() -> None:
    source = "# - an item\n#   continued\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == [1]


def test_other_bullets_are_found_but_not_as_early_breaks() -> None:
    source = "# * one item\n# * another item\n# + a third\n"
    assert check_text.other_bullets(check_text.regions_python(source)) == [
        1,
        2,
        3,
    ]
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_other_bullets_in_a_docstring_are_found() -> None:
    source = '"""A list.\n\n* an item\n- a good item\n"""\n'
    assert check_text.other_bullets(check_text.regions_python(source)) == [3]


def test_a_star_without_a_space_isnt_a_bullet() -> None:
    source = '"""Take arguments.\n\n*args are passed on.\n"""\n'
    assert check_text.other_bullets(check_text.regions_python(source)) == []


def test_a_bullet_in_a_laid_out_example_is_left_alone() -> None:
    source = (
        '"""Show reST.\n'
        "\n"
        "For example::\n"
        "\n"
        "    * a reST bullet, shown as it is\n"
        '"""\n'
    )
    assert check_text.other_bullets(check_text.regions_python(source)) == []


def test_an_exception_in_a_laid_out_example_still_counts() -> None:
    # The tools obey it wherever it is, so it's reported even in an example.
    source = "# For example::\n#\n#   x = 1  # noqa\n"
    assert check_text.exception_comments(source) == [3]


def test_other_bullets_in_config_comments_are_found() -> None:
    source = "# * an item\nkey: value  # * not a list\n"
    assert check_text.other_bullets(check_text.regions_config(source)) == [1]


def test_needless_double_backticks_are_found() -> None:
    source = (
        '"""Return ``x``.\n'
        "\n"
        "Use `y`, or ``a`b``, which holds a backtick.\n"
        '"""\n'
        "# A ``comment``.\n"
        "z = 1  # and ``this``\n"
        "# A `good` one.\n"
    )
    assert check_text.double_backticks(check_text.regions_python(source)) == [
        1,
        5,
        6,
    ]


def test_needless_double_backticks_in_config_comments_are_found() -> None:
    source = "# Run ``ruff``.\n# Run `ruff`.\n"
    assert check_text.double_backticks(check_text.regions_config(source)) == [1]


@pytest.mark.parametrize(
    "line",
    [
        "a = 1  # noqa",  # ruff, for a line
        "a = 1  # noqa: E501",  # one of ruff's rules, for a line
        "# ruff: noqa",  # ruff, for the whole file
        "# ruff: noqa: E501",  # one of ruff's rules, for the whole file
        "a = 1  # type: ignore",  # type checkers, for a line
        "a = 1  # pyright: ignore[reportAssignmentType]",  # pyright, for a line
        "# pyright: basic",  # a weaker pyright, for the whole file
        "# pyright: reportUnusedCallResult=false",  # a rule, for the file
        "# pyright: strict",  # stricter, but a setting outside pyproject.toml
        "# fmt: off",  # the formatter, for a block
        "a = [1,2]  # fmt: skip",  # the formatter, for a line
        "# isort: skip",  # import sorting, for a line
        "a = 1  # NOQA",  # ruff reads it in any case
        "a = 1  # Noqa: E501",  # the same, for one rule
        "# flake8: noqa: F401",  # flake8's form, which ruff still obeys
        "# FMT: OFF",  # the formatter's, in capitals
    ],
)
def test_a_comment_that_switches_checks_off_is_found(line: str) -> None:
    assert check_text.exception_comments(f"{line}\n") == [1]


@pytest.mark.parametrize(
    "line",
    [
        "x: int = 1  # type: int",  # an old-style type comment, not ignore
        "# The format: off by one.",  # the words, but not a directive
    ],
)
def test_other_comments_with_similar_words_are_fine(line: str) -> None:
    assert check_text.exception_comments(f"{line}\n") == []


def test_the_same_words_outside_a_comment_are_fine() -> None:
    source = 'marker = "# noqa"  # a string, not a comment\n'
    assert check_text.exception_comments(source) == []


def test_an_exception_counts_only_at_a_comments_start() -> None:
    source = (
        "# noqa: E501, on a line of its own\n"
        "x = 1  # a note  # noqa\n"
        "# See ruff's noqa comments.\n"
    )
    assert check_text.exception_comments(source) == [1, 2]


def test_a_list_straight_after_text_is_found() -> None:
    source = '"""Summary.\n\nThe kinds:\n- one\n- two\n"""\n'
    assert check_text.lists_after_text(source) == [4]


def test_a_list_after_a_blank_line_passes() -> None:
    source = (
        '"""Summary.\n'
        "\n"
        "The kinds:\n"
        "\n"
        "- one, which goes on\n"
        "  under its bullet\n"
        "- two\n"
        "\n"
        "For example::\n"
        "\n"
        "    text\n"
        "- not a list after an example\n"
        '"""\n'
    )
    assert check_text.lists_after_text(source) == []


@pytest.mark.parametrize(
    ("body", "found"),
    [
        ("- outer\n\n  - inner\n\n- outer two\n", []),  # blank lines around
        ("- outer\n  - inner\n- outer two\n", [4]),  # nested straight after
        ("- outer\n\n  - inner\n\n  outer goes on\n- outer two\n", []),
        ("1. first\n\n   - detail\n2. second\n", []),  # numbered, then nested
    ],
)
def test_a_nested_list_needs_a_blank_line_before_it(
    body: str,
    found: list[int],
) -> None:
    source = f'"""Summary.\n\n{body}"""\n'
    assert check_text.lists_after_text(source) == found


def test_nested_lists_in_comments_wrap_by_their_own_items() -> None:
    source = (
        "# - an outer item\n"
        "#   - an inner item\n"
        "#     continued too early\n"
        "#   the outer item goes on\n"
        "# - another outer item\n"
    )
    assert check_text.early_breaks(check_text.regions_python(source)) == [2]


def test_a_word_that_wouldnt_fit_is_fine() -> None:
    link = "https://example.com/" + "a" * 40
    source = f"{comment(60)}\n# {link}\n"
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_a_docstring_paragraph_ending_early_is_found() -> None:
    source = (
        "def f() -> None:\n"
        '    """Summary.\n'
        "\n"
        "    Some words.\n"
        "    More words.\n"
        '    """\n'
    )
    assert check_text.early_breaks(check_text.regions_python(source)) == [4]


def test_a_docstring_summary_ending_early_is_found() -> None:
    source = 'x = 1\n"""The value of x,\nfor a test."""\n'
    assert check_text.early_breaks(check_text.regions_python(source)) == [2]


def test_text_after_a_double_colon_is_left_as_laid_out() -> None:
    source = (
        '"""An example.\n'
        "\n"
        "For example::\n"
        "\n"
        "    Error: missing <drive>.\n"
        "    usage: disc-badger eject <drive> [options]\n"
        '"""\n'
    )
    assert check_text.early_breaks(check_text.regions_python(source)) == []


def test_filled_config_comments_pass() -> None:
    source = f"{comment(78)}\n# end\nkey: value\n"
    assert check_text.early_breaks(check_text.regions_config(source)) == []


def test_a_config_comment_ending_early_is_found() -> None:
    source = (
        f"jobs:\n{comment(length=60, indent='  ')}\n  # fits\n  key: value\n"
    )
    assert check_text.early_breaks(check_text.regions_config(source)) == [2]


def test_config_comments_at_the_end_of_a_line_are_left_alone() -> None:
    source = 'ignore = [\n    "S101",  # short\n    "T201",  # short\n]\n'
    assert check_text.early_breaks(check_text.regions_config(source)) == []


PINNED_ACTION = "      - uses: actions/setup-python@" + "0" * 40 + " # v7.1.0"


@pytest.mark.parametrize(
    "line",
    [
        "key: " + "word " * 20,  # spaces throughout
        "# " + "word " * 15 + "x" * 8,  # only its last word crosses the limit
        "  run: " + "x" * 90,  # a long value after its key could move down
    ],
)
def test_a_line_that_could_wrap_is_too_long(line: str) -> None:
    assert check_text.long_lines(f"{line}\n") == [1]


@pytest.mark.parametrize(
    "line",
    [
        "x" * 80,  # exactly the limit
        "# https://example.com/" + "a" * 80,  # a link on a line of its own
        "  - https://example.com/" + "a" * 80,  # the same, as a list item
        PINNED_ACTION,  # Dependabot keeps its version comment on the line
    ],
)
def test_a_line_that_cant_wrap_may_run_over(line: str) -> None:
    assert check_text.long_lines(f"{line}\n") == []


def test_a_pinned_action_must_fit_before_its_comment() -> None:
    line = "      - uses: actions/setup-python@" + "0" * 50 + " # v7.1.0"
    assert check_text.long_lines(f"{line}\n") == [1]


def test_a_run_checks_each_kind_of_file(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Settings files get their comments checked; other text files only their
    # line lengths; binary files nothing.
    early = f"{comment(60)}\n# fits\n"
    for name in ["ci.yml", "settings.toml", ".gitignore", "notes.txt"]:
        _ = (tmp_path / name).write_text(early, encoding="utf-8")
    long = "word " * 20 + "\n"
    _ = (tmp_path / "README.md").write_text(long, encoding="utf-8")
    _ = (tmp_path / "logo.png").write_bytes(b"\x89PNG\0" + long.encode())
    assert check_text.main([str(tmp_path)]) == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert "ci.yml:1: the next word fits" in out
    assert "settings.toml:1: the next word fits" in out
    assert ".gitignore:1: the next word fits" in out
    assert "notes.txt" not in out
    assert "README.md:1: this line runs past" in out
    assert "logo.png" not in out


def test_a_file_that_isnt_utf_8_is_reported(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    latin_1 = tmp_path / "notes.txt"
    _ = latin_1.write_bytes("café\n".encode("latin-1"))
    assert check_text.main([str(latin_1)]) == ExitCode.PROBLEMS
    assert "isn't UTF-8 text" in capsys.readouterr().out


def test_a_run_reports_each_early_line(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    good = tmp_path / "good.py"
    bad = tmp_path / "bad.py"
    _ = good.write_text("# fine\n", encoding="utf-8")
    _ = bad.write_text(f"{comment(60)}\n# fits\n", encoding="utf-8")
    assert check_text.main([str(tmp_path)]) == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert "bad.py:1:" in out
    assert "good.py" not in out
    assert check_text.main([str(good)]) == ExitCode.OK


def test_a_byte_order_mark_is_reported_and_the_rest_still_checked(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marked = tmp_path / "marked.py"
    early = f"{comment(60)}\n# fits\n"
    _ = marked.write_bytes(("\ufeff" + early).encode())
    assert check_text.main([str(marked)]) == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert "marked.py:1: this file starts with a byte-order mark" in out
    assert "marked.py:1: the next word fits" in out


def test_invalid_python_is_reported_and_the_next_file_still_checked(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ = (tmp_path / "a_broken.py").write_text(
        "x = 1\ndef (:\n",
        encoding="utf-8",
    )
    _ = (tmp_path / "b_next.py").write_text(
        f"{comment(60)}\n# fits\n",
        encoding="utf-8",
    )
    assert check_text.main([str(tmp_path)]) == ExitCode.PROBLEMS
    out = capsys.readouterr().out
    assert "a_broken.py:2: this isn't valid Python" in out
    assert "b_next.py:1: the next word fits" in out


def test_an_unfinished_string_is_reported_as_invalid_python(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unfinished = tmp_path / "unfinished.py"
    _ = unfinished.write_text('x = """never closed\n', encoding="utf-8")
    assert check_text.main([str(unfinished)]) == ExitCode.PROBLEMS
    assert "this isn't valid Python" in capsys.readouterr().out


def test_utf_16_text_is_reported_rather_than_skipped(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    utf_16 = tmp_path / "notes.txt"
    _ = utf_16.write_text("Some notes.\n", encoding="utf-16")
    assert check_text.main([str(utf_16)]) == ExitCode.PROBLEMS
    assert "isn't UTF-8 text" in capsys.readouterr().out


def test_no_paths_prints_the_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check_text.main([]) == ExitCode.USAGE
    assert capsys.readouterr().out.startswith("usage:")
