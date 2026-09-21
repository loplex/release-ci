#!/usr/bin/env bash
# Carry a published release back onto the default branch. Driven by environment rather than by arguments,
# because that is how a composite action hands its inputs over - and kept out of action.yml so that it can be
# run against a repository in a test rather than only by GitHub.
#
# Reads:  SOURCE TAG TAG_PREFIX DEFAULT_BRANCH CHECK_WORKFLOW GITHUB_OUTPUT
#         GH_TOKEN, by `gh` rather than by anything here
# Writes: version, next, landed  (to GITHUB_OUTPUT)
set -uo pipefail

# Refused here rather than skipped at the end: the input is required, and GitHub does not hold an action to
# that, so one left out arrives as nothing. Skipped, it would land the release with nothing asked to check it.
if [ -z "$CHECK_WORKFLOW" ]; then
  echo "::error::check-workflow names no workflow, so nothing would check the release once it landed"
  exit 1
fi

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../check-release" && pwd)/check-release.py"

prefix_arguments=()
if [ "$TAG_PREFIX" = '^none' ]; then
  prefix_arguments=(--tag-prefix '')
elif [ -n "$TAG_PREFIX" ]; then
  prefix_arguments=(--tag-prefix "$TAG_PREFIX")
fi
check_release=(python3 "$script" --source "$SOURCE" "${prefix_arguments[@]}")

prefix=$("${check_release[@]}" prefix); rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::check-release could not say what release tags are called here"
  exit 1
fi
version="${TAG#"$prefix"}"

# What follows a release is a question about versions, so it is answered where the other ones are. Counting
# the patch up here would be wrong after a pre-release: 0.2.0-rc.1 was a step towards 0.2.0, and work goes on
# heading for it rather than skipping to 0.2.1.
next=$("${check_release[@]}" next "$TAG"); rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::check-release could not say what follows $TAG"
  exit 1
fi
{
  echo "version=${version}"
  echo "next=${next}"
} >> "$GITHUB_OUTPUT"

# A run repeated once the release has landed - to try a later step of the job again, say - finds the tag on the
# default branch already and nothing left to do: the release branch is deleted by then, or left over for someone
# to delete. Failing on it would put a red run over a release that is where it should be.
if git merge-base --is-ancestor "$TAG" "origin/${DEFAULT_BRANCH}"; then
  echo "${TAG} is on ${DEFAULT_BRANCH} already: the release has landed, and there is nothing to carry back"
  echo "landed=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

# Not a setting: check-release names release/<version> first among the remote branches holding the tag,
# or among the local ones where no remote one does.
branch="release/${version}"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if ! git switch "$branch"; then
  echo "::error::could not switch to ${branch}, the branch the release commit is expected on"
  exit 1
fi

# Written by the tool that also reads that line, rather than by a pattern here: a reader and a writer that
# have to agree about how the line is written can drift apart in silence, and it is the writing that stops
# while the reading goes on working. A source that declares no version says so with a status of its own, 3,
# and is believed. Any other failure stops the run before anything reaches the default branch: the release is
# out either way, and landing it with the released version still declared would have the next release
# refused, the file naming a version that is no longer being worked on.
"${check_release[@]}" set-version "${next}" >/dev/null; rc=$?
if [ "$rc" -eq 0 ]; then
  git diff --quiet || git commit -qam "chore: start ${next}" || exit 1
elif [ "$rc" -eq 3 ]; then
  echo "${SOURCE} records no version after a release, so none was written"
else
  echo "::error::${SOURCE} could not be given ${next}, so nothing was carried back"
  exit 1
fi

# Titled by what the branch holds rather than by what this run wrote. A run repeated after an earlier one
# pushed the branch and was refused the pull request finds the next version opened already, by the commit that
# earlier run made, and writes nothing.
if git log --format=%s "${TAG}..HEAD" | grep -xF "chore: start ${next}" >/dev/null; then
  title="Release ${version}, and start ${next}"
else
  title="Release ${version}"
fi

# Work that landed on the default branch since the release was cut is merged in here, and the result is held to
# the rules before anything is pushed, so that what is about to become the default branch is a tree that was
# looked at rather than one that never existed. The changelog check is the reason: a three-way merge can put an
# entry added to [Unreleased] after the branch point into the released section instead - git merges lines and
# cannot see that a heading is a container.
#
# It is also what makes the push below a fast-forward: the branch now holds the default branch's tip, so
# moving that branch onto this one takes no new commit.
#
# A merge that conflicts, or whose result the rules refuse, is undone and left to a pull request, which is
# where a conflict is resolved anyway. Attempting it must not be able to fail the run: the release is out
# either way.
landable=true
before=$(git rev-parse HEAD)
if ! git merge --no-edit "origin/${DEFAULT_BRANCH}"; then
  git merge --abort 2>/dev/null || true
  landable=false
  echo "::warning::origin/${DEFAULT_BRANCH} did not merge into ${branch}; it is left to a pull request"
else
  for check in changelog ancestry; do
    if ! "${check_release[@]}" "$check"; then
      git reset -q --hard "$before"
      landable=false
      echo "::warning::origin/${DEFAULT_BRANCH} merged into ${branch}, but ${check} refused the result;" \
           "it is left to a pull request"
      break
    fi
  done
fi

# Pushed rather than offered, because the tag is the point. It names the commit the release was made from,
# and every way GitHub's own buttons land a branch - squash, rebase, and the merge commit too, which never
# fast-forwards - either replaces that commit or leaves it on the merge's second parent, off the default
# branch's first-parent line. A push moves the default branch onto this branch as it stands, so the release
# commit, and the tag with it, stays on that line.
#
# Not forced, deliberately. The push is a fast-forward only while nothing else has moved the default branch
# since the merge above; if something has, git refuses it and the pull request carries the release instead.
# That refusal is the race being caught, not an error to push past. A default branch that takes no push from
# the credential the checkout left - a protected one requiring pull requests - refuses it every time, and
# the warning cannot tell the two apart, so it names both.
landed=false
if [ "$landable" = true ] && git push origin "HEAD:${DEFAULT_BRANCH}"; then
  landed=true
elif [ "$landable" = true ]; then
  echo "::warning::the push to ${DEFAULT_BRANCH} was refused: it moved while this ran, or it takes no push" \
       "from the credential the checkout left"
fi
echo "landed=${landed}" >> "$GITHUB_OUTPUT"

if [ "$landed" = true ]; then
  # Neither of these is worth failing a release that is already out and already on the default branch, so
  # both only say so. A push made with GITHUB_TOKEN starts no workflow run, which is why the check is asked
  # for by hand; asking is a write to Actions and is answered 403 without `actions: write`. Where a pull
  # request an earlier run opened still carries the branch, GitHub marks it merged once its head is on the
  # default branch, so deleting the branch does not close it unmerged.
  gh workflow run "$CHECK_WORKFLOW" --ref "${DEFAULT_BRANCH}" \
    || echo "::warning::${CHECK_WORKFLOW} was not started for ${DEFAULT_BRANCH}; start it by hand"
  git push origin --delete "$branch" \
    || echo "::warning::${branch} is still there; it has landed and can be deleted"
  exit 0
fi

# The way out of the cases above, and nothing else: a conflict to resolve, a merge the rules refused, or a
# default branch that refused the push. A pull request after a release is therefore a thing to look at
# rather than a step of the process, which is why the body says what happened and how it must be merged.
if ! git push origin "$branch"; then
  echo "::error::${branch} could not be pushed, so no pull request carries ${TAG} back"
  exit 1
fi
# A run repeated while the pull request an earlier one opened is still open - to try a later step of the job again,
# say - finds that pull request carrying the branch as just pushed, and GitHub would refuse it a second one. Where
# the question itself fails, the pull request is asked for all the same, and the answer to that says why.
carrying_pull_request=$(gh pr list --base "${DEFAULT_BRANCH}" --head "$branch" --state open --json url \
  --jq '.[0].url // empty' 2>/dev/null) || carrying_pull_request=""
if [ -n "$carrying_pull_request" ]; then
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

The checks here may be waiting to be approved rather than running: where the Actions bot opened this pull
request, GitHub holds its runs until someone with write access approves them, from the banner on this pull
request (**Approve workflows to run**).
BODY
)"
