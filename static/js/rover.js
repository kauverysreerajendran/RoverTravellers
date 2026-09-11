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

  // ---- Process submenus (Main Table / Complete Table) ----------------
  // Groups are rendered server-side from the process registry; the active
  // group always starts open, and any group the user opens by hand is
  // remembered across navigations.
  var STORE_KEY = "roverOpenProcessGroups";

  function readOpenGroups() {
    try {
      return JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function writeOpenGroups(slugs) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(slugs)); } catch (e) {}
  }

  function setGroupOpen(group, open) {
    var toggle = group.querySelector(".nav-group-toggle");
    var submenu = group.querySelector(".nav-submenu");
    if (!toggle || !submenu) return;
    submenu.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  var groups = document.querySelectorAll(".nav-group");
  if (groups.length) {
    var remembered = readOpenGroups();

    groups.forEach(function (group) {
      // The active group stays open regardless of what was remembered, so
      // a refresh or a direct URL never lands on a collapsed submenu.
      if (group.classList.contains("is-active")) {
        setGroupOpen(group, true);
      } else if (remembered.indexOf(group.dataset.process) !== -1) {
        setGroupOpen(group, true);
      }

      var toggle = group.querySelector(".nav-group-toggle");
      if (!toggle) return;
      toggle.addEventListener("click", function () {
        // On the collapsed icon rail the submenu is not visible, so
        // expand the rail first and then open the group.
        if (document.documentElement.classList.contains("rover-sidebar-collapsed")) {
          document.documentElement.classList.remove("rover-sidebar-collapsed");
          try { localStorage.setItem("roverSidebarExpanded", "true"); } catch (e) {}
          setGroupOpen(group, true);
        } else {
          setGroupOpen(group, toggle.getAttribute("aria-expanded") !== "true");
        }

        var open = [];
        document.querySelectorAll(".nav-group").forEach(function (g) {
          var t = g.querySelector(".nav-group-toggle");
          if (t && t.getAttribute("aria-expanded") === "true") open.push(g.dataset.process);
        });
        writeOpenGroups(open);
      });
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
