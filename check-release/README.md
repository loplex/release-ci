# check-release

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
`precedence()` in [`check-release/check-release.py`](check-release.py) is where that rule
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

[`check-release/action.yml`](action.yml) is a composite action, so a project asks for the
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

`<tag>` is one of this repository's release tags, for the reasons [What is here](../README.md#what-is-here) gives,
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
version is named with `--version`, or the `version` input of `check-release` or
`release-flow/prepare`. `set-version` under `tags` refuses rather than reporting a success in
which nothing was written, and with exit status 3 rather than 1, so that a caller can tell
"nothing to write to" from a write that failed.

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

Each source is an adapter in [`check-release/sources.py`](sources.py), and the rules
know none of them by name. Adding `package.json`, `pyproject.toml` or `Cargo.toml` means one more
adapter there, filed under the name `--source` gives it, its file carrying the tag prefix beside the
version as `gradle.properties` carries `tagPrefix`, and nothing in the rules changes unless it marks
a version being worked on other than with a `-SNAPSHOT` suffix, the one marker they know. A plain
`VERSION` file has no room for a prefix, which the rules ask of every source naming a file unless
`--tag-prefix` is given, so it takes more than an adapter. What an adapter has to answer, its file
and the tag prefix included, is listed at the top of [`sources.py`](sources.py);
[`check-release/test_sources.py`](test_sources.py) holds every adapter to it, and asks
one that declares a version for a file to try it on.
