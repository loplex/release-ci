# check-release

`check-release` is a composite action that checks a repository before and after a release, with
[`lib/main.py`](../lib/README.md).\
It runs:

- `version`, `changelog` and `ancestry`, whichever its `checks` input names;
- `channel`, after a `version` check that passed.

What each check holds a repository to, and where the version comes from, is in
[`lib/README.md`](../lib/README.md).

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

[No default tag prefix, on purpose](../lib/README.md#no-default-tag-prefix-on-purpose)
explains why there is no default.

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
- `steps.<id>.outputs.channel`: the
  [channel](../lib/README.md#the-channel-a-version-goes-to) of that version.\
  `default` for a final release, otherwise the first identifier of its pre-release suffix.

### The `version` input

The `version` input gives the `version` check a version to check, such as one from a dispatch form.\
It replaces:

- under `gradle.properties`, the version the file declares;
- under `tags`, the default: the version after the highest release, or a later one where
  `[Unreleased]` asks for more.

How to spell it under each source is under
[Where the version comes from](../lib/README.md#where-the-version-comes-from).
