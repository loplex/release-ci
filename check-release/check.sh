#!/usr/bin/env bash
# Run the checks the action was asked for, and output what `version` answered.
# It reads environment variables, not arguments, because that is how a composite action passes its inputs.
# It is a file of its own, not part of action.yml, so that a test can run it against a repository.
#
# Reads:  VERSION_SOURCE TAG_PREFIX CHECKS VERSION GITHUB_OUTPUT
# Writes: version, channel  (to GITHUB_OUTPUT, where `version` ran and said yes)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-release.py"

# The prefix is passed on only where the caller gave one, so that a source declaring its own prefix answers.
# An empty input means "not given", not "the empty prefix":
# GitHub passes a missing input as an empty string too, so the two cannot be told apart.
# Read as "not given", a mistake fails loudly; read as "no prefix", it would pass having found no release.
# `^none` says "no prefix", and check-release.py reads it so.
source_arguments=(--version-source "$VERSION_SOURCE")
if [[ -n $TAG_PREFIX ]]; then
  source_arguments+=(--tag-prefix "$TAG_PREFIX")
fi

# Split at spaces and newlines, without glob expansion.
# `*` is then a name that is no check, not the files in the workspace.
read -rd '' -a check_names <<< "$CHECKS"

# No check at all is refused, like a name that is no check:
# a run that compared nothing and passed looks exactly like one that compared everything.
if (( ${#check_names[@]} == 0 )); then
  echo "::error::no check was asked for: name some of version, changelog and ancestry"
  exit 1
fi

for check in "${check_names[@]}"; do
  case "$check" in
    version|changelog|ancestry) ;;
    *)
      echo "::error::'$check' is not a check this action runs: version, changelog and ancestry are"
      exit 1 ;;
  esac
done

failed=0
for check in "${check_names[@]}"; do
  if [[ $check == version && -n $VERSION ]]; then
    out=$(python3 "$script" version "${source_arguments[@]}" --version "$VERSION" 2>&1)
    rc=$?
  else
    out=$(python3 "$script" "$check" "${source_arguments[@]}" 2>&1)
    rc=$?
  fi
  printf '%s\n' "$out"

  if (( rc != 0 )); then
    echo "::error::check-release $check said no"
    failed=1
  elif [[ $check == version ]]; then
    candidate=$(printf '%s' "$out" | tail -1)
    printf 'version=%s\n' "$candidate" >> "$GITHUB_OUTPUT"
    channel=$(python3 "$script" channel "$candidate")
    rc=$?
    if (( rc != 0 )); then
      echo "::error::check-release channel said no"
      failed=1
    else
      printf 'channel=%s\n' "$channel" >> "$GITHUB_OUTPUT"
    fi
  fi
done
exit "$failed"
