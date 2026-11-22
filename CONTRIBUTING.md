# Contributing

This document defines how issues, commits, pull requests and releases are written in this repository.

## Commits

Format:

```
type(scope): subject
```

- `type` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `perf`, `ci`, `build`, `chore`.
- `scope` is optional. Use the package or module the change touches (`api`, `cli`, `web`, `auth`), or `release` for version commits. Do not use the repository name as a scope.
- `subject` is English, imperative, lower case, no trailing period, at most 72 characters.
- `revert` is not a valid type. A mistake is corrected with a new commit, never by reverting.

A body is required when the reason for the change is not obvious from the subject. Wrap the body at 72 characters and separate it from the subject with one blank line.

```
fix(grep): respect .gitignore when searching directories

Directory walks included ignored files, so search results disagreed with
`git status`. The walker now filters through the ignore rules first.
```

## Branches

Name branches `type/short-topic`, using the same types as commits: `feat/issue-templates`, `fix/context-budget`. One branch carries one change.

## Pull requests

Title: same format as a commit subject.

Body: four sections, always in this order, at most three bullets each.

```markdown
## What
- What changed.

## Why
- Why it was needed.

## Blast Radius
- What else this touches, and the one fact that makes it safe.

## Verify
- How it was checked. Paste the command and its output, or name the test that covers it.
```

`Blast Radius` is the cost of guessing wrong: which callers, stored data, API
contracts or other repositories the change can reach. A list of grep hits is not
enough. Name the fact that makes the change safe and how it was proven by running
code.

`Verify` states what was observed, not what was intended. "Tests pass" is only
acceptable when the test that covers this behaviour is named. When the change is
behaviour no test reaches, paste the command output or the screenshot.

A green pipeline is necessary and not sufficient. It does not authorize a merge on
its own.

Merging:

- Merge commits only. Squash merge and rebase merge are prohibited.
- A wrong change is corrected with a new commit on a new branch.
- `git revert` is prohibited.

## Issues

Three forms are available: `bug`, `feature`, `task`. A blank issue is not accepted.

- `bug`: what happened, what was expected, how to reproduce, environment.
- `feature`: the problem, the proposed behaviour, alternatives considered.
- `task`: the goal, definition of done, related issues.

Every form is required to state what is observable. "Does not work" without a symptom is not a report.

## Versioning

Versions follow Semantic Versioning: `MAJOR.MINOR.PATCH`.

While the major version is `0`, a breaking change increments `MINOR` and any other change increments `PATCH`. `MAJOR` moves to `1` only when the public interface is declared stable.

Each published package carries its own version. A repository with one package has one version; a repository that publishes several packages bumps each one separately in the same release commit.

Version changes are never mixed into a feature pull request. They are made in a dedicated branch and commit:

```
chore(release): bump version to 0.6.0
```

## Releases

A release is a Git tag named `vX.Y.Z` on `main`, with a matching entry in the package manifest and a changelog. It is published only after the version commit is merged.

Every release is created with the pre-release flag set while the package is below `1.0.0`. A package at `1.0.0` or above may publish a stable release.

Release notes use four groups, in this order, each omitted when empty:

## Added
## Changed
## Fixed
## Removed

A commit is listed in exactly one group, by type:

| Type | Group |
| --- | --- |
| `feat` | Added |
| `fix` | Fixed |
| `perf`, `refactor`, `ci`, `build` | Changed |
| `docs`, `style`, `test`, `chore` | not listed |

`Removed` is not derived from a commit type. It lists features or public
interfaces that no longer exist, and is written by hand from the diff.

`chore(release)` commits never appear in release notes; the version itself
is the release note.
Tags are created only on `main`, only after the version commit is merged, and never moved or deleted.

## Before opening a pull request

- Run the `Test` workflow's commands locally first; CI runs the same ones.
- Format, lint and test the code with the commands listed in `AGENTS.md`.
- Check the commit subject against the rules above.
- Check the pull request body against the three-section template.
- Confirm no version change leaked into the branch.
