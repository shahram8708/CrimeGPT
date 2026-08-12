(function () {
  "use strict";

  document.querySelectorAll(".alert-dismissible.alert-success, .alert-dismissible.alert-info").forEach(function (el) {
    window.setTimeout(function () {
      var btn = el.querySelector(".btn-close");
      if (btn) btn.click();
    }, 5000);
  });

  document.querySelectorAll("[data-password-toggle]").forEach(function (toggle) {
    toggle.addEventListener("click", function () {
      var input = document.getElementById(toggle.getAttribute("data-password-toggle"));
      if (!input) return;
      var show = input.getAttribute("type") === "password";
      input.setAttribute("type", show ? "text" : "password");
      toggle.textContent = show ? (toggle.getAttribute("data-hide") || "Hide") : (toggle.getAttribute("data-show") || "Show");
      toggle.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });
  var legacy = document.getElementById("toggle-password");
  var pwd = document.getElementById("password");
  if (legacy && pwd && !legacy.getAttribute("data-password-toggle")) {
    legacy.setAttribute("data-password-toggle", "password");
  }

  function scorePassword(value) {
    if (!value) return 0;
    var s = 0;
    if (value.length >= 8) s += 1;
    if (value.length >= 12) s += 1;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) s += 1;
    if (/\d/.test(value) && /[^A-Za-z0-9]/.test(value)) s += 1;
    return Math.max(0, Math.min(4, s));
  }
  document.querySelectorAll(".js-pw-meter").forEach(function (input) {
    var meter = input.closest("form").querySelector(".pw-meter");
    if (!meter) return;
    var segs = meter.querySelectorAll(".pw-seg");
    function paint() {
      var s = scorePassword(input.value);
      segs.forEach(function (el, i) {
        el.className = "pw-seg" + (i < s ? " on s" + s : "");
      });
    }
    input.addEventListener("input", paint);
    paint();
  });

  var lang = document.getElementById("lang-switch");
  if (lang) {
    lang.addEventListener("change", function () {
      if (lang.value) window.location.href = lang.getAttribute("data-base") + lang.value;
    });
  }

  window.pollJob = function (opts) {
    var url = opts.url;
    var bar = document.getElementById(opts.barId || "job-bar");
    var msg = document.getElementById(opts.msgId || "job-message");
    var statusEl = document.getElementById(opts.statusId || "job-status");
    var timerEl = document.getElementById(opts.timerId || "job-elapsed");
    var stillEl = document.getElementById("job-still");
    var refreshEl = document.getElementById("job-refresh");
    var failBox = document.getElementById("job-fail");
    var okBox = document.getElementById("job-ok");
    var spin = document.getElementById("job-spin");
    var started = Date.now();
    var stopped = false;

    function tick() {
      if (timerEl) {
        var s = Math.floor((Date.now() - started) / 1000);
        var m = Math.floor(s / 60);
        timerEl.textContent = (m < 10 ? "0" : "") + m + ":" + ((s % 60) < 10 ? "0" : "") + (s % 60);
      }
    }
    var clock = window.setInterval(tick, 1000);
    tick();

    function paint(data) {
      if (bar) {
        bar.style.width = (data.progress || 0) + "%";
        bar.setAttribute("aria-valuenow", data.progress || 0);
        bar.textContent = (data.progress || 0) + "%";
      }
      if (msg) msg.textContent = data.message || "";
      if (statusEl) statusEl.textContent = data.status || "";
    }

    function finish(data) {
      stopped = true;
      window.clearInterval(clock);
      if (spin) spin.classList.add("d-none");
      if (data.status === "completed" && okBox) okBox.classList.remove("d-none");
      if (data.status === "failed" && failBox) {
        failBox.classList.remove("d-none");
        var err = document.getElementById("job-error");
        if (err) err.textContent = data.error || "The job failed.";
      }
    }

    function loop() {
      if (stopped) return;
      var elapsed = Date.now() - started;
      if (elapsed > 180000 && stillEl) stillEl.classList.remove("d-none");
      if (elapsed > 600000) {
        if (refreshEl) refreshEl.classList.remove("d-none");
      }
      fetch(url, { headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
        .then(function (r) {
          if (r.status === 401) { window.location.href = "/auth/login"; return null; }
          if (!r.ok) throw new Error("poll failed");
          return r.json();
        })
        .then(function (data) {
          if (!data) return;
          paint(data);
          if (data.status === "completed" || data.status === "failed") {
            finish(data);
            if (data.redirect) window.location.href = data.redirect;
          } else window.setTimeout(loop, 2500);
        })
        .catch(function () { window.setTimeout(loop, 4000); });
    }
    loop();
  };

  var intelForm = document.getElementById("intel-form");
  if (intelForm) {
    intelForm.addEventListener("submit", function (e) {
      if (intelForm.getAttribute("data-hide-modal") === "1") return;
      if (intelForm.getAttribute("data-acked") === "1") return;
      e.preventDefault();
      var modalEl = document.getElementById("intelModal");
      if (modalEl && window.bootstrap) new window.bootstrap.Modal(modalEl).show();
      else {
        intelForm.setAttribute("data-acked", "1");
        intelForm.submit();
      }
    });
    var ack = document.getElementById("intel-ack");
    if (ack) {
      ack.addEventListener("click", function () {
        intelForm.setAttribute("data-acked", "1");
        var hide = document.getElementById("intel-hide-again");
        if (hide && hide.checked) {
          var inp = document.createElement("input");
          inp.type = "hidden";
          inp.name = "hide_again";
          inp.value = "y";
          intelForm.appendChild(inp);
        }
        var ackIn = document.createElement("input");
        ackIn.type = "hidden";
        ackIn.name = "ack";
        ackIn.value = "1";
        intelForm.appendChild(ackIn);
        intelForm.submit();
      });
    }
  }
  var applyBoxes = document.querySelectorAll(".apply-box");
  var applyCount = document.getElementById("apply-count");
  var applyBtn = document.getElementById("apply-btn");
  function paintApply() {
    var n = 0;
    applyBoxes.forEach(function (el) { if (el.checked) n += 1; });
    if (applyCount) applyCount.textContent = n;
    if (applyBtn) applyBtn.disabled = n < 1;
  }
  applyBoxes.forEach(function (el) { el.addEventListener("change", paintApply); });
  paintApply();

  var drop = document.getElementById("dropzone");
  var fileIn = document.getElementById("file");
  if (drop && fileIn) {
    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("drag"); });
    });
    drop.addEventListener("drop", function (e) {
      if (e.dataTransfer.files.length) fileIn.files = e.dataTransfer.files;
    });
  }
  var evSubmit = document.getElementById("ev-submit");
  var evOff = document.getElementById("ev-offline");
  if (evSubmit) {
    function net() {
      var on = navigator.onLine;
      evSubmit.disabled = !on;
      if (evOff) evOff.classList.toggle("d-none", on);
    }
    window.addEventListener("online", net);
    window.addEventListener("offline", net);
    net();
  }

  var wiz = document.getElementById("wizard-form");
  if (wiz) {
    var dirty = false;
    wiz.addEventListener("input", function () { dirty = true; });
    wiz.querySelectorAll("[data-wiz]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var act = document.getElementById("wizard-action");
        if (act) act.value = btn.getAttribute("data-wiz");
      });
    });
    var cancel = document.getElementById("wiz-cancel");
    if (cancel) {
      cancel.addEventListener("click", function () {
        if (!dirty) { window.location.href = "/cases"; return; }
        var modal = document.getElementById("wizLeave");
        if (modal && window.bootstrap) new window.bootstrap.Modal(modal).show();
        else if (window.confirm("Leave without saving?")) window.location.href = "/cases";
      });
    }
    window.addEventListener("beforeunload", function (e) {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    });
    wiz.addEventListener("submit", function () { dirty = false; });
    var nar = document.getElementById("narrative");
    var cnt = document.getElementById("nar-count");
    function countNar() { if (nar && cnt) cnt.textContent = (nar.value || "").length; }
    if (nar) { nar.addEventListener("input", countNar); countNar(); }
    if (wiz.getAttribute("data-offline") === "1" && window.indexedDB) {
      var req = window.indexedDB.open("crimegpt-wizard", 1);
      req.onupgradeneeded = function () { req.result.createObjectStore("drafts"); };
      req.onsuccess = function () {
        var dbx = req.result;
        var uid = document.body.getAttribute("data-user") || "anon";
        var tx = dbx.transaction("drafts", "readonly");
        tx.objectStore("drafts").get(uid).onsuccess = function (ev) {
          var saved = ev.target.result;
          if (!saved) return;
          Object.keys(saved).forEach(function (k) {
            var el = wiz.elements[k];
            if (el && !el.value) el.value = saved[k];
          });
        };
        wiz.addEventListener("input", function () {
          var data = {};
          Array.prototype.forEach.call(wiz.elements, function (el) {
            if (el.name) data[el.name] = el.value;
          });
          var w = dbx.transaction("drafts", "readwrite");
          w.objectStore("drafts").put(data, uid);
        });
      };
    }
  }
})();
