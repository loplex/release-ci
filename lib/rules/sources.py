"""Where the version of the next release comes from: one adapter per kind of repository.

The rules know no source by name; main.py asks the adapter for them.

An adapter is a plain object over text.
main.py reads and writes the file an adapter names, and the adapter says what that text declares
and what it becomes.
So each adapter can be tested without a repository,
and finding the file, or refusing a missing one, is written once instead of once per format.

There are two kinds of source:
- One that declares a version keeps the next version in a file between releases,
  marked as being worked on where its ecosystem has a marker for that.
  A release reads the version from that file and writes the following one back.
- One that declares nothing is given the version when a release is asked for.
  Without one, it takes the version after the highest release, or a later one where `[Unreleased]` asks for more.
  It records nothing afterwards, because it has no file to record it in.

What every adapter answers:
- `name`: the `--version-source` value that selects it.
- `declares_a_version`.
- `marker`: the ending of a version being worked on, hyphen included (`-SNAPSHOT` for gradle.properties),
  or empty where there is no such state.
- `file`: the file it declares a version in, or None where it declares none.

An adapter that declares a version also answers:
- `holds`: what the file is read for, named in the refusal when the file is missing.
- `encoding`: how the file's bytes are read and written back.
- `version()` and `tag_prefix()` over the file's text, and `with_version()`, the text with a new version in it.

The tag prefix comes from the file.
main.py asks tag_prefix() of every source that names a file, unless `--tag-prefix` is given.
A source that names no file is given its prefix.

Adding a source, such as package.json, pyproject.toml or Cargo.toml:
- It is another adapter here, its file carrying the tag prefix beside the version,
  filed in SOURCES under its `--version-source` name.
- Nothing in main.py or the other modules of rules/ changes, unless the source marks a version being
  worked on other than with a `-SNAPSHOT` suffix, the only marker being_worked_on in versions.py knows.
- test_sources.py holds it to what every adapter has to answer, and fails if the rules do not refuse its marker.
- A plain VERSION file has no room for a tag prefix, so it needs more than an adapter.
"""

import re

# gradle.properties is a Java properties file, and Gradle reads it with java.util.Properties.
# It is read here the way Properties.load() documents, so the version and the prefix are the ones the build sees:
# - A natural line ends at `\n`, `\r` or `\r\n`.
# - A line ending in an odd number of backslashes goes on in the next, whose leading white space is dropped.
# - `#` or `!` opens a comment only at the start of a logical line.
# - The key runs to the first `=`, `:` or white space that is not escaped.
# - An escape is `\t`, `\n`, `\r`, `\f`, `\uXXXX`, or a backslash before any other character,
#   which then stands for itself.
NATURAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
KEY_AND_VALUE = re.compile(r"((?:\\.|[^\\=: \t\f])*)[ \t\f]*[=:]?[ \t\f]*(.*)", re.DOTALL)
ESCAPE = re.compile(r"\\(u[0-9A-Fa-f]{4}|u|.)", re.DOTALL)


def logical_lines(text: str) -> list[tuple[int, int, str]]:
    """Every logical line of a properties file that declares something, as (start, end, line).

    `start` is where its first natural line starts, `end` where its last one ends,
    and `line` is the logical line with its continuations joined."""
    found, start, joined = [], 0, None
    for match in NATURAL_LINE.finditer(text):
        natural = match.group(0).rstrip("\r\n")
        body = natural.lstrip(" \t\f")
        if joined is None:
            if not body or body[0] in "#!":
                continue
            start, joined = match.start(), ""
        joined += body
        if (len(body) - len(body.rstrip("\\"))) % 2:
            joined = joined[:-1]
            continue
        found.append((start, match.start() + len(natural), joined))
        joined = None
    if joined is not None:
        found.append((start, len(text), joined))
    return found


def unescaped(text: str) -> str:
    """A key or a value with its escapes read.

    A `\\u` not followed by four hex digits is refused, as Properties refuses it.
    Two that make a UTF-16 surrogate pair are one character, as they are in the Java string Properties reads them
    into."""
    def one(escape):
        code = escape.group(1)
        if code == "u":
            raise SystemExit(f"gradle.properties has a malformed \\uxxxx escape in '{text}', which Gradle refuses "
                             "as well")
        escapes = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}
        return chr(int(code[1:], 16)) if len(code) == 5 else escapes.get(code, code)
    return ESCAPE.sub(one, text).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def stored(value: str) -> str:
    """A value written the way Properties.store(OutputStream) writes one.

    The file then reads it back as it was given, and no character of text fails to encode:
    - a backslash is doubled;
    - a tab, a line break and a form feed become their escapes;
    - a leading space, and `=`, `:`, `#`, `!`, get a backslash in front;
    - every other character below a space or above `~` becomes `\\uXXXX`,
      and a character outside the first 65536 becomes the two units of its UTF-16 pair.

    A lone surrogate is no character of text.
    On the command line it is what Python makes of a byte its filesystem encoding cannot decode,
    and main() refuses it there.
    One handed here any other way is refused by the UTF-16 encoding below, before the file is opened for writing.
    Properties.store(OutputStream) would write it as `\\uXXXX` instead."""
    escapes = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r", "\f": "\\f"}
    written = []
    for at, character in enumerate(value):
        if character in escapes:
            written.append(escapes[character])
        elif character in "=:#!" or (character == " " and at == 0):
            written.append("\\" + character)
        elif not " " <= character <= "~":
            units = character.encode("utf-16-be")
            written.extend(f"\\u{int.from_bytes(units[i:i + 2], 'big'):04X}" for i in range(0, len(units), 2))
        else:
            written.append(character)
    return "".join(written)


class Tags:
    """A repository whose version lives only in its tags.

    It declares no version and no tag prefix:
    - the prefix is given;
    - the version is given, or it is the one after the highest release,
      or a later one where `[Unreleased]` asks for more;
    - no version is being worked on, so there is no marker."""

    name = "tags"
    declares_a_version = False
    file = None
    marker = ""


class GradleProperties:
    """gradle.properties, the Java properties file a project declares its version and its tag prefix in.

    `-SNAPSHOT` is how Gradle and Maven mark a version being worked on.
    It is never released to any channel:
    `version` refuses a candidate that still carries it, and no tag that carries it counts as a release.
    """

    name = "gradle.properties"
    declares_a_version = True
    file = "gradle.properties"
    holds = "the version and tagPrefix"
    # Gradle hands the file to Properties.load() as bytes, which reads each byte as one Latin-1 character
    # instead of decoding UTF-8.
    # Read and written the same way here, no byte in the file fails to decode.
    # A comment, or any value but the version, goes back in the bytes it was read from, whatever its encoding.
    encoding = "iso-8859-1"
    marker = "-SNAPSHOT"

    # What a release puts back in front of the version it writes:
    # the indentation, the key and the separator, exactly as the first line of the declaration has them.
    # Gradle allows space around the separator and before the key, and projects write it every way.
    # Choosing one spelling here would show in the diff as a change nobody made,
    # and so would an indented declaration moved to the margin.
    # Where a continuation splits the key itself, the first line holds only part of it,
    # and the declaration is written as `version = ` after that line's indentation.
    DECLARATION_LEAD = re.compile(r"[ \t\f]*(?:\\[^\r\n]|[^\\=: \t\f\r\n])*[ \t\f]*[=:]?[ \t\f]*")

    def properties(self, text: str) -> dict[str, str]:
        """Every key the file declares, with its value, read the way Gradle reads them (see NATURAL_LINE).

        `version = 0.2.0`, `version=0.2.0` and `version: 0.2.0` all declare it, and so does a continued line.
        Escapes are read.
        A key declared twice keeps its last value, as it does for Gradle."""
        found = {}
        for _, _, line in logical_lines(text):
            key, value = KEY_AND_VALUE.match(line).groups()
            found[unescaped(key)] = unescaped(value)
        return found

    def version(self, text: str) -> str:
        """The version the file names, marker included.

        A release is asked to be this version with the marker taken off."""
        declared = self.properties(text).get("version")
        if declared is None:
            raise SystemExit("gradle.properties names no version")
        return declared

    def tag_prefix(self, text: str) -> str:
        """What release tags carry in front of the version.

        A prefix declared empty is a prefix too: the project tags bare versions.
        A prefix left out is refused, because a wrong guess would pass every check."""
        prefix = self.properties(text).get("tagPrefix")
        if prefix is None:
            raise SystemExit("gradle.properties does not say, in tagPrefix, what release tags are called")
        return prefix

    def with_version(self, text: str, version: str) -> str:
        """The file with the version's declaration rewritten and everything else left alone.

        The replacement is built by hand, so the version is data: `&` and `\\1` in it are characters,
        not instructions.
        The version is escaped as Properties.store(OutputStream) escapes a value (see stored()),
        so the file reads it back as it was given.

        A file that declares the version more than once is refused.
        The reader takes the last declaration, as Gradle does:
        - rewriting another one would leave the version the build sees unchanged;
        - rewriting the last one would leave a stale line above it for the next reader to trust.
        """
        declarations = [(start, end) for start, end, line in logical_lines(text)
                        if unescaped(KEY_AND_VALUE.match(line).group(1)) == "version"]
        if not declarations:
            raise SystemExit("gradle.properties names no version to rewrite")
        if len(declarations) > 1:
            raise SystemExit(f"gradle.properties declares the version {len(declarations)} times, and a release "
                             f"rewrites one declaration: say it once")
        start, end = declarations[0]
        lead = self.DECLARATION_LEAD.match(text, start).group(0)
        if unescaped(KEY_AND_VALUE.match(lead.lstrip(" \t\f")).group(1)) != "version":
            lead = lead[:len(lead) - len(lead.lstrip(" \t\f"))] + "version = "
        elif not lead.endswith(("=", ":", " ", "\t", "\f")):
            lead += " = "
        return text[:start] + lead + stored(version) + text[end:]


SOURCES = {adapter.name: adapter for adapter in (GradleProperties(), Tags())}
