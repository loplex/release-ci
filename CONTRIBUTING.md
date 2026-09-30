# Contributing to release-ci

## Running the tests

```
python3 -m pip install -r .github/requirements.txt
python3 -m unittest discover -s check-release
python3 -m unittest discover -s release-flow
python3 -m unittest discover -s intellij
python3 -m unittest discover -s .github
```

The first line installs what the `.github` suite needs.\
All four suites run on every push and pull request, in
[`.github/workflows/test.yml`](.github/workflows/test.yml), on the Python
[`.python-version`](.python-version) names.\
The first three need 3.11 or later, where the actions ask only for 3.10.

### The `check-release` suite

- The rules in `check-release` are plain functions over text, tags and booleans, and
  [`test_check_release.py`](check-release/test_check_release.py) exercises them without a repository
  to release.
- [`test_sources.py`](check-release/test_sources.py) does the same for the adapters for where the
  version comes from.
- The helpers that face git, beside the rules, get a repository built for the purpose.
- [`test_check.py`](check-release/test_check.py) runs the action's script,
  [`check.sh`](check-release/check.sh), against such a repository.

### The `release-flow` suite

It builds what each of its actions needs:

- a repository;
- a bare remote to push to, so that a refused fast-forward is a real refusal;
- a stub for whatever is called out, so that nothing is sent anywhere.

### The `intellij` suite

It builds:

- archives;
- a Plugin Verifier report;
- a stub `curl`, which answers for the Marketplace from a file the test writes, so that nothing is
  uploaded.

### The `.github` suite

It reads the repository as text: [`test_line_length.py`](.github/test_line_length.py) holds every
tracked file git does not take for binary to the line length [`.editorconfig`](.editorconfig) sets
for it, but for the lines the comment there lists, and refuses one that is not UTF-8 by name.

The suite reads Markdown through [cmarkgfm](https://github.com/theacodes/cmarkgfm), the Python
binding of GitHub's own cmark-gfm, so that code, tables and headings are what GitHub renders.\
The length test renders a line opening with a link alone, so a link whose definition stands
elsewhere, or one written in HTML, does not count as one there.\
cmarkgfm and the packages it needs are pinned in
[`.github/requirements.txt`](.github/requirements.txt), and no other suite needs a package.

## Releasing this repository

This repository is released through its own actions, as any other repository would be, except that:

- its workflows take them by path, unpinned, this being the one repository they already sit in;
- its release workflows run them on the Python its suites run on rather than the runner's own.

It declares its version nowhere, so [`release.yml`](.github/workflows/release.yml) asks for one when
it is dispatched:

- left empty, the version after the highest release is taken;
- the first release has to be named outright.

There is nothing to build, so `release-flow/draft` follows `release-flow/prepare` directly.

Publishing the draft is the decision to release, and
[`release-publish.yml`](.github/workflows/release-publish.yml) carries the release back onto the
default branch.

GitHub reads each the way [Where GitHub reads each workflow from][reads] says:

- `release.yml` only once it has landed on the default branch, and then from the branch it is
  dispatched on, which is why its job runs on the default branch alone;
- `release-publish.yml` from the commit a release tags, which carries the file because a release is
  cut from the default branch.

[reads]: release-flow/README.md#where-github-reads-each-workflow-from

The `guards` job in [`test.yml`](.github/workflows/test.yml) runs the rules over this repository
itself on every push and pull request, through the action at `./check-release`, by path as well, on
the runner's own `python3`.
