(function () {
  "use strict";

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";

  var toastEl = null;
  var toastTimer = null;
  function toast(message) {
    toastEl = toastEl || document.getElementById("toast");
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("show");
    }, 2600);
  }

  function api(url, options) {
    options = options || {};
    var headers = Object.assign({ "X-CSRF-Token": csrf }, options.headers || {});
    var init = { method: options.method || "POST", headers: headers, credentials: "same-origin", keepalive: !!options.keepalive };
    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    } else if (options.body) {
      init.body = options.body;
    }
    return fetch(url, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        data.status = response.status;
        if (!response.ok && data.ok === undefined) data.ok = false;
        return data;
      });
    });
  }

  window.App = { toast: toast, api: api, csrf: csrf };

  // ---- Arabic copied from PDF files -------------------------------------------------------
  // Many PDFs keep Arabic as presentation-form glyphs in visual (reversed) order; when pasted the
  // letters appear disconnected and backwards. Convert such text to normal Arabic on paste.
  // (Same logic as server/arabicfix.py.)
  var PRES = /[ﭐ-﷿ﹰ-﻾]/;
  var PRES_G = /[ﭐ-ﷹ﷼-﷿ﹰ-﻾]/g;
  var LTR_RUN = /[0-9A-Za-z٠-٩۰-۹]+(?:[.,:\/\-][0-9A-Za-z٠-٩۰-۹]+)*/g;
  var MIRROR = { "(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<", "«": "»", "»": "«" };

  function normalizeForms(text) {
    return text.replace(PRES_G, function (c) { return c.normalize ? c.normalize("NFKC") : c; });
  }
  function looksReversed(text) {
    var words = text.match(/[ء-ي]{3,}/g) || [];
    var starts = 0, ends = 0;
    words.forEach(function (w) {
      if (/^[وفبك]?ال/.test(w)) starts++;
      if (/لا[وفبك]?$/.test(w)) ends++;
    });
    return ends > starts;
  }
  function reverseLine(line) {
    var out = Array.from(line).reverse().join("");
    out = out.replace(LTR_RUN, function (run) { return Array.from(run).reverse().join(""); });
    return out.replace(/[()\[\]{}<>«»]/g, function (c) { return MIRROR[c]; });
  }
  function fixPdfArabic(text) {
    if (!text || !PRES.test(text)) return text;
    text = text.replace(/﻿/g, "");
    if (looksReversed(normalizeForms(text))) {
      text = text.split("\n").map(reverseLine).join("\n");
    }
    return normalizeForms(text);
  }
  window.App.fixPdfArabic = fixPdfArabic;

  document.addEventListener("paste", function (event) {
    var el = event.target;
    if (!el || !(el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && /^(text|search|)$/.test(el.type || "")))) return;
    var data = event.clipboardData || window.clipboardData;
    if (!data) return;
    var text = data.getData("text/plain") || data.getData("text");
    var fixed = fixPdfArabic(text);
    if (fixed === text) return;
    event.preventDefault();
    var done = false;
    try { done = document.execCommand("insertText", false, fixed); } catch (e) { done = false; }
    if (!done) {
      var start = el.selectionStart || 0, end = el.selectionEnd || 0;
      el.setRangeText(fixed, start, end, "end");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
    var ar = (document.documentElement.lang || "ar").indexOf("ar") === 0;
    toast(ar ? "تم إصلاح النص العربي المنسوخ من ملف PDF" : "Arabic text copied from a PDF was repaired");
  }, true);

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    var area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    return Promise.resolve();
  }
  window.App.copy = copyText;

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("nav-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var open = document.body.classList.toggle("nav-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
    /* close <details> menus when clicking elsewhere */
    document.addEventListener("click", function (event) {
      Array.prototype.forEach.call(document.querySelectorAll("details.menu[open]"), function (menu) {
        if (!menu.contains(event.target)) menu.removeAttribute("open");
      });
    });
    /* "select all" checkboxes: <input type=checkbox data-check-all="name"> */
    Array.prototype.forEach.call(document.querySelectorAll("[data-check-all]"), function (master) {
      var name = master.getAttribute("data-check-all");
      var scope = master.closest("form") || document;
      function boxes() { return scope.querySelectorAll('input[type="checkbox"][name="' + name + '"]'); }
      function sync() {
        var all = boxes(), on = 0;
        Array.prototype.forEach.call(all, function (b) { if (b.checked && b.closest("tr, label, li") && b.closest("tr, label, li").offsetParent !== null) on += 1; });
        var counter = scope.querySelector("[data-check-count]");
        if (counter) counter.textContent = on;
        var bar = scope.querySelector("[data-check-bar]");
        if (bar) bar.hidden = on === 0;
      }
      master.addEventListener("change", function () {
        Array.prototype.forEach.call(boxes(), function (b) {
          var row = b.closest("tr, label, li");
          if (!row || row.offsetParent !== null) b.checked = master.checked;
        });
        sync();
      });
      scope.addEventListener("change", function (e) { if (e.target.name === name) sync(); });
      sync();
    });
    /* live filter for long lists: <input data-filter="#selector-of-items"> */
    Array.prototype.forEach.call(document.querySelectorAll("[data-filter]"), function (input) {
      var items = document.querySelectorAll(input.getAttribute("data-filter"));
      input.addEventListener("input", function () {
        var q = input.value.trim().toLowerCase();
        Array.prototype.forEach.call(items, function (el) {
          el.hidden = q !== "" && el.textContent.toLowerCase().indexOf(q) === -1;
        });
      });
    });
    /* copy buttons: <button data-copy="text"> */
    document.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-copy]");
      if (!btn) return;
      copyText(btn.getAttribute("data-copy")).then(function () { toast(btn.getAttribute("data-copied") || "✓"); });
    });
    /* print buttons */
    document.addEventListener("click", function (event) {
      if (event.target.closest("[data-print]")) window.print();
    });
    /* password generator buttons: <button data-gen-password="#input"> */
    document.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-gen-password]");
      if (!btn) return;
      var input = document.querySelector(btn.getAttribute("data-gen-password"));
      var chars = "abcdefghjkmnpqrstuvwxyz23456789", out = "";
      var rnd = new Uint32Array(6);
      (window.crypto || window.msCrypto).getRandomValues(rnd);
      for (var i = 0; i < 6; i += 1) out += chars[rnd[i] % chars.length];
      if (input) { input.value = out; input.type = "text"; input.focus(); }
    });
    /* auto-submit selects inside filter forms */
    Array.prototype.forEach.call(document.querySelectorAll("form[data-autosubmit] select"), function (sel) {
      sel.addEventListener("change", function () { sel.form.submit(); });
    });
  });

  document.addEventListener("click", function (event) {
    var dismiss = event.target.closest("[data-dismiss]");
    if (dismiss) {
      var alertBox = dismiss.closest(".alert");
      if (alertBox) alertBox.remove();
    }
  });

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      var message = form.getAttribute && form.getAttribute("data-confirm");
      if (message && !window.confirm(message)) event.preventDefault();
    },
    true
  );
})();
