#!/usr/bin/env python3
"""Validate and query the managed Home Assistant app release contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


MANIFEST_NAME = "release-manifest.json"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OCI_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UPSTREAM_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
CUSTOM_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)-wanfix\.(?:0|[1-9][0-9]*)$"
)
ACTION_USE_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*[\"']?([^\"'\s#]+)[\"']?\s*(?:#.*)?$"
)
PINNED_ACTION_RE = re.compile(r"^([^@]+)@([0-9a-fA-F]{40})$")

ROOT_DOCUMENTS = (
    "README.md",
    "LICENSE.md",
    "SECURITY.md",
    "UPSTREAM.md",
)
APP_DOCUMENTS = (
    "README.md",
    "DOCS.md",
    "CHANGELOG.md",
)


class ContractError(ValueError):
    """Raised when repository state violates the release contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContractError(f"required file is missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ContractError(f"required text file is not UTF-8: {path}") from exc


def load_manifest(root: Path) -> dict[str, Any]:
    """Load the release manifest from *root* without validating other files."""

    path = root.resolve() / MANIFEST_NAME
    try:
        value = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise ContractError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
    _require(isinstance(value, dict), f"{MANIFEST_NAME} must contain an object")
    return value


def resolve_dotted(value: Any, dotted_path: str) -> Any:
    """Resolve a dotted path through dictionaries and list indexes."""

    _require(bool(dotted_path), "dotted path must not be empty")
    current = value
    traversed: list[str] = []
    for component in dotted_path.split("."):
        _require(bool(component), f"invalid dotted path: {dotted_path!r}")
        traversed.append(component)
        if isinstance(current, dict):
            _require(
                component in current,
                f"manifest path does not exist: {'.'.join(traversed)}",
            )
            current = current[component]
        elif isinstance(current, list) and component.isdigit():
            index = int(component)
            _require(
                index < len(current),
                f"manifest list index is out of range: {'.'.join(traversed)}",
            )
            current = current[index]
        else:
            raise ContractError(
                f"manifest path cannot traverse {'.'.join(traversed)}"
            )
    return current


def _manifest_value(
    manifest: dict[str, Any], dotted_path: str, expected_type: type
) -> Any:
    value = resolve_dotted(manifest, dotted_path)
    _require(
        isinstance(value, expected_type),
        f"manifest value {dotted_path} must be {expected_type.__name__}",
    )
    if expected_type is str:
        _require(bool(value), f"manifest value {dotted_path} must not be empty")
    return value


def _yaml_scalar(text: str, key: str, source: Path) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*$")
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            continue
        match = pattern.match(line)
        if not match:
            continue
        raw = match.group(1)
        if " #" in raw:
            raw = raw.split(" #", 1)[0].rstrip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        _require(bool(raw), f"top-level YAML key {key} is empty in {source}")
        return raw
    raise ContractError(f"top-level YAML key {key} is missing from {source}")


def _yaml_list(text: str, key: str, source: Path) -> list[str]:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if re.fullmatch(rf"{re.escape(key)}:\s*", line):
            start = index + 1
            break
    _require(start is not None, f"top-level YAML list {key} is missing from {source}")

    values: list[str] = []
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break
        match = re.match(r"^\s+-\s+([^#]+?)(?:\s+#.*)?$", line)
        if match:
            item = match.group(1).strip().strip("\"'")
            values.append(item)
    _require(bool(values), f"top-level YAML list {key} is empty in {source}")
    return values


def _safe_repository_path(root: Path, relative: str, label: str) -> Path:
    _require("\\" not in relative, f"{label} must use forward slashes")
    candidate_path = Path(relative)
    _require(not candidate_path.is_absolute(), f"{label} must be repository-relative")
    _require(".." not in candidate_path.parts, f"{label} must not contain '..'")
    candidate = (root / candidate_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"{label} resolves outside the repository") from exc
    return candidate


def _docker_arg(dockerfile: str, name: str) -> str:
    pattern = re.compile(
        rf"^ARG\s+{re.escape(name)}=(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))\s*$",
        re.MULTILINE,
    )
    match = pattern.search(dockerfile)
    _require(match is not None, f"Dockerfile must define ARG {name} with a default")
    assert match is not None
    return next(group for group in match.groups() if group is not None)


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    _require(manifest.get("schema_version") == 1, "unsupported manifest schema_version")
    _require(manifest.get("channel") == "stable", "manifest channel must be stable")
    _require(
        manifest.get("status") in {"locally_validated_not_published"},
        "manifest status is not allowed at the publication boundary",
    )

    string_paths = (
        "repository.canonical_url",
        "repository.stable_branch",
        "repository.app_directory",
        "repository.app_slug",
        "release.custom_version",
        "release.image",
        "upstream.app.repository",
        "upstream.app.version",
        "upstream.app.tag",
        "upstream.app.commit",
        "upstream.app.tree",
        "upstream.app.runtime_image",
        "upstream.app.runtime_image_index_digest",
        "upstream.tailscale.repository",
        "upstream.tailscale.version",
        "upstream.tailscale.tag",
        "upstream.tailscale.commit",
        "upstream.tailscale.patched_tree",
        "source.candidate_commit",
        "source.candidate_tree",
        "build.builder_image",
        "build.builder_image_index_digest",
        "build.builder_action_commit",
        "build.checkout_action_commit",
    )
    for path in string_paths:
        _manifest_value(manifest, path, str)

    upstream_app_version = resolve_dotted(manifest, "upstream.app.version")
    tailscale_version = resolve_dotted(manifest, "upstream.tailscale.version")
    custom_version = resolve_dotted(manifest, "release.custom_version")
    _require(
        UPSTREAM_VERSION_RE.fullmatch(upstream_app_version) is not None,
        "upstream.app.version must be strict X.Y.Z",
    )
    _require(
        UPSTREAM_VERSION_RE.fullmatch(tailscale_version) is not None,
        "upstream.tailscale.version must be strict X.Y.Z",
    )
    _require(
        CUSTOM_VERSION_RE.fullmatch(custom_version) is not None,
        "release.custom_version must be X.Y.Z-wanfix.N",
    )
    _require(
        resolve_dotted(manifest, "upstream.app.tag") == f"v{upstream_app_version}",
        "upstream.app.tag must match upstream.app.version",
    )
    _require(
        resolve_dotted(manifest, "upstream.tailscale.tag") == f"v{tailscale_version}",
        "upstream.tailscale.tag must match upstream.tailscale.version",
    )
    _require(
        resolve_dotted(manifest, "upstream.app.runtime_image")
        == f"ghcr.io/hassio-addons/tailscale:{upstream_app_version}",
        "upstream.app.runtime_image must match upstream.app.version",
    )
    _require(
        re.fullmatch(
            r"golang:(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
            r"(?:0|[1-9][0-9]*)-alpine",
            resolve_dotted(manifest, "build.builder_image"),
        )
        is not None,
        "build.builder_image must be a versioned golang alpine image",
    )

    for path in (
        "upstream.app.runtime_image_index_digest",
        "build.builder_image_index_digest",
    ):
        _require(
            OCI_DIGEST_RE.fullmatch(resolve_dotted(manifest, path)) is not None,
            f"manifest value {path} must be a lowercase sha256 OCI digest",
        )

    sha_paths = (
        "upstream.app.commit",
        "upstream.app.tree",
        "upstream.tailscale.commit",
        "upstream.tailscale.patched_tree",
        "source.candidate_commit",
        "source.candidate_tree",
        "build.builder_action_commit",
        "build.checkout_action_commit",
    )
    for path in sha_paths:
        _require(
            SHA1_RE.fullmatch(resolve_dotted(manifest, path)) is not None,
            f"manifest value {path} must be a lowercase 40-hex object ID",
        )

    custom_commits = _manifest_value(manifest, "source.custom_commits", list)
    _require(bool(custom_commits), "source.custom_commits must not be empty")
    for commit in custom_commits:
        _require(
            isinstance(commit, str) and SHA1_RE.fullmatch(commit) is not None,
            "every source.custom_commits entry must be a lowercase 40-hex commit",
        )
    _require(
        custom_commits[-1] == resolve_dotted(manifest, "source.candidate_commit"),
        "source.candidate_commit must be the final custom commit",
    )

    architectures = _manifest_value(manifest, "build.architectures", list)
    _require(
        architectures == ["amd64", "aarch64"],
        "build.architectures must be the reviewed amd64/aarch64 set",
    )
    _require(
        resolve_dotted(manifest, "release.mutable_tags") is False,
        "release.mutable_tags must be false",
    )
    _require(
        resolve_dotted(manifest, "release.automatic_install") is False,
        "release.automatic_install must be false",
    )

    verification_boundary = {
        "source_locally_validated": True,
        "multi_arch_images_built": False,
        "published": False,
        "installed": False,
        "activated": False,
        "live_verified": False,
        "failover_verified": False,
        "failback_verified": False,
    }
    for key, expected in verification_boundary.items():
        _require(
            resolve_dotted(manifest, f"verification.{key}") is expected,
            f"verification.{key} must be {str(expected).lower()}",
        )
    _require(
        resolve_dotted(manifest, "build.base_images_digest_pinned") is True,
        "build.base_images_digest_pinned must be true",
    )
    _require(
        resolve_dotted(manifest, "build.hermetic") is False,
        "build.hermetic must remain false until dependency closure is captured",
    )

    image = resolve_dotted(manifest, "release.image")
    _require(
        re.fullmatch(r"ghcr[.]io/[a-z0-9._-]+/[a-z0-9._-]+", image) is not None,
        "release.image must be an untagged lowercase GHCR image name",
    )
    canonical_url = resolve_dotted(manifest, "repository.canonical_url")
    _require(
        re.fullmatch(r"https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", canonical_url)
        is not None,
        "repository.canonical_url must be a canonical GitHub repository URL",
    )
    _require(
        re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            resolve_dotted(manifest, "upstream.app.repository"),
        )
        is not None,
        "upstream.app.repository must be owner/name",
    )


def _validate_documents(root: Path, app_root: Path) -> None:
    for relative in ROOT_DOCUMENTS:
        path = root / relative
        _require(path.is_file() and path.stat().st_size > 0, f"required document missing: {relative}")
    for relative in APP_DOCUMENTS:
        path = app_root / relative
        display = path.relative_to(root).as_posix()
        _require(path.is_file() and path.stat().st_size > 0, f"required document missing: {display}")

    obsolete = [
        path
        for path in root.rglob("build.yaml")
        if ".git" not in path.relative_to(root).parts
    ]
    _require(
        not obsolete,
        "obsolete build.yaml must be absent: "
        + ", ".join(path.relative_to(root).as_posix() for path in obsolete),
    )


def _validate_configuration(
    root: Path, app_root: Path, manifest: dict[str, Any]
) -> None:
    config_path = app_root / "config.yaml"
    config = _read_text(config_path)
    expected_scalars = {
        "version": resolve_dotted(manifest, "release.custom_version"),
        "slug": resolve_dotted(manifest, "repository.app_slug"),
        "url": resolve_dotted(manifest, "repository.canonical_url"),
        "image": resolve_dotted(manifest, "release.image"),
        "stage": "experimental",
    }
    for key, expected in expected_scalars.items():
        actual = _yaml_scalar(config, key, config_path)
        _require(actual == expected, f"config.yaml {key} does not match the manifest")

    config_architectures = _yaml_list(config, "arch", config_path)
    manifest_architectures = resolve_dotted(manifest, "build.architectures")
    _require(
        set(config_architectures) == set(manifest_architectures)
        and len(config_architectures) == len(manifest_architectures),
        "config.yaml arch does not match build.architectures",
    )

    repository_path = root / "repository.yaml"
    repository = _read_text(repository_path)
    for key in ("name", "maintainer"):
        _yaml_scalar(repository, key, repository_path)
    repository_url = _yaml_scalar(repository, "url", repository_path)
    _require(
        repository_url == resolve_dotted(manifest, "repository.canonical_url"),
        "repository.yaml url does not match repository.canonical_url",
    )


def _validate_dockerfile_and_patches(
    root: Path, app_root: Path, manifest: dict[str, Any]
) -> None:
    dockerfile_path = app_root / "Dockerfile"
    dockerfile = _read_text(dockerfile_path)
    tailscale_commit = resolve_dotted(manifest, "upstream.tailscale.commit")
    tailscale_version = resolve_dotted(manifest, "upstream.tailscale.version")
    tailscale_tag = resolve_dotted(manifest, "upstream.tailscale.tag")
    runtime_image = resolve_dotted(manifest, "upstream.app.runtime_image")
    runtime_image_digest = resolve_dotted(
        manifest, "upstream.app.runtime_image_index_digest"
    )
    builder_image = resolve_dotted(manifest, "build.builder_image")
    builder_image_digest = resolve_dotted(
        manifest, "build.builder_image_index_digest"
    )

    _require(
        _docker_arg(dockerfile, "TAILSCALE_COMMIT") == tailscale_commit,
        "Dockerfile TAILSCALE_COMMIT does not match the manifest",
    )
    _require(
        _docker_arg(dockerfile, "TAILSCALE_VERSION_SHORT") == tailscale_version,
        "Dockerfile TAILSCALE_VERSION_SHORT does not match the manifest",
    )
    _require(
        re.search(rf"--branch\s+{re.escape(tailscale_tag)}(?:\s|\\)", dockerfile)
        is not None,
        "Dockerfile clone tag does not match upstream.tailscale.tag",
    )
    from_lines = [
        (match.group(1), match.group(2).lower() if match.group(2) else None)
        for match in re.finditer(
            r"^FROM\s+([^\s]+)(?:\s+AS\s+([A-Za-z0-9._-]+))?\s*$",
            dockerfile,
            re.IGNORECASE | re.MULTILINE,
        )
    ]
    expected_from_lines = [
        (
            f"{builder_image}@{builder_image_digest}",
            "tailscale-wanfix-builder",
        ),
        (f"{runtime_image}@{runtime_image_digest}", None),
    ]
    _require(
        from_lines == expected_from_lines,
        "Dockerfile must use exactly the digest-pinned builder and runtime images",
    )

    patches = _manifest_value(manifest, "patches", list)
    _require(bool(patches), "manifest patches list must not be empty")
    for index, patch in enumerate(patches):
        _require(isinstance(patch, dict), f"patches.{index} must be an object")
        relative = patch.get("path")
        expected_hash = patch.get("sha256")
        _require(
            isinstance(relative, str) and bool(relative),
            f"patches.{index}.path must be a non-empty string",
        )
        _require(
            isinstance(expected_hash, str)
            and SHA256_RE.fullmatch(expected_hash) is not None,
            f"patches.{index}.sha256 must be lowercase 64-hex",
        )
        patch_path = _safe_repository_path(root, relative, f"patches.{index}.path")
        _require(patch_path.is_file(), f"embedded patch is missing: {relative}")
        actual_hash = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        _require(
            actual_hash == expected_hash,
            f"embedded patch hash mismatch for {relative}",
        )
        try:
            docker_relative = patch_path.relative_to(app_root).as_posix()
        except ValueError as exc:
            raise ContractError(f"embedded patch must be inside the app directory: {relative}") from exc
        _require(
            re.search(
                rf"^COPY\s+(?:--[^\s]+\s+)*{re.escape(docker_relative)}(?:\s|$)",
                dockerfile,
                re.MULTILINE,
            )
            is not None,
            f"Dockerfile does not copy embedded patch {docker_relative}",
        )


def _workflow_lines_without_comments(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(line.split(" #", 1)[0])
    return lines


def _validate_workflows(root: Path, manifest: dict[str, Any]) -> None:
    workflow_root = root / ".github" / "workflows"
    _require(workflow_root.is_dir(), "workflow directory is missing")
    workflows = sorted(workflow_root.glob("*.yml")) + sorted(workflow_root.glob("*.yaml"))
    _require(bool(workflows), "no GitHub workflows were found")

    expected_pins = {
        "actions/checkout": resolve_dotted(manifest, "build.checkout_action_commit"),
        "home-assistant/builder": resolve_dotted(manifest, "build.builder_action_commit"),
    }
    seen = {key: False for key in expected_pins}
    for workflow in workflows:
        for line_number, line in enumerate(_read_text(workflow).splitlines(), start=1):
            match = ACTION_USE_RE.match(line)
            if not match:
                continue
            use = match.group(1)
            if use.startswith("./"):
                continue
            pinned = PINNED_ACTION_RE.fullmatch(use)
            _require(
                pinned is not None,
                f"external workflow use is not pinned to 40 hex: "
                f"{workflow.relative_to(root).as_posix()}:{line_number}: {use}",
            )
            assert pinned is not None
            action, commit = pinned.groups()
            for prefix, expected_commit in expected_pins.items():
                if action == prefix or action.startswith(prefix + "/"):
                    seen[prefix] = True
                    _require(
                        commit.lower() == expected_commit,
                        f"{prefix} pin does not match release-manifest.json",
                    )

    for prefix, was_seen in seen.items():
        _require(was_seen, f"required pinned workflow action is not used: {prefix}")

    release_workflows = [path for path in workflows if path.stem.lower() == "release"]
    _require(len(release_workflows) == 1, "exactly one release workflow is required")
    release_lines = _workflow_lines_without_comments(_read_text(release_workflows[0]))
    for line_number, line in enumerate(release_lines, start=1):
        _require(
            re.search(r"(?i)(?<![A-Za-z0-9_.-])latest(?![A-Za-z0-9_.-])", line)
            is None,
            f"release workflow must not publish mutable latest tags (line {line_number})",
        )


def validate_repository(root: Path) -> dict[str, Any]:
    """Validate all local source and distribution contracts and return the manifest."""

    root = root.resolve()
    _require(root.is_dir(), f"repository root is not a directory: {root}")
    manifest = load_manifest(root)
    _validate_manifest_shape(manifest)

    app_directory = resolve_dotted(manifest, "repository.app_directory")
    app_root = _safe_repository_path(root, app_directory, "repository.app_directory")
    _require(app_root.is_dir(), "repository.app_directory does not exist")

    _validate_documents(root, app_root)
    _validate_configuration(root, app_root, manifest)
    _validate_dockerfile_and_patches(root, app_root, manifest)
    _validate_workflows(root, manifest)
    return manifest


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _normalize_requested_custom_version(value: str) -> str:
    normalized = value[1:] if value.startswith("v") else value
    _require(
        CUSTOM_VERSION_RE.fullmatch(normalized) is not None,
        "--version must be v?X.Y.Z-wanfix.N",
    )
    return normalized


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("validate",),
        default="validate",
        help="operation to perform (default: validate)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--get",
        dest="get_path",
        metavar="DOTTED.PATH",
        help="print a validated release-manifest value",
    )
    parser.add_argument(
        "--version",
        help="require this v?X.Y.Z-wanfix.N release version",
    )
    parser.add_argument(
        "--source-sha",
        help="require this exact checked-out Git commit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        manifest = validate_repository(args.root)
        if args.version:
            expected = resolve_dotted(manifest, "release.custom_version")
            _require(
                _normalize_requested_custom_version(args.version) == expected,
                "requested release version does not match release.custom_version",
            )
        if args.source_sha:
            _require(
                SHA1_RE.fullmatch(args.source_sha) is not None,
                "--source-sha must be lowercase 40 hex",
            )
            try:
                completed = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=args.root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise ContractError("could not resolve the checked-out Git commit") from exc
            _require(
                completed.stdout.strip() == args.source_sha,
                "requested source SHA does not match the checked-out Git commit",
            )
        if args.get_path:
            print(_format_value(resolve_dotted(manifest, args.get_path)))
        else:
            print(
                "release contract valid: "
                + resolve_dotted(manifest, "release.custom_version")
            )
    except ContractError as exc:
        print(f"release contract error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
