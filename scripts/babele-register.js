Hooks.once("babele.init", (babele) => {
  console.log("[pf2e-ja] babele.init hook fired");
  babele.register({
    module: "pf2e-ja",
    lang: "ja",
    dir: "babele/ja"
  });
  console.log("[pf2e-ja] babele.register called");
});