# Changelog

## 2026-10-09

`babele/compendium/ja/pf2e.actionspf2e.json` の行動名47個の音写を、決定済みの語と、辞書での同じ語の訳し方にそろえた
（例: デセプティブ→ディセプティブ、チャンネル→チャネル、ヴィジョン等のヴ／ブ、ロア→ロアー）。
名前（name）だけを変更し、説明文は変えていない。
さらに、ディレクターが決めた音写に統一した（フィア→フィアー、フール→フールー、ヴィザージュ→ヴィサージ、クレッセント→クレセント、アボイド→アヴォイド、
エグゼキューショナー→エクセキューショナー、グランデュール→グランジャー、リバレート→リバレイト）。装備・特技・怪物・呪文の名前78行と、行動名6個。
行動名の音写7個も、アメリカ式の発音記号と既存の決定で修正（ブレザー→ブリーザー、ラコンチュアー→ラコンター、クレネレーション→クレネレイション、プルーヴ→プルーブ、サヴァイヴ→サバイブ等）。
本文・リンクの表示名に残っていた旧い音写17か所も統一（フィア→フィアー、フール・ファミリア→フールー・ファミリア、ヴィザージュ→ヴィサージ、クレッセント→クレセント等）。
英語のfool（「ザ・フール」「ハード・トゥ・フール」）は別の語なので変更していない。

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
