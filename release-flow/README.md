# release-flow

Three actions, in the order a release runs them, with what sits between them:

1. `release-flow/prepare`;
2. whatever the ecosystem does - building and signing, which
   [intellij](../intellij/README.md#intellij) does for a JetBrains plugin;
3. `release-flow/draft`;
4. someone deciding to publish the draft;
5. `release-flow/merge-back`.

A fourth action, `release-flow/warn`, follows whatever publishes the release somewhere other than
GitHub, and says on the release when that did not complete.

`release-flow/prepare`, `release-flow/draft` and `release-flow/merge-back`:

- take `source` and `tag-prefix` as
  [check-release's action](../check-release/README.md#using-check-release-from-another-repository)
  does, `^none` included;
- run after a checkout with `fetch-depth: 0`.

`release-flow/warn` takes neither and needs no checkout, as [its section](#release-flowwarn) says.

Every one of them is pinned the way [Pinning](../README.md#pinning) says.\
What each needs of the runner is listed under
[What an action needs of the runner](../README.md#what-an-action-needs-of-the-runner).

## release-flow/prepare

[`release-flow/prepare`](prepare/action.yml) cuts the release commit onto a branch of its own:

1. The rules are asked first - `changelog`, `ancestry` and `version`, all three.\
   Nothing is written where one says no, nor where `[Unreleased]` has nothing to release, as
   [The changelog](../check-release/README.md#the-changelog) says.
2. `[Unreleased]` is closed into a section for the version being released.
3. That version is written back where the source declares one.
4. The one resulting commit is left on `release/<version>`, with the workspace on it.

The version comes from the source, or from the `version` input, as
[Where the version comes from](../check-release/README.md#where-the-version-comes-from) says for
each.

Given a `repository-url`, `release-flow/prepare` also writes the link definitions of the changelog's
versions afresh, pointing into the repository; any other definition stays.

### Nothing leaves the workspace

Nothing is pushed: the build runs from the release commit next, and a build that fails should leave
neither a branch nor a draft on the remote.\
Pushing comes after the build, with the draft.\
`release-flow/prepare` writes nothing outside the workspace and asks for no permissions of its own.

### The release job

```yaml
on:
  workflow_dispatch:
    inputs:
      version:
        description: >-
          The version to release, 0.2.0 or 0.2.0-SNAPSHOT; left empty, the one
          gradle.properties declares
        default: ''
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
          source: gradle.properties
          version: ${{ inputs.version }}
          repository-url: ${{ github.server_url }}/${{ github.repository }}
      # Build from the commit now checked out, then:
      - uses: loplex/release-ci/release-flow/draft@<tag>
        with:
          source: gradle.properties
          version: ${{ steps.cut.outputs.version }}
          tag: ${{ steps.cut.outputs.tag }}
          branch: ${{ steps.cut.outputs.branch }}
          files: build/distributions/*.zip
```

## release-flow/draft

[`release-flow/draft`](draft/action.yml) pushes the branch and drafts the release from it:

- The notes are the released section of `CHANGELOG.md`.
- The files are those `files` names - the build's, by pattern or path, one a line, a pattern being a
  bash glob, in which `**` goes no deeper than `*` - and none where it is left empty.
- A version with a pre-release suffix is marked as one, by the channel `check-release channel` reads
  off it under the rule in
  [The channel a version goes to](../check-release/README.md#the-channel-a-version-goes-to).

The job needs `contents: write` for the push and the draft.\
[The release job](#the-release-job) runs it after the build that follows `prepare`, handing on the
`version`, `tag` and `branch` that `prepare` answers with.

### What is asked before the push, and what after it

What can be answered on the runner - the notes, the files, the channel - is asked before the push:

- A draft refused over one of them leaves no branch behind.
- A pattern that matches no file, or a path that names none, stops the run rather than letting the
  release go out without it.

What GitHub answers comes after the push, a draft having to point at a commit GitHub has:

- A draft it refuses leaves the branch standing.
- Running again replaces the branch and drafts the release from it.

### A draft standing under the tag is replaced

A draft already standing under the tag, left by an earlier run or made by hand, is deleted before
the new one is made.\
A published release is left alone.

### The one forced push in the flow

The push is forced - the one forced push in the flow, the branch being the release's own, and one
left standing by a run whose draft was thrown away being what a second run replaces.\
A protection rule or ruleset over `release/*` has to let the checkout's credential force-push there,
which GitHub's branch protection does not by default.

### The tag is created when the draft is published

The tag is named but not created: GitHub creates it when the draft is published, so a draft thrown
away leaves no tag behind.

## release-flow/merge-back

[`release-flow/merge-back`](merge-back/action.yml) carries a published release back onto the default
branch:

1. It opens the next version being worked on, where the source declares one.
2. It takes in whatever landed since the release was cut.
3. It moves the default branch onto the release branch with a **fast-forward** push.

The release branch is `release/<version>`, named after the tag's version: the release commit and
whatever it takes on above it.

```yaml
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
          source: gradle.properties
          tag: ${{ github.event.release.tag_name }}
          default-branch: ${{ github.event.repository.default_branch }}
          check-workflow: ci.yml
```

### A fast-forward push, not a pull request

The fast-forward is the point, and so is that push not being forced.\
A release tag names the commit the release was made from:

- *Squash and merge* and *Rebase and merge* replace that commit with a copy, which takes the tag off
  the default branch's history and turns `ancestry` red for every commit after it.
- A merge commit keeps the tag reachable, but only through its second parent, off the default
  branch's first-parent line, which is why merge-back pushes rather than opening a pull request.
- A push moves the default branch onto the release branch as it stands, so the release commit stays
  on the first-parent line, below the commit opening the next version, where the source declares
  one, and whatever else the release branch gained, such as a merge of what landed meanwhile.

### When a pull request carries the release instead

A pull request carries the release instead of the push where:

- what landed meanwhile would not merge in cleanly (the merge is then undone);
- the default branch moved under that push and git refused it - that refusal is a race with another
  push being caught, not an error to push past;
- the rules refuse the merged tree: `changelog` and `ancestry` are asked of it before it is pushed,
  because a three-way merge can put an entry added to `[Unreleased]` into the released section;
- the default branch takes no push from the credential `actions/checkout` left in the workspace - a
  protected one requiring pull requests, say; such a branch sends every release to a pull request.

That credential is `GITHUB_TOKEN` unless the checkout is given a `token` of its own; merge-back's
own `token` does not push.

### What the pull request needs of the repository

Merge-back opens its pull request with the action's `token`, `GITHUB_TOKEN` unless it is set.\
Opened with `GITHUB_TOKEN`, it takes more than the job's `pull-requests: write`: the repository has
to allow it, with *Allow GitHub Actions to create and approve pull requests* under Settings >
Actions > General.\
A new personal repository has it off, and one in an organization takes whatever the organization
says.

Merging it with a merge commit has to be allowed as well, under Settings > General > Pull Requests.\
A default branch whose protection requires a linear history takes neither that merge nor
merge-back's own push, once that push carries a merge of what landed meanwhile.

### `landed` says whether the release landed

The merge-back step succeeds whether it landed the release or opened a pull request for it, and
`landed` says which:

- `true` where the release commit is on the default branch - carried there by this run, or found
  there by a run repeated after the release landed, whichever way it landed;
- `false` where a pull request carries it instead, opened by this run or by an earlier one and still
  open.

A step that failed may leave `landed` unset.

### Running it again

A run repeated while the pull request merge-back opened is still open tries to land the release
again:

- Where it now can, it does, with `landed` as `true`, and GitHub marks the pull request
  [merged](https://docs.github.com/en/pull-requests/reference/pull-request-merges), its head being
  on the default branch.
- Where it still cannot, the pull request goes on carrying it.

### The release branch

- The run that lands the release deletes the release branch, and a deletion that fails - a rule over
  the branch forbidding it, say - only warns.
- Where a pull request carries the release from that branch instead, the branch is left to whoever
  merges it.
- A run that cannot push that branch, or cannot open the pull request, fails.

### Merge merge-back's pull request with a merge commit

Merge a pull request merge-back opens with a merge commit, as the pull request's body says.\
The tag then stays reachable, which is all `ancestry` asks, where *Squash and merge* and *Rebase and
merge* take it off the history.

Until it is merged the default branch does not reach the release's tag, so:

- `ancestry` and `changelog` fail on it and on every other pull request into it;
- `version` does too, where the source declares a version, which on the default branch is still the
  one just released;
- no next release can be prepared.

The workflows on merge-back's own pull request may wait to be approved rather than run, as the pull
request's body says too.\
GitHub holds the runs of a pull request opened with `GITHUB_TOKEN` until someone with write access
approves them.

### `check-workflow` needs `workflow_dispatch`, and `GITHUB_TOKEN` needs `actions: write`

`check-workflow` names the workflow that checks the default branch, by file name.\
A push made with `GITHUB_TOKEN` starts no workflow run at all, so merge-back asks for that one by
hand once the release has landed.

That workflow:

- has to list `workflow_dispatch` among its triggers: GitHub refuses to start one that does not, and
  the release has landed by then, so the run only warns;
- has to be named: left out, the run stops before anything is carried back rather than land a
  release nothing checks.

`actions: write` is not optional where `token` is left as `GITHUB_TOKEN`, and the `contents: write`
the pushes take does not stand in for it.\
Asking for a run by hand is a write to Actions, and without it the dispatch is answered 403 and the
release lands with nothing having checked it.

## release-flow/warn

[`release-flow/warn`](warn/action.yml) says on a published release that publishing it somewhere
other than GitHub did not complete, and takes that back once it has.\
Whoever has the release's files in hand looks at the release, not through the runs of a workflow.\
So a publish that went red is said where they will look: a `> [!WARNING]` at the start of the notes,
naming where the release was to go and linking the run.

It follows the step that publishes, in the same job, with `if: ${{ !cancelled() }}` so that a
failure before it does not stop it, and is handed that step's `outcome`:

| `outcome` | The notes                                     |
|-----------|-----------------------------------------------|
| `success` | lose the warning, where they carry one        |
| `failure` | gain the warning at the start                 |
| `skipped` | gain it too: a step before the publish failed |

- Anything else fails the run. That includes the empty `outcome` an id naming no step gives, which
  read as a failure would put the warning on every release.
- `outcome` rather than `conclusion`, so that a publish step allowed to fail with
  `continue-on-error` still counts as failed.
- The publish step's outcome decides, not the job's. A merge-back that failed while the publish
  completed puts no warning on the release: the release is served all the same, and the job going
  red says the rest.
- A run whose notes already say what it would say leaves them alone. Running the job again - once a
  first version uploaded by hand is approved, say - takes the warning off where the publish now
  completes, and says it once where it fails again.

The release is asked for by the repository's name, so no checkout is needed.\
The job needs `contents: write` to write the notes.\
The job under [intellij/publish](../intellij/README.md#the-job-that-publishes) shows the step after
an upload to the JetBrains Marketplace.

### How the warning is found

The warning sits between two HTML comments, `<!-- release-flow/warn -->` and
`<!-- /release-flow/warn -->`, which GitHub keeps in the notes and does not show.\
It is looked for only where `release-flow/warn` puts it: at the very start of the notes, the markers
on lines of their own around nothing but quoted lines.

- A line that starts the notes from its first column cannot stand in a code block, a list or a
  quote, so the notes need no parsing to know the warning there is this action's.
- The words between the markers do not matter: a warning written by another version of the action is
  the one taken off or replaced.
- Taking it off takes the blank line after it too, and gives the rest of the notes back with their
  line ends as they were.

### What fails the run instead

A line holding nothing but either marker anywhere else fails the run and leaves the notes as they
are, for a warning there to be taken off by hand.\
So does a warning at the start that is not closed, or that holds a line that is not quoted.

Such a line may be the warning after someone wrote above it, or an example the notes show as code,
and the action does not guess which.\
The step runs last, after the release and everything before it are done, so failing it undoes
nothing.

### The warning is the one thing the notes say that the changelog does not

A release's notes are its released section of `CHANGELOG.md` - `release-flow/draft` writes them with
`check-release notes` - so that the two cannot come to say different things.

The warning is the exception: it is the one thing release-flow writes into the notes of a release
already published, and no changelog carries it.\
A released section may not be edited, and whether a publish completed is not a change to the
project.

The warning stands until a run whose publish completes takes it off, or, where that run cannot tell
it for this action's, until it is taken off by hand.

## Where GitHub reads each workflow from

The release job and the merge-back job sit in workflows of their own, which GitHub reads from
different commits:

- One started by a dispatch runs only once its workflow file is on the default branch, and then
  takes the workflow file, and the checkout, from whichever branch it is started on.\
  That is why [the release job](#the-release-job) runs on the default branch alone: a release cut
  from anywhere else is what merge-back would carry onto it, unreviewed.
- One started by a release runs from the file as it stands in the commit the release tags.

Both have to be on the default branch before a release is cut from it.
