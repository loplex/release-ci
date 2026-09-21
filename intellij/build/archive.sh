#!/usr/bin/env bash
# Say where the signed archive landed. Named here rather than guessed at by whoever drafts the release: exactly
# one archive is expected, and a pattern matching several would attach the wrong one without saying so. Kept
# out of action.yml so that it can be run in a test.
#
# Reads:  PATTERN GITHUB_OUTPUT
# Writes: archive  (to GITHUB_OUTPUT)
set -uo pipefail

shopt -s nullglob
matched=($PATTERN)
shopt -u nullglob
# A pattern with no glob character in it comes back as itself whether the file is there or not, so what came
# back is asked for as well as counted, and said apart: "matched 1" of a file that is not there would read as
# the count being at fault.
if [ "${#matched[@]}" -ne 1 ]; then
  echo "::error::${PATTERN} matched ${#matched[@]} file(s) here, and a release carries exactly one archive"
  exit 1
elif [ ! -f "${matched[0]}" ]; then
  echo "::error::${PATTERN} names no file here, and a release carries exactly one archive"
  exit 1
fi
echo "archive=${matched[0]}" >> "$GITHUB_OUTPUT"
echo "signed archive: ${matched[0]}"
