"""Where the version a release is asked to be comes from, and where the next one is recorded once it is one:
one adapter per kind of repository, so that the rules in check-release.py know no source by name.

An adapter is a plain object over text. check-release.py reads and writes the file an adapter names, and the
adapter says what that text declares and what it becomes - so that each can be exercised without a repository,
and so that finding the file, and refusing where it is missing, is written once rather than once per format.

Two kinds, and they differ in more than a filename. A source that declares a version names the next one in a
file between releases, marked as being worked on where its ecosystem has a marker for that, so a release reads
the version off that file and writes the following one back. A source that declares nothing is handed the
version when a release is asked for, or takes the one after the highest release there is where none is handed
in, and records nothing afterwards, because there is no file to record it in.

What an adapter answers: `name`, the one `--source` gives it; `declares_a_version`; `marker`, the ending a
version carries while it is being worked on, hyphen and all - `-SNAPSHOT` for gradle.properties - or empty
where there is no such state; and `file`, the file it declares a version in, or None where it declares none.
One that declares a version also says in `holds` what that file is looked in for - the refusal where the file
is missing says so - and in `encoding` how the file's bytes are read and written back, and answers `version()`
and `tag_prefix()` over its text, and `with_version()` with what that text becomes. The tag prefix goes with
the file: check-release.py asks tag_prefix() of every source naming one unless `--tag-prefix` is given, and a
source naming none has its prefix handed in.

Another source - package.json, pyproject.toml, Cargo.toml - is another adapter here, its file carrying the tag
prefix beside the version, filed in SOURCES under the name `--source` gives it. Nothing in check-release.py
changes for it unless it marks a version being worked on other than with a `-SNAPSHOT` suffix, the one
being_worked_on knows; test_sources.py holds it to what every adapter has to answer, and says so if it does. A
plain VERSION file has no room for a prefix, which check-release.py asks of every source naming a file unless
`--tag-prefix` is given, so it takes more than an adapter.
"""

import re

# gradle.properties is a Java properties file, and Gradle reads it with java.util.Properties, so it is read here
# the way that class's load() documents: the version and the prefix a release takes are then the ones the build
# sees. A natural line ends at `\n`, `\r` or `\r\n`. One ending in an odd number of backslashes goes on in the next,
# whose leading white space is dropped, and `#` or `!` opens a comment only where a logical line starts. The key
# runs to the first `=`, `:` or white space that is not escaped; an escape is `\t`, `\n`, `\r`, `\f`, `\uXXXX`, or
# a backslash in front of any other character, which then stands for itself.
NATURAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
KEY_AND_VALUE = re.compile(r"((?:\\.|[^\\=: \t\f])*)[ \t\f]*[=:]?[ \t\f]*(.*)", re.DOTALL)
ESCAPE = re.compile(r"\\(u[0-9A-Fa-f]{4}|u|.)", re.DOTALL)


def logical_lines(text: str) -> list[tuple[int, int, str]]:
    """Every logical line of a properties file that declares something, as (start, end, line): where its first
    natural line starts, where its last one ends, and the line with its continuations joined."""
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
    """A key or a value with its escapes read. A `\\u` not followed by four hex digits is refused, as Properties
    refuses it, and two that make a UTF-16 surrogate pair are one character, as they are in the Java string
    Properties reads them into."""
    def one(escape):
        code = escape.group(1)
        if code == "u":
            raise SystemExit(f"gradle.properties has a malformed \\uxxxx escape in '{text}', which Gradle refuses "
                             "as well")
        escapes = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}
        return chr(int(code[1:], 16)) if len(code) == 5 else escapes.get(code, code)
    return ESCAPE.sub(one, text).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def stored(value: str) -> str:
    """A value written the way Properties.store(OutputStream) writes one, so that the file reads it back as it was given
    and no character of text fails to encode: a backslash doubled, a tab, a line break or a form feed as its escape, a
    leading space and `=`, `:`, `#`, `!` behind a backslash, and every other character below a space or above `~` as
    `\\uXXXX`, a character outside the first 65536 as the two of its UTF-16 pair. A lone surrogate is no character of
    text: it is what Python makes of a command-line byte its filesystem encoding cannot decode, and the UTF-16
    encoding below refuses it before the file is opened for writing. Properties.store(OutputStream) would write it as
    `\\uXXXX` instead."""
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
    """A repository whose version lives only in its tags. It declares no version and no tag prefix: the prefix is
    handed in, the version is handed in or taken as the one after the highest release, and there is no version
    being worked on for a marker to sit on."""

    name = "tags"
    declares_a_version = False
    file = None
    marker = ""


class GradleProperties:
    """gradle.properties, the Java properties file a project declares its version and its tag prefix in.

    `-SNAPSHOT` is Gradle's and Maven's spelling of a version being worked on, which is the one suffix never
    released to any channel: check-release refuses a candidate still carrying it, and leaves a tag carrying it
    out of what counts as released."""

    name = "gradle.properties"
    declares_a_version = True
    file = "gradle.properties"
    holds = "the version and tagPrefix"
    # Gradle hands the file to Properties.load() as bytes, and that takes each byte for one Latin-1 character rather
    # than decoding UTF-8. Read and written the same way, no byte in the file fails to decode, and a comment or any
    # value but the version's, saved in any encoding, goes back in the bytes it was read from.
    encoding = "iso-8859-1"
    marker = "-SNAPSHOT"

    # What a release puts back in front of the version it writes: the indentation, the key and the separator
    # exactly as the first line of the declaration has them. Gradle allows space around the separator and in front
    # of the key, and projects write it every way, so it is put back rather than chosen here: turning one spelling
    # into the other would show up in the diff as a change nobody made, and so would an indented declaration moved
    # to the margin. Where a continuation splits the key itself, that first line holds only part of it, and the
    # declaration is written again as `version = ` after that line's indentation.
    DECLARATION_LEAD = re.compile(r"[ \t\f]*(?:\\[^\r\n]|[^\\=: \t\f\r\n])*[ \t\f]*[=:]?[ \t\f]*")

    def properties(self, text: str) -> dict[str, str]:
        """Every key the file declares, with its value, read the way Gradle reads them (see NATURAL_LINE):
        `version = 0.2.0`, `version=0.2.0` and `version: 0.2.0` alike, a line continued onto the next, an escape.
        A key declared twice keeps its last value, as it does for Gradle."""
        found = {}
        for _, _, line in logical_lines(text):
            key, value = KEY_AND_VALUE.match(line).groups()
            found[unescaped(key)] = unescaped(value)
        return found

    def version(self, text: str) -> str:
        """The version the file names, marker and all: what a release is asked to be once the marker is off."""
        declared = self.properties(text).get("version")
        if declared is None:
            raise SystemExit("gradle.properties names no version")
        return declared

    def tag_prefix(self, text: str) -> str:
        """What release tags carry in front of the version. Declared empty is a prefix too - a project that tags
        bare versions says so - and left out is refused, the wrong guess passing every check."""
        prefix = self.properties(text).get("tagPrefix")
        if prefix is None:
            raise SystemExit("gradle.properties does not say, in tagPrefix, what release tags are called")
        return prefix

    def with_version(self, text: str, version: str) -> str:
        """The file with the version's declaration rewritten and everything else left alone.

        A replacement built by hand, the version written as data: `&` and `\\1` in it are characters, not
        instructions, and the version is escaped as Properties.store(OutputStream) escapes a value (see
        stored()), so that the file reads it back as it was given. A file declaring the version more than once
        is refused rather than rewritten at one of them. The reader takes the last declaration, as Gradle
        does, so rewriting any other leaves the version the build sees as it was - and rewriting the last one
        leaves a stale line above it for the next reader to trust.
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
