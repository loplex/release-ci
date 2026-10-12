"""The repository being checked: git, its files, and the release tags it holds.

Everything here that reads the repository goes through repository(), which a test can point elsewhere.
"""

import re
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
    A release still on its way here, on `release/<version>`, is told apart before this rule (see carried_by)
    and does not reach it.

    A tag a branch holds that does reach it was most often landed with a squash or a rebase merge:
    either replays the release commit and leaves the original on the branch it came from.
    The other readings are a rewrite of the history the release was cut from, and a release still to be carried
    back that carried_by could not recognize: from a branch of another name, or into a tree whose CHANGELOG.md is
    missing or cannot be read.
    So that message names all three, the squash first; each is settled by looking at that one branch.
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
                f"{prefix}{version} is released but is not on this history: {branch} still holds it. It was "
                f"landed with a squash or a rebase, which replays the release commit and leaves the tag on the "
                f"original the copy replaced, or the history it was cut from was rewritten, or that branch has yet "
                f"to be carried back"
            )
        else:
            problems.append(
                f"{prefix}{version} is released but is no longer reachable: a rewrite has taken it off this "
                f"history"
            )
    return problems


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=repository(), capture_output=True, text=True, check=True).stdout


# What release-flow/prepare records in a release commit, as git trailers `Release-CI-<name>: <value>`.
# A commit with none of them was not cut by a prepare that records them.
RECORDED = "Release-CI-"


def recorded(ref: str) -> dict[str, list[str]]:
    """The trailers `Release-CI-<name>` of the commit `ref` names, by `<name>` in lower case, each with its values.

    Read by git, which also wrote them (`git interpret-trailers` in release-flow/prepare),
    so where a trailer starts and ends is decided in one place.
    Git matches a trailer's key whatever its case, and so does this.
    A ref that names no commit here is refused."""
    try:
        text = git("log", "-1", "--format=%(trailers:only,unfold)", ref)
    except subprocess.CalledProcessError:
        raise SystemExit(f"{ref} names no commit here") from None
    found = {}
    for line in text.splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip().lower().startswith(RECORDED.lower()):
            found.setdefault(key.strip()[len(RECORDED):].lower(), []).append(value.strip())
    return found


def line_of(data: bytes, offset: int) -> int:
    """The line `offset` stands on, a CRLF, a CR or an LF ending each line, as CommonMark ends them."""
    return len(re.findall(rb"\r\n|\r|\n", data[:offset])) + 1


def read_file(name: str, holds: str, encoding: str = "utf-8", newline: str | None = None) -> str:
    """A file of the repository, read as text.

    A missing file is refused with its name and what it is read for, and so is one that does not decode,
    with the line of its first byte that does not.
    A traceback would read as the tool breaking, not as the repository lacking a file, and would name no fix.

    `newline` is open()'s: left out, line endings are read as `\\n`.
    A writer that wants to keep the file's own line endings passes `""`."""
    try:
        with open(repository() / name, encoding=encoding, newline=newline) as stream:
            return stream.read()
    except FileNotFoundError:
        raise SystemExit(f"there is no {name} here, and it is where {holds} would be read from") from None
    except UnicodeDecodeError as error:
        # read() decodes the whole file at once, so the error counts from its first byte.
        line = line_of(error.object, error.start)
        raise SystemExit(f"{name} line {line} holds a byte that is not {encoding}, and {name} is where {holds} "
                         f"would be read from") from None


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

    Asked only for a tag that HEAD does not reach, to choose between the messages of check_ancestry.
    - Remote branches are asked first, and named as fetched: a release is carried back from what the remote has,
      and a local branch of the same name may hold something else.
    - Among the branches of the first kind that holds the tag, `release/<version>` comes first, because it is the one
      the reader has to act on.
      With it, in name order, comes any name ending in `/release/<version>`, the remote's `origin/release/<version>` and
      a `team/release/<version>` alike: the branch is only named in a message, while release_branch, which decides
      whether a release is awaited, takes the release branch alone.
    """
    wanted = f"release/{version}"
    _, branches = holding(tag)
    return min(branches, key=lambda name: (name != wanted and not name.endswith("/" + wanted), name), default="")


def release_branch(kind: str, branch: str, version: str) -> bool:
    """Whether `branch`, of `kind`, is the release branch itself: `release/<version>` as a local branch,
    `<remote>/release/<version>` as fetched. A branch whose name only ends so, `team/release/<version>`, is another."""
    return is_branch(kind, branch, f"release/{version}")


def is_branch(kind: str, branch: str, name: str) -> bool:
    """Whether `branch`, of `kind`, is the branch `name`: itself as a local branch, `<remote>/<name>` as fetched."""
    return (branch.split("/", 1)[1:] if kind == "refs/remotes" else [branch]) == [name]


def holding(tag: str) -> tuple[str, list[str]]:
    """The first kind of branch any of which holds `tag`, `refs/remotes` before `refs/heads`, and those branches.

    Both holder and carried_by take the branches of that kind alone, so the two cannot disagree about which kind
    a branch was found among."""
    for kind in ("refs/remotes", "refs/heads"):
        branches = git("for-each-ref", "--contains", tag, "--format=%(refname:short)", kind).split()
        if branches:
            return kind, branches
    return "", []


def carried_by(prefix: str, versions) -> dict[str, str]:
    """Of `versions`, released but off this history, those whose release branch still holds the tag, each with it.

    A release is published from `release/<version>` and reaches the default branch only when merge-back carries it
    there, or its pull request does once merged. Until then the tag is off this history, which is no fault.
    Two things about the history tell that apart from a rewrite that took the tag off:
    - `release/<version>` holds the tag.
    - Every parent of the tagged commit is on this history: the history the release was cut from is all still here.
      A force-push below the point the release was cut from fails this.
    A squash or a rebase merge passes both, so the caller has a third question to ask, of the tree.

    A force-push that takes a landed release back off passes all three while its branch is still there.
    merge-back deletes the branch when its own push lands the release; one its pull request carried is left to
    whoever merged it, and until it is deleted such a force-push is taken for a release on its way.
    """
    found = {}
    for version in versions:
        tag = f"{prefix}{version}"
        kind, branches = holding(tag)
        named = [branch for branch in branches if release_branch(kind, branch, version)]
        if named and cut_from_here(tag):
            found[version] = named[0]
    return found


def landed_after(prefix: str, versions, default_branch: str) -> dict[str, str]:
    """Of `versions`, released but off this history, those that landed on the default branch after HEAD was made,
    each with the branch that holds it.

    A commit pushed while merge-back runs, and checked only once the release has landed, a re-run or a run that waited
    in a queue, finds `release/<version>` deleted and the tag on the default branch.
    The commit is older than the release, not cut off from it.
    Two things about the history tell that apart from a rewrite:
    - `default_branch` holds the tag, as fetched where a remote branch holds it, as carried_by() looks for the release
      branch. A squash or a rebase merge would have left the default branch a copy of the release commit instead.
    - Every parent of the tagged commit is on this history, as carried_by() asks.
    """
    found = {}
    for version in versions:
        tag = f"{prefix}{version}"
        kind, branches = holding(tag)
        named = [branch for branch in branches if is_branch(kind, branch, default_branch)]
        if named and cut_from_here(tag):
            found[version] = named[0]
    return found


def cut_from_here(tag: str) -> bool:
    """Whether every parent of the commit `tag` points at is on this history.
    A tagged commit with no parent was cut from no history, so nothing says it is this one."""
    parents = git("rev-list", "--parents", "-n", "1", f"{tag}^{{commit}}").split()[1:]
    return bool(parents) and all(reaches(parent) for parent in parents)


def reaches(commit: str) -> bool:
    """Whether HEAD reaches `commit`: it is HEAD or one of its ancestors."""
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=repository(), capture_output=True
    ).returncode == 0
