(function () {
  "use strict";
  var KB = window.KB = window.KB || {};

  // === Apply theme immediately to prevent flash ===
  var _savedTheme = null;
  try { _savedTheme = localStorage.getItem("kb-theme"); } catch (e) {}
  var _prefersDark = _savedTheme === "dark" || (!_savedTheme && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", _prefersDark ? "dark" : "light");

  // === Debounce utility ===
  function debounce(fn, ms) {
    var timer;
    return function () {
      var args = arguments;
      var ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  // === Data loading ===
  function loadData(callback) {
    // Primary: JSONP-style from <script> tag
    if (window.__KB_DATA__) {
      callback(null, window.__KB_DATA__);
      return;
    }

    // Fallback: fetch over HTTP
    if (typeof fetch !== "undefined") {
      fetch("data/kb_index.json")
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        })
        .then(function (data) { callback(null, data); })
        .catch(function (err) { callback(err); });
      return;
    }

    callback(new Error("No data source available. Serve via HTTP or include data/kb_data.js."));
  }

  // === Event wiring ===
  function wireEvents() {
    // Theme toggle
    var themeBtn = document.getElementById("theme-toggle");
    function applyTheme(dark) {
      document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
      themeBtn.textContent = dark ? "\u2600" : "\u263D";
      try { localStorage.setItem("kb-theme", dark ? "dark" : "light"); } catch (e) {}
    }
    // Set button icon to match already-applied theme
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark");
    themeBtn.addEventListener("click", function () {
      var isDark = document.documentElement.getAttribute("data-theme") === "dark";
      applyTheme(!isDark);
    });

    // Search input
    var searchInput = document.getElementById("search-input");
    var debouncedSearch = debounce(function () {
      KB.State.setQuery(searchInput.value.trim());
    }, 150);
    searchInput.addEventListener("input", debouncedSearch);

    // Tag cloud (delegated)
    document.getElementById("tag-cloud").addEventListener("click", function (e) {
      var tagEl = e.target.closest(".tag-cloud-item");
      if (tagEl) KB.State.toggleTag(tagEl.dataset.tag);
    });

    // Category checkboxes (delegated)
    document.getElementById("filter-categories").addEventListener("change", function (e) {
      if (e.target.classList.contains("category-checkbox")) {
        KB.State.toggleCategory(e.target.value);
      }
    });

    // Product checkboxes (delegated)
    document.getElementById("filter-products").addEventListener("change", function (e) {
      if (e.target.classList.contains("product-checkbox")) {
        KB.State.toggleProduct(e.target.value);
      }
    });

    // Confidence buttons (delegated)
    document.getElementById("filter-confidence").addEventListener("click", function (e) {
      var btn = e.target.closest(".confidence-btn");
      if (btn) KB.State.setConfidence(btn.dataset.level);
    });

    // Sort dropdown (custom)
    var sortEl = document.getElementById("sort-select");
    sortEl.querySelector(".custom-select-display").addEventListener("click", function (e) {
      e.stopPropagation();
      sortEl.classList.toggle("open");
    });
    sortEl.querySelector(".custom-select-options").addEventListener("click", function (e) {
      var opt = e.target.closest(".custom-select-option");
      if (!opt) return;
      KB.State.setSort(opt.dataset.value);
      sortEl.classList.remove("open");
    });
    // Close on outside click
    document.addEventListener("click", function () {
      sortEl.classList.remove("open");
    });

    // Clear filters
    document.getElementById("clear-filters").addEventListener("click", function (e) {
      e.preventDefault();
      searchInput.value = "";
      KB.State.clearFilters();
    });

    // Card grid (delegated) — open detail
    document.getElementById("card-grid").addEventListener("click", function (e) {
      var card = e.target.closest(".card");
      if (card) KB.State.selectArticle(card.dataset.articleId);
    });

    // Detail overlay — close
    var overlay = document.getElementById("detail-overlay");

    overlay.querySelector(".detail-backdrop").addEventListener("click", function () {
      KB.State.selectArticle(null);
    });

    overlay.querySelector(".detail-close").addEventListener("click", function () {
      KB.State.selectArticle(null);
    });

    // Escape key closes detail
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var state = KB.State.get();
        if (state.selectedArticleId) {
          KB.State.selectArticle(null);
        }
      }
    });

    // Filter chip removal (delegated on results-info)
    document.getElementById("results-info").addEventListener("click", function (e) {
      var removeBtn = e.target.closest(".filter-chip-remove");
      if (!removeBtn) return;
      var chipEl = removeBtn.closest(".filter-chip");
      if (!chipEl) return;
      var type = chipEl.dataset.chipType;
      var value = chipEl.dataset.chipValue;

      if (type === "search") {
        searchInput.value = "";
        KB.State.setQuery("");
      } else if (type === "tag") {
        KB.State.toggleTag(value);
      } else if (type === "category") {
        // Need to reverse the formatCategory to get original value
        // Toggle all active categories that format to this label
        var state = KB.State.get();
        var iter = state.filters.activeCategories.values();
        var v = iter.next();
        while (!v.done) {
          var formatted = v.value.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
          if (formatted === value) {
            KB.State.toggleCategory(v.value);
            break;
          }
          v = iter.next();
        }
      } else if (type === "product") {
        KB.State.toggleProduct(value);
      } else if (type === "confidence") {
        KB.State.setConfidence(value);
      }
    });
  }

  // === Init ===
  function init() {
    loadData(function (err, data) {
      if (err) {
        document.getElementById("loading").innerHTML =
          '<p style="color:#dc2626">Failed to load knowledge base: ' + err.message + '</p>' +
          '<p style="font-size:0.85rem;color:#6b7280;margin-top:0.5rem">' +
          'Try serving with: python3 -m http.server 8000 -d ui/</p>';
        return;
      }

      KB.Search.init(data.articles || []);
      KB.State.onChange(KB.Render.update);
      wireEvents();
      KB.State.init(data);
    });
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
