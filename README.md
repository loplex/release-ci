# release-ci

The release rules a project would otherwise carry its own copy of, and the pipeline that runs them.
Here today: the guards a release has to pass, cutting the release commit onto a branch of its own, and
carrying a published release back onto the default branch. [What is here](#what-is-here) says where, and
[What is planned](#what-is-planned) what is still to come.

What goes where is decided by the ecosystem boundary, not by whichever file is being written:

- A directory whose content is ecosystem-free carries a name that says nothing about an ecosystem.
- A directory for one ecosystem is named after it, and more will follow, one per ecosystem.

This repository is to be released through its own pipeline, so nothing in the ecosystem-free directories may
end up assuming one ecosystem's build.

## What is here

| Directory       | Holds                                                                   |
|-----------------|-------------------------------------------------------------------------|
| `check-release` | What a release has to be true of, asked as properties over a repository |
| `release-flow`  | How a GitHub release is cut and carried back                            |

Each action's inputs and outputs are listed in full, with what each does, in the `action.yml` beside it;
the sections below show how they fit together. Every action runs on the runner's own `python3`, 3.10 or
later; `release-flow/merge-back` needs `gh` as well, and GitHub-hosted runners carry both.

Pin an action of this repository to one of its release tags, `v` and a version, rather than to a branch
or a bare commit. A branch moves, so what runs would change under the pin; a commit that nothing reaches
any more may fail to check out, GitHub keeping no promises about unreachable objects, and a release tag is
what keeps a released commit reachable.

## What is planned

| Directory       | Will hold                                                                |
|-----------------|--------------------------------------------------------------------------|
| `release-flow`  | How a GitHub release is drafted before it is tagged                      |
| `intellij`      | How a JetBrains plugin is built, signed and published to the Marketplace |

## check-release

`check-release` reads the tags and `CHANGELOG.md` out of the repository it is asked about, and takes the
version a release is asked to be from whichever source the invocation names. The first two are the same
everywhere; the third is what a project type decides, and
[Where the version comes from](#where-the-version-comes-from) says where the rules stop and the source begins.

`check-release.py` holds, as separate subcommands, what a release asks of a repository and does with it:

| Subcommand        | What for                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------|
| `version`         | whether the [candidate version](#where-the-version-comes-from) may be released, given the releases |
| `next`            | the version that follows a released one, with the source's [marker](#where-the-version-comes-from) |
| `changelog`       | whether every released section of `CHANGELOG.md` still reads the way its tag has it                |
| `ancestry`        | whether every released tag is still reachable from this history                                    |
| `prefix`          | what release tags are called here                                                                  |
| `channel`         | the distribution channel a version goes to                                                         |
| `set-version`     | write a version where it is declared: the one released, then the next                              |
| `close-changelog` | move `[Unreleased]` into a section of its own, dated                                               |
| `notes`           | the text below one released section's heading, which is what its release notes say                 |

Of these, the composite action [below](#using-check-release-from-another-repository) runs `version`,
`changelog` and `ancestry`, whichever its `checks` input names, and `channel` after a `version` that says
yes.

A version here is a semantic version: `1.0.0`, `1.0.0-rc.1`, `1.0.0-eap-2`, `1.0.0+dfsg1`. The
grammar is SemVer 2.0.0's own, so a leading zero and an empty identifier are refused rather than
ordered by rules nobody wrote down.

Build metadata - the `+` part, the shape Debian packaging reaches for - is taken, and the spec's
rule about it is taken with it: "Build metadata MUST be ignored when determining version precedence.
Thus two versions that differ only in the build metadata, have the same precedence."

That has one consequence worth meeting here rather than in a red run. `1.0.0+b` does not outrank
`1.0.0+a`, so releasing one after the other is refused - not because the `+` is unwelcome, but because
whoever compares versions would be offered no release at all. `version` says so in those words rather
than as "does not come after", which about a version that plainly came after would read as a bug. A
project needing `+dfsg1` to count as an upgrade needs an ordering SemVer does not define, and
`precedence()` in [`check-release/check-release.py`](check-release/check-release.py) is where that rule
would go.

The channel a version goes to is the first identifier of its pre-release suffix, and `default` for a final
release: `1.0.0-rc.1` goes to `rc`. Identifiers are separated by dots and a hyphen is an ordinary character
inside one, so `1.0.0-eap-2` goes to a channel of its own, `eap-2`, where `1.0.0-eap.2` goes to `eap`. Build
metadata plays no part.

`CHANGELOG.md` is read in the shape [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) gives it:
a `## [Unreleased]` section on top, and a `## [<version>]` section for each release below it. A
release closes `[Unreleased]` into a section of its own, so there has to be something under it: an
empty one is refused, unless there are pre-releases of the version to take in: a final release takes
their entries into its own section.

## Using check-release from another repository

[`check-release/action.yml`](check-release/action.yml) is a composite action, so a project asks for the
rules rather than keeping a copy of them:

```yaml
on:
  push:
    branches: [main]
  pull_request:
  # release-flow/merge-back starts this workflow by hand, as its check-workflow, once a release has landed.
  workflow_dispatch:

jobs:
  release-rules:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: loplex/release-ci/check-release@<tag>
        id: release
        with:
          source: gradle.properties
          checks: version changelog ancestry
```

`branches` keeps the workflow off tags. Publishing a release creates its tag, and a workflow on `push`
with no filter runs for that tag too, where there is nothing to ask: the commit a release tags names the
version it released, and `version` read off the source there passes as that release, with a note saying
so, rather than refusing it as released already.

`checks` names `version` here because its default, `changelog ancestry`, leaves it out. Every check
named runs, and the step fails at the end if any of them said no, naming each one that did; the
outputs below are written all the same where `version` said yes.

`<tag>` is one of this repository's release tags, for the reasons [What is here](#what-is-here) gives,
and what the action needs of the runner is listed there as well.

`tag-prefix` is left out above because `gradle.properties` declares the prefix, and a value given here
would answer over the top of it; give it where the source declares none, as with `tags`. Where such a
source's tags carry no prefix at all, say `tag-prefix: ^none`: an empty value will not do, GitHub
handing over an input left out and an input set to nothing as the same empty string, and `^none`
cannot be mistaken for a real prefix because git refuses `^` in a ref name. Why there is no default is
under [Where the version comes from](#where-the-version-comes-from).

`fetch-depth: 0` is not optional. A shallow checkout has neither the history `ancestry` reads nor the
tags every check counts from, so the checks find nothing and pass having compared nothing, which is the
one outcome worth fearing here. Only `version` under `tags`, handed no version, fails instead: it finds
no release to count from.

Where `version` is among the checks and says yes, the action answers with
`steps.<id>.outputs.version`, the version that may be released, bare under either source - `0.2.0` for
a `0.2.0-SNAPSHOT` in `gradle.properties` - and `steps.<id>.outputs.channel`, the channel that version
goes to by the rule under [check-release](#check-release): `default` for a final release, the first
identifier of its pre-release suffix otherwise.

The `version` input hands the `version` check a version of its own - a dispatch input, say - in
place of the one the source declares, or under `tags` the one after the highest release; how one
is spelled under each source is under [Where the version comes
from](#where-the-version-comes-from).

## Where the version comes from

Every invocation names its source, with `--source` or an action's `source` input, because the
wrong guess is silent. Two are implemented, and they differ in more than a filename:

| `--source`          | The version a release is asked to be                                              | After a release           |
|---------------------|-----------------------------------------------------------------------------------|---------------------------|
| `gradle.properties` | read from the file or handed in with `--version`, a `-SNAPSHOT` ending it dropped | the next one written back |
| `tags`              | handed in with `--version`, or the version after the highest release              | nothing to write          |

The version a release is asked to be, whichever way it is found, is the candidate version: what
`check-release version` holds to the rules.

Carrying `-SNAPSHOT` belongs to `gradle.properties`: it is Gradle's and Maven's way of saying "not
released yet", and a release takes it off the end of the version, whether the file declares it or
`--version`, or the `version` input of `check-release` or `release-flow/prepare`, hands it in; a
version handed in may also leave it out. A version still carrying it after that -
`1.0.0-SNAPSHOT-SNAPSHOT`, `1.0.0-SNAPSHOT+b`, or `1.0.0-SNAPSHOT` handed to `tags` - is refused
whatever the source. A repository whose version lives only in its tags has no such state, so the
version after a release is worked out bare and the source adds the marker where there is one.

Under `tags`, with nothing released yet, there is no highest release to follow, and the first
version is named with `--version`, or the `version` input of either action. `set-version` under
`tags` refuses rather than reporting a success in which nothing was written, and with exit status
3 rather than 1, so that a caller can tell "nothing to write to" from a write that failed.

`--tag-prefix` says what release tags are called. Under `gradle.properties` the file says it where
`--tag-prefix` is not given, in a `tagPrefix` line it then has to carry beside the `version` one:
`version = 0.2.0-SNAPSHOT` and `tagPrefix = v`, or `tagPrefix =` where the tags carry nothing in
front, are the two lines it needs. A source naming no file, as `tags` does, has to be told, and
`--tag-prefix ''` tells it the tags carry nothing in front. `--tag-prefix` has no default, on purpose:
a repository tagging bare versions, read as though it tagged `v*`, turns up no releases at all, and
every check over them - all but `version` under `tags` given no version, which finds no release to
count from - passes having compared nothing. A caller wanting a default declares it where its own
readers can see it. Every action taking `source` takes the prefix as its `tag-prefix` input, `^none`
saying the tags carry none, as [above](#using-check-release-from-another-repository).

Each source is an adapter in [`check-release/sources.py`](check-release/sources.py), and the rules
know none of them by name. Adding `package.json`, `pyproject.toml` or `Cargo.toml` means one more
adapter there, filed under the name `--source` gives it, its file carrying the tag prefix beside the
version as `gradle.properties` carries `tagPrefix`, and nothing in the rules changes unless it marks
a version being worked on other than with a `-SNAPSHOT` suffix, the one marker they know. A plain
`VERSION` file has no room for a prefix, which the rules ask of every source naming a file unless
`--tag-prefix` is given, so it takes more than an adapter. What an adapter has to answer, its file
and the tag prefix included, is listed at the top of [`sources.py`](check-release/sources.py);
[`check-release/test_sources.py`](check-release/test_sources.py) holds every adapter to it, and asks
one that declares a version for a file to try it on.

## release-flow

Two actions so far, one for each end of a release, because between them sits making the artifact - the
ecosystem's to say how - and drafting the release with it, which is planned.

Every action in release-flow takes `source` and `tag-prefix` as [check-release's
action](#using-check-release-from-another-repository) does, `^none` included, runs after a checkout
with `fetch-depth: 0`, and is pinned the way [What is here](#what-is-here) says, which also lists
what each needs of the runner.

### release-flow/prepare

[`release-flow/prepare`](release-flow/prepare/action.yml) cuts the release commit onto a branch of its
own. The rules are asked first - `changelog`, `ancestry` and `version`, all three - and nothing is
written where one says no, nor where `[Unreleased]` has nothing to release, as
[check-release](#check-release) says; then `[Unreleased]` is closed into a section for the version
being released, that version is written back where the source declares one, and the one resulting
commit is left on `release/<version>` with the workspace on it. Nothing is pushed: the build runs from
that commit next, and a build that fails should leave neither a branch nor a draft on the remote.
Pushing comes after the build, with the draft. `release-flow/prepare` writes nothing outside the
workspace and asks for no permissions of its own. The version comes from the source, or from the
`version` input, as [Where the version comes from](#where-the-version-comes-from) says for each. Given
a `repository-url`, `release-flow/prepare` also writes the link definitions of the changelog's versions
afresh, pointing into the repository; any other definition stays.

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
      # Build from the commit now checked out. Once it has succeeded, push the branch and draft the
      # release at ${{ steps.cut.outputs.tag }} with the archive attached; the tag itself does not
      # exist until the draft is published.
```

### release-flow/merge-back

[`release-flow/merge-back`](release-flow/merge-back/action.yml) carries a published release back onto the
default branch. It opens the next version being worked on where the source declares one, takes in
whatever landed since the release was cut, and moves the default branch onto the release branch -
`release/<version>`, named after the tag's version: the release commit and whatever it takes on above it -
with a **fast-forward** push:

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

The fast-forward is the point, and so is that push not being forced. A release tag names the commit the
release was made from; *Squash and merge* and *Rebase and merge* replace that commit with a copy, which
takes the tag off the default branch's history and turns `ancestry` red for every commit after it. A
merge commit keeps the tag reachable, but only through its second parent, off the default branch's
first-parent line, which is why merge-back pushes rather than opening a pull request. A push moves the
default branch onto the release branch as it stands, so the release commit stays on that line, with at
most the commit opening the next version and a merge of what landed meanwhile above it. Where what
landed meanwhile would not merge in cleanly, the merge is undone and a pull request carries the release
instead. Where the default branch moved under that push, git refuses it, and a pull request carries the
release all the same - that refusal is a race with another push being caught, not an error to push past.
A merge whose result the rules refuse goes to a pull request too: `changelog` and `ancestry` are asked
of the merged tree before it is pushed, because a three-way merge can put an entry added to
`[Unreleased]` into the released section. And a default branch that takes no push from the credential
`actions/checkout` left in the workspace - a protected one requiring pull requests, say - sends every
release to one. That credential is `GITHUB_TOKEN` unless the checkout is given a `token` of its own;
merge-back's own `token` does not push.

That pull request is opened with the action's `token`, `GITHUB_TOKEN` unless it is set, and opened with
`GITHUB_TOKEN` it takes more than the job's `pull-requests: write`: the repository has to allow it,
with *Allow GitHub Actions to create and approve pull requests* under Settings > Actions > General. A
new personal repository has it off, and one in an organization takes whatever the organization says.
Merging it with a merge commit has to be allowed as well, under Settings > General > Pull Requests; and
a default branch whose protection requires a linear history takes neither that merge nor merge-back's
own push, once that push carries a merge of what landed meanwhile.

The merge-back step succeeds whether it landed the release or opened a pull request for it, and `landed`
says which: `true` where the release commit is on the default branch - carried there by this run, or
found there by a run repeated after the release landed, whichever way it landed - and `false` where a
pull request carries it instead, opened by this run or by an earlier one and still open. A step that
failed may leave `landed` unset. A run repeated while that pull request is still open tries to land the
release again: where it now can, it does, with `landed` as `true`, and GitHub marks the pull request
[merged](https://docs.github.com/en/pull-requests/reference/pull-request-merges), its head being on the
default branch; where it still cannot, the pull request goes on carrying it. The run that lands the
release deletes the release branch, and a deletion that fails - a rule over the branch forbidding it,
say - only warns; where a pull request carries the release from that branch instead, the branch is left
to whoever merges it, and a run that cannot push that branch, or cannot open the pull request, fails.

Merge a pull request merge-back opens with a merge commit, as the pull request's body says: the tag then
stays reachable, which is all `ancestry` asks, where *Squash and merge* and *Rebase and merge* take it
off the history. Until it is merged the default branch does not reach the release's tag, so `ancestry`
and `changelog` fail on it and on every other pull request into it - `version` too, where the source
declares a version, which on the default branch is still the one just released - and no next release can
be prepared. The workflows on merge-back's own pull request may wait to be approved rather than run, as
the pull request's body says too: GitHub holds the runs of a pull request opened with `GITHUB_TOKEN`
until someone with write access approves them.

`check-workflow` names the workflow that checks the default branch, by file name: a push made with
`GITHUB_TOKEN` starts no workflow run at all, so merge-back asks for that one by hand once the release has
landed. It has to list `workflow_dispatch` among its triggers - GitHub refuses to start one that does not,
and the release has landed by then, so the run only warns - and it has to be named: left out, the run
stops before anything is carried back rather than land a release nothing checks. `actions: write` is not
optional where `token` is left as `GITHUB_TOKEN`, and the `contents: write` the pushes take does not stand
in for it: asking for a run by hand is a write to Actions, and without it the dispatch is answered 403 and
the release lands with nothing having checked it.

### Where GitHub reads each workflow from

The release job and the merge-back job sit in workflows of their own, which GitHub reads from different
commits. One started by a dispatch runs only once its workflow file is on the default branch, and then
takes the workflow file, and the checkout, from whichever branch it is started on - which is why the
release job under [release-flow/prepare](#release-flowprepare) runs on the default branch alone: a
release cut from anywhere else is what merge-back would carry onto it, unreviewed. One started by a
release runs from the file as it stands in the commit the release tags. Both have to be on the default
branch before a release is cut from it.

## Running the tests

The rules in `check-release` are plain functions over text, tags and booleans, and
[`test_check_release.py`](check-release/test_check_release.py) exercises them without a repository to
release, as [`test_sources.py`](check-release/test_sources.py) does the adapters for where the version
comes from; the helpers beside them that face git get one built for the purpose, and
[`test_check.py`](check-release/test_check.py) runs the action's script,
[`check.sh`](check-release/check.sh), against one. The suite in `release-flow` builds what each of its
actions needs - a repository, a bare remote to push to, so that a refused fast-forward is a real
refusal, and a stub for whatever is called out, so that nothing is sent anywhere:

```
python3 -m unittest discover -s check-release
python3 -m unittest discover -s release-flow
```

Both run on every push and pull request, in [`.github/workflows/test.yml`](.github/workflows/test.yml),
on the Python [`.python-version`](.python-version) names: they need 3.11 or later, where the actions ask
only for 3.10. The `guards` job in `test.yml` runs the rules over this repository itself, through the
action at `./check-release` - unpinned, this being the one repository it already sits in.
