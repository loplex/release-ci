# check-release

`check-release` checks a repository before and after a release.\
It reads three things:

- the tags of the repository;
- `CHANGELOG.md` of the same repository;
- the version the release is asked to be, from the source the call names.

The first two work the same in every project.\
The third depends on the kind of project, as
[Where the version comes from](#where-the-version-comes-from) describes.

## Subcommands

`check-release.py` has one subcommand per question a release asks:

| Subcommand        | What it does                                                                                                |
|-------------------|-------------------------------------------------------------------------------------------------------------|
| `version`         | checks whether the [candidate version](#where-the-version-comes-from) may be released next                  |
| `next`            | prints the version after a released one, with the source's [marker](#-snapshot-belongs-to-gradleproperties) |
| `changelog`       | checks that every released section of `CHANGELOG.md` still reads as its tag has it                          |
| `ancestry`        | checks that every release tag is still reachable from the current history                                   |
| `prefix`          | prints what release tags carry in front of the version                                                      |
| `channel`         | prints the [distribution channel](#the-channel-a-version-goes-to) of a version                              |
| `set-version`     | writes a version into the file the source declares it in                                                    |
| `close-changelog` | moves what is under `[Unreleased]` into a dated section for the version being released                      |
| `notes`           | prints the text of one released section, which is what its release notes say                               |

The options go after the subcommand name, and a subcommand refuses an option it never reads:

- `--version-source` and `--tag-prefix`: `version`, `next`, `changelog`, `ancestry`, `prefix` and
  `close-changelog`.\
  `close-changelog` reads them only with `--repository-url`, and takes them either way.
- `--version-source` alone: `set-version`.
- Neither: `notes` and `channel`.

The composite action [below](#using-check-release-from-another-repository) runs:

- `version`, `changelog` and `ancestry`, whichever its `checks` input names;
- `channel`, after a `version` check that passed.

## Versions

A version is a semantic version: `1.0.0`, `1.0.0-rc.1`, `1.0.0-eap-2`, `1.0.0+dfsg1`.\
The grammar is the one SemVer 2.0.0 defines.\
A leading zero or an empty identifier is refused, because SemVer gives it no order.

### What `version` refuses

`version` refuses a candidate that:

- is not a semantic version;
- still carries the [`-SNAPSHOT` marker](#-snapshot-belongs-to-gradleproperties);
- does not come after the last release it is offered next to:
  - a final release has to come after the last final release;
  - a pre-release has to come after the highest release of any kind;
- has a core that is not one step past the last final release: after `0.2.0`, the next one is
  `0.2.1`, `0.3.0` or `1.0.0`, or a pre-release of one of them;
- moves less than [`[Unreleased]` asks for](#what-unreleased-asks-of-the-version).

A stable hotfix such as `0.2.1` may therefore go out while `0.3.0-beta.1` is open, from a branch
whose changelog does not hold the beta's section.\
Where it does, the beta's entries ask for a step as
[`[Unreleased]`'s do](#what-unreleased-asks-of-the-version).\
Where only pre-releases exist, the next version stays in their core: after `0.2.0-rc.1`, a later
pre-release of `0.2.0`, or `0.2.0` itself.\
With nothing released yet, any valid version may be the first.

### Build metadata does not order releases

Build metadata is the part after `+`, as in `1.0.0+dfsg1`.\
SemVer says it plays no part in ordering:

> Build metadata MUST be ignored when determining version precedence. Thus two versions that differ
> only in the build metadata, have the same precedence.

So `1.0.0+b` does not come after `1.0.0+a`, and releasing it after `1.0.0+a` is refused.\
The refusal says the two differ only in build metadata.
It does not say "does not come after", which would look like a bug for a version made later.

A project that needs `+dfsg1` to count as an upgrade needs an ordering SemVer does not define.\
That rule would go into `precedence()` in [`rules/versions.py`](rules/versions.py).

### The channel a version goes to

The channel is the first identifier of the pre-release suffix, or `default` for a final release.

- Identifiers are separated by dots.
- A hyphen is an ordinary character inside an identifier.
- Build metadata plays no part.

| Version       | Channel                 |
|---------------|-------------------------|
| `1.0.0`       | `default`               |
| `1.0.0-rc.1`  | `rc`                    |
| `1.0.0-eap-2` | `eap-2`, one of its own |
| `1.0.0-eap.2` | `eap`                   |

`channel` takes the version without the tag prefix: `0.3.0-beta.1`, not `v0.3.0-beta.1`.

## The changelog

`CHANGELOG.md` is read in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/):

- a `## [Unreleased]` section on top;
- a `## [<version>]` section for each release below it.

`close-changelog`, which `release-flow/prepare` runs, turns `[Unreleased]` into the section of the
release.
It refuses:

- a file with no `[Unreleased]` section;
- a version that already has a section;
- an empty `[Unreleased]`, unless the release is a final one with pre-releases to take in.

A final release takes into its section the entries of every pre-release since the final release
before it, by SemVer's order.\
That includes an abandoned pre-release of another version: `1.0.0` after `0.3.0-beta.1` takes that
beta's entries in.\
A pre-release takes in nothing but its own entries.

The `changelog` check compares every released section with the copy in its release tag.

- `[Unreleased]` is not compared.
- A release tagged before its section existed has nothing to compare, and is listed as not
  compared.
- A section that is missing because its tag is not on the current history is reported as such:
  the release has not reached this branch yet.

### What `[Unreleased]` asks of the version

The entries under `[Unreleased]` say how far the release has to move past the last final release.\
So do the entries of every pre-release above the last final release whose section the changelog
holds.\
The rule is [SemVer's rules 6 to 8](https://semver.org/#semantic-versioning-specification-semver),
applied to Keep a Changelog's kinds of change:

| Under `[Unreleased]`                                   | The release is at least              |
|--------------------------------------------------------|--------------------------------------|
| `### Added`, `### Changed`, `### Deprecated`           | a minor                              |
| `### Removed`, or an entry marked `**BREAKING**`       | a major, and a minor while below 1.0 |
| `### Fixed`, `### Security`, a group of any other name | a patch                              |

- `version` refuses a candidate that moves less, and names the group that asks for more.
- Under `tags` with no version given, the default is the version after the highest release.\
  Where `[Unreleased]` asks for more, it is the smallest version that satisfies it.
- An entry starting with `**BREAKING**` marks a change that breaks something a caller relied on,
  under whichever group it stands.\
  This is a convention of this repository: Keep a Changelog has no such marker.\
  A group such as release-please's `### ⚠ BREAKING CHANGES` counts as a group of any other name.
- Below 1.0, a breaking change moves the minor, as Cargo and npm read `^0.y`.\
  SemVer's rule 4 promises nothing about `0.y.z`, and 1.0 is a step taken on purpose.
- A group with a name Keep a Changelog does not use, such as `### Documentation`, is named in a
  note on stderr.\
  A feature filed under a misspelled `### Add` can then still be seen.
- An empty group asks for nothing, and HTML comments are ignored.
- An entry under no group at all is refused, because nothing says what kind of change it is.
- A repository with no `CHANGELOG.md`, or no `[Unreleased]` section in it, is asked for no more
  than a patch, and told so on stderr.

## Using check-release from another repository

[`check-release/action.yml`](action.yml) is a composite action.\
A project uses it instead of keeping its own copy of the rules:

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
          version-source: gradle.properties
          checks: version changelog ancestry
```

The [`action.yml`](action.yml) describes every input and output.\
The sections below explain the choices in this example.

### `branches` keeps the workflow off tags

Publishing a release creates its tag.\
A workflow on `push` with no filter runs for that tag too, with nothing to check.

If it does run on the release commit, `version` can still pass there:

- The commit a release tags still declares the version it released.
- Where the source declares a version and no `version` input is given, `version` sees that the tag
  points at this commit, notes it, and passes.
- A version given in the `version` input is still checked.

### `checks` names `version`, which its default leaves out

The default of `checks` is `changelog ancestry`.\
The example adds `version`.

- Every check named runs, even after one of them fails.
- The step fails at the end if any check failed, and names each one that did.
- The [outputs](#outputs) are written whenever `version` passed, even if another check failed.

### `<tag>` is a release tag

`<tag>` is one of this repository's release tags, as in every example here.\
[Pinning](../README.md#pinning) says what other refs give you.\
What the action needs on the runner is under
[What an action needs of the runner](../README.md#what-an-action-needs-of-the-runner).

### `tag-prefix` is left out where the source declares it

The example has no `tag-prefix`, because `gradle.properties` declares the prefix.\
A value given here would override the file.\
Give it where the source declares none, as with `tags`.

Where the tags have no prefix at all, give `tag-prefix: ^none`.

- An empty value cannot mean that: GitHub passes a missing input as an empty string too.
- `^none` can never be a real prefix, because git refuses `^` in a tag name.

[No default tag prefix, on purpose](#no-default-tag-prefix-on-purpose) explains why there is no
default.

### `fetch-depth: 0` is required

A shallow checkout has neither the history `ancestry` reads nor the tags every check counts from.\
The checks then find nothing to compare, and pass.\
The one exception is `version` under `tags` with no version given: it fails, because it finds no
release to count from.

### Outputs

When `version` is among the checks and passes, the action sets two outputs:

- `steps.<id>.outputs.version`: the version that may be released, without the tag prefix and
  without `-SNAPSHOT`.\
  For `0.2.0-SNAPSHOT` in `gradle.properties` it is `0.2.0`.
- `steps.<id>.outputs.channel`: the [channel](#the-channel-a-version-goes-to) of that version.\
  `default` for a final release, otherwise the first identifier of its pre-release suffix.

### The `version` input

The `version` input gives the `version` check a version to check, such as one from a dispatch form.\
It replaces:

- under `gradle.properties`, the version the file declares;
- under `tags`, the default: the version after the highest release, or a later one where
  `[Unreleased]` asks for more.

How to spell it under each source is under
[Where the version comes from](#where-the-version-comes-from).

## Where the version comes from

Every call that reads the source names it, with `--version-source` or the action's
`version-source` input.\
There is no default, because a wrong guess would pass silently.

Two sources exist:

| `--version-source`  | Where the candidate version comes from                                                         | After a release           |
|---------------------|------------------------------------------------------------------------------------------------|---------------------------|
| `gradle.properties` | the `version` line of the file, or `--version`; a `-SNAPSHOT` at its end is dropped            | the next one written back |
| `tags`              | `--version`, or the version after the highest release, moved further where `[Unreleased]` asks | nothing written           |

The candidate version is the version `check-release version` checks against the rules.

### `-SNAPSHOT` belongs to `gradle.properties`

`-SNAPSHOT` is how Gradle and Maven mark a version that is not released yet.

- A release drops it from the end of the version.\
  This holds whether the version comes from the file, from `--version`, or from the `version` input
  of `check-release` or `release-flow/prepare`.
- A version given by hand may also leave it out.
- A version that still carries `SNAPSHOT` after that is refused, whatever the source:
  `1.0.0-SNAPSHOT-SNAPSHOT`, `1.0.0-SNAPSHOT+b`, or `1.0.0-SNAPSHOT` given under `tags`.
- `tags` has no marker: the version after a release is worked out bare, and a source that has a
  marker adds it.

### The first release under `tags` needs a version

Under `tags`, with nothing released yet, there is no release to count from.\
Give the first version with `--version`, or with the `version` input of `check-release` or
`release-flow/prepare`.

### `set-version` under `tags` exits with 3

Under `tags` there is no file to write a version to.\
`set-version` then exits with status 3 instead of reporting a success.\
Its other refusals exit with 1, or 2 for a command line it cannot parse.\
So a caller can tell "nothing to write to" from a failed write.

### The tag prefix

`--tag-prefix` says what release tags carry in front of the version: `v` for `v0.1.0`.

- Under `gradle.properties`, unless `--tag-prefix` is given, the file declares it in a `tagPrefix`
  line, which it then has to have.\
  The two lines it needs are `version = 0.2.0-SNAPSHOT` and `tagPrefix = v`,
  or `tagPrefix =` where the tags have no prefix.\
  `--tag-prefix`, where given, overrides the file.
- Under `tags`, nothing declares it, so it has to be given.\
  `--tag-prefix ''` says the tags have no prefix, and so does `--tag-prefix '^none'`.
- Every action that takes `version-source` takes the prefix as its `tag-prefix` input, with
  `^none` for no prefix, as [above](#tag-prefix-is-left-out-where-the-source-declares-it).

#### No default tag prefix, on purpose

A wrong default would pass silently.\
A repository that tags bare versions, read as if it tagged `v*`, has no releases at all.\
Every check then passes, having compared nothing.\
The one exception is `version` under `tags` with no version given, which fails with no release to
count from.\
A caller that wants a default writes it in its own workflow, where its readers can see it.

### Adding a source

Each source is an adapter in [`check-release/rules/sources.py`](rules/sources.py).\
The rules know none of them by name.

Adding `package.json`, `pyproject.toml` or `Cargo.toml` means one more adapter there:

- filed under the name `--version-source` gives it;
- its file declaring the tag prefix next to the version, as `gradle.properties` declares
  `tagPrefix`.

The rules need no change, unless the new source marks a version in progress with something other
than a `-SNAPSHOT` suffix.

A plain `VERSION` file has no room for a tag prefix.\
check-release.py asks every source with a file for one, unless `--tag-prefix` is given, so such a
file takes more than an adapter.

The top of [`rules/sources.py`](rules/sources.py) lists what an adapter has to answer, its file and
tag prefix included.\
[`check-release/tests/test_sources.py`](tests/test_sources.py) holds every adapter to that list.\
It also needs a sample file for each adapter that declares a version.
