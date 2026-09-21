# release-ci

The release rules a project would otherwise carry its own copy of, and the pipeline that runs them.
Here today: the guards a release has to pass, cutting the release commit onto a branch of its own, and
carrying a published release back onto the default branch. [What is here](#what-is-here) places
drafting a release before its tag exists, and per-ecosystem publishing, which are planned.

## What is here

| Directory       | Holds                                                                    |
|-----------------|--------------------------------------------------------------------------|
| `check-release` | What a release has to be true of, asked as properties over a repository  |
| `release-flow`  | The shape a release is cut in and carried back, as steps over a workflow |

`check-release` reads the tags and `CHANGELOG.md` out of the repository it is asked about, and takes the
version a release is asked to be from whichever source that project declares. The first two are the same
everywhere; the third is what a project type decides, and [check-release](#check-release) says where
that line is drawn.

One more directory is planned and named ahead of time, so that what goes where is decided by the boundary
rather than by whichever file is being written: one per ecosystem, `intellij` first, for building, signing
and publishing. A directory whose content is ecosystem-free carries a name that says nothing about an
ecosystem; an adapter's name says which one it is.

## check-release

`check-release.py` answers, as separate subcommands, the questions a release has to pass:

| Subcommand        | Asks                                                              |
|-------------------|-------------------------------------------------------------------|
| `version`         | whether the declared version may be released, given every tag     |
| `next`            | the version that follows a released one                           |
| `changelog`       | whether every released section still reads the way its tag has it |
| `ancestry`        | whether every released tag is still reachable from this history   |
| `prefix`          | what release tags are called here                                 |
| `channel`         | the distribution channel a version goes to                        |
| `set-version`     | write the declared version, which is what a release does          |
| `close-changelog` | move `[Unreleased]` into a section of its own, dated              |

A version here is a semantic version: `1.0.0`, `1.0.0-rc.1`, `1.0.0-eap-2`, `1.0.0+dfsg1`. The
grammar is SemVer 2.0.0's own, so a leading zero and an empty identifier are refused rather than
ordered by rules nobody wrote down.

Build metadata - the `+` part, the shape Debian packaging reaches for - is taken, and the spec's
rule about it is taken with it: "Build metadata MUST be ignored when determining version precedence.
Thus two versions that differ only in the build metadata, have the same precedence."

That has one consequence worth meeting here rather than in a red run. `1.0.0+b` does not outrank
`1.0.0+a`, so releasing one after the other is refused - not because the `+` is unwelcome, but
because whoever compares versions would be offered nothing by it. `version` says that in those
words rather than as "does not come after", which about a version that plainly came after would
read as a bug. A project needing `+dfsg1` to count as an upgrade needs an ordering SemVer does not
define, and `precedence` is where that rule would go.

The rules are plain functions over text, tags and booleans, and `test_check_release.py` exercises
them without a repository to release; the helpers beside them that face git get one built for the
purpose. The suites beside it build what each step needs - a repository, a bare remote, a stub for
whatever is called out:

```
python3 -m unittest discover -s check-release
python3 -m unittest discover -s release-flow
```

Both run on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml). The second builds a bare repository to push
against and puts a stub `gh` on the path, so that a refused fast-forward is a real refusal and nothing is
sent anywhere.

## Using it from another repository

`check-release/action.yml` is a composite action, so a project asks for the rules rather than keeping a
copy of them:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
- uses: loplex/release-ci/check-release@<tag>
  id: release
  with:
    source: gradle.properties
    checks: version changelog ancestry
```

Pin to a release tag rather than to a branch, and keep the tag: a consumer pinned to a commit no tag
reaches will fail to check out, GitHub keeping no promises about unreachable objects. This repository's
own workflow uses `./check-release`, being the one repository the action already sits in.

`tag-prefix` is left out above because `gradle.properties` declares it, in `tagPrefix`. Giving it to
the action answers over the top of that: a repository tagging bare versions, told `v`, finds no
releases at all and every check passes having compared nothing. Give it where the source declares
nothing, which `tags` does not.

A repository whose tags carry no prefix at all says `tag-prefix: ^none` there. An empty value will
not do, GitHub handing over an input left out and an input set to nothing as the same empty string,
and `^none` cannot be mistaken for a real prefix because git refuses `^` in a ref name.

`fetch-depth: 0` is not optional. A shallow checkout has neither the history `ancestry` reads nor the
tags every check counts from, so the checks find nothing and pass, which is the one outcome worth
fearing here.

Where `version` is among the checks, the action answers with `steps.<id>.outputs.version`, the version
that may be released, and `outputs.channel`, where it is published.

## Where the version comes from

Every invocation says so, with `--source`, because the wrong guess is silent. Two are implemented,
and they differ in more than a filename:

| `--source`          | The version a release is asked to be                                 | After a release           |
|---------------------|----------------------------------------------------------------------|---------------------------|
| `gradle.properties` | read from the file, carrying `-SNAPSHOT`, which is dropped           | the next one written back |
| `tags`              | handed in with `--version`, or the version after the highest release | nothing to write          |

`-SNAPSHOT` belongs to the first of those, not to releasing: it is Gradle's and Maven's way of
saying "not released yet". A repository consumed by tag alone has no such state, so `version_after`
answers a bare version and the source adds the marker where there is one. `set-version` under
`tags` refuses rather than reporting a success in which nothing was written, and with exit status 3
rather than 1, so that a caller can tell "nothing to write to" from a write that failed.

`--tag-prefix` says what release tags are called. `gradle.properties` declares it in the file, as
`tagPrefix`; any other source has to be told. There is no default here on purpose - a repository
tagging bare versions, read as though it tagged `v*`, turns up no releases at all and every check
over them passes having compared nothing. A caller wanting a default declares it where its own
readers can see it.

Adding `package.json`, `pyproject.toml`, `Cargo.toml` or a plain `VERSION` file means a branch in
`declares_a_version`, `marker_of` and `prefix_from`, which sit together for that reason, and a reader
and a writer for that file. `version` and `set-version` call Gradle's outright, it being the one source
that declares a version, so they are where the choice between the two is then made.

## release-flow

Two actions, one for each end of a release. Between them sits whatever the ecosystem does - building,
signing, drafting the release with the archive - which is why they are two.

`release-flow/prepare` cuts the release commit onto a branch of its own. The rules are asked first and
nothing is written where they say no; then the declared version has its marker dropped and is written
back, `[Unreleased]` is closed into a section for it, and the one resulting commit is left on
`release/<version>` with the workspace on it. Nothing is pushed: the build runs from that commit next,
and a build that fails should leave neither a branch nor a draft on the remote. Pushing comes after the
build, with the draft.

```yaml
jobs:
  prepare:
    runs-on: ubuntu-latest
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
          repository-url: ${{ github.server_url }}/${{ github.repository }}
      # Build from the commit now checked out. Once it has succeeded, push the branch and draft the
      # release at ${{ steps.cut.outputs.tag }} with the archive attached; the tag itself does not
      # exist until the draft is published.
```

`release-flow/merge-back` carries a published release back onto the default branch. It opens the next
version being worked on, takes in whatever landed while the draft waited, and moves the default branch
onto the release commit by **fast-forward**:

```yaml
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
```

The fast-forward is the point, and so is the push not being forced. A release tag names the commit the
archive was built and signed from; *Squash and merge* and *Rebase and merge* replace that commit with a
copy, which takes the tag off the default branch's history and turns `ancestry` red for every commit
after it. A merge commit keeps the tag reachable, but only through its second parent, off the default
branch's first-parent line. A push moves the default branch onto the release branch as it stands, so
the release commit stays on that line, with at most a merge of what landed meanwhile above it. Where
the default branch moved under that push, or would not merge in cleanly, git refuses and a pull request
carries the release instead - that refusal is the race being caught, not an error to push past. So does
a merge whose result the rules refuse: `changelog` and `ancestry` are asked of the merged tree before it
is pushed, because a three-way merge can put an entry added to `[Unreleased]` into the released section.

`actions: write` is not optional and is not about the contents: asking for a build run by hand is a write
to Actions, and without it the dispatch is answered 403 and the release lands with nothing having checked
it. The dispatch is there because a push made with `GITHUB_TOKEN` starts no workflow run at all.
