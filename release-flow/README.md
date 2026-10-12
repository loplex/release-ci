# release-flow

Four actions that cut, draft, carry back and flag a GitHub release.

A release runs them in this order:

1. `release-flow/prepare` cuts the release commit.
2. The ecosystem builds and signs what the release carries.\
   For a JetBrains plugin, [intellij](../intellij/README.md#intellij) does that.
3. `release-flow/draft` pushes the release branch and drafts the release.
4. Someone publishes the draft.
5. `release-flow/merge-back` carries the release back onto the default branch.

`release-flow/warn` follows a step that publishes the release somewhere other than GitHub.\
It says on the release when that publish did not complete.

| Action                    | Runs in                                   | Takes `version-source` and `tag-prefix` |
|---------------------------|-------------------------------------------|-----------------------------------------|
| `release-flow/prepare`    | a checkout with `fetch-depth: 0`          | yes                                     |
| `release-flow/draft`      | the workspace `release-flow/prepare` left | no                                      |
| `release-flow/merge-back` | a checkout with `fetch-depth: 0`          | yes                                     |
| `release-flow/warn`       | no checkout                               | no                                      |

`version-source` and `tag-prefix` work as in
[check-release's action](../check-release/README.md#using-check-release-from-another-repository),
`^none` included.\
Why `release-flow/warn` needs no checkout is in [its section](#release-flowwarn).

What pinning an action to a release tag or to another ref gets you is under
[Pinning](../README.md#pinning).\
What each action needs of the runner is under
[What an action needs of the runner](../README.md#what-an-action-needs-of-the-runner).

## The workflow files

Three workflows carry a project through a release, and the examples here name them:

| File                  | Started by                             | Runs                                                |
|-----------------------|----------------------------------------|-----------------------------------------------------|
| `ci.yml`              | a push, a pull request, and merge-back | `check-release`; for a plugin, `intellij/check` too |
| `release-draft.yml`   | a dispatch, on the default branch      | [the release job](#the-release-job)                 |
| `release-publish.yml` | the release being published            | [the merge-back job](#release-flowmerge-back)       |

- Nothing requires these names; `check-workflow` names the first by its file, whatever it is.
- One name per role makes the three easy to find in any project that uses this repository.
- This repository's own are `test.yml`, `release.yml` and `release-publish.yml`.

## release-flow/prepare

[`release-flow/prepare`](prepare/action.yml) cuts the release commit onto a branch of its own:

1. It asks the rules `changelog`, `ancestry` and `version`, all three.\
   Where one says no, it writes nothing.\
   It also writes nothing where `[Unreleased]` has nothing to release, as
   [The changelog](../lib/README.md#the-changelog) says.
2. It closes `[Unreleased]` into a section for the version being released.
3. It writes that version back where the source declares one.
4. It makes one commit on `release/<version>`, and leaves the workspace on that branch.

The version comes from the source, or from the `version` input.\
[Where the version comes from](../lib/README.md#where-the-version-comes-from) says how,
for each source.

Given a `repository-url`, `prepare` also rewrites the link definitions of the changelog's versions,
pointing into the repository.\
Any other link definition stays as it is.

Given `skip-unreadable-releases: true`, the `changelog` check names as not compared a release whose
tag holds a line of `CHANGELOG.md` it does not read, instead of failing.\
[The changelog](../lib/README.md#the-changelog) says which lines count.\
The release job below passes it on from a checkbox of the dispatch.\
`merge-back` and `check-release` take the same input.\
Their events have no checkbox, so it is written in their workflows.

### Nothing leaves the workspace

`prepare` pushes nothing.\
The build runs from the release commit next, and a failed build should leave neither a branch nor
a draft on the remote.\
`release-flow/draft` pushes, after the build.\
`prepare` writes nothing outside the workspace, and needs no permissions of its own.

### The release job

```yaml
# .github/workflows/release-draft.yml
on:
  workflow_dispatch:
    inputs:
      version:
        description: >-
          The version to release, 0.2.0 or 0.2.0-SNAPSHOT; left empty, the one
          gradle.properties declares
        default: ''
      skip-unreadable-releases:
        description: >-
          Pass over a release whose tag holds a CHANGELOG.md line the checks do
          not read
        type: boolean
        default: false
# One at a time: two runs would race for the same release branch and the same draft.
concurrency:
  group: release
  cancel-in-progress: false
jobs:
  release:
    # A dispatch can be started on any branch, and would cut the release from that one.
    if: github.ref == format('refs/heads/{0}', github.event.repository.default_branch)
    runs-on: ubuntu-latest
    # For pushing the branch and drafting the release after the build; prepare itself takes none.
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: loplex/release-ci/release-flow/prepare@<tag>
        id: cut
        with:
          version-source: gradle.properties
          version: ${{ inputs.version }}
          repository-url: ${{ github.server_url }}/${{ github.repository }}
          skip-unreadable-releases: ${{ inputs.skip-unreadable-releases }}
      # Build from the commit now checked out, then:
      - uses: loplex/release-ci/release-flow/draft@<tag>
        with:
          version: ${{ steps.cut.outputs.version }}
          tag: ${{ steps.cut.outputs.tag }}
          branch: ${{ steps.cut.outputs.branch }}
          files: build/distributions/*.zip
```

## release-flow/draft

[`release-flow/draft`](draft/action.yml) pushes the release branch and drafts the release from it:

- The notes are the version's released section of `CHANGELOG.md`.\
  A relative link in them leads nowhere while the release is a draft: GitHub reads it at a name
  of the draft's own, `untagged-…`, and at the tag only once the draft is published.
- The files are what `files` names, one pattern or path per line.\
  A pattern is a bash glob, in which `**` goes no deeper than `*`.\
  With `files` left empty, nothing is attached.
- A version with a pre-release suffix is marked as a pre-release.\
  `lib/main.py channel` decides that, by the rule in
  [The channel a version goes to](../lib/README.md#the-channel-a-version-goes-to).

The job needs `contents: write` for the push and the draft.\
[The release job](#the-release-job) runs `draft` after the build, and hands it the `version`, `tag`
and `branch` that `prepare` outputs.

### What draft checks before the push, and what GitHub answers after it

`draft` checks the notes, the files and the channel before it pushes:

- Where one of them fails, no branch is left behind.
- A pattern that matches no file, or a path that names none, stops the run.\
  The release does not go out without the file.

GitHub can answer only after the push, because a draft has to point at a commit GitHub has:

- Where GitHub refuses the draft, the branch stays.
- Running again replaces the branch and drafts the release from it.

### A draft standing under the tag is replaced

Before it makes the draft, `draft` deletes any draft already standing under the tag.\
Such a draft may come from an earlier run, or be made by hand.\
A published release is left alone.

### The one forced push in the flow

`draft` pushes the release branch with force, the only forced push in the flow.\
The branch belongs to the release: a second run replaces the branch an earlier run left behind with
its draft thrown away.\
A protection rule or ruleset over `release/*` has to let the checkout's credential force-push
there.\
GitHub's branch protection does not allow that by default.

### The tag is created when the draft is published

`draft` names the tag but does not create it.\
GitHub creates it when the draft is published, so a draft thrown away leaves no tag behind.

## release-flow/merge-back

[`release-flow/merge-back`](merge-back/action.yml) carries a published release back onto the default
branch:

1. Where the source declares a version, it opens the next one, in a commit of its own.
2. It merges in whatever landed on the default branch since the release was cut.
3. It moves the default branch onto the release branch with a **fast-forward** push.

The release branch is `release/<version>`, named after the tag's version.\
It holds the release commit and whatever merge-back adds above it.

```yaml
# .github/workflows/release-publish.yml
on:
  release:
    types: [published]
# One run per release at a time: two runs for one release would race to land it.
concurrency:
  group: merge-back-${{ github.event.release.tag_name }}
  cancel-in-progress: false
jobs:
  merge-back:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      actions: write
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: loplex/release-ci/release-flow/merge-back@<tag>
        with:
          version-source: gradle.properties
          tag: ${{ github.event.release.tag_name }}
          default-branch: ${{ github.event.repository.default_branch }}
          check-workflow: ci.yml
```

### A fast-forward push, not a pull request

The push is a fast-forward, and it is not forced.\
A release tag names the commit the release was made from, and each way of landing treats that commit
differently:

- *Squash and merge* and *Rebase and merge* replace the commit with a copy.\
  The tag drops off the default branch's history, and `ancestry` goes red for every commit after it.
- A merge commit keeps the tag reachable, but only through its second parent.\
  That is off the default branch's first-parent line, so merge-back pushes instead of opening a pull
  request.
- A push moves the default branch onto the release branch as it stands.\
  The release commit stays on the first-parent line.\
  Above it are the commit that opens the next version, where the source declares one, and whatever
  else the release branch gained, such as a merge of what landed meanwhile.\
  Where a merge is there, a notice on the run that lands says so, with how many commits they took
  in.\
  The run is green either way, though such a merge stays on the default branch's history.

### When a pull request carries the release instead

merge-back opens a pull request instead of pushing where:

- what landed meanwhile does not merge in cleanly; the merge is then undone;
- the rules refuse the merged tree.\
  merge-back asks `changelog` and `ancestry` of it before the push, because a three-way merge can
  put an entry added to `[Unreleased]` into the released section;
- the default branch moved under the push, and git refused it.\
  That refusal is a race with another push being caught, not an error to push past;
- the default branch takes no push from the credential `actions/checkout` left in the workspace.\
  A protected branch that requires pull requests is one, and sends every release to a pull request.

That credential is `GITHUB_TOKEN`, unless the checkout is given a `token` of its own.\
merge-back's own `token` does not push.

### What the pull request needs of the repository

merge-back opens its pull request with its `token` input, which is `GITHUB_TOKEN` unless it is set.\
With `GITHUB_TOKEN`, the job's `pull-requests: write` is not enough.\
The repository has to allow it as well: *Allow GitHub Actions to create and approve pull requests*,
under Settings > Actions > General.\
A new personal repository has it off.\
A repository in an organization takes whatever the organization says.

Merge commits have to be allowed too, under Settings > General > Pull Requests.\
A default branch whose protection requires a linear history takes neither that merge nor
merge-back's own push, once that push carries a merge of what landed meanwhile.

### Required pull requests and a linear history leave a release no way to land

A default branch whose protection requires both pull requests and a linear history cannot take a
release with its tag on the history:

- every release goes to merge-back's pull request, as
  [When a pull request carries the release instead](#when-a-pull-request-carries-the-release-instead)
  says;
- the protection refuses to merge that pull request with a merge commit;
- *Squash and merge* and *Rebase and merge* take the tag off the history, as
  [Merge merge-back's pull request with a merge commit](#merge-merge-backs-pull-request-with-a-merge-commit)
  says.

Only a push by a credential allowed to bypass the protection lands the release there.\
A linear history alone leaves a release no way to land as well, once anything landed on the default
branch while the release was out: merge-back's push then carries a merge, which the protection
refuses, and its pull request meets the last two points above.

### `landed` says whether the release landed

The merge-back step succeeds both when it lands the release and when it opens a pull request.\
The `landed` output says which:

- `true`: the release commit is on the default branch.\
  This run carried it there, or a repeated run found it there, whichever way it landed.
- `false`: a pull request carries the release instead.\
  This run opened it, or an earlier run did and it is still open.

Read `landed` only after the step succeeded.\
A step that failed may have left it unset, or `false` with no pull request opened.

### Running it again

A run repeated while merge-back's pull request is still open tries to land the release again:

- Where it now can, it does, and `landed` is `true`.\
  GitHub then marks the pull request
  [merged](https://docs.github.com/en/pull-requests/reference/pull-request-merges), because its
  head is on the default branch.
- Where it still cannot, the pull request goes on carrying the release.

### The release branch

- The run that lands the release deletes the release branch.\
  Where the deletion fails, because a rule over the branch forbids it, say, the run only warns.
- Where a pull request carries the release instead, the branch is left to whoever merges it.
- A run that cannot push the branch, or cannot open the pull request, fails.
- Delete a branch left behind once its release has landed.\
  GitHub's repository setting *Automatically delete head branches* does so for the branch of a
  merged pull request.\
  While it is there, a force-push that takes the release back off the default branch is taken for a
  release [yet to land](../lib/README.md#a-release-yet-to-land-exits-with-4), and only warned of.

### Merge merge-back's pull request with a merge commit

Merge the pull request merge-back opens with a merge commit, as the pull request's body says.\
The tag then stays reachable, which is all `ancestry` asks.\
*Squash and merge* and *Rebase and merge* take it off the history.

The workflows on merge-back's pull request may wait for approval instead of running, as its body
says too.\
GitHub holds the runs of a pull request opened with `GITHUB_TOKEN` until someone with write access
approves them.

### The checks warn until the release lands

From the publish until the release lands, by merge-back's push or by its pull request, the default
branch does not reach the release's tag.

- On the default branch and on every pull request into it, `ancestry`, `changelog` and, where the
  source declares a version, `version` find the release
  [yet to land](../lib/README.md#a-release-yet-to-land-exits-with-4).\
  `check-release` warns of it and passes.
- That includes a commit pushed while merge-back runs, as long as its check runs before the release
  lands.\
  A check of it that runs later, a re-run or one that waited in a queue, fails once the release
  branch is deleted, as merge-back deletes it when its own push lands the release: `ancestry` and
  `changelog` read the tag as taken off the history, and `version`, where the source declares a
  version, finds the version just released declared.\
  While the branch is still there, such a check warns.\
  Nothing is wrong with the commit: a run on a later one, such as the one merge-back starts, settles
  it.
- No next release can be prepared: `prepare` refuses.
- A warning in a check run started after the merge-back run means the release is not on the default
  branch: the run failed, its pull request is still open, or a force-push took the release back off,
  as [The release branch](#the-release-branch) says.\
  Look at that run, and [run it again](#running-it-again) where it failed.

### `check-workflow` needs `workflow_dispatch`, and `GITHUB_TOKEN` needs `actions: write`

`check-workflow` names the workflow that checks the default branch, by file name.\
A push made with `GITHUB_TOKEN` starts no workflow run, so merge-back starts that workflow itself
once the release has landed.

That workflow:

- has to list `workflow_dispatch` among its triggers.\
  GitHub refuses to start one that does not, and the release has landed by then, so the run only
  warns;
- has to be named.\
  Without it, the run stops before it carries anything back, so that no release lands unchecked.

[The workflow files](#the-workflow-files) suggests a file name for it.

With `token` left as `GITHUB_TOKEN`, the job needs `actions: write`.\
Starting a workflow is a write to Actions.\
Without the permission GitHub answers 403, and the release lands with nothing having checked it.\
The `contents: write` that the pushes need does not cover it.

## release-flow/warn

[`release-flow/warn`](warn/action.yml) says on a published release that publishing it somewhere
other than GitHub did not complete.\
Once a later publish completes, it takes that back.

Whoever has the release's files in hand looks at the release, not at the runs of a workflow.\
So the warning goes where they look: a `> [!WARNING]` at the start of the notes, naming where the
release was to go and linking the run.

It follows the step that publishes, in the same job, with `if: ${{ !cancelled() }}`, so that a
failure before it does not skip it.\
It is handed that step's `outcome`:

| `outcome` | The notes                                     |
|-----------|-----------------------------------------------|
| `success` | lose the warning, where they carry one        |
| `failure` | gain the warning at the start                 |
| `skipped` | gain it too: a step before the publish failed |

- Any other `outcome` fails the run.\
  That includes the empty one that a step id naming no step gives.\
  Read as a failure, it would put the warning on every release.
- It reads `outcome`, not `conclusion`, so a publish step allowed to fail with `continue-on-error`
  still counts as failed.
- The publish step's outcome decides, not the job's.\
  A merge-back that failed while the publish completed puts no warning on the release.\
  The release is served all the same, and the red job says the rest.
- A run whose notes already say what it would say leaves them alone.\
  Running the job again takes the warning off where the publish now completes, once a first version
  uploaded by hand is approved, say.\
  Where the publish fails again, the warning is said only once.

`warn` asks for the release by the repository's name, so it needs no checkout.\
The job needs `contents: write` to write the notes.\
The job under [intellij/publish](../intellij/README.md#the-job-that-publishes) shows the step after
an upload to the JetBrains Marketplace.

### How the warning is found

The warning sits between two HTML comments, `<!-- release-flow/warn -->` and
`<!-- /release-flow/warn -->`.\
GitHub keeps them in the notes, and does not show them.\
`warn` looks for the warning only where it puts it: at the very start of the notes, with the markers
on lines of their own around nothing but quoted lines.

- A line that starts the notes at the first column cannot stand in a code block, a list or a quote.\
  So no parsing is needed to know that the warning there is this action's.
- The words between the markers do not matter.\
  A warning written by another version of the action is still the one taken off or replaced.
- Taking the warning off takes the blank line after it too.\
  The rest of the notes keeps its line ends as they were.

### What fails the run instead

These fail the run, and leave the notes as they are for the warning to be taken off by hand:

- a line holding nothing but either marker, anywhere but the start of the notes;
- an opening marker at the start that is indented, or has spaces after it;
- a warning at the start that is not closed;
- a warning at the start that holds a line that is not quoted.

Such a line may be the warning after someone wrote above it, or an example the notes show as code.\
The action does not guess which.\
The step runs last, after the release and everything before it are done, so failing it undoes
nothing.

### The warning is the one thing release-flow writes into published notes

A release's notes are its released section of `CHANGELOG.md`.\
`release-flow/draft` writes them with `lib/main.py notes`, so that the two cannot come to say
different things.\
A link definition is one way they can: the `changelog` check compares none, so one edited after the
release moves the changelog's link and not the release page's.

The warning is the other.\
It is the only thing release-flow writes into the notes of a release already published, and no
changelog carries it.\
A released section may not be edited, and whether a publish completed is not a change to the
project.

The warning stays until a run whose publish completes takes it off.\
Where that run cannot tell it for this action's, it stays until someone takes it off by hand.

## Where GitHub reads each workflow from

The release job and the merge-back job are in workflows of their own, and GitHub reads them from
different commits:

- A workflow started by a dispatch runs only once its file is on the default branch.\
  It then takes the workflow file, and the checkout, from the branch it is started on.\
  That is why [the release job](#the-release-job) runs on the default branch alone: a release cut
  from another branch is what merge-back would carry onto the default branch, unreviewed.
- A workflow started by a release runs from the file as it stands in the commit the release tags.\
  A re-run takes the file from that commit too.\
  So a release cut while that file leaves out an input a pinned action requires runs without it on
  every re-run, even one made after the file is fixed on the default branch.

Both files have to be on the default branch before a release is cut from it.

A version of this repository that makes an input required marks it `**BREAKING**` in
[`CHANGELOG.md`](../CHANGELOG.md).\
A workflow moving its pin to that version can then pass the input in the same commit.
