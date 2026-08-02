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
    def test_current_repository_satisfies_contract_and_getter(self) -> None:
        manifest = release_contract.validate_repository(ROOT)
        self.assertEqual(
            release_contract.resolve_dotted(manifest, "release.custom_version"),
            "0.28.1-wanfix.3",
        )

        lookups = {
            "status": "locally_validated_not_published",
            "release.custom_version": "0.28.1-wanfix.3",
            "upstream.app.runtime_image": (
                "ghcr.io/hassio-addons/tailscale:0.28.1"
            ),
            "upstream.app.runtime_image_index_digest": (
                "sha256:2a15916111291ade93481fe17f4b30107610b1d510c02f7645d83a36fad4aece"
            ),
            "build.builder_image": "golang:1.26.1-alpine",
            "build.builder_image_index_digest": (
                "sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039"
            ),
            "build.base_images_digest_pinned": "true",
            "verification.anonymous_pull_verified": "false",
            "verification.signature_verified": "false",
            "source.candidate_commit": (
                "d6b6ffd28711c40f83b2bd62d9c8b97f2aaaa2e3"
            ),
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
            expected = "version: 0.28.1-wanfix.3"
            self.assertEqual(content.count(expected), 1)
            config.write_text(
                content.replace(expected, "version: 0.28.1-wanfix.99"),
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
        pinned_references = (
            (
                "golang:1.26.1-alpine@sha256:"
                "2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039",
                "golang:1.26.1-alpine",
            ),
            (
                "ghcr.io/hassio-addons/tailscale:0.28.1@sha256:"
                "2a15916111291ade93481fe17f4b30107610b1d510c02f7645d83a36fad4aece",
                "ghcr.io/hassio-addons/tailscale:0.28.1",
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
        if "publication" not in release_contract.load_manifest(ROOT)["release"]:
            self.skipTest("current checkout is an unpublished candidate")
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
            manifest["release"]["publication"]["image_index_digest"] = (
                "sha256:NOT-A-PUBLISHED-DIGEST"
            )
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
