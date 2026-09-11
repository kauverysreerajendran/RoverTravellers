document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("sidebarToggle");
  var sidebar = document.getElementById("roverSidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
  }

  var clock = document.getElementById("headerClock");
  if (clock) {
    setInterval(function () {
      var now = new Date();
      var options = { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" };
      clock.textContent = now.toLocaleString("en-GB", options).replace(",", "");
    }, 1000 * 30);
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.getAttribute("data-confirm"))) {
        e.preventDefault();
      }
    });
  });
});
