# Changelog

Notable changes to this project, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) - which is also the format
`check-release changelog` reads. A section that has been released is compared against the tag that
released it, so once a version has a section here, that section may not be edited again.

## [Unreleased]

### Changed

- **BREAKING** The `source` input of `check-release`, `release-flow/prepare` and
  `release-flow/merge-back` is now `version-source`.
  [UPGRADING.md](UPGRADING.md#the-source-input-is-now-version-source) shows the change.
- **BREAKING** `check-release.py`: `--source` is now `--version-source`.
  It and `--tag-prefix` go after the command, and a command refuses the ones it never reads.
  `channel` takes the version without the tag prefix.
  [UPGRADING.md](UPGRADING.md#from-02) shows the new calls.
- **BREAKING** `check-release version` holds the version to what waits under `[Unreleased]`, and
  under an open pre-release train whose sections the changelog holds: `### Added`, `### Changed` or
  `### Deprecated` asks for at least a minor, and `### Removed` or an entry starting with
  `**BREAKING**` for a major, or a minor below 1.0. A release that moves less is refused, and so is
  one with an entry under no `###` group. Under `tags`, left without a version, the default is the
  version after the highest release, or the least one `[Unreleased]` allows where that is further.
  A note on stderr says where `CHANGELOG.md` or its `[Unreleased]` is missing, or where a `###`
  group is not a kind Keep a Changelog names. merge-back's pull request that starts the next version
  tells whoever merges it to raise that version where the check refuses it.
- `close-changelog` takes into a final release the entries of every pre-release that SemVer orders
  below it and above the final release before it, whatever version they were for. It took in only
  the pre-releases of that version, so `1.0.0` after an abandoned `0.3.0-beta.1` left that beta's
  entries out.
- `close-changelog --repository-url` compares a final release from the final release before it,
  passing over its pre-releases, whose entries its section took in: the link of `0.3.0` after
  `0.3.0-beta.2` showed only the commits since `0.3.0-beta.2`, not the train its section took in. A
  pre-release compares from the release before it, which past a hotfix is the one before in its
  train. "Before" is SemVer's order, not the file's.

### Removed

- `release-flow/draft`: the `source` and `tag-prefix` inputs, which it no longer reads.

### Fixed

- `intellij/publish`: `attempts` and `wait` have to be whole numbers, `attempts` from 1 to 9999,
  checked before the upload.
  An `attempts` that was no number made no attempt, and the run failed as though the version was not
  served; a `wait` that was no number left the attempts with no pause between them.
- `check-release`: a glob in `checks`, such as `*`, is refused under its own name.
  It used to be expanded to the files in the workspace, and the error named those instead.
- A `tagPrefix` in `gradle.properties` holding an unpaired `\uD800`-`\uDFFF` escape is refused.
  `prefix` ended in a traceback printing it, and the other checks passed having found no release.
- A command-line argument holding a byte that does not decode is refused by name before any
  subcommand runs. `set-version` ended in a traceback, and `close-changelog` in one that left
  `CHANGELOG.md` empty.
- `set-version` and `close-changelog` write a CRLF file back with CRLF line endings. They wrote
  every line of it back as LF, so a release commit rewrote the whole file to change one line.
- A `CHANGELOG.md` heading indented by up to three spaces, or with a tab after its `#`s, is read as
  a heading, and a `###` heading closed by a run of `#`s is read without them, as CommonMark reads
  both. `close-changelog` found no indented `## [Unreleased]`, and a final release taking in its
  train listed a pre-release's indented or closed `### Added` apart from its own.

## [0.2.0] - 2026-09-29

### Added

- `release-flow/warn`, which says at the top of a published release's notes that publishing it
  somewhere other than GitHub did not complete, linking the run, and takes that back once a run
  repeated later publishes it.

## [0.1.0] - 2026-09-29

### Added

- `check-release`, the rules a release has to pass, as subcommands over a repository: which version
  may be released next, whether a released changelog section still reads as it was released, whether
  every released tag is still reachable, which distribution channel a version goes to, what release
  tags are called, which version follows a released one, and what a release writes back.
- `--source`, which says where the version a release is asked to be comes from: `gradle.properties`,
  or `tags` for a repository that declares no version: it is handed one, or takes the one after its
  highest release.
- `--tag-prefix`, which says what release tags carry in front of the version, for a source that
  declares no prefix of its own.
- `check-release/action.yml`, a composite action, so a project asks for the rules rather than keeping
  a copy of them.
- A note, on stderr, where a tag prefix counts none of the tags a repository carries: every check
  over the empty list but `version` under `tags` with no version given still passes, and the note
  says there is no release to compare against.
- `release-flow/merge-back`, which carries a published release back onto the default branch by
  fast-forward, and offers a pull request where it cannot.
- `close-changelog`, which moves what is under `[Unreleased]` into a released section of its own,
  dated, the way the Gradle changelog plugin does.
- `release-flow/prepare`, which cuts the release commit onto a branch of its own: `[Unreleased]`
  closed into a section for the version, the version written back where the source declares one, and
  nothing pushed.
- `notes`, which prints one released section without its heading, so the release notes and the
  changelog cannot come to say different things.
- `release-flow/draft`, which pushes the release branch and drafts the release from it once the build
  has succeeded.
- `intellij`, the first ecosystem: building and signing a JetBrains plugin between prepare and draft,
  and publishing it to the Marketplace once its draft is published.

[Unreleased]: https://github.com/loplex/release-ci/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/loplex/release-ci/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/loplex/release-ci/commits/v0.1.0
