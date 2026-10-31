# BSecure Tailscale WAN Fix

This repository packages a narrowly modified Home Assistant Tailscale app. It
tracks the official
[`hassio-addons/app-tailscale`](https://github.com/hassio-addons/app-tailscale)
release and adds reviewed WAN failover recovery plus bounded, sanitized
diagnostics.

This is an independent custom app. It is not an official Home Assistant,
Tailscale, or Home Assistant Community Apps release.

## Upgrade candidate

Version `0.30.5-wanfix.1` targets official app `v0.30.5` and Tailscale
`v1.104.4`, built with Go `1.27.3`. It combines immediate control reconnection
when STUN detects a new public IPv4 address with recovery after the map
watchdog detects a silent connection failure.

This branch is an unpublished upgrade candidate. The stable `main` branch
continues to advertise `0.28.1-wanfix.3` until an immutable replacement is
published and verified. Candidate validation does not establish installation,
activation, remote access, or WAN failover behavior.

Source and release boundaries are recorded in
[`release-manifest.json`](release-manifest.json). Pull-request CI builds both
architectures without publishing and runs control-client regression tests.

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

## Upgrade validation

The candidate ports diagnostics and identity migration onto the new app's
startup scripts, configuration schema, and service bundle layout. Existing
network preferences must survive migration; the identity-seeding options
remain disabled by default. Configuration migration, bounded logging, and
service registration are tested separately from the Go recovery patch.

Before deployment, require the candidate's source, Linux recovery, amd64, and
aarch64 CI checks to pass. Publication and installation are later phases;
never merge an unpublished candidate into the stable branch. A Samba copy
alone does not install or activate this managed container image.

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
