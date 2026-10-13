#!/usr/bin/env bash
# Run the checks the action was asked for, and output what `version` answered.
# It reads environment variables, not arguments, because that is how a composite action passes its inputs.
# It is a file of its own, not part of action.yml, so that a test can run it against a repository.
#
# Reads:  PYTHON VERSION_SOURCE TAG_PREFIX CHECKS VERSION SNAPSHOT_SUFFIX SKIP_UNREADABLE_RELEASES DEFAULT_BRANCH
#         GITHUB_OUTPUT
# Writes: version, channel  (to GITHUB_OUTPUT, where `version` ran and said yes)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/main.py"

# The prefix is passed on only where the caller gave one, so that a source declaring its own prefix answers.
# An empty input means "not given", not "the empty prefix":
# GitHub passes a missing input as an empty string too, so the two cannot be told apart.
# Read as "not given", a mistake fails loudly; read as "no prefix", it would pass having found no release.
# `^none` says "no prefix", and lib/main.py reads it so.
source_arguments=(--version-source "$VERSION_SOURCE")
if [[ -n $TAG_PREFIX ]]; then
  source_arguments+=(--tag-prefix "$TAG_PREFIX")
fi
# The branch releases land on, so that a release landed after the commit checked only warns.
# Empty where the event names no repository: such a release then fails, as a rewrite would.
if [[ -n ${DEFAULT_BRANCH:-} ]]; then
  source_arguments+=(--default-branch "$DEFAULT_BRANCH")
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

# `true` passes over a release whose tag holds a CHANGELOG.md line lib/main.py does not read: a tag cannot be edited.
# Empty is `false`, because a dispatch input arrives empty on every other event.
case ${SKIP_UNREADABLE_RELEASES:-false} in
  true) changelog_arguments=(--skip-unreadable-releases) ;;
  false) changelog_arguments=() ;;
  *)
    echo "::error::skip-unreadable-releases is '$SKIP_UNREADABLE_RELEASES', which is neither true nor false"
    exit 1 ;;
esac

# Passed even where empty: lib/main.py refuses it empty under a source that declares a version, and takes the suffix
# the nearest recorded release names, using this only where that release names none or no release records anything.
# Joined by `=`, because a suffix starts with a hyphen and would be read as an option of its own.
version_arguments=("--snapshot-suffix=${SNAPSHOT_SUFFIX:-}")
if [[ -n $VERSION ]]; then
  version_arguments+=(--version "$VERSION")
fi

failed=0
for check in "${check_names[@]}"; do
  if [[ $check == version ]]; then
    out=$("$PYTHON" "$script" version "${source_arguments[@]}" "${version_arguments[@]}" 2>&1)
    rc=$?
  elif [[ $check == changelog ]]; then
    out=$("$PYTHON" "$script" changelog "${source_arguments[@]}" "${changelog_arguments[@]}" 2>&1)
    rc=$?
  else
    out=$("$PYTHON" "$script" "$check" "${source_arguments[@]}" 2>&1)
    rc=$?
  fi
  printf '%s\n' "$out"

  # 4: nothing wrong but a published release that has yet to land here, which merge-back or its pull request carries
  # back, or one that landed after this commit.
  # A commit pushed in that window cannot be changed to pass, and does not have to be.
  if (( rc == 4 )); then
    echo "::warning::check-release $check found a published release that has yet to land here, or landed after this" \
      "commit"
  elif (( rc != 0 )); then
    echo "::error::check-release $check said no"
    failed=1
  elif [[ $check == version ]]; then
    candidate=$(printf '%s' "$out" | tail -1)
    printf 'version=%s\n' "$candidate" >> "$GITHUB_OUTPUT"
    channel=$("$PYTHON" "$script" channel "$candidate")
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
