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
    initChecks(document);
    initSort(document);
    initLiveSearch();
    /* auto-submit selects inside filter forms */
    Array.prototype.forEach.call(document.querySelectorAll("form[data-autosubmit] select"), function (sel) {
      sel.addEventListener("change", function () { sel.form.submit(); });
    });
  });

  /* "select all" checkboxes: <input type=checkbox data-check-all="name"> */
  function initChecks(root) {
    Array.prototype.forEach.call(root.querySelectorAll("[data-check-all]"), function (master) {
      if (master._bound) return;
      master._bound = true;
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
      if (!scope["_checks_" + name]) {
        scope["_checks_" + name] = true;
        scope.addEventListener("change", function (e) { if (e.target.name === name) sync(); });
      }
      sync();
    });
  }

  /* ---------- sortable lists: click a column title to sort (▲ / ▼) ---------- */
  function cellKey(td) {
    var raw = (td.getAttribute("data-sort") || td.textContent || "").trim();
    var text = raw.replace(/[٠-٩]/g, function (d) { return String(d.charCodeAt(0) - 0x0660); })
      .replace(/[۰-۹]/g, function (d) { return String(d.charCodeAt(0) - 0x06F0); }).replace(/٫/g, ".");
    var m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:[ ،,]+(\d{1,2}):(\d{2}))?/);  /* dd/mm/yyyy hh:mm */
    if (m) return { n: +m[3] * 1e8 + +m[2] * 1e6 + +m[1] * 1e4 + (+m[4] || 0) * 100 + (+m[5] || 0) };
    m = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]+(\d{1,2}):(\d{2}))?/);
    if (m) return { n: +m[1] * 1e8 + +m[2] * 1e6 + +m[3] * 1e4 + (+m[4] || 0) * 100 + (+m[5] || 0) };
    m = text.match(/^-?\d+(?:\.\d+)?(?=\s*(?:%|\/|$|\s))/);
    if (m) return { n: parseFloat(m[0]) };
    return { s: text.toLowerCase() };
  }
  function initSort(root) {
    Array.prototype.forEach.call(root.querySelectorAll("table.table"), function (table) {
      if (table._sortable || table.hasAttribute("data-nosort") || !table.tHead || !table.tBodies[0]) return;
      var rows = table.tBodies[0].rows;
      if (rows.length < 2) return;
      table._sortable = true;
      var heads = table.tHead.rows[0].cells;
      Array.prototype.forEach.call(heads, function (th, col) {
        var label = th.textContent.trim();
        if (!label || label === "#" || th.querySelector("input")) return;
        th.classList.add("sortable");
        th.setAttribute("tabindex", "0");
        th.setAttribute("aria-sort", "none");
        var arrow = document.createElement("span");
        arrow.className = "sort-arrow";
        arrow.setAttribute("aria-hidden", "true");
        th.appendChild(arrow);
        function go() {
          var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
          Array.prototype.forEach.call(heads, function (h) { if (h.hasAttribute("aria-sort")) h.setAttribute("aria-sort", "none"); });
          th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
          var body = table.tBodies[0];
          var list = Array.prototype.slice.call(body.rows).map(function (tr, i) { return { tr: tr, i: i, k: tr.cells[col] ? cellKey(tr.cells[col]) : { s: "" } }; });
          list.sort(function (a, b) {
            var x = a.k, y = b.k, r;
            if (x.n !== undefined && y.n !== undefined) r = x.n - y.n;
            else if (x.n !== undefined) r = -1;
            else if (y.n !== undefined) r = 1;
            else r = (x.s || "").localeCompare(y.s || "", "ar");
            return r * dir || a.i - b.i;
          });
          list.forEach(function (item) { body.appendChild(item.tr); });
          /* keep a leading "#" column counting 1, 2, 3 */
          if (heads[0] && heads[0].textContent.trim() === "#") {
            Array.prototype.forEach.call(body.rows, function (tr, i) {
              if (tr.cells[0]) tr.cells[0].textContent = window.Digits ? window.Digits.local(String(i + 1)) : String(i + 1);
            });
          }
        }
        th.addEventListener("click", function (e) { if (!e.target.closest("input, a, button")) go(); });
        th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      });
    });
  }

  /* ---------- search while typing: <form data-live-search> refreshes the [data-live-target] parts ---------- */
  function initLiveSearch() {
    Array.prototype.forEach.call(document.querySelectorAll("form[data-live-search]"), function (form) {
      var input = form.querySelector('input[type="search"], input[name="q"]');
      if (!input) return;
      var timer = null, seq = 0;
      function run() {
        var params = new URLSearchParams(new FormData(form));
        var url = (form.getAttribute("action") || location.pathname) + "?" + params.toString();
        var mine = ++seq;
        form.classList.add("searching");
        fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "live" } }).then(function (r) { return r.text(); }).then(function (html) {
          if (mine !== seq) return;
          var doc = new DOMParser().parseFromString(html, "text/html");
          var fresh = doc.querySelectorAll("[data-live-target]");
          Array.prototype.forEach.call(document.querySelectorAll("[data-live-target]"), function (el, i) {
            if (!fresh[i]) return;
            el.innerHTML = fresh[i].innerHTML;
            initChecks(el);
            initSort(el);
          });
          if (history.replaceState) history.replaceState(null, "", url);
        }).catch(function () { /* the button still submits normally */ }).then(function () {
          if (mine === seq) form.classList.remove("searching");
        });
      }
      input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 300); });
      form.addEventListener("submit", function (e) { e.preventDefault(); clearTimeout(timer); run(); });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
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
      var btn = event.submitter;
      var message = (btn && btn.getAttribute && btn.getAttribute("data-confirm")) || (form.getAttribute && form.getAttribute("data-confirm"));
      if (message && !window.confirm(message)) event.preventDefault();
    },
    true
  );
})();
