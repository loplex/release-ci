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

It reads the tags and `CHANGELOG.md` out of the repository it is asked about, and takes the version a
release is asked to be from whichever source the invocation names. The first two are the same
everywhere; the third is what a project type decides, and
[Where the version comes from](#where-the-version-comes-from) says where the rules stop and the source begins.

## What is planned

| Directory       | Will hold                                                                  |
|-----------------|----------------------------------------------------------------------------|
| `release-flow`  | How a GitHub release is cut, drafted before it is tagged, and carried back |
| `intellij`      | How a JetBrains plugin is built, signed and published to the Marketplace   |

## check-release

`check-release.py` holds, as separate subcommands, what a release asks of a repository and does with it:

| Subcommand    | What for                                                                                           |
|---------------|----------------------------------------------------------------------------------------------------|
| `version`     | whether the [candidate version](#where-the-version-comes-from) may be released, given the releases |
| `next`        | the version that follows a released one, with the source's [marker](#where-the-version-comes-from) |
| `changelog`   | whether every released section of `CHANGELOG.md` still reads the way its tag has it                |
| `ancestry`    | whether every released tag is still reachable from this history                                    |
| `prefix`      | what release tags are called here                                                                  |
| `channel`     | the distribution channel a version goes to                                                         |
| `set-version` | write a version where it is declared: the one released, then the next                              |

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
repository to release, as [`test_sources.py`](check-release/test_sources.py) does the adapters for
where the version comes from; the helpers beside them that face git get one built for the purpose:

```
python3 -m unittest discover -s check-release
```

The same command runs on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml).

## Where the version comes from

Every invocation says so, with `--source`, because the wrong guess is silent. Two are implemented,
and they differ in more than a filename:

| `--source`          | The version a release is asked to be                                              | After a release           |
|---------------------|-----------------------------------------------------------------------------------|---------------------------|
| `gradle.properties` | read from the file or handed in with `--version`, a `-SNAPSHOT` ending it dropped | the next one written back |
| `tags`              | handed in with `--version`, or the version after the highest release              | nothing to write          |

The version a release is asked to be, whichever way it is found, is the candidate version: what
`check-release version` holds to the rules.

Carrying `-SNAPSHOT` belongs to `gradle.properties`: it is Gradle's and Maven's way of saying "not
released yet", and a release takes it off the end of the version, whether the file declares it or
`--version` hands it in; a version handed in may also leave it out. A version still carrying it
after that - `1.0.0-SNAPSHOT-SNAPSHOT`, `1.0.0-SNAPSHOT+b`, or `1.0.0-SNAPSHOT` handed to `tags` -
is refused whatever the source. A repository whose version lives only in its tags has no such
state, so the version after a release is worked out bare and the source adds the marker where there
is one.

Under `tags`, with nothing released yet, there is no highest release to follow, and the first
version is named with `--version`. `set-version` under `tags` refuses rather than reporting a
success in which nothing was written, and with exit status 3 rather than 1, so that a caller can
tell "nothing to write to" from a write that failed.

`--tag-prefix` says what release tags are called. Under `gradle.properties` the file says it where
`--tag-prefix` is not given, in a `tagPrefix` line it then has to carry beside the `version` one:
`version = 0.2.0-SNAPSHOT` and `tagPrefix = v`, or `tagPrefix =` where the tags carry nothing in
front, are the two lines it needs. A source naming no file, as `tags` does, has to be told, and
`--tag-prefix ''` tells it the tags carry nothing in front. `--tag-prefix` has no default, on
purpose: a repository tagging bare versions, read as though it tagged `v*`, turns up no releases at
all, and every check over them - all but `version` under `tags` given no version, which finds no
release to count from - passes having compared nothing. A caller wanting a default declares it where
its own readers can see it.

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
