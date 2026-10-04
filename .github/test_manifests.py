#!/usr/bin/env python3
"""What every action.yml this repository tracks has to be true of, read as text.

Run with `python3 -m unittest discover -s .github` from the repository's root, with the packages in
`.github/requirements.txt` installed.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = sorted(subprocess.run(["git", "ls-files", "-z", "--", "*/action.yml"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.split("\0")[:-1])

# The inputs each action marks `required: true`, which every workflow that uses it has to pass.
REQUIRED = {
    "check-release/action.yml": {"version-source"},
    "intellij/build/action.yml": {"certificate-chain", "private-key", "private-key-password"},
    "intellij/publish/action.yml": {"plugin-id", "version", "archive", "token"},
    "release-flow/draft/action.yml": {"version", "tag", "branch"},
    "release-flow/merge-back/action.yml": {"version-source", "tag", "default-branch", "check-workflow"},
    "release-flow/prepare/action.yml": {"version-source"},
    "release-flow/warn/action.yml": {"tag", "outcome", "to"},
}

# The actions that run Python, each on the one it installs (see the test below).
RUNS_PYTHON = {
    "check-release/action.yml",
    "intellij/publish/action.yml",
    "release-flow/draft/action.yml",
    "release-flow/merge-back/action.yml",
    "release-flow/prepare/action.yml",
    "release-flow/warn/action.yml",
}
PYTHON_STEP = re.compile(r"^    - id: python\n"
                         r"      uses: actions/setup-python@\S+\n"
                         r"      with:\n"
                         r"        python-version-file: \$\{\{ github\.action_path \}\}/"
                         r"(?P<up>[./]+)/\.python-version\n"
                         r"        update-environment: false\n", re.MULTILINE)

LIBRARY_PATH = 'export LD_LIBRARY_PATH="${PYTHON%/bin/*}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"'


def run_blocks(text):
    """Each `run:` script in a manifest, a `run: |` block whole."""
    blocks = []
    for run in re.finditer(r"^( *)run: (.*)\n", text, re.MULTILINE):
        if run.group(2) != "|":
            blocks.append(run.group(2))
            continue
        lines = []
        for line in text[run.end():].splitlines():
            if line.strip() and len(line) - len(line.lstrip()) <= len(run.group(1)):
                break
            lines.append(line)
        blocks.append("\n".join(lines))
    return blocks


def required(manifest):
    """The inputs a manifest marks `required: true`; a `required:` holding anything but `true` or `false` fails."""
    inputs = re.search(r"^inputs:\n((?:\n|[ #].*\n)*)", (ROOT / manifest).read_text(encoding="utf-8"), re.MULTILINE)
    names, name = set(), None
    for line in inputs.group(1).splitlines() if inputs else ():
        if key := re.fullmatch(r"  ([\w-]+):\s*", line):
            name = key.group(1)
        elif flag := re.fullmatch(r"    required:\s*(.*?)\s*", line):
            if flag.group(1) not in ("true", "false"):
                raise ValueError(f"{manifest}: input {name}: required: {flag.group(1)}")
            if flag.group(1) == "true":
                names.add(name)
    return names


class Manifests(unittest.TestCase):

    def test_an_expression_stands_only_as_a_value(self):
        """GitHub evaluates `${{ }}` wherever it stands in action.yml, including a description's text.
        One it cannot evaluate there fails every step that uses the action, before anything runs.
        In a `run:` script it would be pasted into the code, which is why inputs reach the scripts through `env:`."""
        self.assertTrue(MANIFESTS)
        for manifest in MANIFESTS:
            for number, line in enumerate((ROOT / manifest).read_text(encoding="utf-8").splitlines(), 1):
                if "${{" in line and not line.lstrip().startswith("#"):
                    self.assertRegex(line, r"^\s*(?!description:|run:)[A-Za-z_][\w-]*:\s*\$\{\{",
                                     f"{manifest}:{number}: {line}")

    def test_a_change_to_the_required_inputs_is_made_on_purpose(self):
        """An input that becomes required breaks every caller whose workflow does not pass it when its pin moves.
        A workflow started by a release runs from the file in the commit the release tags.
        So a release cut before the workflow passes the input runs without it, however often it is run again.
        CHANGELOG.md marks such an input **BREAKING**, saying a caller has to pass it, before REQUIRED is updated.
        GitHub does not enforce `required`, so this checks what a manifest promises.
        Refusing an input that was left out is up to each script."""
        self.assertEqual(sorted(REQUIRED), MANIFESTS)
        for manifest in MANIFESTS:
            with self.subTest(manifest):
                self.assertEqual(required(manifest), REQUIRED[manifest])

    def test_an_action_runs_python_only_on_the_one_it_installs(self):
        """The actions run on the Python .python-version names, whatever python3 the caller's runner carries.
        - A `python3` in a script or a `run:` would take the runner's instead.
        - A step that runs the scripts without `PYTHON` fails on the unset variable.
        - A setup-python left to update the environment changes the python3 of the calling job's later steps.
        - Without LD_LIBRARY_PATH, that Python does not start in a job that runs in a container."""
        runs_python = set()
        for manifest in MANIFESTS:
            text = (ROOT / manifest).read_text(encoding="utf-8")
            here = (ROOT / manifest).parent
            scripts = [path.read_text(encoding="utf-8") for path in sorted(here.glob("*.sh"))]
            code = [line for block in scripts + run_blocks(text) for line in block.splitlines()
                    if not line.lstrip().startswith("#")]
            for line in code:
                self.assertNotRegex(line, r"\bpython3?\b", f"{manifest}: {line}")
            if "$PYTHON" not in text and not any("$PYTHON" in script for script in scripts):
                continue
            runs_python.add(manifest)
            step = PYTHON_STEP.search(text)
            self.assertIsNotNone(step, f"{manifest}: no setup-python step with update-environment: false")
            version_file = (here / step.group("up") / ".python-version").resolve()
            self.assertEqual(version_file, ROOT / ".python-version", manifest)
            for env in re.findall(r"^      env:\n((?:        .*\n)+)", text, re.MULTILINE):
                self.assertIn("        PYTHON: ${{ steps.python.outputs.python-path }}\n", env, manifest)
            for block in run_blocks(text):
                self.assertIn(LIBRARY_PATH, block, f"{manifest}: {block}")
        self.assertEqual(runs_python, RUNS_PYTHON)


if __name__ == "__main__":
    unittest.main()
