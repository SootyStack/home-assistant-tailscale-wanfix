FROM ghcr.io/hassio-addons/tailscale:0.28.1

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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

# Build arguments
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

# Labels
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Franck Nijhof <opensource@frenck.dev>" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Community Apps" \
    org.opencontainers.image.authors="Franck Nijhof <opensource@frenck.dev>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://frenck.dev/home-assistant-apps" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
