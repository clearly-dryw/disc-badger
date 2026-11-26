# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the text that ruff leaves alone, by the rules in STYLE.md.

Run as `python tools/check_text.py PATH ...` to check the files under the given
paths. It prints each line that breaks a rule, and why, and exits with 1 if any
do.
"""

# Most checks read prose: comment blocks and docstrings in Python files, and `#`
# comment blocks in settings files (CONFIG_SUFFIXES and CONFIG_NAMES). The
# long-line check reads every line of every other text file; ruff checks
# Python's. Which lines are prose, and which belong together, follows the
# conventions in STYLE.md, so the answer is never a guess:
#
# - A paragraph is consecutive lines of a comment block or a docstring. A blank
#   line, or a blank `#` line, ends it.
# - A list item starts with a bullet or a number and full stop, such as `1. `;
#   the lines continuing it are indented under its text.
# - A line ending in `::` introduces text laid out on purpose: the indented
#   lines after it are left as they are.
# - Comments at the end of a line of code aren't prose paragraphs.
#
# A prose line may end only where the next word wouldn't fit within
# LINE_MAX_CHARS. Each other rule is explained beside the code that checks it.

import ast
import codecs
import io
import itertools
import pathlib
import re
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, replace

from exit_code import ExitCode

LINE_MAX_CHARS = 80
"""The longest a line may be, in characters."""

CONFIG_SUFFIXES = (".yml", ".yaml", ".toml")
"""The settings files, by suffix, whose `#` comments are prose too."""

CONFIG_NAMES = (".gitattributes", ".gitignore")
"""The settings files, by name, whose `#` comments are prose too."""

# A list item, by its bullet or number. Only "- " is the bullet STYLE.md allows,
# but "* " and "+ " still start an item, so a list using them is reported for
# its bullets alone.
_LIST_ITEM = re.compile(r"([-*+] |\d+\. )")
_OTHER_BULLET = re.compile(r"^[*+] ")

# Code goes in single backticks everywhere. Double backticks are only for code
# that holds a backtick itself, which single ones can't enclose.
_DOUBLE_BACKTICKS = re.compile(r"``[^`]+``")

# A comment that switches checks off, for a line, a block or a whole file,
# whichever tool reads it: ruff, its formatter, pyright or another type checker.
# Exceptions go in pyproject.toml instead, for a whole file or folder, with a
# reason, where reviewers see every exception in one place. A comment counts at
# its start or after another `#`, in capitals too, as ruff reads them either
# way. Any `ruff:`, `flake8:` or `pyright:` comment counts, even one that makes
# checks stricter, as its settings belong in pyproject.toml too; ruff still
# obeys comments meant for flake8, the tool it replaces.
_EXCEPTION_COMMENT = re.compile(
    r"(^|#)\s*(noqa|ruff:|flake8:|pyright:|type:\s*ignore"
    r"|fmt:\s*(off|on|skip)|isort:\s*(off|on|skip))",
    re.IGNORECASE,
)

# Where a line's text starts: after its indentation, any comment marker, and any
# list bullet or number.
_TEXT_START = re.compile(r"\s*(#+\s*)?([-*+]\s+|\d+\.\s+)?")

# A GitHub action pinned to a full commit, as Dependabot keeps it: the version
# goes in a comment on the same line, where Dependabot updates it, so that
# comment may run past the limit.
_PINNED_ACTION = re.compile(r"\s*(- )?uses: \S+@[0-9a-f]{40} # \S+")

# What each check reports about a line.
_MESSAGE_EARLY_BREAK = (
    f"the next word fits on this line; fill it up to {LINE_MAX_CHARS} columns"
)
_MESSAGE_LONG_LINE = f"this line runs past {LINE_MAX_CHARS} columns; wrap it"
_MESSAGE_OTHER_BULLET = 'lists use "- " for bullets'
_MESSAGE_DOUBLE_BACKTICKS = "put code in single backticks: `code`"
_MESSAGE_LIST_AFTER_TEXT = "leave a blank line before a list in a docstring"
_MESSAGE_BYTE_ORDER_MARK = (
    "this file starts with a byte-order mark; save it as UTF-8 without one"
)
_MESSAGE_EXCEPTION_COMMENT = (
    "move this exception to pyproject.toml, for a whole file or folder, with a "
    "reason"
)

# Text is UTF-8 without a byte-order mark: invisible bytes some editors put
# first, which git shows as a change and some tools stumble on. UTF-16 text
# starts with a mark of its own.
_BYTE_ORDER_MARK = "\ufeff"
_UTF_16_MARKS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


@dataclass(frozen=True)
class Line:
    """One physical line holding prose."""

    number: int
    """The line number, from 1."""
    length: int
    """The physical line's length, without trailing spaces."""
    column: int
    """Where its text starts; for a docstring's first line, the column of the
    opening quotes, so it lines up with the lines after it."""
    text: str
    """The prose itself, without comment markers or quotes."""


def _is_pinned_action(line: str) -> bool:
    """Return whether a line pins an action, and fits up to its comment."""
    return (
        _PINNED_ACTION.fullmatch(line) is not None
        and len(line.split(" #", 1)[0]) <= LINE_MAX_CHARS
    )


def _could_wrap(line: str) -> bool:
    """Return whether a line runs past LINE_MAX_CHARS, though it could wrap."""
    if len(line) <= LINE_MAX_CHARS or _is_pinned_action(line):
        return False
    # Find where the word holding the first column past the limit starts, and
    # where the line's text starts.
    crossing = line.rfind(" ", 0, LINE_MAX_CHARS + 1) + 1
    text = _TEXT_START.match(line)
    return crossing > (text.end() if text else 0)


def _prose_lines(lines: list[Line]) -> Iterator[Line]:
    """Yield a region's lines, blanking the text laid out after a "::" line."""
    laid_out_below = -1  # the column of a "::" line's text, while it applies
    for line in lines:
        if laid_out_below >= 0:
            if not line.text or line.column > laid_out_below:
                yield replace(line, text="")
                continue
            laid_out_below = -1
        yield line
        if line.text.endswith("::"):
            laid_out_below = line.column


def _prose_lines_matching(
    regions: list[list[Line]],
    pattern: re.Pattern[str],
) -> list[int]:
    """Return the numbers of the prose lines the pattern finds a match in."""
    return sorted(
        line.number
        for region in regions
        for line in _prose_lines(region)
        if pattern.search(line.text)
    )


def _close_items(
    items: list[tuple[int, int]],
    column: int,
) -> bool:
    """Close the open items that a line starting at `column` isn't inside.

    Return whether the line starts where one of them did: the next item of its
    list.
    """
    next_item = False
    while items and column < items[-1][1]:
        bullet_column, _ = items.pop()
        next_item = next_item or bullet_column == column
    return next_item


def _lists_after_text_in(region: list[Line]) -> Iterator[int]:
    """Yield the lines of a docstring that start a list straight after text."""
    # The open list items, outermost first: where each one's bullet and text
    # start. A line belongs to every item whose text it's indented under; blank
    # lines don't end an item, which may hold paragraphs.
    items: list[tuple[int, int]] = []
    after_blank = True
    for line in _prose_lines(region):
        if not line.text:
            after_blank = True
            continue
        next_item = _close_items(items=items, column=line.column)
        item = _LIST_ITEM.match(line.text)
        if item and not next_item and not after_blank:
            yield line.number
        if item:
            items.append((line.column, line.column + item.end()))
        after_blank = False


def _check_group(group: list[Line]) -> Iterator[int]:
    """Yield the lines of one paragraph or list item that end early."""
    for line, after in itertools.pairwise(group):
        next_word = after.text.split()[0]
        if line.length + 1 + len(next_word) <= LINE_MAX_CHARS:
            yield line.number


def _check_region(lines: list[Line]) -> Iterator[int]:
    """Yield the lines of one comment block or docstring that end early."""
    group: list[Line] = []
    text_column = 0
    for line in _prose_lines(lines):
        item = _LIST_ITEM.match(line.text)
        joins_group = (
            bool(group)
            and bool(line.text)
            and not item
            and line.column == text_column
        )
        if not joins_group:
            yield from _check_group(group)
            group = []
            text_column = line.column + (item.end() if item else 0)
        if line.text:
            group.append(line)
        # A "::" line ends its paragraph, even if the next line isn't indented.
        if line.text.endswith("::"):
            yield from _check_group(group)
            group = []
    yield from _check_group(group)


def _comment_line(
    line: str,
    number: int,
    column: int,
) -> Line:
    """Return the prose of the comment that starts at `column` of a line."""
    text = line[column + 1 :]
    return Line(
        number=number,
        length=len(line.rstrip()),
        column=column + 1 + len(text) - len(text.lstrip()),
        text=text.strip(),
    )


def _blocks(
    lines: list[str],
    starts: list[tuple[int, int]],
) -> Iterator[list[Line]]:
    """Group whole-line comments, by line number and column, into blocks."""
    block: list[Line] = []
    block_column = -1
    last_number = 0
    for number, column in starts:
        line = lines[number - 1]
        if line[:column].strip():
            continue  # a comment at the end of a line of code
        if block and (number != last_number + 1 or column != block_column):
            yield block
            block = []
        block.append(_comment_line(line, number=number, column=column))
        block_column = column
        last_number = number
    if block:
        yield block


def _comment_regions(source: str) -> list[list[Line]]:
    """Return a Python file's comments: each block, and each end-of-line one."""
    lines = source.splitlines()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    starts = [token.start for token in tokens if token.type == tokenize.COMMENT]
    at_end = [
        [_comment_line(lines[number - 1], number=number, column=column)]
        for number, column in starts
        if lines[number - 1][:column].strip()
    ]
    return [*_blocks(lines=lines, starts=starts), *at_end]


def _is_string(statement: ast.stmt) -> bool:
    """Return whether a statement is a string on its own, as a docstring."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _docstring_lines(
    lines: list[str],
    statement: ast.stmt,
) -> list[Line]:
    """Return a docstring's lines, without its quotes."""
    end = statement.end_lineno or statement.lineno
    found: list[Line] = []
    for number in range(statement.lineno, end + 1):
        raw = lines[number - 1]
        column = len(raw) - len(raw.lstrip())
        text = raw.strip()
        if number == statement.lineno:
            text = re.sub(r'^[rRbBuU]*("""|\'\'\')', "", text)
        text = re.sub(r'("""|\'\'\')$', "", text).strip()
        found.append(
            Line(
                number=number,
                length=len(raw.rstrip()),
                column=column,
                text=text,
            ),
        )
    return found


def _docstrings(source: str) -> Iterator[list[Line]]:
    """Yield each docstring's lines, one list per docstring."""
    lines = source.splitlines()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node,
            ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        ):
            continue
        for index, statement in enumerate(node.body):
            follows_assignment = index > 0 and isinstance(
                node.body[index - 1],
                ast.Assign | ast.AnnAssign,
            )
            if (index == 0 or follows_assignment) and _is_string(statement):
                yield _docstring_lines(lines=lines, statement=statement)


def _files(paths: list[str]) -> Iterator[pathlib.Path]:
    """Yield the files at or under the given paths."""
    for path in map(pathlib.Path, paths):
        if path.is_dir():
            yield from sorted(
                found for found in path.rglob("*") if found.is_file()
            )
        else:
            yield path


def _read_text(path: pathlib.Path) -> str | None:
    """Return a file's text, or None if it's binary.

    Raise UnicodeDecodeError if it's text, but not UTF-8, as UTF-16 text is.
    """
    data = path.read_bytes()
    # UTF-16 text is full of null bytes, so look for its mark first, or it would
    # pass for a binary file.
    if data.startswith(_UTF_16_MARKS):
        raise UnicodeDecodeError("utf-16", data, 0, len(_UTF_16_MARKS[0]), "")
    if b"\0" in data:
        return None
    return data.decode("utf-8").replace("\r\n", "\n")


def _each(
    numbers: list[int],
    message: str,
) -> list[tuple[int, str]]:
    """Pair each line number with the same message."""
    return [(number, message) for number in numbers]


def _is_config(path: pathlib.Path) -> bool:
    """Return whether a file is a settings file with `#` comments."""
    return path.suffix in CONFIG_SUFFIXES or path.name in CONFIG_NAMES


def _prose_problems(regions: list[list[Line]]) -> list[tuple[int, str]]:
    """Return the problems any file's prose can have."""
    return [
        *_each(
            numbers=early_breaks(regions),
            message=_MESSAGE_EARLY_BREAK,
        ),
        *_each(
            numbers=other_bullets(regions),
            message=_MESSAGE_OTHER_BULLET,
        ),
        *_each(
            numbers=double_backticks(regions),
            message=_MESSAGE_DOUBLE_BACKTICKS,
        ),
    ]


def _python_problems(source: str) -> list[tuple[int, str]]:
    """Return the problems a Python file's text can have."""
    # Python's own tools read the file, so code they can't read is reported
    # where it goes wrong, and the other files are still checked. ruff and
    # pyright report it in more detail.
    try:
        return [
            *_prose_problems(regions_python(source)),
            *_each(
                numbers=lists_after_text(source),
                message=_MESSAGE_LIST_AFTER_TEXT,
            ),
            *_each(
                numbers=exception_comments(source),
                message=_MESSAGE_EXCEPTION_COMMENT,
            ),
        ]
    except SyntaxError as error:
        return [(error.lineno or 1, f"this isn't valid Python: {error.msg}")]
    except tokenize.TokenError as error:
        reason, (number, _) = error.args
        return [(number, f"this isn't valid Python: {reason}")]


def _problems(
    path: pathlib.Path,
    source: str,
) -> list[tuple[int, str]]:
    """Return each problem in a file's text: its line number and message."""
    found: list[tuple[int, str]] = []
    if source.startswith(_BYTE_ORDER_MARK):
        found.append((1, _MESSAGE_BYTE_ORDER_MARK))
        source = source.removeprefix(_BYTE_ORDER_MARK)
    # ruff checks the lines of Python files; every other file's are checked
    # here.
    if path.suffix == ".py":
        found += _python_problems(source)
    else:
        found += _each(
            numbers=long_lines(source),
            message=_MESSAGE_LONG_LINE,
        )
        if _is_config(path):
            found += _prose_problems(regions_config(source))
    return sorted(found)


def regions_python(source: str) -> list[list[Line]]:
    """Return a Python file's prose: its comments, then its docstrings.

    A block of whole-line comments is one region, and so is each comment at the
    end of a line of code.
    """
    return [*_comment_regions(source), *_docstrings(source)]


def regions_config(source: str) -> list[list[Line]]:
    """Return a settings file's prose: its blocks of whole-line comments."""
    # Take each line whose text starts with # as a comment. In a YAML block of
    # text, such as a step's shell commands, it's a shell comment: prose too.
    lines = source.splitlines()
    starts = [
        (number, len(line) - len(line.lstrip()))
        for number, line in enumerate(lines, start=1)
        if line.lstrip().startswith("#")
    ]
    return list(_blocks(lines=lines, starts=starts))


def early_breaks(regions: list[list[Line]]) -> list[int]:
    """Return the numbers of the lines that end before they need to."""
    return sorted(
        number for region in regions for number in _check_region(region)
    )


def other_bullets(regions: list[list[Line]]) -> list[int]:
    """Return the numbers of the list items whose bullet isn't `- `."""
    return _prose_lines_matching(regions=regions, pattern=_OTHER_BULLET)


def double_backticks(regions: list[list[Line]]) -> list[int]:
    """Return the numbers of the lines with needless double backticks."""
    return _prose_lines_matching(regions=regions, pattern=_DOUBLE_BACKTICKS)


def exception_comments(source: str) -> list[int]:
    """Return the numbers of the lines whose comments switch a check off."""
    # Read every comment line, examples too: the tools obey an exception
    # wherever it is.
    return sorted(
        line.number
        for region in _comment_regions(source)
        for line in region
        if _EXCEPTION_COMMENT.search(line.text)
    )


def lists_after_text(source: str) -> list[int]:
    """Return the docstring lines that start a list straight after text.

    A nested list starts a list too, so it needs a blank line before it.
    """
    # Docstrings are reStructuredText, which Sphinx reads, and reST runs a list
    # into the paragraph before it unless a blank line separates them.
    return sorted(
        number
        for region in _docstrings(source)
        for number in _lists_after_text_in(region)
    )


def long_lines(source: str) -> list[int]:
    """Return the lines that run past LINE_MAX_CHARS, though they could wrap."""
    # A line may run over only when the word that crosses the limit is the first
    # word of its text, as a long link on a line of its own is: moving it to the
    # next line wouldn't help.
    return [
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if _could_wrap(line.rstrip())
    ]


def main(argv: list[str]) -> ExitCode:
    """Check the files under the given paths; return the exit code."""
    if not argv:
        print("usage: python tools/check_text.py PATH ...")
        return ExitCode.USAGE
    failed = False
    for path in _files(argv):
        try:
            source = _read_text(path)
        except UnicodeDecodeError:
            failed = True
            print(f"{path}: this file isn't UTF-8 text; save it as UTF-8")
            continue
        if source is None:
            continue  # a binary file, such as an image, isn't text
        for number, problem in _problems(path=path, source=source):
            failed = True
            print(f"{path}:{number}: {problem}")
    return ExitCode.PROBLEMS if failed else ExitCode.OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
