#!/usr/bin/env python3
"""Functional regression checks for one-time Tailscale identity seeding."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = APP_ROOT / "rootfs/usr/bin/tailscale-diagnostics-seed"
BACKUP_SLUG = "1234abcd"
OFFICIAL_SOURCE = "a0d7b954_tailscale"
LOCAL_SOURCE = "local_tailscale"
SOURCE_ARCHIVES = {
    "official": OFFICIAL_SOURCE,
    "local": LOCAL_SOURCE,
}


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved.as_posix()
    drive, tail = os.path.splitdrive(str(resolved))
    return f"/{drive[0].lower()}{tail.replace(os.sep, '/')}"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = 0o600
    archive.addfile(member, io.BytesIO(content))


class DiagnosticSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bash = os.environ.get("BASH_EXE") or shutil.which("bash")
        if not self.bash:
            self.skipTest("Bash is required for the identity-seed checks")

    def _inner_archive(
        self,
        directory: Path,
        source: str,
        identity: bytes,
        *,
        include_state_directory: bool = True,
    ) -> Path:
        archive_path = directory / f"{source}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            _add_bytes(archive, "data/tailscaled.state", identity)
            if include_state_directory:
                state_directory = tarfile.TarInfo("data/state")
                state_directory.type = tarfile.DIRTYPE
                state_directory.mode = 0o700
                archive.addfile(state_directory)
                _add_bytes(archive, "data/state/profile.json", b"profile")
            _add_bytes(archive, "data/final_serve_reset_is_done", b"done")
        return archive_path

    def _outer_backup(self, directory: Path, archives: list[Path]) -> None:
        backup_path = directory / "backup" / f"{BACKUP_SLUG}.tar"
        backup_path.parent.mkdir()
        with tarfile.open(backup_path, "w") as backup:
            for archive_path in archives:
                backup.add(archive_path, arcname=archive_path.name)

    def _run_seed(
        self,
        workspace: Path,
        source: str,
        *,
        existing_identity: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        data_directory = workspace / "data"
        backup_directory = workspace / "backup"
        temp_directory = workspace / "tmp"
        mock_bin = workspace / "bin"
        for directory in (data_directory, temp_directory, mock_bin):
            directory.mkdir(exist_ok=True)
        if existing_identity:
            (data_directory / "tailscaled.state").write_bytes(b"existing")

        for command in ("chown", "sync"):
            _write_executable(mock_bin / command, "#!/bin/sh\nexit 0\n")

        script = SEED_SCRIPT.read_text(encoding="utf-8")
        replacements = {
            'readonly DATA_DIRECTORY="/data"': (
                f'readonly DATA_DIRECTORY="{_bash_path(data_directory)}"'
            ),
            'readonly BACKUP_DIRECTORY="/backup"': (
                f'readonly BACKUP_DIRECTORY="{_bash_path(backup_directory)}"'
            ),
            'readonly TEMP_DIRECTORY="/tmp"': (
                f'readonly TEMP_DIRECTORY="{_bash_path(temp_directory)}"'
            ),
        }
        for original, replacement in replacements.items():
            self.assertEqual(script.count(original), 1)
            script = script.replace(original, replacement)

        harness = f"""
bashio::config() {{
  case "$1" in
    diagnostic_seed_backup) printf '%s\\n' '{BACKUP_SLUG}' ;;
    diagnostic_seed_source) printf '%s\\n' '{source}' ;;
    *) return 1 ;;
  esac
}}
bashio::var.has_value() {{ [[ -n "${{1-}}" ]]; }}
bashio::exit.nok() {{ printf '%s\\n' "$1" >&2; exit 1; }}
bashio::log.info() {{ printf '%s\\n' "$1"; }}
"""
        test_script = workspace / "tailscale-diagnostics-seed"
        _write_executable(test_script, harness + script)

        environment = os.environ.copy()
        environment["PATH"] = (
            str(mock_bin)
            + os.pathsep
            + str(Path(self.bash).resolve().parent)
            + os.pathsep
            + environment.get("PATH", "")
        )
        return subprocess.run(
            [self.bash, _bash_path(test_script)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_selected_source_is_imported_from_backup_with_both_apps(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".seed-test-", dir=APP_ROOT) as temp:
            workspace = Path(temp)
            official = self._inner_archive(
                workspace, OFFICIAL_SOURCE, b"official-identity"
            )
            local = self._inner_archive(workspace, LOCAL_SOURCE, b"local-identity")
            self._outer_backup(workspace, [official, local])

            completed = self._run_seed(workspace, "local")

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertEqual(
                (workspace / "data/tailscaled.state").read_bytes(),
                b"local-identity",
            )
            marker = (workspace / "data/.diagnostic-seed-complete").read_text()
            self.assertIn(f"source_backup={BACKUP_SLUG}\n", marker)
            self.assertIn("source_selector=local\n", marker)
            self.assertIn(f"source_archive={LOCAL_SOURCE}.tar.gz\n", marker)

    def test_each_allowlisted_source_can_be_selected(self) -> None:
        for selector, source in SOURCE_ARCHIVES.items():
            with self.subTest(selector=selector), tempfile.TemporaryDirectory(
                prefix=".seed-test-", dir=APP_ROOT
            ) as temp:
                workspace = Path(temp)
                archive = self._inner_archive(workspace, source, source.encode())
                self._outer_backup(workspace, [archive])

                completed = self._run_seed(workspace, selector)

                self.assertEqual(completed.returncode, 0, msg=completed.stderr)
                self.assertEqual(
                    (workspace / "data/tailscaled.state").read_bytes(),
                    source.encode(),
                )

    def test_unsupported_or_missing_selected_source_fails_closed(self) -> None:
        cases = (
            ("other", LOCAL_SOURCE, "source is not supported"),
            ("disabled", LOCAL_SOURCE, "requires an enabled source"),
            ("local", OFFICIAL_SOURCE, "selected Tailscale add-on archive"),
        )
        for selected, archived, message in cases:
            with self.subTest(selected=selected), tempfile.TemporaryDirectory(
                prefix=".seed-test-", dir=APP_ROOT
            ) as temp:
                workspace = Path(temp)
                archive = self._inner_archive(workspace, archived, b"identity")
                self._outer_backup(workspace, [archive])

                completed = self._run_seed(workspace, selected)

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(message, completed.stderr)
                self.assertFalse((workspace / "data/tailscaled.state").exists())

    def test_missing_state_directory_or_existing_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".seed-test-", dir=APP_ROOT) as temp:
            workspace = Path(temp)
            archive = self._inner_archive(
                workspace,
                LOCAL_SOURCE,
                b"identity",
                include_state_directory=False,
            )
            self._outer_backup(workspace, [archive])

            completed = self._run_seed(workspace, "local")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("state directory", completed.stderr)
            self.assertFalse((workspace / "data/tailscaled.state").exists())

        with tempfile.TemporaryDirectory(prefix=".seed-test-", dir=APP_ROOT) as temp:
            workspace = Path(temp)
            archive = self._inner_archive(workspace, LOCAL_SOURCE, b"new-identity")
            self._outer_backup(workspace, [archive])

            completed = self._run_seed(
                workspace, "local", existing_identity=True
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Refusing to seed over", completed.stderr)
            self.assertEqual(
                (workspace / "data/tailscaled.state").read_bytes(), b"existing"
            )


if __name__ == "__main__":
    unittest.main()
