// Small client-side helpers. No external dependencies besides htmx and Chart.js (both local).
(function () {
  "use strict";

  // Confirmation for dangerous actions: <form data-confirm="..."> or <button data-confirm="...">.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var submitter = e.submitter;
    var text = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
    if (text && !window.confirm(text)) {
      e.preventDefault();
    }
  }, true);

  document.addEventListener("click", function (e) {
    var closeBtn = e.target.closest("[data-dismiss]");
    if (closeBtn) {
      var box = closeBtn.closest(".flash");
      if (box) box.remove();
    }
    var toggle = e.target.closest(".menu-toggle");
    if (toggle) {
      document.querySelector(".sidebar").classList.toggle("open");
    }
    var results = document.getElementById("search-results");
    if (results && !e.target.closest(".search")) {
      results.innerHTML = "";
    }
    var printBtn = e.target.closest("[data-print]");
    if (printBtn) {
      window.print();
    }
  });

  // DD.MM.YYYY mask for date fields (dates are typed as text to keep the Russian format in every browser).
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("date-input")) return;
    if (e.inputType && e.inputType.indexOf("delete") === 0) return;
    var digits = el.value.replace(/\D/g, "").slice(0, 8);
    var out = digits.slice(0, 2);
    if (digits.length > 2) out += "." + digits.slice(2, 4);
    if (digits.length > 4) out += "." + digits.slice(4, 8);
    if (digits.length === 2 || digits.length === 4) out += ".";
    el.value = out;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var results = document.getElementById("search-results");
      if (results) results.innerHTML = "";
    }
  });

  // Chart.js defaults matching the stylesheet.
  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#6f7c76";
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
  }

  var rub = new Intl.NumberFormat("ru-RU");
  window.GolfCRM = {
    colors: {
      green: "#2d7a56",
      greenLight: "#8fc9a8",
      greenFill: "rgba(59, 148, 104, 0.12)",
      amber: "#d99a1e",
      red: "#d0473b",
      gray: "#c9d1cd",
      palette: ["#236146", "#3b9468", "#8fc9a8", "#d99a1e", "#1f5a8f", "#98a39e"]
    },
    formatNumber: function (v) { return rub.format(v); },
    formatRub: function (v) { return rub.format(v) + " ₽"; },
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
