# Changelog

Notable changes to this project, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) - which is also the format
`check-release changelog` reads. A section that has been released is compared against the tag that
released it, so once a version has a section here, that section may not be edited again.

## [Unreleased]

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
