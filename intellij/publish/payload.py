#!/usr/bin/env python3
"""Whether two plugin archives carry the same payload, which is what survives being signed.

A signature is not appended to a zip. It sits in a block of its own between the entry data and the central
directory, and writing it rewrites the central directory and the end-of-central-directory record with it. The
Marketplace counter-signs what it is given, so the file it serves can never be byte-identical to the file that
was accepted - and it would differ again every time the certificate behind it changed, which is not a defect
either. What a signature leaves alone is every entry's name, size and CRC, so that is what can be held to.

Run as `payload.py accepted.zip served.zip`: says so and exits 0 where the two agree, and names what differs
and exits 1 where they do not.
"""

import sys
import zipfile


def payload(path: str) -> list[tuple[str, int, int]]:
    """Every entry's name, uncompressed size and CRC, sorted. Not the compressed size: recompressing at
    another level changes it while the entry is the same bytes, and the Marketplace is entitled to do that."""
    with zipfile.ZipFile(path) as archive:
        return sorted((entry.filename, entry.file_size, entry.CRC) for entry in archive.infolist())


def differences(accepted: list[tuple[str, int, int]], served: list[tuple[str, int, int]]) -> list[str]:
    """What one archive has that the other does not, and what they both have but differently. Named entry by
    entry rather than counted, because the answer a reader needs is which file to go and look at.

    A zip may hold one name more than once, so each name is held to every entry carrying it: a name kept once
    would let an archive with an entry twice pass for one that has it once."""
    found = []
    ours, theirs = {}, {}
    for entries, by_name in ((accepted, ours), (served, theirs)):
        for name, size, crc in entries:
            by_name.setdefault(name, []).append((size, crc))
    for name in sorted(set(ours) - set(theirs)):
        found.append(f"only the accepted archive has {name}")
    for name in sorted(set(theirs) - set(ours)):
        found.append(f"only the served archive has {name}")
    for name in sorted(set(ours) & set(theirs)):
        if len(ours[name]) != len(theirs[name]):
            found.append(f"{name} is in the accepted archive {len(ours[name])} time(s) and in the served one "
                         f"{len(theirs[name])}")
        elif ours[name] != theirs[name]:
            (size, crc), (other_size, other_crc) = next(
                pair for pair in zip(ours[name], theirs[name]) if pair[0] != pair[1])
            found.append(f"{name} differs: accepted {size}B/{crc:08x}, served {other_size}B/{other_crc:08x}")
    return found


def main() -> int:
    # What is served back can be something other than an archive - a page of HTML answered 200 - and that is
    # said as the finding it is rather than as a traceback.
    try:
        accepted, served = (payload(path) for path in sys.argv[1:3])
    except zipfile.BadZipFile as refused:
        print(f"::error::what was compared is not a zip archive ({refused}), so there is no payload to hold "
              f"the Marketplace to", file=sys.stderr)
        return 1
    found = differences(accepted, served)
    if not found:
        print(f"The Marketplace serves the accepted payload: {len(accepted)} entries, all matching.")
        return 0
    for line in found:
        print(line, file=sys.stderr)
    print("::error::the Marketplace is not serving the payload that was accepted", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
