#!/usr/bin/env bash
# Carry a published release back onto the default branch.
# Inputs come from the environment, because that is how a composite action hands them over.
# The script lives outside action.yml so that a test can run it against a repository, not only GitHub.
#
# Reads:  PYTHON VERSION_SOURCE TAG TAG_PREFIX DEFAULT_BRANCH CHECK_WORKFLOW GITHUB_OUTPUT
#         GH_TOKEN, read by `gh`, not by this script
# Writes: version, next, landed  (to GITHUB_OUTPUT)
set -uo pipefail

# Refused here, not skipped at the end.
# The input is required, but GitHub does not enforce that, so one left out arrives empty.
# Skipping it would land the release with nothing started to check it.
if [[ -z $CHECK_WORKFLOW ]]; then
  echo "::error::check-workflow names no workflow, so nothing would check the release once it landed"
  exit 1
fi

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../check-release" && pwd)/check-release.py"

check_release=("$PYTHON" "$script")
source_arguments=(--version-source "$VERSION_SOURCE")
if [[ -n $TAG_PREFIX ]]; then
  source_arguments+=(--tag-prefix "$TAG_PREFIX")
fi

prefix=$("${check_release[@]}" prefix "${source_arguments[@]}"); rc=$?
if (( rc != 0 )); then
  echo "::error::check-release could not say what release tags are called here"
  exit 1
fi
version="${TAG#"$prefix"}"

# check-release answers what follows a release, as it answers every other question about versions.
# Counting up the patch here would be wrong after a pre-release.
# 0.2.0-rc.1 was a step towards 0.2.0, so work goes on towards 0.2.0, not 0.2.1.
next=$("${check_release[@]}" next "$TAG" "${source_arguments[@]}"); rc=$?
if (( rc != 0 )); then
  echo "::error::check-release could not say what follows $TAG"
  exit 1
fi
{
  echo "version=${version}"
  echo "next=${next}"
} >> "$GITHUB_OUTPUT"

# A run repeated after the release has landed, to retry a later step of the job for example, finds the tag on
# the default branch already.
# There is nothing left to do: the release branch is deleted by then, or left for someone to delete.
# Failing here would show a red run for a release that is where it should be.
if git merge-base --is-ancestor "$TAG" "origin/${DEFAULT_BRANCH}"; then
  echo "${TAG} is on ${DEFAULT_BRANCH} already: the release has landed, and there is nothing to carry back"
  echo "landed=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Not a setting: check-release names release/<version> first among the branches that hold the tag -
# the remote ones, or the local ones where no remote one does.
branch="release/${version}"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if ! git switch "$branch"; then
  echo "::error::could not switch to ${branch}, the branch the release commit is expected on"
  exit 1
fi

# Written by the tool that also reads that line, not by a pattern here.
# A separate reader and writer can drift apart unnoticed: the writing breaks while the reading still works.
# A source that declares no version has nothing to write and exits with 3, which is accepted.
# Any other failure stops the run before anything reaches the default branch.
# The release is out either way.
# Landing it with the released version still declared would get the next release refused: the file would name a
# version that is no longer being worked on.
"${check_release[@]}" set-version "${next}" --version-source "$VERSION_SOURCE" >/dev/null; rc=$?
if (( rc == 0 )); then
  git diff --quiet || git commit -qam "chore: start ${next}" || exit 1
elif (( rc == 3 )); then
  echo "${VERSION_SOURCE} records no version after a release, so none was written"
else
  echo "::error::${VERSION_SOURCE} could not be given ${next}, so nothing was carried back"
  exit 1
fi

# The title follows what the branch holds, not what this run wrote.
# An earlier run may have pushed the branch and then been refused the pull request.
# A repeated run then finds the next version already started by that run's commit, and writes nothing.
#
# The version started is counted from the release alone.
# An entry that landed on the default branch while the release was out may ask [Unreleased] for more, such as an
# `### Added`. It never lands here on its own:
# - the merge below conflicts in CHANGELOG.md, or
# - it puts the entry in the released section, which the changelog check refuses.
# So it reaches the pull request.
# Once it stands under [Unreleased] there, a version check refuses the version started, and the body says why.
# It stands there once the conflict is resolved, or once the entry is moved back out of the released section.
if git log --format=%s "${TAG}..HEAD" | grep -xF "chore: start ${next}" >/dev/null; then
  title="Release ${version}, and start ${next}"
  opened="
This branch starts \`${next}\`, counted from \`${version}\` alone. Where \`${DEFAULT_BRANCH}\` brings an entry
under \`[Unreleased]\` that asks for more - an \`### Added\` that landed while the release was out, say - it
stands under \`[Unreleased]\` here only once the conflict is resolved, or once it is moved back out of the
released section the \`changelog\` check names. From then on the \`version\` check of this pull request, where
it runs one, refuses the version this branch starts and names the least version it takes: raise the declared
version to that one here, followed by the marker \`${next}\` carries. The check takes the marker off before it
compares, so one declared without it passes as well, and the default branch then builds as that release before
it is one.
"
else
  title="Release ${version}"
  opened=""
fi

# Work that landed on the default branch since the release was cut is merged in here.
# The result is checked before anything is pushed, so the new default branch is a tree that was checked.
# The changelog check is the reason.
# A three-way merge can put an entry added to [Unreleased] after the branch point into the released section:
# git merges lines and cannot see that a heading contains what follows it.
#
# The merge also makes the push below a fast-forward.
# The branch now holds the default branch's tip, so moving the default branch onto it takes no new commit.
#
# A merge that conflicts, or whose result the checks refuse, is undone and left to a pull request.
# A conflict is resolved there anyway.
# The attempt must not fail the run: the release is out either way.
landable=true
before=$(git rev-parse HEAD)
if ! git merge --no-edit "origin/${DEFAULT_BRANCH}"; then
  git merge --abort 2>/dev/null || true
  landable=false
  echo "::warning::origin/${DEFAULT_BRANCH} did not merge into ${branch}; it is left to a pull request"
else
  for check in changelog ancestry; do
    if ! "${check_release[@]}" "$check" "${source_arguments[@]}"; then
      git reset -q --hard "$before"
      landable=false
      echo "::warning::origin/${DEFAULT_BRANCH} merged into ${branch}, but ${check} refused the result;" \
           "it is left to a pull request"
      break
    fi
  done
fi

# Pushed, not offered as a pull request, because the tag names the commit the release was made from.
# Every way GitHub's buttons land a branch loses that commit from the default branch's first-parent line:
# - squash and rebase replace it with a copy;
# - a merge commit, which never fast-forwards, leaves it on the merge's second parent.
# A push moves the default branch onto this branch as it is, so the release commit and its tag stay on that line.
#
# Deliberately not forced.
# The push is a fast-forward only while nothing else has moved the default branch since the merge above.
# If something has, git refuses it and a pull request carries the release instead.
# That refusal catches the race; it is not an error to push past.
# A default branch that takes no push from the credentials the checkout left, such as a protected one requiring
# pull requests, refuses every time.
# The warning cannot tell the two cases apart, so it names both.
landed=false
if [[ $landable == true ]] && git push origin "HEAD:${DEFAULT_BRANCH}"; then
  landed=true
elif [[ $landable == true ]]; then
  echo "::warning::the push to ${DEFAULT_BRANCH} was refused: it moved while this ran, or it takes no push" \
       "from the credential the checkout left"
fi
echo "landed=${landed}" >> "$GITHUB_OUTPUT"

if [[ $landed == true ]]; then
  # The release is already out and on the default branch, so neither step below fails the run: both only warn.
  # A push made with GITHUB_TOKEN starts no workflow run, so the check workflow is started by hand.
  # Starting it is a write to Actions, answered 403 without `actions: write`.
  # A pull request an earlier run opened for this branch is marked merged by GitHub once its head is on the
  # default branch, so deleting the branch does not close it unmerged.
  gh workflow run "$CHECK_WORKFLOW" --ref "${DEFAULT_BRANCH}" \
    || echo "::warning::${CHECK_WORKFLOW} was not started for ${DEFAULT_BRANCH}; start it by hand"
  git push origin --delete "$branch" \
    || echo "::warning::${branch} is still there; it has landed and can be deleted"
  exit 0
fi

# Only the cases above get here: a conflict to resolve, a merge the checks refused, or a refused push.
# A pull request after a release is therefore something to look at, not a routine step.
# That is why its body says what happened and how it must be merged.
if ! git push origin "$branch"; then
  echo "::error::${branch} could not be pushed, so no pull request carries ${TAG} back"
  exit 1
fi
# A repeated run, to retry a later step of the job for example, may find the pull request an earlier run opened
# still open, now carrying the branch as just pushed.
# GitHub would refuse a second one.
# Where the lookup itself fails, the pull request is still asked for, and GitHub's answer says what is wrong.
carrying_pull_request=$(gh pr list --base "${DEFAULT_BRANCH}" --head "$branch" --state open --json url \
  --jq '.[0].url // empty' 2>/dev/null) || carrying_pull_request=""
if [[ -n $carrying_pull_request ]]; then
  echo "${carrying_pull_request} carries ${TAG} back already, so no other pull request is opened"
  exit 0
fi
gh pr create \
  --base "${DEFAULT_BRANCH}" \
  --head "$branch" \
  --title "$title" \
  --body "$(cat <<BODY
\`${TAG}\` is published, but could not be carried back on its own: \`${DEFAULT_BRANCH}\` did not merge into
this branch cleanly, or merged into a tree the release rules refused, or refused the push that would have
landed it - having moved under it, or taking no push from the credential the run pushed with. The run that
tried says which of the three it met; why a push was refused, it cannot tell.

**Merge this with a merge commit.** Neither *Squash and merge* nor *Rebase and merge* may be used here:
\`${TAG}\` points at the release commit in this branch, and both of them replace that commit with a copy,
which leaves the tag off the history of \`${DEFAULT_BRANCH}\`. *Rebase and merge* does so even where a
fast-forward would do, because it always rewrites committer and date. The \`ancestry\` check goes red for
every commit afterwards if that happens.

Until this is merged, \`${DEFAULT_BRANCH}\` does not reach \`${TAG}\`: \`ancestry\` and \`changelog\` fail there
and on every other pull request into it - \`version\` too, where the source declares a version, which
\`${DEFAULT_BRANCH}\` still declares as the one just released - and no next release can be prepared.
${opened}
The checks here may be waiting to be approved rather than running: where the Actions bot opened this pull
request, GitHub holds its runs until someone with write access approves them, from the banner on this pull
request (**Approve workflows to run**).
BODY
)"
