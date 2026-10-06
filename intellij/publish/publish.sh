#!/usr/bin/env bash
# Upload an accepted archive to the JetBrains Marketplace, and check that the Marketplace serves it.
# What matters is not that the upload answered 2xx, but that the Marketplace serves the archive that was accepted.
# So the upload's answer is only reported, and what is served decides.
#
# Reads:  PYTHON PUBLISH_TOKEN PLUGIN_ID VERSION ARCHIVE ATTEMPTS WAIT
#         RUNNER_TEMP, or TMPDIR, as the place for the upload's answer and for what the Marketplace serves back
set -uo pipefail

# Checked before anything is uploaded, and before either is used as a number.
# `attempts` goes into the arithmetic of the waiting loop, where bash evaluates it as an expression:
# a name would be read as a variable, and a subscript would run the command it holds.
# Four digits at most: 9999 attempts at the default 30 seconds apart already take more than 83 hours,
# so a longer number is a mistake.
# A `wait` that is no number would leave the attempts with no pause between them.
if [[ ! $ATTEMPTS =~ ^[1-9][0-9]{0,3}$ ]]; then
  echo "::error::attempts is '${ATTEMPTS}', and has to be a whole number from 1 to 9999"
  exit 1
fi
if [[ ! $WAIT =~ ^[0-9]+$ ]]; then
  echo "::error::wait is '${WAIT}', and has to be a whole number of seconds"
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
temp="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"

# The channel is read off the version, by the same rule the draft was marked with, rather than passed in.
# Two places spelling it out could come to disagree.
# And once a release is published, there is no `version` check left to answer it.
channel=$("$PYTHON" "${here}/../../lib/main.py" channel "$VERSION") || exit 1

# A final release sends no channel field.
# The Marketplace takes an empty channel as its default one
# (https://plugins.jetbrains.com/docs/marketplace/plugin-upload.html).
# The Gradle publishPlugin task does the same with `default`: it sends nothing.
channel_field=()
if [[ $channel != default ]]; then
  channel_field=(-F "channel=${channel}")
fi

# The archive is uploaded as it is, through the upload API: the call publishPlugin makes, without the task.
# publishPlugin depends on buildPlugin and signPlugin, so through Gradle the plugin would be built again from source.
# The Marketplace would then get a second build instead of the file that was accepted with the draft.
#
# The upload is deliberately not allowed to fail the run. Its answer is still kept in full.
# The check below covers every way the upload can fail:
# - a version that did not upload is not served;
# - a version somebody uploaded by hand is served, and passes only if it carries the accepted payload.
# Reading what is served, rather than the error message, also means no wording JetBrains may change matters.
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

# A pre-release is served only from the channel its suffix names, so it is asked for there
# (https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html).
# A final release is asked for with no channel at all.
# What check-release calls `default`, the Marketplace serves under no name, and asking for `default` by name is a 404.
# The `+` that opens build metadata is sent encoded.
# It is the one character of a version that means something else in a query: the Marketplace reads it as a space
# and answers 404.
url="https://plugins.jetbrains.com/plugin/download?pluginId=${PLUGIN_ID}&version=${VERSION//+/%2B}"
if [[ $channel != default ]]; then
  url="${url}&channel=${channel}"
fi

# A version may be served a while after it is uploaded, so any answer but 200 is asked again:
# ATTEMPTS attempts in all, WAIT seconds apart.
# An update is served as soon as it is uploaded, counter-signed.
# This holds although JetBrains's approval guidelines say every update is reviewed before it becomes public.
# The IDE offers an update from the default channel to its users only once it is approved; nothing here waits for it.
# A first version is different: a person uploads it, and it is served once it is approved.
# No bounded wait sits through that. Such a run fails, and is run again once the version is approved,
# within the 30 days GitHub allows a run to be re-run.
# https://plugins.jetbrains.com/docs/marketplace/jetbrains-marketplace-approval-guidelines.html
served="${temp}/served.zip"
download_code=000
for (( attempt = 1; attempt <= ATTEMPTS; attempt++ )); do
  download_code=$(curl -sS -L -o "$served" -w '%{http_code}' "$url") || download_code=000
  [[ $download_code == 200 ]] && break
  echo "attempt ${attempt}: HTTP ${download_code}"
  (( attempt < ATTEMPTS )) && sleep "$WAIT"
done

if [[ $download_code != 200 ]]; then
  echo "::error::${VERSION} is not served by the Marketplace (last HTTP ${download_code}). The upload did not" \
       "happen, or this plugin has no listing yet and the first version has to be uploaded by hand: the archive" \
       "the release carries, and once that is approved, run this job again, which GitHub allows for 30 days" \
       "after the run first started."
  exit 1
fi

"$PYTHON" "${here}/payload.py" "$ARCHIVE" "$served"
