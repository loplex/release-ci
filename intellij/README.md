# intellij

The one ecosystem so far, in two actions: `intellij/build`, which goes between `release-flow/prepare`
and `release-flow/draft`, and `intellij/publish`, which goes after the draft has been published, beside
`release-flow/merge-back`. Both are pinned the way [What is here](../README.md#what-is-here) says, which also lists
what `intellij/publish` needs of the runner.

## intellij/build

[`intellij/build`](build/action.yml) runs the project's own Gradle tasks through `./gradlew`:
`check`, then the Plugin Verifier - the check the Marketplace [runs
itself](https://plugins.jetbrains.com/docs/marketplace/understanding-plugin-security.html), run here
first and on the very commit that will be published - then `signPlugin`, and it says where the signed
archive landed. The Plugin Verifier's report is kept as the run's `pluginVerifier-result` artifact,
whether it passed or not. The build script has to be on the IntelliJ Platform Gradle Plugin 2.x: under
the Gradle IntelliJ Plugin 1.x, `verifyPlugin` checks only `plugin.xml` and the archive's structure and
the Plugin Verifier never runs, so a build that finds no report stops there. The report is looked for
in `build/reports/pluginVerifier` under the workspace, so the plugin has to be the build's root
project: one in a subproject writes its report under that subproject, and the build stops there as
well. Gradle is cached by setup-gradle's open-source `basic` provider rather than its default one, a
proprietary component under Gradle's own [terms of use](https://gradle.com/legal/terms-of-use/), which
a caller would otherwise accept unasked. The signing inputs reach `signPlugin` as the environment
variables `CERTIFICATE_CHAIN`, `PRIVATE_KEY` and `PRIVATE_KEY_PASSWORD`, which the build script's
`signing` block has to read. No version is handed to the build: the archive carries whatever version
the build script gives it. A plugin's release runs with `source: gradle.properties`, the file carrying
the `version` and `tagPrefix` lines [Where the version comes from](../check-release/README.md#where-the-version-comes-from)
names, and `release-flow/prepare` rewrites that `version` line, so the plugin has to take its version
from there, `project.version`, rather than from a property of its own, or the archive goes out under
the version it had before.

```yaml
# In the release job under release-flow/prepare, after prepare (`id: cut`) and in place of its draft step:
- uses: loplex/release-ci/intellij/build@<tag>
  id: built
  with:
    certificate-chain: ${{ secrets.CERTIFICATE_CHAIN }}
    private-key: ${{ secrets.PRIVATE_KEY }}
    private-key-password: ${{ secrets.PRIVATE_KEY_PASSWORD }}
- uses: loplex/release-ci/release-flow/draft@<tag>
  with:
    source: gradle.properties
    version: ${{ steps.cut.outputs.version }}
    tag: ${{ steps.cut.outputs.tag }}
    branch: ${{ steps.cut.outputs.branch }}
    files: ${{ steps.built.outputs.archive }}
```

The draft attaches what the build says it signed, rather than a pattern of its own: the build finds the
archive by its own `archive-pattern`, and two patterns written out separately can come to disagree,
where the one that matters is the file that was signed. The `files` pattern in the `release` job under
[release-flow/prepare](../release-flow/README.md#release-flowprepare) is for a build that does not say which file it made.

## intellij/publish

[`intellij/publish`](publish/action.yml) does not trust its own upload. The archive a published
draft carried is the accepted one, and what a release needs to be true is that the Marketplace ends up
serving it, so that is asked of the Marketplace itself, and the answer is compared **by payload rather
than by bytes**: the Marketplace
[counter-signs](https://plugins.jetbrains.com/docs/intellij/plugin-signing.html) what it is given, and a
signature sits in a block of its own between the entry data and the central directory, moving the
directory along and changing the one offset that points at it, in the end record, while leaving each
entry's name, size and CRC, and where its data starts, exactly as they were. A byte comparison would fail
on that, and fail again whenever the certificate behind it changed.

A plugin with no listing yet cannot be uploaded over the API at all - its first version is
[uploaded](https://plugins.jetbrains.com/docs/intellij/publishing-plugin.html), and
[reviewed](https://plugins.jetbrains.com/docs/marketplace/publishing-and-listing-your-plugin.html), by a
person, and the file to upload is the archive the release carries, so that what the Marketplace serves
is what was accepted. Every update is reviewed as well before it becomes publicly available, the
[approval guidelines][approval] say, which can take days; a [JetBrains blog post][channels] says an
update to a custom channel is approved without a review where the plugin has an update approved in the
default channel within the last 120 days. An update is served as soon as it is uploaded all the same,
counter-signed, which is what `intellij/publish` is built on. `intellij/publish` asks for the version
`attempts` times, `wait` seconds apart (10 and 30 unless set), so that one served a little after its
upload is not taken for one that is missing. It cannot tell an upload that did not happen and a plugin
with no listing apart, and fails after the last attempt naming both. Where it was a first version
uploaded by hand, the release is finished by running the job that `intellij/publish` sits in again -
`merge-back` in the example below - once that version is approved and within the 30 days GitHub lets a
run be
[re-run](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs): the
upload is tried again, which does not decide the run, and the version is asked for again.

[approval]: https://plugins.jetbrains.com/docs/marketplace/jetbrains-marketplace-approval-guidelines.html
[channels]: https://blog.jetbrains.com/platform/2023/09/busy-plugin-developers-newsletter-summer-2023/

The job that carries a published release back publishes it too, with the very file the draft carried -
downloaded from the release, not built again. It takes the place of the `merge-back` job under
[release-flow/merge-back](../release-flow/README.md#release-flowmerge-back), and checks out as that job does:

```yaml
on:
  release:
    types: [published]
# One run per release at a time: two runs for one release would race to land it.
concurrency:
  group: merge-back-${{ github.event.release.tag_name }}
  cancel-in-progress: false
jobs:
  merge-back:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      actions: write
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: loplex/release-ci/release-flow/merge-back@<tag>
        id: back
        with:
          source: gradle.properties
          tag: ${{ github.event.release.tag_name }}
          default-branch: ${{ github.event.repository.default_branch }}
          check-workflow: ci.yml
      - id: accepted
        if: ${{ !cancelled() && steps.back.outputs.version != '' }}
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ github.event.release.tag_name }}
        run: |
          gh release download "$TAG" --pattern '*.zip' --dir "$RUNNER_TEMP/accepted"
          archives=("$RUNNER_TEMP"/accepted/*.zip)
          if [ "${#archives[@]}" -ne 1 ]; then
            echo "::error::the release carries ${#archives[@]} archive(s), and publishing takes exactly one"
            exit 1
          fi
          echo "archive=${archives[0]}" >> "$GITHUB_OUTPUT"
      - uses: loplex/release-ci/intellij/publish@<tag>
        id: publish
        if: ${{ !cancelled() && steps.accepted.outcome == 'success' }}
        with:
          plugin-id: cz.example.plugin
          version: ${{ steps.back.outputs.version }}
          archive: ${{ steps.accepted.outputs.archive }}
          token: ${{ secrets.PUBLISH_TOKEN }}
      - uses: loplex/release-ci/release-flow/warn@<tag>
        if: ${{ !cancelled() }}
        with:
          tag: ${{ github.event.release.tag_name }}
          outcome: ${{ steps.publish.outcome }}
          to: the JetBrains Marketplace
```

The channel is not passed: `intellij/publish` reads it off the version with `check-release channel`, by
the rule under [check-release](../check-release/README.md#check-release) that `release-flow/draft` marks a pre-release by, so the
two cannot come to disagree.

Neither the download nor the upload waits for the merge-back step to succeed, only for it to have named
the version: a release that did not make it back onto the default branch is out all the same, and the
Marketplace should serve it too. Where that step failed, the job still fails, so that is not missed;
where it opened a pull request instead, the merge-back step succeeds, so the job does not fail over it,
and that pull request, with `landed` as `false`, is what says the release did not land. Running the job
again - once a first version is approved, say, and within those 30 days - is safe: a merge-back step
that finds its release on the default branch already says so, with `landed` as `true`, and carries
nothing back a second time, and one that finds the pull request an earlier run opened still open tries
to land the release again, as [release-flow/merge-back](../release-flow/README.md#release-flowmerge-back) says.

The last step puts a warning on the release where the Marketplace did not end up serving the accepted
archive, or where nothing was uploaded because a step before the upload failed, and a run repeated once
the Marketplace serves it takes the warning off, as [release-flow/warn](../release-flow/README.md#release-flowwarn) says.
