# release-ci

The release rules a project would otherwise carry its own copy of, and the pipeline that runs them.
Here today: the guards a release has to pass. [What is here](#what-is-here) says where, and
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

It reads three things out of the repository it is asked about: the tags, `CHANGELOG.md`, and the
file the version is declared in. The first two are the same everywhere; the third is what a project
type decides, and [check-release](#check-release) says where that line is drawn.

## What is planned

| Directory       | Will hold                                                                  |
|-----------------|----------------------------------------------------------------------------|
| `release-flow`  | How a GitHub release is cut, drafted before it is tagged, and carried back |
| `intellij`      | How a JetBrains plugin is built, signed and published to the Marketplace   |

## check-release

`check-release.py` holds, as separate subcommands, what a release asks of a repository and does with it:

| Subcommand    | What for                                                                            |
|---------------|-------------------------------------------------------------------------------------|
| `version`     | whether the declared version may be released, given the releases                    |
| `next`        | the version to be worked on once one is released                                    |
| `changelog`   | whether every released section of `CHANGELOG.md` still reads the way its tag has it |
| `ancestry`    | whether every released tag is still reachable from this history                     |
| `prefix`      | what release tags are called here                                                   |
| `channel`     | the distribution channel a version goes to                                          |
| `set-version` | write a version where it is declared: the one released, then the next               |

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
a `## [Unreleased]` section on top, and a `## [<version>]` section for each release below it.

The rules are plain functions over text, tags and booleans, and
[`check-release/test_check_release.py`](check-release/test_check_release.py) exercises them without a
repository to release; the helpers beside them that face git get one built for the purpose:

```
python3 -m unittest discover -s check-release
```

The same command runs on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml).

Where a version is declared, and how it is written back, is the one thing here that a project type
decides. Today that is `gradle.properties`; the reading and the writing sit in functions of their
own so that another file format is another adapter rather than another rule.
