#!/usr/bin/env python3
"""Focused regression checks for the WAN diagnostic logging policy."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
HEALTH_EVENT = APP_ROOT / "rootfs/usr/bin/tailscale-diagnostic-health-event"
STATE_STREAM = APP_ROOT / "rootfs/usr/bin/tailscale-diagnostic-state-stream"
DAEMON_STREAM = APP_ROOT / "rootfs/usr/bin/tailscale-diagnostic-daemon-stream"
STAGE2_HOOK = APP_ROOT / "rootfs/etc/s6-overlay/scripts/stage2_hook.sh"
CONFIG = APP_ROOT / "config.yaml"


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved.as_posix()
    drive, tail = os.path.splitdrive(str(resolved))
    return f"/{drive[0].lower()}{tail.replace(os.sep, '/')}"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


class DiagnosticLoggingTests(unittest.TestCase):
    def test_state_stream_is_change_only(self) -> None:
        script = STATE_STREAM.read_text(encoding="utf-8")

        self.assertNotIn("HEARTBEAT_SECONDS", script)
        self.assertNotIn("last_emit", script)
        self.assertIn(
            'if [[ "${state_signature}" != "${last_signature}" ]]; then',
            script,
        )

        observations = ["online", "online", "online", "offline", "offline", "online"]
        emitted: list[str] = []
        previous = ""
        for observation in observations:
            if observation != previous:
                emitted.append(observation)
                previous = observation

        self.assertEqual(emitted, ["online", "offline", "online"])

    def test_health_log_records_baseline_and_transitions(self) -> None:
        bash = os.environ.get("BASH_EXE") or shutil.which("bash")
        if not bash:
            self.skipTest("Bash is required for the runtime health-event check")

        with tempfile.TemporaryDirectory(
            prefix=".diagnostic-test-", dir=APP_ROOT
        ) as temp:
            workspace = Path(temp)
            mock_bin = workspace / "bin"
            health_directory = workspace / "health"
            mock_bin.mkdir()
            health_directory.mkdir()

            _write_executable(
                mock_bin / "jq",
                """#!/bin/sh
if [ "${1-}" = "-r" ]; then
  filter=${2-}
  payload=$(cat)
  case "${filter}" in
    *result*) printf '%s\n' "${payload}" | sed -nE 's/.*"result"[[:space:]]*:[[:space:]]*"([^"]*)".*/\\1/p' ;;
    *reason*) printf '%s\n' "${payload}" | sed -nE 's/.*"reason"[[:space:]]*:[[:space:]]*"([^"]*)".*/\\1/p' ;;
  esac
  exit 0
fi

result=""
reason=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --arg|--argjson)
      key=$2
      value=$3
      [ "${key}" = "result" ] && result=${value}
      [ "${key}" = "reason" ] && reason=${value}
      shift 3
      ;;
    *) shift ;;
  esac
done
printf '{"result":"%s","reason":"%s"}\n' "${result}" "${reason}"
""",
            )
            for command in ("chown", "chmod", "mkdir"):
                _write_executable(mock_bin / command, "#!/bin/sh\nexit 0\n")
            _write_executable(
                mock_bin / "mv",
                """#!/bin/sh
[ "${1-}" = "-f" ] && shift
cat "$1" > "$2"
: > "$1"
""",
            )
            _write_executable(
                mock_bin / "stat",
                """#!/bin/sh
if [ "${1-}" = "-c" ] && [ "${2-}" = "%s" ]; then
  wc -c < "$3" | tr -d ' '
  exit 0
fi
exit 1
""",
            )

            script = HEALTH_EVENT.read_text(encoding="utf-8")
            original = 'readonly LOG_DIRECTORY="/data/diagnostics/health"'
            replacement = (
                f'readonly LOG_DIRECTORY="{_bash_path(health_directory)}"'
            )
            self.assertEqual(script.count(original), 1)
            test_script = workspace / "tailscale-diagnostic-health-event"
            _write_executable(test_script, script.replace(original, replacement))

            environment = os.environ.copy()
            environment["PATH"] = (
                str(mock_bin)
                + os.pathsep
                + str(Path(bash).resolve().parent)
                + os.pathsep
                + environment.get("PATH", "")
            )

            def run_event(result: str, reason: str, started: str, online: str) -> None:
                completed = subprocess.run(
                    [
                        bash,
                        _bash_path(test_script),
                        "Running",
                        "true" if result == "healthy" else "false",
                        result,
                        reason,
                        started,
                        online,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
                )

            log_file = health_directory / "healthcheck.jsonl"
            run_event("healthy", "ok", "100", "150")
            run_event("healthy", "ok", "200", "250")
            run_event("unhealthy", "backend_stopped", "200", "250")
            run_event("unhealthy", "backend_stopped", "300", "350")
            run_event("unhealthy", "offline_timeout", "300", "350")
            run_event("healthy", "ok", "400", "450")

            records = [json.loads(line) for line in log_file.read_text().splitlines()]
            self.assertEqual(
                [(record["result"], record["reason"]) for record in records],
                [
                    ("healthy", "ok"),
                    ("unhealthy", "backend_stopped"),
                    ("unhealthy", "offline_timeout"),
                    ("healthy", "ok"),
                ],
            )

            log_file.write_text(
                ("x" * 524288) + '\n{"result":"healthy","reason":"ok"}\n',
                encoding="utf-8",
                newline="\n",
            )
            run_event("unhealthy", "offline_timeout", "500", "550")
            self.assertTrue((health_directory / "healthcheck.jsonl.1").is_file())
            rotated_records = [
                json.loads(line) for line in log_file.read_text().splitlines()
            ]
            self.assertEqual(
                [(record["result"], record["reason"]) for record in rotated_records],
                [("unhealthy", "offline_timeout")],
            )

    def test_verbose_capture_remains_opt_in_and_sanitized(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")
        stage2 = STAGE2_HOOK.read_text(encoding="utf-8")
        daemon = DAEMON_STREAM.read_text(encoding="utf-8")

        self.assertIn("diagnostic_capture: false", config)
        self.assertIn("bashio::config.false 'diagnostic_capture'", stage2)
        self.assertIn("tailscale-diagnostics-daemon-pipeline", stage2)
        self.assertIn("tailscale-diagnostics-state-pipeline", stage2)
        self.assertIn("debug daemon-logs --verbose=1", daemon)
        self.assertIn("tailscale-diagnostic-sanitize", daemon)


if __name__ == "__main__":
    unittest.main()
