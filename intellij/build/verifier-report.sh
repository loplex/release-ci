#!/usr/bin/env bash
# Stop a build whose verifyPlugin left no report. Under the Gradle IntelliJ Plugin 1.x, `verifyPlugin` checks
# plugin.xml and the archive's structure, never runs the Plugin Verifier, and passes; so does a build writing the
# report elsewhere, a plugin in a subproject writing it under that subproject. Neither leaves a report in
# build/reports/pluginVerifier under the working directory, and a release is not let through as verified by a
# check that did not run. Kept out of action.yml so that it can be run in a test.
set -uo pipefail

if [ -z "$(ls -A build/reports/pluginVerifier 2>/dev/null)" ]; then
  echo "::error::verifyPlugin left no report in build/reports/pluginVerifier: the build script is not on" \
       "the IntelliJ Platform Gradle Plugin 2.x, whose verifyPlugin runs the Plugin Verifier, or it" \
       "writes the report elsewhere"
  exit 1
fi
