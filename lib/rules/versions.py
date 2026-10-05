"""Semantic versions: which text is one, how versions are ordered, and which one may follow which.

Plain functions over strings, with no repository behind them.
"""

import re


# A version is a semantic version, build metadata included, in SemVer 2.0.0's own grammar:
# no leading zeros, and a pre-release identifier is a number or holds a letter or a hyphen.
# That grammar is what lets precedence() order versions as the spec does.
# A shape the spec leaves undefined, such as `1.0.0-a..b` or `01.0.0`, does not match, so nothing has to order it.
# `re.ASCII` keeps `\d` to ASCII digits, as the spec has them: otherwise `1٠.0.0` would be ordered as 10.0.0.
# `\Z` ends the match where the text ends; `$` would let a trailing newline through.
#
# Build metadata, the `+` part, is accepted together with the spec's rule for it:
# "Build metadata MUST be ignored when determining version precedence."
# So neither of `1.0.0+a` and `1.0.0+b` comes after the other, and check_version says so in those words.
# Metadata is captured apart from the pre-release suffix, so it is not part of the channel either.
#
# The pre-release suffix names the distribution channel (see channel_of):
# `0.2.0-beta.1` is offered only to whoever subscribed to `beta`, and is a pre-release wherever it is published.
PRE_RELEASE_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
BUILD_METADATA = r"(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)"
SEMVER = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-({PRE_RELEASE_IDENTIFIER}(?:\.{PRE_RELEASE_IDENTIFIER})*))?(?:\+({BUILD_METADATA}))?\Z",
    re.ASCII,
)


def precedence(version: str) -> tuple:
    """A key that orders versions the way SemVer does, so that `<` and `sorted` mean what the spec means.

    Two rules that string comparison gets wrong:
    - a release outranks every pre-release of the same three numbers: `0.2.0` > `0.2.0-rc.1`;
    - a numeric identifier in the suffix compares as a number: `beta.9` < `beta.10`.

    Build metadata is dropped, not ranked last, because the spec says so:
    two versions that differ only in metadata have the same precedence.
    Every caller has to cope with that equality; check_version is where it is met and named.
    """
    major, minor, patch, suffix, _ = SEMVER.match(version).groups()
    if suffix is None:
        return (int(major), int(minor), int(patch), 1, ())

    identifier_keys = tuple(
        (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier) for identifier in suffix.split(".")
    )
    return (int(major), int(minor), int(patch), 0, identifier_keys)


def being_worked_on(version: str) -> bool:
    """Whether SNAPSHOT is one of the dot- or hyphen-separated parts of the pre-release suffix of `version`.

    That covers `1.0.0-SNAPSHOT`, `1.0.0-rc.1-SNAPSHOT` and `1.0.0-SNAPSHOT-SNAPSHOT`.
    The last is what a script makes by appending the marker to a version that has it already.
    version_command strips one marker only, so its candidate still carries the other.
    `preSNAPSHOT` is not the marker.
    Build metadata is not looked at: it names a build, not a state."""
    suffix = SEMVER.match(version).group(4) or ""
    return "SNAPSHOT" in re.split(r"[.-]", suffix)


def core(version: str) -> tuple[int, int, int]:
    major, minor, patch, _, _ = SEMVER.match(version).groups()
    return (int(major), int(minor), int(patch))


def successors(released_core: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """The three cores SemVer allows after `released_core`: one part goes up by one, every part right of it to zero."""
    major, minor, patch = released_core
    return [(major, minor, patch + 1), (major, minor + 1, 0), (major + 1, 0, 0)]


def core_text(parts: tuple[int, int, int]) -> str:
    return "{}.{}.{}".format(*parts)


def check_version(candidate: str, releases: list[str]) -> list[str]:
    """Whether `candidate` may be released, given the releases already tagged."""

    if not SEMVER.match(candidate):
        return [f"'{candidate}' is not a version this project releases"]
    if being_worked_on(candidate):
        return [f"{candidate} is a version being worked on, and a release is precisely what it cannot be"]

    ordered = sorted((version for version in releases if SEMVER.match(version)), key=precedence)
    if not ordered:
        return []  # Nothing to be consistent with; the first release may name itself anything valid.

    problems = []
    finals = [version for version in ordered if SEMVER.match(version).group(4) is None]
    is_final = SEMVER.match(candidate).group(4) is None

    # The base rule: a release has to outrank the last release offered to the same people.
    # An update check, in an IDE or a package manager, offers a release by comparing versions,
    # so a release that does not outrank the last one is offered to nobody.
    # - A final release goes to everyone, so it has to outrank the last final release.
    #   Pre-releases reach only their channel's subscribers, so they do not count here:
    #   a hotfix 0.2.1 may go out while 0.3.0-beta.1 is open, and no channel is offered a downgrade.
    #   That holds only from a branch the train has not reached.
    #   Where the train's sections stand, check_step refuses the hotfix, since it would carry the train's changes.
    # - A pre-release goes to subscribers, who see every release, so it has to outrank the highest tag of all.
    #   So while a train is open, a hotfix cannot be tried on a channel first:
    #   0.2.1-rc.1 sorts below 0.3.0-beta.1 and is refused, while 0.2.1 itself passes.
    to_outrank = finals[-1] if is_final and finals else ordered[-1]
    if precedence(candidate) == precedence(to_outrank) and candidate != to_outrank:
        # Equal precedence with different text can only be build metadata, which SemVer leaves out of ordering.
        # It gets a message of its own: "does not come after" would read as wrong about a version that plainly
        # came later in time. What it does not do is outrank the release.
        problems.append(
            f"{candidate} and {to_outrank} differ only in build metadata, which SemVer leaves out of ordering: "
            f"neither comes after the other, so whoever compares versions is offered no release at all"
        )
        # No step is measured either: the candidate has that release's core,
        # and "does not follow" would be the misleading arithmetic this message replaces.
        return problems
    elif precedence(candidate) <= precedence(to_outrank):
        problems.append(f"{candidate} does not come after {to_outrank}, which is released already")

    # The step is measured from the last *final* release, not from the highest tag.
    # A pre-release train such as 0.2.0-rc.1, 0.2.0-rc.2, 0.2.0 then stays inside one allowed core.
    # Going backwards inside the train is what the check above refuses.
    # An open train also cannot be left for a core the last final release does not allow:
    # after 0.2.0, 0.4.0 is refused whatever 0.3.0-beta.1 says, and 1.0.0 is not.
    # With nothing final released yet, the open train is the only way on:
    # after 0.2.0-rc.1, a later pre-release of 0.2.0, or 0.2.0 itself.
    # Without this, a project that has only ever tagged pre-releases could name any core.
    if finals:
        measured_from, allowed = finals[-1], successors(core(finals[-1]))
    else:
        measured_from, allowed = ordered[-1], [core(ordered[-1])]
    if core(candidate) not in allowed:
        choices = ", ".join(core_text(permitted) for permitted in allowed)
        one_of = "one of " if len(allowed) > 1 else ""
        problems.append(f"{candidate} does not follow {measured_from}: the next version is {one_of}{choices}")

    return problems


def version_after(released: str) -> str:
    """The version that follows `released`, without a marker. It is used two ways:
    - a project that declares its version writes it back as the next one being worked on;
      the source adds the marker, where it has one;
    - a repository versioned by its tags alone offers it as the default when a release is asked for.

    A pre-release moves nothing: `0.2.0-rc.1` was a step towards `0.2.0`, so work goes on towards it.
    A final release is followed by the smallest step, a patch.
    By the time of the release, `[Unreleased]` may ask for more, and check_step holds the release to it:
    - where the source declares a version, whoever lands a feature raises the version to a minor in the same
      pull request, where a reviewer sees the line.
      For a feature that landed while a release was out, that is the pull request carrying the release back,
      and its body says so.
    - where the source declares none, next_candidate moves the default as far as `[Unreleased]` asks.
    """
    major, minor, patch, suffix, _ = SEMVER.match(released).groups()  # Metadata names a build, not what follows it.
    if suffix is not None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{int(patch) + 1}"


def channel_of(version: str) -> str:
    """The distribution channel a version is published to:
    the first identifier of its pre-release suffix, or `default` for a final release.

    - `0.3.0-beta.1` goes to `beta`, and is offered only to whoever subscribed to that channel.
    - `0.3.0` goes to everyone.
    - Identifiers are separated by dots, and a hyphen is an ordinary character inside one:
      `1.0.0-eap.2` names the channel `eap`, and `1.0.0-eap-2` names `eap-2`, a channel per build.
      That is a thing to spell on purpose, not to meet by accident.
    - Build metadata is not part of it: `0.3.0-beta.1+sha.5114f85` goes to `beta`, and `1.0.0+dfsg1` to everyone.

    Such a name is for channels on the JetBrains Marketplace and dist-tags on npm.
    A registry with nothing of the kind gets the same answer; what a pre-release suffix means there is for its
    publishing step to decide.

    Whatever marks a release as a pre-release, or uploads it to a channel, should ask this rather than repeat the
    rule. A project whose own publishing task needs the channel has to repeat the rule there, and keep both alike.
    """
    suffix = SEMVER.match(version).group(4)
    if suffix is None:
        return "default"
    return suffix.split(".")[0]
