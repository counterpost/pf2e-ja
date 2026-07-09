import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_weblate_lang.py"
SPEC = importlib.util.spec_from_file_location("prepare_weblate_lang", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


class JsonAndSyntaxTests(unittest.TestCase):
    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "valid.json"
            path.write_text('{"PF2E": {"A": "B"}}\n', encoding="utf-8")
            loaded = prepare.load_json_file(path, "source")
            self.assertEqual(loaded.data["PF2E"]["A"], "B")

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "broken.json"
            path.write_text('{"PF2E": ', encoding="utf-8")
            with self.assertRaises(prepare.ToolError):
                prepare.load_json_file(path, "source")

    def test_source_only_key_is_untranslated(self):
        stats, stale = prepare.compute_key_stats({"a": "A", "b": "B"}, {"a": "訳"})
        self.assertEqual(stats.untranslated, 1)
        self.assertEqual(stats.stale_keys, 0)
        self.assertEqual(stale, set())

    def test_translation_only_key_is_stale(self):
        stats, stale = prepare.compute_key_stats({"a": "A"}, {"a": "訳", "b": "古い"})
        self.assertEqual(stats.stale_keys, 1)
        self.assertEqual(stale, {"b"})

    def test_empty_and_null_translation_are_untranslated(self):
        stats, _ = prepare.compute_key_stats({"a": "A", "b": "B"}, {"a": " ", "b": None})
        self.assertEqual(stats.untranslated, 2)
        self.assertEqual(stats.completion, 0.0)

    def test_foundry_syntax_ok_when_label_is_translated(self):
        source = {
            "a": "@UUID[Compendium.pf2e.foo.Item.abc]{English}",
            "b": "@Check[flat|dc:10]{Flat Check}",
            "c": "Hello {name}",
        }
        translation = {
            "a": "@UUID[Compendium.pf2e.foo.Item.abc]{日本語}",
            "b": "@Check[flat|dc:10]{平目判定}",
            "c": "こんにちは {name}",
        }
        issues = prepare.compare_syntax(source, translation)
        self.assertEqual(issues, [])

    def test_foundry_syntax_missing(self):
        issues = prepare.compare_syntax({"a": "@Damage[2d6[fire]]"}, {"a": "2d6 fire"})
        self.assertEqual(len(issues), 1)

    def test_foundry_syntax_added(self):
        issues = prepare.compare_syntax({"a": "plain"}, {"a": "@Localize[PF2E.Foo]"})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].category, "foundry_added")

    def test_named_placeholders_ignore_order(self):
        issues = prepare.compare_syntax(
            {"a": "{item} was added to {character}."},
            {"a": "{character}に{item}を追加した。"},
        )
        self.assertEqual(issues, [])

    def test_named_placeholder_missing_and_added(self):
        issues = prepare.compare_syntax(
            {"a": "{item} was added to {character}."},
            {"a": "{character}に{count}個追加した。"},
        )
        categories = {issue.category for issue in issues}
        self.assertEqual(categories, {"placeholder_missing", "placeholder_added"})

    def test_foundry_syntax_ignores_order(self):
        issues = prepare.compare_syntax(
            {"a": "@UUID[Compendium.pf2e.conditionitems.Item.abc] then @Check[flat|dc:10]"},
            {"a": "@Check[flat|dc:10]してから@UUID[Compendium.pf2e.conditionitems.Item.abc]"},
        )
        self.assertEqual(issues, [])

    def test_foundry_syntax_changed(self):
        issues = prepare.compare_syntax(
            {"a": "@Check[flat|dc:10]"},
            {"a": "@Check[flat|dc:15]"},
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].category, "foundry_changed")

    def test_html_addition_is_allowed_when_balanced(self):
        issues = prepare.compare_syntax({"a": "plain"}, {"a": "<p>plain</p><font>追加</font>"})
        self.assertEqual(issues, [])

    def test_html_unbalanced_is_reported(self):
        issues = prepare.compare_syntax({"a": "plain"}, {"a": "<p><strong>plain</p>"})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].category, "html_validation")

    def test_html_invalid_source_fragment_does_not_fail_translation(self):
        issues = prepare.compare_syntax(
            {"a": "Title</p><p>Body"},
            {"a": "題名</p><p>本文"},
        )
        self.assertEqual(issues, [])

    def test_ordered_translation_omits_missing_keys(self):
        source = {"b": "B", "a": {"x": "X", "y": "Y"}}
        translation = {"a": {"y": "訳Y", "x": "訳X"}}
        self.assertEqual(
            prepare.ordered_translation(source, translation),
            {"a": {"x": "訳X", "y": "訳Y"}},
        )

    def test_config_input_root_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_root = root / "translator"
            input_root.mkdir()
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "source_repository": "https://github.com/counterpost/pf2e-ja.git",
                "source_ref": "translator-current-job",
                "source_commit": "dummy",
                "input_root_candidates": [str(input_root)],
                "source_json_path": "${input_root}/lang/en.json",
                "translated_json_path": "${input_root}/localized/en-ja.json",
                "target_repository": "counterpost/pf2e-ja",
                "target_branch": "main",
                "target_source_path": "lang/en.json",
                "target_translation_path": "lang/ja.json",
                "syntax_report_path": "reports/issues.jsonl",
            }), encoding="utf-8")
            config = prepare.load_config(config_path, root)
            self.assertEqual(config.source_json_path, input_root / "lang" / "en.json")
            self.assertEqual(config.translated_json_path, input_root / "localized" / "en-ja.json")
            self.assertEqual(config.target_source_path, root / "lang" / "en.json")


class GitSafetyTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path, prepare.Config]:
        temp = tempfile.TemporaryDirectory()
        repo = Path(temp.name)
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.email", "test@example.invalid")
        git(repo, "config", "user.name", "Test User")
        (repo / "lang").mkdir()
        (repo / "lang" / "en.json").write_text('{"a":"A"}\n', encoding="utf-8")
        (repo / "lang" / "ja.json").write_text('{"a":"訳"}\n', encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "init")
        git(repo, "remote", "add", "origin", "https://github.com/counterpost/pf2e-ja.git")
        git(repo, "branch", "crowdin-legacy")
        config = prepare.Config(
            source_repository="https://github.com/counterpost/pf2e-ja.git",
            source_ref="main",
            source_commit="HEAD",
            source_json_path=repo / "lang" / "en.json",
            translated_json_path=repo / "lang" / "ja.json",
            target_repository="counterpost/pf2e-ja",
            target_branch="main",
            target_source_path=repo / "lang" / "en.json",
            target_translation_path=repo / "lang" / "ja.json",
            syntax_report_path=repo / "reports" / "issues.jsonl",
        )
        return temp, repo, config

    def test_clean_main_repo_passes(self):
        temp, repo, config = self.make_repo()
        with temp:
            prepare.check_git_state(repo, config, allow_dirty=False)

    def test_dirty_worktree_fails(self):
        temp, repo, config = self.make_repo()
        with temp:
            (repo / "lang" / "ja.json").write_text('{"a":"変更"}\n', encoding="utf-8")
            with self.assertRaises(prepare.ToolError):
                prepare.check_git_state(repo, config, allow_dirty=False)

    def test_crowdin_legacy_fails(self):
        temp, repo, config = self.make_repo()
        with temp:
            git(repo, "checkout", "crowdin-legacy")
            with self.assertRaises(prepare.ToolError):
                prepare.check_git_state(repo, config, allow_dirty=True)

    def test_remote_mismatch_fails(self):
        temp, repo, config = self.make_repo()
        with temp:
            git(repo, "remote", "set-url", "origin", "https://github.com/example/wrong.git")
            with self.assertRaises(prepare.ToolError):
                prepare.check_git_state(repo, config, allow_dirty=True)

    def test_diff_none_when_content_same(self):
        temp, repo, config = self.make_repo()
        with temp:
            self.assertFalse(prepare.write_if_changed(config.target_source_path, '{"a":"A"}\n', dry_run=True))


if __name__ == "__main__":
    unittest.main()
