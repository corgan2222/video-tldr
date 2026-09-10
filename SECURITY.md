# Security Policy

video-tldr is a browser extension. It runs with the permissions its
manifest declares and nothing more: what it may read on a page, what it
stores, and where it may send anything is bounded by `src/manifest.json`,
and that file is the authoritative list. Today it declares no permission
and runs no content script; this document grows with the features.

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
  `https://github.com/corgan2222/video-tldr/security/advisories/new`. Preferred: report, discussion,
  and fix stay in one place, and you see the patch before it goes public.
- **Email `stefan@knaak.org`** with the project name and "security" in the
  subject line. Nothing is encrypted at rest on the receiving end; if the
  detail is too sensitive for plain mail, send a short note asking for
  another channel.

What makes a report quick to act on: the version you run, the browser with
its version, and the steps to trigger it.

## What counts as a vulnerability

Three promises, and a vulnerability is a way to break one of them:

- The extension reads only what its manifest permissions allow, on the
  pages they name.
- Everything it runs ships inside the package. No code is fetched at
  runtime.
- It sends data nowhere the documentation does not name.

A page the extension runs on, or another extension, that can make it break
one of these is the report this policy is for.

## What is explicitly not a vulnerability

- Reports from a vulnerability scanner **without a path showing how this
  applies here**. A dependency with a CVE in a code path this program does
  not use is not a vulnerability of this program.
- A permission the manifest declares and the documentation explains. That
  is a decision, not a leak. Argue against the decision in an issue.

## What's worth looking at

- **The manifest.** Every permission and host permission is the first thing
  a store reviewer reads and the first thing worth a second look here. A
  change to it is reviewed as a change to what the extension may do.
- **Message passing.** There is no message handler yet. Once popup,
  background and content scripts talk to each other, that seam is where a
  page could try to reach in, and a handler checks who sent a message
  before it acts on it.
- **Storage.** Nothing is stored yet. Settings, once there are any, belong
  in the browser's extension storage, which the browser isolates per
  extension and does not encrypt beyond what the profile does. No secret
  belongs there.

## Out of scope

- The warning a browser shows for an extension installed from a file. The
  zip attached to a GitHub release is for testing; the store listings are
  the supported way in.
- Anything a page can do to itself. The extension is not a sandbox for the
  pages it runs on.

## What you can expect

- **Acknowledgment of receipt within 7 days.** If nothing arrives, send it
  again; the first one may have been lost.
- **An assessment within 30 days**: confirmed, not a bug, or a follow-up
  question.
- **Credit, if you want it**, in the release that fixes it.
- No money. This is a spare-time project with no revenue.
- If a report sits unanswered for 90 days, you may publish it. A policy
  that asks for silence without holding up its own end has not earned it.
