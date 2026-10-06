#!/usr/bin/env python3
"""What every action.yml this repository tracks has to be true of, read as text.

Run with `python3 -m unittest discover -s .github` from the repository's root, with the packages in
`lib/requirements.txt` and `.github/requirements.txt` installed.
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
    "intellij/check/action.yml": set(),
    "intellij/publish/action.yml": {"plugin-id", "version", "archive", "token"},
    "release-flow/draft/action.yml": {"version", "tag", "branch"},
    "release-flow/merge-back/action.yml": {"version-source", "tag", "default-branch", "check-workflow"},
    "release-flow/prepare/action.yml": {"version-source"},
    "release-flow/warn/action.yml": {"tag", "outcome", "to"},
}

# The actions that run Python, each on the one it installs (see the test below).
RUNS_PYTHON = {
    "check-release/action.yml",
    "intellij/build/action.yml",
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
        - A step that runs Python without `PYTHON` fails on the unset variable.
        - A setup-python left to update the environment changes the python3 of the calling job's later steps.
        - Without LD_LIBRARY_PATH, that Python does not start in a job that runs in a container.
        The last two hold for each step that runs Python, itself or through a script; a Gradle step needs neither."""
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
            python_scripts = {path.name for path in here.glob("*.sh") if "$PYTHON" in path.read_text(encoding="utf-8")}
            for step in re.split(r"^    - ", text[text.index("\n  steps:\n"):], flags=re.MULTILINE)[1:]:
                step = "    - " + step
                block = "\n".join(run_blocks(step))
                if "$PYTHON" not in block and not any(f"/{name}" in block for name in python_scripts):
                    continue
                self.assertIn("        PYTHON: ${{ steps.python.outputs.python-path }}\n", step, manifest)
                self.assertIn(LIBRARY_PATH, block, f"{manifest}: {block}")
        self.assertEqual(runs_python, RUNS_PYTHON)

    def test_an_action_hands_its_jdk_only_to_its_gradle_steps(self):
        """setup-java left to set the default changes JAVA_HOME and java for the calling job's later steps.
        With `set-default: false` nothing does, so every step that runs Gradle names the JDK in its own `env:`."""
        sets_up_java = 0
        for manifest in MANIFESTS:
            text = (ROOT / manifest).read_text(encoding="utf-8")
            if "actions/setup-java@" not in text:
                continue
            sets_up_java += 1
            self.assertRegex(text, r"    - id: java\n      uses: actions/setup-java@\S+\n      with:\n"
                                   r"(?:        .*\n)*?        set-default: false\n", manifest)
            steps = re.split(r"\n    - ", text[text.index("\nruns:"):])
            gradle = [step for step in steps if "./gradlew" in step]
            self.assertTrue(gradle, manifest)
            for step in gradle:
                self.assertIn("        JAVA_HOME: ${{ steps.java.outputs.path }}\n", step, f"{manifest}: {step}")
        self.assertEqual(sets_up_java, 2)

    def test_intellij_check_runs_the_checks_intellij_build_runs_before_it_signs(self):
        """intellij/check writes out intellij/build's steps again, since a composite action can call another only
        by a ref. Step for step, comments aside, they are the same, but for what only a release does:
        the Python, the change notes and their page, signing, and the archive.
        The inputs intellij/check has default to what they default to in intellij/build."""
        def steps(manifest):
            text = (ROOT / manifest).read_text(encoding="utf-8")
            found = []
            for step in re.split(r"^    - ", text[text.index("\n  steps:\n"):], flags=re.MULTILINE)[1:]:
                lines = [line for line in step.splitlines() if line.strip() and not line.lstrip().startswith("#")
                         and "CHANGE_NOTES" not in line]
                found.append("\n".join(lines).replace("run: |\n        ./gradlew", "run: ./gradlew")
                             .replace("$GITHUB_ACTION_PATH/../build/", "$GITHUB_ACTION_PATH/"))
            return found
        release_only = ("actions/setup-python@", "notes.sh", "steps.notes.outputs.preview", "signPlugin", "archive.sh",
                        "check-archive.py")
        build = [step for step in steps("intellij/build/action.yml") if not any(only in step for only in release_only)]
        self.assertEqual(steps("intellij/check/action.yml"), build)

        def defaults(manifest):
            return dict(re.findall(r"^  ([\w-]+):\n(?:    .*\n|\n)*?    default: (.*)$",
                                   (ROOT / manifest).read_text(encoding="utf-8"), re.MULTILINE))
        check = defaults("intellij/check/action.yml")
        self.assertEqual(sorted(check), ["free-disk-space", "java-distribution", "java-version"])
        self.assertEqual(check, {name: default for name, default in defaults("intellij/build/action.yml").items()
                                 if name in check})

    def test_intellij_build_hands_change_notes_only_where_asked(self):
        """The notes step runs only with change-notes on, and its output reaches every Gradle step under the action's
        own name, becoming CHANGE_NOTES, in the C.UTF-8 locale, only where it is not empty.
        The archive check reads it as CHANGE_NOTES, so that a job's own CHANGE_NOTES is not checked.
        Python writes and reads the notes as UTF-8 whatever the locale.
        Their page is uploaded unzipped, so that a browser opens it, and only with change-notes on too."""
        text = (ROOT / "intellij/build/action.yml").read_text(encoding="utf-8")
        steps = re.split(r"^    - ", text[text.index("\n  steps:\n"):], flags=re.MULTILINE)[1:]
        self.assertRegex(text, r"\n  change-notes:\n(?:    .*\n|\n)*?    default: 'false'\n")
        notes = [step for step in steps if "notes.sh" in step]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("id: notes\n      if: inputs.change-notes == 'true'\n"), notes[0])
        self.assertIn('"$PYTHON" -X utf8 "$here/change-notes.py"',
                      (ROOT / "intellij/build/notes.sh").read_text(encoding="utf-8"))
        gradle = [step for step in steps if "./gradlew" in step]
        self.assertEqual(len(gradle), 3)
        for step in gradle:
            self.assertIn("        RELEASE_CI_CHANGE_NOTES: ${{ steps.notes.outputs.html }}\n", step)
            self.assertIn("        [[ -z $RELEASE_CI_CHANGE_NOTES ]] || "
                          "export CHANGE_NOTES=$RELEASE_CI_CHANGE_NOTES LC_ALL=C.UTF-8\n", step)
            self.assertNotRegex(step, r"\n        CHANGE_NOTES:")
        check = [step for step in steps if "check-archive.py" in step]
        self.assertEqual(len(check), 1)
        self.assertIn("        CHANGE_NOTES: ${{ steps.notes.outputs.html }}\n", check[0])
        self.assertIn('"$PYTHON" -X utf8 "$GITHUB_ACTION_PATH/check-archive.py"', check[0])
        page = [step for step in steps if "steps.notes.outputs.preview" in step]
        self.assertEqual(len(page), 1)
        self.assertTrue(page[0].startswith("if: inputs.change-notes == 'true'\n      uses: actions/upload-artifact@"),
                        page[0])
        self.assertIn("        archive: false\n", page[0])


if __name__ == "__main__":
    unittest.main()
