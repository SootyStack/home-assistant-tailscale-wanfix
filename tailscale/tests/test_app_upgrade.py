#!/usr/bin/env python3
"""Execute upgrade migrations and service selection without a Supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
ROOTFS = APP_ROOT / "rootfs"
STAGE2 = ROOTFS / "etc/s6-overlay/scripts/stage2_hook.sh"


def bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved.as_posix()
    drive, tail = os.path.splitdrive(str(resolved))
    return f"/{drive[0].lower()}{tail.replace(os.sep, '/')}"


MOCK_BASHIO = r'''
set -euo pipefail
jq() {
    if [[ "${JQ_WINDOWS}" == true ]]; then
        "${JQ_FOR_TESTS}" --binary "$@"
    else
        "${JQ_FOR_TESTS}" "$@"
    fi
}
bashio::app.options() { cat "${OPTIONS_FOR_TESTS}"; }
bashio::app.option() {
    local key="$1" value="${2-}"
    if (( $# == 1 )); then
        jq --arg key "${key}" 'del(.[$key])' "${OPTIONS_FOR_TESTS}" > "${OPTIONS_FOR_TESTS}.new"
    elif [[ "${value}" == ^* ]]; then
        jq --arg key "${key}" --argjson value "${value:1}" '.[$key] = $value' "${OPTIONS_FOR_TESTS}" > "${OPTIONS_FOR_TESTS}.new"
    else
        jq --arg key "${key}" --arg value "${value}" '.[$key] = $value' "${OPTIONS_FOR_TESTS}" > "${OPTIONS_FOR_TESTS}.new"
    fi
    mv "${OPTIONS_FOR_TESTS}.new" "${OPTIONS_FOR_TESTS}"
}
bashio::jq() { printf '%s' "$1" | jq -r "$2"; }
bashio::jq.has_value() { printf '%s' "$1" | jq -e "$2" >/dev/null; }
bashio::config() {
    jq -r --arg key "$1" 'getpath($key|split(".")) | select(. != null) | if type == "array" then .[] else . end' "${OPTIONS_FOR_TESTS}"
}
bashio::config.true() { [[ "$(bashio::config "$1")" == true ]]; }
bashio::config.false() { [[ "$(bashio::config "$1")" == false ]]; }
bashio::config.equals() { [[ "$(bashio::config "$1")" == "$2" ]]; }
bashio::var.true() { [[ "$1" == true ]]; }
bashio::var.equals() { [[ "$1" == "$2" ]]; }
bashio::var.has_value() { [[ -n "${1-}" && "${1-}" != null ]]; }
bashio::var.json_array() { jq -cn '$ARGS.positional' --args "$@"; }
bashio::try() { TRY_ERROR=0; "$@" || TRY_ERROR=$?; }
bashio::try.failed() { (( TRY_ERROR != 0 )); }
bashio::log.info() { printf '%s\n' "$*" >&2; }
bashio::log.warning() { printf '%s\n' "$*" >&2; }
bashio::exit.nok() { printf '%s\n' "$*" >&2; exit 1; }
bashio::dns.locals() { printf '%s\n' 'dns://192.0.2.53'; }
wait-for-local-network() { [[ "${NETWORK_READY}" == true ]]; }
subnet-routes() {
    if [[ "$1" == local ]]; then
        [[ -z "${LOCAL_SUBNETS}" ]] || printf '%s\n' "${LOCAL_SUBNETS}"
    else
        jq -r '.advertise_routes | unique[]' "${OPTIONS_FOR_TESTS}"
    fi
}
'''


class AppUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bash = os.environ.get("BASH_EXE") or shutil.which("bash")
        self.jq = os.environ.get("JQ_EXE") or shutil.which("jq")
        if not self.bash or not self.jq:
            self.skipTest("Bash and jq are required for migration execution")

    def options(self, **overrides: object) -> dict:
        options = {
            "accept_dns": True,
            "accept_routes": False,
            "advertise_connector": False,
            "advertise_exit_node": False,
            "advertise_routes": [],
            "advertise_tags": [],
            "diagnostic_capture": False,
            "diagnostic_seed_backup": "",
            "diagnostic_seed_source": "disabled",
            "log_suppression": True,
            "log_upload": False,
            "share_homeassistant": "disabled",
            "taildrop": False,
            "userspace_networking": True,
        }
        options.update(overrides)
        return options

    def run_hook(self, options: dict, *, network_ready: bool = True,
                 local_subnets: str = "192.0.2.0/24") -> tuple:
        # The production script runs unchanged except that absolute service paths
        # are redirected into a disposable copy of the container filesystem.
        with tempfile.TemporaryDirectory(prefix="tailscale-upgrade-") as temp:
            workspace = Path(temp)
            rootfs = workspace / "rootfs"
            shutil.copytree(ROOTFS, rootfs)
            options_path = workspace / "options.json"
            options_path.write_text(json.dumps(options), encoding="utf-8")
            mock = workspace / "bashio.sh"
            mock.write_text(MOCK_BASHIO, encoding="utf-8", newline="\n")
            script = workspace / "stage2_hook.sh"
            script.write_text(
                STAGE2.read_text(encoding="utf-8").replace(
                    "/etc/s6-overlay/", bash_path(rootfs / "etc/s6-overlay") + "/"
                ), encoding="utf-8", newline="\n",
            )
            environment = os.environ.copy()
            environment.update({
                "BASH_ENV": bash_path(mock),
                "JQ_FOR_TESTS": bash_path(Path(self.jq)),
                "JQ_WINDOWS": str(os.name == "nt").lower(),
                "OPTIONS_FOR_TESTS": bash_path(options_path),
                "NETWORK_READY": str(network_ready).lower(),
                "LOCAL_SUBNETS": local_subnets,
            })
            result = subprocess.run(
                [self.bash, bash_path(script)], env=environment,
                capture_output=True, text=True, timeout=30,
            )
            saved = json.loads(options_path.read_text(encoding="utf-8"))
            files = {p.relative_to(rootfs).as_posix() for p in rootfs.rglob("*") if p.is_file()}
            return result, saved, files

    def assert_success(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_options_migrate_without_resetting_network_choices(self) -> None:
        options = self.options(
            accept_routes=True, advertise_exit_node=True,
            advertise_connector=True, advertise_routes=["198.51.100.0/24"],
            userspace_networking=False, taildrop=True,
            tags=["tag:home"], log_level="info",
            taildrive={"addons": True, "addon_configs": False, "backup": False,
                       "config": False, "media": True, "share": False, "ssl": False},
        )
        result, saved, files = self.run_hook(options)
        self.assert_success(result)
        for key in ("accept_routes", "advertise_exit_node", "advertise_connector",
                    "advertise_routes", "userspace_networking", "taildrop", "log_upload"):
            self.assertEqual(saved[key], options[key], key)
        self.assertNotIn("tags", saved)
        self.assertEqual(saved["advertise_tags"], ["tag:home"])
        self.assertNotIn("log_level", saved)
        self.assertTrue(saved["log_suppression"])
        self.assertEqual(saved["taildrive"], {
            "local_apps": True, "app_configs": False, "backup": False,
            "config": False, "media": True, "share": False, "ssl": False,
        })
        self.assertIn("etc/s6-overlay/user-bundles.d/user/contents.d/forwarding", files)

    def test_debug_logging_migrates_without_enabling_cloud_upload(self) -> None:
        result, saved, _ = self.run_hook(self.options(log_level="debug"))
        self.assert_success(result)
        self.assertFalse(saved["log_suppression"])
        self.assertFalse(saved["log_upload"])

    def test_local_subnets_expand_and_keep_explicit_routes(self) -> None:
        result, saved, _ = self.run_hook(self.options(
            advertise_routes=["local_subnets", "198.51.100.0/24", "192.0.2.0/24"]
        ))
        self.assert_success(result)
        self.assertEqual(saved["advertise_routes"], ["192.0.2.0/24", "198.51.100.0/24"])

    def test_network_failure_preserves_legacy_route_intent(self) -> None:
        options = self.options(advertise_routes=["local_subnets", "198.51.100.0/24"])
        result, saved, _ = self.run_hook(options, network_ready=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("routes were left unchanged", result.stderr)
        self.assertEqual(saved["advertise_routes"], options["advertise_routes"])

    def test_empty_discovery_preserves_legacy_route_intent(self) -> None:
        options = self.options(advertise_routes=["local_subnets"])
        result, saved, _ = self.run_hook(options, local_subnets="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("routes were left unchanged", result.stderr)
        self.assertEqual(saved["advertise_routes"], options["advertise_routes"])

    def test_diagnostic_services_use_current_bundle_and_stay_opt_in(self) -> None:
        for capture in (False, True):
            with self.subTest(capture=capture):
                result, saved, files = self.run_hook(self.options(diagnostic_capture=capture))
                self.assert_success(result)
                for pipeline in ("tailscale-diagnostics-daemon-pipeline",
                                 "tailscale-diagnostics-state-pipeline"):
                    marker = "etc/s6-overlay/user-bundles.d/user/contents.d/" + pipeline
                    self.assertEqual(marker in files, capture)
                    self.assertNotIn("etc/s6-overlay/s6-rc.d/user/contents.d/" + pipeline, files)
                self.assertIn("etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d/tailscale-diagnostics-seed", files)
                self.assertEqual(saved["diagnostic_seed_source"], "disabled")
                self.assertEqual(saved["diagnostic_seed_backup"], "")

    def test_healthcheck_preserves_magicdns_reconfigurator_accounting(self) -> None:
        # A responsive Tailscale daemon must not erase an outstanding DNS proxy
        # failure by continually refreshing LAST_ONLINE_TIMESTAMP.
        for dns_health, capture in (("HEALTHY", False), ("UNHEALTHY", False),
                                    ("UNHEALTHY", True)):
            with self.subTest(dns_health=dns_health, capture=capture), \
                    tempfile.TemporaryDirectory(prefix="tailscale-health-") as temp:
                workspace = Path(temp)
                options = workspace / "options.json"
                options.write_text(json.dumps(self.options(diagnostic_capture=capture)), encoding="utf-8")
                env_dir = workspace / "environment"
                env_dir.mkdir()
                mock = workspace / "bashio.sh"
                mock.write_text(MOCK_BASHIO + r'''
bashio::log.reinitialize_output() { :; }
date() { printf '1000\n'; }
tailscale_for_tests() { printf '{"BackendState":"Running","Self":{"Online":true}}\n'; }
tailscale-diagnostic-health-event() { printf '%s %s\n' "$3" "$4" > "${HEALTH_EVENT_FOR_TESTS}"; }
''', encoding="utf-8", newline="\n")
                script = workspace / "healthcheck"
                content = (ROOTFS / "usr/bin/healthcheck").read_text(encoding="utf-8")
                content = content.replace("exec &> /proc/1/fd/1", ":")
                content = content.replace("/var/run/s6/container_environment", bash_path(env_dir))
                content = content.replace("/opt/tailscale", "tailscale_for_tests")
                script.write_text(content, encoding="utf-8", newline="\n")
                event = workspace / "event.txt"
                environment = os.environ.copy()
                environment.update({
                    "BASH_ENV": bash_path(mock),
                    "JQ_FOR_TESTS": bash_path(Path(self.jq)),
                    "JQ_WINDOWS": str(os.name == "nt").lower(),
                    "OPTIONS_FOR_TESTS": bash_path(options),
                    "HEALTH_EVENT_FOR_TESTS": bash_path(event),
                    "STARTED_TIMESTAMP": "100",
                    "LAST_ONLINE_TIMESTAMP": "600",
                    "MAGICDNS_PROXIES_RECONFIGURATOR_HEALTH_STATE": dns_health,
                })
                result = subprocess.run(
                    [self.bash, bash_path(script)], env=environment,
                    capture_output=True, text=True, timeout=10,
                )
                if dns_health == "HEALTHY":
                    self.assert_success(result)
                    self.assertEqual((env_dir / "LAST_ONLINE_TIMESTAMP").read_text(), "1000")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((env_dir / "LAST_ONLINE_TIMESTAMP").exists())
                self.assertEqual(event.exists(), capture)
                if capture:
                    self.assertEqual(event.read_text().strip(), "unhealthy offline_timeout")


if __name__ == "__main__":
    unittest.main()
