#!/usr/bin/env bash
# Upload an accepted archive to the JetBrains Marketplace and hold the Marketplace to it. What the release
# needs to be true is not that the upload answered 2xx, but that the Marketplace ends up serving the archive
# that was accepted - so the upload's answer is reported and the serving is what decides.
#
# Reads:  PUBLISH_TOKEN PLUGIN_ID VERSION ARCHIVE ATTEMPTS WAIT
#         RUNNER_TEMP, or TMPDIR, for somewhere to put what the Marketplace serves back
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"

# The channel is read off the version by the rule the draft was marked with, rather than handed in: two places
# spelling it could come to disagree, and once a release is published there is no `version` check left to
# answer it. The version comes bare, so neither a source nor a prefix has anything to add to the reading - the
# tag source with no prefix is the one that reads nothing else.
channel=$(python3 "${here}/../../check-release/check-release.py" --source tags --tag-prefix '' channel "$VERSION") \
  || exit 1

# No channel field for a final release: the Marketplace takes an empty channel as its default one, which is
# also what the Gradle publishPlugin task does with `default` - it sends nothing.
field=()
if [ "$channel" != default ]; then
  field=(-F "channel=${channel}")
fi

# Handed over as it is, over the upload API - the call publishPlugin makes underneath, without the task.
# publishPlugin depends on buildPlugin and signPlugin, and signPlugin writes to the very path the accepted
# archive sits at: through Gradle the archive would be rebuilt from source and overwritten before it was
# read, and the Marketplace would be handed a second build in place of the file that was accepted.
#
# Deliberately not allowed to fail the run, although the answer is kept in full. Every way this can fail is
# one the check below already answers: a version that did not upload is not served, and a version somebody
# uploaded by hand is served and matches. Reading the state rather than the error message also means no
# wording JetBrains may change one day is load-bearing.
answer="${work}/upload-answer.txt"
code=$(curl -sS -o "$answer" -w '%{http_code}' \
  -H "Authorization: Bearer ${PUBLISH_TOKEN}" \
  -F "xmlId=${PLUGIN_ID}" \
  -F "family=intellij" \
  -F "file=@${ARCHIVE}" \
  "${field[@]}" \
  https://plugins.jetbrains.com/api/updates/upload) || code=000
echo "upload: HTTP ${code}"
cat "$answer" 2>/dev/null; echo
case "$code" in
  2??) ;;
  *) echo "::warning::the upload was answered HTTP ${code}; whether that matters is settled by the check below" ;;
esac

# A pre-release is served from the channel its suffix names and from nowhere else, so that is where it is
# asked for. A final release is asked for with no channel at all: what check-release calls `default` the
# Marketplace serves under no name, and asking for `default` by that name is answered 404.
url="https://plugins.jetbrains.com/plugin/download?pluginId=${PLUGIN_ID}&version=${VERSION}"
if [ "$channel" != default ]; then
  url="${url}&channel=${channel}"
fi

# An upload is not servable the instant it is taken, so a 404 straight after publishing says "not yet" as
# often as it says "not there". An update to a listed plugin is served without anyone reviewing it, so this
# is cover for a slow Marketplace and not for a review - a plugin's very first version is reviewed by a
# person, and no bounded wait would sit through that. A version that never appears still fails, only later.
served="${work}/served.zip"
code=000
for attempt in $(seq 1 "$ATTEMPTS"); do
  code=$(curl -sS -L -o "$served" -w '%{http_code}' "$url") || code=000
  [ "$code" = 200 ] && break
  echo "attempt ${attempt}: HTTP ${code}"
  [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$WAIT"
done

if [ "$code" != 200 ]; then
  echo "::error::${VERSION} is not served by the Marketplace (last HTTP ${code}). Either the upload did not" \
       "happen, or this plugin has no listing yet and the first version has to be uploaded by hand."
  exit 1
fi

python3 "${here}/payload.py" "$ARCHIVE" "$served"
