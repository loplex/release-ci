# Contributing to release-ci

## Running the tests

```
python3 -m pip install -r .github/requirements.txt
python3 -m unittest discover -s check-release
python3 -m unittest discover -s release-flow
python3 -m unittest discover -s intellij
python3 -m unittest discover -s .github
```

The first line installs what the `.github` suite needs.

All four suites run on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml).\
They run on the Python that [`.python-version`](.python-version) names.\
The actions install that same Python for themselves, so the tests and the actions run on one
version.

### The `check-release` suite

The tests sit in [`check-release/tests`](check-release/tests):

- [`test_versions.py`](check-release/tests/test_versions.py),
  [`test_changelog.py`](check-release/tests/test_changelog.py) and
  [`test_steps.py`](check-release/tests/test_steps.py) test the rules.\
  They are plain functions over text, so they need no repository to release.
- [`test_sources.py`](check-release/tests/test_sources.py) does the same for the adapters that say
  where the version comes from.
- [`test_repository.py`](check-release/tests/test_repository.py) tests what reads the repository,
  and [`test_check_release.py`](check-release/tests/test_check_release.py) the command line.\
  Both get repositories built for the purpose, but for `check_ancestry`, a rule tested over plain
  booleans.
- [`test_check.py`](check-release/tests/test_check.py) runs the action's script,
  [`check.sh`](check-release/check.sh), against such a repository.

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
  on.

The suite reads Markdown through [cmarkgfm](https://github.com/theacodes/cmarkgfm), the Python
binding of GitHub's own cmark-gfm.\
Code, tables, headings and links are then what GitHub renders.

- The length test renders a line that opens with a link on its own.\
  So a link defined elsewhere, or written in HTML, does not count as a link there.
- The link test reads a heading's anchor through
  [regex](https://github.com/mrabarnett/mrab-regex), for the `\p{...}` classes Python's own `re`
  lacks.
- cmarkgfm, the packages it needs, and regex are pinned in
  [`.github/requirements.txt`](.github/requirements.txt).\
  No other suite needs a package.

## Recording a change

A change that a user of the actions would notice gets an entry under `## [Unreleased]` in
[`CHANGELOG.md`](CHANGELOG.md).\
The entry goes in the group Keep a Changelog gives its kind: `### Added`, `### Changed`,
`### Deprecated`, `### Removed`, `### Fixed` or `### Security`.

A change that breaks something a caller relied on:

- has an entry that starts with `**BREAKING**`, as
  [What `[Unreleased]` asks of the version](check-release/README.md#what-unreleased-asks-of-the-version)
  says;
- gets a section in [`UPGRADING.md`](UPGRADING.md), under the version it breaks, that shows what a
  caller has to change.

A release with nothing under `[Unreleased]` is refused.\
The exception is a final release that takes in the entries of the pre-releases since the final
release before it, as [The changelog](check-release/README.md#the-changelog) says.

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
