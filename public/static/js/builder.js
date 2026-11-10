/* Exam builder (v4).
   Storage is unchanged from earlier versions: question text keeps **bold** / __underline__ marks, blanks stay
   [word] / [word|alternative] / [ ] (empty, manual grading). New presentation-only data lives in q.extra. */
(function () {
  "use strict";

  var builder = document.getElementById("builder");
  if (!builder) return;

  var data = JSON.parse(document.getElementById("form-data").textContent);
  var T = JSON.parse(document.getElementById("i18n-data").textContent);
  var api = window.App.api;
  var toast = window.App.toast;

  var GRADED = ["mcq", "checkbox", "dropdown", "truefalse", "short", "number", "match", "fill", "order"];
  var CHOICE = ["mcq", "checkbox", "dropdown"];
  var UNSCORED = ["scale", "date", "section"];
  var MANUAL = ["paragraph", "file", "draw"];
  var TYPES = ["mcq", "checkbox", "dropdown", "truefalse", "short", "fill", "order", "match", "number", "paragraph", "draw", "file", "section", "scale", "date"];
  var GROUPS = [["qgroup_choice", ["mcq", "checkbox", "dropdown", "truefalse"]],
    ["qgroup_write", ["short", "fill", "order", "number", "paragraph", "draw"]],
    ["qgroup_other", ["match", "section", "file", "scale", "date"]]];
  var BLANK_RE = /\[([^\[\]\n]+)\]/g;
  var INV = "⁣"; /* invisible text given to picture-only options so they stay distinct */

  var settings = data.settings;
  var questions = data.questions;
  function padEmpty(q) {  /* an unfinished question comes back from autosave without its empty rows */
    q.extra = q.extra && typeof q.extra === "object" ? q.extra : {};
    if (CHOICE.indexOf(q.type) !== -1) { q.options = Array.isArray(q.options) ? q.options : []; while (q.options.length < 2) q.options.push(""); }
    if (q.type === "match") { q.options = q.options && typeof q.options === "object" ? q.options : {}; if (!(q.options.pairs || []).length) q.options.pairs = [["", ""]]; }
    if (tfMulti(q)) { if (!q.options.items.length) q.options.items = ["", ""]; if (!q.manual_grade && !Array.isArray(q.correct)) q.correct = []; tfSync(q); }
    return q;
  }
  questions.forEach(padEmpty);
  var revision = 0, savedRevision = 0, saving = false, saveTimer = null, retryTimer = null, retryDelay = 3000;
  var pendingFocus = null, activeIndex = 0, previewTimer = null, device = "phone";

  var list = $("q-list");
  var summary = $("summary");
  var saveState = $("save-state");
  var preview = $("preview-body");

  function $(id) { return document.getElementById(id); }
  function fmt(text, values) {
    return String(text || "").replace(/\{(\w+)\}/g, function (m, key) { return values && values[key] !== undefined ? values[key] : m; });
  }
  function h(tag, props, children) {
    var el = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (key) {
      var value = props[key];
      if (value === undefined || value === null || value === false) return;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key === "html") el.innerHTML = value;
      else if (key === "value") el.value = value;
      else if (key.slice(0, 2) === "on") el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? "" : value);
    });
    (children || []).forEach(function (child) {
      if (child) el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return el;
  }
  function esc(s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /* same marks as the server's |rich filter */
  function rich(text) {
    var html = esc(text);
    html = html.replace(/__([^_\s](?:[^\n]*?[^_\s])?)__/g, "<u>$1</u>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    return html.replace(/\n/g, "<br>");
  }
  function media(name) { return data.mediaBase.replace("__NAME__", name); }
  function num(n) { return Math.round((parseFloat(latin(n)) || 0) * 100) / 100; }
  /* number fields show the interface's digits (digits.js) and are read back as 0-9 */
  function latin(v) { return window.Digits ? window.Digits.latin(v) : String(v == null ? "" : v); }
  function numVal(el) { return parseFloat(latin(el.value)); }
  function setNumInput(el, v) { if (window.Digits) window.Digits.setNum(el, v); else el.value = v; }
  function numInput(props) {
    var el = h("input", Object.assign({ type: "text", inputmode: "decimal", autocomplete: "off", "data-num": "1", dir: "ltr" }, props));
    if (window.Digits) window.Digits.numField(el);
    return el;
  }
  function shown(text) { return String(text || "").split(INV).join(""); }

  var ICONS = {
    up: '<path d="m18 15-6-6-6 6"/>', down: '<path d="m6 9 6 6 6-6"/>',
    fold: '<path d="m7 20 5-5 5 5"/><path d="m7 4 5 5 5-5"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    minus: '<path d="M5 12h14"/>',
    grip: '<circle cx="9" cy="5" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="19" r="1"/>',
    bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    check: '<path d="M20 6 9 17l-5-5"/>', spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/><path d="m9 13 2 2 4-4"/>',
    cloudoff: '<path d="m2 2 20 20"/><path d="M5.78 5.78A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.31-.2"/><path d="M21.53 16.5A4.5 4.5 0 0 0 17.5 10h-1.79A7 7 0 0 0 10.5 5.07"/>',
    spin: '<path d="M21 12a9 9 0 1 1-6.22-8.56"/>', blank: '<path d="M4 17h16"/><path d="M8 13h8"/><path d="M12 5v4"/>',
    eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    star: '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>'
  };
  function icon(name, size) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 16) + '" height="' + (size || 16) +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (ICONS[name] || "") + "</svg>";
  }
  function iconButton(name, label, onClick, extra) {
    extra = extra || {};
    return h("button", {
      type: "button", class: "icon-btn" + (extra.danger ? " danger" : "") + (extra.extraClass ? " " + extra.extraClass : ""),
      title: label, "aria-label": label, html: icon(name, 16), onclick: onClick, disabled: !!extra.disabled
    });
  }
  function chipButton(iconName, label, onClick, cls) {
    var b = h("button", { type: "button", class: "chip " + (cls || ""), html: (iconName ? icon(iconName, 14) : "") + "<span></span>", onclick: onClick });
    b.querySelector("span").textContent = label;
    return b;
  }

  /* ================= state ================= */
  function touch(q) {
    revision += 1;
    if (q && q._error) delete q._error;
    if (q) refreshCardState(q);
    setSaveState("saving");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save(); }, 1200);
    updateSummary();
    schedulePreview();
  }

  function setSaveState(state, message) {
    var map = {
      saved: ["ok", "cloud", T.saved_ok],
      saving: ["busy", "spin", T.saving_now],
      offline: ["off", "cloudoff", T.offline_retry],
      error: ["off", "cloudoff", T.offline_retry],
      idle: ["", "", ""]
    };
    var m = map[state] || map.idle;
    saveState.className = "save-state " + m[0];
    saveState.innerHTML = m[2] ? (m[1] ? icon(m[1], 14) : "") + "<span></span>" : "";
    if (m[2]) saveState.querySelector("span").textContent = m[2];
  }

  function tfMulti(q) { return q.type === "truefalse" && q.options && Array.isArray(q.options.items); }
  /* keep statements, marks and points the same length */
  function tfSync(q) {
    var o = q.options, n = o.items.length;
    if (!Array.isArray(o.item_points)) o.item_points = [];
    o.item_points = o.item_points.slice(0, n);
    while (o.item_points.length < n) o.item_points.push(1);
    if (!q.manual_grade) {
      var c = Array.isArray(q.correct) ? q.correct.slice(0, n) : [];
      while (c.length < n) c.push(null);
      q.correct = c;
      q.points = num(o.item_points.reduce(function (a, b) { return a + (parseFloat(b) || 0); }, 0));
    }
  }
  function tfDefaults(q) {
    q.options = { items: ["", ""], item_points: [1, 1] };
    q.correct = q.manual_grade ? null : [null, null];
    if (!String(q.text || "").trim()) q.text = T.tf_instruction_default;
    q.points = 2;
  }

  function newQuestion(type) {
    var manual = GRADED.indexOf(type) !== -1 && !!data.defaultManual;
    var q = {
      id: null, type: type, text: "", description: "", image: "", audio: "", extra: {},
      points: UNSCORED.indexOf(type) !== -1 ? 0 : (type === "match" || type === "fill" ? 2 : 1),
      required: type !== "section", options: null, correct: null, explanation: "", partial: false,
      manual_grade: manual, _fresh: true
    };
    applyTypeDefaults(q);
    if (type === "fill") q.options.bank = !manual;
    if (type === "truefalse") tfDefaults(q);  /* new cards hold several statements */
    return q;
  }

  function applyTypeDefaults(q) {
    if (CHOICE.indexOf(q.type) !== -1) {
      if (!Array.isArray(q.options)) q.options = ["", ""];
    } else if (q.type === "scale") {
      if (!q.options || q.options.max === undefined) q.options = { max: 5, min_label: "", max_label: "", style: "stars" };
    } else if (q.type === "draw") {
      if (!q.options || q.options.height === undefined) q.options = { lines: true, height: 380 };
    } else if (q.type === "match") {
      if (!q.options || !Array.isArray(q.options.pairs)) q.options = { pairs: [["", ""], ["", ""], ["", ""]], distractors: [] };
    } else if (q.type === "fill") {
      if (!q.options || typeof q.options.template !== "string") q.options = { template: "", bank: !q.manual_grade, distractors: [] };
    } else if (q.type === "truefalse" && q.options && Array.isArray(q.options.items)) {
      /* several statements: keep them */
    } else {
      q.options = null;
    }
  }

  function changeType(q, type) {
    var wasChoice = CHOICE.indexOf(q.type) !== -1;
    var oldCorrect = q.correct;
    var wasUnscored = UNSCORED.indexOf(q.type) !== -1;
    var wasGraded = GRADED.indexOf(q.type) !== -1;
    q.type = type;
    if (!wasGraded && GRADED.indexOf(type) !== -1) q.manual_grade = !!data.defaultManual;
    if (!(wasChoice && CHOICE.indexOf(type) !== -1)) q.options = null;
    applyTypeDefaults(q);
    q.correct = null;
    if (wasChoice && CHOICE.indexOf(type) !== -1) {
      if (type === "checkbox") q.correct = Array.isArray(oldCorrect) ? oldCorrect : (typeof oldCorrect === "number" ? [oldCorrect] : null);
      else q.correct = Array.isArray(oldCorrect) ? (oldCorrect.length ? oldCorrect[0] : null) : (typeof oldCorrect === "number" ? oldCorrect : null);
    }
    if (UNSCORED.indexOf(type) !== -1) q.points = 0;
    else if (wasUnscored) q.points = 1;
    if (type === "section") q.required = false;
    if (type === "truefalse") tfDefaults(q);
    if (type !== "checkbox") q.partial = false;
    delete q.extra.option_images; delete q.extra.left_images; delete q.extra.right_images;
  }

  function blanksOf(q) {
    var out = [];
    String((q.options && q.options.template) || "").replace(BLANK_RE, function (m, inner) { out.push(inner); return m; });
    return out;
  }
  function altsOf(raw) { return String(raw || "").split("|").map(function (s) { return s.trim(); }).filter(Boolean); }

  /* What is missing? "" = complete */
  function issueOf(q) {
    if (q.type === "section") return "";
    if (!String(q.text || "").trim()) return T.warn_no_text;
    if (CHOICE.indexOf(q.type) !== -1) {
      var filled = q.options.filter(function (o, i) { return String(o).trim() || imgAt(q, "option_images", i); }).length;
      if (filled < 2) return T.warn_two_options;
    }
    if (q.type === "match" && !(q.options.pairs || []).some(function (p, i) {
      return (String(p[0]).trim() || imgAt(q, "left_images", i)) && (String(p[1]).trim() || imgAt(q, "right_images", i));
    })) return T.warn_add_pair;
    if (q.type === "fill" && !blanksOf(q).length) return T.warn_add_blank;
    if (q.type === "order" && !(q.correct || []).length) return T.warn_add_answer;
    if (tfMulti(q)) {
      var filledTf = q.options.items.filter(function (x) { return String(x).trim(); }).length;
      if (!filledTf) return T.warn_tf_items;
      if (q.manual_grade) return "";
      return q.options.items.every(function (x, i) { return !String(x).trim() || (q.correct && (q.correct[i] === "true" || q.correct[i] === "false")); }) ? "" : T.warn_tf_marks;
    }
    if (GRADED.indexOf(q.type) === -1 || q.manual_grade) return "";
    if (q.type === "fill") return blanksOf(q).every(function (b) { return altsOf(b).length; }) ? "" : T.warn_blank_answers;
    if (q.type === "match" || q.type === "order") return "";
    var c = q.correct;
    var missing = c === null || c === undefined || (Array.isArray(c) && !c.length);
    if (!missing) return "";
    if (q.type === "checkbox") return T.warn_pick_correct_multi;
    return (CHOICE.indexOf(q.type) !== -1 || q.type === "truefalse") ? T.warn_pick_correct : T.warn_add_answer;
  }

  /* problems that stop the exam from being saved (the server would refuse them) */
  function blockingIssue(q) {
    if (q.type === "section") return "";
    if (!String(q.text || "").trim()) return T.warn_no_text;
    if (CHOICE.indexOf(q.type) !== -1 && q.options.filter(function (o, i) { return String(o).trim() || imgAt(q, "option_images", i); }).length < 2) return T.warn_two_options;
    if (q.type === "match" && issueOf(q) === T.warn_add_pair) return T.warn_add_pair;
    if (q.type === "fill" && !blanksOf(q).length) return T.warn_add_blank;
    if (q.type === "order" && !(q.correct || []).length) return T.warn_add_answer;
    return "";
  }
  /* the warning is shown only after the teacher has left the question */
  function shownIssue(q) {
    if (q._error) return q._error;
    return q._fresh ? "" : issueOf(q);
  }
  function leave(q) {
    if (!q || !q._fresh) return;
    delete q._fresh;
    refreshCardState(q);
    updateSummary();
  }

  function imgAt(q, key, i) { var a = q.extra && q.extra[key]; return a && a[i] ? a[i] : ""; }
  function setImg(q, key, i, name, size) {
    var a = (q.extra[key] || []).slice(0, size);
    while (a.length < size) a.push("");
    a[i] = name || "";
    q.extra[key] = a;
    if (!a.some(Boolean)) delete q.extra[key];
  }

  /* ================= card ================= */
  function cardClass(q) {
    var c = "card qcard t-" + q.type + (q._collapsed ? " collapsed" : "");
    if (q.type === "section") return c + " section";
    if (GRADED.indexOf(q.type) !== -1 && q.manual_grade) c += " manual no-key";
    else if (MANUAL.indexOf(q.type) !== -1) c += " manual";
    else if (UNSCORED.indexOf(q.type) !== -1) c += " info";
    if (shownIssue(q)) c += " warn";
    return c;
  }

  function modeBadge(q) {
    if (q.type === "section") return null;
    if (UNSCORED.indexOf(q.type) !== -1) return h("span", { class: "badge gray", text: T.not_counted });
    var manual = MANUAL.indexOf(q.type) !== -1 || q.manual_grade;
    return h("span", { class: "badge " + (manual ? "amber" : "green"), text: manual ? T.grading_manual : T.grading_auto });
  }

  function fillStatus(el, q) {
    var issue = shownIssue(q);
    var pending = !issue && q._fresh && issueOf(q);
    el.className = "q-status" + (q.type === "section" || pending ? "" : issue ? " warn" : " ok");
    el.innerHTML = q.type === "section" || pending ? "" : issue ? icon("alert", 14) + "<span></span>" : icon("check", 15);
    if (issue) el.querySelector("span").textContent = issue;
  }
  function fillWarn(el, q) {
    var issue = shownIssue(q);
    el.hidden = !issue;
    el.innerHTML = issue ? icon("alert", 15) + "<span></span>" : "";
    if (issue) el.querySelector("span").textContent = issue;
  }

  function refreshCardState(q) {
    if (!q._el) return;
    q._el.className = cardClass(q) + (q._el.classList.contains("focus") ? " focus" : "");
    if (q._status) fillStatus(q._status, q);
    if (q._warn) fillWarn(q._warn, q);
    if (q._sumText) {
      var first = String(q.text || "").split("\n")[0];
      q._sumText.textContent = first || (q.type === "section" ? T.type_section : T.untitled_question);
      q._sumText.classList.toggle("empty", !first);
    }
    if (q._pts) q._pts.textContent = fmt(T.n_points, { n: num(q.points) });
  }

  function renderCard(q, index) {
    var card = h("article", { class: cardClass(q), "data-index": index });
    q._el = card;
    q._warn = null;
    var number = questions.slice(0, index + 1).filter(function (x) { return x.type !== "section"; }).length;

    var grip = h("span", { class: "grip", title: T.drag_hint, html: icon("grip", 16) });
    grip.addEventListener("pointerdown", function (event) { startDrag(event, index, card); });
    grip.tabIndex = 0;
    grip.setAttribute("role", "button");
    grip.setAttribute("aria-label", T.drag_hint);
    grip.addEventListener("keydown", function (event) {  /* keyboard: arrows move the question */
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      move(index, event.key === "ArrowUp" ? -1 : 1);
      var g = list.querySelectorAll(".qcard")[Math.max(0, Math.min(questions.length - 1, index + (event.key === "ArrowUp" ? -1 : 1)))];
      if (g && g.querySelector(".grip")) g.querySelector(".grip").focus();
    });

    var numEl = h("span", { class: "q-num" + (q.type === "section" ? " sec" : ""), text: q.type === "section" ? "§" : String(number) });
    q._sumText = h("span", { class: "q-sum-text", dir: q.extra.dir || "auto" });
    q._pts = UNSCORED.indexOf(q.type) === -1 ? h("span", { class: "badge gray pts-chip" }) : null;
    q._status = h("span", { class: "q-status" });
    fillStatus(q._status, q);

    if (q._collapsed) {
      var row = h("button", { type: "button", class: "q-collapsed", "aria-expanded": "false",
        onclick: function () { openCard(index); } }, [
        numEl, q._sumText,
        h("span", { class: "badge soft type-chip-sm", text: T["type_" + q.type] }),
        q._pts, q._status, h("span", { class: "chev", html: icon("down", 16) })
      ]);
      card.appendChild(h("div", { class: "qcard-row" }, [grip, row]));
      refreshCardState(q);
      return card;
    }

    var typeSelect = h("select", { class: "qtype", "aria-label": fmt(T.question_n, { n: number }),
      onchange: function () { changeType(q, typeSelect.value); touch(q); render(); } });
    TYPES.forEach(function (type) {
      var o = h("option", { value: type, text: T["type_" + type] });
      if (type === q.type) o.selected = true;
      typeSelect.appendChild(o);
    });

    var head = h("div", { class: "qcard-head" }, [
      grip, numEl, typeSelect, modeBadge(q), q._pts, h("span", { class: "spacer" }),
      h("div", { class: "qcard-tools" }, [
        iconButton("copy", T.duplicate, function () { duplicate(index); }),
        iconButton("bookmark", T.bank_save_one, function () { saveToBank(q); }),
        iconButton("plus", T.insert_here, function (e) { openTypePicker(e.currentTarget, index + 1); }, { extraClass: "add" }),
        iconButton("trash", T.remove, function () { remove(index); }, { danger: true })
      ])
    ]);

    head.addEventListener("click", function (e) {
      if (e.target.closest("button, select, input, a, .grip, label")) return;
      keepPlace(card, function () { leave(q); q._collapsed = true; render(); });
    });
    head.title = T.click_to_fold;
    var fields = h("div", { class: "q-fields qcard-body" });
    q._warn = h("p", { class: "q-warn", role: "status" });
    fields.appendChild(q._warn);
    fields.appendChild(textEditor(q));
    if (q.type === "section") {
      var body = h("textarea", { rows: "4", class: "sec-body", maxlength: "6000", dir: q.extra.dir || "auto", placeholder: T.sec_reading_ph, "aria-label": T.section_body,
        oninput: function () { q.description = body.value; touch(q); } });
      body.value = q.description || "";
      fields.appendChild(body);
      fields.appendChild(h("p", { class: "q-hint", text: T.section_note }));
    } else {
      var hintInput = h("input", { type: "text", maxlength: "1500", dir: q.extra.dir || "auto", placeholder: T.question_help, "aria-label": T.question_help,
        value: q.description, oninput: function () { q.description = hintInput.value; touch(q); } });
      fields.appendChild(hintInput);
    }

    var bodyEl = null;
    if (CHOICE.indexOf(q.type) !== -1) bodyEl = renderChoice(q);
    else if (q.type === "truefalse") bodyEl = renderTrueFalse(q);
    else if (q.type === "short") bodyEl = renderShort(q);
    else if (q.type === "number") bodyEl = renderNumber(q);
    else if (q.type === "scale") bodyEl = renderScale(q);
    else if (q.type === "match") bodyEl = renderMatch(q);
    else if (q.type === "fill") bodyEl = renderFill(q);
    else if (q.type === "order") bodyEl = renderOrder(q);
    else if (q.type === "draw") bodyEl = renderDraw(q);
    if (bodyEl) fields.appendChild(bodyEl);

    if (q.type === "paragraph") fields.appendChild(h("p", { class: "q-hint", text: T.manual_grade_note }));
    if (q.type === "file") fields.appendChild(h("p", { class: "q-hint", text: T.file_upload_note }));
    if (GRADED.indexOf(q.type) !== -1 && q.manual_grade && ["fill", "truefalse", "mcq", "checkbox", "dropdown"].indexOf(q.type) === -1) {
      fields.appendChild(h("p", { class: "q-hint warn", text: T.manual_no_key }));
    }
    if (UNSCORED.indexOf(q.type) !== -1 && q.type !== "section") fields.appendChild(h("p", { class: "q-hint", text: T.info_only_note }));

    if (GRADED.indexOf(q.type) !== -1 || MANUAL.indexOf(q.type) !== -1) {
      var explBtn = h("button", { type: "button", class: "chip expl-btn" + (String(q.explanation || "").trim() ? " on" : ""),
        "aria-expanded": q._showExpl ? "true" : "false", html: icon("info", 14) + "<span></span>",
        onclick: function () {
          q._showExpl = !q._showExpl;
          explBtn.setAttribute("aria-expanded", q._showExpl ? "true" : "false");
          explanation.hidden = !q._showExpl;
          if (q._showExpl) { grow(explanation); explanation.focus(); }
        } });
      explBtn.querySelector("span").textContent = T.explanation_btn;
      var explanation = h("textarea", { rows: "2", maxlength: "2000", dir: q.extra.dir || "auto", class: "expl-field",
        placeholder: T.explanation_ph, "aria-label": T.explanation, hidden: !q._showExpl,
        oninput: function () { q.explanation = explanation.value; explBtn.classList.toggle("on", !!explanation.value.trim()); touch(q); } });
      explanation.value = q.explanation || "";
      var toolRow = bodyEl && bodyEl.querySelector(".opt-tools");
      if (!toolRow) { toolRow = h("div", { class: "opt-tools" }); fields.appendChild(toolRow); }
      toolRow.appendChild(explBtn);
      fields.appendChild(explanation);
    }
    var foot = footRow(q);
    if (foot.children.length) fields.appendChild(foot);
    card.appendChild(head);
    card.appendChild(fields);
    refreshCardState(q);
    return card;
  }

  function footRow(q) {
    var row = h("div", { class: "q-row q-foot" });
    var autoFill = (q.type === "fill" || tfMulti(q)) && !q.manual_grade;
    if (UNSCORED.indexOf(q.type) === -1) {
      var points = numInput({ value: q.points, "aria-label": T.points, maxlength: "7",
        readonly: autoFill, title: autoFill ? T.fill_points_auto : null,
        oninput: function () { var n = numVal(points); q.points = isNaN(n) ? 0 : Math.max(0, Math.min(1000, n)); touch(q); } });
      q._pointsInput = points;
      row.appendChild(h("label", { class: "pts" }, [h("span", { text: T.points }), points]));
    }
    if (q.type !== "section") {
      var required = h("input", { type: "checkbox", onchange: function () { q.required = required.checked; touch(q); } });
      required.checked = !!q.required;
      row.appendChild(h("label", { class: "check switch", style: "margin:0" }, [required, h("span", { text: T.required })]));
    }
    if (GRADED.indexOf(q.type) !== -1) {
      var modeSel = h("div", { class: "grade-mode", role: "radiogroup", "aria-label": T.grading_mode });
      [["auto", T.grading_auto], ["manual", T.grading_manual]].forEach(function (m) {
        modeSel.appendChild(h("button", { type: "button", class: "gm" + ((m[0] === "manual") === !!q.manual_grade ? " on" : ""), text: m[1],
          onclick: function () {
            var manual = m[0] === "manual";
            if (manual === !!q.manual_grade) return;
            q.manual_grade = manual;
            if (q.type === "fill") {
              if (!q._bankTouched) q.options.bank = !manual; /* word box: on for auto, off for manual by default */
              if (!manual) syncFillPoints(q);
            }
            if (tfMulti(q)) { if (manual) q.correct = null; tfSync(q); }
            touch(q); render();
          } }));
      });
      row.appendChild(h("span", { class: "spacer" }));
      row.appendChild(h("span", { class: "gm-label", text: T.grading_mode }));
      row.appendChild(modeSel);
    }
    return row;
  }

  /* ---------- question text: toolbar (B, U, formula, direction, picture, sound, recording, file) ---------- */
  function textEditor(q) {
    var box = h("div", { class: "text-box" });
    var area = h("textarea", { rows: "1", maxlength: "1500", dir: q.extra.dir || "auto", "data-q-text": "1",
      placeholder: q.type === "section" ? T.section_title : T.question_text, "aria-label": T.question_text,
      oninput: function () { q.text = area.value; area.classList.remove("invalid"); touch(q); } });
    area.value = q.text;

    function wrap(mark) {
      var s = area.selectionStart, e = area.selectionEnd, v = area.value;
      var sel = v.slice(s, e);
      area.value = v.slice(0, s) + mark + sel + mark + v.slice(e);
      area.focus();
      area.setSelectionRange(s + mark.length, e + mark.length);
      q.text = area.value; touch(q);
    }
    function setDir(dir) {
      q.extra.dir = q.extra.dir === dir ? "" : dir;
      if (!q.extra.dir) delete q.extra.dir;
      touch(q); render();
    }
    var bar = h("div", { class: "fmt-bar", role: "toolbar", "aria-label": T.format_bar });
    function tb(html, label, fn, cls) {
      var b = h("button", { type: "button", class: "fmt " + (cls || ""), title: label, "aria-label": label, html: html,
        onmousedown: function (e) { e.preventDefault(); }, onclick: fn });
      bar.appendChild(b);
      return b;
    }
    tb("<b>B</b>", T.fmt_bold, function () { wrap("**"); });
    tb("<u>U</u>", T.fmt_underline, function () { wrap("__"); });
    tb("√x", T.fmt_math, function (e) { openMath(e.currentTarget, area, q); }, "math");
    bar.appendChild(h("span", { class: "fmt-sep" }));
    tb("ع ←", T.dir_rtl, function () { setDir("rtl"); }, "dir" + (q.extra.dir === "rtl" ? " on" : ""));
    tb("EN →", T.dir_ltr, function () { setDir("ltr"); }, "dir" + (q.extra.dir === "ltr" ? " on" : ""));
    bar.appendChild(h("span", { class: "fmt-sep" }));
    var imgInput = fileInput("image/*", function (f) { upload(f, f.name, null, function (res) { q.image = res.name; touch(q); render(); }); });
    var audInput = fileInput("audio/*", function (f) { upload(f, f.name, null, function (res) { q.audio = res.name; touch(q); render(); }); });
    var attInput = fileInput(".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv", function (f) {
      upload(f, f.name, "attach", function (res) { q.extra.attachment = { name: res.name, label: res.label || f.name }; touch(q); render(); });
    });
    tb(icon("image", 15), q.image ? T.change_image : T.add_image, function () { imgInput.click(); });
    tb(icon("music", 15), T.add_audio, function () { audInput.click(); });
    var recBtn = tb(icon("mic", 15), T.record_audio, function () { record(q, recBtn); });
    tb(icon("clip", 15), T.add_file, function () { attInput.click(); });
    box.appendChild(bar);
    box.appendChild(area);
    [imgInput, audInput, attInput].forEach(function (i) { box.appendChild(i); });

    var strip = h("div", { class: "media-strip" });
    if (q.image && !(q.type === "draw" && q.options && q.options.on_image)) strip.appendChild(h("span", { class: "media-item" }, [
      h("img", { src: media(q.image), alt: "", class: "q-img-thumb" }),
      iconButton("x", T.remove_image, function () { q.image = ""; touch(q); render(); }, { danger: true })]));
    if (q.audio) strip.appendChild(h("span", { class: "media-item" }, [
      h("audio", { controls: true, preload: "none", src: media(q.audio) }),
      iconButton("x", T.remove_audio, function () { q.audio = ""; touch(q); render(); }, { danger: true })]));
    if (q.extra.attachment) strip.appendChild(h("span", { class: "media-item file" }, [
      h("span", { html: icon("clip", 14) }), h("a", { href: media(q.extra.attachment.name) + "?name=" + encodeURIComponent(q.extra.attachment.label || ""), target: "_blank", text: q.extra.attachment.label || q.extra.attachment.name }),
      iconButton("x", T.remove, function () { delete q.extra.attachment; touch(q); render(); }, { danger: true })]));
    if (strip.children.length) box.appendChild(strip);
    return box;
  }

  function fileInput(accept, onFile) {
    var input = h("input", { type: "file", accept: accept, hidden: true });
    input.addEventListener("change", function () {
      var f = input.files && input.files[0];
      input.value = "";
      if (f) onFile(f);
    });
    return input;
  }

  function upload(fileOrBlob, filename, kind, done) {
    var body = new FormData();
    body.append("file", fileOrBlob, filename);
    if (kind) body.append("kind", kind);
    toast(T.uploading);
    api(data.imageUrl, { body: body }).then(function (res) {
      if (!res.ok) { toast(res.error || T.image_error); return; }
      done(res);
    }).catch(function () { toast(T.image_error); });
  }

  var recorder = null;
  function record(q, btn) {
    if (recorder && recorder.state === "recording") { recorder.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { toast(T.mic_denied); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (tr) { tr.stop(); });
        var type = recorder.mimeType || "audio/webm";
        var ext = type.indexOf("mp4") !== -1 ? "m4a" : (type.indexOf("ogg") !== -1 ? "ogg" : "webm");
        btn.classList.remove("rec");
        upload(new Blob(chunks, { type: type }), "recording." + ext, null, function (res) { q.audio = res.name; touch(q); render(); });
      };
      recorder.start();
      btn.classList.add("rec");
      toast(T.recording);
    }).catch(function () { toast(T.mic_denied); });
  }

  /* ---------- LaTeX formula box ---------- */
  var mathPop = null;
  function closePop() { if (mathPop) { mathPop.remove(); mathPop = null; } }
  function openMath(anchor, target, q) {
    closePop();
    var start = target.selectionStart, end = target.selectionEnd;
    var input = h("input", { type: "text", dir: "ltr", class: "math-input", placeholder: "F = m \\cdot a", spellcheck: "false" });
    var out = h("div", { class: "math-out", dir: "ltr" });
    function draw() {
      var v = input.value.trim();
      if (!v) { out.textContent = ""; return; }
      window.MathView.toString(v, true).then(function (html) { if (html) out.innerHTML = html; else out.textContent = v; });
    }
    input.addEventListener("input", draw);
    var snippets = [["a/b", "\\frac{a}{b}"], ["x²", "^{2}"], ["√x", "\\sqrt{x}"], ["π", "\\pi"], ["±", "\\pm"], ["≥", "\\geq"], ["≤", "\\leq"], ["×", "\\times"], ["÷", "\\div"], ["°", "^{\\circ}"]];
    var quick = h("div", { class: "math-quick" });
    snippets.forEach(function (s) {
      quick.appendChild(h("button", { type: "button", text: s[0], onclick: function () {
        var p = input.selectionStart || input.value.length;
        input.value = input.value.slice(0, p) + s[1] + input.value.slice(input.selectionEnd || p);
        input.focus(); draw();
      } }));
    });
    var insert = h("button", { type: "button", class: "btn primary sm", text: T.insert, onclick: function () {
      var v = input.value.trim();
      if (!v) { closePop(); return; }
      var snippet = "\\( " + v + " \\)";
      var val = target.value;
      target.value = val.slice(0, start) + snippet + val.slice(end);
      q.text = target.value;
      closePop();
      target.focus();
      target.setSelectionRange(start + snippet.length, start + snippet.length);
      touch(q);
    } });
    mathPop = h("div", { class: "pop math-pop", role: "dialog", "aria-label": T.fmt_math }, [
      h("b", { text: T.math_title }), input, out, quick,
      h("div", { class: "pop-foot" }, [h("small", { class: "muted", text: T.math_hint }), insert])
    ]);
    placePop(mathPop, anchor);
    input.focus();
  }
  function placePop(pop, anchor) {
    document.body.appendChild(pop);
    var r = anchor.getBoundingClientRect();
    var w = pop.offsetWidth;
    var left = Math.min(window.innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2));
    pop.style.top = (window.scrollY + r.bottom + 6) + "px";
    pop.style.left = (window.scrollX + left) + "px";
  }
  document.addEventListener("mousedown", function (e) {
    if (mathPop && !mathPop.contains(e.target) && !e.target.closest(".fmt.math")) closePop();
    if (picker && !picker.contains(e.target) && !e.target.closest("[data-picker]")) closePicker();
  });

  /* ---------- choices ---------- */
  function renderChoice(q) {
    var manual = !!q.manual_grade;
    var multi = q.type === "checkbox";
    var wrap = h("div", { class: "opt-editor" });
    var name = "pick-" + (q._k || (q._k = Math.random().toString(36).slice(2)));
    var head = h("div", { class: "opt-head" }, [h("b", { text: T.options_label }),
      manual ? null : h("small", { class: "muted", text: multi ? T.pick_correct_multi : T.pick_correct_hint })]);
    q.options.forEach(function (text, index) {
      var checked = !manual && (multi ? (q.correct || []).indexOf(index) !== -1 : q.correct === index);
      var line = h("div", { class: "opt-line" + (checked ? " correct" : "") });
      var pick = h("input", { type: multi ? "checkbox" : "radio", name: name, class: "pick", "aria-label": T.correct_answer + " " + (index + 1),
        onchange: function () {
          if (multi) {
            var set = (q.correct || []).filter(function (i) { return i !== index; });
            if (pick.checked) set.push(index);
            set.sort(function (a, b) { return a - b; });
            q.correct = set.length ? set : null;
          } else {
            q.correct = index;
          }
          touch(q); render();
        } });
      pick.checked = checked;
      var input = h("input", { type: "text", maxlength: "300", value: shown(text), placeholder: fmt(T.option_n, { n: index + 1 }),
        dir: q.extra.dir || "auto", "data-opt": index,
        oninput: function () { q.options[index] = input.value; touch(q); },
        onkeydown: function (event) {
          if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); addOption(q, index + 1); }
        },
        onpaste: function (event) {
          var text = (event.clipboardData || window.clipboardData).getData("text");
          var rows = String(text || "").split(/\r?\n/).map(cleanListItem).filter(Boolean);
          if (rows.length < 2) return;
          event.preventDefault();
          var before = JSON.parse(JSON.stringify({ o: q.options, c: q.correct, i: q.extra.option_images || null }));
          rows.forEach(function (row, k) {
            var at = index + k;
            if (at < q.options.length && (k === 0 || !String(q.options[at]).trim())) q.options[at] = row;
            else q.options.splice(at, 0, row);
          });
          q.options = q.options.slice(0, 30);
          q._undo = before;
          q._undoMsg = fmt(T.pasted_n, { n: rows.length });
          touch(q); render();
        } });
      var mark = manual ? h("span", { class: "opt-letter", "aria-hidden": "true", text: letter(index) }) : pick;
      line.appendChild(mark);
      line.appendChild(input);
      if (checked) line.appendChild(h("span", { class: "correct-tag", text: T.correct_tag }));
      if (q.type !== "dropdown") {
        var img = imgAt(q, "option_images", index);
        if (img) line.appendChild(h("span", { class: "opt-img" }, [h("img", { src: media(img), alt: "" }),
          h("button", { type: "button", class: "img-x", title: T.remove_image, html: icon("x", 12), onclick: function () { setImg(q, "option_images", index, "", q.options.length); touch(q); render(); } })]));
        var picker = fileInput("image/*", function (f) { upload(f, f.name, null, function (res) { setImg(q, "option_images", index, res.name, q.options.length); touch(q); render(); }); });
        line.appendChild(picker);
        line.appendChild(iconButton("image", T.option_image, function () { picker.click(); }, { extraClass: "ghosty" }));
      }
      line.appendChild(iconButton("x", T.remove, function () { removeOption(q, index); }, { danger: true, disabled: q.options.length <= 2, extraClass: "ghosty" }));
      wrap.appendChild(line);
    });
    var box = h("div", { class: "q-fields" }, [head, wrap]);
    if (q._undo) {
      box.appendChild(h("div", { class: "undo-bar" }, [h("span", { text: q._undoMsg }),
        h("button", { type: "button", class: "link", text: T.undo, onclick: function () {
          q.options = q._undo.o; q.correct = q._undo.c;
          if (q._undo.i) q.extra.option_images = q._undo.i; else delete q.extra.option_images;
          delete q._undo; touch(q); render();
        } })]));
      setTimeout(function () { if (q._undo) { delete q._undo; } }, 8000);
    }
    if (multi && !manual) {
      var scoring = h("div", { class: "seg wide", role: "radiogroup", "aria-label": T.cb_scoring });
      [[false, T.cb_all_or_nothing], [true, T.cb_partial]].forEach(function (m) {
        scoring.appendChild(h("button", { type: "button", class: !!q.partial === m[0] ? "on" : "", text: m[1],
          onclick: function () { q.partial = m[0]; touch(q); render(); } }));
      });
      var parts = [h("small", { class: "muted", text: T.cb_scoring }), scoring];
      if (q.partial) {
        var deduct = h("input", { type: "checkbox", onchange: function () {
          if (deduct.checked) delete q.extra.cb_deduct; else q.extra.cb_deduct = false;
          touch(q); render();
        } });
        deduct.checked = q.extra.cb_deduct !== false;
        parts.push(h("label", { class: "check switch", style: "margin:0" }, [deduct, h("span", { text: T.cb_deduct })]));
      }
      parts.push(h("small", { class: "cb-calc", text: cbCalc(q) }));
      box.appendChild(h("div", { class: "cb-scoring" }, parts));
    }
    var addBtn = chipButton("plus", T.add_option, function () { addOption(q, q.options.length); });
    addBtn.title = T.options_tip;
    var tools = h("div", { class: "opt-tools" }, [addBtn]);
    tools.appendChild(chipButton("spark", T.ai_distractors, function () { suggestDistractors(q, sugBox); }, "ai"));
    box.appendChild(tools);
    var sugBox = h("div", { class: "sug-box", hidden: true });
    box.appendChild(sugBox);
    return box;
  }

  /* one line that shows how a checkbox question is marked */
  function cbCalc(q) {
    var k = (q.correct || []).length, m = num(q.points);
    if (!k) return T.cb_calc_none;
    if (!q.partial) return fmt(T.cb_calc_all, { m: m, k: k });
    var e = num(m / k);
    return fmt(T.cb_calc_partial, { e: e, m: m }) + " " + (q.extra.cb_deduct === false ? T.cb_calc_no_deduct : fmt(T.cb_calc_deduct, { e: e }));
  }
  var LETTERS_AR = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي", "ك", "ل", "م", "ن", "س", "ع", "ف", "ص", "ق", "ر", "ش", "ت", "ث", "خ", "ذ", "ض", "ظ", "غ"];
  function letter(i) {
    if (document.documentElement.lang.slice(0, 2) === "ar") return LETTERS_AR[i] || String(i + 1);
    return i < 26 ? String.fromCharCode(65 + i) : String(i + 1);
  }

  function cleanListItem(line) {
    return String(line).replace(/^\s*(?:[-*•▪◦·]\s+|\(?[0-9٠-٩]+\s*[.)\-]\s*|\(?[a-zA-Zأ-ي][.)]\s+)/, "").trim();
  }

  function addOption(q, at) {
    if (q.options.length >= 30) return;
    q.options.splice(at, 0, "");
    if (Array.isArray(q.correct)) q.correct = q.correct.map(function (i) { return i >= at ? i + 1 : i; });
    else if (typeof q.correct === "number" && q.correct >= at) q.correct += 1;
    if (q.extra.option_images) q.extra.option_images.splice(at, 0, "");
    pendingFocus = { q: q, opt: at };
    touch(q); render();
  }

  function removeOption(q, index) {
    if (q.options.length <= 2) return;
    q.options.splice(index, 1);
    if (q.extra.option_images) { q.extra.option_images.splice(index, 1); if (!q.extra.option_images.some(Boolean)) delete q.extra.option_images; }
    if (Array.isArray(q.correct)) {
      q.correct = q.correct.filter(function (i) { return i !== index; }).map(function (i) { return i > index ? i - 1 : i; });
      if (!q.correct.length) q.correct = null;
    } else if (typeof q.correct === "number") {
      if (q.correct === index) q.correct = null;
      else if (q.correct > index) q.correct -= 1;
    }
    touch(q); render();
  }

  function suggestDistractors(q, box) {
    if (!data.aiEnabled) { toast(data.isAdmin ? T.ai_disabled_admin : T.ai_disabled); return; }
    box.hidden = false;
    box.textContent = T.ai_thinking;
    api(data.aiUrl, { json: { mode: "distractors", question: q.text, options: q.options, correct: q.correct } }).then(function (res) {
      box.textContent = "";
      if (!res.ok) { box.textContent = res.error || T.ai_failed; return; }
      if (!(res.options || []).length) { box.textContent = T.ai_none_new; return; }
      box.appendChild(h("b", { class: "sug-title", html: icon("spark", 13) + " " + esc(T.ai_suggested) }));
      var chips = h("div", { class: "sug-chips" });
      res.options.forEach(function (o) {
        chips.appendChild(h("button", { type: "button", class: "chip", text: "+ " + o, onclick: function (e) {
          var empty = q.options.indexOf("");
          if (empty !== -1) q.options[empty] = o; else if (q.options.length < 30) q.options.push(o);
          e.currentTarget.remove();
          touch(q); render();
        } }));
      });
      box.appendChild(chips);
    }).catch(function () { box.textContent = T.ai_failed; });
  }

  /* ---------- true / false: both buttons always visible ---------- */
  function renderTrueFalseMulti(q) {
    var o = q.options, manual = !!q.manual_grade;
    tfSync(q);
    var list = h("div", { class: "tfm-list" });
    o.items.forEach(function (text, i) {
      var mark = !manual && q.correct ? q.correct[i] : null;
      var row = h("div", { class: "tfm-row" + (mark ? " has-" + mark : "") });
      row.appendChild(h("span", { class: "pair-num", text: String(i + 1) }));
      var input = h("textarea", { rows: "1", maxlength: "500", class: "tfm-text", dir: q.extra.dir || "auto", "data-opt": i,
        placeholder: fmt(T.tf_statement_n, { n: i + 1 }), "aria-label": fmt(T.tf_statement_n, { n: i + 1 }),
        oninput: function () { o.items[i] = input.value; touch(q); },
        onkeydown: function (e) {
          if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); tfAdd(q, i + 1); }
        },
        onpaste: function (e) {
          var t = (e.clipboardData || window.clipboardData).getData("text");
          if (window.App.fixPdfArabic) t = window.App.fixPdfArabic(t);
          var rowsIn = String(t || "").split(/\r?\n/).map(cleanListItem).filter(Boolean);
          if (rowsIn.length < 2) return;
          e.preventDefault();
          rowsIn.forEach(function (r, k) {
            var at = i + k;
            if (at < o.items.length && (k === 0 || !String(o.items[at]).trim())) o.items[at] = r;
            else { o.items.splice(at, 0, r); o.item_points.splice(at, 0, 1); if (Array.isArray(q.correct)) q.correct.splice(at, 0, null); }
          });
          o.items = o.items.slice(0, 40);
          touch(q); render();
        } });
      input.value = text;
      row.appendChild(input);
      if (!manual) {
        var picks = h("span", { class: "tfm-picks", role: "radiogroup", "aria-label": T.correct_answer });
        [["true", "✓", "yes"], ["false", "✗", "no"]].forEach(function (m) {
          picks.appendChild(h("button", { type: "button", class: "tfm-pick " + m[2] + (mark === m[0] ? " on" : ""), text: m[1], title: T[m[0]],
            "aria-label": T[m[0]], "aria-pressed": mark === m[0] ? "true" : "false",
            onclick: function () { q.correct[i] = m[0]; touch(q); render(); } }));
        });
        row.appendChild(picks);
        var val = h("span", { class: "step-val", text: String(num(o.item_points[i])) });
        row.appendChild(h("span", { class: "stepper", title: T.points }, [
          h("button", { type: "button", html: icon("minus", 12), title: "−", onclick: function () {
            o.item_points[i] = Math.max(0, num((parseFloat(o.item_points[i]) || 0) - 0.5)); tfSync(q); touch(q); render(); } }), val,
          h("button", { type: "button", html: icon("plus", 12), title: "+", onclick: function () {
            o.item_points[i] = num((parseFloat(o.item_points[i]) || 0) + 0.5); tfSync(q); touch(q); render(); } })]));
      }
      row.appendChild(h("button", { type: "button", class: "tfm-del", title: T.remove, "aria-label": T.remove + " " + (i + 1),
        disabled: o.items.length <= 1, html: icon("trash", 16),
        onclick: function () {
          if (o.items.length <= 1) return;
          o.items.splice(i, 1); o.item_points.splice(i, 1); if (Array.isArray(q.correct)) q.correct.splice(i, 1);
          touch(q); render();
        } }));
      list.appendChild(row);
    });
    var parts = [h("div", { class: "opt-head" }, [h("b", { text: T.tf_statements }), manual ? null : h("small", { class: "muted", text: T.tf_total_auto })]), list,
      h("div", { class: "opt-tools" }, [chipButton("plus", T.tf_add_statement, function () { tfAdd(q, o.items.length); })]),
      h("p", { class: "q-hint", text: manual ? T.tf_manual_hint : T.tf_pick_each })];
    return h("div", { class: "q-fields" }, parts);
  }
  function tfAdd(q, at) {
    var o = q.options;
    if (o.items.length >= 40) return;
    o.items.splice(at, 0, ""); o.item_points.splice(at, 0, 1);
    if (Array.isArray(q.correct)) q.correct.splice(at, 0, null);
    pendingFocus = { q: q, opt: at };
    touch(q); render();
  }

  function renderTrueFalse(q) {
    if (tfMulti(q)) return renderTrueFalseMulti(q);
    var manual = !!q.manual_grade;
    var box = h("div", { class: "tf-edit" + (manual ? " manual" : "") }, manual ? [] : [h("small", { class: "muted", text: T.tf_pick_hint })]);
    var row = h("div", { class: "tf-row", role: manual ? null : "radiogroup", "aria-label": T.correct_answer });
    ["true", "false"].forEach(function (value) {
      var on = !manual && q.correct === value;
      if (manual) { row.appendChild(h("span", { class: "tf-btn plain", text: T[value] })); return; }
      row.appendChild(h("button", { type: "button", class: "tf-btn" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false",
        html: (on ? icon("check", 16) + " " : "") + esc(T[value]),
        onclick: function () { q.correct = value; touch(q); render(); } }));
    });
    box.appendChild(row);
    if (manual) box.appendChild(h("small", { class: "muted", text: T.tf_manual_hint }));
    /* an older one-statement card can become a list of statements */
    box.appendChild(h("div", { class: "opt-tools" }, [chipButton("plus", T.tf_make_multi, function () {
      var first = String(q.text || "").trim();
      q.options = { items: [first, ""], item_points: [num(q.points) || 1, 1] };
      q.correct = q.manual_grade ? null : [q.correct === "true" || q.correct === "false" ? q.correct : null, null];
      q.text = T.tf_instruction_default;
      pendingFocus = { q: q, opt: 1 };
      touch(q); render();
    })]));
    return box;
  }

  function renderShort(q) {
    var area = h("textarea", { rows: "3", placeholder: T.accepted_answers, dir: q.extra.dir || "auto",
      oninput: function () {
        var l = lines(area.value);
        q.correct = l.length ? l : null;
        touch(q);
      } });
    area.value = Array.isArray(q.correct) ? q.correct.join("\n") : "";
    return h("div", { class: "q-fields key-only" }, [
      h("label", { class: "field" }, [h("span", { text: T.accepted_answers }), area, h("small", { class: "muted", text: T.accepted_answers_hint })])]);
  }

  function renderNumber(q) {
    var value = numInput({ value: q.correct && q.correct.value !== undefined ? q.correct.value : "" });
    var tol = numInput({ value: q.correct && q.correct.tolerance ? q.correct.tolerance : "" });
    function sync() {
      var v = numVal(value);
      if (value.value.trim() === "" || isNaN(v)) q.correct = null;
      else q.correct = { value: v, tolerance: Math.abs(numVal(tol) || 0) };
      touch(q);
    }
    value.addEventListener("input", sync);
    tol.addEventListener("input", sync);
    return h("div", { class: "row-2 key-only" }, [
      h("label", { class: "field" }, [h("span", { text: T.numeric_answer }), value]),
      h("label", { class: "field" }, [h("span", { text: T.tolerance }), tol])]);
  }

  function lines(text) { return String(text || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean); }

  /* ---------- scale: stars or numbers with a live preview ---------- */
  function renderScale(q) {
    var o = q.options;
    var style = o.style === "stars" ? "stars" : "numbers";
    var seg = h("div", { class: "seg" });
    [["stars", T.scale_stars], ["numbers", T.scale_numbers]].forEach(function (s) {
      seg.appendChild(h("button", { type: "button", class: style === s[0] ? "on" : "", text: s[1], onclick: function () { o.style = s[0]; touch(q); render(); } }));
    });
    var max = h("select", { onchange: function () { o.max = parseInt(max.value, 10); touch(q); render(); } });
    for (var n = 3; n <= 10; n += 1) {
      var opt = h("option", { value: String(n), text: String(n) });
      if (o.max === n) opt.selected = true;
      max.appendChild(opt);
    }
    var lo = h("input", { type: "text", maxlength: "60", value: o.min_label || "", placeholder: T.scale_min_label, oninput: function () { o.min_label = lo.value; touch(q); } });
    var hi = h("input", { type: "text", maxlength: "60", value: o.max_label || "", placeholder: T.scale_max_label, oninput: function () { o.max_label = hi.value; touch(q); } });
    var pv = h("div", { class: "scale-preview", html: scaleHtml(o, Math.ceil(o.max / 2)) });
    return h("div", { class: "q-fields" }, [
      h("div", { class: "q-row" }, [seg, h("label", { class: "pts" }, [h("span", { text: T.scale_size }), max])]),
      h("div", { class: "row-2" }, [hi, lo]),
      h("div", { class: "live-box" }, [h("small", { class: "muted", text: style === "stars" ? T.preview_stars : T.preview_numbers }), pv])]);
  }

  function scaleHtml(o, value) {
    var out = '<div class="scale-pv ' + (o.style === "stars" ? "stars" : "nums") + '">';
    for (var i = 1; i <= (o.max || 5); i += 1) {
      out += o.style === "stars"
        ? '<span class="st' + (i <= value ? " on" : "") + '">' + icon("star", 22) + "</span>"
        : '<span class="nb' + (i === value ? " on" : "") + '">' + i + "</span>";
    }
    out += "</div>";
    if (o.min_label || o.max_label) out += '<div class="scale-labels"><span>' + esc(o.min_label) + "</span><span>" + esc(o.max_label) + "</span></div>";
    return out;
  }

  /* ---------- matching (text and/or picture on both sides) ---------- */
  function renderMatch(q) {
    var wrap = h("div", { class: "pair-editor" });
    wrap.appendChild(h("div", { class: "pair-line pair-head" }, [h("span", { class: "muted small", text: T.match_left }), h("span"), h("span", { class: "muted small", text: T.match_right }), h("span")]));
    var size = q.options.pairs.length;
    q.options.pairs.forEach(function (pair, index) {
      function side(k, key, ph) {
        var cell = h("div", { class: "pair-cell" });
        var img = imgAt(q, key, index);
        var picker = fileInput("image/*", function (f) { upload(f, f.name, null, function (res) { setImg(q, key, index, res.name, size); touch(q); render(); }); });
        if (img) cell.appendChild(h("span", { class: "opt-img" }, [h("img", { src: media(img), alt: "" }),
          h("button", { type: "button", class: "img-x", title: T.remove_image, html: icon("x", 12), onclick: function () { setImg(q, key, index, "", size); touch(q); render(); } })]));
        else cell.appendChild(iconButton("image", T.option_image, function () { picker.click(); }, { extraClass: "ghosty" }));
        var input = h("input", { type: "text", maxlength: "300", value: shown(pair[k]), placeholder: ph, dir: q.extra.dir || "auto", "data-opt": k ? null : index,
          oninput: function () { pair[k] = input.value; touch(q); },
          onkeydown: function (event) { if (k && event.key === "Enter" && !event.isComposing) { event.preventDefault(); addPair(q); } } });
        cell.appendChild(input);
        cell.appendChild(picker);
        return cell;
      }
      var del = iconButton("x", T.remove, function () {
        if (q.options.pairs.length <= 1) return;
        q.options.pairs.splice(index, 1);
        ["left_images", "right_images"].forEach(function (key) { if (q.extra[key]) { q.extra[key].splice(index, 1); if (!q.extra[key].some(Boolean)) delete q.extra[key]; } });
        touch(q); render();
      }, { danger: true, disabled: q.options.pairs.length <= 1, extraClass: "ghosty" });
      wrap.appendChild(h("div", { class: "pair-line" }, [h("span", { class: "pair-num", text: String(index + 1) }), side(0, "left_images", T.text_or_image),
        h("span", { class: "pair-arrow", text: "⟷" }), side(1, "right_images", T.text_or_image), del]));
    });
    var wrongs = q.options.distractors = (q.options.distractors || []).filter(function (x) { return String(x).trim(); });
    var chips = h("div", { class: "wrong-chips" });
    wrongs.forEach(function (w, i) {
      chips.appendChild(h("span", { class: "wrong-chip" }, [h("span", { text: w }),
        h("button", { type: "button", html: icon("x", 11), title: T.remove, "aria-label": T.remove, onclick: function () { wrongs.splice(i, 1); touch(q); render(); } })]));
    });
    var addWrong = h("button", { type: "button", class: "chip wrong-add", html: icon("plus", 13) + "<span></span>", onclick: function () {
      var inp = h("input", { type: "text", class: "wrong-input", maxlength: "300", placeholder: T.match_wrong_ph, dir: q.extra.dir || "auto",
        onkeydown: function (e) {
          if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); inp.blur(); }
          if (e.key === "Escape") { inp.value = ""; inp.blur(); }
        },
        onblur: function () {
          var v = inp.value.trim();
          if (v && wrongs.length < 20) { wrongs.push(v); touch(q); }
          render();
        } });
      addWrong.replaceWith(inp);
      inp.focus();
    } });
    addWrong.querySelector("span").textContent = T.match_wrong_add;
    if (wrongs.length >= 20) addWrong.disabled = true;
    chips.appendChild(addWrong);
    return h("div", { class: "q-fields" }, [wrap,
      h("div", { class: "opt-tools" }, [chipButton("plus", T.add_pair, function () { addPair(q); })]),
      chips,
      h("p", { class: "q-hint", text: T.match_hint_one })]);
  }
  function addPair(q) {
    if (q.options.pairs.length >= 40) return;
    q.options.pairs.push(["", ""]);
    pendingFocus = { q: q, opt: q.options.pairs.length - 1 };
    touch(q); render();
  }

  /* ---------- fill in the blanks ---------- */
  var floatBtn = h("button", { type: "button", class: "float-blank", hidden: true, html: icon("blank", 14) + "<span></span>" });
  floatBtn.querySelector("span").textContent = T.make_blank;
  floatBtn.addEventListener("mousedown", function (e) { e.preventDefault(); });
  document.body.appendChild(floatBtn);
  var fillCtx = null; /* {q, ed, range, api} of the editor holding the selection */

  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    var node = sel.anchorNode;
    var ed = node && (node.nodeType === 1 ? node : node.parentNode).closest && (node.nodeType === 1 ? node : node.parentNode).closest(".fill-ed");
    if (!ed || !ed._fill) { floatBtn.hidden = true; return; }
    var range = sel.getRangeAt(0);
    ed._fill.range = range.cloneRange();
    fillCtx = ed._fill;
    var usable = !sel.isCollapsed && range.toString().trim() && !rangeHasChip(range);
    if (ed._fill.makeBtn) ed._fill.makeBtn.disabled = !usable;
    if (usable && !ed._fill.q.manual_grade) {
      var r = range.getBoundingClientRect();
      floatBtn.hidden = false;
      floatBtn.style.top = (window.scrollY + r.top - floatBtn.offsetHeight - 8) + "px";
      floatBtn.style.left = (window.scrollX + r.left + r.width / 2 - floatBtn.offsetWidth / 2) + "px";
    } else {
      floatBtn.hidden = true;
    }
  });
  floatBtn.addEventListener("click", function () { if (fillCtx) fillCtx.makeBlank(); floatBtn.hidden = true; });

  function rangeHasChip(range) {
    var frag = range.cloneContents();
    return !!(frag.querySelector && frag.querySelector(".fill-chip")) ||
      !!(range.startContainer.parentNode && range.startContainer.parentNode.closest && range.startContainer.parentNode.closest(".fill-chip"));
  }

  function syncFillPoints(q) {
    var count = blanksOf(q).length;
    var bp = q.options.blank_points;
    if (!Array.isArray(bp)) return;
    if (bp.length !== count) {
      bp = bp.slice(0, count);
      while (bp.length < count) bp.push(1);
      q.options.blank_points = bp;
    }
    if (!q.manual_grade && count) q.points = num(bp.reduce(function (a, b) { return a + (parseFloat(b) || 0); }, 0));
  }
  function blankShare(q, i) {
    var count = blanksOf(q).length || 1;
    if (Array.isArray(q.options.blank_points) && q.options.blank_points.length === count) return num(q.options.blank_points[i]);
    return num((parseFloat(q.points) || 0) / count);
  }
  function materialize(q) {
    var count = blanksOf(q).length;
    if (!Array.isArray(q.options.blank_points) || q.options.blank_points.length !== count) {
      var share = num((parseFloat(q.points) || count) / (count || 1)) || 1;
      q.options.blank_points = [];
      for (var i = 0; i < count; i += 1) q.options.blank_points.push(share);
    }
  }

  /* a blank holding a number or an English word is written left-to-right inside an Arabic sentence */
  function guessDir(ans) {
    var w = altsOf(ans)[0] || "";
    if (!w) return "";
    if (/^[\d٠-٩۰-۹.,٫\/\-+×÷=%\s]+$/.test(w)) return "num";
    if (/[A-Za-z]/.test(w) && !/[\u0600-\u06FF]/.test(w)) return "ltr";
    return "";
  }
  function applyDir(input, d) {
    if (d) input.setAttribute("dir", d === "rtl" ? "rtl" : "ltr"); else input.setAttribute("dir", (input.getAttribute("data-qdir") || "auto"));
    if (d === "num") input.setAttribute("inputmode", "decimal"); else input.removeAttribute("inputmode");
  }

  /* direction of the fill-in sentence: the teacher's choice, else its words, else the question text
     ("1- [ ]  2- [ ]" has no words and follows the Arabic question), else the interface language */
  function textDir(t) {
    var m = String(t || "").match(/[A-Za-z\u0600-\u06FF]/);
    return m ? (/[A-Za-z]/.test(m[0]) ? "ltr" : "rtl") : "";
  }
  function fillDir(q) {
    if (q.extra.dir === "rtl" || q.extra.dir === "ltr") return q.extra.dir;
    var words = String((q.options && q.options.template) || "").replace(BLANK_RE, " ");
    return textDir(words) || textDir(q.text) || (document.documentElement.lang.slice(0, 2) === "ar" ? "rtl" : "ltr");
  }

  function renderFill(q) {
    var o = q.options;
    var manual = !!q.manual_grade;
    var ed = h("div", { class: "fill-ed" + (manual ? " manual" : ""), contenteditable: "true", dir: fillDir(q), spellcheck: "false",
      role: "textbox", "aria-multiline": "true", "aria-label": T.fill_template, "data-placeholder": manual ? T.fill_ph_manual : T.fill_ph_auto });
    var ctx = { q: q, ed: ed, range: null };
    ed._fill = ctx;
    /* direction of the whole sentence (same setting as the ع ← / EN → buttons of the question text) */
    var sentenceDir = h("div", { class: "seg dir-seg", role: "radiogroup", title: T.sentence_dir, "aria-label": T.sentence_dir });
    [["", T.blank_dir_auto], ["rtl", T.blank_dir_ar], ["ltr", T.blank_dir_en]].forEach(function (x) {
      var on = (q.extra.dir || "") === x[0];
      sentenceDir.appendChild(h("button", { type: "button", class: on ? "on" : "", role: "radio", "aria-checked": on ? "true" : "false", text: x[1],
        onmousedown: function (e) { e.preventDefault(); },
        onclick: function () { if (x[0]) q.extra.dir = x[0]; else delete q.extra.dir; touch(q); render(); } }));
    });

    function chip(ans, d) {
      if (d === undefined) d = guessDir(ans);
      var c = h("span", { class: "fill-chip", contenteditable: "false", "data-ans": ans, "data-dir": d || "" });
      if (d) c.setAttribute("dir", d === "rtl" ? "rtl" : "ltr");
      c.appendChild(h("span", { class: "fc-label" }));
      c.appendChild(h("button", { type: "button", class: "fc-x", tabindex: "-1", title: T.unblank, html: icon("x", 11),
        onmousedown: function (e) { e.preventDefault(); },
        onclick: function () {
          var first = altsOf(c.getAttribute("data-ans"))[0] || "";
          c.replaceWith(document.createTextNode(first));
          changed(true);
        } }));
      return c;
    }
    function relabel() {
      Array.prototype.forEach.call(ed.querySelectorAll(".fill-chip"), function (c, i) {
        var alts = altsOf(c.getAttribute("data-ans"));
        var label = c.querySelector(".fc-label");
        c.classList.toggle("empty", !alts.length);
        if (manual || !alts.length) label.textContent = fmt(T.blank_n_label, { n: window.Digits ? window.Digits.local(String(i + 1)) : i + 1 });
        else label.textContent = alts[0];
      });
    }
    function build() {
      ed.textContent = "";
      var text = o.template || "", last = 0, m;
      function addText(s) {
        s.split("\n").forEach(function (part, i) {
          if (i) ed.appendChild(h("br"));
          if (part) ed.appendChild(document.createTextNode(part));
        });
      }
      var dirs = Array.isArray(o.blank_dirs) ? o.blank_dirs : [], k = 0;
      BLANK_RE.lastIndex = 0;
      while ((m = BLANK_RE.exec(text))) {
        addText(text.slice(last, m.index));
        ed.appendChild(chip(m[1].trim() ? m[1] : "", dirs[k] || ""));
        k += 1;
        last = m.index + m[0].length;
      }
      addText(text.slice(last));
      relabel();
    }
    function serialize() {
      var out = "", dirs = [];
      function walk(node) {
        Array.prototype.forEach.call(node.childNodes, function (child) {
          if (child.nodeType === 3) out += child.nodeValue.replace(/ /g, " ");
          else if (child.nodeType === 1) {
            if (child.classList.contains("fill-chip")) {
              dirs.push(child.getAttribute("data-dir") || "");
              var ans = altsOf(child.getAttribute("data-ans")).join("|");
              out += "[" + (ans || " ") + "]";
            } else if (child.tagName === "BR") out += "\n";
            else {
              if ((child.tagName === "DIV" || child.tagName === "P") && out && out.slice(-1) !== "\n") out += "\n";
              walk(child);
            }
          }
        });
      }
      walk(ed);
      /* writing direction of each blank travels with its chip */
      if (dirs.some(Boolean)) o.blank_dirs = dirs; else delete o.blank_dirs;
      return out.replace(/\n+$/, "");
    }
    function changed(rebuildRows) {
      o.template = serialize();
      ed.setAttribute("dir", fillDir(q));
      relabel();
      if (!manual) { syncFillPoints(q); if (q._pointsInput) setNumInput(q._pointsInput, q.points); }
      if (rebuildRows) rows();
      livePrev();
      touch(q);
    }
    ed.addEventListener("input", function () {
      var before = blanksOf(q).length;
      o.template = serialize();
      changed(blanksOf(q).length !== before);
    });
    ed.addEventListener("blur", function () {
      if (/\[[^\[\]\n]+\]/.test(Array.prototype.map.call(ed.childNodes, function (n) { return n.nodeType === 3 ? n.nodeValue : ""; }).join(""))) { build(); rows(); }
    });
    ed.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); document.execCommand("insertLineBreak"); }
    });
    ed.addEventListener("paste", function (e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text");
      if (window.App.fixPdfArabic) text = window.App.fixPdfArabic(text);
      document.execCommand("insertText", false, text);
    });
    ed.addEventListener("click", function (e) {
      var c = e.target.closest(".fill-chip");
      if (!c || manual) return;
      var i = Array.prototype.indexOf.call(ed.querySelectorAll(".fill-chip"), c);
      var input = rowsBox.querySelector('[data-blank="' + i + '"]');
      if (input) input.focus();
    });

    function insertNode(range, node, word) {
      range.deleteContents();
      var lead = word && /^\s/.test(word) ? " " : "", trail = word && /\s$/.test(word) ? " " : "";
      if (trail) range.insertNode(document.createTextNode(trail));
      range.insertNode(node);
      if (lead) range.insertNode(document.createTextNode(lead));
      var sel = window.getSelection();
      var after = document.createRange();
      after.setStartAfter(node);
      after.collapse(true);
      sel.removeAllRanges();
      sel.addRange(after);
    }
    ctx.makeBlank = function () {
      var range = ctx.range;
      if (!range || !ed.contains(range.commonAncestorContainer)) return;
      var raw = range.toString();
      var word = raw.trim();
      if (!word || rangeHasChip(range)) return;
      insertNode(range, chip(word.replace(/[\[\]|]/g, "")), raw);
      changed(true);
      floatBtn.hidden = true;
    };
    ctx.insertBlank = function () {
      var range = ctx.range && ed.contains(ctx.range.commonAncestorContainer) ? ctx.range : null;
      if (!range) {
        range = document.createRange();
        range.selectNodeContents(ed);
        range.collapse(false);
      } else {
        range.collapse(false);
      }
      var node = chip("");
      range.insertNode(document.createTextNode(" "));
      range.insertNode(node);
      var sel = window.getSelection();
      var after = document.createRange();
      after.setStartAfter(node.nextSibling || node);
      after.collapse(true);
      sel.removeAllRanges();
      sel.addRange(after);
      ctx.range = after.cloneRange();
      changed(true);
    };

    var action;
    if (manual) {
      action = h("button", { type: "button", class: "btn outline sm blank-btn", html: icon("blank", 14) + "<span></span>",
        onmousedown: function (e) { e.preventDefault(); }, onclick: function () { ctx.insertBlank(); } });
      action.querySelector("span").textContent = T.insert_blank;
    } else {
      action = h("button", { type: "button", class: "btn outline sm blank-btn", disabled: true, html: icon("blank", 14) + "<span></span>",
        onmousedown: function (e) { e.preventDefault(); }, onclick: function () { ctx.makeBlank(); } });
      action.querySelector("span").textContent = T.make_blank;
      ctx.makeBtn = action;
    }
    var edBox = h("div", { class: "fill-box" }, [
      h("div", { class: "fill-bar" }, [action, h("small", { class: "muted", text: manual ? T.insert_blank_hint : T.make_blank_hint }), h("span", { class: "spacer" }), sentenceDir]), ed]);

    var rowsBox = h("div", { class: "blank-rows" });
    function dirSelect(i) {
      var cur = (o.blank_dirs || [])[i] || "";
      var sel = h("select", { class: "blank-dir", "aria-label": T.blank_dir, title: T.blank_dir, onchange: function () {
        var c = ed.querySelectorAll(".fill-chip")[i];
        if (!c) return;
        c.setAttribute("data-dir", sel.value);
        if (sel.value) c.setAttribute("dir", sel.value === "rtl" ? "rtl" : "ltr"); else c.removeAttribute("dir");
        changed(false);
        var a = rowsBox.querySelector('[data-blank="' + i + '"]');
        if (a) applyDir(a, sel.value);
      } });
      [["", T.blank_dir_auto], ["rtl", T.blank_dir_ar], ["ltr", T.blank_dir_en], ["num", T.blank_dir_num]].forEach(function (x) {
        var op = h("option", { value: x[0], text: x[1] });
        if (x[0] === cur) op.selected = true;
        sel.appendChild(op);
      });
      return sel;
    }
    function rows() {
      rowsBox.textContent = "";
      var blanks = blanksOf(q);
      if (!blanks.length) return;
      if (manual) {  /* manual: only the writing direction of each blank */
        rowsBox.appendChild(h("div", { class: "blank-rows-head" }, [h("b", { text: T.blank_dir })]));
        var line = h("div", { class: "blank-dirs" });
        blanks.forEach(function (b, i) { line.appendChild(h("span", { class: "blank-dir-item" }, [h("span", { class: "bn", text: String(i + 1) }), dirSelect(i)])); });
        rowsBox.appendChild(line);
        return;
      }
      rowsBox.appendChild(h("div", { class: "blank-rows-head" }, [h("b", { text: T.blank_rows_title }),
        h("button", { type: "button", class: "link", text: T.distribute_equally, onclick: function () {
          var count = blanks.length, total = parseFloat(q.points) || count;
          var share = num(total / count);
          o.blank_points = blanks.map(function () { return share; });
          syncFillPoints(q); if (q._pointsInput) setNumInput(q._pointsInput, q.points);
          rows(); touch(q);
        } })]));
      var chips = ed.querySelectorAll(".fill-chip");
      blanks.forEach(function (raw, i) {
        var cur = altsOf(raw);  /* [answer, alternative, ...] */
        function setAlts() {
          var c = chips[i];
          if (c) c.setAttribute("data-ans", cur.filter(function (x) { return x; }).join("|"));
          o.template = serialize(); relabel(); livePrev(); touch(q);
        }
        var ans = h("input", { type: "text", class: "blank-ans" + (cur[0] ? "" : " missing"), value: cur[0] || "", placeholder: T.blank_answer_ph,
          dir: q.extra.dir || "auto", "data-blank": i,
          oninput: function () {
            cur[0] = ans.value.replace(/[\[\]|]/g, "").trim();
            ans.classList.toggle("missing", !cur[0]);
            setAlts();
          } });
        var altBox = h("span", { class: "alt-box" });
        cur.slice(1).forEach(function (a, k) {
          altBox.appendChild(h("span", { class: "alt-chip" }, [h("span", { text: a }), h("button", { type: "button", html: icon("x", 10), title: T.remove, onclick: function () {
            cur.splice(k + 1, 1); setAlts(); rows();
          } })]));
        });
        var addAlt = h("button", { type: "button", class: "link", text: "+ " + T.alt_answer, onclick: function () {
          var inp = h("input", { type: "text", class: "alt-input", placeholder: T.alt_answer, dir: q.extra.dir || "auto", onkeydown: function (e) {
            if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
          }, onblur: function () {
            var v = inp.value.replace(/[\[\]|]/g, "").trim();
            if (v) { if (!cur.length) cur.push(v); else cur.push(v); setAlts(); }
            rows();
          } });
          addAlt.replaceWith(inp);
          inp.focus();
        } });
        var val = h("span", { class: "step-val", text: String(blankShare(q, i)) });
        function step(d) {
          materialize(q);
          o.blank_points[i] = Math.max(0, num((parseFloat(o.blank_points[i]) || 0) + d));
          syncFillPoints(q); if (q._pointsInput) setNumInput(q._pointsInput, q.points);
          val.textContent = String(num(o.blank_points[i]));
          totalEl.textContent = String(num(q.points));
          touch(q);
        }
        var stepper = h("span", { class: "stepper" }, [
          h("button", { type: "button", html: icon("minus", 12), title: "−", onclick: function () { step(-0.5); } }), val,
          h("button", { type: "button", html: icon("plus", 12), title: "+", onclick: function () { step(0.5); } })]);
        applyDir(ans, (o.blank_dirs || [])[i]);
        rowsBox.appendChild(h("div", { class: "blank-row" }, [h("span", { class: "bn", text: String(i + 1) }), ans, altBox, addAlt, h("span", { class: "spacer" }), dirSelect(i), stepper]));
      });
      var totalEl = h("b", { text: String(num(q.points)) });
      rowsBox.appendChild(h("div", { class: "blank-total" }, [h("span", { text: T.fill_points_auto }), totalEl]));
    }

    var bank = h("input", { type: "checkbox", onchange: function () { o.bank = bank.checked; q._bankTouched = true; touch(q); render(); } });
    bank.checked = !!o.bank;
    var bankRow = h("label", { class: "check switch bank-toggle", style: "margin:0" }, [bank, h("span", { text: T.word_bank }),
      h("small", { class: "muted", text: manual ? T.word_bank_manual_note : T.word_bank_auto_note })]);
    var words = h("input", { type: "text", maxlength: "500", placeholder: manual ? T.bank_words_ph : T.distractors, dir: q.extra.dir || "auto",
      value: (o.distractors || []).join("، "),
      oninput: function () { o.distractors = words.value.split(/[,،]/).map(function (s) { return s.trim(); }).filter(Boolean); livePrev(); touch(q); } });

    function livePrev() { schedulePreview(); }

    build();
    rows();
    livePrev();
    var parts = [edBox, rowsBox, bankRow];
    if (o.bank) parts.push(h("label", { class: "field" }, [h("span", { text: manual ? T.bank_words : T.distractors }), words]));
    if (manual) {
      parts.push(h("p", { class: "q-hint warn", text: T.manual_no_key }));
      parts.push(h("p", { class: "q-hint partial-line", text: fmt(T.partial_line, { n: num(q.points) }) }));
    }
    return h("div", { class: "q-fields" }, parts);
  }

  function fillPreviewHtml(q) {
    var o = q.options || {};
    var text = o.template || "";
    var html = "", last = 0, m;
    BLANK_RE.lastIndex = 0;
    while ((m = BLANK_RE.exec(text))) {
      html += rich(text.slice(last, m.index)) + '<span class="pv-blank"></span>';
      last = m.index + m[0].length;
    }
    html += rich(text.slice(last));
    var words = [];
    if (o.bank) {
      blanksOf(q).forEach(function (b) { var a = altsOf(b)[0]; if (a) words.push(a); });
      (o.distractors || []).forEach(function (w) { if (w) words.push(w); });
      words = words.filter(function (w, i) { return words.indexOf(w) === i; }).sort();
    }
    var bankHtml = words.length ? '<div class="pv-bank">' + words.map(function (w) { return "<span>" + esc(w) + "</span>"; }).join("") + "</div>" : "";
    return '<div class="pv-fill" dir="' + fillDir(q) + '">' + html + "</div>" + bankHtml;
  }

  function renderOrder(q) {
    var pv = h("div", { class: "chunk-preview", dir: q.extra.dir || "auto" });
    function refresh() {
      pv.textContent = "";
      var first = (q.correct || [])[0] || "";
      var chunks = first.indexOf("/") !== -1 ? first.split("/") : first.split(/\s+/);
      chunks.map(function (c) { return c.trim(); }).filter(Boolean).forEach(function (c) { pv.appendChild(h("span", { class: "chunk", text: c })); });
      pv.hidden = !pv.children.length;
    }
    var area = h("textarea", { rows: "2", dir: q.extra.dir || "auto", placeholder: T.order_answer,
      oninput: function () { var l = lines(area.value); q.correct = l.length ? l : null; refresh(); touch(q); } });
    area.value = Array.isArray(q.correct) ? q.correct.join("\n") : "";
    refresh();
    return h("div", { class: "q-fields" }, [
      h("label", { class: "field" }, [h("span", { text: T.order_answer }), area, h("small", { class: "muted", text: T.order_answer_hint })]),
      h("div", {}, [h("small", { class: "muted", text: T.order_preview }), pv])]);
  }

  function renderDraw(q) {
    var linesBox = h("input", { type: "checkbox", onchange: function () { q.options.lines = linesBox.checked; touch(q); } });
    linesBox.checked = q.options.lines !== false;
    var sizes = [[260, T.draw_small], [380, T.draw_medium], [560, T.draw_large]];
    var cur = q.options.height || 380;
    if (sizes.every(function (z) { return z[0] !== cur; })) sizes.push([cur, T.draw_xl]);  /* keep an older custom size */
    var hSeg = h("div", { class: "seg size-seg", role: "radiogroup", "aria-label": T.draw_height });
    sizes.forEach(function (z) {
      hSeg.appendChild(h("button", { type: "button", class: cur === z[0] ? "on" : "", role: "radio", "aria-checked": cur === z[0] ? "true" : "false", text: z[1],
        onclick: function () { q.options.height = z[0]; touch(q); render(); } }));
    });
    /* draw on the question picture: circle, tick, join with lines, write in the boxes */
    var onImg = !!q.options.on_image;
    var imgBox = h("input", { type: "checkbox", onchange: function () {
      if (imgBox.checked) q.options.on_image = true; else delete q.options.on_image;
      touch(q); render();
    } });
    imgBox.checked = onImg;
    var picker = fileInput("image/*", function (f) { upload(f, f.name, null, function (res) { q.image = res.name; touch(q); render(); }); });
    var imgRow = h("div", { class: "draw-img-opt" + (onImg ? " on" : "") }, [
      h("label", { class: "check switch", style: "margin:0" }, [imgBox, h("span", { text: T.draw_on_image })]),
      h("small", { class: "muted", text: T.draw_on_image_note })]);
    if (onImg) {
      if (q.image) imgRow.appendChild(h("div", { class: "draw-img-thumb" }, [h("img", { src: media(q.image), alt: "" }),
        chipButton("image", T.change_image, function () { picker.click(); })]));
      else imgRow.appendChild(h("div", { class: "draw-img-empty" }, [h("span", { html: icon("alert", 14) }), h("span", { text: T.draw_need_image }),
        chipButton("image", T.add_image, function () { picker.click(); })]));
      imgRow.appendChild(picker);
    }
    var parts = [imgRow];
    if (!onImg) parts.push(h("div", { class: "q-row" }, [h("span", { class: "gm-label", text: T.draw_height }), hSeg, h("span", { class: "spacer" }),
      h("label", { class: "check", style: "margin:0" }, [linesBox, h("span", { text: T.draw_lines })])]));
    parts.push(h("p", { class: "q-hint", text: onImg ? T.draw_on_image_hint : T.draw_note }));
    return h("div", { class: "q-fields" }, parts);
  }

  /* ================= type picker (add between questions) ================= */
  var picker = null;
  function closePicker() { if (picker) { picker.remove(); picker = null; } }
  function openTypePicker(anchor, at) {
    closePicker();
    picker = h("div", { class: "pop type-pop", role: "dialog", "aria-label": T.add_question }, [h("b", { text: T.add_question_here })]);
    GROUPS.forEach(function (g) {
      picker.appendChild(h("small", { class: "muted", text: T[g[0]] }));
      var row = h("div", { class: "add-types" });
      g[1].forEach(function (type) {
        row.appendChild(h("button", { type: "button", class: "type-chip t-" + type, onclick: function () { closePicker(); insertAt(type, at); } },
          [h("span", { class: "type-ico", text: T["ico_" + type] }), h("span", { text: T["type_" + type] })]));
      });
      picker.appendChild(row);
    });
    placePop(picker, anchor);
  }
  function insertAt(type, at) {
    leave(questions[activeIndex]);
    var q = newQuestion(type);
    questions.splice(at, 0, q);
    activeIndex = at;
    pendingFocus = { q: q, scroll: true };
    touch(); render();
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closePicker(); closePop(); } });

  /* ================= list ================= */
  /* keep a card where it is on screen while the cards above it open or close */
  function keepPlace(card, fn) {
    var before = card ? card.getBoundingClientRect().top : null;
    var index = card ? parseInt(card.getAttribute("data-index"), 10) : -1;
    fn();
    var after = list.querySelectorAll(".qcard")[index];
    if (before !== null && after) {
      var top = after.getBoundingClientRect().top;
      var min = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
      if (top !== before) window.scrollBy(0, top - Math.max(before, min));
    }
  }
  /* only one question is open at a time */
  function openCard(index) {
    var card = list.querySelectorAll(".qcard")[index];
    keepPlace(card, function () {
      if (index !== activeIndex) leave(questions[activeIndex]);
      activeIndex = index;
      questions[index]._collapsed = false;
      pendingFocus = { q: questions[index], keep: true };
      render();
    });
  }
  function grow(el) {
    if (!el || el.hidden || !el.isConnected) return;
    el.style.height = "auto";
    el.style.height = (el.scrollHeight + 2) + "px";
  }
  list.addEventListener("input", function (e) { if (e.target.tagName === "TEXTAREA") grow(e.target); });
  window.addEventListener("resize", function () { Array.prototype.forEach.call(list.querySelectorAll("textarea"), grow); });

  function render() {
    if (pendingFocus) {
      var want = questions.indexOf(pendingFocus.q);
      if (want >= 0) {
        if (want !== activeIndex && questions[activeIndex] && questions[activeIndex] !== pendingFocus.q) leave(questions[activeIndex]);
        activeIndex = want;
        pendingFocus.q._collapsed = false;
      }
    }
    questions.forEach(function (q, i) { if (i !== activeIndex) q._collapsed = true; });
    list.textContent = "";
    floatBtn.hidden = true;
    if (!questions.length) list.appendChild(h("div", { class: "q-empty", text: T.no_questions }));
    questions.forEach(function (q, i) {
      list.appendChild(renderCard(q, i));
      if (q.type !== "section" || i < questions.length - 1) {  /* "add a question here" under every question */
        var gap = h("div", { class: "q-gap" }, [h("button", { type: "button", class: "gap-add", "data-picker": "1", html: icon("plus", 13) + "<span></span>",
          onclick: function (e) { openTypePicker(e.currentTarget, i + 1); } })]);
        gap.querySelector("span").textContent = T.add_question_here;
        list.appendChild(gap);
      }
    });
    updateSummary();
    Array.prototype.forEach.call(list.querySelectorAll("textarea"), grow);
    var cards = list.querySelectorAll(".qcard");
    if (pendingFocus) {
      var idx = questions.indexOf(pendingFocus.q);
      var card = cards[idx];
      var target = card && (pendingFocus.opt !== undefined ? card.querySelector('[data-opt="' + pendingFocus.opt + '"]') : card.querySelector("[data-q-text]"));
      if (target) {
        target.focus({ preventScroll: !pendingFocus.scroll });
        if (pendingFocus.scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      if (idx >= 0) activeIndex = idx;
      pendingFocus = null;
    }
    markActive();
    renderPreview();
  }

  function markActive() {
    Array.prototype.forEach.call(list.querySelectorAll(".qcard"), function (el, i) { el.classList.toggle("focus", i === activeIndex && !questions[i]._collapsed); });
  }

  function updateSummary() {
    var total = questions.reduce(function (sum, q) { return sum + (UNSCORED.indexOf(q.type) === -1 ? (parseFloat(q.points) || 0) : 0); }, 0);
    var count = questions.filter(function (q) { return q.type !== "section"; }).length;
    summary.textContent = fmt(T.n_questions_short, { n: count }) + " · " + T.total_points + ": " + num(total);
    var link = $("issues-link");
    var bad = questions.filter(function (q) { return shownIssue(q); });
    if (link) {
      link.hidden = !bad.length;
      link.textContent = "⚠ " + fmt(bad.length === 1 ? T.n_incomplete_one : T.n_incomplete, { n: bad.length });
    }
  }
  var issuesLink = $("issues-link");
  if (issuesLink) issuesLink.addEventListener("click", function () {
    var i = questions.findIndex(function (q) { return shownIssue(q); });
    if (i < 0) return;
    tabTo("questions");
    if (i !== activeIndex) leave(questions[activeIndex]);
    questions[i]._collapsed = false;
    activeIndex = i;
    render();
    var card = list.querySelectorAll(".qcard")[i];
    if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  list.addEventListener("focusin", function (event) {
    var card = event.target.closest(".qcard");
    if (!card) return;
    var i = parseInt(card.getAttribute("data-index"), 10);
    if (!isNaN(i) && i !== activeIndex && !questions[i]._collapsed) { leave(questions[activeIndex]); activeIndex = i; markActive(); renderPreview(); }
  });
  /* leaving the question list altogether (settings, preview, toolbar…) also counts as leaving */
  document.addEventListener("focusin", function (event) {
    if (!list.contains(event.target) && !(picker && picker.contains(event.target)) && !(mathPop && mathPop.contains(event.target))) leave(questions[activeIndex]);
  });

  /* ================= live preview (as the student sees it) ================= */
  function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(renderPreview, 160); }

  function sectionOf(index) {
    for (var i = index - 1; i >= 0; i -= 1) if (questions[i].type === "section") return questions[i];
    return null;
  }

  function renderPreview() {
    if (!preview) return;
    var q = questions[activeIndex] || questions[0];
    var frame = $("preview-frame");
    if (frame) frame.className = "pv-frame " + device;
    var tb = $("btn-try");
    if (tb) tb.hidden = !q || q.type === "section" || TRY_TYPES.indexOf(q.type) === -1 || !!q.manual_grade;
    if (!q) { preview.innerHTML = '<p class="muted">' + esc(T.no_questions) + "</p>"; return; }
    var scored = questions.filter(function (x) { return x.type !== "section"; });
    var pos = scored.indexOf(q) + 1;
    var dir = q.extra.dir || "auto";
    var out = "";
    if (q.type !== "section") {
      out += '<div class="pv-top"><span>' + esc(fmt(T.q_of_n, { n: pos, total: scored.length })) + "</span>" +
        (UNSCORED.indexOf(q.type) === -1 ? "<span>" + esc(fmt(T.n_points, { n: num(q.points) })) + "</span>" : "") + "</div>";
      out += '<div class="pv-bar"><i style="width:' + Math.round(100 * pos / Math.max(1, scored.length)) + '%"></i></div>';
      var sec = sectionOf(questions.indexOf(q));
      if (sec && (String(sec.text || "").trim() || sec.description || sec.image)) {
        var sd = sec.extra.dir || "auto";
        out += '<div class="pv-sec">' + (String(sec.text || "").trim() ? '<div class="pv-sec-title" dir="' + esc(sd) + '">' + rich(sec.text) + "</div>" : "") +
          (sec.image ? '<img class="pv-img" src="' + esc(media(sec.image)) + '" alt="">' : "") +
          (sec.description ? '<div class="pv-passage small" dir="' + esc(sd) + '">' + rich(sec.description) + "</div>" : "") + "</div>";
      }
    }
    out += '<div class="pv-q" dir="' + esc(dir) + '">' + (rich(q.text) || '<span class="muted">' + esc(q.type === "section" ? T.type_section : T.untitled_question) + "</span>") + "</div>";
    if (q.type === "section") {
      if (q.image) out += '<img class="pv-img" src="' + esc(media(q.image)) + '" alt="">';
      if (q.description) out += '<div class="pv-passage" dir="' + esc(dir) + '">' + rich(q.description) + "</div>";
    } else {
      if (q.description) out += '<p class="pv-hint" dir="' + esc(dir) + '">' + rich(q.description) + "</p>";
      if (q.image && !(q.type === "draw" && q.options && q.options.on_image)) out += '<img class="pv-img" src="' + esc(media(q.image)) + '" alt="">';
      if (q.audio) out += '<audio class="pv-audio-el" controls preload="none" src="' + esc(media(q.audio)) + '"></audio>';
      if (q.extra.attachment) out += '<div class="pv-file">' + icon("clip", 14) + " " + esc(q.extra.attachment.label || "") + "</div>";
      var tryable = TRY_TYPES.indexOf(q.type) !== -1;
      out += tryable ? tryBody(q, dir) : previewBody(q, dir);
      out += '<div class="pv-result" id="pv-result">' + (tryable ? (q._tryResult || "") : "") + "</div>";
      out += '<div class="pv-next">' + esc(T.next) + "</div>";
    }
    preview.innerHTML = out;
    preview.setAttribute("data-index", String(questions.indexOf(q)));
    if (window.MathView) window.MathView.render(preview);
  }

  /* ---------- trying the question in the preview (graded by the server with the real rules) ---------- */
  var TRY_TYPES = ["mcq", "checkbox", "dropdown", "truefalse", "short", "number", "fill", "order", "match"];
  function payloadOf(q) {
    var single = questions;
    questions = [q];
    var out = buildPayload().questions[0];
    questions = single;
    return out;
  }
  function tryBody(q, dir) {
    var p = payloadOf(q);
    var v = q._try;
    var d = ' dir="' + esc(dir) + '"';
    var o = p.options;
    var imgs = (p.extra && p.extra.option_images) || [];
    if (q.type === "mcq" || q.type === "checkbox") {
      /* every option row of the editor, empty ones as faded placeholders; i = its place among the saved options */
      var i = -1;
      return q.options.map(function (raw, n) {
        if (!String(raw).trim() && !imgAt(q, "option_images", n)) {
          return '<div class="pv-opt ghost"' + d + '><span class="pv-mark' + (q.type === "checkbox" ? " sq" : "") + '"></span><span>' + esc(fmt(T.option_n, { n: n + 1 })) + "</span></div>";
        }
        i += 1;
        var opt = (o || [])[i];
        var on = q.type === "checkbox" ? (Array.isArray(v) && v.indexOf(i) !== -1) : v === i;
        return '<label class="pv-opt pick"' + d + '><input type="' + (q.type === "checkbox" ? "checkbox" : "radio") + '" name="pv-choice" data-k="choice" value="' + i + '"' + (on ? " checked" : "") + ">" +
          "<span>" + rich(shown(opt)) + "</span>" + (imgs[i] ? '<img src="' + esc(media(imgs[i])) + '" alt="">' : "") + "</label>";
      }).join("");
    }
    if (q.type === "dropdown") {
      return '<select class="pv-sel" data-k="select"' + d + '><option value="">' + esc(T.choose) + "</option>" + (o || []).map(function (opt, i) {
        return '<option value="' + i + '"' + (v === i ? " selected" : "") + ">" + esc(shown(opt)) + "</option>";
      }).join("") + "</select>";
    }
    if (tfMulti(q)) {
      var vals = Array.isArray(v) ? v : [], k = -1;
      return '<div class="pv-tfl"' + d + ">" + q.options.items.map(function (it, n) {
        if (!String(it).trim()) return '<div class="pv-tfr ghost"><span class="pv-tfn">' + (n + 1) + "</span><span>" + esc(fmt(T.tf_statement_n, { n: n + 1 })) + "</span></div>";
        k += 1;
        return '<div class="pv-tfr"><span class="pv-tfn">' + (n + 1) + "</span><span class=\"pv-tfs\">" + rich(it) + "</span>" +
          ["true", "false"].map(function (val) {
            return '<label class="pv-tfp ' + (val === "true" ? "yes" : "no") + '"><input type="radio" name="pv-tf' + k + '" data-k="tfm" data-i="' + k + '" value="' + val + '"' + (vals[k] === val ? " checked" : "") + "><span>" + (val === "true" ? "✓" : "✗") + "</span></label>";
          }).join("") + "</div>";
      }).join("") + "</div>";
    }
    if (q.type === "truefalse") {
      return ["true", "false"].map(function (val) {
        return '<label class="pv-opt pick"><input type="radio" name="pv-tf" data-k="tf" value="' + val + '"' + (v === val ? " checked" : "") + "><span>" + esc(T[val]) + "</span></label>";
      }).join("");
    }
    if (q.type === "short" || q.type === "number") {
      return '<input class="pv-in" type="text" data-k="text"' + (q.type === "number" ? ' dir="ltr" inputmode="decimal"' : d) + ' value="' + esc(v || "") + '" placeholder="' + esc(T.your_answer) + '">';
    }
    if (q.type === "fill") {
      var text = (o && o.template) || "", html = "", last = 0, m, k = 0;
      var vals = Array.isArray(v) ? v : [];
      BLANK_RE.lastIndex = 0;
      while ((m = BLANK_RE.exec(text))) {
        var bd = ((o && o.blank_dirs) || [])[k];
        html += rich(text.slice(last, m.index)) + '<input class="pv-blank-in" type="text" data-k="blank" data-i="' + k + '"' + (bd ? ' dir="' + (bd === "rtl" ? "rtl" : "ltr") + '"' + (bd === "num" ? ' inputmode="decimal"' : "") : "") + ' value="' + esc(vals[k] || "") + '">';
        last = m.index + m[0].length;
        k += 1;
      }
      html += rich(text.slice(last));
      var words = [];
      if (o && o.bank) {
        blanksOf(q).forEach(function (b) { var a = altsOf(b)[0]; if (a) words.push(a); });
        (o.distractors || []).forEach(function (w) { if (w) words.push(w); });
        words = words.filter(function (w, i) { return words.indexOf(w) === i; }).sort();
      }
      return '<div class="pv-fill" dir="' + fillDir(q) + '">' + html + "</div>" + (words.length ? '<div class="pv-bank">' + words.map(function (w) {
        return '<button type="button" data-k="word" data-w="' + esc(w) + '">' + esc(w) + "</button>";
      }).join("") + "</div>" : "");
    }
    if (q.type === "order") {
      var first = (q.correct || [])[0] || "";
      var chunks = (first.indexOf("/") !== -1 ? first.split("/") : first.split(/\s+/)).map(function (c) { return c.trim(); }).filter(Boolean);
      var order = chunks.map(function (c, i) { return i; }).sort(function (a, b) { return chunks[a] < chunks[b] ? -1 : chunks[a] > chunks[b] ? 1 : a - b; });
      var picked = Array.isArray(v) ? v : [];
      return '<div class="pv-line built"' + d + ">" + picked.map(function (i) { return "<span>" + esc(chunks[i]) + "</span>"; }).join(" ") + "</div>" +
        '<div class="pv-bank"' + d + ">" + order.map(function (i) {
          return '<button type="button" data-k="chunk" data-i="' + i + '"' + (picked.indexOf(i) !== -1 ? " disabled" : "") + ">" + esc(chunks[i]) + "</button>";
        }).join("") + "</div>";
    }
    if (q.type === "match") {
      var pairs = (o && o.pairs) || [];
      var L = (p.extra && p.extra.left_images) || [], R = (p.extra && p.extra.right_images) || [];
      var choices = [];
      pairs.forEach(function (pr) { if (choices.indexOf(pr[1]) === -1) choices.push(pr[1]); });
      (o.distractors || []).forEach(function (x) { if (x && choices.indexOf(x) === -1) choices.push(x); });
      choices.sort();
      var given = Array.isArray(v) ? v : [];
      return pairs.map(function (pr, i) {
        return '<div class="pv-mrow"' + d + "><span>" + (i + 1) + ". " + (L[i] ? '<img src="' + esc(media(L[i])) + '" alt="">' : "") + rich(shown(pr[0])) + "</span>" +
          '<select class="pv-sel sm" data-k="match" data-i="' + i + '"><option value="">' + esc(T.choose) + "</option>" + choices.map(function (c, n) {
            var label = shown(c).trim() || ("🖼 " + (n + 1));
            return '<option value="' + esc(c) + '"' + (given[i] === c ? " selected" : "") + ">" + esc(label) + "</option>";
          }).join("") + "</select></div>";
      }).join("") + (R.some(Boolean) ? '<div class="pv-bank">' + pairs.map(function (pr, i) {
        return R[i] ? "<span><img src=\"" + esc(media(R[i])) + "\" alt=\"\">" + esc(shown(pr[1]).trim() || ("🖼 " + (choices.indexOf(pr[1]) + 1))) + "</span>" : "";
      }).join("") + "</div>" : "");
    }
    return "";
  }

  function tryValue(q) {
    var v = q._try;
    if (q.type === "order") {
      var first = (q.correct || [])[0] || "";
      var chunks = (first.indexOf("/") !== -1 ? first.split("/") : first.split(/\s+/)).map(function (c) { return c.trim(); }).filter(Boolean);
      return (Array.isArray(v) ? v : []).map(function (i) { return chunks[i]; }).join(" ");
    }
    return v === undefined ? null : v;
  }

  function currentQ() {
    var i = parseInt(preview.getAttribute("data-index"), 10);
    return questions[i];
  }
  var lastBlank = 0;
  if (preview) {
    preview.addEventListener("focusin", function (e) { if (e.target.getAttribute("data-k") === "blank") lastBlank = parseInt(e.target.getAttribute("data-i"), 10); });
    function onEdit(e) {
      var el = e.target, k = el.getAttribute && el.getAttribute("data-k"), q = currentQ();
      if (!q || !k) return;
      if (k === "choice") {
        if (q.type === "checkbox") {
          q._try = Array.prototype.map.call(preview.querySelectorAll('[data-k="choice"]:checked'), function (x) { return parseInt(x.value, 10); });
        } else q._try = parseInt(el.value, 10);
      } else if (k === "select") q._try = el.value === "" ? undefined : parseInt(el.value, 10);
      else if (k === "tf") q._try = el.value;
      else if (k === "tfm") {
        var n = preview.querySelectorAll(".pv-tfr:not(.ghost)").length, outv = [];
        for (var j = 0; j < n; j += 1) { var c = preview.querySelector('[data-k="tfm"][data-i="' + j + '"]:checked'); outv.push(c ? c.value : ""); }
        q._try = outv;
      }
      else if (k === "text") q._try = el.value;
      else if (k === "blank") {
        var vals = Array.prototype.map.call(preview.querySelectorAll('[data-k="blank"]'), function (x) { return x.value; });
        q._try = vals;
      } else if (k === "match") {
        q._try = Array.prototype.map.call(preview.querySelectorAll('[data-k="match"]'), function (x) { return x.value; });
      } else return;
      clearResult(q);
    }
    preview.addEventListener("input", onEdit);
    preview.addEventListener("change", onEdit);
    preview.addEventListener("click", function (e) {
      var el = e.target.closest("[data-k]"), q = currentQ();
      if (!el || !q) return;
      var k = el.getAttribute("data-k");
      if (k === "word") {
        var inputs = preview.querySelectorAll('[data-k="blank"]');
        var target = inputs[lastBlank] && !inputs[lastBlank].value ? inputs[lastBlank] : Array.prototype.filter.call(inputs, function (x) { return !x.value; })[0] || inputs[lastBlank];
        if (target) { target.value = el.getAttribute("data-w"); onEdit({ target: target }); }
      } else if (k === "chunk") {
        q._try = (Array.isArray(q._try) ? q._try : []).concat([parseInt(el.getAttribute("data-i"), 10)]);
        clearResult(q); renderPreview();
      } else if (k === "clear") {
        delete q._try; clearResult(q); renderPreview();
      } else if (k === "check") {
        checkTry(q);
      }
    });
  }
  function clearResult(q) {
    delete q._tryResult;
    var box = $("pv-result");
    if (box) box.innerHTML = "";
  }
  var tryBtn = $("btn-try");
  if (tryBtn) tryBtn.addEventListener("click", function () {
    var q = questions[activeIndex];
    var box = $("pv-result");
    if (!q || q.type === "section") return;
    if (TRY_TYPES.indexOf(q.type) === -1 || q.manual_grade) {
      if (box) box.innerHTML = '<div class="res info">' + esc(UNSCORED.indexOf(q.type) !== -1 ? T.try_not_scored : T.try_manual) + "</div>";
      return;
    }
    checkTry(q);
  });
  function checkTry(q) {
    var box = $("pv-result");
    if (box) box.innerHTML = '<span class="muted small">' + icon("spin", 14) + " " + esc(T.try_checking) + "</span>";
    api(data.checkUrl, { json: { question: payloadOf(q), value: tryValue(q) } }).then(function (r) {
      var html;
      if (!r.ok) html = '<div class="res warn">' + icon("alert", 15) + " " + esc(r.error || T.save_failed) + "</div>";
      else if (r.manual) html = '<div class="res info">' + esc(T.try_manual) + "</div>";
      else if (r.nokey) html = '<div class="res warn">' + icon("alert", 15) + " " + esc(T.try_nokey) + "</div>";
      else if (r.empty) html = '<div class="res info">' + esc(T.try_empty_hint) + "</div>";
      else {
        var full = r.points >= r.max - 1e-9, none = r.points <= 0;
        var cls = full ? "ok" : none ? "bad" : "part";
        var label = full ? T.try_right : none ? T.try_wrong : T.try_partial;
        html = '<div class="res ' + cls + '"><b>' + (full ? "✓ " : none ? "✗ " : "~ ") + esc(label) + "</b> — " + esc(fmt(T.try_score, { n: num(r.points), m: num(r.max) })) + "</div>";
        if (!full && r.correct) html += '<div class="res-key">' + esc(T.correct_answer) + ": <b>" + esc(shown(r.correct)) + "</b></div>";
      }
      html += '<button type="button" class="link small" data-k="clear">' + esc(T.try_again) + "</button>";
      q._tryResult = html;
      if (box && currentQ() === q) box.innerHTML = html;
    }).catch(function () { if (box) box.innerHTML = '<span class="muted small">' + esc(T.offline_retry) + "</span>"; });
  }

  function previewBody(q, dir) {
    var o = q.options;
    var d = ' dir="' + esc(dir) + '"';
    if (CHOICE.indexOf(q.type) !== -1) {
      if (q.type === "dropdown") return '<div class="pv-select"' + d + ">" + esc(T.choose) + " ▾</div>";
      return (o || []).map(function (opt, i) {
        var img = imgAt(q, "option_images", i);
        if (!String(opt).trim() && !img) return '<div class="pv-opt ghost"' + d + '><span class="pv-mark' + (q.type === "checkbox" ? " sq" : "") + '"></span><span>' + esc(fmt(T.option_n, { n: i + 1 })) + "</span></div>";
        return '<div class="pv-opt"' + d + '><span class="pv-mark' + (q.type === "checkbox" ? " sq" : "") + '"></span><span>' + rich(shown(opt)) + "</span>" +
          (img ? '<img src="' + esc(media(img)) + '" alt="">' : "") + "</div>";
      }).join("");
    }
    if (tfMulti(q)) return '<div class="pv-tfl"' + d + ">" + q.options.items.map(function (it, n) {
      return '<div class="pv-tfr' + (String(it).trim() ? "" : " ghost") + '"><span class="pv-tfn">' + (n + 1) + "</span><span class=\"pv-tfs\">" + (String(it).trim() ? rich(it) : esc(fmt(T.tf_statement_n, { n: n + 1 }))) + '</span><span class="pv-tfp yes"><span>✓</span></span><span class="pv-tfp no"><span>✗</span></span></div>';
    }).join("") + "</div>";
    if (q.type === "truefalse") return ["true", "false"].map(function (v) { return '<div class="pv-opt"><span class="pv-mark"></span><span>' + esc(T[v]) + "</span></div>"; }).join("");
    if (q.type === "short" || q.type === "number" || q.type === "date") return '<div class="pv-input"' + d + ">" + esc(q.type === "date" ? "yyyy-mm-dd" : T.your_answer) + "</div>";
    if (q.type === "paragraph") return '<div class="pv-input tall"' + d + ">" + esc(T.your_answer) + "</div>";
    if (q.type === "file") return '<div class="pv-input">' + icon("clip", 14) + " " + esc(T.choose_file) + "</div>";
    if (q.type === "draw") {
      if (o && o.on_image && q.image) return '<div class="pv-draw on-img"><img src="' + esc(media(q.image)) + '" alt=""></div>';
      return '<div class="pv-draw' + (o && o.lines === false ? "" : " lined") + '"></div>';
    }
    if (q.type === "fill") return fillPreviewHtml(q);
    if (q.type === "scale") return scaleHtml(o || {}, 0);
    if (q.type === "order") {
      var first = (q.correct || [])[0] || "";
      var chunks = (first.indexOf("/") !== -1 ? first.split("/") : first.split(/\s+/)).map(function (c) { return c.trim(); }).filter(Boolean);
      chunks.sort();
      return '<div class="pv-line"></div><div class="pv-bank"' + d + ">" + chunks.map(function (c) { return "<span>" + esc(c) + "</span>"; }).join("") + "</div>";
    }
    if (q.type === "match") {
      var pairs = ((o && o.pairs) || []).map(function (p, i) { return { p: p, i: i }; }).filter(function (x) {
        return (String(x.p[0]).trim() || imgAt(q, "left_images", x.i)) && (String(x.p[1]).trim() || imgAt(q, "right_images", x.i));
      }).map(function (x) { var p = x.p.slice(); p.i = x.i; return p; });
      var left = pairs.map(function (p, k) {
        var i = p.i;
        var img = imgAt(q, "left_images", i);
        return '<div class="pv-mrow"' + d + "><span>" + (k + 1) + ". " + rich(shown(p[0])) + "</span>" + (img ? '<img src="' + esc(media(img)) + '" alt="">' : "") + '<span class="pv-slot"></span></div>';
      }).join("");
      var right = pairs.map(function (p) {
        var img = imgAt(q, "right_images", p.i);
        return "<span>" + (img ? '<img src="' + esc(media(img)) + '" alt="">' : "") + rich(shown(p[1])) + "</span>";
      }).concat((o && o.distractors || []).map(function (x) { return "<span>" + esc(x) + "</span>"; })).join("");
      return left + '<div class="pv-bank">' + right + "</div>";
    }
    return "";
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-device]"), function (b) {
    b.addEventListener("click", function () {
      device = b.getAttribute("data-device");
      Array.prototype.forEach.call(document.querySelectorAll("[data-device]"), function (x) { x.classList.toggle("on", x === b); });
      renderPreview();
    });
  });
  var pvToggle = $("btn-preview-panel");
  if (pvToggle) pvToggle.addEventListener("click", function () { builder.classList.toggle("show-preview"); renderPreview(); });

  /* ================= question bank ================= */
  function payloadFor(q) {
    var single = questions;
    questions = [q];
    var out = buildPayload().questions[0];
    questions = single;
    out.id = null;
    return out;
  }
  function saveToBank(q) {
    api(data.bankUrl, { json: { question: payloadFor(q), subject: settings.subject || "", grade: settings.grade || "" } })
      .then(function (res) { toast(res.ok ? res.message : (res.error || T.save_failed)); })
      .catch(function () { toast(T.save_failed); });
  }

  var bankModal = $("bank-modal");
  var bankItems = [], bankPicked = {}, bankTimer = null;
  function bankCount() { $("bank-count").textContent = Object.keys(bankPicked).length; }
  function loadBank() {
    var params = ["q=" + encodeURIComponent($("bank-q").value.trim()), "type=" + encodeURIComponent($("bank-type").value),
      "subject=" + encodeURIComponent($("bank-subject").value), "grade=" + encodeURIComponent($("bank-grade").value)];
    var box = $("bank-list");
    box.textContent = T.loading;
    fetch(data.bankUrl + "?" + params.join("&"), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (res) {
      bankItems = res.items || [];
      [["bank-subject", res.subjects], ["bank-grade", res.grades]].forEach(function (pair) {
        var sel = $(pair[0]);
        if (sel.options.length <= 1) (pair[1] || []).forEach(function (v) { sel.appendChild(h("option", { value: v, text: v })); });
      });
      box.textContent = "";
      if (!bankItems.length) { box.appendChild(h("div", { class: "empty", text: T.bank_none_found })); return; }
      bankItems.forEach(function (item) {
        var cb = h("input", { type: "checkbox", onchange: function () {
          if (cb.checked) bankPicked[item.bank_id] = item; else delete bankPicked[item.bank_id];
          bankCount();
        } });
        cb.checked = !!bankPicked[item.bank_id];
        var meta = h("div", { class: "bank-meta" }, [h("span", { class: "badge blue", text: item.type_label })]);
        if (item.points) meta.appendChild(h("span", { class: "badge gray", text: item.points + " " + T.points }));
        if (item.subject) meta.appendChild(h("span", { class: "badge green", text: item.subject }));
        if (item.grade) meta.appendChild(h("span", { class: "badge green", text: item.grade }));
        var body = h("div", { class: "bank-body" }, [meta, h("div", { class: "bank-text", dir: "auto", text: item.text })]);
        if (item.answer) body.appendChild(h("div", { class: "bank-answer small", dir: "auto", text: "✓ " + item.answer }));
        var row = h("label", { class: "card bank-item" }, [cb, body]);
        if (item.image) row.appendChild(h("img", { class: "bank-img", src: media(item.image), alt: "", loading: "lazy" }));
        box.appendChild(row);
      });
    }).catch(function () { box.textContent = T.save_failed; });
  }
  function openBank() { bankPicked = {}; bankCount(); bankModal.hidden = false; loadBank(); $("bank-q").focus(); }
  $("btn-bank").addEventListener("click", openBank);
  $("bank-cancel").addEventListener("click", function () { bankModal.hidden = true; });
  bankModal.addEventListener("click", function (e) { if (e.target === bankModal) bankModal.hidden = true; });
  $("bank-q").addEventListener("input", function () { clearTimeout(bankTimer); bankTimer = setTimeout(loadBank, 300); });
  ["bank-type", "bank-subject", "bank-grade"].forEach(function (id) { $(id).addEventListener("change", loadBank); });
  $("bank-add").addEventListener("click", function () {
    var ids = Object.keys(bankPicked).map(Number);
    if (!ids.length) { bankModal.hidden = true; return; }
    var first = null;
    ids.forEach(function (id) {
      var it = bankPicked[id];
      var q = { id: null, type: it.type, text: it.text, description: it.description || "", image: it.image || "", audio: it.audio || "",
        points: it.points, required: it.type !== "section", options: JSON.parse(JSON.stringify(it.options)),
        correct: JSON.parse(JSON.stringify(it.correct)), explanation: it.explanation || "", partial: !!it.partial,
        manual_grade: !!it.manual_grade, extra: JSON.parse(JSON.stringify(it.extra || {})) };
      questions.push(q);
      if (!first) first = q;
    });
    api(data.bankUsedUrl, { json: { ids: ids } });
    bankModal.hidden = true;
    pendingFocus = { q: first, scroll: true };
    touch(); render();
    toast(fmt(T.bank_added, { n: ids.length }));
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !bankModal.hidden) bankModal.hidden = true; });

  /* ================= AI: questions from a reading text ================= */
  var aiModal = $("ai-modal");
  var aiCounts = { mcq: 3, truefalse: 2 };
  var aiLevel = "medium", aiResults = [];
  function aiOpen() {
    aiModal.hidden = false;
    $("ai-off").hidden = !!data.aiEnabled;
    $("ai-on").hidden = !data.aiEnabled;
    if (!data.aiEnabled) { $("ai-off-text").textContent = data.isAdmin ? T.ai_disabled_admin : T.ai_disabled; return; }
    var passage = $("ai-passage");
    if (!passage.value.trim()) {
      for (var i = Math.min(activeIndex, questions.length - 1); i >= 0; i -= 1) {
        if (questions[i] && questions[i].type === "section" && questions[i].description) { passage.value = questions[i].description; break; }
      }
    }
    drawCounts();
    passage.focus();
  }
  function drawCounts() {
    var box = $("ai-types");
    box.textContent = "";
    Object.keys(aiCounts).forEach(function (type) {
      box.appendChild(h("span", { class: "count-chip" }, [
        h("button", { type: "button", html: icon("minus", 11), onclick: function () { aiCounts[type] -= 1; if (aiCounts[type] <= 0) delete aiCounts[type]; drawCounts(); } }),
        h("span", { text: T["type_" + type] + " × " + aiCounts[type] }),
        h("button", { type: "button", html: icon("plus", 11), onclick: function () { aiCounts[type] = Math.min(10, aiCounts[type] + 1); drawCounts(); } })]));
    });
    var add = h("select", { class: "count-add", onchange: function () { if (add.value) { aiCounts[add.value] = (aiCounts[add.value] || 0) + 1; drawCounts(); } } }, [h("option", { value: "", text: "+ " + T.ai_add_type })]);
    ["mcq", "truefalse", "short", "fill", "checkbox", "paragraph"].forEach(function (t) { if (!aiCounts[t]) add.appendChild(h("option", { value: t, text: T["type_" + t] })); });
    box.appendChild(add);
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-level]"), function (b) {
    b.addEventListener("click", function () {
      aiLevel = b.getAttribute("data-level");
      Array.prototype.forEach.call(document.querySelectorAll("[data-level]"), function (x) { x.classList.toggle("on", x === b); });
    });
  });
  function aiGenerate() {
    var passage = $("ai-passage").value.trim();
    var res = $("ai-results");
    if (!passage) { toast(T.ai_need_text); return; }
    res.innerHTML = '<div class="ai-wait">' + icon("spin", 18) + " " + esc(T.ai_thinking) + "</div>";
    $("ai-generate").disabled = true;
    api(data.aiUrl, { json: { mode: "questions", passage: passage, counts: aiCounts, level: aiLevel } }).then(function (r) {
      $("ai-generate").disabled = false;
      res.textContent = "";
      if (!r.ok) { res.textContent = r.error || T.ai_failed; return; }
      aiResults = (r.questions || []).map(function (q) { q._pick = true; return q; });
      if (!aiResults.length) { res.textContent = T.ai_failed; return; }
      drawResults();
    }).catch(function () { $("ai-generate").disabled = false; res.textContent = T.ai_failed; });
  }
  function drawResults() {
    var res = $("ai-results");
    res.textContent = "";
    res.appendChild(h("b", { class: "small", text: T.ai_review }));
    aiResults.forEach(function (q) {
      var cb = h("input", { type: "checkbox", onchange: function () { q._pick = cb.checked; countAi(); } });
      cb.checked = q._pick;
      var meta = T["type_" + q.type];
      if (q.type === "mcq" && typeof q.correct === "number") meta += " · " + q.options.map(function (o, i) { return i === q.correct ? o + " ✓" : o; }).join(" · ");
      else if (q.type === "truefalse") meta += " · " + T[q.correct] + " ✓";
      else if (q.type === "fill") meta += " · " + q.options.template;
      res.appendChild(h("label", { class: "ai-item" }, [cb, h("span", {}, [h("b", { dir: "auto", text: q.text }), h("small", { class: "muted", dir: "auto", text: meta })])]));
    });
    countAi();
  }
  function countAi() {
    var n = aiResults.filter(function (q) { return q._pick; }).length;
    $("ai-add").textContent = fmt(T.ai_add_n, { n: n });
    $("ai-add").disabled = !n;
    $("ai-again").hidden = false;
  }
  if (aiModal) {
    $("btn-ai").addEventListener("click", aiOpen);
    $("ai-close").addEventListener("click", function () { aiModal.hidden = true; });
    aiModal.addEventListener("click", function (e) { if (e.target === aiModal) aiModal.hidden = true; });
    $("ai-generate").addEventListener("click", aiGenerate);
    $("ai-again").addEventListener("click", aiGenerate);
    $("ai-add").addEventListener("click", function () {
      var at = Math.min(questions.length, activeIndex + 1);
      var first = null;
      aiResults.filter(function (q) { return q._pick; }).forEach(function (r) {
        var q = newQuestion(r.type);
        q.text = r.text;
        if (r.options) q.options = r.options;
        q.correct = r.correct;
        q.points = r.points || q.points;
        if (GRADED.indexOf(q.type) !== -1) q.manual_grade = q.type === "fill" ? false : (r.correct === null || r.correct === undefined);
        if (q.type === "fill") q.options.bank = true;
        questions.splice(at, 0, q);
        at += 1;
        if (!first) first = q;
      });
      aiModal.hidden = true;
      aiResults = [];
      $("ai-results").textContent = "";
      pendingFocus = { q: first, scroll: true };
      touch(); render();
    });
  }

  /* ================= drag & drop ================= */
  function startDrag(event, fromIndex, card) {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    var target = null;
    card.classList.add("dragging");
    document.body.classList.add("is-dragging");
    function moveTo(e) {
      var el = document.elementFromPoint(e.clientX, e.clientY);
      var over = el ? el.closest(".qcard") : null;
      if (target && target !== over) target.classList.remove("drop-target");
      target = over && over !== card ? over : null;
      if (target) target.classList.add("drop-target");
      if (e.clientY < 70) window.scrollBy(0, -14);
      else if (e.clientY > window.innerHeight - 70) window.scrollBy(0, 14);
    }
    function up() {
      document.removeEventListener("pointermove", moveTo);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      card.classList.remove("dragging");
      document.body.classList.remove("is-dragging");
      if (target) {
        target.classList.remove("drop-target");
        var to = parseInt(target.getAttribute("data-index"), 10);
        if (!isNaN(to) && to !== fromIndex) {
          var open = questions[activeIndex];
          var item = questions.splice(fromIndex, 1)[0];
          questions.splice(to, 0, item);
          activeIndex = Math.max(0, questions.indexOf(open));
          touch(); render();
        }
      }
    }
    document.addEventListener("pointermove", moveTo);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  function move(index, delta) {
    var to = index + delta;
    if (to < 0 || to >= questions.length) return;
    var open = questions[activeIndex];
    var item = questions.splice(index, 1)[0];
    questions.splice(to, 0, item);
    activeIndex = Math.max(0, questions.indexOf(open));
    touch(); render();
    var cards = list.querySelectorAll(".qcard");
    if (cards[to]) cards[to].scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function duplicate(index) {
    var copy = JSON.parse(JSON.stringify(questions[index], function (k, v) { return k.charAt(0) === "_" ? undefined : v; }));
    copy.id = null;
    questions.splice(index + 1, 0, copy);
    pendingFocus = { q: copy, scroll: true };
    touch(); render();
  }
  function remove(index) {
    if (!window.confirm(T.confirm_delete_question)) return;
    var open = questions[activeIndex];
    questions.splice(index, 1);
    activeIndex = questions.indexOf(open);
    if (activeIndex < 0) { activeIndex = Math.max(0, Math.min(index, questions.length - 1)); if (questions[activeIndex]) questions[activeIndex]._collapsed = true; }
    touch(); render();
  }

  $("add-bar").addEventListener("click", function (event) {
    var button = event.target.closest("[data-add]");
    if (!button) return;
    insertAt(button.getAttribute("data-add"), questions.length);
  });

  /* ================= settings ================= */
  var BOOLS = ["shuffle_questions", "shuffle_options", "show_answers", "require_login", "block_copy", "detect_tabs", "require_fullscreen"];
  var NUMS = ["time_limit_min", "max_attempts", "pass_percent", "max_violations"];
  var TEXTS = ["description", "show_results", "subject", "grade"];
  var DATES = ["opens_at", "closes_at"];
  function pad(n) { return n < 10 ? "0" + n : String(n); }
  function toLocalInput(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function fromLocalInput(value) {
    if (!value) return null;
    var ms = new Date(value).getTime();
    return isNaN(ms) ? null : Math.floor(ms / 1000);
  }
  var titleInput = $("f-title");
  titleInput.value = settings.title;
  titleInput.addEventListener("input", function () { settings.title = titleInput.value; touch(); });
  BOOLS.forEach(function (key) {
    var el = $("s-" + key);
    el.checked = !!settings[key];
    el.addEventListener("change", function () { settings[key] = el.checked; touch(); });
  });
  NUMS.forEach(function (key) {
    var el = $("s-" + key);
    setNumInput(el, settings[key]);
    el.addEventListener("input", function () { settings[key] = el.value.trim() === "" ? 0 : parseInt(latin(el.value), 10) || 0; touch(); });
  });
  TEXTS.forEach(function (key) {
    var el = $("s-" + key);
    el.value = settings[key] || (key === "show_results" ? "after_grading" : "");
    el.addEventListener("input", function () { settings[key] = el.value; touch(); });
  });
  DATES.forEach(function (key) {
    var el = $("s-" + key);
    el.value = toLocalInput(settings[key]);
    el.addEventListener("input", function () { settings[key] = fromLocalInput(el.value); touch(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".class-check"), function (el) {
    el.addEventListener("change", function () {
      var id = parseInt(el.value, 10);
      var ids = (settings.class_ids || []).filter(function (x) { return x !== id; });
      if (el.checked) ids.push(id);
      settings.class_ids = ids;
      touch();
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".student-check"), function (el) {
    el.addEventListener("change", function () {
      var id = parseInt(el.value, 10);
      var ids = (settings.student_ids || []).filter(function (x) { return x !== id; });
      if (el.checked) ids.push(id);
      settings.student_ids = ids;
      var badge = $("student-count");
      if (badge) badge.textContent = ids.length;
      touch();
    });
  });
  $("btn-collapse").addEventListener("click", function () { questions.forEach(function (q) { q._collapsed = true; }); render(); });

  Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (tab) {
    tab.addEventListener("click", function () {
      var name = tab.getAttribute("data-tab");
      Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (t) {
        var on = t === tab;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      ["questions", "settings", "share"].forEach(function (id) { $("tab-" + id).hidden = id !== name; });
      if (history.replaceState) history.replaceState(null, "", "#" + name);
    });
  });
  $("btn-copy-link").addEventListener("click", function () {
    var input = $("share-url");
    var done = function () { toast(T.copy_done); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(input.value).then(done, function () { input.select(); document.execCommand("copy"); done(); });
    else { input.select(); document.execCommand("copy"); done(); }
  });

  /* ================= saving (with offline retry) ================= */
  function buildPayload() {
    return {
      settings: Object.assign({}, settings, { title: settings.title }),
      questions: questions.map(function (q) {
        var extra = {};
        if (q.extra.dir) extra.dir = q.extra.dir;
        if (q.extra.attachment) extra.attachment = q.extra.attachment;
        if (q.type === "checkbox" && q.partial && q.extra.cb_deduct === false) extra.cb_deduct = false;
        var out = { id: q.id, type: q.type, text: q.text, description: q.description, image: q.image || "", audio: q.audio || "", points: q.points,
          required: !!q.required, explanation: q.explanation, partial: !!q.partial, manual_grade: !!q.manual_grade,
          options: q.options, correct: q.correct, extra: extra };
        if (q.type === "match") {
          var pairs = [], li = [], ri = [], used = {};
          (q.options.pairs || []).forEach(function (p, i) {
            var L = imgAt(q, "left_images", i), R = imgAt(q, "right_images", i);
            var a = String(p[0]).trim() ? p[0] : (L ? null : ""), b = String(p[1]).trim() ? p[1] : (R ? null : "");
            if (a === "" || b === "") return;
            if (a === null) a = invisible(used);
            if (b === null) b = invisible(used);
            pairs.push([a, b]); li.push(L); ri.push(R);
          });
          out.options = { pairs: pairs, distractors: q.options.distractors || [] };
          if (li.some(Boolean)) extra.left_images = li;
          if (ri.some(Boolean)) extra.right_images = ri;
        }
        if (CHOICE.indexOf(q.type) !== -1) {
          var keep = [], imgs = [], remap = {}, seen = {};
          q.options.forEach(function (text, i) {
            var img = q.type !== "dropdown" ? imgAt(q, "option_images", i) : "";
            if (String(text).trim() || img) {
              remap[i] = keep.length;
              keep.push(String(text).trim() ? text : invisible(seen));
              imgs.push(img);
            }
          });
          out.options = keep;
          if (imgs.some(Boolean)) extra.option_images = imgs;
          if (Array.isArray(q.correct)) out.correct = q.correct.filter(function (i) { return remap[i] !== undefined; }).map(function (i) { return remap[i]; });
          else if (typeof q.correct === "number") out.correct = remap[q.correct] !== undefined ? remap[q.correct] : null;
        }
        if (q.type === "fill") {
          out.options = Object.assign({}, q.options);
          if (q.manual_grade) delete out.options.blank_points;
        }
        return out;
      })
    };
  }
  function invisible(used) {
    var n = 1;
    while (used[n]) n += 1;
    used[n] = true;
    return new Array(n + 1).join(INV);
  }

  var DRAFT_KEY = "exam-draft-" + data.id;
  function keepDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ at: Date.now(), payload: buildPayload() })); } catch (e) { /* storage unavailable */ }
  }
  function dropDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ } }

  function save(force) {
    clearTimeout(saveTimer);
    if (saving) {
      return new Promise(function (resolve) {
        var wait = setInterval(function () { if (!saving) { clearInterval(wait); resolve(save(force)); } }, 120);
      });
    }
    if (revision === savedRevision && !force && questions.every(function (q) { return q.id; })) return Promise.resolve(true);
    saving = true;
    var startRevision = revision;
    setSaveState("saving");
    return api(builder.getAttribute("data-save-url"), { json: buildPayload() }).then(function (res) {
      saving = false;
      if (!res.ok) {
        if (!res.status || res.status >= 500) return offline();
        setSaveState("error");
        if (typeof res.index === "number" && questions[res.index]) markError(questions[res.index], res.error);
        return false;
      }
      retryDelay = 3000;
      clearTimeout(retryTimer);
      (res.ids || []).forEach(function (id, i) { if (questions[i]) questions[i].id = id; });
      savedRevision = startRevision;
      dropDraft();
      if (revision === startRevision) setSaveState("saved");
      else saveTimer = setTimeout(function () { save(); }, 1200);
      return true;
    }).catch(function () { saving = false; return offline(); });
  }
  /* show the problem on the question itself, without moving the page */
  function markError(q, message) {
    questions.forEach(function (x) { if (x !== q) delete x._error; });
    q._error = String(message || T.save_needs_fix).replace(/^[^:：]*[:：]\s*/, "");
    delete q._fresh;
    refreshCardState(q);
    updateSummary();
  }

  function offline() {
    keepDraft();
    setSaveState("offline");
    clearTimeout(retryTimer);
    retryTimer = setTimeout(function () { save(true); }, retryDelay);
    retryDelay = Math.min(30000, retryDelay * 2);
    return false;
  }
  window.addEventListener("online", function () { if (revision !== savedRevision) { retryDelay = 3000; save(true); } });

  function tabTo(name) { var tab = document.querySelector('[data-tab="' + name + '"]'); if (tab) tab.click(); }

  $("btn-save").addEventListener("click", function () { save(true); });
  Array.prototype.forEach.call(document.querySelectorAll("[data-save-first], #btn-preview"), function (button) {
    button.addEventListener("click", function (event) {
      var form = button.closest("form");
      if (!form) return;
      event.preventDefault();
      var publishing = !!form.querySelector('input[name="status"][value="published"]');
      if (publishing) {
        var bad = questions.filter(function (q) { return issueOf(q); });
        if (bad.length) {
          bad.forEach(function (q) { delete q._fresh; refreshCardState(q); });
          updateSummary();
          toast(T.publish_blocked);
          return;
        }
      }
      save(true).then(function (ok) { if (ok) form.submit(); });
    });
  });
  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(true); }
  });
  window.addEventListener("beforeunload", function (event) {
    if (revision !== savedRevision) { keepDraft(); event.preventDefault(); event.returnValue = ""; }
  });

  /* keep content clear of the sticky top bar */
  var barEl = document.querySelector(".builder-bar"), stuck = false, fullH = 0;
  function fitOffsets() {
    var head = document.querySelector(".site-header, header.topbar, body > header");
    var headH = head ? head.offsetHeight : 64;
    var sticky = barEl && getComputedStyle(barEl).position === "sticky";
    if (barEl) barEl.style.top = headH + "px";
    var top = headH + (barEl && sticky ? barEl.offsetHeight : 0) + 12;
    document.documentElement.style.scrollPaddingTop = top + "px";
    document.documentElement.style.setProperty("--builder-top", top + "px");
  }
  window.addEventListener("resize", function () { if (!stuck && barEl) fullH = barEl.offsetHeight; fitOffsets(); });
  window.addEventListener("scroll", function () {
    if (!barEl) return;
    var want = stuck ? window.scrollY > 40 : window.scrollY > 120;  /* hysteresis: no flicker */
    if (want === stuck) return;
    if (want) fullH = barEl.offsetHeight;
    stuck = want;
    barEl.classList.toggle("stuck", stuck);
    /* the compact bar is shorter: keep that space below it so the page does not jump */
    barEl.style.marginBlockEnd = stuck ? Math.max(0, fullH - barEl.offsetHeight) + "px" : "";
    fitOffsets();
  }, { passive: true });
  setTimeout(fitOffsets, 50);

  /* ================= init ================= */
  (function restoreDraft() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null"); } catch (e) { raw = null; }
    if (!raw || !raw.payload || !raw.at || raw.at / 1000 <= (data.updatedAt || 0)) { dropDraft(); return; }
    if (!window.confirm(T.draft_restore)) { dropDraft(); return; }
    var p = raw.payload;
    Object.assign(settings, p.settings || {});
    questions = (p.questions || []).map(padEmpty);
    revision = 1;
    setTimeout(function () { save(true); }, 300);
  })();
  questions.forEach(function (q, i) { q._collapsed = i > 0; });
  render();
  if (location.hash === "#settings" || location.hash === "#share") tabTo(location.hash.slice(1));
  setSaveState(revision ? "saving" : "saved");
})();
