# release-ci

Release rules and a release pipeline that projects share, instead of each carrying its own copy:

- the checks a release has to pass;
- GitHub releases that are cut, drafted before they are tagged, and carried back;
- publishing per ecosystem, to the JetBrains Marketplace first.

[What is here](#what-is-here) says which directory holds which.

Where something goes depends on whether it is tied to one ecosystem:

- A directory that is not tied to one has a name that names no ecosystem.
- A directory for one ecosystem is named after it.
  More will follow, one per ecosystem.

This repository is released through its own pipeline, as
[Releasing this repository](CONTRIBUTING.md#releasing-this-repository) describes.\
So nothing in the directories that are not tied to an ecosystem may assume one ecosystem's build.

## What is here

| Directory                                  | Holds                                                                                                      |
|--------------------------------------------|------------------------------------------------------------------------------------------------------------|
| [`check-release`](check-release/README.md) | the checks a release has to pass, asked of a repository                                                    |
| [`release-flow`](release-flow/README.md)   | how a GitHub release is cut, drafted before it is tagged, carried back, and flagged where a publish failed |
| [`intellij`](intellij/README.md)           | how a JetBrains plugin is checked, built, signed and published to the Marketplace                          |
| [`lib`](lib/README.md)                     | `main.py`, the command line behind the actions above, and the release rules it applies                     |

- `lib` is not an action: a workflow calls the actions, and the actions run it.
- Each action's `action.yml` lists all its inputs and outputs, and what each does.
- The README in each directory shows how its actions fit together.
- A project that releases with these actions runs them from three workflows of its own.\
  [The workflow files](release-flow/README.md#the-workflow-files) suggests a file name for each.

### What an action needs of the runner

- Every action that runs Python installs it with `actions/setup-python`, leaving the job's own
  `python3` as it was.\
  It is the version [`.python-version`](.python-version) names.\
  A self-hosted runner that does not have it downloads it, where `actions/setup-python` publishes a
  build for its system.
- The actions are tried in jobs that run on a GitHub-hosted runner itself.\
  A job with a `container:` runs them in that container, where two limits apply that are not this
  repository's own:
  - `actions/setup-python` brings the Python built for the runner's system, not the image's.\
    It builds Python only for
    [the systems GitHub-hosted runners run](https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md#using-setup-python-with-a-self-hosted-runner).\
    In an image other than the runner's it may not start, or start without a module such as `ssl`,
    which `intellij/build` with `change-notes: true` needs to download cmarkgfm.
  - `actions/checkout` marks the workspace safe for git only while it runs.\
    A later step running git as another user, as a container's `root` does, is refused the
    repository, unless a step after the checkout runs
    `git config --global --add safe.directory "$GITHUB_WORKSPACE"`.
- `release-flow/draft`, `release-flow/merge-back` and `release-flow/warn` need `gh`.
- `intellij/publish` needs `curl`.
- GitHub-hosted runners have both.
- `intellij/build` with `change-notes: true` downloads cmarkgfm from PyPI, and runs Gradle in the
  `C.UTF-8` locale, which the system has to have.

## Pinning

The examples in these READMEs pin an action to one of this repository's release tags, `v` and a
version, written as `@<tag>`.\
What a workflow pins to is its own choice, and each kind of ref gives something different:

| Pinned to                              | What it gives                                                       |
|----------------------------------------|---------------------------------------------------------------------|
| a release tag                          | a released commit; the tag is also what keeps that commit reachable |
| the full SHA of a release tag's commit | the same code, and nothing can move it, where a tag can be moved    |
| a branch                               | code that changes under the pin whenever the branch moves           |

- GitHub's [security guide](https://docs.github.com/en/actions/reference/security/secure-use)
  recommends the full SHA, because nothing can move it.
- A commit that nothing reaches any more can be checked out by its SHA only until a garbage
  collection removes it.\
  GitHub promises no date for that; its [guide to removing sensitive data][sensitive-data] has
  GitHub Support run one.

[sensitive-data]: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

Moving the pin to a newer version may ask for changes in the workflow.\
[`UPGRADING.md`](UPGRADING.md) lists them, per version.

The pin holds this repository's code only.\
The actions that these actions call in turn, `actions/setup-python`, `actions/setup-java` and the
rest, run at the tags each `action.yml` names for them, and their owners can move those tags.

### No moving `v0`

This repository keeps no major version tag, such as `v4`, for a pin to follow.\
This diverges from
[GitHub's guide to versioning actions](https://github.com/actions/toolkit/blob/main/docs/action-versioning.md).\
There the author moves a major version tag to each release that keeps its inputs and behavior.\
A pin to that tag then takes fixes without being changed.

This repository keeps no such tag while its version is below 1.0.\
[Item 4 of the SemVer specification](https://semver.org/#semantic-versioning-specification-semver)
says that anything may change in `0.y.z`, so a moving `v0` would promise nothing a pin could rely
on.\
A moving major version tag belongs to 1.0 and later.
