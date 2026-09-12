/* Dashboard charts.
 *
 * The data arrives through json_script, never templated into JavaScript,
 * and the palette is read from the stylesheet so the page has one source
 * of colour. Charts are deliberately quiet: no titles (the card carries
 * it), no gridlines across the x axis, no point markers until you hover,
 * no animation, and a fixed height so the layout never jumps.
 */
(function () {
  var node = document.getElementById("dashboard-data");
  if (!node || typeof Chart === "undefined") return;

  var data = JSON.parse(node.textContent);
  var style = getComputedStyle(document.documentElement);

  function token(name, fallback) {
    return (style.getPropertyValue(name) || "").trim() || fallback;
  }

  var palette = [1, 2, 3, 4, 5, 6].map(function (i) {
    return token("--chart-" + i, "#101a2b");
  });
  var ink = token("--rover-slate", "#5b6575");
  var grid = "rgba(16, 26, 43, .08)";

  Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = ink;
  Chart.defaults.animation = false;
  Chart.defaults.maintainAspectRatio = false;

  function colour(index) {
    return palette[index % palette.length];
  }

  function dayLabel(iso) {
    var parts = iso.split("-");
    return parts[2] + "/" + parts[1];
  }

  function tooltip(unit) {
    return {
      callbacks: {
        label: function (item) {
          var value = item.parsed.y === undefined ? item.parsed : item.parsed.y;
          if (value === null) return item.dataset.label + ": -";
          return item.dataset.label + ": " + value + " " + unit;
        },
      },
    };
  }

  function legend(targetId, series) {
    var target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = series.map(function (item, index) {
      return '<span class="chart-chip"><i style="background:' + colour(index) + '"></i>' +
        item.label + "</span>";
    }).join("");
  }

  var axis = {
    x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
    y: { beginAtZero: true, grid: { color: grid, borderDash: [3, 3], drawBorder: false } },
  };

  // ---- Daily output: one stacked bar per day, one colour per process ----
  var throughput = document.getElementById("throughputChart");
  if (throughput && data.throughput && !data.throughput.empty) {
    legend("throughputLegend", data.throughput.series);
    new Chart(throughput, {
      type: "bar",
      data: {
        labels: data.throughput.labels.map(dayLabel),
        datasets: data.throughput.series.map(function (item, index) {
          return {
            label: item.label,
            data: item.data,
            backgroundColor: colour(index),
            borderWidth: 0,
            borderRadius: 2,
            barPercentage: 0.9,
            categoryPercentage: 0.8,
          };
        }),
      },
      options: {
        plugins: { legend: { display: false }, tooltip: tooltip("kg") },
        scales: {
          x: Object.assign({ stacked: true }, axis.x),
          y: Object.assign({ stacked: true }, axis.y),
        },
      },
    });
  }

  // ---- Wastage: one thin line per process, weekly ----
  var wastage = document.getElementById("wastageChart");
  if (wastage && data.wastage && !data.wastage.empty) {
    new Chart(wastage, {
      type: "line",
      data: {
        labels: data.wastage.labels.map(dayLabel),
        datasets: data.wastage.series.map(function (item, index) {
          return {
            label: item.label,
            data: item.data,
            borderColor: colour(index),
            backgroundColor: colour(index),
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            spanGaps: true,
            tension: 0.3,
          };
        }),
      },
      options: {
        plugins: {
          legend: { display: true, position: "top", align: "start",
                    labels: { boxWidth: 8, boxHeight: 8, usePointStyle: true, padding: 12 } },
          tooltip: tooltip("%"),
        },
        scales: { x: axis.x, y: Object.assign({ ticks: { callback: function (v) { return v + "%"; } } }, axis.y) },
      },
    });
  }

  // ---- Traveller type mix: horizontal bars, heaviest first ----
  var mix = document.getElementById("mixChart");
  if (mix && data.traveller_mix && !data.traveller_mix.empty) {
    new Chart(mix, {
      type: "bar",
      data: {
        labels: data.traveller_mix.labels,
        datasets: [{
          label: "Rolled",
          data: data.traveller_mix.data,
          backgroundColor: colour(0),
          borderWidth: 0,
          borderRadius: 2,
        }],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false }, tooltip: tooltip("kg") },
        scales: {
          x: { beginAtZero: true, grid: { color: grid, borderDash: [3, 3], drawBorder: false } },
          y: { grid: { display: false } },
        },
      },
    });
  }
})();
