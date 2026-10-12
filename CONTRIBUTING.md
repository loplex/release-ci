# Contributing to release-ci

## Running the tests

```
python3 -m pip install --require-hashes -r lib/requirements.txt -r .github/requirements.txt
python3 -m unittest discover -s lib
python3 -m unittest discover -s check-release
python3 -m unittest discover -s release-flow
python3 -m unittest discover -s intellij
python3 -m unittest discover -s .github
```

The first line installs what the `lib`, `intellij` and `.github` suites need.

[`.github/run-tests.sh`](.github/run-tests.sh) runs the same tests in a fraction of the time, on the
Python that `PYTHON` names, `python3` by default:

```
.github/run-tests.sh
```

- It runs the five suites at once, each split over as many processes as there are cores.
- It prints one line per suite, then the whole output of every red one.
- A suite whose tests did not all run is red as well.
- It tests the checkout it is run in, wherever it comes from, so the copy in a newer checkout can
  test an older commit's worktree.
- pytest-xdist splits tests over processes the same way for pytest.\
  It is not used, so that running the tests needs no package of its own.

All five suites run on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml).\
They run on the Python that [`.python-version`](.python-version) names.\
The actions install that same Python for themselves, so the tests and the actions run on one
version.

### The `lib` suite

The tests sit in [`lib/tests`](lib/tests):

- [`test_versions.py`](lib/tests/test_versions.py),
  [`test_changelog.py`](lib/tests/test_changelog.py),
  [`test_markdown.py`](lib/tests/test_markdown.py) and
  [`test_steps.py`](lib/tests/test_steps.py) test the rules.\
  They are plain functions over text, so they need no repository to release.
- [`test_sources.py`](lib/tests/test_sources.py) does the same for the adapters that say where the
  version comes from.
- [`test_repository.py`](lib/tests/test_repository.py) tests what reads the repository, and
  [`test_main.py`](lib/tests/test_main.py) the command line.\
  Both get repositories built for the purpose, but for `check_ancestry`, a rule tested over plain
  booleans.

### The `check-release` suite

[`check-release/tests/test_check.py`](check-release/tests/test_check.py) runs the action's script,
[`check.sh`](check-release/check.sh), against a repository built for the purpose.

### The `release-flow` suite

The tests sit in [`release-flow/tests`](release-flow/tests), one file per action.\
They build what each action needs:

- a repository;
- a bare remote to push to, so that a refused fast-forward is a real refusal;
- a stub `gh`, so that nothing is sent to GitHub.

### The `intellij` suite

The tests sit in [`intellij/tests`](intellij/tests).\
They build:

- archives;
- a Plugin Verifier report;
- a stub `curl` that answers for the Marketplace from a file the test writes, so that nothing is
  uploaded.

### The `.github` suite

It reads the repository as text:

- [`test_line_length.py`](.github/test_line_length.py) holds every tracked text file to the line
  length [`.editorconfig`](.editorconfig) sets for it.\
  The comment in `.editorconfig` lists the lines it lets through.\
  A file that is not UTF-8 is refused by name.
- [`test_markdown_links.py`](.github/test_markdown_links.py) holds every relative link in a tracked
  Markdown file to a tracked file or directory.\
  Where the link names a heading, the heading has to exist.
- [`test_manifests.py`](.github/test_manifests.py) reads every `action.yml` as text, for what GitHub
  would take wrongly from any of them, and with the scripts beside each, for which Python they run
  on and which steps get the JDK `intellij/build` sets up.
- [`test_changelog_reader.py`](.github/test_changelog_reader.py) holds `lib/main.py`'s own reading
  of `CHANGELOG.md` to GitHub's.\
  Every text it reads, this repository's `CHANGELOG.md` at every commit, written cases and documents
  put together at random, has to split into the same headings, list items and code as cmark-gfm
  splits it.\
  It reads the whole history, so in a shallow clone it fails.

[`test_run_tests.py`](.github/test_run_tests.py) runs `run-tests.sh` over a checkout made for the
purpose, with five small suites of its own.\
Over this repository it would run itself again.

The suite reads Markdown through [cmarkgfm](https://github.com/theacodes/cmarkgfm), the Python
binding of GitHub's own cmark-gfm.\
Code, tables, headings and links are then what GitHub renders.

- `lib/main.py` reads `CHANGELOG.md` without a package, so that an action needs none to read it;
  the reader test is what holds it to cmark-gfm.\
  Only `notes --html` renders through cmarkgfm.
- The length test renders a line that opens with a link on its own.\
  So a link defined elsewhere, or written in HTML, does not count as a link there.
- The link test reads a heading's anchor through
  [regex](https://github.com/mrabarnett/mrab-regex), for the `\p{...}` classes Python's own `re`
  lacks.
- cmarkgfm and the packages it needs are pinned, with hashes, in
  [`lib/requirements.txt`](lib/requirements.txt).\
  The `lib` and `intellij` suites need it, for `notes --html`.
- regex is pinned, with hashes, in [`.github/requirements.txt`](.github/requirements.txt).
- No other suite needs a package.

## Recording a change

A change that a user of the actions would notice gets an entry under `## [Unreleased]` in
[`CHANGELOG.md`](CHANGELOG.md).\
The entry goes in the group Keep a Changelog gives its kind: `### Added`, `### Changed`,
`### Deprecated`, `### Removed`, `### Fixed` or `### Security`.

A change that breaks something a caller relied on:

- has an entry that starts with `**BREAKING**`, as
  [What `[Unreleased]` asks of the version](lib/README.md#what-unreleased-asks-of-the-version)
  says;
- gets a section in [`UPGRADING.md`](UPGRADING.md), under the version it breaks, that shows what a
  caller has to change.

A release whose `[Unreleased]` says nothing is refused.\
The exception is a final release that takes in entries saying something from the pre-releases since
the final release before it, as [The changelog](lib/README.md#the-changelog) says.

## Releasing this repository

This repository is released through its own actions, like any other repository, with one difference:
its workflows use the actions by path, unpinned, because this is the repository they are in.

It declares its version nowhere, so [`release.yml`](.github/workflows/release.yml) asks for one when
it is dispatched:

- Left empty, it is the version after the highest release, or a later one where `[Unreleased]` asks
  for more.
- The first release has to be named outright.

There is nothing to build, so `release-flow/draft` follows `release-flow/prepare` directly.

Publishing the draft is the decision to release.\
[`release-publish.yml`](.github/workflows/release-publish.yml) then carries the release back onto
the default branch.\
Where it carries it back in a pull request instead, the repository needs the settings under
[What the pull request needs of the repository][settings].

[settings]: release-flow/README.md#what-the-pull-request-needs-of-the-repository

GitHub reads each workflow as [Where GitHub reads each workflow from][reads] says:

- `release.yml` only once it is on the default branch, and then from the branch it is dispatched
  on.\
  That is why its job runs on the default branch only.
- `release-publish.yml` from the commit a release tags.\
  That commit has the file, because a release is cut from the default branch.

[reads]: release-flow/README.md#where-github-reads-each-workflow-from

The `guards` job in [`test.yml`](.github/workflows/test.yml) runs the checks over this repository on
every push and pull request.\
It uses the action at `./check-release`, by path as well.
