# Upstream and patch policy

The current candidate is derived from Home Assistant Community Apps Tailscale
`v0.28.1`, commit `25b151d15b45d9b89dde6af549d96b19ffe6004c`.
It embeds Tailscale `v1.96.4`, commit
`41cb72f27119f95b859335f3ffc3434d6ca55e23`.

The exact source commits, trees, patch digest, image name, and validation state
are machine-readable in [`release-manifest.json`](release-manifest.json).

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
