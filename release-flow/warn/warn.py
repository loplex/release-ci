#!/usr/bin/env python3
"""Say on a published release that publishing it somewhere else did not complete, or take that back once it has.

Someone with the release's files in hand looks at the release, not at workflow runs.
So a failed publish is reported where they will see it: a warning at the start of the notes, linking the run.
The next run whose publish completes takes that warning off again, and only the warning.
The rest of the notes belongs to the release.

The warning sits between two HTML comments, which GitHub keeps in the notes as written and does not show.
It is looked for only where this script puts it: at the very start of the notes.
A line at the start of the notes, in its first column, cannot be inside a code block, a list or a quote.
So a marker there is this action's, whatever the words between the markers, and nothing has to be parsed.
A warning written by another version of this action is taken off all the same.

A marker on a line of its own anywhere else is not guessed at.
It may be an example shown as code, or this warning after someone wrote above it.
Either way the run stops and the notes are left as they are.
This runs after the release and everything before it are done, so stopping undoes nothing.

Inputs come from the environment, because that is how a composite action hands them over.
The script lives outside action.yml so that a test can run it against a stub `gh`.

Reads: OUTCOME TAG TO RUN
       GH_TOKEN GH_REPO, read by `gh`, not by this script
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


# A line and its line end, with the line ends CommonMark knows.
# str.splitlines would also end a line at a form feed or a Unicode line separator, which Markdown reads as text.
LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")


def without_warning(notes):
    """The notes without the warning at their start, and without the blank line after it.

    Line ends are kept: GitHub stores notes as they were sent, CRLF included.
    Taking the warning off gives back the notes as they were before it, and a warning put on uses their line ends.
    """
    lines = LINE.findall(notes)
    # A line holding only a marker counts whatever its indentation and whatever it stands in.
    # Unless it is the warning's own, this cannot tell it from the warning's.
    # Only spaces and tabs are stripped, because CommonMark indents with nothing else.
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
    """The notes with the warning at their start, in place of any warning they had.

    A run that fails again, or a later version of this action, says it once, in its current wording.
    """
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

# The outcome is a step's, handed over as `steps.<id>.outcome`.
# An id that names no step hands over nothing.
# That is refused, not read as a failure: otherwise every release would be said to have failed to publish.
if not OUTCOME:
    fail("outcome is empty: does steps.<id> name the step that publishes?")
# `cancelled` is refused with the rest.
# A step's outcome is `cancelled` only where the run was cancelled, and then a step under `!cancelled()` does not run.
# A step that runs out of its timeout-minutes has failed.
if OUTCOME not in ("success", "failure", "skipped"):
    fail(f"outcome is '{OUTCOME}', where success, failure or skipped was expected")
if not TAG:
    fail("tag names no release")
if not TO.strip() or "\n" in TO or "\r" in TO:
    fail("to has to say, on one line, what the release is published to")

# Read as JSON, not through `--jq`: jq adds a line end to what it prints, and the notes may not end with one.
viewed = subprocess.run(["gh", "release", "view", TAG, "--json", "body"], capture_output=True, text=True)
if viewed.returncode != 0:
    print(viewed.stderr, file=sys.stderr, end="")
    fail(f"the notes of {TAG} could not be read")
notes = json.loads(viewed.stdout)["body"] or ""

# `skipped` warns like `failure`: a publish step that did not run is a publish that did not complete.
# It was skipped because a step before it failed, such as the one taking the archive off the release.
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
