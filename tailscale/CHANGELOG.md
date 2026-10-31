# Changelog

## 0.30.5-wanfix.1 (unpublished candidate)

- Upgrade the exact official app baseline to `v0.30.5` and Tailscale to
  `v1.104.4`, retaining immediate STUN IPv4 recovery and adding a map-watchdog
  transport reset for silent connection failures.
- Port managed diagnostic pipelines to the current s6 user-bundle layout.
- Preserve upstream option migrations, new-install defaults, and MagicDNS
  reconfigurator health accounting.
- Keep diagnostic capture opt-in and identity seeding disabled for routine
  upgrades. Publication, installation, and live verification remain separate.

## 0.28.1-wanfix.3

- Allow a one-time identity seed to select either the official Community Apps
  installation or a local Home Assistant app as its exact source.
- Add functional synthetic-backup coverage for the guarded identity import.
- Publish and verify signed `amd64` and `aarch64` images plus the immutable
  multi-architecture manifest.

## 0.28.1-wanfix.2

- Base the app on official Home Assistant Community Apps Tailscale `v0.28.1`.
- Build Tailscale `v1.96.4` from its locked commit with the WAN control-session
  reset patch.
- Add persistent, sanitized WAN transition diagnostics and explicit one-time
  diagnostic seeding.
- Reduce persistent diagnostic logging to state transitions, bounded
  health events, and explicit capture mode.
- Prepare a managed, immutable Home Assistant repository release channel.
- Publish and independently verify signed `amd64` and `aarch64` images plus the
  immutable multi-architecture manifest.
