#!/usr/bin/env bash
# Runs this repository's five test suites at once, each split over several processes:
# the tests CONTRIBUTING.md runs with five commands, one after another, answered in a fraction of the time.
# CI runs those five commands.
# It tests the checkout it is run in, from anywhere inside it, which need not be the checkout it comes from.
#
# Reads:  PYTHON  the interpreter, python3 by default, with the packages CONTRIBUTING.md installs
# Prints one line per suite, then the whole output of every red one; exits 1 when any suite is red.
#
# A suite's tests are run as `unittest discover -s <suite>` runs them, from the suite's directory,
# dealt out in turn to as many processes as there are cores.
# That is safe because the tests share nothing: each builds what it needs in a temporary directory of its own,
# and no suite has a setUpClass or a setUpModule.
# pytest-xdist does the same for pytest; it is not used, so that running the tests needs no package of its own.
set -u

python=${PYTHON:-python3}
tree=$(git rev-parse --show-toplevel) || exit 1
processes=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
suites=(lib check-release release-flow intellij .github)

for suite in "${suites[@]}"; do
  # An older commit may not have the suite yet; that is no failure.
  [[ -d $tree/$suite ]] || continue
  name=${suite#.}
  # A module that does not import is left out of the list, its error in the suite's log, and the suite is red.
  (cd "$tree/$suite" && "$python" -c '
import sys
import unittest

def ids(tests):
    for test in tests:
        if isinstance(test, unittest.TestSuite):
            yield from ids(test)
        elif not test.id().startswith("unittest.loader._FailedTest."):
            yield test.id()

loader = unittest.TestLoader()
print("\n".join(ids(loader.discover(".", top_level_dir="."))))
print("".join(loader.errors), end="", file=sys.stderr)
sys.exit(1 if loader.errors else 0)
') > "$work/$name.ids" 2> "$work/$name.log"
  echo $? > "$work/$name.rc"
  awk -v n="$processes" -v to="$work/$name.part-" 'NF { print > (to (NR % n) ".ids") }' "$work/$name.ids"
  for part in "$work/$name".part-*.ids; do
    [[ -e $part ]] || continue
    (cd "$tree/$suite" && xargs "$python" -m unittest < "$part" > "${part%.ids}.log" 2>&1
     echo $? > "${part%.ids}.rc") &
  done
done
wait

red=()
for suite in "${suites[@]}"; do
  if [[ ! -d $tree/$suite ]]; then
    echo "$suite: absent"
    continue
  fi
  name=${suite#.}
  rc=$(cat "$work/$name.rc")
  for part in "$work/$name".part-*.ids; do
    [[ -e $part ]] || continue
    [[ $(cat "${part%.ids}.rc") == 0 ]] || rc=1
    { echo "== ${part##*/}"; cat "${part%.ids}.log"; } >> "$work/$name.log"
  done
  listed=$(grep -c . "$work/$name.ids")
  ran=$(cat "$work/$name".part-*.log 2>/dev/null | awk '/^Ran [0-9]+ tests? in / { sum += $2 } END { print sum + 0 }')
  # Every test listed has to have run, so that a part lost on the way cannot pass for a green suite.
  if [[ $rc == 0 && $ran == "$listed" ]]; then
    echo "$suite: OK, $ran tests"
  else
    red+=("$suite")
    echo "$suite: FAILED, $ran of $listed tests ran"
  fi
done

for suite in "${red[@]}"; do
  echo
  echo "===== $suite"
  cat "$work/${suite#.}.log"
done
[[ ${#red[@]} == 0 ]]
