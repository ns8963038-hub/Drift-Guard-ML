/* Theme handling — UIUX_DESIGN.md §8.
 *
 * Three states, not two: an explicit "light", an explicit "dark", or no stamp
 * at all, in which case the OS preference decides via prefers-color-scheme.
 *
 * Light is the default because college demo projectors wash dark UIs out to
 * mud. The toggle exists for screenshots and for working at night.
 */
(function () {
  "use strict";

  var KEY = "driftguard-theme";

  // Applied before first paint so there is no flash of the wrong theme.
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode */ }
  if (saved === "light" || saved === "dark") {
    document.documentElement.setAttribute("data-theme", saved);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }

  function currentTheme() {
    var stamped = document.documentElement.getAttribute("data-theme");
    if (stamped) return stamped;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  window.toggleTheme = function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }

    // Re-theme live charts in place rather than rebuilding them.
    if (window.DriftGuardCharts && window.DriftGuardCharts.retheme) {
      window.DriftGuardCharts.retheme();
    }
    var label = document.getElementById("themeLabel");
    if (label) label.textContent = next === "dark" ? "Light mode" : "Dark mode";
  };
})();
