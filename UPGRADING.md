# Upgrading

What a workflow has to change when it moves its pin to a newer version of this repository.\
A version that asks for no change is not listed.\
[`CHANGELOG.md`](CHANGELOG.md) lists every change, this file only the ones a caller has to act on.

## From 0.2

### The `source` input is now `version-source`

In `check-release`, `release-flow/prepare` and `release-flow/merge-back`.\
The new name says what it is the source of: the version of the next release.

Before:

```yaml
- uses: loplex/release-ci/check-release@v0.2.0
  with:
    source: gradle.properties
```

After:

```yaml
- uses: loplex/release-ci/check-release@<tag>
  with:
    version-source: gradle.properties
```

A workflow that still passes `source` fails.
GitHub only warns about the unknown input, and the action then refuses the empty `version-source`.

### `check-release/check-release.py` is now `lib/main.py`

This matters only to a workflow that runs the script itself.
The actions call it the new way already.

- The script moved to [`lib/main.py`](lib/README.md), beside the rules it runs.
- `--source` is now `--version-source`.
- `--version-source` and `--tag-prefix` go after the command, not before it.
- A command refuses the options it never reads.
  `close-changelog` reads them only with `--repository-url`, and takes them either way:

| Command                                                                 | `--version-source` | `--tag-prefix` |
|-------------------------------------------------------------------------|--------------------|----------------|
| `version`, `next`, `changelog`, `ancestry`, `prefix`, `close-changelog` | required           | optional       |
| `set-version`                                                           | required           | refused        |
| `notes`, `channel`                                                      | refused            | refused        |

`--tag-prefix` is optional only where the source declares the prefix: under `tags` it is required,
by `close-changelog` only with `--repository-url`.

Before:

```sh
python3 check-release/check-release.py --source tags --tag-prefix v changelog
python3 check-release/check-release.py --source tags --tag-prefix v channel v0.3.0-beta.1
```

After:

```sh
python3 lib/main.py changelog --version-source tags --tag-prefix v
python3 lib/main.py channel 0.3.0-beta.1
```

`channel` takes the version without the tag prefix.
A tag name such as `v0.3.0-beta.1` is refused.

### `release-flow/draft` has no `source` or `tag-prefix` input

Remove both from the step's `with:`.
The draft reads neither: the notes and the channel do not depend on them.
GitHub only warns about an input the action does not have, so the run does not fail without this.

### `version` holds the version to what `[Unreleased]` asks for

The `version` check, which `release-flow/prepare` runs too, refuses a version that moves less
past the last final release than the entries under `[Unreleased]` ask for.\
`### Added`, `### Changed` and `### Deprecated` ask for a minor.\
`### Removed`, and an entry starting with `**BREAKING**`, ask for a major, or a minor below 1.0.\
[What `[Unreleased]` asks of the version](lib/README.md#what-unreleased-asks-of-the-version)
has the whole rule.

- Release the version the refusal names, or a later one.
- Move an entry that stands under no `###` group under the group of its kind: such an entry is
  refused.
- Under `tags` with no `version` given, the default version already moves as far as is asked.

### Some Markdown in `CHANGELOG.md` is refused

Every `lib/main.py` command that reads `CHANGELOG.md` refuses a line outside the part of Markdown it
reads, so every action that runs one does too.\
[What `main.py` reads in `CHANGELOG.md`](lib/README.md#what-mainpy-reads-in-changelogmd) lists what
is read and what is refused, such as an indented code block, a block quote or a tab in the
indentation.\
Fenced code blocks are read.\
Before moving the pin, run the new version's `changelog` command in the repository, from a clone of
this one at the new tag, with the `version-source` and `tag-prefix` the workflow gives:

```sh
python3 <clone>/lib/main.py changelog --version-source <source> [--tag-prefix <prefix>]
```

- A refusal names the line and what to write instead.\
  Under `[Unreleased]`, write that.
- The `changelog` check reads the copy at each release tag down to the end of that release's
  section, or whole where it has no such section, and a tag cannot be edited.\
  A refused line in what it reads fails the check on every run.\
  Rewrite the line in the tree, and give `skip-unreadable-releases: true` to `check-release`,
  `release-flow/prepare` and `release-flow/merge-back`.
  The check then names that release as not compared, with the line, instead of failing.

### Actions that run Python install their own

Every action now installs the Python this repository's [`.python-version`](.python-version) names
with `actions/setup-python`.\
The others ran on the runner's `python3`; `intellij/build` runs Python for the first time, to read
the signed archive.\
A job without a `container:`, on a GitHub-hosted runner, has nothing to change.

- A job with a `container:` runs these actions in that container, where they are not tried.\
  The image's own `python3` is not used.\
  [What an action needs of the runner](README.md#what-an-action-needs-of-the-runner) names the
  limits of `actions/setup-python` and `actions/checkout` there: run such a job once before moving
  the pin.
- A self-hosted runner needs a system `actions/setup-python` publishes a build for, and a way to
  download it unless it already has that version.

### `intellij/build` leaves the job's JDK as it was

A step after `intellij/build` that runs `java` or Gradle ran on the JDK `intellij/build` set up.\
It now runs on the job's own: where it needs that JDK, set it up in the job with
`actions/setup-java` before that step.

### `intellij/build` checks the signed archive's version

`intellij/build` stops where the signed archive's `plugin.xml` does not carry the version in the
`version` line of `gradle.properties`.\
A build script that gives `project.version` anything else has to take it from that line instead,
which `release-flow/prepare` rewrites for the release.\
[What the plugin's build has to do](intellij/README.md#what-the-plugins-build-has-to-do) shows the
rest.
