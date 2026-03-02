Hooks.once("babele.init", (babele) => {
  console.log("[pf2e-ja] registering with Babele");
  babele.register({
    module: "pf2e-ja",
    lang: "ja",
    dir: "babele/ja/compendium"
  });
});