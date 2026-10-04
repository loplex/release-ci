"""The rules main.py runs, and what they read.

- versions.py, changelog.py and steps.py: the rules, as plain functions over text.
- markdown.py: the part of Markdown changelog.py reads, line by line, and a refusal for the rest.
- repository.py: git, the repository's files, and its release tags,
  with check_ancestry, the rule over which release tags this history reaches.
- sources.py: one adapter per kind of repository, for where the version comes from.
"""
