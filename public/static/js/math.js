/* Math (LaTeX) rendering. Teachers write formulas as \( ... \) (inline) or \[ ... \] (own line).
   KaTeX is loaded from /static/vendor only on pages that contain a formula. */
(function () {
  "use strict";
  var base = (document.currentScript && document.currentScript.src || "").replace(/js\/math\.js.*$/, "vendor/katex/");
  var loading = null;

  function load() {
    if (window.renderMathInElement) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise(function (resolve) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = base + "katex.min.css";
      document.head.appendChild(css);
      var core = document.createElement("script");
      core.src = base + "katex.min.js";
      core.onload = function () {
        var auto = document.createElement("script");
        auto.src = base + "contrib/auto-render.min.js";
        auto.onload = function () { resolve(); };
        auto.onerror = function () { resolve(); };
        document.head.appendChild(auto);
      };
      core.onerror = function () { resolve(); };
      document.head.appendChild(core);
    });
    return loading;
  }

  function hasMath(el) {
    var text = el && (el.textContent || "");
    return text.indexOf("\\(") !== -1 || text.indexOf("\\[") !== -1;
  }

  function render(el) {
    el = el || document.body;
    if (!hasMath(el)) return Promise.resolve();
    return load().then(function () {
      if (!window.renderMathInElement) return;
      window.renderMathInElement(el, {
        delimiters: [{ left: "\\[", right: "\\]", display: true }, { left: "\\(", right: "\\)", display: false }],
        throwOnError: false,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "input", "select", "option"]
      });
    });
  }

  /* KaTeX string for the builder's formula box */
  function toString(latex, display) {
    return load().then(function () {
      if (!window.katex) return null;
      try { return window.katex.renderToString(latex, { throwOnError: false, displayMode: !!display }); } catch (e) { return null; }
    });
  }

  window.MathView = { render: render, toString: toString, load: load };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { render(); });
  else render();
})();
