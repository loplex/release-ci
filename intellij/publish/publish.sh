#!/usr/bin/env bash
# Upload an accepted archive to the JetBrains Marketplace and hold the Marketplace to it. What the release
# needs to be true is not that the upload answered 2xx, but that the Marketplace ends up serving the archive
# that was accepted - so the upload's answer is reported and the serving is what decides.
#
# Reads:  PUBLISH_TOKEN PLUGIN_ID VERSION ARCHIVE ATTEMPTS WAIT
#         RUNNER_TEMP, or TMPDIR, for somewhere to put the upload's answer and what the Marketplace
#         serves back
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
temp="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"

# The channel is read off the version by the rule the draft was marked with, rather than handed in: two places
# spelling it could come to disagree, and once a release is published there is no `version` check left to
# answer it. The version comes bare, so it is read with no prefix, and under `tags`, which declares nothing: no
# file of the repository is read to answer it.
channel=$(python3 "${here}/../../check-release/check-release.py" --source tags --tag-prefix '' channel "$VERSION") \
  || exit 1

# No channel field for a final release: the Marketplace takes an empty channel as its default one
# (https://plugins.jetbrains.com/docs/marketplace/plugin-upload.html), which is also what the Gradle
# publishPlugin task does with `default` - it sends nothing.
channel_field=()
if [ "$channel" != default ]; then
  channel_field=(-F "channel=${channel}")
fi

# Handed over as it is, over the upload API - the call publishPlugin makes underneath, without the task.
# publishPlugin uploads what buildPlugin and signPlugin make, and it depends on them: through Gradle the
# plugin would be built again from source, and the Marketplace would be handed a second build in place of
# the file that was accepted with the draft.
#
# Deliberately not allowed to fail the run, although the answer is kept in full. Every way this can fail is
# one the check below already answers: a version that did not upload is not served, and a version somebody
# uploaded by hand is served, and passes only if it carries the payload that was accepted. Reading the
# state rather than the error message also means no wording JetBrains may change one day is load-bearing.
answer_file="${temp}/upload-answer.txt"
upload_code=$(curl -sS -o "$answer_file" -w '%{http_code}' \
  -H "Authorization: Bearer ${PUBLISH_TOKEN}" \
  -F "xmlId=${PLUGIN_ID}" \
  -F "family=intellij" \
  -F "file=@${ARCHIVE}" \
  "${channel_field[@]}" \
  https://plugins.jetbrains.com/api/updates/upload) || upload_code=000
echo "upload: HTTP ${upload_code}"
cat "$answer_file" 2>/dev/null; echo
case "$upload_code" in
  2??) ;;
  *) echo "::warning::the upload was answered HTTP ${upload_code}; whether that matters is settled by the" \
          "check below" ;;
esac

# A pre-release is served from the channel its suffix names and from nowhere else, so that is where it is
# asked for (https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html). A final release is
# asked for with no channel at all: what check-release calls `default` the Marketplace serves under no name,
# and asking for `default` by that name is answered 404. The `+` that opens build metadata is the one
# character of a version that means something else in a query - the Marketplace reads it as a space and
# answers 404 - so it is sent encoded.
url="https://plugins.jetbrains.com/plugin/download?pluginId=${PLUGIN_ID}&version=${VERSION//+/%2B}"
if [ "$channel" != default ]; then
  url="${url}&channel=${channel}"
fi

# A version may be served a while after it is uploaded, so a 404 straight after publishing is asked again,
# ATTEMPTS times WAIT apart. An update is served as soon as it is uploaded, counter-signed, although JetBrains's
# approval guidelines say every update is reviewed before it becomes publicly available. A first version is not:
# a person uploads it, and it is served once it is approved, which no bounded wait sits through. A run that
# meets that fails, and is run again once the version is approved, within the 30 days GitHub allows a run to be
# re-run.
# https://plugins.jetbrains.com/docs/marketplace/jetbrains-marketplace-approval-guidelines.html
served="${temp}/served.zip"
download_code=000
for attempt in $(seq 1 "$ATTEMPTS"); do
  download_code=$(curl -sS -L -o "$served" -w '%{http_code}' "$url") || download_code=000
  [ "$download_code" = 200 ] && break
  echo "attempt ${attempt}: HTTP ${download_code}"
  [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$WAIT"
done

if [ "$download_code" != 200 ]; then
  echo "::error::${VERSION} is not served by the Marketplace (last HTTP ${download_code}). The upload did not" \
       "happen, or this plugin has no listing yet and the first version has to be uploaded by hand: the archive" \
       "the release carries, and once that is approved, run this job again, which GitHub allows for 30 days" \
       "after the run first started."
  exit 1
fi

python3 "${here}/payload.py" "$ARCHIVE" "$served"
