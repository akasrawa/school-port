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
  var BLANK_RE = /\[([^\[\]\n]+)\]/g;

  var settings = data.settings;
  var questions = data.questions;
  var revision = 0;
  var savedRevision = 0;
  var saving = false;
  var saveTimer = null;
  var pendingFocus = null;

  var list = document.getElementById("q-list");
  var saveState = document.getElementById("save-state");
  var summary = document.getElementById("summary");

  function $(id) { return document.getElementById(id); }
  function fmt(text, values) {
    return String(text || "").replace(/\{(\w+)\}/g, function (m, key) {
      return values && values[key] !== undefined ? values[key] : m;
    });
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

  var ICONS = {
    up: '<path d="m18 15-6-6-6 6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    grip: '<circle cx="9" cy="5" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="19" r="1"/>',
    bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>'
  };
  function icon(name, size) {
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 16) + '" height="' + (size || 16) +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      ICONS[name] + "</svg>"
    );
  }

  /* ---------- state helpers ---------- */
  function touch() {
    revision += 1;
    setSaveState(T.unsaved);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save(); }, 2500);
  }

  function setSaveState(text, isError) {
    saveState.textContent = text || "";
    saveState.classList.toggle("err", !!isError);
  }

  function newQuestion(type) {
    var q = {
      id: null, type: type, text: "", description: "", image: "", audio: "",
      points: UNSCORED.indexOf(type) !== -1 ? 0 : (type === "match" || type === "fill" ? 2 : 1),
      required: type !== "section", options: null, correct: null, explanation: "", partial: false
    };
    applyTypeDefaults(q);
    return q;
  }

  function applyTypeDefaults(q) {
    if (CHOICE.indexOf(q.type) !== -1) {
      if (!Array.isArray(q.options)) q.options = ["", ""];
    } else if (q.type === "scale") {
      q.options = { max: 5, min_label: "", max_label: "" };
    } else if (q.type === "draw") {
      if (!q.options || q.options.height === undefined) q.options = { lines: true, height: 380 };
    } else if (q.type === "match") {
      if (!q.options || !Array.isArray(q.options.pairs)) q.options = { pairs: [["", ""], ["", ""], ["", ""]], distractors: [] };
    } else if (q.type === "fill") {
      if (!q.options || typeof q.options.template !== "string") q.options = { template: "", bank: true, distractors: [] };
    } else {
      q.options = null;
    }
  }

  function changeType(q, type) {
    var wasChoice = CHOICE.indexOf(q.type) !== -1;
    var oldCorrect = q.correct;
    var wasUnscored = UNSCORED.indexOf(q.type) !== -1;
    q.type = type;
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
    if (type !== "checkbox") q.partial = false;
  }

  function fillBlanks(q) {
    var out = [];
    var text = (q.options && q.options.template) || "";
    text.replace(BLANK_RE, function (m, inner) { out.push(inner); return m; });
    return out;
  }

  function lacksKey(q) {
    if (GRADED.indexOf(q.type) === -1 || q.manual_grade) return false;
    if (q.type === "match") {
      return !(q.options && (q.options.pairs || []).some(function (p) { return String(p[0]).trim() && String(p[1]).trim(); }));
    }
    if (q.type === "fill") return fillBlanks(q).length === 0;
    var c = q.correct;
    if (c === null || c === undefined) return true;
    if (Array.isArray(c)) return c.length === 0;
    return false;
  }

  /* ---------- rendering ---------- */
  function cardClass(q) {
    var base = "card qcard t-" + q.type + (q._collapsed ? " collapsed" : "");
    if (q.type === "section") return base + " section";
    if (UNSCORED.indexOf(q.type) !== -1) return base + " info";
    if (MANUAL.indexOf(q.type) !== -1 || q.manual_grade) return base + " manual";
    return base;
  }

  function badgeFor(q) {
    if (q.type === "section") return h("span", { class: "badge blue", text: T.type_section });
    if (GRADED.indexOf(q.type) !== -1 && q.manual_grade) return h("span", { class: "badge amber", text: T.manual_graded });
    if (UNSCORED.indexOf(q.type) !== -1) return h("span", { class: "badge gray", text: T.survey_q });
    if (MANUAL.indexOf(q.type) !== -1) return h("span", { class: "badge amber", text: T.manual_graded });
    return h("span", { class: "badge green", text: T.autograded });
  }

  function iconButton(name, label, onClick, extra) {
    return h("button", Object.assign({
      type: "button", class: "icon-btn" + (extra && extra.danger ? " danger" : "") + (extra && extra.extraClass ? " " + extra.extraClass : ""),
      title: label, "aria-label": label, html: icon(name, 16), onclick: onClick
    }, extra && extra.disabled ? { disabled: true } : {}));
  }

  function renderChoice(q, hint) {
    var wrap = h("div", { class: "opt-editor" });
    var name = "pick-" + (q._k || (q._k = Math.random().toString(36).slice(2)));
    q.options.forEach(function (text, index) {
      var multi = q.type === "checkbox";
      var checked = multi ? (q.correct || []).indexOf(index) !== -1 : q.correct === index;
      var line = h("div", { class: "opt-line" + (checked ? " correct" : "") });
      var pick = h("input", {
        type: multi ? "checkbox" : "radio", name: name, class: "pick", checked: checked,
        "aria-label": T.correct_answer + " " + (index + 1),
        onchange: function () {
          if (multi) {
            var set = (q.correct || []).filter(function (i) { return i !== index; });
            if (pick.checked) set.push(index);
            set.sort(function (a, b) { return a - b; });
            q.correct = set.length ? set : null;
            line.classList.toggle("correct", pick.checked);
          } else {
            q.correct = index;
            Array.prototype.forEach.call(wrap.children, function (el, i) { el.classList.toggle("correct", i === index); });
          }
          updateHint(q, hint);
          touch();
        }
      });
      if (checked) pick.checked = true;
      var input = h("input", {
        type: "text", maxlength: "300", value: text, placeholder: fmt(T.option_n, { n: index + 1 }),
        "data-opt": index,
        oninput: function () { q.options[index] = input.value; touch(); },
        onkeydown: function (event) {
          if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            addOption(q);
          }
        }
      });
      var remove = iconButton("x", T.remove, function () { removeOption(q, index); }, { danger: true, disabled: q.options.length <= 2 });
      line.appendChild(pick); line.appendChild(input); line.appendChild(remove);
      wrap.appendChild(line);
    });
    var add = h("button", {
      type: "button", class: "chip", html: icon("plus", 14) + "<span></span>",
      onclick: function () { addOption(q); }
    });
    add.querySelector("span").textContent = T.add_option;
    var box = h("div", { class: "q-fields" }, [wrap, h("div", {}, [add])]);
    return box;
  }

  function addOption(q) {
    if (q.options.length >= 30) return;
    q.options.push("");
    pendingFocus = { q: q, opt: q.options.length - 1 };
    touch();
    render();
  }

  function removeOption(q, index) {
    if (q.options.length <= 2) return;
    q.options.splice(index, 1);
    if (Array.isArray(q.correct)) {
      q.correct = q.correct.filter(function (i) { return i !== index; }).map(function (i) { return i > index ? i - 1 : i; });
      if (!q.correct.length) q.correct = null;
    } else if (typeof q.correct === "number") {
      if (q.correct === index) q.correct = null;
      else if (q.correct > index) q.correct -= 1;
    }
    touch();
    render();
  }

  function renderTrueFalse(q, hint) {
    var name = "tf-" + (q._k || (q._k = Math.random().toString(36).slice(2)));
    var box = h("div", { class: "tf-pick", role: "radiogroup", "aria-label": T.correct_answer });
    ["true", "false"].forEach(function (value) {
      var input = h("input", {
        type: "radio", name: name, value: value, checked: q.correct === value,
        onchange: function () { q.correct = value; updateHint(q, hint); touch(); }
      });
      if (q.correct === value) input.checked = true;
      box.appendChild(h("label", {}, [input, h("span", { text: T[value] })]));
    });
    return box;
  }

  function renderShort(q, hint) {
    var area = h("textarea", {
      rows: "3", placeholder: T.accepted_answers,
      oninput: function () {
        var lines = area.value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
        q.correct = lines.length ? lines : null;
        updateHint(q, hint);
        touch();
      }
    });
    area.value = Array.isArray(q.correct) ? q.correct.join("\n") : "";
    return h("div", { class: "q-fields" }, [
      h("label", { class: "field" }, [h("span", { text: T.accepted_answers }), area, h("small", { class: "muted", text: T.accepted_answers_hint })])
    ]);
  }

  function renderNumber(q, hint) {
    var value = h("input", { type: "number", step: "any", dir: "ltr", value: q.correct && q.correct.value !== undefined ? q.correct.value : "" });
    var tol = h("input", { type: "number", step: "any", min: "0", dir: "ltr", value: q.correct && q.correct.tolerance ? q.correct.tolerance : "" });
    function sync() {
      if (value.value === "") q.correct = null;
      else q.correct = { value: parseFloat(value.value), tolerance: Math.abs(parseFloat(tol.value) || 0) };
      updateHint(q, hint);
      touch();
    }
    value.addEventListener("input", sync);
    tol.addEventListener("input", sync);
    return h("div", { class: "row-2" }, [
      h("label", { class: "field" }, [h("span", { text: T.numeric_answer }), value]),
      h("label", { class: "field" }, [h("span", { text: T.tolerance }), tol])
    ]);
  }

  function renderScale(q) {
    var max = h("select", { onchange: function () { q.options.max = parseInt(max.value, 10); touch(); } });
    for (var n = 3; n <= 10; n += 1) {
      var opt = h("option", { value: String(n), text: String(n) });
      if (q.options.max === n) opt.selected = true;
      max.appendChild(opt);
    }
    var lo = h("input", { type: "text", maxlength: "60", value: q.options.min_label || "", oninput: function () { q.options.min_label = lo.value; touch(); } });
    var hi = h("input", { type: "text", maxlength: "60", value: q.options.max_label || "", oninput: function () { q.options.max_label = hi.value; touch(); } });
    return h("div", { class: "q-fields" }, [
      h("label", { class: "field" }, [h("span", { text: T.scale_max }), max]),
      h("div", { class: "row-2" }, [
        h("label", { class: "field" }, [h("span", { text: T.scale_min_label }), lo]),
        h("label", { class: "field" }, [h("span", { text: T.scale_max_label }), hi])
      ])
    ]);
  }

  function lines(text) {
    return String(text || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function renderMatch(q, hint) {
    var wrap = h("div", { class: "pair-editor" });
    var headRow = h("div", { class: "pair-line pair-head" }, [
      h("span", { class: "muted small", text: T.match_left }), h("span"), h("span", { class: "muted small", text: T.match_right }), h("span")
    ]);
    wrap.appendChild(headRow);
    q.options.pairs.forEach(function (pair, index) {
      var left = h("input", { type: "text", maxlength: "300", value: pair[0], placeholder: (index + 1) + ".", "data-opt": index,
        oninput: function () { pair[0] = left.value; updateHint(q, hint); touch(); } });
      var right = h("input", { type: "text", maxlength: "300", value: pair[1], placeholder: String.fromCharCode(97 + (index % 26)) + ")",
        oninput: function () { pair[1] = right.value; updateHint(q, hint); touch(); },
        onkeydown: function (event) {
          if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); addPair(q); }
        } });
      var del = iconButton("x", T.remove, function () {
        if (q.options.pairs.length <= 1) return;
        q.options.pairs.splice(index, 1); touch(); render();
      }, { danger: true, disabled: q.options.pairs.length <= 1 });
      wrap.appendChild(h("div", { class: "pair-line" }, [left, h("span", { class: "pair-arrow", text: "⟷" }), right, del]));
    });
    var add = h("button", { type: "button", class: "chip", html: icon("plus", 14) + "<span></span>", onclick: function () { addPair(q); } });
    add.querySelector("span").textContent = T.add_pair;
    var extra = h("textarea", { rows: "2", placeholder: T.distractors,
      oninput: function () { q.options.distractors = lines(extra.value); touch(); } });
    extra.value = (q.options.distractors || []).join("\n");
    return h("div", { class: "q-fields" }, [
      wrap, h("div", {}, [add]),
      h("label", { class: "field" }, [h("span", { text: T.distractors }), extra, h("small", { class: "muted", text: T.distractors_hint })]),
      h("p", { class: "q-hint", text: T.partial_auto_note })
    ]);
  }

  function addPair(q) {
    if (q.options.pairs.length >= 40) return;
    q.options.pairs.push(["", ""]);
    pendingFocus = { q: q, opt: q.options.pairs.length - 1 };
    touch(); render();
  }

  function renderFill(q, hint) {
    var counter = h("small", { class: "muted" });
    var preview = h("div", { class: "fill-preview", dir: "auto" });
    function refresh() {
      var blanks = fillBlanks(q);
      counter.textContent = fmt(T.blanks_found, { n: blanks.length });
      preview.textContent = "";
      var text = q.options.template || "";
      var last = 0, m;
      BLANK_RE.lastIndex = 0;
      while ((m = BLANK_RE.exec(text))) {
        preview.appendChild(document.createTextNode(text.slice(last, m.index)));
        preview.appendChild(h("span", { class: "blank-chip", text: m[1].split("|")[0] }));
        last = m.index + m[0].length;
      }
      preview.appendChild(document.createTextNode(text.slice(last)));
      preview.hidden = !blanks.length;
      updateHint(q, hint);
    }
    var area = h("textarea", { rows: "5", dir: "auto", placeholder: T.fill_template,
      oninput: function () { q.options.template = area.value; refresh(); touch(); } });
    area.value = q.options.template || "";
    var bank = h("input", { type: "checkbox", onchange: function () { q.options.bank = bank.checked; touch(); } });
    bank.checked = !!q.options.bank;
    var extra = h("input", { type: "text", maxlength: "500", placeholder: T.distractors, value: (q.options.distractors || []).join(", "),
      oninput: function () { q.options.distractors = extra.value.split(/[,،]/).map(function (s) { return s.trim(); }).filter(Boolean); touch(); } });
    refresh();
    return h("div", { class: "q-fields" }, [
      h("label", { class: "field" }, [h("span", { text: T.fill_template }), area, h("small", { class: "muted", text: T.fill_template_hint }), counter]),
      preview,
      h("label", { class: "check", style: "margin:0" }, [bank, h("span", { text: T.word_bank })]),
      extra,
      h("p", { class: "q-hint", text: T.partial_auto_note })
    ]);
  }

  function renderOrder(q, hint) {
    var preview = h("div", { class: "chunk-preview", dir: "auto" });
    function refresh() {
      preview.textContent = "";
      var first = (q.correct || [])[0] || "";
      var chunks = first.indexOf("/") !== -1 ? first.split("/") : first.split(/\s+/);
      chunks.map(function (c) { return c.trim(); }).filter(Boolean).forEach(function (c) {
        preview.appendChild(h("span", { class: "chunk", text: c }));
      });
      preview.hidden = !preview.children.length;
      updateHint(q, hint);
    }
    var area = h("textarea", { rows: "2", dir: "auto", placeholder: T.order_answer,
      oninput: function () { var l = lines(area.value); q.correct = l.length ? l : null; refresh(); touch(); } });
    area.value = Array.isArray(q.correct) ? q.correct.join("\n") : "";
    refresh();
    return h("div", { class: "q-fields" }, [
      h("label", { class: "field" }, [h("span", { text: T.order_answer }), area, h("small", { class: "muted", text: T.order_answer_hint })]),
      h("div", {}, [h("small", { class: "muted", text: T.order_preview }), preview])
    ]);
  }

  function imageEditor(q) {
    var box = h("div", { class: "img-editor" });
    var input = h("input", { type: "file", accept: "image/*", hidden: true });
    var btn = h("button", { type: "button", class: "chip", html: icon("image", 14) + "<span></span>", onclick: function () { input.click(); } });
    btn.querySelector("span").textContent = q.image ? T.change_image : T.add_image;
    box.appendChild(btn);
    if (q.image) {
      var img = h("img", { src: data.mediaBase.replace("__NAME__", q.image), alt: "", class: "q-img-thumb" });
      var rm = h("button", { type: "button", class: "chip danger", text: T.remove_image, onclick: function () { q.image = ""; touch(); render(); } });
      box.insertBefore(img, btn);
      box.appendChild(rm);
    }
    box.appendChild(audioEditor(q));
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var body = new FormData();
      body.append("file", file);
      btn.querySelector("span").textContent = T.uploading;
      api(data.imageUrl, { body: body }).then(function (res) {
        if (!res.ok) { toast(res.error || T.image_error); render(); return; }
        q.image = res.name; touch(); render();
      }).catch(function () { toast(T.image_error); render(); });
    });
    box.appendChild(input);
    return box;
  }

  function uploadMedia(fileOrBlob, filename, done) {
    var body = new FormData();
    body.append("file", fileOrBlob, filename);
    api(data.imageUrl, { body: body }).then(function (res) {
      if (!res.ok) { toast(res.error || T.image_error); done(null); return; }
      done(res.name);
    }).catch(function () { toast(T.image_error); done(null); });
  }

  var recorder = null;
  function audioEditor(q) {
    var wrap = h("span", { class: "audio-box" });
    if (q.audio) {
      wrap.appendChild(h("audio", { controls: true, preload: "none", src: data.mediaBase.replace("__NAME__", q.audio) }));
      wrap.appendChild(h("button", { type: "button", class: "chip danger", text: T.remove_audio, onclick: function () { q.audio = ""; touch(); render(); } }));
      return wrap;
    }
    var file = h("input", { type: "file", accept: "audio/*", hidden: true });
    var pick = h("button", { type: "button", class: "chip", html: icon("music", 14) + "<span></span>", onclick: function () { file.click(); } });
    pick.querySelector("span").textContent = T.add_audio;
    file.addEventListener("change", function () {
      var f = file.files && file.files[0];
      if (!f) return;
      pick.querySelector("span").textContent = T.uploading;
      uploadMedia(f, f.name, function (name) { if (name) { q.audio = name; touch(); } render(); });
    });
    var rec = h("button", { type: "button", class: "chip", html: icon("mic", 14) + "<span></span>" });
    rec.querySelector("span").textContent = T.record_audio;
    rec.addEventListener("click", function () {
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
          var blob = new Blob(chunks, { type: type });
          rec.innerHTML = icon("mic", 14) + "<span></span>";
          rec.querySelector("span").textContent = T.uploading;
          uploadMedia(blob, "recording." + ext, function (name) { if (name) { q.audio = name; touch(); } render(); });
        };
        recorder.start();
        rec.innerHTML = '<span class="rec-dot"></span><span></span>';
        rec.querySelector("span:last-child").textContent = T.stop_recording;
      }).catch(function () { toast(T.mic_denied); });
    });
    wrap.appendChild(pick);
    wrap.appendChild(rec);
    wrap.appendChild(file);
    return wrap;
  }

  function summaryText(q) {
    var text = (q.text || "").split("\n")[0];
    return text || T.untitled_question;
  }

  function updateHint(q, hint) {
    if (!hint) return;
    hint.hidden = !lacksKey(q);
  }

  function renderCard(q, index) {
    var card = h("article", { class: cardClass(q), "data-index": index });
    var hint = h("p", { class: "q-hint warn", html: icon("alert", 14) + "<span></span>" });
    hint.querySelector("span").textContent = T.no_key_warning;
    updateHint(q, hint);

    var typeSelect = h("select", {
      class: "qtype", "aria-label": T.question_n.replace("{n}", index + 1),
      onchange: function () { changeType(q, typeSelect.value); touch(); render(); }
    });
    TYPES.forEach(function (type) {
      var o = h("option", { value: type, text: T["type_" + type] });
      if (type === q.type) o.selected = true;
      typeSelect.appendChild(o);
    });

    var insert = h("select", { class: "icon-select", title: T.insert_here, "aria-label": T.insert_here,
      onchange: function () {
        if (!insert.value) return;
        var nq = newQuestion(insert.value);
        questions.splice(index + 1, 0, nq);
        pendingFocus = { q: nq, scroll: true };
        touch(); render();
      } });
    insert.appendChild(h("option", { value: "", text: "＋" }));
    TYPES.forEach(function (type) { insert.appendChild(h("option", { value: type, text: T["type_" + type] })); });

    var grip = h("span", { class: "grip", title: T.drag_hint, html: icon("grip", 16) });
    grip.addEventListener("pointerdown", function (event) { startDrag(event, index, card); });

    var number = questions.slice(0, index + 1).filter(function (x) { return x.type !== "section"; }).length;
    var toggle = h("button", { type: "button", class: "q-summary", "aria-expanded": q._collapsed ? "false" : "true",
      onclick: function () { q._collapsed = !q._collapsed; render(); } });
    toggle.appendChild(h("span", { class: "q-summary-text", dir: "auto", text: summaryText(q) }));
    if (UNSCORED.indexOf(q.type) === -1) toggle.appendChild(h("span", { class: "badge gray", text: (q.points || 0) + " " + T.points }));
    if (lacksKey(q)) toggle.appendChild(h("span", { class: "badge amber", html: icon("alert", 12) }));

    var head = h("div", { class: "qcard-head" }, [
      grip,
      h("span", { class: "q-num" + (q.type === "section" ? " sec" : ""), text: q.type === "section" ? "§" : String(number) }),
      typeSelect,
      badgeFor(q),
      toggle,
      h("div", { class: "qcard-tools" }, [
        iconButton(q._collapsed ? "down" : "up", q._collapsed ? T.expand_all : T.collapse_all, function () { q._collapsed = !q._collapsed; render(); }, { extraClass: "collapse-btn" }),
        iconButton("up", T.move_up, function () { move(index, -1); }, { disabled: index === 0 }),
        iconButton("down", T.move_down, function () { move(index, 1); }, { disabled: index === questions.length - 1 }),
        iconButton("copy", T.duplicate, function () { duplicate(index); }),
        iconButton("bookmark", T.bank_save_one, function () { saveToBank(q); }),
        insert,
        iconButton("trash", T.remove, function () { remove(index); }, { danger: true })
      ])
    ]);

    var text = h("textarea", {
      rows: "2", maxlength: "1500", dir: "auto", placeholder: q.type === "section" ? T.section_title : T.question_text, "aria-label": T.question_text,
      "data-q-text": "1",
      oninput: function () { q.text = text.value; text.classList.remove("invalid"); touch(); }
    });
    text.value = q.text;
    var desc;
    if (q.type === "section") {
      desc = h("textarea", { rows: "5", maxlength: "6000", dir: "auto", placeholder: T.section_body, "aria-label": T.section_body,
        oninput: function () { q.description = desc.value; touch(); } });
      desc.value = q.description || "";
    } else {
      desc = h("input", {
        type: "text", maxlength: "1500", dir: "auto", placeholder: T.question_help, "aria-label": T.question_help, value: q.description,
        oninput: function () { q.description = desc.value; touch(); }
      });
    }

    var fields = h("div", { class: "q-fields" }, [text, h("small", { class: "fmt-hint", html: T.fmt_hint }), desc, imageEditor(q)]);

    var body = null;
    if (CHOICE.indexOf(q.type) !== -1) body = renderChoice(q, hint);
    else if (q.type === "truefalse") body = renderTrueFalse(q, hint);
    else if (q.type === "short") body = renderShort(q, hint);
    else if (q.type === "number") body = renderNumber(q, hint);
    else if (q.type === "scale") body = renderScale(q);
    else if (q.type === "match") body = renderMatch(q, hint);
    else if (q.type === "fill") body = renderFill(q, hint);
    else if (q.type === "order") body = renderOrder(q, hint);
    if (body) fields.appendChild(body);
    if (q.type === "section") fields.appendChild(h("p", { class: "q-hint", text: T.section_note }));

    if (q.type === "paragraph") fields.appendChild(h("p", { class: "q-hint", text: T.manual_grade_note }));
    if (GRADED.indexOf(q.type) !== -1 && q.manual_grade) fields.appendChild(h("p", { class: "q-hint warn", text: T.manual_key_hint }));
    if (q.type === "file") fields.appendChild(h("p", { class: "q-hint", text: T.file_upload_note }));
    if (q.type === "draw") {
      var linesBox = h("input", { type: "checkbox", onchange: function () { q.options.lines = linesBox.checked; touch(); } });
      linesBox.checked = q.options.lines !== false;
      var hSel = h("select", { onchange: function () { q.options.height = parseInt(hSel.value, 10); touch(); } });
      [[260, "S"], [380, "M"], [560, "L"], [800, "XL"]].forEach(function (o) {
        var opt = h("option", { value: String(o[0]), text: T.draw_height + ": " + o[1] });
        if (q.options.height === o[0]) opt.selected = true;
        hSel.appendChild(opt);
      });
      fields.appendChild(h("div", { class: "q-row" }, [h("label", { class: "check", style: "margin:0" }, [linesBox, h("span", { text: T.draw_lines })]), hSel]));
      fields.appendChild(h("p", { class: "q-hint", text: T.draw_note }));
    }
    if (UNSCORED.indexOf(q.type) !== -1 && q.type !== "section") fields.appendChild(h("p", { class: "q-hint", text: T.info_only_note }));
    if (GRADED.indexOf(q.type) !== -1) fields.appendChild(hint);

    var row = h("div", { class: "q-row" });
    if (UNSCORED.indexOf(q.type) === -1) {
      var points = h("input", {
        type: "number", min: "0", max: "1000", step: "any", dir: "ltr", value: q.points,
        "aria-label": T.points,
        oninput: function () { var n = parseFloat(points.value); q.points = isNaN(n) ? 0 : n; touch(); updateSummary(); }
      });
      row.appendChild(h("label", { class: "pts" }, [h("span", { text: T.points }), points]));
    }
    if (q.type !== "section") {
      var required = h("input", { type: "checkbox", checked: !!q.required, onchange: function () { q.required = required.checked; touch(); } });
      if (q.required) required.checked = true;
      row.appendChild(h("label", { class: "check switch", style: "margin:0" }, [required, h("span", { text: T.required })]));
    }
    if (GRADED.indexOf(q.type) !== -1) {
      var modeSel = h("div", { class: "grade-mode", role: "radiogroup", "aria-label": T.grading_mode });
      [["auto", T.grading_auto], ["manual", T.grading_manual]].forEach(function (m) {
        var b = h("button", { type: "button", class: "gm" + ((m[0] === "manual") === !!q.manual_grade ? " on" : ""), text: m[1],
          onclick: function () { q.manual_grade = m[0] === "manual"; touch(); render(); } });
        modeSel.appendChild(b);
      });
      row.appendChild(h("span", { class: "gm-label", text: T.grading_mode }));
      row.appendChild(modeSel);
    }
    if (q.type === "checkbox") {
      var partial = h("input", { type: "checkbox", checked: !!q.partial, onchange: function () { q.partial = partial.checked; touch(); } });
      if (q.partial) partial.checked = true;
      row.appendChild(h("label", { class: "check", style: "margin:0" }, [partial, h("span", { text: T.partial_credit })]));
    }
    if (GRADED.indexOf(q.type) !== -1 || MANUAL.indexOf(q.type) !== -1) {
      var explanation = h("input", {
        type: "text", maxlength: "2000", value: q.explanation,
        placeholder: T.explanation + " (" + T.explanation_hint + ")", "aria-label": T.explanation,
        oninput: function () { q.explanation = explanation.value; touch(); }
      });
      fields.appendChild(explanation);
    }

    if (row.children.length) fields.appendChild(row);
    card.appendChild(head);
    fields.classList.add("qcard-body");
    card.appendChild(fields);
    return card;
  }

  /* ---------- question bank ---------- */
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
  var bankItems = [];
  var bankPicked = {};
  var bankTimer = null;

  function bankCount() { $("bank-count").textContent = Object.keys(bankPicked).length; }

  function loadBank() {
    var params = ["q=" + encodeURIComponent($("bank-q").value.trim()), "type=" + encodeURIComponent($("bank-type").value),
      "subject=" + encodeURIComponent($("bank-subject").value), "grade=" + encodeURIComponent($("bank-grade").value)];
    var list = $("bank-list");
    list.textContent = T.loading;
    fetch(data.bankUrl + "?" + params.join("&"), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (res) {
      bankItems = res.items || [];
      [["bank-subject", res.subjects], ["bank-grade", res.grades]].forEach(function (pair) {
        var sel = $(pair[0]);
        if (sel.options.length <= 1) (pair[1] || []).forEach(function (v) { sel.appendChild(h("option", { value: v, text: v })); });
      });
      list.textContent = "";
      if (!bankItems.length) { list.appendChild(h("div", { class: "empty", text: T.bank_none_found })); return; }
      bankItems.forEach(function (item) {
        var box = h("input", { type: "checkbox", checked: !!bankPicked[item.bank_id], onchange: function () {
          if (box.checked) bankPicked[item.bank_id] = item; else delete bankPicked[item.bank_id];
          bankCount();
        } });
        if (bankPicked[item.bank_id]) box.checked = true;
        var meta = h("div", { class: "bank-meta" }, [h("span", { class: "badge blue", text: item.type_label })]);
        if (item.points) meta.appendChild(h("span", { class: "badge gray", text: item.points + " " + T.points }));
        if (item.subject) meta.appendChild(h("span", { class: "badge green", text: item.subject }));
        if (item.grade) meta.appendChild(h("span", { class: "badge green", text: item.grade }));
        if (item.image) meta.appendChild(h("span", { class: "badge gray", html: icon("image", 12) }));
        var body = h("div", { class: "bank-body" }, [meta, h("div", { class: "bank-text", dir: "auto", text: item.text })]);
        if (item.answer) body.appendChild(h("div", { class: "bank-answer small", dir: "auto", text: "✓ " + item.answer }));
        var row = h("label", { class: "card bank-item" }, [box, body]);
        if (item.image) row.appendChild(h("img", { class: "bank-img", src: data.mediaBase.replace("__NAME__", item.image), alt: "", loading: "lazy" }));
        list.appendChild(row);
      });
    }).catch(function () { list.textContent = T.save_failed; });
  }

  function openBank() {
    bankPicked = {};
    bankCount();
    bankModal.hidden = false;
    loadBank();
    $("bank-q").focus();
  }
  $("btn-bank").addEventListener("click", openBank);
  Array.prototype.forEach.call(document.querySelectorAll("[data-open-bank]"), function (b) { b.addEventListener("click", openBank); });
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
      var q = {
        id: null, type: it.type, text: it.text, description: it.description || "", image: it.image || "", audio: it.audio || "",
        points: it.points, required: it.type !== "section", options: JSON.parse(JSON.stringify(it.options)),
        correct: JSON.parse(JSON.stringify(it.correct)), explanation: it.explanation || "", partial: !!it.partial,
        manual_grade: !!it.manual_grade
      };
      questions.push(q);
      if (!first) first = q;
    });
    api(data.bankUsedUrl, { json: { ids: ids } });
    bankModal.hidden = true;
    pendingFocus = { q: first, scroll: true };
    touch();
    render();
    toast(fmt(T.bank_added, { n: ids.length }));
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !bankModal.hidden) bankModal.hidden = true; });

  /* pointer-based drag & drop: works with mouse, touch (iPad/phone) and pen */
  function startDrag(event, fromIndex, card) {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    var target = null;
    card.classList.add("dragging");
    document.body.classList.add("is-dragging");
    function cardAt(x, y) {
      var el = document.elementFromPoint(x, y);
      return el ? el.closest(".qcard") : null;
    }
    function move(e) {
      var over = cardAt(e.clientX, e.clientY);
      if (target && target !== over) target.classList.remove("drop-target");
      target = over && over !== card ? over : null;
      if (target) target.classList.add("drop-target");
      var edge = 70;
      if (e.clientY < edge) window.scrollBy(0, -14);
      else if (e.clientY > window.innerHeight - edge) window.scrollBy(0, 14);
    }
    function up() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      card.classList.remove("dragging");
      document.body.classList.remove("is-dragging");
      if (target) {
        target.classList.remove("drop-target");
        var to = parseInt(target.getAttribute("data-index"), 10);
        if (!isNaN(to) && to !== fromIndex) {
          var item = questions.splice(fromIndex, 1)[0];
          questions.splice(to, 0, item);
          touch();
          render();
        }
      }
    }
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  function render() {
    list.textContent = "";
    if (!questions.length) {
      list.appendChild(h("div", { class: "q-empty", text: T.no_questions }));
    } else {
      questions.forEach(function (q, i) { list.appendChild(renderCard(q, i)); });
    }
    updateSummary();
    if (pendingFocus) {
      var idx = questions.indexOf(pendingFocus.q);
      var card = list.children[idx];
      var target = null;
      if (card) {
        target = pendingFocus.opt !== undefined
          ? card.querySelector('[data-opt="' + pendingFocus.opt + '"]')
          : card.querySelector("[data-q-text]");
      }
      if (target) {
        target.focus({ preventScroll: pendingFocus.scroll === false });
        if (pendingFocus.scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      pendingFocus = null;
    }
  }

  function updateSummary() {
    var total = questions.reduce(function (sum, q) { return sum + (UNSCORED.indexOf(q.type) === -1 ? (parseFloat(q.points) || 0) : 0); }, 0);
    var shown = Math.round(total * 100) / 100;
    var count = questions.filter(function (q) { return q.type !== "section"; }).length;
    summary.textContent = count + " " + T.questions_count + " · " + T.total_points + ": " + shown;
  }

  /* ---------- actions ---------- */
  function move(index, delta) {
    var to = index + delta;
    if (to < 0 || to >= questions.length) return;
    var item = questions.splice(index, 1)[0];
    questions.splice(to, 0, item);
    pendingFocus = null;
    touch();
    render();
    list.children[to].scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function duplicate(index) {
    var copy = JSON.parse(JSON.stringify(questions[index]));
    copy.id = null;
    copy._collapsed = false;
    delete copy._k;
    questions.splice(index + 1, 0, copy);
    pendingFocus = { q: copy, scroll: true };
    touch();
    render();
  }

  function remove(index) {
    if (!window.confirm(T.confirm_delete_question)) return;
    questions.splice(index, 1);
    touch();
    render();
  }

  document.getElementById("add-bar").addEventListener("click", function (event) {
    var button = event.target.closest("[data-add]");
    if (!button) return;
    var q = newQuestion(button.getAttribute("data-add"));
    questions.push(q);
    pendingFocus = { q: q, scroll: true };
    touch();
    render();
  });

  list.addEventListener("focusin", function (event) {
    var card = event.target.closest(".qcard");
    Array.prototype.forEach.call(list.querySelectorAll(".qcard.focus"), function (el) { if (el !== card) el.classList.remove("focus"); });
    if (card) card.classList.add("focus");
  });

  /* ---------- settings ---------- */
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
    el.value = settings[key] === null || settings[key] === undefined ? "" : settings[key];
    el.addEventListener("input", function () { settings[key] = el.value === "" ? 0 : parseInt(el.value, 10) || 0; touch(); });
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
  $("btn-expand").addEventListener("click", function () { questions.forEach(function (q) { q._collapsed = false; }); render(); });

  /* ---------- tabs & share ---------- */
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
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); document.execCommand("copy"); done(); });
    } else {
      input.select();
      document.execCommand("copy");
      done();
    }
  });

  /* ---------- saving ---------- */
  function buildPayload() {
    return {
      settings: Object.assign({}, settings, { title: settings.title }),
      questions: questions.map(function (q) {
        var out = {
          id: q.id, type: q.type, text: q.text, description: q.description, image: q.image || "", audio: q.audio || "", points: q.points,
          required: !!q.required, explanation: q.explanation, partial: !!q.partial, manual_grade: !!q.manual_grade,
          options: q.options, correct: q.correct
        };
        if (q.type === "match") {
          out.options = {
            pairs: (q.options.pairs || []).filter(function (p) { return String(p[0]).trim() && String(p[1]).trim(); }),
            distractors: q.options.distractors || []
          };
        }
        if (CHOICE.indexOf(q.type) !== -1) {
          var keep = [];
          var remap = {};
          q.options.forEach(function (text, i) {
            if (String(text).trim()) { remap[i] = keep.length; keep.push(text); }
          });
          out.options = keep;
          if (Array.isArray(q.correct)) {
            out.correct = q.correct.filter(function (i) { return remap[i] !== undefined; }).map(function (i) { return remap[i]; });
          } else if (typeof q.correct === "number") {
            out.correct = remap[q.correct] !== undefined ? remap[q.correct] : null;
          }
        }
        return out;
      })
    };
  }

  function focusQuestion(index) {
    var card = list.children[index];
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    var field = card.querySelector("[data-q-text]");
    if (field) field.focus({ preventScroll: true });
    card.classList.add("focus");
  }

  function save() {
    clearTimeout(saveTimer);
    if (saving) {
      return new Promise(function (resolve) {
        var wait = setInterval(function () {
          if (!saving) { clearInterval(wait); resolve(save()); }
        }, 120);
      });
    }
    if (revision === savedRevision && arguments.length === 0 && questions.every(function (q) { return q.id; })) {
      return Promise.resolve(true);
    }
    saving = true;
    var startRevision = revision;
    setSaveState(T.saving);
    return api(builder.getAttribute("data-save-url"), { json: buildPayload() })
      .then(function (res) {
        saving = false;
        if (!res.ok) {
          setSaveState(T.save_failed, true);
          if (res.error) toast(res.error);
          if (typeof res.index === "number") {
            tabTo("questions");
            focusQuestion(res.index);
          }
          return false;
        }
        (res.ids || []).forEach(function (id, i) { if (questions[i]) questions[i].id = id; });
        savedRevision = startRevision;
        setSaveState(revision === startRevision ? T.saved : T.unsaved);
        if (revision !== startRevision) saveTimer = setTimeout(function () { save(); }, 1500);
        return true;
      })
      .catch(function () {
        saving = false;
        setSaveState(T.save_failed, true);
        return false;
      });
  }

  function tabTo(name) {
    var tab = document.querySelector('[data-tab="' + name + '"]');
    if (tab) tab.click();
  }

  $("btn-save").addEventListener("click", function () { save(true); });

  Array.prototype.forEach.call(document.querySelectorAll("[data-save-first], #btn-preview"), function (button) {
    button.addEventListener("click", function (event) {
      var form = button.closest("form");
      if (!form) return;
      event.preventDefault();
      save(true).then(function (ok) { if (ok) form.submit(); });
    });
  });

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      save(true);
    }
  });

  window.addEventListener("beforeunload", function (event) {
    if (revision !== savedRevision) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  /* ---------- init ---------- */
  if (questions.length > 12) questions.forEach(function (q) { q._collapsed = true; });
  render();
  if (location.hash === "#settings" || location.hash === "#share") tabTo(location.hash.slice(1));
  setSaveState("");
})();
