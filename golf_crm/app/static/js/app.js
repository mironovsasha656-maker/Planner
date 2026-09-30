// Client-side helpers. No dependencies besides htmx and Chart.js (both stored locally).
(function () {
  "use strict";

  var css = getComputedStyle(document.documentElement);
  var token = function (name) { return css.getPropertyValue(name).trim(); };

  // ---------------------------------------------------------------- toasts
  function toast(text, kind, url) {
    var box = document.getElementById("toasts");
    if (!box || !text) return;
    var el = document.createElement("div");
    el.className = "toast " + (kind || "success");
    el.setAttribute("role", "status");
    var body = document.createElement("div");
    body.className = "body";
    body.textContent = text;
    if (url) {
      var link = document.createElement("a");
      link.href = url;
      link.textContent = " Открыть";
      body.appendChild(link);
    }
    var close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть");
    close.setAttribute("data-dismiss", "");
    close.textContent = "×";
    el.appendChild(body);
    el.appendChild(close);
    box.appendChild(el);
    autoclose(el, url ? 9000 : 5000);
  }
  function dismiss(el) {
    el.classList.add("leaving");
    setTimeout(function () { el.remove(); }, 200);
  }
  function autoclose(el, ms) {
    var timer = setTimeout(function () { dismiss(el); }, ms);
    el.addEventListener("mouseenter", function () { clearTimeout(timer); });
    el.addEventListener("mouseleave", function () { timer = setTimeout(function () { dismiss(el); }, 2500); });
  }
  document.querySelectorAll("[data-autoclose]").forEach(function (el) { autoclose(el, 5000); });

  // ---------------------------------------------------------------- dialogs (modal + slide-over)
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  var openerStack = [];

  function openDialog(id) {
    var overlay = document.getElementById(id);
    if (!overlay) return;
    if (overlay.hidden) openerStack.push({ id: id, opener: document.activeElement });
    overlay.hidden = false;
    document.body.classList.add("no-scroll");
    focusFirst(overlay);
  }
  function focusFirst(overlay) {
    var target = overlay.querySelector("[autofocus]") ||
      overlay.querySelector(".modal-body " + FOCUSABLE.split(", ").join(", .modal-body ")) ||
      overlay.querySelector(FOCUSABLE);
    if (target) setTimeout(function () { target.focus(); }, 0);
  }
  function closeDialog(id) {
    var overlay = document.getElementById(id);
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    // Clear after the current event loop turn: htmx may still dispatch HX-Trigger events
    // (e.g. "toast") on elements inside the dialog, which must stay attached until then.
    var content = overlay.firstElementChild;
    if (content) setTimeout(function () { if (overlay.hidden) content.innerHTML = ""; }, 0);
    if (!document.querySelector(".overlay:not([hidden])")) document.body.classList.remove("no-scroll");
    for (var i = openerStack.length - 1; i >= 0; i--) {
      if (openerStack[i].id === id) {
        var opener = openerStack.splice(i, 1)[0].opener;
        if (opener && document.contains(opener)) opener.focus();
        break;
      }
    }
  }
  function topDialog() {
    var open = Array.prototype.slice.call(document.querySelectorAll(".overlay:not([hidden])"));
    return open.length ? open[open.length - 1] : null;
  }

  document.addEventListener("htmx:afterSwap", function (e) {
    var id = e.detail.target && e.detail.target.id;
    if (id === "modal-content") {
      if (e.detail.target.innerHTML.trim()) { openDialog("modal"); } else { closeDialog("modal"); }
    } else if (id === "panel-content") {
      if (e.detail.target.innerHTML.trim()) { openDialog("panel"); } else { closeDialog("panel"); }
    } else if (id === "notif-menu") {
      document.getElementById("notif-menu").classList.remove("hidden");
      document.getElementById("bell-btn").setAttribute("aria-expanded", "true");
    }
  });
  // Server-driven events (HX-Trigger response header).
  document.body.addEventListener("closeModal", function () { closeDialog("modal"); });
  document.body.addEventListener("closePanel", function () { closeDialog("panel"); });
  document.body.addEventListener("toast", function (e) { toast(e.detail.text, e.detail.kind, e.detail.url); });
  document.body.addEventListener("newNotifications", function (e) {
    var d = e.detail || {};
    (d.items || []).forEach(function (n) { toast(n.text, n.kind || "info", n.url); });
    if (d.latest !== undefined) setLastSeen(d.latest);
  });

  document.addEventListener("keydown", function (e) {
    var dialog = topDialog();
    if (e.key === "Escape") {
      if (dialog) { closeDialog(dialog.id); e.preventDefault(); return; }
      var results = document.getElementById("search-results");
      if (results) results.innerHTML = "";
      closeNotifMenu();
      return;
    }
    if (e.key === "Tab" && dialog) {  // focus trap
      var items = Array.prototype.filter.call(dialog.querySelectorAll(FOCUSABLE), function (el) { return el.offsetParent !== null; });
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { first.focus(); e.preventDefault(); }
    }
  });

  // ---------------------------------------------------------------- clicks
  function closeNotifMenu() {
    var menu = document.getElementById("notif-menu");
    if (menu && !menu.classList.contains("hidden")) {
      menu.classList.add("hidden");
      document.getElementById("bell-btn").setAttribute("aria-expanded", "false");
    }
  }
  document.addEventListener("click", function (e) {
    var t = e.target;
    var dismissBtn = t.closest("[data-dismiss]");
    if (dismissBtn) {
      var box = dismissBtn.closest(".toast, .flash");
      if (box) dismiss(box);
    }
    if (t.classList && t.classList.contains("overlay")) closeDialog(t.id);  // backdrop click
    var closer = t.closest("[data-close]");
    if (closer && closer.closest(".overlay")) closeDialog(closer.closest(".overlay").id);
    else if (closer) window.location.href = "/tasks";
    if (t.closest(".menu-toggle")) document.querySelector(".sidebar").classList.toggle("open");
    var results = document.getElementById("search-results");
    if (results && !t.closest(".search")) results.innerHTML = "";
    if (!t.closest(".notif-wrap")) closeNotifMenu();
    else if (t.closest("#bell-btn") && !document.getElementById("notif-menu").classList.contains("hidden")) {
      closeNotifMenu();
      e.preventDefault();
      e.stopPropagation();
    }
    if (t.closest("[data-print]")) window.print();
    // searchable "related entity" picker
    var pick = t.closest("[data-pick]");
    if (pick) {
      var combo = pick.closest(".combo");
      combo.querySelector("input[type=hidden]").value = pick.dataset.pick;
      combo.querySelector(".combo-label").textContent = pick.dataset.label;
      combo.querySelector(".combo-chosen").classList.remove("hidden");
      combo.querySelector(".combo-search").classList.add("hidden");
      combo.querySelector(".combo-results").innerHTML = "";
      e.preventDefault();
    }
    var clear = t.closest("[data-clear-pick]");
    if (clear) {
      var c = clear.closest(".combo");
      c.querySelector("input[type=hidden]").value = "";
      c.querySelector(".combo-chosen").classList.add("hidden");
      var search = c.querySelector(".combo-search");
      search.classList.remove("hidden");
      search.value = "";
      search.focus();
    }
  }, true);

  // Confirmation for dangerous actions: <form data-confirm> or <button data-confirm>.
  document.addEventListener("submit", function (e) {
    var submitter = e.submitter;
    var text = (submitter && submitter.dataset.confirm) || e.target.dataset.confirm;
    if (text && !window.confirm(text)) e.preventDefault();
  }, true);

  // ---------------------------------------------------------------- input masks
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el.classList) return;
    if (e.inputType && e.inputType.indexOf("delete") === 0) return;
    var digits, out;
    if (el.classList.contains("date-input")) {  // DD.MM.YYYY
      digits = el.value.replace(/\D/g, "").slice(0, 8);
      out = digits.slice(0, 2);
      if (digits.length > 2) out += "." + digits.slice(2, 4);
      if (digits.length > 4) out += "." + digits.slice(4, 8);
      if (digits.length === 2 || digits.length === 4) out += ".";
      el.value = out;
    } else if (el.classList.contains("time-input")) {  // HH:MM
      digits = el.value.replace(/\D/g, "").slice(0, 4);
      out = digits.slice(0, 2);
      if (digits.length > 2) out += ":" + digits.slice(2, 4);
      if (digits.length === 2) out += ":";
      el.value = out;
    }
  });

  // ---------------------------------------------------------------- notifications
  var userId = document.body.dataset.user || "0";
  var storeKey = "golfcrm-notif-last-" + userId;
  function lastSeen() {
    try { var v = sessionStorage.getItem(storeKey); return v === null ? -1 : parseInt(v, 10); } catch (err) { return -1; }
  }
  function setLastSeen(v) {
    try { sessionStorage.setItem(storeKey, String(v)); } catch (err) { /* private mode */ }
  }

  // ---------------------------------------------------------------- charts
  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.color = token("--text-2");
    Chart.defaults.borderColor = token("--chart-grid");
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
    Chart.defaults.plugins.tooltip.backgroundColor = token("--surface-3");
    Chart.defaults.plugins.tooltip.borderColor = token("--border-strong");
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleColor = token("--text");
    Chart.defaults.plugins.tooltip.bodyColor = token("--text");
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
  }
  var nf = new Intl.NumberFormat("ru-RU");

  window.GolfCRM = {
    toast: toast,
    openDialog: openDialog,
    closeDialog: closeDialog,
    lastSeen: lastSeen,
    colors: {
      accent: token("--accent"),
      accentSoft: token("--accent-soft"),
      grid: token("--chart-grid"),
      muted: token("--text-3"),
      surface: token("--surface"),
      series: [token("--chart-1"), token("--chart-2"), token("--chart-3")]
    },
    formatNumber: function (v) { return nf.format(v); },
    formatRub: function (v) { return nf.format(v) + " ₽"; },
    chart: function (id, config) {
      var el = document.getElementById(id);
      if (!el || !window.Chart) return null;
      config.options = config.options || {};
      config.options.responsive = true;
      config.options.maintainAspectRatio = false;
      return new Chart(el, config);
    }
  };
})();
