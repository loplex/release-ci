#!/usr/bin/env python3
"""Whether two plugin archives carry the same payload, which is what survives being signed.

A signature is not appended to a zip. It sits in a block of its own between the entry data and the central
directory, and writing it moves the central directory along and rewrites the one offset pointing at it, in the
end-of-central-directory record. The Marketplace counter-signs what it is given
(https://plugins.jetbrains.com/docs/intellij/plugin-signing.html), so the file it serves can never be
byte-identical to the file that was accepted - and it would differ again every time the certificate behind it
changed, which is not a defect either. What a signature leaves alone is every entry's name, size and CRC, so
that is what can be held to.

Run as `payload.py accepted.zip served.zip`: says so and exits 0 where the two agree, and names what differs
and exits 1 where they do not.
"""

import sys
import zipfile


def payload(path: str) -> list[tuple[str, int, int]]:
    """Every entry's name, uncompressed size and CRC, sorted. Not the compressed size: it is not payload, and
    the same bytes stored at another level of compression are the same entry."""
    with zipfile.ZipFile(path) as archive:
        return sorted((entry.filename, entry.file_size, entry.CRC) for entry in archive.infolist())


def differences(accepted: list[tuple[str, int, int]], served: list[tuple[str, int, int]]) -> list[str]:
    """What one archive has that the other does not, and what they both have but differently. Named entry by
    entry rather than counted, because the answer a reader needs is which file to go and look at.

    A zip may hold one name more than once, so each name is held to every entry carrying it: a name kept once
    would let an archive with an entry twice pass for one that has it once."""
    found = []
    accepted_by_name, served_by_name = {}, {}
    for entries, by_name in ((accepted, accepted_by_name), (served, served_by_name)):
        for name, size, crc in entries:
            by_name.setdefault(name, []).append((size, crc))
    for name in sorted(set(accepted_by_name) - set(served_by_name)):
        found.append(f"only the accepted archive has {name}")
    for name in sorted(set(served_by_name) - set(accepted_by_name)):
        found.append(f"only the served archive has {name}")
    for name in sorted(set(accepted_by_name) & set(served_by_name)):
        if len(accepted_by_name[name]) != len(served_by_name[name]):
            found.append(f"{name} is in the accepted archive {len(accepted_by_name[name])} time(s) and in the "
                         f"served one {len(served_by_name[name])}")
        elif accepted_by_name[name] != served_by_name[name]:
            (accepted_size, accepted_crc), (served_size, served_crc) = next(
                pair for pair in zip(accepted_by_name[name], served_by_name[name]) if pair[0] != pair[1])
            found.append(f"{name} differs: accepted {accepted_size}B/{accepted_crc:08x}, "
                         f"served {served_size}B/{served_crc:08x}")
    return found


def main() -> int:
    # What is served back can be something other than an archive - a page of HTML answered 200 - and that is
    # said as the finding it is rather than as a traceback.
    try:
        accepted, served = (payload(path) for path in sys.argv[1:3])
    except zipfile.BadZipFile as error:
        print(f"::error::what was compared is not a zip archive ({error}), so there is no payload to hold "
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
