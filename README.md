# release-ci

The release rules a project would otherwise carry its own copy of, and the pipeline that runs them.
Nothing is here yet: [What is planned](#what-is-planned) says what will be, and where.

What goes where is decided by the ecosystem boundary, not by whichever file is being written:

- A directory whose content is ecosystem-free carries a name that says nothing about an ecosystem.
- A directory for one ecosystem is named after it, and more will follow, one per ecosystem.

This repository is to be released through its own pipeline, so nothing in the ecosystem-free directories may
end up assuming one ecosystem's build.

## What is planned

| Directory       | Will hold                                                                  |
|-----------------|----------------------------------------------------------------------------|
| `check-release` | What a release has to be true of, asked as properties over a repository    |
| `release-flow`  | How a GitHub release is cut, drafted before it is tagged, and carried back |
| `intellij`      | How a JetBrains plugin is built, signed and published to the Marketplace   |
