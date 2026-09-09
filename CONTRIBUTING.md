# Contributing

Thanks for stopping by. This is a small project with strong opinions; the
rules below are what keep it small.

## The one rule

**Measured, not assumed.**

Platforms behave differently from their own documentation in more than one
place. This project therefore claims nothing that has not been verified on a
real system, and where a number is missing, no claim is made either. A change
based on "should work in theory" is not one. A number without a date is a
suspicion.

Everything else follows from that.

## Setup

TODO: name the toolchain and its minimum version. Then:

```
npx prettier --check .
npm run lint
npm test
npm run build
```

All four must be green.

The same checks run as git hooks, so that a red build is caught before it
travels rather than after. Once per clone:

```
pip install pre-commit
pre-commit install --install-hooks
pre-commit install --hook-type pre-push
```

The hooks live on your machine, and `--no-verify` skips them. CI runs the
same checks again and is the one that decides.

The release build ends up at `dist/`. That binary never travels
through a commit: the released one is built by CI from the tag.

## Branches and main

`main` is protected and takes no direct push. Not from a contributor, not
from the maintainer. Every change arrives as a pull request, and every change
gets its own branch. Start it from `origin/main`, never from your local
`main`:

```
git fetch origin
git switch -c feature/short-name origin/main
git push -u origin HEAD
gh pr create
```

| Prefix     | For                          |
| ---------- | ---------------------------- |
| `feature/` | new behavior                 |
| `fix/`     | a defect                     |
| `docs/`    | documentation only           |
| `test/`    | tests only                   |
| `chore/`   | build, tooling, dependencies |

These prefixes are not decoration. `.github/release-drafter.yml` reads them
and sorts the pull request into the right heading of the next release's
notes, so a branch named after what it does labels itself. A branch named
something else still merges; it just arrives in the notes unsorted.

Name the part after the prefix in English. A branch name reaches the pull
request list and the release notes, which puts it in the same class as the
commit message and the code: everything that leaves this repository is
English.

To merge, the CI checks must be green and the branch must be up to date with
`main`. No approving review is required: this is a one-person project and
nobody can approve their own work.

When another pull request lands first, rebase onto `origin/main` and push
with `--force-with-lease`. GitHub offers a button that brings the branch up
to date for you, but it does that with a merge commit.

## What belongs in a pull request

- **One test per new pure function.** Test names are complete sentences that
  state what holds: `a_range_whose_ends_are_the_wrong_way_round_is_no_range_at_all`.
  Anyone who can't spell out the name in words hasn't understood the rule
  yet.
- **Small functions with names that say what they do.**
- **Comments that explain the _why_.** What the code does is in the code.
  What's valuable is what explains it: which alternative was rejected, which
  measurement is behind it, which platform quirk forces it.
- **English in the code**, including comments and identifiers.
- **Commit messages in complete sentences** that say what the change does
  and why. No `feat:` prefix.

## About changes to the delicate part

TODO: name the part of this program where a mistake costs the user data or
trust, and the rules that protect it.
<!-- The pattern, one rule per line, from the project this template came from:
- Never delete without a backup. Not a request; the type system checks it.
- Destructive write attempts belong in a throwaway VM, not on the
  development machine.
-->

## What tends to get rejected

- **New dependencies.** Every one has to justify itself; the list is short
  and should stay that way.
- **Rewrites without a bug behind them.** Refactoring that fixes nothing and
  enables nothing costs review time and adds risk.
- **Machine-generated translations.** Every language in this project is
  written by hand and meant to read equally well.

## Reporting bugs

Open an issue at `https://github.com/corgan2222/corganshelper/issues`. What makes a report quick to act
on:

- The version you run and the platform it runs on.
- The shortest path to trigger the bug.
- What happened, and what you expected instead.

A security vulnerability does **not** belong in an issue: see
[`SECURITY.md`](SECURITY.md).
