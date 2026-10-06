#!/usr/bin/env bash
# Cut the release commit onto a branch of its own, named for the version:
# - [Unreleased] is closed into a section for the version being released;
# - that version is written back where the source declares one;
# - all of it is one commit.
# This is everything a release does to the repository before the build.
# Nothing is pushed: the build runs from this commit next.
# A failed build should leave neither a branch nor a draft behind, so the push waits for the build and goes with the
# draft.
#
# Inputs come from the environment, because that is how a composite action hands them over.
# The script lives outside action.yml so that a test can run it against a repository.
#
# Reads:  PYTHON VERSION_SOURCE TAG_PREFIX VERSION REPOSITORY_URL SKIP_UNREADABLE_RELEASES GITHUB_OUTPUT
# Writes: version, tag, branch  (to GITHUB_OUTPUT)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../lib" && pwd)/main.py"

check_release=("$PYTHON" "$script")
source_arguments=(--version-source "$VERSION_SOURCE")
if [[ -n $TAG_PREFIX ]]; then
  source_arguments+=(--tag-prefix "$TAG_PREFIX")
fi

# `true` passes over a release whose tag holds a CHANGELOG.md line lib/main.py does not read: a tag cannot be edited.
# Empty is `false`, because a dispatch input arrives empty on every other event.
case ${SKIP_UNREADABLE_RELEASES:-false} in
  true) changelog_arguments=(--skip-unreadable-releases) ;;
  false) changelog_arguments=() ;;
  *)
    echo "::error::skip-unreadable-releases is '$SKIP_UNREADABLE_RELEASES', which is neither true nor false"
    exit 1 ;;
esac

# All the checks run before anything is written.
# A release that fails them was then never cut, and there is nothing to undo.
failed=0
"${check_release[@]}" changelog "${source_arguments[@]}" "${changelog_arguments[@]}" || failed=1
"${check_release[@]}" ancestry "${source_arguments[@]}" || failed=1
version_arguments=()
if [[ -n $VERSION ]]; then
  version_arguments=(--version "$VERSION")
fi
version=$("${check_release[@]}" version "${source_arguments[@]}" "${version_arguments[@]}"); rc=$?
if (( rc != 0 || failed != 0 )); then
  echo "::error::the release rules said no, so nothing was cut"
  exit 1
fi
prefix=$("${check_release[@]}" prefix "${source_arguments[@]}"); rc=$?
if (( rc != 0 )); then
  exit 1
fi
# Not a setting: once the release is tagged, check-release names release/<version> first among the branches
# that hold its tag - the remote ones, or the local ones where no remote one does.
branch="release/${version}"

# What patchChangelog does in a Gradle plugin, done by the tool that later checks the result against the tag.
# The entries under [Unreleased] become the section for this version, dated today.
# Where a repository URL is given, the link definitions are written again to include it.
#
# This is the first write, and also the last check.
# An [Unreleased] with nothing to release is refused before the file is rewritten:
# nothing under it says something, and for a final release nothing in the pre-releases since the final release before
# it, in SemVer order, says something either.
# Such a release then leaves no branch and no output behind.
repository_url_arguments=()
if [[ -n $REPOSITORY_URL ]]; then
  repository_url_arguments=(--repository-url "$REPOSITORY_URL")
fi
"${check_release[@]}" close-changelog "$version" "${source_arguments[@]}" "${repository_url_arguments[@]}" || exit 1

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

# Created here, not switched to, so that a branch left by an earlier attempt is replaced, not continued.
# A second attempt at the same version starts again from the commit checked out.
git switch -C "$branch" || exit 1

# Written by the tool that also reads that line, not by a pattern here.
# A source that declares no version has nothing to write and exits with 3.
# The release is still the version it was asked to be.
# Any other failure stops here, before a commit names a release the build would not make.
"${check_release[@]}" set-version "$version" --version-source "$VERSION_SOURCE" >/dev/null; rc=$?
if (( rc == 3 )); then
  echo "${VERSION_SOURCE} declares no version, so none was written; ${prefix}${version} is what the tag will say"
elif (( rc != 0 )); then
  echo "::error::${VERSION_SOURCE} could not be given ${version}, so no release commit was made"
  exit 1
fi

git commit -qam "chore(release): ${version}" || exit 1

# Written only once the commit is made.
# A failed step then leaves nothing that a later step could read as a release that was cut.
{
  echo "version=${version}"
  echo "tag=${prefix}${version}"
  echo "branch=${branch}"
} >> "$GITHUB_OUTPUT"

echo "cut ${version} onto ${branch}, to be built from here and tagged ${prefix}${version} once published"
