# Upgrading

What a workflow has to change when it moves its pin to a newer version of this repository.\
A version that asks for no change is not listed.\
[`CHANGELOG.md`](CHANGELOG.md) lists every change, this file only the ones a caller has to act on.

## From 0.2

### `check-release.py` takes its options after the command

This matters only to a workflow that runs `check-release.py` itself.
The actions call it the new way already.

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
python3 check-release.py --source tags --tag-prefix v changelog
python3 check-release.py --source tags --tag-prefix v channel v0.3.0-beta.1
```

After:

```sh
python3 check-release.py changelog --version-source tags --tag-prefix v
python3 check-release.py channel 0.3.0-beta.1
```

`channel` takes the version without the tag prefix.
A tag name such as `v0.3.0-beta.1` is refused.

### `release-flow/draft` has no `source` or `tag-prefix` input

Remove both from the step's `with:`.
The draft reads neither: the notes and the channel do not depend on them.
GitHub only warns about an input the action does not have, so the run does not fail without this.

### `version` holds the version to what `[Unreleased]` asks for

`check-release version`, which `release-flow/prepare` runs too, refuses a version that moves less
past the last final release than the entries under `[Unreleased]` ask for.\
`### Added`, `### Changed` and `### Deprecated` ask for a minor.\
`### Removed`, and an entry starting with `**BREAKING**`, ask for a major, or a minor below 1.0.\
[What `[Unreleased]` asks of the version](check-release/README.md#what-unreleased-asks-of-the-version)
has the whole rule.

- Release the version the refusal names, or a later one.
- Move an entry that stands under no `###` group under the group of its kind: such an entry is
  refused.
- Under `tags` with no `version` given, the default version already moves as far as is asked.
