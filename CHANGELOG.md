# Changelog

Notable changes to this project, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — which is also the format
`check-release changelog` reads. A section that has been released is compared against the tag that
released it, so once a version has a section here, that section may not be edited again.

## [Unreleased]

### Added

- `check-release`, the rules a release has to pass, as subcommands over a repository: which version
  may be released next, whether a released changelog section still reads as it was released, whether
  every released tag is still reachable, which distribution channel a version goes to, and what a
  release writes back.
- `--source`, which says where the version a release is asked to be comes from: `gradle.properties`,
  or `tags` for a repository that is handed the version and records nothing.
- `--tag-prefix`, which says what release tags carry in front of the version, for a source that
  declares no prefix of its own.
- `check-release/action.yml`, a composite action, so a project asks for the rules rather than keeping
  a copy of them.
- A note where a tag prefix counts none of the tags a repository carries, rather than an empty list
  every later check then passes over having compared nothing.
- `release-flow/merge-back`, which carries a published release back onto the default branch by
  fast-forward, and offers a pull request where it cannot.
- `close-changelog`, which moves what is under `[Unreleased]` into a released section of its own,
  dated, the way the Gradle changelog plugin does.
- `release-flow/prepare`, which cuts the release commit onto a branch of its own: the version written
  back, `[Unreleased]` closed into a section for it, and nothing pushed.
- `section`, which prints one released section without its heading, so the release notes and the
  changelog cannot come to say different things.
- `release-flow/draft`, which pushes the release branch and drafts the release from it once the build
  has succeeded.
- `intellij`, the first ecosystem: building and signing a JetBrains plugin between prepare and draft,
  and publishing it to the Marketplace once the release is accepted.

[Unreleased]: https://github.com/loplex/release-ci/commits/main
