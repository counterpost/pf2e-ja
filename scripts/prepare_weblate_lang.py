#!/usr/bin/env python3
"""Prepare PF2e language JSON files for Weblate publication.

This tool is intentionally deterministic and local-only. It validates the
configured source and Japanese translation JSON files, reports key coverage and
protected Foundry/PF2e syntax mismatches, and writes lang/en.json and
lang/ja.json only when --write is explicitly provided.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/weblate_publish.json")
DEFAULT_COMMIT_MESSAGE = "Update Weblate source and Japanese translation"
MAX_ISSUES_STDOUT = 20


class ToolError(RuntimeError):
    """Expected fatal error with a user-facing message."""


@dataclass(frozen=True)
class Config:
    source_repository: str
    source_ref: str
    source_commit: str
    source_json_path: Path
    translated_json_path: Path
    target_repository: str
    target_branch: str
    target_source_path: Path
    target_translation_path: Path
    syntax_report_path: Path


@dataclass(frozen=True)
class JsonInput:
    label: str
    path: Path
    data: Any


@dataclass(frozen=True)
class KeyStats:
    source_keys: int
    translation_keys: int
    common_keys: int
    untranslated: int
    stale_keys: int
    completion: float


@dataclass(frozen=True)
class SyntaxIssue:
    key: str
    reason: str
    category: str
    source_tokens: list[str]
    translation_tokens: list[str]
    missing_tokens: list[str]
    added_tokens: list[str]


@dataclass(frozen=True)
class SyntaxStats:
    placeholder_missing: int = 0
    placeholder_added: int = 0
    foundry_missing: int = 0
    foundry_added: int = 0
    foundry_changed: int = 0
    html_validation: int = 0


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise ToolError(f"git {' '.join(args)} failed: {message}")
    return result


def load_config(path: Path, repo_root: Path) -> Config:
    raw = load_json_file(path, "config").data
    if not isinstance(raw, dict):
        raise ToolError(f"Config top-level must be an object: {path}")

    required = [
        "source_repository",
        "source_ref",
        "source_commit",
        "source_json_path",
        "translated_json_path",
        "target_repository",
        "target_branch",
        "target_source_path",
        "target_translation_path",
        "syntax_report_path",
    ]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ToolError(f"Config is missing required value(s): {', '.join(missing)}")

    input_root = resolve_input_root(repo_root, raw)

    return Config(
        source_repository=str(raw["source_repository"]),
        source_ref=str(raw["source_ref"]),
        source_commit=str(raw["source_commit"]),
        source_json_path=resolve_config_path(repo_root, raw["source_json_path"], input_root=input_root),
        translated_json_path=resolve_config_path(repo_root, raw["translated_json_path"], input_root=input_root),
        target_repository=str(raw["target_repository"]),
        target_branch=str(raw["target_branch"]),
        target_source_path=resolve_config_path(repo_root, raw["target_source_path"], input_root=input_root),
        target_translation_path=resolve_config_path(repo_root, raw["target_translation_path"], input_root=input_root),
        syntax_report_path=resolve_config_path(repo_root, raw["syntax_report_path"], input_root=input_root),
    )


def resolve_repo_path(repo_root: Path, value: Any) -> Path:
    return resolve_config_path(repo_root, value, input_root=None)


def resolve_input_root(repo_root: Path, raw: Mapping[str, Any]) -> Path | None:
    candidates = raw.get("input_root_candidates", [])
    if not candidates:
        return None
    if not isinstance(candidates, list):
        raise ToolError("input_root_candidates must be a list when provided.")
    checked: list[str] = []
    for candidate in candidates:
        expanded = expand_path_vars(str(candidate), repo_root=repo_root, input_root=None)
        if not expanded:
            continue
        path = Path(expanded)
        if not path.is_absolute():
            path = repo_root / path
        resolved = path.resolve()
        checked.append(str(resolved))
        if resolved.is_dir():
            return resolved
    raise ToolError("No input root candidate exists: " + ", ".join(checked))


def expand_path_vars(value: str, repo_root: Path, input_root: Path | None) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "repo_root":
            return str(repo_root)
        if name == "input_root":
            if input_root is None:
                return ""
            return str(input_root)
        return os.environ.get(name, "")

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)


def resolve_config_path(repo_root: Path, value: Any, input_root: Path | None) -> Path:
    expanded = expand_path_vars(str(value), repo_root=repo_root, input_root=input_root)
    if not expanded:
        raise ToolError(f"Path value resolved to empty string: {value}")
    path = Path(expanded)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def load_json_file(path: Path, label: str) -> JsonInput:
    if not path.exists():
        raise ToolError(f"{label} JSON does not exist: {path}")
    if not path.is_file():
        raise ToolError(f"{label} JSON is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"{label} JSON is not valid UTF-8: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{label} JSON is malformed: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"{label} JSON top-level must be an object: {path}")
    return JsonInput(label=label, path=path, data=data)


def get_repo_root(cwd: Path) -> Path:
    result = run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(result.stdout.strip()).resolve()


def normalize_remote(value: str) -> str:
    value = value.strip()
    if value.endswith(".git"):
        value = value[:-4]
    value = value.replace("\\", "/")
    match = re.match(r"git@github\.com:(?P<repo>[^/]+/[^/]+)$", value)
    if match:
        return match.group("repo").lower()
    match = re.match(r"https?://github\.com/(?P<repo>[^/]+/[^/]+)$", value)
    if match:
        return match.group("repo").lower()
    return value.lower()


def check_git_state(repo_root: Path, config: Config, allow_dirty: bool) -> None:
    branch = run_git(["branch", "--show-current"], repo_root).stdout.strip()
    if not branch:
        raise ToolError("Detached HEAD is not allowed.")
    if branch == "crowdin-legacy":
        raise ToolError("Refusing to run on crowdin-legacy.")
    if branch != config.target_branch:
        raise ToolError(f"Current branch must be {config.target_branch}, got {branch}.")

    remotes = run_git(["remote", "get-url", "origin"], repo_root).stdout.strip()
    if normalize_remote(remotes) != config.target_repository.lower():
        raise ToolError(
            f"origin remote must be {config.target_repository}, got {remotes}."
        )

    branches = run_git(["branch", "--all"], repo_root).stdout
    if "main" not in branches:
        raise ToolError("main branch was not found.")
    if "crowdin-legacy" not in branches:
        raise ToolError("crowdin-legacy branch was not found.")

    git_dir = Path(run_git(["rev-parse", "--git-dir"], repo_root).stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    for state_name in ["MERGE_HEAD", "REBASE_HEAD"]:
        if (git_dir / state_name).exists():
            raise ToolError(f"Git operation in progress: {state_name}")
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        raise ToolError("Git rebase is in progress.")

    conflicts = run_git(["diff", "--name-only", "--diff-filter=U"], repo_root).stdout.strip()
    if conflicts:
        raise ToolError(f"Unresolved conflict(s): {conflicts}")

    status = run_git(["status", "--porcelain"], repo_root).stdout.strip()
    if status and not allow_dirty:
        raise ToolError("Working tree has uncommitted changes. Re-run with --allow-dirty to inspect anyway.")


def flatten_leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        leaves: dict[str, Any] = {}
        for key, child in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(flatten_leaves(child, child_key))
        return leaves
    return {prefix: value}


def is_translated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def compute_key_stats(source: Mapping[str, Any], translation: Mapping[str, Any]) -> tuple[KeyStats, set[str]]:
    source_flat = flatten_leaves(source)
    translation_flat = flatten_leaves(translation)
    source_keys = set(source_flat)
    translation_keys = set(translation_flat)
    common = source_keys & translation_keys
    stale = translation_keys - source_keys
    untranslated = len(source_keys - translation_keys) + sum(
        1 for key in common if not is_translated(translation_flat[key])
    )
    translated = len(source_keys) - untranslated
    completion = (translated / len(source_keys) * 100) if source_keys else 100.0
    return (
        KeyStats(
            source_keys=len(source_keys),
            translation_keys=len(translation_keys),
            common_keys=len(common),
            untranslated=untranslated,
            stale_keys=len(stale),
            completion=completion,
        ),
        stale,
    )


PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.-]*\}")
FOUNDRY_TOKEN_RE = re.compile(
    r"@(?:UUID|Check|Damage|Localize)\[(?>(?:[^\[\]]+|\[[^\[\]]*\])*)\]"
)
FOUNDRY_WITH_LABEL_RE = re.compile(
    r"(@(?:UUID|Check|Damage|Localize)\[(?>(?:[^\[\]]+|\[[^\[\]]*\])*)\])"
    r"(\{[^{}]*\})?"
)
HTML_TAG_RE = re.compile(r"<[^>]*>")
HTML_TAG_NAME_RE = re.compile(r"^</?\s*([A-Za-z][A-Za-z0-9:-]*)\b")
VOID_HTML_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


def placeholder_tokens(value: str) -> list[str]:
    occupied = foundry_spans(value)
    return [
        match.group(0)
        for match in PLACEHOLDER_RE.finditer(value or "")
        if not any(overlaps(match.span(), span) for span in occupied)
    ]


def foundry_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for match in FOUNDRY_WITH_LABEL_RE.finditer(value or ""):
        token = match.group(1)
        if match.group(2) is not None:
            token += "{}"
        tokens.append(token)
    return tokens


def foundry_spans(value: str) -> list[tuple[int, int]]:
    return [match.span() for match in FOUNDRY_WITH_LABEL_RE.finditer(value or "")]


def overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def counter_missing_added(source_tokens: list[str], translation_tokens: list[str]) -> tuple[list[str], list[str]]:
    source_counter = Counter(source_tokens)
    translation_counter = Counter(translation_tokens)
    return (
        sorted((source_counter - translation_counter).elements()),
        sorted((translation_counter - source_counter).elements()),
    )


def foundry_kind(token: str) -> str:
    match = re.match(r"@([A-Za-z]+)", token)
    return match.group(1) if match else token.split("[", 1)[0]


def classify_foundry_difference(missing: list[str], added: list[str]) -> tuple[str, list[str], list[str]]:
    if not missing:
        return "foundry_added", missing, added
    if not added:
        return "foundry_missing", missing, added
    missing_kinds = Counter(foundry_kind(token) for token in missing)
    added_kinds = Counter(foundry_kind(token) for token in added)
    if missing_kinds == added_kinds:
        return "foundry_changed", missing, added
    return "foundry_mismatch", missing, added


def validate_html(value: str) -> list[str]:
    stack: list[str] = []
    issues: list[str] = []
    for match in HTML_TAG_RE.finditer(value or ""):
        tag = match.group(0)
        name_match = HTML_TAG_NAME_RE.match(tag)
        if not name_match:
            issues.append(f"malformed tag {tag}")
            continue
        name = name_match.group(1).lower()
        is_close = tag.startswith("</")
        is_self_closing = tag.endswith("/>") or name in VOID_HTML_TAGS
        if is_self_closing and not is_close:
            continue
        if is_close:
            if not stack:
                issues.append(f"unexpected closing tag </{name}>")
                continue
            if stack[-1] != name:
                issues.append(f"expected </{stack[-1]}>, got </{name}>")
                stack.pop()
                continue
            stack.pop()
        else:
            stack.append(name)
    for name in reversed(stack):
        issues.append(f"unclosed tag <{name}>")
    return issues


def compare_syntax(source_flat: Mapping[str, Any], translation_flat: Mapping[str, Any]) -> list[SyntaxIssue]:
    issues: list[SyntaxIssue] = []
    for key in sorted(set(source_flat) & set(translation_flat)):
        source_value = source_flat[key]
        translation_value = translation_flat[key]
        if not isinstance(source_value, str) or not isinstance(translation_value, str):
            continue
        if not translation_value.strip():
            continue
        source_placeholders = placeholder_tokens(source_value)
        translation_placeholders = placeholder_tokens(translation_value)
        missing_placeholders, added_placeholders = counter_missing_added(source_placeholders, translation_placeholders)
        if missing_placeholders:
            issues.append(
                SyntaxIssue(
                    key=key,
                    reason="placeholder missing",
                    category="placeholder_missing",
                    source_tokens=source_placeholders,
                    translation_tokens=translation_placeholders,
                    missing_tokens=missing_placeholders,
                    added_tokens=[],
                )
            )
        if added_placeholders:
            issues.append(
                SyntaxIssue(
                    key=key,
                    reason="placeholder added",
                    category="placeholder_added",
                    source_tokens=source_placeholders,
                    translation_tokens=translation_placeholders,
                    missing_tokens=[],
                    added_tokens=added_placeholders,
                )
            )

        source_foundry = foundry_tokens(source_value)
        translation_foundry = foundry_tokens(translation_value)
        missing_foundry, added_foundry = counter_missing_added(source_foundry, translation_foundry)
        if missing_foundry or added_foundry:
            category, missing_tokens, added_tokens = classify_foundry_difference(missing_foundry, added_foundry)
            issues.append(
                SyntaxIssue(
                    key=key,
                    reason=category.replace("_", " "),
                    category=category,
                    source_tokens=source_foundry,
                    translation_tokens=translation_foundry,
                    missing_tokens=missing_tokens,
                    added_tokens=added_tokens,
                )
            )

        source_html_issues = validate_html(source_value)
        html_issues = [] if source_html_issues else validate_html(translation_value)
        if html_issues:
            issues.append(
                SyntaxIssue(
                    key=key,
                    reason="html validation issue",
                    category="html_validation",
                    source_tokens=[],
                    translation_tokens=html_issues,
                    missing_tokens=[],
                    added_tokens=html_issues,
                )
            )
    return issues


def syntax_stats(issues: list[SyntaxIssue]) -> SyntaxStats:
    return SyntaxStats(
        placeholder_missing=sum(len(issue.missing_tokens) for issue in issues if issue.category == "placeholder_missing"),
        placeholder_added=sum(len(issue.added_tokens) for issue in issues if issue.category == "placeholder_added"),
        foundry_missing=sum(len(issue.missing_tokens) for issue in issues if issue.category in {"foundry_missing", "foundry_mismatch"}),
        foundry_added=sum(len(issue.added_tokens) for issue in issues if issue.category in {"foundry_added", "foundry_mismatch"}),
        foundry_changed=sum(1 for issue in issues if issue.category == "foundry_changed"),
        html_validation=sum(1 for issue in issues if issue.category == "html_validation"),
    )


def ordered_translation(source: Any, translation: Any, include_stale: bool = False) -> Any:
    if isinstance(source, dict):
        result: dict[str, Any] = {}
        translation_map = translation if isinstance(translation, dict) else {}
        for key, source_child in source.items():
            if key not in translation_map:
                continue
            child = ordered_translation(source_child, translation_map[key], include_stale=False)
            if child is _MISSING:
                continue
            result[key] = child
        if include_stale and isinstance(translation, dict):
            for key, value in translation.items():
                if key not in result:
                    result[key] = value
        return result
    if translation is None:
        return None
    return translation


class _Missing:
    pass


_MISSING = _Missing()


def ordered_source(source: Any) -> Any:
    return source


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=4) + "\n"


def write_if_changed(path: Path, content: str, dry_run: bool) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    changed = existing != content
    if changed and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return changed


def report_syntax_issues(path: Path, issues: list[SyntaxIssue], dry_run: bool) -> None:
    if not issues:
        return
    lines = [
        json.dumps(
            {
                "key": issue.key,
                "reason": issue.reason,
                "category": issue.category,
                "source_tokens": issue.source_tokens,
                "translation_tokens": issue.translation_tokens,
                "missing_tokens": issue.missing_tokens,
                "added_tokens": issue.added_tokens,
            },
            ensure_ascii=False,
        )
        for issue in issues
    ]
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def diff_summary(repo_root: Path, paths: list[Path]) -> str:
    rel_paths = [os.path.relpath(path, repo_root).replace("\\", "/") for path in paths]
    result = run_git(["diff", "--stat", "--", *rel_paths], repo_root, check=False)
    return result.stdout.strip() or "(no git diff)"


def planned_diff_summary(repo_root: Path, planned: Mapping[Path, str]) -> str:
    lines: list[str] = []
    total_added = 0
    total_removed = 0
    for path, content in planned.items():
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        added = 0
        removed = 0
        for line in difflib.ndiff(existing.splitlines(), content.splitlines()):
            if line.startswith("+ "):
                added += 1
            elif line.startswith("- "):
                removed += 1
        total_added += added
        total_removed += removed
        rel = os.path.relpath(path, repo_root).replace("\\", "/")
        if existing == content:
            lines.append(f"{rel} | unchanged")
        else:
            lines.append(f"{rel} | planned change (+{added} -{removed})")
    if not lines:
        return "(no planned paths)"
    lines.append(f"2 files | planned +{total_added} -{total_removed}")
    return "\n".join(lines)


def print_syntax_stats(stats: SyntaxStats) -> None:
    print(f"Placeholder missing : {stats.placeholder_missing:,}")
    print(f"Placeholder added   : {stats.placeholder_added:,}")
    print(f"Foundry missing     : {stats.foundry_missing:,}")
    print(f"Foundry added       : {stats.foundry_added:,}")
    print(f"Foundry changed     : {stats.foundry_changed:,}")
    print(f"HTML validation     : {stats.html_validation:,}")


def commit_changes(repo_root: Path, paths: list[Path], message: str) -> bool:
    rel_paths = [os.path.relpath(path, repo_root).replace("\\", "/") for path in paths]
    run_git(["add", "--", *rel_paths], repo_root)
    staged = run_git(["diff", "--cached", "--name-only", "--", *rel_paths], repo_root).stdout.strip()
    if not staged:
        return False
    run_git(["commit", "-m", message, "--", *rel_paths], repo_root)
    return True


def push_changes(repo_root: Path, branch: str) -> None:
    if branch == "crowdin-legacy":
        raise ToolError("Refusing to push crowdin-legacy.")
    run_git(["push", "origin", branch], repo_root)


def print_stats(stats: KeyStats) -> None:
    print(f"Source keys      : {stats.source_keys:,}")
    print(f"Translation keys : {stats.translation_keys:,}")
    print(f"Common keys      : {stats.common_keys:,}")
    print(f"Untranslated     : {stats.untranslated:,}")
    print(f"Stale keys       : {stats.stale_keys:,}")
    print(f"Completion       : {stats.completion:.2f}%")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-json", type=Path, help="Override configured source JSON path.")
    parser.add_argument("--translated-json", type=Path, help="Override configured Japanese JSON path.")
    parser.add_argument("--write", action="store_true", help="Write lang/en.json and lang/ja.json.")
    parser.add_argument("--commit", action="store_true", help="Commit lang/en.json and lang/ja.json after writing.")
    parser.add_argument("--push", action="store_true", help="Push the commit to origin/main after committing.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes.")
    parser.add_argument("--allow-stale", action="store_true", help="Allow translation-only stale keys.")
    parser.add_argument("--allow-syntax-issues", action="store_true", help="Allow protected syntax mismatches.")
    parser.add_argument("--skip-git-checks", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path.cwd()
    repo_root = get_repo_root(cwd)
    config = load_config((repo_root / args.config).resolve() if not args.config.is_absolute() else args.config, repo_root)

    if args.source_json:
        config = Config(**{**config.__dict__, "source_json_path": resolve_repo_path(repo_root, args.source_json)})
    if args.translated_json:
        config = Config(**{**config.__dict__, "translated_json_path": resolve_repo_path(repo_root, args.translated_json)})

    if args.push and not args.commit:
        raise ToolError("--push requires --commit.")
    if args.commit and not args.write:
        raise ToolError("--commit requires --write.")

    if not args.skip_git_checks:
        check_git_state(repo_root, config, allow_dirty=args.allow_dirty or args.write)

    source_input = load_json_file(config.source_json_path, "source")
    translation_input = load_json_file(config.translated_json_path, "translation")
    print(f"Git root         : {repo_root}")
    print(f"Source JSON      : {source_input.path}")
    print(f"Translation JSON : {translation_input.path}")
    print(f"Source repo/ref  : {config.source_repository} @ {config.source_ref}")
    print(f"Source commit    : {config.source_commit}")
    print("Validator reuse  : local Weblate protected-token validator")

    stats, stale_keys = compute_key_stats(source_input.data, translation_input.data)
    print_stats(stats)
    if stale_keys and not args.allow_stale:
        sample = ", ".join(sorted(stale_keys)[:MAX_ISSUES_STDOUT])
        raise ToolError(f"Translation has {len(stale_keys)} stale key(s): {sample}")

    syntax_issues = compare_syntax(flatten_leaves(source_input.data), flatten_leaves(translation_input.data))
    syntax_summary = syntax_stats(syntax_issues)
    print(f"Protected syntax : {len(syntax_issues):,} issue(s)")
    print_syntax_stats(syntax_summary)
    if syntax_issues:
        report_syntax_issues(config.syntax_report_path, syntax_issues, dry_run=not args.write)
        for issue in syntax_issues[:MAX_ISSUES_STDOUT]:
            print(
                f"  - {issue.key}: {issue.reason}; "
                f"missing={issue.missing_tokens[:5]} added={issue.added_tokens[:5]}"
            )
        suffix = " (not written in dry-run)" if not args.write else ""
        print(f"Syntax report    : {config.syntax_report_path}{suffix}")
        if not args.allow_syntax_issues:
            raise ToolError("Protected syntax validation failed.")

    en_content = dump_json(ordered_source(source_input.data))
    ja_ordered = ordered_translation(source_input.data, translation_input.data)
    ja_content = dump_json(ja_ordered)

    dry_run = not args.write
    en_changed = write_if_changed(config.target_source_path, en_content, dry_run=dry_run)
    ja_changed = write_if_changed(config.target_translation_path, ja_content, dry_run=dry_run)
    print(f"Mode             : {'write' if args.write else 'dry-run'}")
    print(f"Target source    : {config.target_source_path} ({'changed' if en_changed else 'unchanged'})")
    print(f"Target ja        : {config.target_translation_path} ({'changed' if ja_changed else 'unchanged'})")
    print("Planned diff     :")
    print(planned_diff_summary(repo_root, {
        config.target_source_path: en_content,
        config.target_translation_path: ja_content,
    }))
    print("Git diff summary :")
    print(diff_summary(repo_root, [config.target_source_path, config.target_translation_path]))

    committed = False
    if args.commit:
        check_git_state(repo_root, config, allow_dirty=True)
        committed = commit_changes(
            repo_root,
            [config.target_source_path, config.target_translation_path],
            args.commit_message,
        )
        print(f"Commit           : {'created' if committed else 'skipped (no diff)'}")

    if args.push:
        if not committed:
            print("Push             : skipped (no commit)")
        else:
            check_git_state(repo_root, config, allow_dirty=True)
            push_changes(repo_root, config.target_branch)
            print(f"Push             : origin {config.target_branch}")
    else:
        print("Push             : skipped")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
