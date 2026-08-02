# Changelog

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
