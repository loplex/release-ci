# intellij

Two actions for a JetBrains plugin:

| Action             | Where it goes in the release                                   |
|--------------------|----------------------------------------------------------------|
| `intellij/build`   | between `release-flow/prepare` and `release-flow/draft`        |
| `intellij/publish` | after the draft is published, beside `release-flow/merge-back` |

- What a pin to a release tag or another ref gets: [Pinning](../README.md#pinning).
- What `intellij/build` and `intellij/publish` need on the runner:
  [What an action needs of the runner](../README.md#what-an-action-needs-of-the-runner).

## intellij/build

[`intellij/build`](build/action.yml) runs the project's own Gradle tasks through `./gradlew`:

1. `check`.
2. `verifyPlugin`, which runs the Plugin Verifier.\
   The Marketplace runs the same check
   [itself](https://plugins.jetbrains.com/docs/marketplace/understanding-plugin-security.html).\
   Here it runs first, on the commit that will be published.
3. `signPlugin`.

Then it says where the signed archive is, in its `archive` output, and checks the version in its
`plugin.xml`.

The Plugin Verifier's report is kept as the run's `pluginVerifier-result` artifact, whether it
passed or not.

### What the plugin's build has to do

- **Use the IntelliJ Platform Gradle Plugin 2.x.**\
  Under the Gradle IntelliJ Plugin 1.x, `verifyPlugin` checks only `plugin.xml` and the archive's
  structure, and never runs the Plugin Verifier.\
  The build then finds no report, and stops.
- **Have the plugin as the root project.**\
  The report is looked for in `build/reports/pluginVerifier` under the workspace.\
  A plugin in a subproject writes it under that subproject, and the build stops as well.
- **Read the signing variables in the `signing` block.**\
  The signing inputs reach `signPlugin` as `CERTIFICATE_CHAIN`, `PRIVATE_KEY` and
  `PRIVATE_KEY_PASSWORD`.
- **Take the version from the `version` line of `gradle.properties`**, as `project.version`.\
  No version is handed to the build: the archive gets whatever version the build script gives it.\
  A plugin is released with `version-source: gradle.properties`, and `release-flow/prepare` rewrites
  that `version` line.\
  A version from a property of the plugin's own would leave the archive at the old version.\
  So the signed archive's `plugin.xml` is checked against that line, and the build stops where
  they differ.\
  [Where the version comes from](../lib/README.md#where-the-version-comes-from) describes
  the file.

### Gradle is cached by the open-source provider

The build caches Gradle with setup-gradle's open-source `basic` provider, not its default one.\
The default one is a proprietary component under Gradle's own
[terms of use](https://gradle.com/legal/terms-of-use/).\
Using it would make a caller accept those terms without being asked.

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

The draft's `files` is the build's `archive` output, not a pattern of its own.\
The build finds the archive by its `archive-pattern`.\
A second pattern, written in the workflow, could come to match another file than the one signed.

The `files` pattern in the `release` job under
[release-flow/prepare](../release-flow/README.md#the-release-job) is for a build that does not say
which file it made.

## intellij/publish

[`intellij/publish`](publish/action.yml) uploads the archive the published draft carried.\
The upload's own answer does not decide the run.\
What decides it is whether the Marketplace then serves the accepted archive, which is asked of the
Marketplace itself.

### Compared by payload rather than by bytes

The Marketplace [counter-signs](https://plugins.jetbrains.com/docs/intellij/plugin-signing.html)
what it is given, so the file it serves differs from the one uploaded:

- The signature is a block of its own between the entries' data and the central directory.
- It moves the central directory along, and changes the one offset that points at it, in the end
  record.
- Each entry's name, size, CRC and data offset stay exactly as they were.

So the two archives are compared by what their entries hold.\
A comparison of the bytes would fail on the signature, and fail again whenever the certificate
behind it changed.

### A first version is uploaded by hand

A plugin with no listing yet cannot be uploaded over the API at all.\
A person [uploads](https://plugins.jetbrains.com/docs/intellij/publishing-plugin.html) its first
version, and a person
[reviews it](https://plugins.jetbrains.com/docs/marketplace/publishing-and-listing-your-plugin.html).\
Upload the archive the release carries, so that the Marketplace serves what was accepted.

### An update is served as soon as it is uploaded

- JetBrains's [approval guidelines][approval] say every update is reviewed before it becomes
  publicly available, which can take days.
- A [JetBrains blog post][channels] says an update to a custom channel is approved without a review
  where the plugin has an update approved in the default channel within the last 120 days.
- An update is served as soon as it is uploaded all the same, counter-signed.\
  `intellij/publish` is built on that.

[approval]: https://plugins.jetbrains.com/docs/marketplace/jetbrains-marketplace-approval-guidelines.html
[channels]: https://blog.jetbrains.com/platform/2023/09/busy-plugin-developers-newsletter-summer-2023/

### Asking until the version is served

`intellij/publish` asks for the version `attempts` times, `wait` seconds apart.\
The defaults are 10 attempts, 30 seconds apart.\
A version served a little after its upload is then not taken for a missing one.

After the last attempt the run fails.\
It cannot tell an upload that did not happen from a plugin with no listing, so the error names both.

### Finishing a release whose first version was uploaded by hand

Once the first version is approved, run the job that `intellij/publish` is in again: `merge-back` in
the example below.\
GitHub lets a run be
[re-run](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
within 30 days.\
The upload is tried again, which does not decide the run, and the version is asked for again.

### The job that publishes

The job that carries a published release back also publishes it.\
It publishes the file the draft carried, downloaded from the release, not built again.\
It takes the place of the `merge-back` job under
[release-flow/merge-back](../release-flow/README.md#release-flowmerge-back), and checks out the same
way:

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

The channel is not an input.\
`intellij/publish` reads it off the version with `lib/main.py channel`, by the rule under
[The channel a version goes to](../lib/README.md#the-channel-a-version-goes-to).\
`release-flow/draft` marks a pre-release by the same rule, so the two cannot come to disagree.

### A pre-release reaches only those who add its channel

A version in a channel other than `default` is not offered to the plugin's users:

- The plugin's page on the Marketplace shows every channel, this one included.
- An IDE installs it, and updates to it, only after its user adds the channel as a custom plugin
  repository, as [Custom release channels][custom-channels] says.

Whether an update to a custom channel waits for a review:
[An update is served as soon as it is uploaded](#an-update-is-served-as-soon-as-it-is-uploaded).

### How a tester adds the channel

1. In the IDE, open Settings, select Plugins, click the gear icon and choose
   *Manage Plugin Repositories…*, as [Add custom repositories][custom-repositories] shows.
2. Add `https://plugins.jetbrains.com/plugins/<channel>/<plugin id>`.\
   The plugin id is the number in the plugin's Marketplace URL.\
   This brings in this plugin's channel alone.\
   `https://plugins.jetbrains.com/plugins/<channel>/list` brings in every plugin's channel of that
   name.

### A tester who keeps the channel is offered no final release

- A custom repository takes precedence over the default channel.\
  A user who has added one sees none of the plugin's updates in the default channel.
- JetBrains calls this temporary, and asks for every update to the default channel to be uploaded to
  the custom channel as well: see [Channel Priority Notice][channel-priority].
- `intellij/publish` uploads a version to the one channel
  [read off it](#the-channel-is-read-off-the-version).\
  So a final release goes to `default` alone.

So a tester removes the repository once the final release is out.\
The IDE then offers the final release over the pre-release.\
The comparison it checks for updates with (`VersionComparatorUtil`, in 2025.3) takes `0.1.1` to be
newer than `0.1.1-beta.1`.

### Withdrawing a pre-release

On the Marketplace, as [Plugin updates][plugin-updates] says:

- A version can be hidden, with the eye icon next to it.\
  Neither the Marketplace nor an IDE's search then offers it.\
  A direct link still reaches it.
- A version can be removed, with the trash can icon next to it.\
  Where the icon is missing, JetBrains suggests hiding the version or writing to
  marketplace@jetbrains.com.
- The documentation does not say what either does to a copy already installed.

On GitHub, `release-flow` takes nothing back.\
The release, its tag, and what [merge-back](../release-flow/README.md#release-flowmerge-back)
carried onto the default branch stay as they are.

[custom-channels]: https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html
[channel-priority]: https://plugins.jetbrains.com/docs/marketplace/custom-release-channels.html#channel-priority-notice
[custom-repositories]: https://www.jetbrains.com/help/idea/managing-plugins.html#add_plugin_repos
[plugin-updates]: https://plugins.jetbrains.com/docs/marketplace/plugin-updates.html

### The publish does not wait for merge-back to succeed

The download and the upload wait only for the merge-back step to name the version, not for it to
succeed.\
A release that did not get back onto the default branch is out all the same, and the Marketplace
should serve it too.

- Where the merge-back step failed, the job still fails, so the failure is not missed.
- Where it opened a pull request instead, the step succeeds and the job does not fail over it.\
  The pull request, and `landed` as `false`, say that the release did not land.

Running the job again is safe, for example once a first version is approved:

- A merge-back step that finds the release on the default branch already says so, with `landed` as
  `true`, and carries nothing back a second time.
- One that finds the pull request an earlier run opened still open tries to land the release again,
  as [release-flow/merge-back](../release-flow/README.md#running-it-again) says.

### The warning

The last step puts a warning on the release in two cases:

- the Marketplace did not end up serving the accepted archive;
- nothing was uploaded, because a step before the upload failed.

Running the job again once the Marketplace serves the version takes the warning off, as
[release-flow/warn](../release-flow/README.md#release-flowwarn) says.
