#!/usr/bin/env python3
"""Regression tests for the managed release and upstream-intake contracts."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import release_contract  # noqa: E402
import upstream_intake  # noqa: E402


class ReleaseContractTests(unittest.TestCase):
    def _published_fixture(self, clone: Path) -> dict:
        """Give a temporary copy internally consistent synthetic publication data."""
        manifest_path = clone / "release-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "published_verified_not_installed"
        image = manifest["release"]["image"]
        version = manifest["release"]["custom_version"]
        repository = manifest["repository"]["canonical_url"]
        image_prefix, image_name = image.rsplit("/", 1)
        manifest["release"]["publication"] = {
            "source_commit": "1" * 40,
            "image_reference": f"{image}:{version}",
            "image_index_digest": "sha256:" + "2" * 64,
            "image_index_media_type": "application/vnd.oci.image.index.v1+json",
            "published_at_utc": "2026-10-31T00:00:00Z",
            "workflow_run_id": 1,
            "workflow_run_url": f"{repository}/actions/runs/1",
            "architectures": {
                architecture: {
                    "image": f"{image_prefix}/{architecture}-{image_name}",
                    "image_index_digest": "sha256:" + "3" * 64,
                    "platform": platform,
                    "manifest_digest": "sha256:" + "4" * 64,
                    "config_digest": "sha256:" + "5" * 64,
                }
                for architecture, platform in (
                    ("amd64", "linux/amd64"), ("aarch64", "linux/arm64")
                )
            },
            "signature": {
                "verifier": "cosign v3.0.6",
                "certificate_identity": (
                    f"{repository}/.github/workflows/release.yaml@refs/heads/main"
                ),
                "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
                "transparency_log_verified": True,
            },
        }
        for key in (
            "multi_arch_images_built", "published", "anonymous_pull_verified",
            "signature_verified",
        ):
            manifest["verification"][key] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        config = clone / "tailscale" / "config.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "stage: experimental", "stage: stable"
            ),
            encoding="utf-8",
            newline="\n",
        )
        return manifest

    def test_current_repository_satisfies_contract_and_getter(self) -> None:
        manifest = release_contract.validate_repository(ROOT)
        self.assertEqual(
            release_contract.resolve_dotted(manifest, "release.custom_version"),
            "0.30.5-wanfix.1",
        )

        lookups = {
            "status": manifest["status"],
            "release.custom_version": "0.30.5-wanfix.1",
            "upstream.tailscale.version": "1.104.4",
            "upstream.app.runtime_image": (
                "ghcr.io/hassio-addons/tailscale:0.30.5"
            ),
            "upstream.app.runtime_image_index_digest": (
                "sha256:edf3932b4bd5205df4ed94809b622286465259b206e4ccaa1046c020c50328a8"
            ),
            "build.builder_image": "golang:1.27.3-alpine",
            "build.builder_image_index_digest": (
                "sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb"
            ),
            "build.base_images_digest_pinned": "true",
            "release.automatic_install": "false",
            "source.candidate_commit": manifest["source"]["candidate_commit"],
        }
        for dotted_path, expected in lookups.items():
            with self.subTest(dotted_path=dotted_path):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = release_contract.main(
                        ["--root", str(ROOT), "--get", dotted_path]
                    )
                self.assertEqual(result, 0)
                self.assertEqual(output.getvalue().strip(), expected)

    def test_config_version_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-contract-") as temporary:
            clone = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                clone,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "upstream-candidates"
                ),
            )
            config = clone / "tailscale" / "config.yaml"
            content = config.read_text(encoding="utf-8")
            expected = "version: 0.30.5-wanfix.1"
            self.assertEqual(content.count(expected), 1)
            config.write_text(
                content.replace(expected, "version: 0.30.5-wanfix.99"),
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(
                release_contract.ContractError,
                "config.yaml version does not match",
            ):
                release_contract.validate_repository(clone)

    def test_unpublished_candidate_boundary_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-contract-") as temporary:
            clone = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                clone,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "upstream-candidates"
                ),
            )
            manifest_path = clone / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "locally_validated_not_published"
            manifest["release"].pop("publication", None)
            for key in (
                "multi_arch_images_built",
                "published",
                "anonymous_pull_verified",
                "signature_verified",
            ):
                manifest["verification"][key] = False
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            config = clone / "tailscale" / "config.yaml"
            content = config.read_text(encoding="utf-8")
            if "stage: stable" in content:
                config.write_text(
                    content.replace("stage: stable", "stage: experimental"),
                    encoding="utf-8",
                    newline="\n",
                )
            else:
                self.assertEqual(content.count("stage: experimental"), 1)

            candidate = release_contract.validate_repository(clone)
            self.assertEqual(
                release_contract.resolve_dotted(candidate, "status"),
                "locally_validated_not_published",
            )

    def test_unpinned_base_image_fails(self) -> None:
        manifest = release_contract.load_manifest(ROOT)
        pinned_references = (
            (
                manifest["build"]["builder_image"] + "@"
                + manifest["build"]["builder_image_index_digest"],
                manifest["build"]["builder_image"],
            ),
            (
                manifest["upstream"]["app"]["runtime_image"] + "@"
                + manifest["upstream"]["app"]["runtime_image_index_digest"],
                manifest["upstream"]["app"]["runtime_image"],
            ),
        )
        for pinned, unpinned in pinned_references:
            with self.subTest(image=unpinned), tempfile.TemporaryDirectory(
                prefix="release-contract-"
            ) as temporary:
                clone = Path(temporary) / "repository"
                shutil.copytree(
                    ROOT,
                    clone,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "upstream-candidates"
                    ),
                )
                dockerfile = clone / "tailscale" / "Dockerfile"
                content = dockerfile.read_text(encoding="utf-8")
                self.assertEqual(content.count(pinned), 1)
                dockerfile.write_text(
                    content.replace(pinned, unpinned),
                    encoding="utf-8",
                    newline="\n",
                )
                with self.assertRaisesRegex(
                    release_contract.ContractError,
                    "digest-pinned builder and runtime images",
                ):
                    release_contract.validate_repository(clone)

    def test_malformed_base_image_digest_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-contract-") as temporary:
            clone = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                clone,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "upstream-candidates"
                ),
            )
            manifest_path = clone / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["build"]["builder_image_index_digest"] = "sha256:NOT-A-DIGEST"
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(
                release_contract.ContractError,
                "lowercase sha256 OCI digest",
            ):
                release_contract.validate_repository(clone)

    def test_malformed_published_image_digest_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-contract-") as temporary:
            clone = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                clone,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "upstream-candidates"
                ),
            )
            manifest = self._published_fixture(clone)
            release_contract.validate_repository(clone)
            manifest["release"]["publication"]["image_index_digest"] = (
                "sha256:NOT-A-PUBLISHED-DIGEST"
            )
            manifest_path = clone / "release-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(
                release_contract.ContractError,
                "lowercase sha256 OCI digest",
            ):
                release_contract.validate_repository(clone)


class UpstreamIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="upstream-intake-")
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        shutil.copyfile(
            ROOT / "release-manifest.json", self.root / "release-manifest.json"
        )
        # Intake tests use a fixed baseline independent of the candidate release.
        manifest_path = self.root / "release-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["upstream"]["app"]["version"] = "0.28.1"
        manifest["upstream"]["app"]["tag"] = "v0.28.1"
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _release_file(self, **overrides: object) -> Path:
        value: dict[str, object] = {
            "tag_name": "v0.28.1",
            "draft": False,
            "prerelease": False,
        }
        value.update(overrides)
        path = Path(self.temporary.name) / "release.json"
        path.write_text(
            json.dumps(value, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def test_version_normalization_and_numeric_comparison(self) -> None:
        self.assertEqual(
            upstream_intake.parse_version("v1.20.3"),
            ("1.20.3", (1, 20, 3)),
        )
        self.assertEqual(upstream_intake.compare_versions("1.10.0", "1.9.99"), 1)
        self.assertEqual(upstream_intake.compare_versions("v2.0.0", "2.0.0"), 0)
        self.assertEqual(upstream_intake.compare_versions("0.9.0", "1.0.0"), -1)

    def test_equal_release_is_a_no_change(self) -> None:
        outputs = upstream_intake.process_release(
            self.root, self._release_file(tag_name="0.28.1")
        )
        self.assertEqual(outputs["changed"], "false")
        self.assertEqual(outputs["upstream_version"], "0.28.1")
        self.assertEqual(outputs["descriptor_path"], "")
        self.assertFalse((self.root / "upstream-candidates").exists())

    def test_new_release_is_deterministic_and_idempotent(self) -> None:
        release = self._release_file(tag_name="v0.29.0")
        first = upstream_intake.process_release(self.root, release)
        descriptor_path = self.root / "upstream-candidates" / "v0.29.0.json"
        first_content = descriptor_path.read_bytes()

        self.assertEqual(first["changed"], "true")
        self.assertEqual(
            first["descriptor_path"], "upstream-candidates/v0.29.0.json"
        )
        self.assertEqual(first["branch_name"], "automation/upstream-v0.29.0")
        self.assertEqual(first["upstream_version"], "0.29.0")
        descriptor = json.loads(first_content)
        self.assertEqual(descriptor["baseline"]["version"], "0.28.1")
        self.assertEqual(descriptor["candidate"]["version"], "0.29.0")
        self.assertFalse(descriptor["policy"]["automatic_publish"])

        second = upstream_intake.process_release(self.root, release)
        self.assertEqual(second["changed"], "false")
        self.assertEqual(descriptor_path.read_bytes(), first_content)
        self.assertEqual(second["branch_name"], first["branch_name"])

    def test_prerelease_is_ignored_before_tag_validation(self) -> None:
        outputs = upstream_intake.process_release(
            self.root,
            self._release_file(tag_name="not-a-version", prerelease=True),
        )
        self.assertEqual(outputs, upstream_intake._empty_outputs())
        self.assertFalse((self.root / "upstream-candidates").exists())

    def test_malformed_stable_release_fails(self) -> None:
        for malformed in ("v1.2", "release-1.2.3", "v01.2.3", "1.2.3-rc1"):
            with self.subTest(tag_name=malformed):
                with self.assertRaisesRegex(
                    release_contract.ContractError,
                    "not strict",
                ):
                    upstream_intake.process_release(
                        self.root, self._release_file(tag_name=malformed)
                    )


if __name__ == "__main__":
    unittest.main()
