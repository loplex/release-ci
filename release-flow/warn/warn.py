#!/usr/bin/env python3
"""Say on a published release that publishing it somewhere else did not complete, or take that back once it has.

Someone who has the release's files in hand looks at the release, not through the runs of a workflow, so a
publish that went red is said where they will see it: a warning at the start of the notes, linking the run. The
next run whose publish completes takes that warning off again, and only it - the notes around it are the
release's own.

The warning sits between two HTML comments, which GitHub keeps in the notes as they were written and does not
show, and it is looked for only where this puts it: at the very start of the notes. A line that starts the
notes from its first column cannot stand inside a code block, a list or a quote, so nothing has to be parsed to
know that a marker there is this action's, whatever the words between the markers - a warning written by
another version of this action is still the one taken off. A marker on a line of its own anywhere else is not
guessed at: it may be an example the notes show as code, or this warning after someone wrote above it, and
either way the run stops and the notes are left as they are. It runs after the release and everything before
it are done, so stopping undoes nothing.

Driven by environment rather than by arguments, because that is how a composite action hands its inputs over -
and kept out of action.yml so that it can be run against a stub `gh` in a test.

Reads: OUTCOME TAG TO RUN
       GH_TOKEN GH_REPO, by `gh` rather than by anything here
"""

import json
import os
import re
import subprocess
import sys
import tempfile

START = "<!-- release-flow/warn -->"
END = "<!-- /release-flow/warn -->"


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


# A line and its end, the ends being those CommonMark knows: str.splitlines would also end a line at a form
# feed or a Unicode line separator, which Markdown reads as text.
LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")


def without_warning(notes):
    """The notes with the warning at their start taken off, and the blank line that follows it.

    Line ends are kept as they were: GitHub keeps notes as they were sent, CRLF included, so taking the warning
    off gives back the notes as they stood before it, and one put on is written in their line ends.
    """
    lines = LINE.findall(notes)
    # Whatever its indentation, and whatever it stands in: a line that holds a marker alone, and is not the
    # warning's own, is one this cannot tell from the warning's. Spaces and tabs are all that is taken off, as
    # CommonMark indents with nothing else.
    markers = [at for at, line in enumerate(lines) if line.strip(" \t\r\n") in (START, END)]
    if not markers:
        return notes
    if markers[0] != 0:
        fail(f"the notes of {TAG} hold a marker of this warning on line {markers[0] + 1}, where this action does "
             f"not put one; they are left as they are, for a warning there to be taken off by hand")
    if lines[0].rstrip("\r\n") != START:
        fail(f"the notes of {TAG} open with a marker of this warning that is not as this action writes it - "
             f"indented, or with spaces after it; they are left as they are, for it to be taken off by hand")
    end = markers[1] if len(markers) > 1 else None
    if end is None or lines[end].rstrip("\r\n") != END or not all(line.startswith(">") for line in lines[1:end]):
        fail(f"the notes of {TAG} open with a warning that does not read as this action's - not closed, or "
             f"holding more than quoted lines; they are left as they are, for it to be taken off by hand")
    if len(markers) > 2:
        fail(f"the notes of {TAG} hold a marker of this warning on line {markers[2] + 1} as well, below the one "
             f"at their start; they are left as they are, for a warning there to be taken off by hand")
    rest = end + 1
    if rest < len(lines) and not lines[rest].strip(" \t\r\n"):
        rest += 1
    return "".join(lines[rest:])


def with_warning(notes):
    """The notes with the warning at their start, in place of the one they carried: a run that fails again, or
    a later version of this action, says it once and says it the way it says it now."""
    rest = without_warning(notes)
    newline = "\r\n" if "\r\n" in notes else "\r" if "\r" in notes else "\n"
    block = [
        START,
        "> [!WARNING]",
        # One sentence to a line: GitHub shows a line end in release notes as a line break.
        f"> Publishing this release to {TO} did not complete: see [the run]({RUN}).",
        f"> What {TO} serves for this version may not be what this release carries.",
        END,
    ]
    written = "".join(line + newline for line in block)
    return written + newline + rest if rest else written


OUTCOME, TAG, TO, RUN = (os.environ.get(name, "") for name in ("OUTCOME", "TAG", "TO", "RUN"))

# The outcome is a step's, handed over as `steps.<id>.outcome`. An id that names no step hands over nothing,
# which is refused rather than read as a failure: every release would be said to have failed to publish.
if not OUTCOME:
    fail("outcome is empty: does steps.<id> name the step that publishes?")
# `cancelled` is refused with the rest: a step's outcome is that only where the run was cancelled, and then a step
# under `!cancelled()` does not run. A step that runs out of its timeout-minutes has failed.
if OUTCOME not in ("success", "failure", "skipped"):
    fail(f"outcome is '{OUTCOME}', where success, failure or skipped was expected")
if not TAG:
    fail("tag names no release")
if not TO.strip() or "\n" in TO or "\r" in TO:
    fail("to has to say, on one line, what the release is published to")

# Read as JSON rather than through `--jq`: jq ends what it prints with a line end, which the notes need not.
viewed = subprocess.run(["gh", "release", "view", TAG, "--json", "body"], capture_output=True, text=True)
if viewed.returncode != 0:
    print(viewed.stderr, file=sys.stderr, end="")
    fail(f"the notes of {TAG} could not be read")
notes = json.loads(viewed.stdout)["body"] or ""

# `skipped` warns as `failure` does: the publish step not running is a publish that did not complete, the step
# before it having failed - taking the archive off the release, say.
wanted = without_warning(notes) if OUTCOME == "success" else with_warning(notes)
if wanted == notes:
    print(f"The notes of {TAG} already say what this run would; they are left as they are.")
    sys.exit(0)

with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".md", delete=False) as written:
    written.write(wanted)
try:
    edited = subprocess.run(["gh", "release", "edit", TAG, "--notes-file", written.name])
finally:
    os.unlink(written.name)
if edited.returncode != 0:
    fail(f"the notes of {TAG} could not be written")
if OUTCOME == "success":
    print(f"The warning is off {TAG}: publishing it has completed.")
else:
    print(f"{TAG} now says that publishing it to {TO} did not complete.")
