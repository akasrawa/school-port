(function () {
  "use strict";

  var root = document.getElementById("take");
  if (!root) return;

  var cfg = JSON.parse(root.getAttribute("data-config"));
  var I18N = window.I18N || {};
  var api = window.App.api;
  var cards = Array.prototype.slice.call(root.querySelectorAll(".question"));
  var saveState = document.getElementById("save-state");
  var progressText = document.getElementById("progress-text");
  var progressBar = document.getElementById("progress-bar");
  var finished = false;
  var submitting = false;
  var dirty = false;
  var saving = false;
  var saveTimer = null;
  var filePickerOpen = false;

  function $(id) { return document.getElementById(id); }
  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }
  function fmt(text, values) {
    return String(text || "").replace(/\{(\w+)\}/g, function (m, key) {
      return values && values[key] !== undefined ? values[key] : m;
    });
  }

  /* ---------- reading answers ---------- */
  function readValue(card) {
    var type = card.getAttribute("data-type");
    var qid = card.getAttribute("data-qid");
    if (type === "file" || type === "draw") return undefined;
    if (type === "match") {
      return Array.prototype.map.call(card.querySelectorAll("select[data-match]"), function (el) { return el.value; });
    }
    if (type === "fill") {
      return Array.prototype.map.call(card.querySelectorAll("input[data-blank]"), function (el) { return el.value; });
    }
    if (type === "checkbox") {
      return Array.prototype.map.call(
        card.querySelectorAll('input[type="checkbox"]:checked'),
        function (input) { return parseInt(input.value, 10); }
      );
    }
    if (type === "mcq" || type === "truefalse" || type === "scale") {
      var checked = card.querySelector('input[name="q' + qid + '"]:checked');
      return checked ? checked.value : "";
    }
    var field = card.querySelector("[name='q" + qid + "']");
    return field ? field.value : "";
  }

  function isAnswered(card) {
    var type = card.getAttribute("data-type");
    if (type === "file" || type === "draw") {
      var name = card.querySelector("[data-file-name]");
      return !!(name && name.textContent.trim());
    }
    var value = readValue(card);
    if (type === "match" || type === "fill") {
      return value.length > 0 && value.every(function (v) { return String(v || "").trim() !== ""; });
    }
    if (Array.isArray(value)) return value.length > 0;
    return String(value || "").trim() !== "";
  }

  /* ---------- word bank (fill in the blanks) ---------- */
  var lastBlank = null;
  root.addEventListener("focusin", function (event) {
    if (event.target.matches && event.target.matches("input[data-blank]")) lastBlank = event.target;
  });
  function markBank(card) {
    if (!card) return;
    var used = Array.prototype.map.call(card.querySelectorAll("input[data-blank]"), function (el) { return el.value.trim().toLowerCase(); });
    Array.prototype.forEach.call(card.querySelectorAll(".bank-word"), function (w) {
      w.classList.toggle("used", used.indexOf(w.getAttribute("data-word").toLowerCase()) !== -1);
    });
  }
  Array.prototype.forEach.call(root.querySelectorAll('.question[data-type="fill"]'), markBank);
  function sizeBlank(input) {
    markBank(input.closest(".question"));
    input.style.width = Math.max(5, Math.min(28, (input.value || "").length + 2)) + "ch";
  }
  Array.prototype.forEach.call(root.querySelectorAll("input[data-blank]"), sizeBlank);
  root.addEventListener("input", function (event) {
    if (event.target.matches && event.target.matches("input[data-blank]")) sizeBlank(event.target);
    if (event.target.matches && event.target.matches("select[data-match]")) event.target.classList.toggle("filled", !!event.target.value);
  });
  root.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("select[data-match]")) event.target.classList.toggle("filled", !!event.target.value);
  });
  root.addEventListener("click", function (event) {
    var word = event.target.closest(".bank-word");
    if (!word) return;
    var card = word.closest(".question");
    var target = lastBlank && card.contains(lastBlank) && !lastBlank.value ? lastBlank : null;
    if (!target) {
      target = Array.prototype.filter.call(card.querySelectorAll("input[data-blank]"), function (el) { return !el.value; })[0];
    }
    if (!target && lastBlank && card.contains(lastBlank)) target = lastBlank;
    if (!target) return;
    target.value = word.getAttribute("data-word");
    sizeBlank(target);
    var blanks = card.querySelectorAll("input[data-blank]");
    var next = Array.prototype.filter.call(blanks, function (el) { return !el.value; })[0];
    if (next) { next.focus({ preventScroll: true }); lastBlank = next; }
    updateProgress();
    scheduleSave();
  });

  /* ---------- reorder words ---------- */
  function setupOrder(box) {
    var answer = box.querySelector("[data-order-answer]");
    var hidden = box.querySelector('input[type="hidden"]');
    var pool = Array.prototype.slice.call(box.querySelectorAll("[data-chunk]"));
    var chosen = [];
    function sync(save) {
      Array.prototype.forEach.call(answer.querySelectorAll(".chunk-btn"), function (el) { el.remove(); });
      chosen.forEach(function (btn) {
        var clone = document.createElement("button");
        clone.type = "button";
        clone.className = "chunk-btn picked";
        clone.textContent = btn.textContent;
        clone.addEventListener("click", function () {
          chosen.splice(chosen.indexOf(btn), 1);
          sync(true);
        });
        answer.appendChild(clone);
      });
      pool.forEach(function (btn) { btn.classList.toggle("used", chosen.indexOf(btn) !== -1); btn.disabled = chosen.indexOf(btn) !== -1; });
      answer.querySelector(".order-ph").hidden = chosen.length > 0;
      hidden.value = chosen.map(function (b) { return b.textContent.trim(); }).join(" ");
      if (save) { updateProgress(); scheduleSave(); }
    }
    pool.forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (chosen.indexOf(btn) === -1) { chosen.push(btn); sync(true); }
      });
    });
    box.querySelector("[data-order-reset]").addEventListener("click", function () { chosen = []; sync(true); });
    /* rebuild a saved answer */
    var rest = (hidden.value || "").trim();
    var guard = 0;
    while (rest && guard < 60) {
      guard += 1;
      var best = null;
      pool.forEach(function (btn) {
        var text = btn.textContent.trim();
        if (chosen.indexOf(btn) !== -1) return;
        if ((rest === text || rest.indexOf(text + " ") === 0) && (!best || text.length > best.textContent.trim().length)) best = btn;
      });
      if (!best) break;
      chosen.push(best);
      rest = rest.slice(best.textContent.trim().length).trim();
    }
    sync(false);
  }
  Array.prototype.forEach.call(root.querySelectorAll("[data-order]"), setupOrder);

  function collect() {
    var answers = {};
    cards.forEach(function (card) {
      var value = readValue(card);
      if (value !== undefined) answers[card.getAttribute("data-qid")] = value;
    });
    return answers;
  }

  /* ---------- progress ---------- */
  function updateProgress() {
    var done = 0;
    cards.forEach(function (card) {
      var answered = isAnswered(card);
      if (answered) {
        done += 1;
        card.classList.remove("unanswered");
        var err = card.querySelector(".q-error");
        if (err) err.hidden = true;
      }
      var dot = document.querySelector('[data-nav="' + card.getAttribute("data-qid") + '"]');
      if (dot) {
        dot.classList.toggle("done", answered);
        if (answered) dot.classList.remove("missing");
      }
    });
    if (progressText) progressText.textContent = done + "/" + cards.length;
    if (progressBar) progressBar.style.width = (cards.length ? (done / cards.length) * 100 : 0) + "%";
    return done;
  }

  /* ---------- saving ---------- */
  function setSaveState(text, isError) {
    if (!saveState) return;
    saveState.textContent = text || "";
    saveState.classList.toggle("err", !!isError);
  }

  function goTo(url) {
    finished = true;
    window.location.href = url;
  }

  function save(keepalive) {
    if (finished || submitting) return Promise.resolve();
    if (saving && !keepalive) return Promise.resolve();
    clearTimeout(saveTimer);
    saving = true;
    dirty = false;
    setSaveState(I18N.saving);
    return api(cfg.saveUrl, { json: { answers: collect() }, keepalive: !!keepalive })
      .then(function (data) {
        saving = false;
        if (data.done && data.redirect) return goTo(data.redirect);
        if (!data.ok) throw new Error("save");
        if (typeof data.remaining === "number") syncClock(data.remaining);
        setSaveState(I18N.saved);
        if (dirty) scheduleSave();
      })
      .catch(function () {
        saving = false;
        dirty = true;
        setSaveState(navigator.onLine ? I18N.save_failed : I18N.offline, true);
      });
  }

  function scheduleSave() {
    dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save(false); }, 1200);
  }

  root.addEventListener("input", function (event) {
    if (event.target.type === "file") return;
    updateProgress();
    scheduleSave();
  });
  root.addEventListener("change", function (event) {
    if (event.target.type === "file") return;
    updateProgress();
    scheduleSave();
  });

  setInterval(function () { if (dirty && !saving) save(false); }, 15000);
  window.addEventListener("online", function () { if (dirty) save(false); });
  window.addEventListener("offline", function () { setSaveState(I18N.offline, true); });
  window.addEventListener("pagehide", function () { if (dirty) save(true); });

  /* ---------- file uploads ---------- */
  root.addEventListener("click", function (event) {
    if (event.target.closest(".file-drop label")) filePickerOpen = true;
  });
  window.addEventListener("focus", function () {
    setTimeout(function () { filePickerOpen = false; }, 600);
  });
  root.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("[data-file-q]")) return;
    var file = input.files && input.files[0];
    if (!file) return;
    var qid = input.getAttribute("data-file-q");
    var nameEl = $("fname-" + qid);
    var body = new FormData();
    body.append("file", file);
    nameEl.textContent = I18N.uploading;
    nameEl.style.color = "";
    api(cfg.uploadUrl.replace(/\/0$/, "/" + qid), { body: body })
      .then(function (data) {
        if (data.done && data.redirect) return goTo(data.redirect);
        if (!data.ok) throw new Error(data.error || "upload");
        nameEl.textContent = data.name;
        updateProgress();
      })
      .catch(function (err) {
        nameEl.textContent = "";
        window.App.toast(err && err.message && err.message !== "upload" ? err.message : I18N.save_failed);
      })
      .then(function () { filePickerOpen = false; });
  });

  /* ---------- matching with tap cards ---------- */
  function setupMatch(board) {
    var rows = Array.prototype.slice.call(board.querySelectorAll(".match-row"));
    var unique = board.getAttribute("data-unique") === "1";
    var active = 0;
    function sel(i) { return rows[i].querySelector("select"); }
    function firstEmpty() {
      for (var i = 0; i < rows.length; i += 1) if (!sel(i).value) return i;
      return -1;
    }
    function sync() {
      var used = {};
      rows.forEach(function (row, i) {
        var value = sel(i).value;
        var shown = row.querySelector(".slot-value");
        var card = null;
        Array.prototype.forEach.call(board.querySelectorAll(".match-choice"), function (b) { if (value && b.getAttribute("data-choice") === value) card = b; });
        if (card) {
          shown.innerHTML = card.innerHTML;
          var letter = shown.querySelector(".choice-letter");
          if (letter) letter.remove();
        } else {
          shown.textContent = value;
        }
        row.classList.toggle("filled", !!value);
        row.classList.toggle("active", i === active);
        if (value) used[value] = true;
      });
      Array.prototype.forEach.call(board.querySelectorAll(".match-choice"), function (btn) {
        btn.classList.toggle("used", unique && !!used[btn.getAttribute("data-choice")]);
      });
    }
    function setValue(i, value) {
      var s = sel(i);
      s.value = value;
      s.classList.toggle("filled", !!value);
      s.dispatchEvent(new Event("change", { bubbles: true }));
    }
    board.addEventListener("click", function (e) {
      var slot = e.target.closest(".match-slot");
      var row = e.target.closest(".match-row");
      var choice = e.target.closest(".match-choice");
      if (slot) {
        var i = parseInt(slot.getAttribute("data-slot"), 10);
        if (i === active && sel(i).value) setValue(i, "");
        active = i;
        sync();
        return;
      }
      if (row) { active = parseInt(row.getAttribute("data-row"), 10); sync(); return; }
      if (choice) {
        if (active < 0) active = firstEmpty();
        if (active < 0) active = rows.length - 1;
        var value = choice.getAttribute("data-choice");
        if (unique) {
          rows.forEach(function (r, j) { if (j !== active && sel(j).value === value) setValue(j, ""); });
        }
        setValue(active, value);
        var next = firstEmpty();
        active = next >= 0 ? next : active;
        sync();
      }
    });
    board.addEventListener("change", sync);
    active = Math.max(0, firstEmpty());
    sync();
  }
  Array.prototype.forEach.call(root.querySelectorAll("[data-match-board]"), setupMatch);

  /* ---------- star rating ---------- */
  Array.prototype.forEach.call(root.querySelectorAll("[data-stars]"), function (box) {
    function paint() {
      var checked = box.querySelector("input:checked");
      var value = checked ? parseInt(checked.value, 10) : 0;
      Array.prototype.forEach.call(box.querySelectorAll(".scale-opt"), function (label, i) { label.classList.toggle("on", i < value); });
    }
    box.addEventListener("change", paint);
    paint();
  });

  /* ---------- handwriting (draw) ---------- */
  var LOGICAL_W = 1000;
  var drawFlushers = [];
  function setupDraw(box) {
    var qid = box.getAttribute("data-draw");
    var canvas = box.querySelector("canvas");
    var pad = box.querySelector(".draw-pad");
    var state = box.querySelector("[data-draw-state]");
    var nameEl = box.querySelector("[data-file-name]");
    var bgUrl = box.getAttribute("data-bg");  /* drawing on the question picture */
    var bg = null;
    var lines = !bgUrl && box.getAttribute("data-lines") === "1";
    var LOGICAL_H = Math.round(parseInt(box.getAttribute("data-height"), 10) * LOGICAL_W / 720) || 520;
    var ctx = canvas.getContext("2d");
    var strokes = [];
    var base = null;
    var current = null;
    var tool = "pen", color = "#111827", size = 3.5;
    var uploadTimer = null, dirtyDraw = false, uploading = false;
    var scale = 1;

    function resize() {
      var cssW = pad.clientWidth || 600;
      var cssH = cssW * LOGICAL_H / LOGICAL_W;
      var dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      canvas.style.height = cssH + "px";
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      scale = canvas.width / LOGICAL_W;
      if (lines) {
        var gap = 64 * cssW / LOGICAL_W;
        pad.style.backgroundImage = "repeating-linear-gradient(to bottom, transparent 0, transparent " + (gap - 1) + "px, #cbd5e1 " + (gap - 1) + "px, #cbd5e1 " + gap + "px)";
      }
      paint(ctx, scale);
    }

    function drawStroke(c, st, k) {
      if (!st.points.length) return;
      c.save();
      c.globalCompositeOperation = st.eraser ? "destination-out" : "source-over";
      c.strokeStyle = st.color;
      c.fillStyle = st.color;
      c.lineWidth = (st.eraser ? st.size * 5 : st.size) * k;
      c.lineCap = "round";
      c.lineJoin = "round";
      var p = st.points;
      if (p.length === 1) {
        c.beginPath();
        c.arc(p[0][0] * k, p[0][1] * k, c.lineWidth / 2, 0, Math.PI * 2);
        c.fill();
      } else {
        c.beginPath();
        c.moveTo(p[0][0] * k, p[0][1] * k);
        for (var i = 1; i < p.length - 1; i += 1) {
          var mx = (p[i][0] + p[i + 1][0]) / 2, my = (p[i][1] + p[i + 1][1]) / 2;
          c.quadraticCurveTo(p[i][0] * k, p[i][1] * k, mx * k, my * k);
        }
        c.lineTo(p[p.length - 1][0] * k, p[p.length - 1][1] * k);
        c.stroke();
      }
      c.restore();
    }

    function paint(c, k) {
      c.clearRect(0, 0, c.canvas.width, c.canvas.height);
      if (base) c.drawImage(base, 0, 0, LOGICAL_W * k, LOGICAL_H * k);
      strokes.forEach(function (st) { drawStroke(c, st, k); });
      if (current) drawStroke(c, current, k);
    }

    function exportBlob(cb) {
      var layer = document.createElement("canvas");
      layer.width = LOGICAL_W; layer.height = LOGICAL_H;
      paint(layer.getContext("2d"), 1);
      var out = document.createElement("canvas");
      out.width = LOGICAL_W; out.height = LOGICAL_H;
      var o = out.getContext("2d");
      o.fillStyle = "#fff";
      o.fillRect(0, 0, LOGICAL_W, LOGICAL_H);
      if (bg) o.drawImage(bg, 0, 0, LOGICAL_W, LOGICAL_H);  /* the teacher sees the marks on the picture */
      if (lines) {
        o.strokeStyle = "#cbd5e1"; o.lineWidth = 1.5;
        for (var y = 64; y < LOGICAL_H; y += 64) { o.beginPath(); o.moveTo(0, y); o.lineTo(LOGICAL_W, y); o.stroke(); }
      }
      o.drawImage(layer, 0, 0);
      out.toBlob(cb, "image/png");
    }

    function setState(text) { if (state) state.textContent = text || ""; }

    function upload(clear) {
      if (finished) return;
      clearTimeout(uploadTimer);
      if (uploading) { uploadTimer = setTimeout(function () { upload(clear); }, 800); return; }
      uploading = true; dirtyDraw = false;
      setState(I18N.saving);
      var send = function (blob) {
        var body = new FormData();
        if (clear) body.append("clear", "1");
        body.append("file", blob || new Blob([""], { type: "image/png" }), "handwriting.png");
        api(cfg.uploadUrl.replace(/\/0$/, "/" + qid), { body: body })
          .then(function (data) {
            uploading = false;
            if (data.done && data.redirect) return goTo(data.redirect);
            if (!data.ok) throw new Error(data.error || "upload");
            nameEl.textContent = clear ? "" : "handwriting.png";
            setState(I18N.saved);
            updateProgress();
            if (dirtyDraw) upload(false);
          })
          .catch(function () { uploading = false; dirtyDraw = true; setState(I18N.save_failed); });
      };
      if (clear) send(null); else exportBlob(send);
    }

    function schedule() {
      dirtyDraw = true;
      clearTimeout(uploadTimer);
      uploadTimer = setTimeout(function () { upload(false); }, 1200);
    }

    function point(e) {
      var r = canvas.getBoundingClientRect();
      return [(e.clientX - r.left) * LOGICAL_W / r.width, (e.clientY - r.top) * LOGICAL_H / r.height];
    }
    canvas.addEventListener("pointerdown", function (e) {
      if (finished) return;
      e.preventDefault();
      canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
      var pressure = e.pointerType === "pen" && e.pressure ? 0.6 + e.pressure : 1;
      current = { color: color, size: size * pressure, eraser: tool === "eraser", points: [point(e)] };
      paint(ctx, scale);
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!current) return;
      e.preventDefault();
      var evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
      evs.forEach(function (ev) { current.points.push(point(ev)); });
      paint(ctx, scale);
    });
    function end() {
      if (!current) return;
      strokes.push(current);
      current = null;
      paint(ctx, scale);
      nameEl.textContent = "handwriting.png";
      updateProgress();
      schedule();
    }
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") end(); });

    box.addEventListener("click", function (e) {
      var tb = e.target.closest("[data-tool]");
      if (tb) {
        tool = tb.getAttribute("data-tool");
        box.querySelectorAll("[data-tool]").forEach(function (b) { b.classList.toggle("on", b === tb); });
      }
      var sw = e.target.closest("[data-color]");
      if (sw) {
        color = sw.getAttribute("data-color");
        tool = "pen";
        box.querySelectorAll("[data-color]").forEach(function (b) { b.classList.toggle("on", b === sw); });
        box.querySelectorAll("[data-tool]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-tool") === "pen"); });
      }
      var act = e.target.closest("[data-act]");
      if (act && act.getAttribute("data-act") === "undo") {
        if (strokes.length) { strokes.pop(); paint(ctx, scale); schedule(); }
      } else if (act && act.getAttribute("data-act") === "clear") {
        if (!strokes.length && !base) return;
        if (!window.confirm(I18N.draw_clear_confirm)) return;
        strokes = []; base = null; paint(ctx, scale);
        nameEl.textContent = "";
        updateProgress();
        upload(true);
      }
    });
    box.querySelector(".draw-size").addEventListener("change", function (e) { size = parseFloat(e.target.value) || 3.5; });

    drawFlushers.push(function () {
      if (dirtyDraw && !uploading) upload(false);
      return dirtyDraw || uploading;
    });
    window.addEventListener("resize", function () { clearTimeout(box._rt); box._rt = setTimeout(resize, 150); });
    window.addEventListener("pagehide", function () { if (dirtyDraw) upload(false); });
    if (box.getAttribute("data-has") === "1") {
      var img = new Image();
      img.onload = function () { base = img; paint(ctx, scale); };
      img.src = cfg.fileUrl.replace(/\/0$/, "/" + qid) + "?t=" + Date.now();
    }
    if (bgUrl) {
      box.classList.add("on-img");
      var pic = new Image();
      pic.onload = function () {
        bg = pic;
        LOGICAL_H = Math.max(200, Math.min(2400, Math.round(LOGICAL_W * pic.naturalHeight / Math.max(1, pic.naturalWidth))));
        pad.style.backgroundImage = "url(\"" + bgUrl + "\")";
        pad.style.backgroundSize = "100% 100%";
        resize();
      };
      pic.src = bgUrl;
    }
    resize();
  }
  Array.prototype.forEach.call(root.querySelectorAll("[data-draw]"), setupDraw);

  /* ---------- submit ---------- */
  var confirmModal = $("confirm-modal");

  function openConfirm() {
    var done = updateProgress();
    var left = cards.length - done;
    $("confirm-text").textContent = left > 0 ? fmt(I18N.confirm_unanswered, { n: left }) : I18N.confirm_all;
    show(confirmModal);
    $("confirm-ok").focus();
  }

  function markMissing(ids) {
    var first = null;
    ids.forEach(function (id) {
      var card = $("q-" + id);
      if (!card) return;
      card.classList.add("unanswered");
      var err = card.querySelector(".q-error");
      if (err) err.hidden = false;
      var dot = document.querySelector('[data-nav="' + id + '"]');
      if (dot) dot.classList.add("missing");
      if (!first) first = card;
    });
    if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function submit(auto, tries) {
    if (finished || submitting) return;
    var busy = drawFlushers.map(function (f) { return f(); }).some(Boolean);
    if (busy && (tries || 0) < 12) {
      setSaveState(I18N.saving);
      setTimeout(function () { submit(auto, (tries || 0) + 1); }, 500);
      return;
    }
    submitting = true;
    clearTimeout(saveTimer);
    hide(confirmModal);
    setSaveState(I18N.submitting);
    var buttons = [$("btn-submit"), $("btn-submit-2"), $("confirm-ok")];
    buttons.forEach(function (b) { if (b) b.disabled = true; });
    api(cfg.submitUrl, { json: { answers: collect(), auto: !!auto } })
      .then(function (data) {
        if (data.ok && data.redirect) return goTo(data.redirect);
        if (data.done && data.redirect) return goTo(data.redirect);
        submitting = false;
        buttons.forEach(function (b) { if (b) b.disabled = false; });
        setSaveState("");
        if (data.missing) markMissing(data.missing);
        if (data.error) window.App.toast(data.error);
      })
      .catch(function () {
        submitting = false;
        buttons.forEach(function (b) { if (b) b.disabled = false; });
        setSaveState(I18N.save_failed, true);
      });
  }

  ["btn-submit", "btn-submit-2"].forEach(function (id) {
    var btn = $(id);
    if (btn) btn.addEventListener("click", openConfirm);
  });
  $("confirm-ok").addEventListener("click", function () { submit(false); });
  $("confirm-cancel").addEventListener("click", function () { hide(confirmModal); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !confirmModal.hidden) hide(confirmModal);
  });

  /* ---------- timer ---------- */
  var timerEl = $("timer");
  var timerText = $("timer-text");
  var deadline = null;

  function syncClock(seconds) {
    if (seconds === null || seconds === undefined) return;
    deadline = Date.now() + seconds * 1000;
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  function tick() {
    if (deadline === null || finished) return;
    var left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    var h = Math.floor(left / 3600);
    var m = Math.floor((left % 3600) / 60);
    var s = left % 60;
    timerText.textContent = (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(s);
    timerEl.classList.toggle("low", left <= 300 && left > 60);
    timerEl.classList.toggle("critical", left <= 60);
    if (left <= 0 && !submitting) {
      hide(confirmModal);
      show($("done-modal"));
      submit(true);
    }
  }

  if (cfg.remaining !== null && cfg.remaining !== undefined) {
    syncClock(cfg.remaining);
    tick();
    setInterval(tick, 500);
  }

  /* ---------- integrity ---------- */
  var violations = cfg.violations || 0;
  var lastEventAt = {};
  var warnModal = $("warn-modal");

  function renderViolations() {
    var chip = $("viol-chip");
    if (!chip || !cfg.maxViolations) return;
    chip.hidden = violations === 0;
    $("viol-text").textContent = I18N.violations + ": " + violations + "/" + cfg.maxViolations;
  }

  function reportEvent(type, counted, detail) {
    if (finished || submitting) return;
    var now = Date.now();
    if (lastEventAt[type] && now - lastEventAt[type] < 1500) return;
    lastEventAt[type] = now;
    api(cfg.eventUrl, { json: { type: type, detail: detail || "" } })
      .then(function (data) {
        if (data.done && data.redirect) return goTo(data.redirect);
        if (!data.ok) return;
        if (typeof data.violations === "number") violations = data.violations;
        renderViolations();
        if (data.terminated && data.redirect) {
          $("warn-text").textContent = I18N.violation_term;
          hide($("warn-ok"));
          show(warnModal);
          setTimeout(function () { goTo(data.redirect); }, 1800);
          return;
        }
        if (counted) {
          var text = I18N.violation_text;
          if (cfg.maxViolations) {
            text += " " + fmt(I18N.violation_left, { left: Math.max(0, cfg.maxViolations - violations) });
          }
          $("warn-text").textContent = text;
          show($("warn-ok"));
          show(warnModal);
          $("warn-ok").focus();
        }
      })
      .catch(function () {});
  }

  $("warn-ok").addEventListener("click", function () { hide(warnModal); });
  renderViolations();

  if (cfg.detectTabs) {
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) reportEvent("tab_hidden", true);
    });
    window.addEventListener("blur", function () {
      setTimeout(function () {
        if (document.hidden || filePickerOpen || document.hasFocus()) return;
        if (lastEventAt.tab_hidden && Date.now() - lastEventAt.tab_hidden < 3000) return;
        reportEvent("window_blur", true);
      }, 350);
    });
  }

  if (cfg.blockCopy) {
    document.body.classList.add("no-copy");
    var blocked = { copy: "copy_attempt", cut: "copy_attempt", paste: "paste_attempt", contextmenu: "menu_attempt" };
    Object.keys(blocked).forEach(function (name) {
      document.addEventListener(name, function (event) {
        event.preventDefault();
        reportEvent(blocked[name], false);
      });
    });
    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && ["c", "x", "v", "p", "s", "u"].indexOf(event.key.toLowerCase()) !== -1) {
        event.preventDefault();
        reportEvent("copy_attempt", false);
      }
    });
  }

  if (cfg.fullscreen) {
    var fsModal = $("fs-modal");
    var inFullscreen = function () { return !!document.fullscreenElement; };
    var needFullscreen = function () { if (!inFullscreen() && !finished) show(fsModal); };
    $("fs-ok").addEventListener("click", function () {
      var el = document.documentElement;
      var request = el.requestFullscreen || el.webkitRequestFullscreen;
      var result = request ? request.call(el) : null;
      var done = function () { hide(fsModal); };
      if (result && result.then) result.then(done, done);
      else done();
    });
    document.addEventListener("fullscreenchange", function () {
      if (inFullscreen()) {
        hide(fsModal);
        reportEvent("fullscreen_enter", false);
      } else if (!finished && !submitting) {
        reportEvent("fullscreen_exit", true);
        show(fsModal);
      }
    });
    needFullscreen();
  }

  /* ---------- init ---------- */
  updateProgress();
})();
