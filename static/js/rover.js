(function () {
  var bar = document.getElementById("rover-progress");
  if (!bar) return;
  var width = 0;
  var timer = null;

  function start() {
    width = 12;
    bar.style.width = width + "%";
    bar.classList.add("is-active");
    clearInterval(timer);
    timer = setInterval(function () {
      // Ease toward 90% but never actually reach/complete on its own —
      // the real navigation (full page load) replaces the DOM anyway.
      width += (90 - width) * 0.12;
      bar.style.width = width + "%";
    }, 200);
  }

  function done() {
    clearInterval(timer);
    bar.style.width = "100%";
    setTimeout(function () {
      bar.classList.remove("is-active");
      setTimeout(function () { bar.style.width = "0%"; }, 200);
    }, 150);
  }

  window.addEventListener("pageshow", done);
  window.addEventListener("beforeunload", start);

  document.addEventListener("click", function (e) {
    var link = e.target.closest("a[href]");
    if (!link) return;
    var href = link.getAttribute("href");
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
    if (link.target === "_blank" || link.hasAttribute("download")) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    if (link.origin !== window.location.origin) return;
    start();
  });

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form && !form.hasAttribute("data-no-progress")) start();
  });
})();

document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("sidebarToggle");
  var sidebar = document.getElementById("roverSidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
    document.addEventListener("click", function (e) {
      if (sidebar.classList.contains("open") && !sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove("open");
      }
    });
  }

  var collapseBtn = document.getElementById("sidebarCollapseToggle");
  if (collapseBtn) {
    collapseBtn.addEventListener("click", function () {
      var collapsed = document.documentElement.classList.toggle("rover-sidebar-collapsed");
      try { localStorage.setItem("roverSidebarExpanded", collapsed ? "false" : "true"); } catch (e) {}
    });
  }

  var dateEl = document.getElementById("headerDate");
  var timeEl = document.getElementById("headerTime");
  if (dateEl && timeEl) {
    var tick = function () {
      var now = new Date();
      dateEl.textContent = now.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
      timeEl.textContent =
        now.toLocaleDateString("en-GB", { weekday: "short" }) + ", " +
        now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    };
    setInterval(tick, 30 * 1000);
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });
});
