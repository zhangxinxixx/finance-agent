# Public Release PR Checklist

Use this checklist for every pull request targeting the public `main` branch.
It is a review gate, not evidence that publication, deployment, or runtime
activation has already happened.

## Scope and history

- [ ] This PR is linked to exactly one Issue: `Closes #<issue-number>`.
- [ ] Any exception to the one-PR/one-Issue rule names the linked Issues, the
  approving maintainer, and the reason.
- [ ] The PR is based on the current public `main` and preserves history from
  baseline `f4499c3`.
- [ ] The PR does not replace a published snapshot or force-push `main`.

## Required CI

All of the following checks are green for the reviewed head commit:

- [ ] `Backend contracts`
- [ ] `Analysis Memory PostgreSQL`
- [ ] `Frontend contracts`
- [ ] `Gold Policy core`

## Public-content review

- [ ] The diff contains no local runtime data or generated reports. The
  `storage/raw`, `storage/parsed`, `storage/features`, and `storage/outputs`
  trees contain no runtime files except tracked `.gitkeep` placeholders.
- [ ] The diff contains no private or local paths, browser profiles, cookies,
  login state, keys, tokens, webhooks, internal collaboration references, or
  private operational material.
- [ ] Secret and local-path scans pass for the complete PR diff.
- [ ] The changed files are limited to the linked Issue and do not bundle the
  next roadmap slice.

## Delivery state

Record evidence separately and leave unperformed states unchecked:

- [ ] Code merged — merge commit or squash SHA: ______
- [ ] CI green for the merged commit — run URL: ______
- [ ] Public repository publication confirmed — remote SHA: ______
- [ ] Deployment completed — environment/evidence: ______
- [ ] Runtime activation verified — probe/artifact evidence: ______

Publication, deployment, and runtime activation must not be inferred from code
merge or CI success.

## One-PR/one-Issue exception

`None` or: Issue links, approving maintainer, and written rationale.
