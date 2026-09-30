# release-ci

The release rules a project would otherwise carry its own copy of, and the pipeline that runs them:

- the guards a release has to pass;
- draft-before-tag GitHub releases cut, drafted and carried back;
- per-ecosystem publishing, to the JetBrains Marketplace first.

[What is here](#what-is-here) says which directory holds which.

What goes where is decided by the ecosystem boundary, not by whichever file is being written:

- A directory whose content is ecosystem-free carries a name that says nothing about an ecosystem.
- A directory for one ecosystem is named after it, and more will follow, one per ecosystem.

This repository is released through its own pipeline, as
[Releasing this repository](CONTRIBUTING.md#releasing-this-repository) describes, so nothing in the
ecosystem-free directories may assume one ecosystem's build.

## What is here

| Directory                                  | Holds                                                                                                      |
|--------------------------------------------|------------------------------------------------------------------------------------------------------------|
| [`check-release`](check-release/README.md) | What a release has to be true of, asked as properties over a repository                                    |
| [`release-flow`](release-flow/README.md)   | How a GitHub release is cut, drafted before it is tagged, carried back, and flagged where a publish failed |
| [`intellij`](intellij/README.md)           | How a JetBrains plugin is built, signed and published to the Marketplace                                   |

- Each action's inputs and outputs are listed in full, with what each does, in the `action.yml`
  beside it.
- The README in each directory shows how the actions in it fit together.

### What an action needs of the runner

- Every action but `intellij/build` runs on the runner's own `python3`, 3.10 or later.
- `release-flow/draft`, `release-flow/merge-back` and `release-flow/warn` need `gh` as well.
- `intellij/publish` needs `curl` as well.
- GitHub-hosted runners carry `python3`, `gh` and `curl`.

## Pinning

The examples in these READMEs pin an action of this repository to one of its release tags, `v` and a
version, as `@<tag>`.\
What a workflow pins to is its own choice, and each ref gets something different:

- A release tag names a released commit, and is what keeps it reachable.
- The full SHA of the commit a release tag names is the same code, and nothing can move it, where a
  tag can be moved; GitHub's
  [security guide](https://docs.github.com/en/actions/reference/security/secure-use) recommends it
  for that reason.
- A branch moves, so this repository's code would change under the pin.
- A commit that nothing reaches any more may fail to check out, GitHub keeping no promises about
  unreachable objects.

The pin holds this repository's code only: the actions `intellij/build` calls in turn,
`actions/setup-java` and the rest, run at the tags its `action.yml` names for them, which their
owners can move.

### No moving `v0`

This repository keeps no major version tag, such as `v4`, for a pin to follow.\
This diverges from
[GitHub's guide to versioning actions](https://github.com/actions/toolkit/blob/main/docs/action-versioning.md).\
There the author moves a major version tag to each release that keeps its inputs and behavior, so
that a pin to it takes fixes without being changed.

This repository keeps no such tag while its version is below 1.0, because
[item 4 of the SemVer specification](https://semver.org/#semantic-versioning-specification-semver)
says that anything may change in `0.y.z`: a moving `v0` would promise nothing a pin could rely on.\
A moving major version tag belongs to 1.0 and later.
