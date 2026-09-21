#!/usr/bin/env bash
# Cut the release commit onto a branch of its own: the version the source declares, minus its marker, written
# back as the version being released; [Unreleased] closed into a section for it; one commit, on a branch
# named for the version. Everything a release does to the repository before anything is built, and nothing
# that needs a build. Nothing is pushed either: the build runs from this commit next, and a build that fails
# should leave neither a branch nor a draft behind - which is why pushing waits for the build to have
# succeeded, and goes with the draft.
#
# Driven by environment rather than by arguments, because that is how a composite action hands its inputs
# over - and kept out of action.yml so that it can be run against a repository in a test.
#
# Reads:  SOURCE TAG_PREFIX VERSION BRANCH_PREFIX REPOSITORY_URL GITHUB_OUTPUT
# Writes: version, tag, branch  (to GITHUB_OUTPUT)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../check-release" && pwd)/check-release.py"

prefix=()
if [ "$TAG_PREFIX" = '^none' ]; then
  prefix=(--tag-prefix '')
elif [ -n "$TAG_PREFIX" ]; then
  prefix=(--tag-prefix "$TAG_PREFIX")
fi
rules=(python3 "$script" --source "$SOURCE" "${prefix[@]}")

# The rules first, and all of them, before anything is written: a release that fails them is one that was
# never cut, not one that has to be undone.
failed=0
for check in changelog ancestry; do
  "${rules[@]}" "$check" || failed=1
done
asked=()
if [ -n "$VERSION" ]; then
  asked=(--version "$VERSION")
fi
version=$("${rules[@]}" version "${asked[@]}"); rc=$?
if [ "$rc" -ne 0 ] || [ "$failed" -ne 0 ]; then
  echo "::error::the release rules said no, so nothing was cut"
  exit 1
fi
tag_prefix=$("${rules[@]}" prefix); rc=$?
if [ "$rc" -ne 0 ]; then
  exit 1
fi
branch="${BRANCH_PREFIX}${version}"

# What patchChangelog does in a Gradle plugin, done by the same file that later checks the result against the
# tag: the entries under [Unreleased] become the section for this version, dated today, and where the
# repository is given the link definitions are written afresh to include it.
#
# First of the writes, and the last of the rules with it: an [Unreleased] with nothing under it is refused
# before the file is rewritten, so a release with nothing to say about itself leaves no branch and no output
# behind either.
closing=(close-changelog "$version")
if [ -n "$REPOSITORY_URL" ]; then
  closing+=(--repository-url "$REPOSITORY_URL")
fi
"${rules[@]}" "${closing[@]}" || exit 1

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

# Created from here rather than switched to, so that a branch left behind by an earlier attempt is replaced
# rather than continued: a second attempt at the same version starts from the default branch again.
git switch -C "$branch" || exit 1

# Written by the tool that also reads that line, rather than by a pattern here. A source that declares no
# version has nothing to write and says so with a status of its own, 3; the release is still the version it
# was asked to be. Any other failure stops here, before a commit names a release the build would not make.
"${rules[@]}" set-version "$version" >/dev/null; rc=$?
if [ "$rc" -eq 3 ]; then
  echo "${SOURCE} declares no version, so none was written; ${version} is what the tag will say"
elif [ "$rc" -ne 0 ]; then
  echo "::error::${SOURCE} could not be given ${version}, so no release commit was made"
  exit 1
fi

git commit -qam "chore(release): ${version}" || exit 1

# Written once the commit is made, so that a step which failed leaves nothing for a later one to read as
# though the release had been cut.
{
  echo "version=${version}"
  echo "tag=${tag_prefix}${version}"
  echo "branch=${branch}"
} >> "$GITHUB_OUTPUT"

echo "cut ${version} onto ${branch}, to be built from here and tagged ${tag_prefix}${version} once published"
