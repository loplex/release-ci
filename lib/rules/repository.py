"""The repository being checked: git, its files, and the release tags it holds.

Everything here that reads the repository goes through repository(), which a test can point elsewhere.
"""

import subprocess
import sys
from pathlib import Path

from .versions import SEMVER, being_worked_on, precedence


def repository_root() -> Path:
    """The root of the repository being checked, asked of git in the working directory.

    This file runs from a checkout of its own repository, against the repository in the working directory,
    which is usually another one.
    A root taken from this file's path would then name the wrong repository, and nothing would fail:
    this repository has a CHANGELOG.md of its own for the checks to read instead.
    """
    rev_parse = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if rev_parse.returncode != 0:
        raise SystemExit("lib/main.py has to be run inside the repository it is checking")
    return Path(rev_parse.stdout.strip())


# Resolved on first use, not when this file is loaded:
# - `--help` then works outside a repository;
# - a test can set a repository of its own here before anything reads it.
# A subcommand that reads the repository still refuses to run outside one, once the arguments are parsed.
REPO: Path | None = None


def repository() -> Path:
    global REPO
    if REPO is None:
        REPO = repository_root()
    return REPO


def check_ancestry(reachability: dict[str, bool], prefix: str, held_by: dict[str, str] | None = None) -> list[str]:
    """Whether every released tag is still part of the history it was released from.

    A tag points at the commit a release was made from, and is the only record of which commit that was.
    Anything that rewrites the commits around it leaves the tag on a commit this history no longer reaches:
    a squash merge, a rebase merge, GitHub's `Update with rebase`, a force-push.

    Asking whether the tag is reachable catches all of them, whatever the cause.
    Forbidding the causes one by one would not: GitHub can add new ways to rewrite a branch.

    `held_by` names, for a tag that is not on this history, a branch that still holds it.
    A release whose branch has not been carried back yet fails the same way as one a rewrite orphaned.
    The message differs, because the cause and the fix differ:
    blaming a rewrite for a merge that is only outstanding sends the reader looking for damage that is not there.

    A branch holding the tag does not tell the two apart:
    a squash or rebase merge replays the release commit and leaves the original on the branch it came from.
    So that message names both readings; both are settled by looking at that one branch.
    Only a tag that no branch holds is put down to a rewrite outright.
    """
    problems = []
    held_by = held_by or {}
    for version, reached in sorted(reachability.items(), key=lambda item: precedence(item[0])):
        if reached:
            continue
        branch = held_by.get(version)
        if branch:
            problems.append(
                f"{prefix}{version} is released but is not on this history: {branch} still holds it. Either "
                f"that branch has not been carried back yet, or it was landed with a squash or a rebase, "
                f"which replays the release commit and leaves the tag on the original the copy replaced"
            )
        else:
            problems.append(
                f"{prefix}{version} is released but is no longer reachable: a rewrite has taken it off this "
                f"history"
            )
    return problems


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=repository(), capture_output=True, text=True, check=True).stdout


def read_file(name: str, holds: str, encoding: str = "utf-8", newline: str | None = None) -> str:
    """A file of the repository, read as text.

    A missing file is refused with its name and what it is read for.
    A traceback would read as the tool breaking, not as the repository lacking a file, and would name no fix.

    `newline` is open()'s: left out, line endings are read as `\\n`.
    A writer that wants to keep the file's own line endings passes `""`."""
    try:
        with open(repository() / name, encoding=encoding, newline=newline) as stream:
            return stream.read()
    except FileNotFoundError:
        raise SystemExit(f"there is no {name} here, and it is where {holds} would be read from") from None


def released_versions(prefix: str) -> list[str]:
    """Every tag that names a release, with the prefix taken off.

    A repository also has tags that are not releases, and those are left out:
    another component's, a deployment's, a milestone's, and a version tagged while it was still being worked on.

    Finding no release among the tags is reported on stderr, not failed:
    a repository may carry other tags only, and a first release has nothing to compare with either.
    But it is also what a wrong prefix looks like, and every check over the result then passes without comparing
    anything. Only `version` under `tags` with no version given fails instead, finding no release to count from.

    Tags are selected by how they start, not by a glob, so a prefix is read as text and not as a pattern,
    and the number of tags passed over comes with the selection.
    """
    tags = git("tag", "-l").split()
    releases = [
        tag[len(prefix) :]
        for tag in tags
        if tag.startswith(prefix)
        and SEMVER.match(tag[len(prefix) :])
        and not being_worked_on(tag[len(prefix) :])
    ]
    if tags and not releases:
        called = f"the prefix '{prefix}'" if prefix else "no prefix at all"
        print(f"note: this repository has {len(tags)} tag(s) and none of them is a release under {called}, "
              f"so there is no release to compare against", file=sys.stderr)
    return releases


def unreachable(prefix: str, versions) -> set[str]:
    """The released versions whose tag this history does not reach.

    Asked of git in one place and handed to each check that needs it,
    so two checks of one repository cannot disagree about which releases are on it."""
    return {
        version
        for version in versions
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"{prefix}{version}", "HEAD"], cwd=repository(), capture_output=True
        ).returncode
        != 0
    }


def holder(tag: str, version: str) -> str:
    """A branch that still holds `tag`, or the empty string if none does.

    Asked only for a tag that HEAD does not reach, to choose between the two messages of check_ancestry.
    - Remote branches are asked first, and named as fetched: a release is carried back from what the remote has,
      and a local branch of the same name may hold something else.
    - Among the branches of the first kind that holds the tag, `release/<version>` comes first,
      because it is the one the reader has to act on.
    """
    wanted = f"release/{version}"
    for pattern in ("refs/remotes", "refs/heads"):
        branches = git("for-each-ref", "--contains", tag, "--format=%(refname:short)", pattern).split()
        if branches:
            return sorted(branches, key=lambda name: (name != wanted and not name.endswith("/" + wanted), name))[0]
    return ""
