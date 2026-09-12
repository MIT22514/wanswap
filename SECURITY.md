# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private reporting: **Security → Report a vulnerability** on this repository.
That opens a private advisory only the maintainers can see.

Please include:

- what the issue is and where (file, function)
- how to reproduce it
- the impact you believe it has
- any suggested fix

You can expect an acknowledgement within a few days. This is a spare-time project, so please
be patient with fixes — but security reports are prioritised over feature work.

## Scope

Things that are genuinely interesting here:

- **Authentication bypass** on the pod-side service (`/source`, `/swap`, `/ws`)
- **Command injection** in the provisioning or deploy scripts
- **Secret disclosure** — the shared token, SSH keys, or anything written to logs
- **A way for an unauthenticated client to consume GPU time or read swapped frames**

## Known and accepted risks

These are documented rather than fixed, so please don't report them as new findings:

- **The pod service listens on `0.0.0.0`.** It is intended to sit behind your provider's
  authenticated proxy, protected by the shared token in `.auth`. Running it on a host with a
  public IP and no token is explicitly unsupported — `.auth` is the only access control.
- **SSH host keys use `StrictHostKeyChecking=accept-new`.** Rented hosts are new machines every
  time, so trust-on-first-use is the pragmatic default. If your threat model requires pinning,
  set your own `~/.ssh/known_hosts` entries and tighten the option.
- **Model weights are fetched at runtime** from third-party release URLs and are not verified by
  hash. See `THIRD-PARTY.md`; if upstream is compromised, so is your pod.
- **The pipeline processes untrusted video** (your camera). Malformed frames are a plausible
  denial-of-service vector against a pod you are paying for, but not a confidentiality risk.

## Supported versions

Only the latest commit on `main` is supported. This is a tool, not a library.
