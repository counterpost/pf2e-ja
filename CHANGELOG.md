# Changelog

## 2026-07-29

`scripts/babele-register.js` へ、`babele/compendium/ja/*.json` のマッピングが
参照していた未登録コンバータ（`translateRules` / `translatePrerequisites` /
`translateSource` / `translateSpellVariants`）を実装。

**問題**: これらのコンバータが未登録のため、Babeleがコンソールへ
`missing converter 'translateXxx' for dynamic field ... field skipped` という
警告を大量に出し、対象フィールド（ルール要素のlabel/text/prompt、前提条件、
出典、呪文バリアント名/時間/対象/射程）が翻訳されず英語のまま表示されていた。
過去に修正した`translateDualLanguage`未登録問題（feat/action名が英語のまま
だった件）と同根。

**対応**:
- `translateRules`: `system.rules`配列の各要素のうち`label`/`text`/`prompt`
  キーだけを翻訳データで差し替える。要素数が食い違う場合は誤対応を避けるため
  変換自体を行わない（原文のまま）。
- `translatePrerequisites`: `system.prerequisites.value`の`[{value}]`配列の
  `value`文字列を差し替える。同様に要素数不一致時は変換しない。
- `translateSource`: `system.publication.title`（出典書名）は固有名詞として
  翻訳せず原文をそのまま返す（no-op、警告消しのみが目的）。
- `translateSpellVariants`: `system.overlays`のオーバーレイごとに、`name`は
  トップレベル、`time`/`target`/`range`は`system.time.value`等のネスト先へ
  書き込む（pf2eシステムの`SpellOverlayOverride`実構造に合わせた）。
  `overlayType`/`sort`等の非翻訳フィールドは変更しない。

全コンバータはfail-open設計: 想定外のデータ形状・要素数不一致の場合は
`undefined`を返し、Babeleが元の値（英語）へ安全にフォールバックする
（構造破壊よりも「未翻訳のまま」の方が安全なため）。

**確認**: Node.js単体テストでロジックを検証（`foundry.utils`をモック）。
実装時に`translatePrerequisites`の条件式が反転しているバグ（訳文があるのに
原文を返してしまう）をテストで検出・修正済み。`node --check`で構文確認。
Foundry実環境での動作確認（コンソールに`missing converter`警告が出ないこと、
実際に訳文が反映されること）は未実施。

**反映範囲**: `F:\github\pf2e-ja`（リポジトリ）と
`E:\pathfinder\Data\modules\pf2e-ja`（実行中のゲームが読むライブコピー）の
両方へ同一内容を反映済み。
