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


  // --------------------------------------------------------------------
  // "Locate me": find a furnace load by number, wire serial or traveller
  // type, or scan its printed label with the camera. Every URL comes from
  // data attributes on the modal, so nothing here knows a route.
  // --------------------------------------------------------------------
  var locateModal = document.getElementById("locateModal");
  if (locateModal) {
    var api = locateModal.getAttribute("data-api");
    var siteBase = (locateModal.getAttribute("data-base") || "").replace(/\/$/, "");
    var searchInput = document.getElementById("locateSearch");
    var list = document.getElementById("locateList");
    var detail = document.getElementById("locateDetail");
    var timer = null;
    var loaded = false;

    function fetchBatches(params) {
      return fetch(api + "?" + params, { headers: { "Accept": "application/json" } })
        .then(function (response) { return response.ok ? response.json() : []; })
        .catch(function () { return []; });
    }

    var current = [];

    function render(batches) {
      current = batches;
      if (!batches.length) {
        list.innerHTML = '<div class="text-muted small py-3 px-2">No batch matches that.</div>';
        return;
      }
      list.innerHTML = batches.map(function (batch, index) {
        var types = (batch.traveller_types || []).join(", ") || "-";
        return '<button type="button" class="locate-row" data-index="' + index + '">' +
          "<strong>" + batch.batch_no + "</strong>" +
          '<span class="meta">' + batch.lot_count + " lot(s) &middot; " + types + "</span>" +
          '<span class="ms-auto badge badge-status-' + batch.status + '">' + batch.status + "</span>" +
          "</button>";
      }).join("");
      Array.prototype.slice.call(list.querySelectorAll(".locate-row")).forEach(function (row) {
        row.addEventListener("click", function () {
          Array.prototype.slice.call(list.querySelectorAll(".locate-row")).forEach(function (other) {
            other.classList.remove("is-active");
          });
          row.classList.add("is-active");
          show(current[parseInt(row.getAttribute("data-index"), 10)]);
        });
      });
    }

    function show(batch) {
      var types = (batch.traveller_types || []).join(", ") || "-";
      var serials = (batch.wire_serials || []).join(", ") || "-";
      detail.hidden = false;
      detail.innerHTML =
        '<img src="' + batch.qr_url + '" alt="Batch QR">' +
        '<div><div class="fs-5 fw-bold">' + batch.batch_no + "</div>" +
        '<div class="small text-muted mb-2">' + batch.lot_count + " lot(s) &middot; " + types +
        "<br>" + serials + "</div>" +
        '<a class="btn btn-primary btn-sm" href="' + batch.url + '">View</a> ' +
        '<a class="btn btn-outline-secondary btn-sm" target="_blank" href="' + batch.label_url + '">Print label</a>' +
        "</div>";
    }

    function loadCompleted() {
      fetchBatches("status=completed").then(render);
    }

    locateModal.addEventListener("shown.bs.modal", function () {
      if (!loaded) { loaded = true; loadCompleted(); }
      if (searchInput) searchInput.focus();
    });

    if (searchInput) {
      searchInput.addEventListener("input", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          var term = searchInput.value.trim();
          if (!term) { loadCompleted(); return; }
          fetchBatches("search=" + encodeURIComponent(term)).then(render);
        }, 250);
      });
    }

    // ---- camera scan -------------------------------------------------
    var startBtn = document.getElementById("locateScanStart");
    var stopBtn = document.getElementById("locateScanStop");
    var note = document.getElementById("locateScanNote");
    var scanner = null;

    function loadScannerLibrary() {
      if (window.Html5Qrcode) return Promise.resolve();
      return new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/html5-qrcode/2.3.8/html5-qrcode.min.js";
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }

    function onDecoded(text) {
      if (siteBase && text.indexOf(siteBase) === 0) {
        window.location.href = text;
        return;
      }
      note.textContent = "Not a Rover label: " + text;
    }

    if (startBtn) {
      startBtn.addEventListener("click", function () {
        note.textContent = "Starting the camera...";
        loadScannerLibrary().then(function () {
          scanner = new window.Html5Qrcode("locateReader");
          return scanner.start(
            { facingMode: "environment" },
            { fps: 10, qrbox: 220 },
            function (text) { scanner.stop().then(function () { onDecoded(text); }); },
            function () {}
          );
        }).then(function () {
          note.textContent = "Point the camera at a batch label.";
          startBtn.hidden = true;
          stopBtn.hidden = false;
        }).catch(function () {
          note.textContent = "Could not open the camera. Allow camera access, or use Find instead.";
        });
      });
    }

    if (stopBtn) {
      stopBtn.addEventListener("click", function () {
        if (scanner) scanner.stop().catch(function () {});
        startBtn.hidden = false;
        stopBtn.hidden = true;
      });
    }

    locateModal.addEventListener("hidden.bs.modal", function () {
      if (scanner) { scanner.stop().catch(function () {}); scanner = null; }
      if (startBtn) startBtn.hidden = false;
      if (stopBtn) stopBtn.hidden = true;
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });
});
