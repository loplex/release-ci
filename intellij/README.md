# intellij

The one ecosystem so far, in two actions:

- `intellij/build`, which goes between `release-flow/prepare` and `release-flow/draft`;
- `intellij/publish`, which goes after the draft has been published, beside
  `release-flow/merge-back`.

What pinning either of them to a release tag or to another ref gets is under
[Pinning](../README.md#pinning).\
What `intellij/publish` needs of the runner is listed under
[What an action needs of the runner](../README.md#what-an-action-needs-of-the-runner).

## intellij/build

[`intellij/build`](build/action.yml) runs the project's own Gradle tasks through `./gradlew`, and
says where the signed archive landed:

1. `check`;
2. the Plugin Verifier - the check the Marketplace
   [runs itself](https://plugins.jetbrains.com/docs/marketplace/understanding-plugin-security.html),
   run here first and on the very commit that will be published;
3. `signPlugin`.

The Plugin Verifier's report is kept as the run's `pluginVerifier-result` artifact, whether it
passed or not.

### What the plugin's build has to do

- Be on the IntelliJ Platform Gradle Plugin 2.x.\
  Under the Gradle IntelliJ Plugin 1.x, `verifyPlugin` checks only `plugin.xml` and the archive's
  structure and the Plugin Verifier never runs, so a build that finds no report stops there.
- Have the plugin as the build's root project.\
  The report is looked for in `build/reports/pluginVerifier` under the workspace; a plugin in a
  subproject writes its report under that subproject, and the build stops there as well.
- Read `CERTIFICATE_CHAIN`, `PRIVATE_KEY` and `PRIVATE_KEY_PASSWORD` in the build script's `signing`
  block.\
  The signing inputs reach `signPlugin` as those environment variables.
- Take the plugin's version from the `version` line of `gradle.properties`, `project.version`,
  rather than from a property of its own, or the archive goes out under the version it had before.\
  No version is handed to the build: the archive carries whatever version the build script gives
  it.\
  A plugin's release runs with `version-source: gradle.properties`, the file carrying the `version`
  and `tagPrefix` lines
  [Where the version comes from](../check-release/README.md#where-the-version-comes-from) names, and
  `release-flow/prepare` rewrites that `version` line.

### Gradle is cached by the open-source provider

Gradle is cached by setup-gradle's open-source `basic` provider rather than its default one.\
The default is a proprietary component under Gradle's own
[terms of use](https://gradle.com/legal/terms-of-use/), which a caller would otherwise accept
unasked.

### In the release job

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
    version: ${{ steps.cut.outputs.version }}
    tag: ${{ steps.cut.outputs.tag }}
    branch: ${{ steps.cut.outputs.branch }}
    files: ${{ steps.built.outputs.archive }}
```

### The draft attaches the archive the build signed

The draft attaches what the build says it signed, rather than a pattern of its own.\
The build finds the archive by its own `archive-pattern`, and two patterns written out separately
can come to disagree, where the one that matters is the file that was signed.\
The `files` pattern in the `release` job under
[release-flow/prepare](../release-flow/README.md#the-release-job) is for a build that does not say
which file it made.

## intellij/publish

[`intellij/publish`](publish/action.yml) does not trust its own upload.\
The archive a published draft carried is the accepted one, and what a release needs to be true is
that the Marketplace ends up serving it, so that is asked of the Marketplace itself.

### Compared by payload rather than by bytes

The answer is compared **by payload rather than by bytes**:

- The Marketplace [counter-signs](https://plugins.jetbrains.com/docs/intellij/plugin-signing.html)
  what it is given.
- A signature sits in a block of its own between the entry data and the central directory, moving
  the directory along and changing the one offset that points at it, in the end record.
- It leaves each entry's name, size and CRC, and where its data starts, exactly as they were.

A byte comparison would fail on that, and fail again whenever the certificate behind it changed.

### A first version is uploaded by hand

A plugin with no listing yet cannot be uploaded over the API at all.\
Its first version is [uploaded](https://plugins.jetbrains.com/docs/intellij/publishing-plugin.html),
and
[reviewed](https://plugins.jetbrains.com/docs/marketplace/publishing-and-listing-your-plugin.html),
by a person.\
The file to upload is the archive the release carries, so that what the Marketplace serves is what
was accepted.

### An update is served as soon as it is uploaded

Every update is reviewed as well before it becomes publicly available, the
[approval guidelines][approval] say, which can take days.\
A [JetBrains blog post][channels] says an update to a custom channel is approved without a review
where the plugin has an update approved in the default channel within the last 120 days.\
An update is served as soon as it is uploaded all the same, counter-signed, which is what
`intellij/publish` is built on.

[approval]: https://plugins.jetbrains.com/docs/marketplace/jetbrains-marketplace-approval-guidelines.html
[channels]: https://blog.jetbrains.com/platform/2023/09/busy-plugin-developers-newsletter-summer-2023/

### Asking until the version is served

`intellij/publish` asks for the version `attempts` times, `wait` seconds apart (10 and 30 unless
set), so that one served a little after its upload is not taken for one that is missing.\
It cannot tell an upload that did not happen and a plugin with no listing apart, and fails after the
last attempt naming both.

### Finishing a release whose first version was uploaded by hand

The release is finished by running the job that `intellij/publish` sits in again - `merge-back` in
the example below - once the first version is approved and within the 30 days GitHub lets a run be
[re-run](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs).\
The upload is tried again, which does not decide the run, and the version is asked for again.

### The job that publishes

The job that carries a published release back publishes it too, with the very file the draft
carried - downloaded from the release, not built again.\
It takes the place of the `merge-back` job under
[release-flow/merge-back](../release-flow/README.md#release-flowmerge-back), and checks out as that
job does:

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
          version-source: gradle.properties
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
          if (( ${#archives[@]} != 1 )); then
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

### The channel is read off the version

The channel is not passed: `intellij/publish` reads it off the version with `check-release channel`,
by the rule under
[The channel a version goes to](../check-release/README.md#the-channel-a-version-goes-to) that
`release-flow/draft` marks a pre-release by, so the two cannot come to disagree.

### A pre-release reaches only those who add its channel

A version that goes to a channel other than `default` is not offered to the plugin's users:

- The plugin's page on the Marketplace shows every channel, this one among them.
- An IDE installs it, and updates to it, only once its user has added the channel as a custom plugin
  repository, as [Custom release channels][custom-channels] says.

Whether an update to a custom channel waits for a review is under
[An update is served as soon as it is uploaded](#an-update-is-served-as-soon-as-it-is-uploaded).

### How a tester adds the channel

1. In the IDE, open Settings, select Plugins, click the gear icon and choose
   *Manage Plugin Repositories…*, as [Add custom repositories][custom-repositories] shows.
2. Add `https://plugins.jetbrains.com/plugins/<channel>/<plugin id>`, the plugin id being the number
   in the plugin's Marketplace URL.\
   That brings in this plugin's channel alone.\
   `https://plugins.jetbrains.com/plugins/<channel>/list` brings in every plugin's channel of that
   name.

### A tester who keeps the channel is offered no final release

- A custom repository takes precedence over the default channel: a user who has added one sees none
  of the plugin's updates in the default channel.
- JetBrains calls this temporary, and asks for every update to the default channel to be uploaded to
  the custom channel as well; see [Channel Priority Notice][channel-priority].
- `intellij/publish` uploads a version to the one channel
  [read off it](#the-channel-is-read-off-the-version), so a final release goes to `default` alone.

So a tester removes the repository once the final release is out.\
The IDE then offers the final release over the pre-release: the comparison it checks for updates by
(`VersionComparatorUtil`, in 2025.3) takes `0.1.1` to be newer than `0.1.1-beta.1`.

### Withdrawing a pre-release

On the Marketplace, as [Plugin updates][plugin-updates] says:

- A version can be hidden, with the eye icon by it.\
  Neither the Marketplace nor an IDE's search then offers it; a direct link still reaches it.
- A version can be removed, with the trash can icon by it.\
  Where the icon is missing, JetBrains suggests hiding the version or writing to
  marketplace@jetbrains.com.
- What either does to a copy already installed, the documentation does not say.

On GitHub, `release-flow` takes nothing back.\
The release, its tag, and what
[merge-back](../release-flow/README.md#release-flowmerge-back) carried onto the default branch stay
as they are.

[custom-channels]: https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html
[channel-priority]: https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html#channel-priority-notice
[custom-repositories]: https://www.jetbrains.com/help/idea/managing-plugins.html#add_plugin_repos
[plugin-updates]: https://plugins.jetbrains.com/docs/marketplace/plugin-updates.html

### The publish does not wait for merge-back to succeed

Neither the download nor the upload waits for the merge-back step to succeed, only for it to have
named the version.\
A release that did not make it back onto the default branch is out all the same, and the Marketplace
should serve it too.

- Where that step failed, the job still fails, so that is not missed.
- Where it opened a pull request instead, the merge-back step succeeds, so the job does not fail
  over it, and that pull request, with `landed` as `false`, is what says the release did not land.

Running the job again - once a first version is approved, say, and within the 30 days GitHub lets a
run be re-run - is safe:

- A merge-back step that finds its release on the default branch already says so, with `landed` as
  `true`, and carries nothing back a second time.
- One that finds the pull request an earlier run opened still open tries to land the release again,
  as [release-flow/merge-back](../release-flow/README.md#running-it-again) says.

### The warning

The last step puts a warning on the release where the Marketplace did not end up serving the
accepted archive, or where nothing was uploaded because a step before the upload failed.\
A run repeated once the Marketplace serves it takes the warning off, as
[release-flow/warn](../release-flow/README.md#release-flowwarn) says.
