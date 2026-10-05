#!/usr/bin/env bash
# Push the release branch and draft the release from it, once the build has succeeded.
# The draft carries what will be published, the archive and the notes, so it is accepted with the file in hand.
#
# The tag is named but not created.
# GitHub creates it, at the target given here, only when the draft is published.
# A draft that is thrown away leaves no tag behind, so a tag always names a release someone accepted.
#
# Inputs come from the environment, because that is how a composite action hands them over.
# The script lives outside action.yml so that a test can run it against a repository.
#
# Reads:  PYTHON VERSION TAG BRANCH FILES GH_TOKEN
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../lib" && pwd)/main.py"
check_release=("$PYTHON" "$script")

# The notes, the files and the channel are checked here, before anything is pushed.
# A draft refused over one of them then leaves no branch behind.
# What GitHub answers comes after the push, because a draft has to point at a commit GitHub has.
# A draft GitHub refuses leaves the branch; running again replaces the branch and drafts the release from it.
notes_file=$(mktemp)
trap 'rm -f "$notes_file"' EXIT
"${check_release[@]}" notes "$VERSION" > "$notes_file" || exit 1

# A pattern that matches nothing is refused, not passed on as text: a release missing its archive is worse than a
# run that stopped.
# A plain path that names no file is refused too.
# nullglob acts only on a word with a glob character in it, and returns a plain path as it is, existing or not.
#
# One pattern or path per line; a blank line is skipped.
# A path may hold a space, such as an archive named after a project called "My Plugin", and is still one path.
# Each is expanded on its own, with IFS empty so that nothing splits it, and the one that fails is named.
patterns=()
while IFS= read -r line; do
  [[ $line == *[^[:space:]]* ]] && patterns+=("$line")
done <<< "$FILES"
attachments=()
shopt -s nullglob
IFS=
for pattern in "${patterns[@]}"; do
  # The glob expansion is the point here: the input is a file pattern.
  # shellcheck disable=SC2206
  matched=($pattern)
  if (( ${#matched[@]} == 0 )); then
    echo "::error::${pattern} matches nothing, so the release would go out without it"
    exit 1
  fi
  for file in "${matched[@]}"; do
    if [[ ! -f $file ]]; then
      echo "::error::${file} is no file here, so the release would go out without it"
      exit 1
    fi
  done
  attachments+=("${matched[@]}")
done
unset IFS
shopt -u nullglob

# A version with a pre-release suffix is marked as a pre-release, so GitHub does not show it as the latest release.
# The rule is check-release's `channel`, so this and whatever publishes the archive agree on what a suffix means.
channel=$("${check_release[@]}" channel "$VERSION") || exit 1
prerelease_arguments=()
if [[ $channel != default ]]; then
  prerelease_arguments=(--prerelease)
fi

# Forced, and the only forced push in the flow.
# The branch belongs to this release: a second run replaces the one left by a run whose draft was thrown away.
# Nothing else writes to it before the release is published.
# Once it is published, the tag stops the same version from being prepared again.
git push --force origin "HEAD:refs/heads/${BRANCH}" || exit 1

# A draft with this tag's name may be left from a run whose release was thrown away.
# GitHub would add a second one beside it, not replace it, so every such draft is deleted first.
# There can be several: one made by hand, or left by two runs that overlapped.
# `gh` finds one at a time, so the loop asks until none is left, at most 20 times.
# Only drafts are deleted.
# A published release of this version is not this run's to remove, and the version check would have refused to
# prepare it again.
for _ in {1..20}; do
  [[ $(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null) == true ]] || break
  echo "Replacing a draft named ${TAG}"
  gh release delete "$TAG" --yes || exit 1
done
if [[ $(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null) == true ]]; then
  echo "::error::drafts named ${TAG} are still there after 20 were removed"
  exit 1
fi

gh release create "$TAG" \
  --draft "${prerelease_arguments[@]}" \
  --target "$(git rev-parse HEAD)" \
  --title "$TAG" \
  --notes-file "$notes_file" \
  "${attachments[@]}" || exit 1
