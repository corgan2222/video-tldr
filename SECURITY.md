# Security Policy

TODO: two or three sentences on what this program touches that makes it
security-relevant. What it reads, what it writes, what it sends, and with
whose privileges.

## Supported versions

Only the latest release.

| Version        | Fixes            |
| -------------- | ---------------- |
| Latest release | Yes              |
| Anything older | No, update first |

The project has one maintainer. There is no branch on which an older version
continues to be maintained, and a table that promised otherwise would be a
promise no one could keep.

## Reporting a vulnerability

**Please not as a public issue.** Issues are public the moment they are
filed, and every reader is someone who can act on it before a fix exists.

Two private channels, either is fine:

- **GitHub private vulnerability reporting.** In this repository's
  _Security_ tab, _Report a vulnerability_:
  `https://github.com/corgan2222/corganshelper/security/advisories/new`. Preferred: report, discussion,
  and fix stay in one place, and you see the patch before it goes public.
- **Email `stefan@knaak.org`** with the project name and "security" in the
  subject line. Nothing is encrypted at rest on the receiving end; if the
  detail is too sensitive for plain mail, send a short note asking for
  another channel.

What makes a report quick to act on: the version you run, the platform, and
the steps to trigger it.

## What counts as a vulnerability

TODO: list the promises this program makes, one sentence each. A
vulnerability is a way to break one of them.

## What is explicitly not a vulnerability

- Reports from a vulnerability scanner **without a path showing how this
  applies here**. A dependency with a CVE in a code path this program does
  not use is not a vulnerability of this program.
- TODO: add the trade-offs this project makes deliberately, so nobody has to
  guess whether they are known.

## What's worth looking at

TODO: name the parts of this program an attacker would target first, and
what each already does about it, in the shape of the section above.
<!-- The pattern, one part per subsection, from the project this template
     came from: a settings interface, a listener bound to a network
     address, stored credentials, a self-updater, an optional elevated
     component. Say what is checked already, so a report tells you
     something the file does not already say. -->

## Out of scope

TODO: list the things that are not a vulnerability because they are a
documented, deliberate trade-off, so nobody has to guess whether they are
known.
<!-- The pattern: a setting that is off by default and named for what it
     does, a warning a code-signing certificate would remove, a scanner
     finding with no path that reaches this program. -->

## What you can expect

- **Acknowledgment of receipt within 7 days.** If nothing arrives, send it
  again; the first one may have been lost.
- **An assessment within 30 days**: confirmed, not a bug, or a follow-up
  question.
- **Credit, if you want it**, in the release that fixes it.
- No money. This is a spare-time project with no revenue.
- If a report sits unanswered for 90 days, you may publish it. A policy
  that asks for silence without holding up its own end has not earned it.
