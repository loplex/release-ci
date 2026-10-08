# Changelog

Notable changes to this project, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), written in the part of Markdown
`lib/main.py changelog` reads. A section that has been released is compared against the tag that
released it, so once a version has a section here, that section may not be edited again.

## [Unreleased]

### Added

- `--tag-prefix '^none'` of `lib/main.py` says the tags have no prefix, as the actions' `tag-prefix`
  input does.
- `lib/main.py notes --html` prints a released section as HTML, rendered by cmark-gfm, for where
  Markdown is not read, such as a JetBrains plugin's change notes.\
  It needs the packages in `lib/requirements.txt`.\
  With `--repository-url` and `--ref` it makes every relative link absolute, read at that tag or
  commit, since away from the repository a relative link leads nowhere.
- **BREAKING** `intellij/build` checks that the signed archive's `plugin.xml` carries the version
  in the `version` line of `gradle.properties`, and stops where it does not.\
  A build script that took its version from anywhere else passed the build and the draft, and
  failed only once the release was published, in `intellij/publish`.\
  It runs Python for that, installed as every other action now installs it, under *Changed*.
- `intellij/check`, a plugin's CI without signing: `check` and `verifyPlugin`, as `intellij/build`
  runs them before it signs, with the Plugin Verifier's report kept.
- `change-notes` on `intellij/build`: the release's section of `CHANGELOG.md`, rendered as HTML,
  reaches the build in `CHANGE_NOTES`, and the signed archive's `plugin.xml` is checked to hold it.\
  A plugin's change notes then say what its release page says, without a renderer of its own.\
  Their relative links are read at the release's tag, which the new `tag` input passes.\
  The same notes, their links read at the release commit, are uploaded as `change-notes.html`, a
  page to open before the draft is published.
- `skip-unreadable-releases` on `check-release`, `release-flow/prepare` and
  `release-flow/merge-back`, and `lib/main.py changelog --skip-unreadable-releases`: the `changelog`
  check names as not compared a release whose tag holds a line of `CHANGELOG.md` it does not read,
  instead of failing.\
  Where that line stands inside the release's own section, a tree without that section still fails.
- `release-flow/merge-back` says in a notice when the release it lands merged in commits that landed
  on the default branch while the release was out, and how many.\
  The run was green with nothing to tell such a landing from a plain fast-forward, though it puts a
  merge on the default branch's history.

### Changed

- **BREAKING** Every action that runs Python installs the version this repository's
  `.python-version` names with `actions/setup-python`, leaving the job's own `python3` as it was.\
  They ran on the runner's `python3`, which had to be 3.10 or later; below that they failed with a
  traceback.\
  In a job with a `container:`, that Python is built for the runner's system, not the image's, and
  the actions are not tried there.\
  A self-hosted runner needs a system `actions/setup-python` publishes a build for.\
  [UPGRADING.md](UPGRADING.md#actions-that-run-python-install-their-own) shows what that asks of a
  job.
- **BREAKING** The `source` input of `check-release`, `release-flow/prepare` and
  `release-flow/merge-back` is now `version-source`.\
  [UPGRADING.md](UPGRADING.md#the-source-input-is-now-version-source) shows the change.
- **BREAKING** `check-release/check-release.py` is now `lib/main.py`, beside the rules it runs.\
  Its `--source` is now `--version-source`.\
  It and `--tag-prefix` go after the command, and a command refuses the ones it never reads.\
  `channel` takes the version without the tag prefix.\
  [UPGRADING.md](UPGRADING.md#check-releasecheck-releasepy-is-now-libmainpy) shows the new calls.
- **BREAKING** `check-release version` holds the version to what `[Unreleased]` asks for:
  - `### Added`, `### Changed` or `### Deprecated` asks for at least a minor.
  - `### Removed`, or an entry that starts with `**BREAKING**`, asks for a major, or a minor below
    1.0.
  - Under an open pre-release train, the train's sections in the changelog ask as well.
  - A release that moves less is refused, and so is one with an entry under no `###` group.
  - Under `tags`, with no version given, the default is the version after the highest release, or
    the least version `[Unreleased]` allows where that is further.
  - A note on stderr says where `CHANGELOG.md` or its `[Unreleased]` is missing, or where a `###`
    group is not a kind Keep a Changelog names.
  - merge-back's pull request that starts the next version tells whoever merges it to raise that
    version where the check refuses it.
- `close-changelog` puts into a final release the entries of every pre-release that SemVer orders
  below it and above the final release before it, whatever version they were for.\
  It took in only the pre-releases of that version: `1.0.0` after an abandoned `0.3.0-beta.1` left
  that beta's entries out.
- `close-changelog --repository-url` compares a final release from the final release before it,
  skipping the pre-releases whose entries its section took in.\
  The link of `0.3.0` after `0.3.0-beta.2` showed only the commits since `0.3.0-beta.2`, not the
  train its section took in.\
  A pre-release compares from the release before it, which after a hotfix is the one before it in
  its train.\
  "Before" means SemVer order, not the order in the file.

### Removed

- `release-flow/draft`: the `source` and `tag-prefix` inputs, which it no longer reads.

### Fixed

- **BREAKING** `intellij/build` leaves the calling job's `JAVA_HOME` and `java` as they were: its
  Gradle steps get the JDK it sets up through a `JAVA_HOME` of their own.\
  It made that JDK the default for every later step of the job.\
  [UPGRADING.md](UPGRADING.md#intellijbuild-leaves-the-jobs-jdk-as-it-was) says what a later step
  that ran on it does now.
- **BREAKING** `lib/main.py` reads `CHANGELOG.md` as CommonMark does, but only the part of Markdown
  a changelog needs, and every command that reads the file refuses a line outside that part, with
  its number and what to write instead.\
  [What `main.py` reads in `CHANGELOG.md`](lib/README.md#what-mainpy-reads-in-changelogmd) lists
  both.\
  `changelog` refuses such a line in the copy at a release tag too, down to the end of that
  release's section, or anywhere in a copy without it.\
  That copy cannot be edited, so the refusal there does not say what to write instead.\
  A `## [x]` or `###` heading inside a fenced code block or an HTML comment was read as a section or
  a group.\
  A line that only began like a link definition, such as `[scope]: entry text`, was left out of the
  release notes and of what the `changelog` check compares.
- `close-changelog` and `notes` refuse as empty an `[Unreleased]` or a section with no character
  `str.isprintable()` accepts but the space, HTML comments aside, such as one of zero-width spaces
  or one holding only `<!-- what changed -->`.\
  In an entry or a line of text, a link counts as its text and every `*`, `_` and `~` as nothing; a
  character reference such as `&nbsp;` counts as its character.\
  `close-changelog` takes a link definition for nothing too, wherever it stands.\
  Both took only white space and link definitions for nothing, `close-changelog` only a definition
  at the end of `[Unreleased]`, so such a section was released with empty notes.
- `close-changelog` refuses an entry under `[Unreleased]` that says nothing, HTML comments aside, on
  its line or in the lines of text right below it, indented as far as its text, such as
  `- <!-- what changed -->` left as a reminder, naming its line.\
  It was released as an empty bullet.
- `close-changelog` leaves out of the section a `###` group with nothing under it, HTML comments
  and link definitions aside.\
  It was released as a heading with nothing under it.\
  A link definition in it stays where the group stood.\
  Text in such a group that is read as saying nothing is refused by its line instead of being left
  out with it, since GitHub may show it.
- `close-changelog` writes empty the blank lines after the last entry under `[Unreleased]`.\
  One holding spaces was written back below the new section as a line of spaces.
- `intellij/publish`: `attempts` and `wait` have to be whole numbers, `attempts` from 1 to 9999,
  checked before the upload.\
  An `attempts` that was no number made no attempt, and the run failed as though the version was
  not served.\
  A `wait` that was no number left the attempts with no pause between them.
- `check-release`: a glob in `checks`, such as `*`, is refused under its own name.\
  It used to be expanded to the files in the workspace, and the error named those instead.
- A `tagPrefix` in `gradle.properties` holding an unpaired `\uD800`-`\uDFFF` escape is refused.\
  `prefix` ended in a traceback printing it, and the other checks passed having found no release.
- A command-line argument holding a byte that does not decode is refused by name, before any
  command runs.\
  `set-version` ended in a traceback, and `close-changelog` in one that left `CHANGELOG.md` empty.
- `set-version` and `close-changelog` write a CRLF file back with CRLF line endings.\
  They wrote every line back as LF, so a release commit rewrote the whole file to change one line.
- `CHANGELOG.md` headings are read as CommonMark reads them in these cases too:
  - A heading indented by up to three spaces, or with a tab after its `#`s, is a heading.
  - A `###` heading closed by a run of `#`s is read without them.

  `close-changelog` found no indented `## [Unreleased]`.\
  A final release that took in its train listed a pre-release's indented or closed `### Added` apart
  from its own.
- `notes` follows the section with the link definitions it names, from wherever they stand in
  `CHANGELOG.md`.\
  It left them out, so a reference link such as `[the issue][1]` showed on the release page as
  written.

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
