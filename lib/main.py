#!/usr/bin/env python3
"""Checks a repository before and after a release, and writes what a release changes in it.

- `version`: whether the candidate version may be released next,
  given the releases already tagged and what waits under `[Unreleased]`.
- `next`: the version that follows a released one, with the snapshot suffix given.
- `changelog`: whether every released section still reads as it did when it was released.
- `ancestry`: whether every release tag is still reachable. A history rewrite can take one off.
- `prefix`: what release tags carry in front of the version.
  Read from the source where it declares one, so that the workflows do not have to repeat it.
- `channel`: the distribution channel of a version, read off its pre-release suffix.
- `set-version`: write a version where the project declares it: the released one, then the next.
- `close-changelog`: move what is under `[Unreleased]` into a section of its own.
  This and `set-version` are what a release writes.
- `notes`: the text below one released section's heading, which is what its release notes say.
- `recorded`: what release-flow/prepare recorded in a release's commit, read for the steps that come after it.

This file is the command line over the rules.
The rules are plain functions over text, so their tests need no repository to release:
- rules/versions.py: semantic versions, how they are ordered, and which one may follow which;
- rules/changelog.py: CHANGELOG.md, its sections, closing `[Unreleased]`, and its links;
- rules/markdown.py: which line of CHANGELOG.md is a heading, an entry or code, as GitHub reads it;
- rules/steps.py: how far the next version has to move.
rules/repository.py reads the repository: git, its files, and its release tags.
It also holds check_ancestry, the rule over which release tags this history reaches.
rules/sources.py holds one adapter per kind of repository, for where the version comes from.
"""

import argparse
import datetime
import os
import subprocess
import sys
from typing import NamedTuple

from rules import sources
from rules.versions import SEMVER, SNAPSHOT_SUFFIX, channel_of, check_version, precedence, version_after
from rules.changelog import (UnreadCopy, absolute_links, bodies, check_changelog, closed, missing, referenced,
                             sections, silent, structure, through, uncompared)
from rules.steps import Asked, NOTHING_ASKED, check_step, next_candidate, train_asks
from rules.repository import (carried_by, check_ancestry, git, holder, landed_after, read_file, recorded,
                               released_versions, repository, unreachable)


def in_utf8_mode() -> None:
    """Run this script again in Python's UTF-8 mode (PEP 540) where it was not started in it.

    Everything here is UTF-8 whatever the locale says: CHANGELOG.md, git's output, the names of branches and tags.
    Outside UTF-8 mode, Python decodes git's output, the arguments, and what it prints in the locale's encoding.
    Under a Latin-2 locale a branch named `café` is then named garbled; under an ASCII one, printing it fails.
    The mode settles all of them at once, where an encoding passed to each call would leave the next one to be found.
    Python 3.15 runs in it by default (PEP 686).

    Called by each script's entry point, never on import, so that a test runner importing this file is not restarted.
    The first `-X utf8` on a command line wins over any later `-X utf8=0`, so the new run cannot start without it.
    """
    if sys.flags.utf8_mode:
        return
    if sys.orig_argv[1:3] == ["-X", "utf8"]:
        raise SystemExit(f"{sys.argv[0]} was started again with -X utf8 and is still not in UTF-8 mode")
    os.execv(sys.executable, [sys.executable, "-X", "utf8", *sys.orig_argv[1:]])


# The exit status of a check that found nothing wrong but a release yet to land here, or one landed after this commit.
# A published release is carried back onto the default branch by merge-back, or by its pull request once merged, and
# every commit checked before then is off its tag.
# So is a commit made before it landed and checked after, given the default branch (see landing).
# A caller reads this as it needs, and only check-release tells it from a failure: it warns.
# prepare refuses to cut a release, and merge-back leaves its merged tree to a pull request, as on any other failure.
AWAITING = 4


class Awaiting(str):
    """A problem that is only a published release off this history for a reason that is no fault (see landing)."""


class Arrival(NamedTuple):
    """Where a published release off this history is, when that is no fault."""

    branch: str
    # True: on the default branch already, landed after this commit was made.
    # False: still on its release branch, yet to be carried back.
    landed: bool


def landing(prefix: str, off_history, default_branch: str | None) -> dict[str, Arrival]:
    """Of the released versions off this history, those still on their way here, or landed after this commit, each
    with where it is.

    carried_by() asks the history for a release still on its release branch.
    landed_after() asks it, given the default branch, for one that landed after this commit was made:
    without the name, such a release is failed as a rewrite would be.
    A squash or a rebase merge passes the questions of both, so the tree is asked too.
    Either copies the release commit onto the default branch, and with it the release's section of CHANGELOG.md.
    A release yet to land has no section here.
    A tree whose CHANGELOG.md is missing, is not UTF-8, or holds a line not read, cannot answer.
    ancestry, and version where the file is missing, then fail its releases off this history as if none were on its way;
    changelog, and version where the file is there, name the file's own fault."""
    ordered = sorted(off_history, key=precedence)
    on_the_way = {version: Arrival(branch, False) for version, branch in carried_by(prefix, ordered).items()}
    if default_branch:
        rest = [version for version in ordered if version not in on_the_way]
        on_the_way |= {version: Arrival(branch, True)
                       for version, branch in landed_after(prefix, rest, default_branch).items()}
    if not on_the_way:
        return {}
    try:
        present = sections(read_changelog("the released sections"))
    except SystemExit:
        return {}
    return {version: arrival for version, arrival in on_the_way.items() if version not in present}


def awaited(released: str, arrival: Arrival, held: str) -> Awaiting:
    """The report of a release off this history that is no fault: `released` names it, `held` is what its branch
    holds."""
    if arrival.landed:
        return Awaiting(f"{released}, and landed on {arrival.branch} after this commit was made: the commit is older "
                        f"than the release, not cut off from it")
    return Awaiting(f"{released}, and has yet to land here: {arrival.branch} holds {held} until it is carried back")


def read_declared(adapter, newline: str | None = None) -> str:
    """The file an adapter declares its version in, read in the adapter's encoding."""
    return read_file(adapter.file, adapter.holds, adapter.encoding, newline)


def read_changelog(holds: str, newline: str | None = None) -> str:
    """CHANGELOG.md, refused at the first line outside the part of Markdown read here (see rules/markdown.py)."""
    text = read_file("CHANGELOG.md", holds, newline=newline)
    structure(text)
    return text


# Where the version of a release comes from is the one thing here that depends on the kind of project.
# rules/sources.py decides it, with one adapter per kind of repository.
# main.py asks an adapter three things, through the functions below:
# whether it declares a version, the version it names, the tag prefix.
# set_version_command also hands it the text to rewrite.
# The file an adapter names is read and written here, in the adapter's `encoding`.
# read_declared() reads it, with the adapter's `holds` saying what the file is read for,
# so a missing file is refused the same way whatever the format.
# The top of rules/sources.py lists everything an adapter answers.
SOURCES = sources.SOURCES


def adapter_of(source: str):
    """The adapter `source` names: `gradle.properties`, `gradle.properties:appVersion` or `tags` (see sources.source).
    One that names none is refused."""
    try:
        return sources.source(source)
    except ValueError as refusal:
        raise SystemExit(str(refusal)) from None


def source_argument(value: str) -> str:
    """`--version-source` as given, once sources.source() has read it: argparse refuses one it cannot read."""
    try:
        sources.source(value)
    except ValueError as refusal:
        raise argparse.ArgumentTypeError(str(refusal)) from None
    return value


def declares_a_version(source: str) -> bool:
    """Whether the source names the version between releases, so that a release reads it there.

    Where it does, a release writes the next version back afterwards.
    Where it does not, `set-version` has nothing to write to, and says so instead of reporting a success."""
    return adapter_of(source).declares_a_version


def declared_version(source: str) -> str:
    """The version a declaring source names, snapshot suffix included.
    Without the suffix, it is what a release is asked to be."""
    adapter = adapter_of(source)
    return adapter.version(read_declared(adapter))


def as_text(value: str, named_in: str) -> str:
    """`value` as given, or a refusal where it holds a lone UTF-16 surrogate.

    A lone surrogate is what a command-line byte that does not decode arrives as (PEP 383).
    It is also what gradle.properties reads an unpaired `\\uD800`-`\\uDFFF` escape as, as Java does.
    Neither UTF-8 nor UTF-16 can encode one, so printing or writing it ends in a traceback,
    and a file already opened for writing would be left empty."""
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise SystemExit(f"{named_in} is {ascii(value)}, which holds a lone UTF-16 surrogate - a command-line byte "
                         "that does not decode, or an unpaired \\uD800-\\uDFFF escape - and is no text")
    return value


def prefix_from(source: str, given: str | None) -> str:
    """What a release tag carries in front of its version: `v` in `v0.1.0`, nothing in `0.1.0`.

    Both spellings are in use, so the prefix is declared, never assumed, and there is no default here.
    A wrong guess would pass: a repository that tags bare versions, read as tagging `v*`, has no release tags,
    and every check then passes without comparing anything, with only a note on stderr.
    The exception is `version` under `tags` with no version given: it fails, finding no release to count from.
    A caller that wants a default declares it where its own readers can see it.

    `^none` given says the tags have no prefix, as `''` does.
    It is the spelling the actions' `tag-prefix` input takes, where an empty value means "not given":
    GitHub passes a missing input as an empty string too, so the two cannot be told apart there.
    `^none` can never be a real prefix, because git refuses `^` in a tag name.

    A declared prefix that is not text (see as_text) is refused here, as main() refuses one on the command line.
    No tag name can be spelled with it, so `prefix` would end in a traceback printing it,
    and every other check would pass having found no release.
    """
    if given == "^none":
        return ""
    if given is not None:
        return given
    adapter = adapter_of(source)
    if adapter.file is not None:
        return as_text(adapter.tag_prefix(read_declared(adapter)), f"tagPrefix in {adapter.file}")
    raise SystemExit(f"--tag-prefix says what release tags are called, which {source} does not declare")


def suffix_argument(value: str) -> str:
    """`--snapshot-suffix` as given, once read: a suffix such as `-SNAPSHOT`, `^none`, or empty for not given."""
    if value in ("", "^none") or SNAPSHOT_SUFFIX.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError(f"'{value}' is no snapshot suffix: a hyphen and one identifier of letters and "
                                     "digits holding a letter, such as -SNAPSHOT, or ^none for none")


def suffix_of(given: str | None) -> str:
    """The snapshot suffix a setting names: `^none`, empty or nothing names none."""
    return "" if given in (None, "", "^none") else given


def nearest_recorded(prefix: str) -> dict[str, str] | None:
    """What the release nearest to HEAD recorded, or None where no release HEAD reaches records anything.

    Of the release tags HEAD reaches whose commit records how release-flow/prepare made it, the one fewest commits
    away, and the higher version where two are as near.
    Under a declaring source, that release's merge-back appended its suffix to the next version, which a version
    raised by hand since keeps, so its record says how the declared version is spelled.
    A tag older releases left, whose commit records nothing, is passed over.
    None before the first release a recording prepare made, on a new project and on one that has just moved to it."""
    try:
        reached = git("tag", "--merged", "HEAD").split()
    except subprocess.CalledProcessError:
        return None  # No commit yet, so no release either.
    found = []
    for tag in reached:
        version = tag[len(prefix):]
        if not tag.startswith(prefix) or not SEMVER.match(version) or not recorded(tag):
            continue
        found.append((int(git("rev-list", "--count", f"{tag}..HEAD")), version, settings_at(tag)))
    if not found:
        return None
    nearest = min(distance for distance, _, _ in found)
    return max(((version, settings) for distance, version, settings in found if distance == nearest),
               key=lambda pair: precedence(pair[0]))[1]


def snapshot_suffix(arguments, prefix: str) -> str:
    """The suffix the declared version carries, which a release takes off: the one nearest_recorded() names,
    which its merge-back appended, or the one `--snapshot-suffix` gives where it names none.

    A release made under `tags` records none, because its merge-back wrote no version.
    So does every release before the first a recording prepare made, and none HEAD reaches records one
    between publishing that release and its merge-back landing here.

    `--snapshot-suffix` is required under a declaring source, `^none` included:
    a project chooses its suffix, because no default fits every one.
    check-release and release-flow/prepare pass their snapshot-suffix input, empty where it was left out."""
    if not arguments.snapshot_suffix:
        raise SystemExit(f"--snapshot-suffix is required under {arguments.version_source}: the suffix the declared "
                         "version carries between releases, such as -SNAPSHOT, or ^none for none; check-release and "
                         "release-flow/prepare take it in their snapshot-suffix input")
    nearest = nearest_recorded(prefix)
    if nearest is not None and "snapshot-suffix" in nearest:
        return suffix_of(nearest["snapshot-suffix"])
    return suffix_of(arguments.snapshot_suffix)


def unreleased_asks(releases: list[str]) -> Asked:
    """What CHANGELOG.md asks of the next release, by train_asks.
    Groups under `[Unreleased]` named outside Keep a Changelog's kinds are noted on stderr.

    A repository without the file is asked for a patch at most, with a note on stderr, not refused:
    `version` still compares what it can over the tags,
    and a check that only reads a changelog should not force a project to keep one.
    The same goes for a file with no `[Unreleased]` section, such as `## Unreleased` without the brackets.
    """
    if not (repository() / "CHANGELOG.md").exists():
        print("note: there is no CHANGELOG.md here, so nothing under [Unreleased] says how far the version has to "
              "move", file=sys.stderr)
        return NOTHING_ASKED
    found = bodies(read_changelog("what waits to be released"))
    if "Unreleased" not in found:
        print("note: CHANGELOG.md has no [Unreleased] section, so nothing under it says how far the version has "
              "to move", file=sys.stderr)
        return NOTHING_ASKED
    asked = train_asks(found, releases)
    for name in asked.unknown:
        print(f"note: [Unreleased] has a group '### {name}', which is not a kind of change Keep a Changelog names, "
              f"so it asks for no more than a patch", file=sys.stderr)
    return asked


def version_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)

    if declares_a_version(arguments.version_source):
        named = arguments.version or declared_version(arguments.version_source)

        # Work carries the snapshot suffix, and a release drops it:
        # the released version is the version worked on without the suffix, so the two cannot drift apart.
        # Only a suffix at the very end comes off, and a version handed in may be given with or without it.
        # One still carrying it after that, such as `1.0.0-SNAPSHOT+b`, is refused by check_version
        # as a version being worked on, which it is.
        suffix = snapshot_suffix(arguments, prefix)
        candidate = named.removesuffix(suffix) if suffix else named

        # The commit a release tags still names the version it released.
        # Publishing the release creates that tag, and a workflow that runs on push runs for it too.
        # There `version` is not being asked to release it again, so it says what the commit is and passes.
        # A version handed in is still checked.
        if not arguments.version and f"{prefix}{candidate}" in git("tag", "--points-at", "HEAD").split():
            print(f"note: this commit is the release of {candidate}, tagged {prefix}{candidate}", file=sys.stderr)
            print(candidate)
            return []
        releases = released_versions(prefix)
        asked = unreleased_asks(releases)

        # Until merge-back carries a published release here, the source here still names the version it released,
        # and nothing is wrong with that: the version written back once it lands names the next one.
        # A version handed in is still checked, as on the commit a release tags.
        arriving = {} if arguments.version or candidate not in releases else landing(
            prefix, unreachable(prefix, [candidate]), arguments.default_branch)
    else:
        # Handed in, or the default where a dispatch left it empty. No file is read, and none will be written.
        if suffix_of(arguments.snapshot_suffix):
            raise SystemExit(f"{arguments.version_source} keeps no version between releases, so there is no "
                             "snapshot suffix to give it")
        suffix = ""
        releases = released_versions(prefix)
        asked = unreleased_asks(releases)
        candidate = arguments.version or next_candidate(releases, asked)
        arriving = {}

    loose = [f"[Unreleased] has an entry under no ### group, so nothing says what kind of change it is: {entry}"
             for entry in asked.loose]
    if candidate in arriving:
        return [awaited(f"{candidate} is released, as {prefix}{candidate}", arriving[candidate], "it"), *loose]
    problems = (check_version(candidate, releases, suffix) or check_step(candidate, releases, asked)) + loose
    if not problems:
        print(candidate)
    return problems


def tagged_copy(tag: str) -> str:
    """CHANGELOG.md as `tag` has it, its line endings read as `\\n` as git() reads them.

    A byte that is not UTF-8 is kept as a lone surrogate (PEP 383), so the copy is still read past it,
    and changelog_command names it where it stands in the part that is read."""
    raw = subprocess.run(["git", "show", f"{tag}:CHANGELOG.md"], cwd=repository(), capture_output=True,
                         check=True).stdout
    return raw.decode("utf-8", errors="surrogateescape").replace("\r\n", "\n").replace("\r", "\n")


def changelog_command(arguments) -> list[str]:
    in_tree = read_changelog("the released sections")
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)

    at_tag, unread, began = {}, {}, set()
    for version in released_versions(prefix):
        try:
            at_tag[version] = tagged_copy(f"{prefix}{version}")
        except subprocess.CalledProcessError:
            # Tagged before the file existed, so there is no section to compare.
            # It is reported below, with the tags older than their section.
            at_tag[version] = ""

    # A copy at a tag is read by the same rules, down to the end of its own section: nothing below it is read.
    # A copy without that section is read whole.
    # One they do not read is told apart from the file in the tree, and a tag cannot be edited to fix it.
    # A byte that is not UTF-8 is a line not read too, where it stands in the part that is read.
    # It changes nothing about where a section starts, so the copy is read past it, and the first line not read,
    # a byte or another, is the one named.
    for version, text in list(at_tag.items()):
        undecoded = next((at for at, character in enumerate(text) if "\udc80" <= character <= "\udcff"), None)
        line = None if undecoded is None else text.count("\n", 0, undecoded) + 1
        byte = f"CHANGELOG.md line {line} holds a byte that is not utf-8"
        try:
            kept = through(text, version)
        except UnreadCopy as refusal:
            first = byte if line is not None and line < refusal.line else str(refusal)
            unread[version] = f"{first} - as tagged {prefix}{version}"
            if refusal.began:
                began.add(version)
            del at_tag[version]
            continue
        if line is None or undecoded >= len(kept):
            at_tag[version] = kept
            continue
        unread[version] = f"{byte} - as tagged {prefix}{version}"
        if version in sections(kept):
            began.add(version)
        del at_tag[version]

    off_history, present = unreachable(prefix, [*at_tag, *began]), sections(in_tree)
    # A release yet to land has no section here, and is not compared until it lands.
    arriving = landing(prefix, off_history, arguments.default_branch)
    problems = [] if arguments.skip_unreadable_releases else [
        f"{why}, which cannot be edited, so [{version}] cannot be compared: the skip-unreadable-releases input, "
        f"--skip-unreadable-releases here, names it as not compared instead"
        + ("" if version not in began or version in present or version in arriving
           else ", but its section is not in this tree, which fails either way") for version, why in unread.items()]
    compared = {version: text for version, text in at_tag.items() if version not in arriving}
    problems += check_changelog(in_tree, compared, off_history=off_history)
    # A skipped copy read past the heading of its own section holds that section, so the tree has to hold it too.
    # One refused above that heading may be older than the section, so its absence from the tree proves nothing.
    gone = [] if not arguments.skip_unreadable_releases else sorted(
        (version for version in began if version not in present), key=precedence)
    problems += [missing(version, off_history) for version in gone if version not in arriving]
    problems += [awaited(f"[{version}] is released", arrival, "its section")
                 for version, arrival in arriving.items() if version in at_tag or version in gone]
    if all(isinstance(problem, Awaiting) for problem in problems):
        not_compared = uncompared(compared)
        print(f"Compared {len(compared) - len(not_compared)} released section(s) against the tag that released them.")
        if not_compared:
            print(f"Not compared: {', '.join(not_compared)} - tagged before the section existed, so the tag holds "
                  f"no text to compare against.")
    # Named whatever else fails: the release was passed over on purpose, and the run says so.
    if arguments.skip_unreadable_releases:
        for version, why in unread.items():
            if version in gone:
                continue
            unknown = ("" if version in present
                       else "; the tree has no section for it, and the tag may never have had one")
            print(f"Not compared: {version} - {why}{unknown}")
    return problems


def next_command(arguments) -> list[str]:
    released = arguments.released.removeprefix(prefix_from(arguments.version_source, arguments.tag_prefix))
    if not SEMVER.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(version_after(released) + suffix_of(arguments.snapshot_suffix))
    return []


# The exit status of `set-version` under a source that declares no version.
# Every other refusal of it exits with 1, and argparse exits with 2 on a command line it cannot parse.
# A caller has to tell "there is nothing to write to" from "the write failed": only the first is safe to go on from.
NOTHING_TO_WRITE = 3


def set_version_command(arguments) -> list[str]:
    """Write a version into the file the source declares it in. A release does this twice:
    the version it releases, before the build, and the next one to work on, once the release is out."""
    if not declares_a_version(arguments.version_source):
        print(f"{arguments.version_source} declares no version, so there is nothing here to write one to",
              file=sys.stderr)
        raise SystemExit(NOTHING_TO_WRITE)

    # Read and written with the file's own line endings, so a CRLF file is not rewritten whole to change one line.
    adapter = adapter_of(arguments.version_source)
    path = repository() / adapter.file
    written = adapter.with_version(read_declared(adapter, newline=""), arguments.version)
    with open(path, "w", encoding=adapter.encoding, newline="") as stream:
        stream.write(written)

    # Read back through the same reader everything else here uses.
    # That catches a writer and a reader that have come to disagree, which would otherwise fail silently.
    # It is the reason this is not a pattern in a shell script.
    if declared_version(arguments.version_source) != arguments.version:
        return [f"{arguments.version_source} still does not name {arguments.version} after being rewritten"]
    print(arguments.version)
    return []


def close_changelog_command(arguments) -> list[str]:
    """Close [Unreleased] into a section for the version being released.
    A release does this to the file before it is published."""
    path = repository() / "CHANGELOG.md"
    on = arguments.date or datetime.date.today().isoformat()
    # The prefix is needed only to write links.
    # A source that declares none should not need one just to close a section.
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix) if arguments.repository_url else ""
    # Written back with one line ending: CRLF where the file has any, else a lone CR where it has one, LF otherwise.
    # So a CRLF file is not rewritten whole to add one section.
    # A file mixing them comes back all in the first of these it holds.
    # A lone CR ends a line too, as open() reads one by default.
    # closed() works on LF text either way.
    raw = read_changelog("the released sections", newline="")
    ending = "\r\n" if "\r\n" in raw else "\r" if "\r" in raw else "\n"
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # The new text is computed before the file is opened: opening it for writing empties it,
    # and a refusal raised in between would leave no changelog at all.
    written = closed(text, arguments.version, on, arguments.repository_url, prefix)
    with open(path, "w", encoding="utf-8", newline=ending) as stream:
        stream.write(written)
    print(f"[{arguments.version}] - {on}")
    return []


def notes_command(arguments) -> list[str]:
    """The text of one released section, below its heading: what the release notes say.

    It comes from the same file the changelog check holds to the tag, so the release page and the changelog
    cannot drift apart, link definitions aside: the check compares none, so one edited after the release moves the
    changelog's link and not the page's. The one other difference is the warning release-flow/warn puts above the
    notes while publishing the release elsewhere has not completed.
    An empty section, or one of nothing but comments, is refused: nobody means to make a release whose notes are
    empty.
    The link definitions the section names follow it, from wherever they stand in the file (see referenced()), so a
    reference link such as `[the issue][1]` stays a link.

    With --html they are rendered to HTML by cmark-gfm, the renderer GitHub's Markdown is built on,
    for where Markdown is not read, such as a JetBrains plugin's change notes.
    Shown there, away from the repository, a relative link leads nowhere; given --repository-url and --ref, every one
    is made absolute, read at that tag or commit (see absolute_links())."""
    if (arguments.repository_url is None) != (arguments.ref is None):
        return ["notes takes --repository-url and --ref together: a relative link is read at a ref of a repository"]
    if arguments.repository_url is not None and not arguments.html:
        return ["notes takes --repository-url and --ref only with --html: the release page reads relative links itself"]
    changelog = read_changelog("the released sections")
    text = bodies(changelog).get(arguments.version, "")
    if all(silent(text)):
        return [f"CHANGELOG.md holds nothing for {arguments.version}, so there are no notes to release it with"]
    definitions = referenced(changelog, text)
    if definitions:
        text += "\n\n" + "\n".join(definitions)
    if not arguments.html:
        print(text)
        return []
    rendered = as_html(text)
    if arguments.repository_url is not None:
        rendered, refused = absolute_links(rendered, arguments.repository_url, arguments.ref)
        if refused:
            return refused
    print(rendered, end="")
    return []


def as_html(markdown: str) -> str:
    """Markdown rendered by cmark-gfm, with GitHub's extensions and cmark-gfm's default options.

    Those options leave raw HTML out, comments included: each becomes an `<!-- raw HTML omitted -->`.
    `>` is escaped wherever it lands, in text, code, a link or a title.
    So `]]>`, which ends the CDATA a plugin.xml carries change notes in, cannot come out of it."""
    try:
        import cmarkgfm
    except ImportError:
        raise SystemExit("notes --html renders with cmarkgfm, which is not installed here: "
                         "python3 -m pip install --require-hashes -r lib/requirements.txt") from None
    return cmarkgfm.github_flavored_markdown_to_html(markdown)


def channel_command(arguments) -> list[str]:
    if not SEMVER.match(arguments.version):
        return [f"'{arguments.version}' is not a version; channel takes one without the tag prefix"]
    print(channel_of(arguments.version))
    return []


def prefix_command(arguments) -> list[str]:
    """What release tags carry in front of the version here.

    Printed for the workflows instead of written into them, so a prefix the source declares is declared once,
    and a repository cannot come to disagree with its own tags.
    A source that declares none is handed the prefix, and this prints it back."""
    print(prefix_from(arguments.version_source, arguments.tag_prefix))
    return []


# What release-flow/prepare records in the release commit, each as a trailer `Release-CI-<name>`.
# The steps after it read them there instead of being given them again, so they cannot be given otherwise:
# merge-back writes the next version where prepare read this one, and checks with the options prepare checked with.
# - version: the version released, which the tag has to name;
# - version-source and tag-prefix: as prepare was given them, the prefix as prepare found it, `^none` for none;
# - snapshot-suffix: what merge-back appends to the next version, `^none` for none,
#   recorded where the source declares a version;
# - skip-unreadable-releases: recorded only where it was `true`.
SETTINGS = ("version", "version-source", "tag-prefix", "snapshot-suffix", "skip-unreadable-releases")


def trailer(name: str) -> str:
    """The trailer a setting is recorded in, spelled as release-flow/prepare writes it: `Release-CI-Version-Source`."""
    return "Release-CI-" + "-".join(word.capitalize() for word in name.split("-"))


def settings_at(ref: str) -> dict[str, str]:
    """What release-flow/prepare recorded in the commit `ref` names.

    Refused where it recorded nothing, where a setting it always records is missing,
    and where one is recorded twice: none of them can then be told to be the one the release was made with."""
    found = recorded(ref)
    if not found:
        raise SystemExit(f"{ref} names a commit with no {', '.join(map(trailer, SETTINGS[:3]))} trailers: "
                         "one release-flow/prepare did not cut, or cut before it recorded them")
    twice = sorted(name for name, values in found.items() if len(values) > 1)
    if twice:
        raise SystemExit(f"{ref} names a commit that records {', '.join(map(trailer, twice))} more than once")
    missing = [name for name in SETTINGS[:3] if name not in found]
    if not missing and "snapshot-suffix" not in found and declares_a_version(found["version-source"][0]):
        missing = ["snapshot-suffix"]
    if missing:
        raise SystemExit(f"{ref} names a commit that records no {', '.join(map(trailer, missing))}")
    return {name: values[0] for name, values in found.items()}


def settings_of(tag: str) -> dict[str, str]:
    """What release-flow/prepare recorded in the commit `tag` names, which has to be the tag of that release.

    A draft's tag can be renamed before it is published, and another tag may stand on the same commit.
    Either would have the steps after the release read a version the tag does not name."""
    settings = settings_at(tag)
    prefix = "" if settings["tag-prefix"] == "^none" else settings["tag-prefix"]
    if f"{prefix}{settings['version']}" != tag:
        raise SystemExit(f"{tag} names the release commit of {settings['version']}, which is tagged "
                         f"{prefix}{settings['version']}: was the draft's tag renamed before it was published?")
    return settings


def built_version() -> tuple[str, str]:
    """The source the release commit checked out records, and the version it names there: what the build makes.

    For intellij/build, which runs on that commit, between release-flow/prepare and release-flow/draft.
    The source is read from the commit rather than given, so it is the one prepare wrote the version into."""
    source = settings_at("HEAD")["version-source"]
    if not declares_a_version(source):
        raise SystemExit(f"the release commit records {source}, which declares no version for the build to take")
    return source, declared_version(source)


def recorded_command(arguments) -> list[str]:
    """One setting release-flow/prepare recorded in the commit of a release tag.
    Where it recorded none: `false` for the skip, `^none` for the suffix of a source that keeps no version."""
    value = settings_of(arguments.tag).get(arguments.name, "false" if arguments.name.startswith("skip") else "^none")
    print(value)
    return []


def ancestry_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)
    releases = released_versions(prefix)
    off_history = unreachable(prefix, releases)
    reachability = {version: version not in off_history for version in releases}

    # A release yet to land is off this history for now, not taken off it, and so is one landed after this commit.
    arriving = landing(prefix, off_history, arguments.default_branch)
    for version in arriving:
        del reachability[version]
    held_by = {
        version: holder(f"{prefix}{version}", version) for version, reached in reachability.items() if not reached
    }
    problems = check_ancestry(reachability, prefix, held_by)
    problems += [awaited(f"{prefix}{version} is released", arrival, "it") for version, arrival in arriving.items()]
    if not problems:
        print(f"All {len(releases)} released tag(s) are reachable from HEAD.")
    elif reachability and all(isinstance(problem, Awaiting) for problem in problems):
        print(f"The other {len(reachability)} released tag(s) are reachable from HEAD.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)

    # A command refuses the options it never reads.
    # `notes` and `channel` read neither, and `set-version` writes a version but names no tag.
    # `close-changelog` reads both only with --repository-url, and takes them either way.
    version_source = argparse.ArgumentParser(add_help=False)
    version_source.add_argument("--version-source", required=True, type=source_argument,
                                help="where the version of the next release comes from: "
                                     f"{', '.join(SOURCES)}; gradle.properties:<key> reads it under that key "
                                     "instead of version")
    tag_prefix = argparse.ArgumentParser(add_help=False)
    tag_prefix.add_argument("--tag-prefix", help="what release tags carry in front of the version, for a source "
                                                 "that declares no prefix of its own; '' or ^none for no prefix")
    both = [version_source, tag_prefix]
    default_branch = argparse.ArgumentParser(add_help=False)
    default_branch.add_argument("--default-branch", help="the branch releases land on: a release it holds that landed "
                                                         "after this commit then exits with 4, not failed as a "
                                                         "rewrite")
    checking = [*both, default_branch]

    version_parser = commands.add_parser("version", parents=checking,
                                         help="whether the candidate version may be released next")
    version_parser.add_argument("--version", help="the version to release, not this program's: the one to "
                                                  "check instead of what the source declares, or of the version "
                                                  "after the highest release, or a later one [Unreleased] asks "
                                                  "for, where it declares none, with or without the snapshot "
                                                  "suffix")
    version_parser.add_argument("--snapshot-suffix", type=suffix_argument,
                                help="the suffix the declared version carries, such as -SNAPSHOT, or ^none, where no "
                                     "release's record applies (see lib/README.md); required under a source that "
                                     "declares a version")
    version_parser.set_defaults(run=version_command)

    next_parser = commands.add_parser("next", parents=both,
                                      help="the version that follows a released one, with the snapshot suffix given")
    next_parser.add_argument("released", help="the version just released, with or without the tag prefix")
    next_parser.add_argument("--snapshot-suffix", type=suffix_argument,
                             help="what to append, such as -SNAPSHOT; ^none or left out appends nothing")
    next_parser.set_defaults(run=next_command)

    changelog_parser = commands.add_parser("changelog", parents=checking,
                                           help="whether released sections still read as released")
    changelog_parser.add_argument("--skip-unreadable-releases", action="store_true",
                                  help="leave out, as not compared, a release whose tag holds a CHANGELOG.md line "
                                       "this program does not read, in its section or above it, or anywhere in a "
                                       "copy without that section; one with that line in its own section still "
                                       "fails where the tree does not hold the section")
    changelog_parser.set_defaults(run=changelog_command)

    set_version_parser = commands.add_parser("set-version", parents=[version_source],
                                             help="write a version where the source declares one")
    set_version_parser.add_argument("version", help="the version to write")
    set_version_parser.set_defaults(run=set_version_command)

    close_changelog_parser = commands.add_parser("close-changelog", parents=both,
                                                 help="close [Unreleased] into a released section")
    close_changelog_parser.add_argument("version", help="the version being released")
    close_changelog_parser.add_argument("--date", help="the date to give the section, today by default")
    close_changelog_parser.add_argument("--repository-url", help="write the versions' link definitions afresh, "
                                                                 "pointing into this repository; left alone "
                                                                 "without it")
    close_changelog_parser.set_defaults(run=close_changelog_command)

    notes_parser = commands.add_parser("notes", help="the text below one released section's heading, as "
                                                     "release notes")
    notes_parser.add_argument("version", help="the version whose notes to print")
    notes_parser.add_argument("--html", action="store_true", help="print them as HTML, rendered by cmark-gfm as "
                                                                  "on GitHub; needs lib/requirements.txt")
    notes_parser.add_argument("--repository-url", help="with --html and --ref, make every relative link absolute, "
                                                       "into this repository")
    notes_parser.add_argument("--ref", help="with --html and --repository-url, the tag or commit a relative link is "
                                            "read at")
    notes_parser.set_defaults(run=notes_command)

    prefix_parser = commands.add_parser("prefix", parents=both, help="what release tags carry in front of the version")
    prefix_parser.set_defaults(run=prefix_command)

    channel_parser = commands.add_parser("channel", help="the distribution channel a version is published to")
    channel_parser.add_argument("version", help="the version, without the tag prefix")
    channel_parser.set_defaults(run=channel_command)

    recorded_parser = commands.add_parser("recorded", help="a setting release-flow/prepare recorded in the commit of "
                                                           "a release tag")
    recorded_parser.add_argument("tag", help="the release's tag, which has to be the one its commit records")
    recorded_parser.add_argument("name", choices=SETTINGS, help="the setting to print")
    recorded_parser.set_defaults(run=recorded_command)

    ancestry_parser = commands.add_parser("ancestry", parents=checking,
                                          help="whether every released tag is still reachable")
    ancestry_parser.set_defaults(run=ancestry_command)

    arguments = parser.parse_args()
    # Arguments that are not text are refused once, here, not wherever an argument is printed or written.
    # Every subcommand, including any added later, is then handed text.
    for name, value in vars(arguments).items():
        if isinstance(value, str):
            as_text(value, f"the {name.replace('_', '-')} argument")
    problems = arguments.run(arguments)

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems and all(isinstance(problem, Awaiting) for problem in problems):
        print("Nothing else was found. The release lands here once merge-back carries it back, or once its pull "
              "request is merged; no release can be prepared from here before then.", file=sys.stderr)
        return AWAITING
    return 1 if problems else 0


if __name__ == "__main__":
    in_utf8_mode()
    sys.exit(main())
