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
});