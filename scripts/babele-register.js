Hooks.once("babele.init", () => {
  if (!game.babele) {
    console.error("[pf2e-ja] game.babele not found");
    return;
  }

  console.log("[pf2e-ja] registering with Babele (babele.init)");
  game.babele.register({
    module: "pf2e-ja",
    lang: "ja",
    dir: "babele/compendium/ja"
  });

  // pf2e.system.jsonのマッピングが参照する動的コンバータ。
  // 未登録のままだと Babele が "missing converter" 警告を出し、
  // 対象フィールドを英語のまま出力してスキップする（rules/prerequisites/
  // source/spellVariants）。ここで実装して翻訳が反映されるようにする。
  //
  // 各コンバータは Babele のレガシー関数シグネチャ
  // (value, translation, source, contextCompendium, allTranslations, runtime, params)
  // で呼ばれる。translation は babele/compendium/ja/*.json の該当フィールドの値。
  // 想定外の形が来た場合は必ず undefined を返し、Babele に元の値のまま
  // フォールバックさせる（構造破壊よりも「訳が反映されない」方が安全なため）。
  game.babele.registerConverters({
    // system.rules: label/text/prompt の3キーのみが翻訳対象（choices等の
    // 配列や条件式は translation 側に存在しないため、原文の該当キーだけを
    // 差し替え、それ以外の構造は一切変更しない）。
    translateRules: (value, translation) => {
      if (!Array.isArray(value) || !Array.isArray(translation)) return undefined;
      // 要素数が食い違う場合、そのまま添字で対応付けると別のルール要素へ
      // 誤って訳文を適用しかねない（ゲーム側のデータ更新でルール要素が
      // 増減した場合等）。安全側でこの回は変換自体を諦める。
      if (value.length !== translation.length) return undefined;
      return value.map((rule, i) => {
        const t = translation[i];
        if (!rule || typeof rule !== "object" || !t || typeof t !== "object") {
          return rule;
        }
        const merged = { ...rule };
        for (const key of ["label", "text", "prompt"]) {
          if (typeof t[key] === "string" && t[key]) {
            merged[key] = t[key];
          }
        }
        return merged;
      });
    },

    // system.prerequisites.value: [{value: "..."}] 形式。value文字列だけを
    // 差し替える。要素数が食い違う場合は安全側で undefined を返す。
    translatePrerequisites: (value, translation) => {
      if (!Array.isArray(value) || !Array.isArray(translation)) return undefined;
      if (value.length !== translation.length) return undefined;
      return value.map((entry, i) => {
        const t = translation[i];
        if (!entry || typeof entry !== "object" || !t || typeof t?.value !== "string") {
          return entry;
        }
        return { ...entry, value: t.value };
      });
    },

    // system.publication.title: 出典書名。書名は固有名詞として原文のまま
    // 保持する方針（force_dict/translator側の出典行と同じ扱い）のため、
    // このコンバータは変換を行わず原文を素通しする（no-op、警告消し用）。
    translateSource: (value) => value,

    // system.overlays: Record<overlayId, SpellOverlayOverride>。
    // pf2eシステムの実データでは overlay.name がトップレベル、time/target/range は
    // overlay.system.{time,target,range}.value に入る（overlay.overlayType/sortは
    // 翻訳対象外なのでそのまま維持）。訳データ側は {name, time, target, range} という
    // 平坦なキーで保持しているため、書き込み先だけシステム側の実構造に合わせる。
    // nameは既存の「訳語/英語原文」二言語表記(translator_memory.strip_dual_language
    // と同じ形式)をそのまま使う。
    translateSpellVariants: (value, translation) => {
      if (!value || typeof value !== "object" || !translation || typeof translation !== "object") {
        return undefined;
      }
      const merged = {};
      for (const [overlayId, overlay] of Object.entries(value)) {
        const t = translation[overlayId];
        if (!overlay || typeof overlay !== "object" || !t || typeof t !== "object") {
          merged[overlayId] = overlay;
          continue;
        }
        const next = foundry.utils.deepClone(overlay);
        if (typeof t.name === "string" && t.name) {
          next.name = t.name;
        }
        for (const [field, path] of [
          ["time", "system.time.value"],
          ["target", "system.target.value"],
          ["range", "system.range.value"],
        ]) {
          if (typeof t[field] === "string" && t[field]) {
            foundry.utils.setProperty(next, path, t[field]);
          }
        }
        merged[overlayId] = next;
      }
      return merged;
    },
  });
});
