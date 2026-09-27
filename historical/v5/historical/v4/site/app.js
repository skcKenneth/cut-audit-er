"use strict";
const languageButton = document.getElementById("language");
languageButton.addEventListener("click", () => {
  const chinese = document.documentElement.lang !== "zh-Hant";
  document.documentElement.lang = chinese ? "zh-Hant" : "en";
  languageButton.textContent = chinese ? "English" : "繁體中文";
  languageButton.setAttribute("aria-label", chinese ? "Switch to English" : "切換至繁體中文");
  document.title = chinese ? "CUT-AUDIT-ER V4 · 研究證據與限制" : "CUT-AUDIT-ER V4 · Evidence and limits";
});
