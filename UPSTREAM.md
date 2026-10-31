# Upstream and patch policy

The current candidate is derived from Home Assistant Community Apps Tailscale
`v0.30.5`, commit `0dfb3a6c3b7849bea0ab518c35faf649916da244`.
It embeds Tailscale `v1.104.4`, commit
`27047635f237d1f3e0b08c0f487674757f30d2f7`, built with Go `1.27.3`.

The exact source commits, trees, patch digest, image name, and validation state
are machine-readable in [`release-manifest.json`](release-manifest.json).

## Control recovery patch

The combined patch ports two independent upstream proposals:

- [SootyStack's PR #20618](https://github.com/tailscale/tailscale/pull/20618),
  head `74d1ba1df204b24aaeca9af7317f71221592510f`, resets the control transport
  when a new STUN-discovered public IPv4 appears. Initial discovery, port-only
  changes, IPv6 endpoints, endpoint removal, and empty results do not trigger
  the reset. The submitted implementation replaces the older packaged patch's
  login, first-map, and pause guards, including a reset while paused.
- [FrankTub's PR #21834](https://github.com/tailscale/tailscale/pull/21834),
  head `ef4028e7b7b19f513188bff0794a591d998c44d6`, discards the specific Noise
  client used by a map request after the existing two-minute watchdog expires.
  It supplies fallback recovery when STUN does not signal a new IPv4 address.

Both proposals remain unmerged at intake. The combined patch retains upstream
copyright and license notices and adds regression coverage for recovery and
concurrent client replacement. Neither mechanism restarts the daemon or adds
periodic probes to a healthy control connection.

The app overlay retains bounded, sanitized diagnostics and guarded one-time
identity migration. It uses the new upstream service bundle paths and option
migrations. Legacy `local_subnets` migration fails without changing the saved
route selection when discovery is unavailable, allowing a later startup to
retry instead of silently discarding the setting.

## Intake rules

The scheduled intake workflow compares the latest stable official app release
with `upstream.app.version` in the stable manifest. A newer stable release may
create or refresh one draft pull request containing an intake descriptor. It
does not:

- rebase or execute unreviewed upstream source;
- merge or publish a candidate;
- remove the embedded WAN-control patch, even if upstream appears similar;
- modify Home Assistant; or
- advance the stable comparison baseline.

An owner must review the upstream diff, determine whether each custom change is
still necessary, reproduce the candidate, validate it, publish an immutable
image, and merge the matching metadata change. The stable baseline advances
only when that exact version is installable.

## Reproducibility boundary

Source provenance is locked, and both multi-architecture base-image indexes are
pinned by SHA-256 digest in the Dockerfile and release manifest. The digests
were resolved from the public OCI Distribution APIs; image signatures and
attestations were not independently verified.

The build is still not claimed to be hermetic. It installs packages from Alpine
repositories, clones the locked Tailscale commit over the network, resolves Go
dependencies through network services, and runs on mutable hosted build
infrastructure. Dependency closure and the build environment must be captured
before making a hermetic-build or byte-for-byte reproducibility claim.
