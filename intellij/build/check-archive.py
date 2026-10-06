#!/usr/bin/env python3
"""Whether the signed archive is the release the build was asked for.

Its plugin.xml has to carry the version in the `version` line of gradle.properties, which release-flow/prepare wrote.
The archive gets whatever version the plugin's build script gives it, and nothing else holds the script to that line.
A plugin that took its version from anywhere else would pass the build and the draft at the old version.
It would show only after the release was published, as a version the Marketplace never serves.

Where CHANGE_NOTES is not empty, the build was handed change notes in it, and its plugin.xml has to carry exactly those.
The IntelliJ Platform Gradle Plugin writes them into a CDATA section as given, but for the last line break,
so white space at the ends is not compared.

Run as `check-archive.py <archive>` in the root of the plugin's repository, after signPlugin.
Where the archive is right, it says so and exits 0.
Where it is not, it says what differs and exits 1.
"""

import io
import os
import sys
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import main  # noqa: E402  (lib/main.py, found through the line above)

PLUGIN_XML = "META-INF/plugin.xml"


def plugin_xml(archive: str) -> tuple[str, bytes]:
    """Where the archive's plugin.xml is, and what it holds.

    A plugin is a zip holding `<name>/lib/*.jar`, one of which carries the plugin.xml, or a jar carrying it itself.
    Exactly one has to: with two, the one read here need not be the one the IDE reads."""
    try:
        with zipfile.ZipFile(archive) as outer:
            if PLUGIN_XML in outer.namelist():
                return PLUGIN_XML, outer.read(PLUGIN_XML)
            found = []
            for name in outer.namelist():
                path = PurePosixPath(name)
                if path.suffix == ".jar" and len(path.parts) == 3 and path.parts[1] == "lib":
                    with zipfile.ZipFile(io.BytesIO(outer.read(name))) as jar:
                        if PLUGIN_XML in jar.namelist():
                            found.append((f"{name}!/{PLUGIN_XML}", jar.read(PLUGIN_XML)))
    except zipfile.BadZipFile as error:
        raise SystemExit(f"{archive}: {error}") from None
    if len(found) != 1:
        raise SystemExit(f"{archive}: {len(found)} jars under <name>/lib/ hold a {PLUGIN_XML}, and a plugin has one"
                         + "".join(f": {where}" for where, _ in found))
    return found[0]


def problems(archive: str, version: str) -> list[str]:
    """What in the archive is not what the release asked for, with `version` the one gradle.properties names."""
    where, text = plugin_xml(archive)
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        return [f"{where} is not XML: {error}"]
    wrong = []
    found = root.findtext("version")
    if found != version:
        says = "has no <version>" if found is None else f"says version {found}"
        wrong.append(f"{where} {says}, and gradle.properties {version}: the build script has to take the plugin's "
                     "version from the `version` line of gradle.properties, which release-flow/prepare wrote")
    notes = os.environ.get("CHANGE_NOTES", "")
    held = root.findtext("change-notes")
    if notes and (held or "").strip() != notes.strip():
        reads = 'the build script has to set changeNotes = providers.environmentVariable("CHANGE_NOTES") in ' \
                "pluginConfiguration"
        if held is None:
            wrong.append(f"{where} has no <change-notes>, though the build was handed CHANGE_NOTES: {reads}")
        else:
            wrong.append(f"{where} holds other <change-notes> than the CHANGE_NOTES the build was handed: {reads}, "
                         "and the system has to have the C.UTF-8 locale Gradle runs in")
    return wrong


def run(archive: str) -> int:
    try:
        version = main.declared_version("gradle.properties")
        found = problems(archive, version)
    except SystemExit as refusal:
        found = [str(refusal.code)]
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print(f"{archive} is version {version}, as gradle.properties says"
              + (", with the change notes it was built with" if os.environ.get("CHANGE_NOTES") else ""))
    return 1 if found else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-archive.py <archive>")
    sys.exit(run(sys.argv[1]))
