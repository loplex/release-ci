#!/usr/bin/env bash
# Render the release's change notes, the section of CHANGELOG.md for its version, as HTML for the build.
# cmarkgfm renders them, installed from PyPI with the hashes lib/requirements.txt pins.
# It goes into a directory of its own under RUNNER_TEMP, so the calling job's Python environment is left as it was.
# Kept out of action.yml so that it can be run in a test.
#
# A relative link in the notes is made absolute, read at the release's tag in the repository, as GitHub reads it on
# the published release's page; an anchor alone leads into CHANGELOG.md instead.
# The tag exists only once the draft is published, so the same notes are also written as a page whose links are
# read at the commit checked out, to be looked at before then.
#
# Reads:  PYTHON RUNNER_TEMP GITHUB_OUTPUT REPOSITORY_URL TAG
# Writes: html     (to GITHUB_OUTPUT) the notes, their links at the tag
#         preview  (to GITHUB_OUTPUT) the path of the page, change-notes.html
set -euo pipefail

if [[ -z ${TAG:-} ]]; then
  echo "::error::intellij/build needs its tag input with change-notes: true:" \
       "a relative link in the notes is made absolute at the release's tag"
  exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
packages="$RUNNER_TEMP/release-ci-change-notes"
"$PYTHON" -m pip install --quiet --disable-pip-version-check --require-hashes --target "$packages" \
  -r "$here/../../lib/requirements.txt"
# -X utf8 writes the notes as UTF-8 whatever the locale.
html=$(PYTHONPATH="$packages" "$PYTHON" -X utf8 "$here/change-notes.py" "$REPOSITORY_URL" "$TAG")
preview="$RUNNER_TEMP/release-ci-change-notes-preview/change-notes.html"
mkdir -p "$(dirname "$preview")"
PYTHONPATH="$packages" "$PYTHON" -X utf8 "$here/change-notes.py" "$REPOSITORY_URL" "$(git rev-parse HEAD)" --page \
  > "$preview"

# A delimiter nobody can have written into the notes, as GitHub advises for an output of several lines.
delimiter="change-notes-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
{ echo "html<<$delimiter"; printf '%s\n' "$html"; echo "$delimiter"; echo "preview=$preview"; } >> "$GITHUB_OUTPUT"

# Shown in the log with workflow commands stopped: a line of the notes starting with `::` is not run as one.
echo "::stop-commands::$delimiter"
printf '%s\n' "$html"
echo "::$delimiter::"
