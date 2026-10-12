#!/usr/bin/env python3
"""The plugin's change notes: the section of CHANGELOG.md for the version the release is made of, as HTML.

It is `lib/main.py notes <version> --html`, with the version read from the line release-flow/prepare wrote,
in the source it recorded in the release commit checked out (see lib/main.py's built_version()).
It needs the packages in lib/requirements.txt.
Run in the root of the plugin's repository.

Usage: change-notes.py <repository-url> <ref> [--page]
- Every relative link in the notes is made absolute, read at <ref> in <repository-url>: the release's tag for the
  notes the build gets, a commit for a page to look at before the tag exists.
- --page prints a whole HTML page around the notes, which a browser shows as UTF-8.
"""

import contextlib
import html
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import main  # noqa: E402  (lib/main.py, found through the line above)

if __name__ == "__main__":
    main.in_utf8_mode()
    if len(sys.argv) not in (3, 4) or sys.argv[3:] not in ([], ["--page"]):
        sys.exit("usage: change-notes.py <repository-url> <ref> [--page]")
    repository_url, ref, *page = sys.argv[1:]
    _, version = main.built_version()
    sys.argv = [sys.argv[0], "notes", version, "--html", "--repository-url", repository_url, "--ref", ref]
    if not page:
        sys.exit(main.main())
    notes = io.StringIO()
    with contextlib.redirect_stdout(notes):
        status = main.main()
    if status:
        sys.exit(status)
    print(f'<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
          f"<title>Change notes of {html.escape(version)}</title>\n"
          f"<p><i>The change notes of {html.escape(version)}, their relative links read at {html.escape(ref)}.</i>"
          "</p>\n"
          f"{notes.getvalue()}</html>")
