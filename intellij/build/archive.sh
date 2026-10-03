#!/usr/bin/env bash
# Say where the signed archive is.
# Named here, not guessed by whoever drafts the release: the release attaches this one file,
# and a pattern of the draft's own that matched several would attach all of them silently.
# Kept out of action.yml so that it can be run in a test.
#
# Reads:  ARCHIVE_PATTERN GITHUB_OUTPUT
# Writes: archive  (to GITHUB_OUTPUT)
set -uo pipefail

# A pattern may hold a space, for an archive named after a project called "My Plugin", and is still one pattern.
# It is expanded with IFS empty, so that nothing splits it.
shopt -s nullglob
IFS=
# The glob expansion is the point here: the input is a file pattern.
# shellcheck disable=SC2206
matched=($ARCHIVE_PATTERN)
shopt -u nullglob
# A pattern with no glob character comes back as itself, whether the file exists or not.
# So the result is counted, and then checked to be a file, with a message of its own for each:
# "matched 1" for a file that is not there would read as though the count were wrong.
if (( ${#matched[@]} != 1 )); then
  echo "::error::${ARCHIVE_PATTERN} matched ${#matched[@]} file(s) here, and a release carries exactly one archive"
  exit 1
elif [[ ! -f ${matched[0]} ]]; then
  echo "::error::${ARCHIVE_PATTERN} names no file here, and a release carries exactly one archive"
  exit 1
fi
echo "archive=${matched[0]}" >> "$GITHUB_OUTPUT"
echo "signed archive: ${matched[0]}"
