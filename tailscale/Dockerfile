FROM golang:1.26.1-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039 AS tailscale-wanfix-builder

ARG TAILSCALE_COMMIT="41cb72f27119f95b859335f3ffc3434d6ca55e23"
ARG TAILSCALE_VERSION_LONG="1.96.4-t41cb72f27-hivewan1"
ARG TAILSCALE_VERSION_SHORT="1.96.4"

RUN apk add --no-cache ca-certificates git

WORKDIR /src
RUN \
    git clone --branch v1.96.4 --depth 1 \
        https://github.com/tailscale/tailscale.git tailscale \
    && test "$(git -C tailscale rev-parse HEAD)" = "${TAILSCALE_COMMIT}"

COPY patches/tailscale-1.96.4-wan-control-reset.patch /tmp/tailscale-wan-control-reset.patch

WORKDIR /src/tailscale
RUN \
    git apply --check /tmp/tailscale-wan-control-reset.patch \
    && git apply /tmp/tailscale-wan-control-reset.patch \
    && CGO_ENABLED=0 go test ./control/controlclient ./control/ts2021 \
    && mkdir -p /out \
    && CGO_ENABLED=0 go build \
        -trimpath \
        -ldflags="\
            -X tailscale.com/version.longStamp=${TAILSCALE_VERSION_LONG} \
            -X tailscale.com/version.shortStamp=${TAILSCALE_VERSION_SHORT} \
            -X tailscale.com/version.gitCommitStamp=${TAILSCALE_COMMIT}" \
        -o /out/tailscaled \
        ./cmd/tailscaled \
    && CGO_ENABLED=0 go build \
        -trimpath \
        -ldflags="\
            -X tailscale.com/version.longStamp=${TAILSCALE_VERSION_LONG} \
            -X tailscale.com/version.shortStamp=${TAILSCALE_VERSION_SHORT} \
            -X tailscale.com/version.gitCommitStamp=${TAILSCALE_COMMIT}" \
        -o /out/tailscale \
        ./cmd/tailscale

FROM ghcr.io/hassio-addons/tailscale:0.28.1@sha256:2a15916111291ade93481fe17f4b30107610b1d510c02f7645d83a36fad4aece

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Replace only the Tailscale executables; retain the exact official add-on
# runtime, services, configuration, and persistent data paths.
ARG TAILSCALE_VERSION_LONG="1.96.4-t41cb72f27-hivewan1"
COPY --from=tailscale-wanfix-builder /out/tailscale /opt/tailscale
COPY --from=tailscale-wanfix-builder /out/tailscaled /opt/tailscaled
RUN /opt/tailscale version | grep -Fq "${TAILSCALE_VERSION_LONG}"

# Overlay only the diagnostic changes onto the exact official 0.28.1 runtime.
COPY rootfs/etc/s6-overlay/scripts/stage2_hook.sh /etc/s6-overlay/scripts/stage2_hook.sh
COPY rootfs/usr/bin/healthcheck /usr/bin/healthcheck
COPY rootfs/usr/bin/tailscale-diagnostic-daemon-stream /usr/bin/tailscale-diagnostic-daemon-stream
COPY rootfs/usr/bin/tailscale-diagnostic-health-event /usr/bin/tailscale-diagnostic-health-event
COPY rootfs/usr/bin/tailscale-diagnostic-sanitize /usr/bin/tailscale-diagnostic-sanitize
COPY rootfs/usr/bin/tailscale-diagnostic-state-stream /usr/bin/tailscale-diagnostic-state-stream
COPY rootfs/usr/bin/tailscale-diagnostics-prepare /usr/bin/tailscale-diagnostics-prepare
COPY rootfs/usr/bin/tailscale-diagnostics-seed /usr/bin/tailscale-diagnostics-seed
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-daemon /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-daemon
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-daemon-log /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-daemon-log
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-prepare /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-prepare
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-seed /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-seed
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-state /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-state
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscale-diagnostics-state-log /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-state-log
COPY rootfs/etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d/tailscale-diagnostics-seed /etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d/tailscale-diagnostics-seed
COPY rootfs/etc/s6-overlay/s6-rc.d/user/contents.d/tailscale-diagnostics-daemon-pipeline /etc/s6-overlay/s6-rc.d/user/contents.d/tailscale-diagnostics-daemon-pipeline
COPY rootfs/etc/s6-overlay/s6-rc.d/user/contents.d/tailscale-diagnostics-state-pipeline /etc/s6-overlay/s6-rc.d/user/contents.d/tailscale-diagnostics-state-pipeline

# Local app development commonly copies the build context through a file share,
# which does not preserve Unix executable bits.
RUN \
    chmod +x \
        /usr/bin/healthcheck \
        /usr/bin/tailscale-diagnostic-* \
        /usr/bin/tailscale-diagnostics-* \
        /etc/s6-overlay/scripts/stage2_hook.sh \
    && find /etc/s6-overlay/s6-rc.d/tailscale-diagnostics-* \
        -type f \
        \( -name run -o -name finish \) \
        -exec chmod +x {} +

HEALTHCHECK \
    CMD healthcheck

# S6 Overlay stage 2 hook
ENV S6_STAGE2_HOOK=/etc/s6-overlay/scripts/stage2_hook.sh

# The Home Assistant builder supplies architecture, version, source, revision,
# and creation labels for published images.
ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
    io.hass.name="Tailscale WAN Diagnostics" \
    io.hass.description="Tailscale with reviewed WAN recovery diagnostics" \
    io.hass.type="app" \
    maintainer="SootyStack" \
    org.opencontainers.image.title="Tailscale WAN Diagnostics" \
    org.opencontainers.image.description="Tailscale with reviewed WAN recovery diagnostics" \
    org.opencontainers.image.vendor="SootyStack" \
    org.opencontainers.image.authors="SootyStack" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/SootyStack/home-assistant-tailscale-wanfix" \
    org.opencontainers.image.documentation="https://github.com/SootyStack/home-assistant-tailscale-wanfix/blob/main/tailscale/DOCS.md"
