# release-ci

The release rules a project would otherwise carry its own copy of, and in time the pipeline that runs
them. Here today: the guards a release has to pass. [What is here](#what-is-here) places
draft-before-tag releases and per-ecosystem publishing, which are planned.

## What is here

| Directory       | Holds                                                                   |
|-----------------|-------------------------------------------------------------------------|
| `check-release` | What a release has to be true of, asked as properties over a repository |

It reads the tags and `CHANGELOG.md` out of the repository it is asked about, and takes the version a
release is asked to be from whichever source that project declares. The first two are the same
everywhere; the third is what a project type decides, and [check-release](#check-release) says where
that line is drawn.

Two more directories are planned and named ahead of time, so that what goes where is decided by the boundary
rather than by whichever file is being written: `release-flow`, for the shape a release is cut and
carried back in, and one directory per ecosystem, `intellij` first, for building, signing and
publishing. A directory whose content is ecosystem-free carries a name that says nothing about an
ecosystem; an adapter's name says which one it is.

## check-release

`check-release.py` answers, as separate subcommands, the questions a release has to pass:

| Subcommand    | Asks                                                              |
|---------------|-------------------------------------------------------------------|
| `version`     | whether the declared version may be released, given every tag     |
| `next`        | the version that follows a released one                           |
| `changelog`   | whether every released section still reads the way its tag has it |
| `ancestry`    | whether every released tag is still reachable from this history   |
| `prefix`      | what release tags are called here                                 |
| `channel`     | the distribution channel a version goes to                        |
| `set-version` | write the declared version, which is what a release does          |

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
purpose:

```
python3 -m unittest discover -s check-release
```

The same command runs on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml).

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
