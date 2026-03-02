Hooks.once("ready", () => {
  const babele = game.modules.get("babele")?.api;
  if (!babele) {
    console.error("Babele API not ready");
    return;
  }

  console.log("[pf2e-ja] registering with Babele (ready)");
  babele.register({
    module: "pf2e-ja",
    lang: "ja",
    dir: "babele"
  });
});