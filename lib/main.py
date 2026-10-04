#!/usr/bin/env python3
"""Checks a repository before and after a release, and writes what a release changes in it.

- `version`: whether the candidate version may be released next,
  given the releases already tagged and what waits under `[Unreleased]`.
- `next`: the version that follows a released one, with the source's marker.
- `changelog`: whether every released section still reads as it did when it was released.
- `ancestry`: whether every release tag is still reachable. A history rewrite can take one off.
- `prefix`: what release tags carry in front of the version.
  Read from the source where it declares one, so that the workflows do not have to repeat it.
- `channel`: the distribution channel of a version, read off its pre-release suffix.
- `set-version`: write a version where the project declares it: the released one, then the next.
- `close-changelog`: move what is under `[Unreleased]` into a section of its own.
  This and `set-version` are what a release writes.
- `notes`: the text below one released section's heading, which is what its release notes say.

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
import subprocess
import sys

from rules import sources
from rules.versions import SEMVER, channel_of, check_version, version_after
from rules.changelog import bodies, check_changelog, closed, structure, through, uncompared
from rules.steps import Asked, NOTHING_ASKED, check_step, next_candidate, train_asks
from rules.repository import check_ancestry, git, holder, read_file, released_versions, repository, unreachable


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
# main.py asks an adapter four things, through the functions below:
# whether it declares a version, its marker for a version being worked on, the version it names, the tag prefix.
# set_version_command also hands it the text to rewrite.
# The file an adapter names is read and written here, in the adapter's `encoding`.
# read_declared() reads it, with the adapter's `holds` saying what the file is read for,
# so a missing file is refused the same way whatever the format.
# The top of rules/sources.py lists everything an adapter answers.
SOURCES = sources.SOURCES


def declares_a_version(source: str) -> bool:
    """Whether the source names the version between releases, so that a release reads it there.

    Where it does, a release writes the next version back afterwards.
    Where it does not, `set-version` has nothing to write to, and says so instead of reporting a success."""
    return SOURCES[source].declares_a_version


def marker_of(source: str) -> str:
    """The ending a version has while it is being worked on, hyphen included: `-SNAPSHOT` for gradle.properties.

    Empty where the source has no such state:
    a repository whose version lives only in its tags has no version being worked on."""
    return SOURCES[source].marker


def declared_version(source: str) -> str:
    """The version a declaring source names, marker included.
    Without the marker, it is what a release is asked to be."""
    adapter = SOURCES[source]
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
    adapter = SOURCES[source]
    if adapter.file is not None:
        return as_text(adapter.tag_prefix(read_declared(adapter)), f"tagPrefix in {adapter.file}")
    raise SystemExit(f"--tag-prefix says what release tags are called, which {source} does not declare")


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

        # Work carries the marker, and a release drops it:
        # the released version is the version worked on without the marker, so the two cannot drift apart.
        # Only a marker at the very end comes off, and a version handed in may be given with or without it.
        # One still carrying it after that, such as `1.0.0-SNAPSHOT+b`, is refused by check_version
        # as a version being worked on, which it is.
        candidate = named.removesuffix(marker_of(arguments.version_source))

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
    else:
        # Handed in, or the default where a dispatch left it empty. No file is read, and none will be written.
        releases = released_versions(prefix)
        asked = unreleased_asks(releases)
        candidate = arguments.version or next_candidate(releases, asked)

    problems = check_version(candidate, releases) or check_step(candidate, releases, asked)
    problems += [f"[Unreleased] has an entry under no ### group, so nothing says what kind of change it is: {entry}"
                 for entry in asked.loose]
    if not problems:
        print(candidate)
    return problems


def changelog_command(arguments) -> list[str]:
    in_tree = read_changelog("the released sections")
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)

    at_tag = {}
    for version in released_versions(prefix):
        try:
            at_tag[version] = git("show", f"{prefix}{version}:CHANGELOG.md")
        except subprocess.CalledProcessError:
            # Tagged before the file existed, so there is no section to compare.
            # It is reported below, with the tags older than their section.
            at_tag[version] = ""

    # A copy at a tag is read by the same rules, down to the end of its own section: nothing below it is read.
    # A copy without that section is read whole.
    # One they do not read is told apart from the file in the tree, and a tag cannot be edited to fix it.
    unread = {}
    for version, text in list(at_tag.items()):
        try:
            at_tag[version] = through(text, version)
        except SystemExit as refusal:
            unread[version] = f"{refusal} - as tagged {prefix}{version}"
            del at_tag[version]

    problems = [f"{why}, which cannot be edited, so [{version}] cannot be compared" for version, why in unread.items()]
    problems += check_changelog(in_tree, at_tag, off_history=unreachable(prefix, at_tag))
    if not problems:
        not_compared = uncompared(at_tag)
        print(f"Compared {len(at_tag) - len(not_compared)} released section(s) against the tag that released them.")
        if not_compared:
            print(f"Not compared: {', '.join(not_compared)} - tagged before the section existed, so the tag holds "
                  f"no text to compare against.")
    return problems


def next_command(arguments) -> list[str]:
    released = arguments.released.removeprefix(prefix_from(arguments.version_source, arguments.tag_prefix))
    if not SEMVER.match(released):
        return [f"'{arguments.released}' is not a version this project releases"]
    print(version_after(released) + marker_of(arguments.version_source))
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
    adapter = SOURCES[arguments.version_source]
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
    cannot drift apart. The one difference is the warning release-flow/warn puts above the notes while
    publishing the release elsewhere has not completed.
    An empty section is refused: nobody means to make a release whose notes are empty."""
    text = bodies(read_changelog("the released sections")).get(arguments.version, "")
    if not text.strip():
        return [f"CHANGELOG.md holds nothing for {arguments.version}, so there are no notes to release it with"]
    print(text)
    return []


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


def ancestry_command(arguments) -> list[str]:
    prefix = prefix_from(arguments.version_source, arguments.tag_prefix)
    releases = released_versions(prefix)
    off_history = unreachable(prefix, releases)
    reachability = {version: version not in off_history for version in releases}

    held_by = {
        version: holder(f"{prefix}{version}", version) for version, reached in reachability.items() if not reached
    }
    problems = check_ancestry(reachability, prefix, held_by)
    if not problems:
        print(f"All {len(releases)} released tag(s) are reachable from HEAD.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)

    # A command refuses the options it never reads.
    # `notes` and `channel` read neither, and `set-version` writes a version but names no tag.
    # `close-changelog` reads both only with --repository-url, and takes them either way.
    version_source = argparse.ArgumentParser(add_help=False)
    version_source.add_argument("--version-source", required=True, choices=SOURCES,
                                help="where the version of the next release comes from")
    tag_prefix = argparse.ArgumentParser(add_help=False)
    tag_prefix.add_argument("--tag-prefix", help="what release tags carry in front of the version, for a source "
                                                 "that declares no prefix of its own; '' or ^none for no prefix")
    both = [version_source, tag_prefix]

    version_parser = commands.add_parser("version", parents=both,
                                         help="whether the candidate version may be released next")
    version_parser.add_argument("--version", help="the version to release, not this program's: the one to "
                                                  "check instead of what the source declares, or of the version "
                                                  "after the highest release, or a later one [Unreleased] asks "
                                                  "for, where it declares none, with or without the marker that "
                                                  "source puts on a declaration")
    version_parser.set_defaults(run=version_command)

    next_parser = commands.add_parser("next", parents=both,
                                      help="the version that follows a released one, with the source's marker")
    next_parser.add_argument("released", help="the version just released, with or without the tag prefix")
    next_parser.set_defaults(run=next_command)

    changelog_parser = commands.add_parser("changelog", parents=both,
                                           help="whether released sections still read as released")
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
    notes_parser.set_defaults(run=notes_command)

    prefix_parser = commands.add_parser("prefix", parents=both, help="what release tags carry in front of the version")
    prefix_parser.set_defaults(run=prefix_command)

    channel_parser = commands.add_parser("channel", help="the distribution channel a version is published to")
    channel_parser.add_argument("version", help="the version, without the tag prefix")
    channel_parser.set_defaults(run=channel_command)

    ancestry_parser = commands.add_parser("ancestry", parents=both,
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
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
