#!/usr/bin/env bash
# Push the release branch and draft the release from it, once the build has succeeded. The draft carries what
# will be published - the archive, the notes - so that accepting it is a decision taken with the file in hand.
#
# The tag is named but not created: GitHub creates it, at the target given here, only when the draft is
# published. A draft that is thrown away leaves no tag behind, and a tag always names a release someone
# accepted.
#
# Driven by environment rather than by arguments, because that is how a composite action hands its inputs
# over - and kept out of action.yml so that it can be run against a repository in a test.
#
# Reads:  SOURCE TAG_PREFIX VERSION TAG BRANCH FILES GH_TOKEN
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../check-release" && pwd)/check-release.py"
prefix=()
if [ "$TAG_PREFIX" = '^none' ]; then
  prefix=(--tag-prefix '')
elif [ -n "$TAG_PREFIX" ]; then
  prefix=(--tag-prefix "$TAG_PREFIX")
fi
rules=(python3 "$script" --source "$SOURCE" "${prefix[@]}")

# What can be answered here - the notes, the files, the channel - is asked before anything is pushed, so that
# a draft refused over one of them leaves no branch behind either. What GitHub answers comes after the push,
# because a draft has to point at a commit GitHub has: a draft it refuses leaves the branch standing, and
# running again replaces both.
notes=$(mktemp)
trap 'rm -f "$notes"' EXIT
"${rules[@]}" section "$VERSION" > "$notes" || exit 1

# A pattern that matches nothing is refused rather than handed on as its own text: a release missing its
# archive is worse than a run that stopped. So is a path given outright that names no file - nullglob acts only
# on a word carrying a glob character, and hands a plain path back as itself whether it exists or not.
#
# Split with globbing off and expanded one pattern at a time: splitting an unquoted $FILES would expand it in
# the same breath, and a pattern matching nothing would vanish from the list before it could be refused.
set -f
patterns=($FILES)
set +f
attached=()
shopt -s nullglob
for pattern in "${patterns[@]}"; do
  matched=($pattern)
  if [ "${#matched[@]}" -eq 0 ]; then
    echo "::error::${pattern} matches nothing, so the release would go out without it"
    exit 1
  fi
  for file in "${matched[@]}"; do
    if [ ! -f "$file" ]; then
      echo "::error::${file} is no file here, so the release would go out without it"
      exit 1
    fi
  done
  attached+=("${matched[@]}")
done
shopt -u nullglob

# A version with a pre-release suffix is marked as one, so that GitHub does not hold it out as the latest
# release. The channel rule is check-release's, so that this and whatever publishes the archive agree about
# what a suffix means.
channel=$("${rules[@]}" channel "$VERSION") || exit 1
marked=()
if [ "$channel" != default ]; then
  marked=(--prerelease)
fi

# Forced, and only here in the flow: the branch is the release's own, and one standing from a run whose draft
# was thrown away is what a second run replaces. Nothing else writes to it before the release is published,
# and once it is, the tag stops the same version from being prepared again.
git push --force origin "HEAD:refs/heads/${BRANCH}" || exit 1

# A draft with this tag's name may be standing from a run whose release was thrown away. GitHub would put a
# second one beside it rather than replace it, so it goes first - and so does every one of them, a run that
# stopped before this line having left one more beside it. `gh` finds one at a time, so they are asked for
# until none is left, a bounded number of times rather than for as long as GitHub keeps answering. Only a
# draft: a published release of this version is not this run's to remove, and the version check would have
# refused to prepare it again.
for _ in $(seq 1 20); do
  [ "$(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null)" = true ] || break
  echo "Replacing the draft ${TAG} left by an earlier run"
  gh release delete "$TAG" --yes || exit 1
done
if [ "$(gh release view "$TAG" --json isDraft --jq .isDraft 2>/dev/null)" = true ]; then
  echo "::error::drafts named ${TAG} are still there after 20 were removed"
  exit 1
fi

gh release create "$TAG" \
  --draft "${marked[@]}" \
  --target "$(git rev-parse HEAD)" \
  --title "$TAG" \
  --notes-file "$notes" \
  "${attached[@]}" || exit 1
