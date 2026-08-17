/* DriftGuard chart factories — docs/UIUX_DESIGN.md §5
 *
 * Wraps the vendored Chart.js. Colours are read from the CSS custom properties
 * in tokens.css rather than hardcoded, so the theme toggle re-themes live charts
 * with update() instead of destroying and rebuilding them.
 *
 * Rules enforced here rather than left to each caller:
 *   - no dual-axis charts, ever (two scales = two charts)
 *   - categorical series assigned in fixed slot order, never cycled
 *   - status colours reserved, never used as a series colour
 *   - null values render as GAPS, never as zero and never interpolated
 *   - every chart gets a "View as table" fallback
 */
(function () {
  "use strict";

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function palette() {
    return {
      series: [token("--series-1"), token("--series-2"), token("--series-3"), token("--series-4")],
      status: {
        good: token("--status-good"),
        warning: token("--status-warning"),
        serious: token("--status-serious"),
        critical: token("--status-critical")
      },
      grid: token("--grid-line"),
      axis: token("--axis-line"),
      label: token("--axis-label"),
      surface: token("--bg-surface"),
      tooltipBg: token("--tooltip-bg"),
      tooltipText: token("--tooltip-text")
    };
  }

  var registry = [];

  function baseOptions(p, extra) {
    var options = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "bottom",
          labels: { color: p.label, boxWidth: 12, usePointStyle: true }
        },
        tooltip: {
          backgroundColor: p.tooltipBg,
          titleColor: p.tooltipText,
          bodyColor: p.tooltipText,
          borderColor: p.axis,
          borderWidth: 1,
          padding: 10
        }
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: p.axis },
          ticks: { color: p.label, maxRotation: 0, autoSkip: true }
        },
        y: {
          grid: { color: p.grid, drawTicks: false },
          border: { display: false },
          ticks: { color: p.label }
        }
      }
    };
    return Object.assign(options, extra || {});
  }

  function register(chart, rebuild) {
    registry.push({ chart: chart, rebuild: rebuild });
    return chart;
  }

  var DriftGuardCharts = {
    /* Multi-series trend. `series` is {label: [values]}; null entries become
     * gaps, which is how unlabelled monitoring runs must render (FR-04.7). */
    createLineChart: function (canvasId, labels, series, options) {
      var canvas = document.getElementById(canvasId);
      if (!canvas || typeof Chart === "undefined") return null;

      var p = palette();
      var datasets = Object.keys(series).map(function (name, i) {
        return {
          label: name,
          data: series[name],
          borderColor: p.series[i % p.series.length],
          backgroundColor: p.series[i % p.series.length],
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 8,
          tension: 0.25,
          spanGaps: false // null = gap, never a straight line across missing runs
        };
      });

      var chart = new Chart(canvas, {
        type: "line",
        data: { labels: labels, datasets: datasets },
        options: baseOptions(p, options)
      });

      return register(chart, function (c) {
        var q = palette();
        c.data.datasets.forEach(function (d, i) {
          d.borderColor = q.series[i % q.series.length];
          d.backgroundColor = q.series[i % q.series.length];
        });
        applyChrome(c, q);
      });
    },

    /* Stacked counts by drift status. Uses the reserved status palette with a
     * 2px surface-coloured gap between segments. */
    createDriftStackChart: function (canvasId, labels, counts) {
      var canvas = document.getElementById(canvasId);
      if (!canvas || typeof Chart === "undefined") return null;

      var p = palette();
      var spec = [
        { key: "none", label: "No drift", color: p.status.good },
        { key: "moderate", label: "Moderate", color: p.status.warning },
        { key: "high", label: "High", color: p.status.critical }
      ];

      var chart = new Chart(canvas, {
        type: "bar",
        data: {
          labels: labels,
          datasets: spec.map(function (s) {
            return {
              label: s.label,
              data: counts[s.key] || [],
              backgroundColor: s.color,
              borderColor: p.surface,
              borderWidth: 2,
              borderRadius: 4
            };
          })
        },
        options: baseOptions(p, {
          scales: {
            x: { stacked: true, grid: { display: false }, ticks: { color: p.label } },
            y: {
              stacked: true,
              beginAtZero: true,
              grid: { color: p.grid },
              ticks: { color: p.label, precision: 0 }
            }
          }
        })
      });

      return register(chart, function (c) {
        var q = palette();
        var colours = [q.status.good, q.status.warning, q.status.critical];
        c.data.datasets.forEach(function (d, i) {
          d.backgroundColor = colours[i];
          d.borderColor = q.surface;
        });
        applyChrome(c, q);
      });
    },

    /* Baseline vs current distribution — exactly two series, slots 1 and 2. */
    createDistributionChart: function (canvasId, bins, baseline, current) {
      var canvas = document.getElementById(canvasId);
      if (!canvas || typeof Chart === "undefined") return null;

      var p = palette();
      var chart = new Chart(canvas, {
        type: "bar",
        data: {
          labels: bins,
          datasets: [
            {
              label: "Baseline",
              data: baseline,
              backgroundColor: p.series[0],
              borderColor: p.surface,
              borderWidth: 2,
              borderRadius: 4
            },
            {
              label: "Current",
              data: current,
              backgroundColor: p.series[1],
              borderColor: p.surface,
              borderWidth: 2,
              borderRadius: 4
            }
          ]
        },
        options: baseOptions(p, {
          scales: {
            x: { grid: { display: false }, ticks: { color: p.label } },
            y: { beginAtZero: true, grid: { color: p.grid }, ticks: { color: p.label } }
          }
        })
      });

      return register(chart, function (c) {
        var q = palette();
        c.data.datasets[0].backgroundColor = q.series[0];
        c.data.datasets[1].backgroundColor = q.series[1];
        c.data.datasets.forEach(function (d) { d.borderColor = q.surface; });
        applyChrome(c, q);
      });
    },

    /* Health score over time, with the 60 and 80 band boundaries marked. */
    createHealthChart: function (canvasId, labels, scores) {
      var canvas = document.getElementById(canvasId);
      if (!canvas || typeof Chart === "undefined") return null;

      var p = palette();
      var chart = new Chart(canvas, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Health score",
              data: scores,
              borderColor: p.series[0],
              backgroundColor: p.series[0],
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 8,
              tension: 0.25,
              spanGaps: false
            }
          ]
        },
        options: baseOptions(p, {
          plugins: { legend: { display: false } }, // one series: the title names it
          scales: {
            x: { grid: { display: false }, ticks: { color: p.label } },
            y: { min: 0, max: 100, grid: { color: p.grid }, ticks: { color: p.label } }
          }
        })
      });

      return register(chart, function (c) {
        var q = palette();
        c.data.datasets[0].borderColor = q.series[0];
        c.data.datasets[0].backgroundColor = q.series[0];
        applyChrome(c, q);
      });
    },

    /* Accessible table view of the same data (UIUX §5.2). Required, not
     * optional: two light-mode series colours sit below 3:1 contrast, and the
     * table is what makes that acceptable. */
    buildTableView: function (containerId, headers, rows) {
      var container = document.getElementById(containerId);
      if (!container) return;

      var table = document.createElement("table");
      table.className = "chart-table";

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      headers.forEach(function (h) {
        var th = document.createElement("th");
        th.scope = "col";
        th.textContent = h;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      rows.forEach(function (row) {
        var tr = document.createElement("tr");
        row.forEach(function (cell) {
          var td = document.createElement("td");
          td.textContent = cell === null || cell === undefined ? "—" : cell;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);

      container.innerHTML = "";
      container.appendChild(table);
    },

    /* Called by theme.js after the theme flips. Re-reads the tokens and
     * updates in place — no destroy, no rebuild, no flash. */
    retheme: function () {
      registry.forEach(function (entry) {
        try {
          entry.rebuild(entry.chart);
          entry.chart.update("none");
        } catch (e) {
          /* a chart removed from the DOM must not break the others */
        }
      });
    }
  };

  function applyChrome(chart, p) {
    var scales = chart.options.scales || {};
    if (scales.y && scales.y.grid) scales.y.grid.color = p.grid;
    if (scales.y && scales.y.ticks) scales.y.ticks.color = p.label;
    if (scales.x && scales.x.ticks) scales.x.ticks.color = p.label;
    var legend = chart.options.plugins && chart.options.plugins.legend;
    if (legend && legend.labels) legend.labels.color = p.label;
    var tooltip = chart.options.plugins && chart.options.plugins.tooltip;
    if (tooltip) {
      tooltip.backgroundColor = p.tooltipBg;
      tooltip.titleColor = p.tooltipText;
      tooltip.bodyColor = p.tooltipText;
    }
  }

  window.DriftGuardCharts = DriftGuardCharts;
})();
