/* One kind of digits across the interface, following its language:
   Arabic interface → ٠١٢٣٤٥٦٧٨٩, English interface → 0123456789.
   Only text on screen changes: form values, codes, formulas and what the teacher is typing stay as they are.
   A piece of text that also contains Latin letters (e.g. "Unit 1") keeps its digits. */
(function () {
  "use strict";
  var lang = (document.documentElement.getAttribute("lang") || "ar").slice(0, 2);
  var arabic = lang === "ar";
  var SKIP = /^(SCRIPT|STYLE|TEXTAREA|CODE|PRE|KBD|SAMP|INPUT|NOSCRIPT)$/;
  var LATIN = /[A-Za-z]/;
  var ARABIC_LETTER = /[ء-ي]/;

  function skip(el) {
    for (var n = el; n && n.nodeType === 1; n = n.parentNode) {
      if (SKIP.test(n.tagName)) return true;
      if (n.isContentEditable || n.getAttribute("contenteditable") === "true") return true;
      if (n.hasAttribute("data-digits")) return n.getAttribute("data-digits") === "keep";
      var cls = n.className;
      if (typeof cls === "string" && (cls.indexOf("katex") !== -1 || cls.indexOf("fill-ed") !== -1)) return true;
    }
    return false;
  }

  function fix(text) {
    if (arabic) {
      if (!/[0-9]/.test(text) || LATIN.test(text.replace(/\b(UTC|GMT|AM|PM)\b/g, ""))) return text;
      /* yyyy-mm-dd → dd/mm/yyyy: the usual Arabic order, and "/" keeps the digits together right-to-left */
      var out = text.replace(/(\d{4})-(\d{1,2})-(\d{1,2})/g, "$3/$2/$1");
      out = out.replace(/(\d)\.(?=\d)/g, "$1٫").replace(/[0-9]/g, function (d) { return String.fromCharCode(0x0660 + +d); });
      return out;
    }
    if (!/[٠-٩۰-۹]/.test(text) || ARABIC_LETTER.test(text)) return text;
    return text.replace(/٫/g, ".").replace(/[٠-٩]/g, function (d) { return String(d.charCodeAt(0) - 0x0660); })
      .replace(/[۰-۹]/g, function (d) { return String(d.charCodeAt(0) - 0x06F0); });
  }

  function textNode(node) {
    var v = node.nodeValue;
    if (!v || v.length > 4000) return;
    var out = fix(v);
    if (out !== v && !skip(node.parentNode)) node.nodeValue = out;
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { textNode(root); return; }
    if (root.nodeType !== 1 || skip(root)) return;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var n, list = [];
    while ((n = walker.nextNode())) list.push(n);
    list.forEach(textNode);
  }

  window.Digits = { fix: fix, walk: walk };

  function start() {
    walk(document.body);
    if (!window.MutationObserver) return;
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        if (r.type === "characterData") textNode(r.target);
        else Array.prototype.forEach.call(r.addedNodes, walk);
      });
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
