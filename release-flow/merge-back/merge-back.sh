#!/usr/bin/env bash
# Carry a published release back onto the default branch. Driven by environment rather than by arguments,
# because that is how a composite action hands its inputs over - and kept out of action.yml so that it can be
# run against a repository in a test rather than only by GitHub.
#
# Reads:  SOURCE TAG TAG_PREFIX DEFAULT_BRANCH BRANCH_PREFIX BUILD_WORKFLOW GITHUB_OUTPUT
#         GH_TOKEN, by `gh` rather than by anything here
# Writes: version, next, landed  (to GITHUB_OUTPUT)
set -uo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../check-release" && pwd)/check-release.py"

prefix=()
if [ "$TAG_PREFIX" = '^none' ]; then
  prefix=(--tag-prefix '')
elif [ -n "$TAG_PREFIX" ]; then
  prefix=(--tag-prefix "$TAG_PREFIX")
fi
rules=(python3 "$script" --source "$SOURCE" "${prefix[@]}")

tag_prefix=$("${rules[@]}" prefix); rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::check-release could not say what release tags are called here"
  exit 1
fi
version="${TAG#"$tag_prefix"}"

# What follows a release is a question about versions, so it is answered where the other ones are. Counting
# the patch up here would be wrong after a pre-release: 0.2.0-rc.1 was a step towards 0.2.0, and work goes on
# heading for it rather than skipping to 0.2.1.
next=$("${rules[@]}" next "$TAG"); rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::check-release could not say what follows $TAG"
  exit 1
fi
{
  echo "version=${version}"
  echo "next=${next}"
} >> "$GITHUB_OUTPUT"

branch="${BRANCH_PREFIX}${version}"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git switch "$branch" || exit 1

# Written by the tool that also reads that line, rather than by a pattern here: a reader and a writer that
# have to agree about how the line is written can drift apart in silence, and it is the writing that stops
# while the reading goes on working. A source that records no version says so with a status of its own, 3,
# and is believed. Any other failure stops the run before anything reaches the default branch: the release is
# out either way, and landing it with the released version still declared would have the next release refused
# as one already made.
"${rules[@]}" set-version "${next}" >/dev/null; rc=$?
if [ "$rc" -eq 0 ]; then
  git commit -qam "chore: start ${next}" || exit 1
elif [ "$rc" -eq 3 ]; then
  echo "${SOURCE} records no version after a release, so none was written"
else
  echo "::error::${SOURCE} could not be given ${next}, so nothing was carried back"
  exit 1
fi

# Work that landed on the default branch while the draft was waiting is merged in here, and the result is held
# to the rules before anything is pushed, so that what is about to become the default branch is a tree that was
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
merged=true
before=$(git rev-parse HEAD)
if ! git merge --no-edit "origin/${DEFAULT_BRANCH}"; then
  git merge --abort 2>/dev/null || true
  merged=false
  echo "::warning::origin/${DEFAULT_BRANCH} did not merge into ${branch}; the pull request carries it"
else
  for check in changelog ancestry; do
    if ! "${rules[@]}" "$check"; then
      git reset -q --hard "$before"
      merged=false
      echo "::warning::origin/${DEFAULT_BRANCH} merged into ${branch}, but ${check} refused the result;" \
           "the pull request carries it"
      break
    fi
  done
fi

# Pushed rather than offered, because the tag is the point. It names the commit the archive was built and
# signed from, and every way GitHub's own buttons land a branch - squash, rebase, and the merge commit too,
# which never fast-forwards - either replaces that commit or leaves it on the merge's second parent, off the
# default branch's first-parent line. A push moves the default branch onto this branch as it stands, so the
# release commit, and the tag with it, stays on that line.
#
# Not forced, deliberately. The push is a fast-forward only while nothing else has moved the default branch
# since the merge above; if something has, git refuses it and the pull request carries the release instead.
# That refusal is the race being caught, not an error to push past.
landed=false
if [ "$merged" = true ] && git push origin "HEAD:${DEFAULT_BRANCH}"; then
  landed=true
elif [ "$merged" = true ]; then
  echo "::warning::${DEFAULT_BRANCH} moved while this ran, so the fast-forward was refused"
fi
echo "landed=${landed}" >> "$GITHUB_OUTPUT"

if [ "$landed" = true ]; then
  # Neither of these is worth failing a release that is already out and already on the default branch, so
  # both only say so. A push made with GITHUB_TOKEN starts no workflow run, which is why the build is asked
  # for by hand; asking is a write to Actions and is answered 403 without `actions: write`.
  if [ -n "$BUILD_WORKFLOW" ]; then
    gh workflow run "$BUILD_WORKFLOW" --ref "${DEFAULT_BRANCH}" \
      || echo "::warning::${BUILD_WORKFLOW} was not started for ${DEFAULT_BRANCH}; start it by hand"
  fi
  git push origin --delete "$branch" \
    || echo "::warning::${branch} is still there; it has landed and can be deleted"
  exit 0
fi

# The way out of the cases above, and nothing else: a conflict to resolve, a merge the rules refused, or a
# default branch that moved under the push. A pull request after a release is therefore a thing to look at
# rather than a step of the process, which is why the body says what happened and how it must be merged.
git push origin "$branch"
gh pr create \
  --base "${DEFAULT_BRANCH}" \
  --head "$branch" \
  --title "Release ${version}, and start ${next}" \
  --body "$(cat <<BODY
\`${TAG}\` is published, but could not be carried back on its own: \`${DEFAULT_BRANCH}\` did not merge into
this branch cleanly, or merged into a tree the release rules refused, or moved while the release was being
published. The run that tried says which.

**Merge this with a merge commit.** Neither *Squash and merge* nor *Rebase and merge* may be used here:
\`${TAG}\` points at the release commit in this branch, and both of them replace that commit with a copy,
which leaves the tag off the history of \`${DEFAULT_BRANCH}\`. *Rebase and merge* does so even where a
fast-forward would do, because it always rewrites committer and date. The \`ancestry\` check goes red for
every commit afterwards if that happens.

The checks here may be waiting to be approved rather than running: GitHub holds the runs of a pull request
the Actions bot opened until someone with write access approves them, from the banner on this pull request
(**Approve workflows to run**).
BODY
)"
