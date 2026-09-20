# release-ci

The release rules a project would otherwise carry its own copy of, and in time the pipeline that runs
them. Here today: the guards a release has to pass. [What is here](#what-is-here) places
draft-before-tag releases and per-ecosystem publishing, which are planned.

## What is here

| Directory       | Holds                                                                   |
|-----------------|-------------------------------------------------------------------------|
| `check-release` | What a release has to be true of, asked as properties over a repository |

It reads three things out of the repository it is asked about: the tags, `CHANGELOG.md`, and the
file the version is declared in. The first two are the same everywhere; the third is what a project
type decides, and [check-release](#check-release) says where that line is drawn.

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
| `next`        | the version to be worked on once one is released                  |
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

Where a version is declared, and how it is written back, is the one thing here that a project type
decides. Today that is `gradle.properties`; the reading and the writing sit in functions of their
own so that another file format is another adapter rather than another rule.
