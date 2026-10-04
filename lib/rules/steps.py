"""How far the next version has to move: what `[Unreleased]` and an open pre-release train ask for.

Plain functions over the changelog's sections and the released versions, with no repository behind them.
"""

import html
import re
from typing import NamedTuple

from .versions import SEMVER, core, core_text, precedence, successors, version_after
from .changelog import groups, says_something, structure
from .markdown import Line


# How far past the last final release each kind moves the version, by SemVer's rules 6 to 8:
# - patch: backward compatible bug fixes and nothing else (rule 6), so a change to existing functionality asks for more;
# - minor: functionality added or deprecated (rule 7), and a change too;
# - major: something a caller relied on and no longer has.
#   Among Keep a Changelog's kinds that is a removal; under any group, an entry marked **BREAKING**.
# A group of any other name, such as `### Documentation` or `### Dependencies`, asks for a patch.
# Every release is at least a patch anyway, and the groups people add are not new functionality.
# An empty `[Unreleased]` asks for a patch here too: close-changelog is what refuses to release it.
# The indices are the order in which successors() lists the three steps.
PATCH, MINOR, MAJOR = 0, 1, 2
STEP_NAMES = ("patch", "minor", "major")
STEP_OF_KIND = {"Added": MINOR, "Changed": MINOR, "Deprecated": MINOR, "Removed": MAJOR, "Fixed": PATCH,
                "Security": PATCH}
# An entry is a list item, and one that starts with **BREAKING** asks for a major.
BREAKING = re.compile(r"\*\*BREAKING:?\*\*", re.IGNORECASE)
# The first list marker on an item's line, and the spaces up to that item's text.
FIRST_ITEM = re.compile(r" *(?:[-*+]|\d{1,9}[.)]) *")
# An HTML comment closed on its line.
COMMENT = re.compile(r"<!--.*?-->")
# An HTML comment left open where an item's text starts, past its list markers, which hides the rest of the line.
OPEN_COMMENT = re.compile(r"((?: *(?:[-*+]|\d{1,9}[.)]) +)* *)<!--")
# An inline link, whose text alone is shown, and not an image: `[text](destination "title")`.
LINK = re.compile(r"(?<!!)\[([^\]]*)\]\([^)]*\)")
# The marks of emphasis and strikethrough.
EMPHASIS = re.compile(r"[*_~]")


class Asked(NamedTuple):
    """What the entries under `[Unreleased]` ask of the version released with them."""
    step: int  # PATCH, MINOR or MAJOR
    why: str  # What asks for the step, the way a refusal names it; empty for a patch, which nothing refuses.
    unknown: list[str]  # Groups named outside Keep a Changelog's kinds, with no BREAKING entry: read as a patch.
    loose: list[str]  # Entries standing under no group at all.
    where: str = "[Unreleased]"  # The section `why` stands in.


NOTHING_ASKED = Asked(PATCH, "", [], [])


def uncommented(lines: list[str], kinds: list[Line]) -> list[str]:
    """The lines with each HTML comment on them blanked out by spaces where it stood, since GitHub shows none.

    A comment is read on its own line only, and the lines it runs on over are read as they are written.
    One left open hides the rest of its line where it starts an item's text, closed comments before it aside, as a
    browser hides it; elsewhere it is text, as GitHub shows it.
    The spaces keep each character that is left in its column."""
    def blank(line: str, kind: Line) -> str:
        line = COMMENT.sub(lambda comment: " " * len(comment[0]), line)
        start = OPEN_COMMENT.match(line) if kind.kind == "item" else None
        return line[: start.end(1)] + " " * (len(line) - start.end(1)) if start else line

    return [blank(line, kind) for line, kind in zip(lines, kinds)]


def closing(line: str) -> str:
    """What a line of an HTML comment holds after the comment closes on it: ` gone` in `<!-- see below --> gone`, and
    nothing where it does not close.
    That is raw HTML, which GitHub passes on as written: its Markdown is not read, a comment in it is left out, one
    left open hides the rest of the line, and a character reference such as `&nbsp;` stands for its character."""
    _, end, rest = line.partition("-->")
    return html.unescape(COMMENT.sub("", rest).partition("<!--")[0]) if end else ""


def shown(text: str) -> str:
    """Text whose comments uncommented() has already blanked out, read a little closer to how GitHub shows it.

    A link stands for its text, every `*`, `_` and `~` goes, as the marks of emphasis and strikethrough would, and a
    character reference such as `&nbsp;` stands for its character.
    It is no renderer, so it can differ from GitHub either way: a code span is taken as written, an HTML tag as text,
    and a `*`, `_` or `~` GitHub would show is dropped all the same."""
    return html.unescape(EMPHASIS.sub("", LINK.sub(r"\1", text)))


def item_says_something(lines: list[str], seen: list[str], kinds: list[Line], index: int) -> bool:
    """Whether the items line `index` opens say something, on that line or in the text right below it.

    `seen` holds the lines as uncommented() gives them.
    What is read is the text after the last marker on the line, and the lines of text right below it that are indented
    at least as far as the text of the first item: in `- - <!-- c -->`, two spaces for the outer item, four for the
    inner one.
    Any other line ends what is read, such as a blank line, a comment, a code block or a nested item, and so does a line
    indented less: an item whose text stands only past it says nothing here, though GitHub may show that text."""
    first = FIRST_ITEM.match(lines[index])
    own = len(lines[index]) - len(kinds[index].text)
    start = own if first is None else first.end()
    read = [seen[index][own:]]
    for below, look, line in zip(lines[index + 1 :], seen[index + 1 :], kinds[index + 1 :]):
        if line.kind != "text" or len(below) - len(below.lstrip(" ")) < start:
            break
        read.append(look)
    return says_something(shown("\n".join(read)))


def asked_by(unreleased: str) -> Asked:
    """What the text under `[Unreleased]` asks of the next release: the largest step any group asks for,
    and what asks for it.

    - HTML comments count as nothing.
    - An empty group asks for nothing: an empty `### Removed` left as a reminder removes nothing.
      Empty is saying nothing (see says_something()), comments aside.
    - An entry above the first group is under no kind, so nothing says how far it moves the version.
      It is handed back in `loose` for the caller to refuse, not counted as a patch.
    - Other text above the first group, such as a sentence introducing the section, is ignored.
    """
    lines, kinds, headings = unreleased.split("\n"), structure(unreleased), groups(unreleased)
    # An entry holding nothing but a comment, such as `- <!-- what changed -->` left as a reminder, is none.
    # So is an entry or a line of text that says nothing else (see shown() and says_something()), such as a no-break
    # space; a comment is read on its own line (see uncommented()), and what follows one that closes on it counts.
    # An entry that says something only in the text right below its line is one: see item_says_something().
    seen = uncommented(lines, kinds)
    nothing = [line.kind == "blank"
               or line.kind == "html" and not says_something(closing(lines[index]))
               or line.kind == "item" and not item_says_something(lines, seen, kinds, index)
               or line.kind == "text" and not says_something(shown(seen[index]))
               for index, line in enumerate(kinds)]
    lead = headings[0][0] if headings else len(lines)
    loose = [lines[index].strip(" \t\r") for index in range(lead) if kinds[index].kind == "item" and not nothing[index]]
    step, why, unknown = PATCH, "", []
    for at, (index, name) in enumerate(headings):
        end = headings[at + 1][0] if at + 1 < len(headings) else len(lines)
        under = kinds[index + 1 : end]
        if all(nothing[index + 1 : end]):
            continue
        if any(line.kind == "item" and BREAKING.match(line.text) for line in under):
            asks, reason = MAJOR, f"an entry marked **BREAKING** under ### {name}"
        else:
            asks, reason = STEP_OF_KIND.get(name, PATCH), f"### {name}"
            if name not in STEP_OF_KIND:
                unknown.append(name)
        if asks > step:
            step, why = asks, reason
    return Asked(step, why, unknown, loose)


def least_step(asked: int, released: str) -> int:
    """The step `asked` comes to after the final release `released`.

    Below 1.0, a breaking change moves the minor, as Cargo and npm read `^0.y`.
    SemVer's rule 4 promises nothing for 0.y.z,
    and 1.0 is a step taken on purpose, not because something was removed."""
    return MINOR if asked == MAJOR and core(released)[0] == 0 else asked


def check_step(candidate: str, releases: list[str], asked: Asked) -> list[str]:
    """Whether `candidate` moves far enough past the last final release for what `asked` says it releases.

    Measured from the last final release, as the step in check_version is,
    so a pre-release of the version it heads for passes wherever that version would.
    With nothing final released there is no step.
    A candidate outside the allowed steps is check_version's to refuse, not this function's.

    `asked` comes from train_asks: `[Unreleased]`, and the pre-release sections above the last final release.
    A release cut where those sections stand carries their changes as well.
    """
    finals = sorted((version for version in releases if SEMVER.match(version) and SEMVER.match(version).group(4)
                     is None), key=precedence)
    if not finals:
        return []
    permitted = successors(core(finals[-1]))
    least = least_step(asked.step, finals[-1])
    if core(candidate) not in permitted or permitted.index(core(candidate)) >= least:
        return []
    return [f"{asked.where} holds {asked.why}, so the release after {finals[-1]} is at least a "
            f"{STEP_NAMES[least]}, {core_text(permitted[least])}, and {candidate} is not"]


def train_asks(found: dict[str, str], releases: list[str]) -> Asked:
    """What a changelog asks of the next release: the most that `[Unreleased]`, or any pre-release section above
    the last final release, asks for. `found` is the changelog by section, as bodies() gives it.

    A release is cut from a branch, and the changelog on that branch says what it carries.
    Where it holds the sections of an open train, such as 0.3.0-beta.1 with `### Added`,
    the branch carries the train's changes, and a hotfix 0.2.1 cut from it would release them as a patch.
    A branch the train never reached has no such section, and is held to its `[Unreleased]` alone.
    Closing the train, or going on with it, moves the core that far anyway.
    Loose entries and unknown group names are handed back for `[Unreleased]` only:
    a released section is not this release's to refuse.
    """
    asked = asked_by(found.get("Unreleased", ""))
    finals = sorted((version for version in releases if SEMVER.match(version) and SEMVER.match(version).group(4)
                     is None), key=precedence)
    if not finals:
        return asked
    for label, text in found.items():
        if SEMVER.match(label) and SEMVER.match(label).group(4) is not None \
                and precedence(label) > precedence(finals[-1]):
            train = asked_by(text)
            if train.step > asked.step:
                asked = asked._replace(step=train.step, why=train.why, where=f"[{label}]")
    return asked


def next_candidate(releases: list[str], asked: Asked = NOTHING_ASKED) -> str:
    """The version to release when nobody says which.

    It is the version after the highest release, or, where that is further,
    the least step past the last final release that `asked` allows.
    A dispatch form cannot compute a default, so its field is left empty and this fills it in.
    With nothing released there is nothing to count from, so the first version has to be named.
    """
    if not releases:
        raise SystemExit("nothing is released here to count from, so say which version to release")
    after = version_after(sorted(releases, key=precedence)[-1])
    finals = sorted((version for version in releases if SEMVER.match(version).group(4) is None), key=precedence)
    if not finals or not check_step(after, releases, asked):
        return after
    return core_text(successors(core(finals[-1]))[least_step(asked.step, finals[-1])])
