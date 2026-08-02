# Security policy

## Supported version

Only the current version advertised by the repository's `main` branch is
supported. Older custom builds and upstream releases should be assessed against
their own source and security notices.

## Reporting a vulnerability

Use this repository's private GitHub security-advisory reporting flow. Do not
open a public issue containing credentials, authentication URLs, node details,
network topology, Home Assistant backups, raw logs, packet captures, or
diagnostic artifacts.

This repository does not operate a public support service and cannot accept
Tailscale account credentials. For vulnerabilities in unmodified upstream
code, follow the reporting process of the affected upstream project as well.

## Release boundary

CI validation does not establish live safety. Publication, Home Assistant
installation, activation, failover testing, and rollback validation are
distinct controlled steps. A GitHub workflow must never contact or mutate a
Home Assistant instance.
