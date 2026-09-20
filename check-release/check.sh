#!/usr/bin/env bash
# Run the checks the action was asked for, and say what `version` answered. Driven by environment rather than
# by arguments, because that is how a composite action hands its inputs over - and kept out of action.yml so
# that it can be run against a repository in a test.
#
# Reads:  SOURCE TAG_PREFIX CHECKS VERSION GITHUB_OUTPUT
# Writes: version, channel  (to GITHUB_OUTPUT, where `version` ran and said yes)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-release.py"

# Passed on only where the caller gave one, so that a source declaring its own prefix is the one
# answering. An empty input is "not given" and not "the empty prefix": GitHub cannot tell the two
# apart, and of the two readings this is the one whose mistake is loud. `^none` is how the other
# one is said, git refusing `^` in a ref name and so never leaving it a real prefix's spelling.
prefix=()
if [ "$TAG_PREFIX" = '^none' ]; then
  prefix=(--tag-prefix '')
elif [ -n "$TAG_PREFIX" ]; then
  prefix=(--tag-prefix "$TAG_PREFIX")
fi

# Nothing asked for is refused for the same reason a name that is no check is: a run that compared nothing
# and passed reads exactly like one that compared everything.
if [ -z "${CHECKS//[[:space:]]/}" ]; then
  echo "::error::no check was asked for: name some of version, changelog and ancestry"
  exit 1
fi

for check in $CHECKS; do
  case "$check" in
    version|changelog|ancestry) ;;
    *)
      echo "::error::'$check' is not a check this action runs: version, changelog and ancestry are"
      exit 1 ;;
  esac
done

failed=0
for check in $CHECKS; do
  if [ "$check" = version ] && [ -n "$VERSION" ]; then
    out=$(python3 "$script" --source "$SOURCE" "${prefix[@]}" version --version "$VERSION" 2>&1)
    rc=$?
  else
    out=$(python3 "$script" --source "$SOURCE" "${prefix[@]}" "$check" 2>&1)
    rc=$?
  fi
  printf '%s\n' "$out"

  if [ "$rc" -ne 0 ]; then
    echo "::error::check-release $check said no"
    failed=1
  elif [ "$check" = version ]; then
    released=$(printf '%s' "$out" | tail -1)
    printf 'version=%s\n' "$released" >> "$GITHUB_OUTPUT"
    channel=$(python3 "$script" --source "$SOURCE" "${prefix[@]}" channel "$released" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
      printf '%s\n' "$channel"
      echo "::error::check-release channel said no"
      failed=1
    else
      printf 'channel=%s\n' "$channel" >> "$GITHUB_OUTPUT"
    fi
  fi
done
exit "$failed"
