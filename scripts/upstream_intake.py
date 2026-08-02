#!/usr/bin/env python3
"""Create a deterministic review descriptor from offline GitHub release JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from release_contract import ContractError, SHA1_RE, load_manifest, resolve_dotted


VERSION_RE = re.compile(
    r"^v?((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*))$"
)
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OUTPUT_KEYS = (
    "changed",
    "descriptor_path",
    "upstream_version",
    "branch_name",
    "pr_title",
    "pr_body",
)


def parse_version(value: str) -> tuple[str, tuple[int, int, int]]:
    """Normalize a strict v?X.Y.Z version and return its numeric tuple."""

    if not isinstance(value, str):
        raise ContractError("release tag_name must be a string")
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise ContractError(f"release tag_name is not strict v?X.Y.Z: {value!r}")
    normalized = match.group(1)
    return normalized, tuple(int(component) for component in normalized.split("."))


def compare_versions(left: str, right: str) -> int:
    """Compare strict versions, returning -1, 0, or 1."""

    _, left_parts = parse_version(left)
    _, right_parts = parse_version(right)
    return (left_parts > right_parts) - (left_parts < right_parts)


def _load_release(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"release JSON file is missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ContractError(f"release JSON file is not UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"release JSON is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("release JSON must contain one GitHub release object")
    for flag in ("draft", "prerelease"):
        if flag in value and not isinstance(value[flag], bool):
            raise ContractError(f"release JSON {flag} must be a boolean")
    return value


def _safe_output_path(root: Path, output: Path | None, version: str) -> Path:
    expected_name = f"v{version}.json"
    candidate = output or Path("upstream-candidates") / expected_name
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError("descriptor output must remain inside the repository") from exc
    if relative.as_posix() != f"upstream-candidates/{expected_name}":
        raise ContractError(
            "descriptor output must be upstream-candidates/" + expected_name
        )
    return candidate


def _baseline(manifest: dict[str, Any]) -> dict[str, str]:
    paths = {
        "repository": "upstream.app.repository",
        "version": "upstream.app.version",
        "tag": "upstream.app.tag",
        "commit": "upstream.app.commit",
        "tree": "upstream.app.tree",
    }
    baseline: dict[str, str] = {}
    for key, dotted in paths.items():
        value = resolve_dotted(manifest, dotted)
        if not isinstance(value, str) or not value:
            raise ContractError(f"manifest value {dotted} must be a non-empty string")
        baseline[key] = value
    normalized, _ = parse_version(baseline["version"])
    if normalized != baseline["version"]:
        raise ContractError("upstream.app.version must not include a v prefix")
    if baseline["tag"] != f"v{normalized}":
        raise ContractError("upstream.app.tag does not match upstream.app.version")
    if REPOSITORY_RE.fullmatch(baseline["repository"]) is None:
        raise ContractError("upstream.app.repository must be owner/name")
    for field in ("commit", "tree"):
        if SHA1_RE.fullmatch(baseline[field]) is None:
            raise ContractError(f"upstream.app.{field} must be lowercase 40 hex")
    return baseline


def _descriptor(baseline: dict[str, str], version: str) -> dict[str, Any]:
    repository = baseline["repository"]
    tag = f"v{version}"
    return {
        "schema_version": 1,
        "kind": "home_assistant_app_upstream_release",
        "status": "review_required",
        "baseline": {
            "repository": repository,
            "version": baseline["version"],
            "tag": baseline["tag"],
            "commit": baseline["commit"],
            "tree": baseline["tree"],
        },
        "candidate": {
            "repository": repository,
            "version": version,
            "tag": tag,
            "release_url": f"https://github.com/{repository}/releases/tag/{tag}",
        },
        "policy": {
            "automatic_rebase": False,
            "automatic_merge": False,
            "automatic_publish": False,
            "live_system_contact": False,
        },
    }


def _write_if_changed(path: Path, value: dict[str, Any]) -> bool:
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except UnicodeDecodeError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return True


def _empty_outputs(upstream_version: str = "") -> dict[str, str]:
    return {
        "changed": "false",
        "descriptor_path": "",
        "upstream_version": upstream_version,
        "branch_name": "",
        "pr_title": "",
        "pr_body": "",
    }


def _candidate_outputs(
    root: Path, descriptor_path: Path, baseline: dict[str, str], version: str, changed: bool
) -> dict[str, str]:
    relative = descriptor_path.relative_to(root).as_posix()
    tag = f"v{version}"
    title = f"Review upstream app {tag}"
    body = (
        f"Review `{baseline['repository']}` release `{tag}` against the pinned "
        f"baseline `{baseline['tag']}`.\n\n"
        f"The deterministic intake descriptor is `{relative}`. This intake does "
        "not rebase, merge, publish, install, or contact Home Assistant."
    )
    return {
        "changed": "true" if changed else "false",
        "descriptor_path": relative,
        "upstream_version": version,
        "branch_name": f"automation/upstream-{tag}",
        "pr_title": title,
        "pr_body": body,
    }


def process_release(
    root: Path, release_json: Path, output: Path | None = None
) -> dict[str, str]:
    """Process one offline GitHub release payload and return workflow outputs."""

    root = root.resolve()
    if not root.is_dir():
        raise ContractError(f"repository root is not a directory: {root}")
    manifest = load_manifest(root)
    baseline = _baseline(manifest)
    release = _load_release(release_json)

    if release.get("draft", False) or release.get("prerelease", False):
        return _empty_outputs()

    tag_name = release.get("tag_name")
    version, _ = parse_version(tag_name)
    comparison = compare_versions(version, baseline["version"])
    if comparison <= 0:
        return _empty_outputs(version)

    descriptor_path = _safe_output_path(root, output, version)
    changed = _write_if_changed(descriptor_path, _descriptor(baseline, version))
    return _candidate_outputs(root, descriptor_path, baseline, version, changed)


def _write_github_outputs(outputs: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    path = Path(output_path)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key in OUTPUT_KEYS:
            value = outputs[key]
            if "\n" not in value and "\r" not in value:
                stream.write(f"{key}={value}\n")
                continue
            delimiter = "__BS_UPSTREAM_INTAKE_EOF__"
            while delimiter in value:
                delimiter += "_"
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--release-json",
        type=Path,
        required=True,
        help="offline GitHub release API response",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="descriptor path; must equal upstream-candidates/vX.Y.Z.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        outputs = process_release(args.root, args.release_json, args.output)
        _write_github_outputs(outputs)
        print(json.dumps(outputs, sort_keys=True))
    except (ContractError, OSError) as exc:
        print(f"upstream intake error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
