# BSecure Tailscale WAN Fix

This repository packages a narrowly modified Home Assistant Tailscale app. It
tracks the official
[`hassio-addons/app-tailscale`](https://github.com/hassio-addons/app-tailscale)
release and adds reviewed WAN failover recovery plus bounded, sanitized
diagnostics.

This is an independent custom app. It is not an official Home Assistant,
Tailscale, or Home Assistant Community Apps release.

## Current release state

Version `0.28.1-wanfix.3`, based on official app `v0.28.1`, is published as a
public, signed multi-architecture image. Its immutable index digest is
`sha256:8cfd8512dc76baa0193367103dcc305910e361eb556579149fbf33abb053397b`.
Anonymous pulls, platform mapping, source labels, certificate identity, and
transparency-log inclusion have been verified.

The release has not been installed, activated, or live-verified. Those remain
separate Home Assistant operations and are recorded independently in
[`release-manifest.json`](release-manifest.json).

## Release policy

- The app version and immutable image tag must be identical.
- Published versions are never overwritten and no `latest` tag is produced.
- Builds and publication are separate: pull requests only build locally in CI;
  publication requires a manual, protected GitHub environment.
- Official releases produce a draft intake pull request. They never merge,
  publish, remove the WAN patch, or alter a Home Assistant installation
  automatically.
- The committed manifest is the comparison baseline used by Home Assistant's
  upstream-release alert.

See [`UPSTREAM.md`](UPSTREAM.md) for provenance and
[`tailscale/DOCS.md`](tailscale/DOCS.md) for app configuration.

## Home Assistant identity

The app keeps the upstream `tailscale` slug, but Home Assistant also derives
repository app identity from the repository URL. A local app and this
repository app therefore have separate installation data. Migration from a
local installation is a one-time, explicitly validated operation. Never run
the official, local-custom, and repository-custom Tailscale apps concurrently.

## License and attribution

The repository remains MIT licensed. The app is derived from the Home
Assistant Community Apps Tailscale project and embeds a patch against
Tailscale. Original copyright and license terms are retained in
[`LICENSE.md`](LICENSE.md), with detailed source locks in
[`release-manifest.json`](release-manifest.json).
