(function () {
  "use strict";
  var KB = window.KB = window.KB || {};

  // Cache DOM references
  var els = {};
  function el(id) {
    if (!els[id]) els[id] = document.getElementById(id);
    return els[id];
  }

  // Utility: escape HTML
  function esc(str) {
    var d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }

  // Utility: format category name for display
  function formatCategory(cat) {
    return (cat || "").replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  // Utility: format date
  function formatDate(dateStr) {
    if (!dateStr) return "";
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  }

  // Utility: truncate text
  function truncate(text, len) {
    if (!text || text.length <= len) return text || "";
    return text.substring(0, len) + "...";
  }

  // === Header Meta ===
  function renderHeaderMeta(meta) {
    el("header-meta").innerHTML =
      '<div>' + esc(meta.total_articles + " articles") + ' from ' +
      esc((meta.total_threads || 0) + " threads") + '</div>' +
      (meta.generated_at ? '<div>Generated ' + esc(formatDate(meta.generated_at)) + '</div>' : '');
  }

  // === Tag Cloud ===
  var TAG_STOPLIST = new Set(["srx"]);

  function renderTagCloud(tagCloud, activeTags, minCount) {
    if (!tagCloud || tagCloud.length === 0) {
      el("tag-cloud").innerHTML = '<span class="empty">No tags</span>';
      el("tag-visible-count").textContent = "";
      return;
    }

    var filtered = tagCloud.filter(function (t) {
      if (TAG_STOPLIST.has(t.tag)) return false;
      return t.count >= minCount || activeTags.has(t.tag);
    });

    var maxCount = 0;
    for (var i = 0; i < filtered.length; i++) {
      if (filtered[i].count > maxCount) maxCount = filtered[i].count;
    }

    var sorted = filtered.slice().sort(function (a, b) {
      return a.tag.localeCompare(b.tag);
    });

    var html = "";
    for (var j = 0; j < sorted.length; j++) {
      var t = sorted[j];
      var size = 0.75 + (t.count / Math.max(maxCount, 1)) * 1.5;
      var active = activeTags.has(t.tag) ? " active" : "";
      html += '<span class="tag-cloud-item' + active + '" data-tag="' + esc(t.tag) +
        '" style="font-size:' + size.toFixed(2) + 'rem" title="' + esc(t.tag + " (" + t.count + ")") +
        '">' + esc(t.tag) + '</span>';
    }

    el("tag-cloud").innerHTML = html;
    el("tag-visible-count").textContent = filtered.length + " / " + tagCloud.length + " tags";
  }

  // === Filters ===
  function renderFilters(state) {
    var f = state.filters;

    // Categories
    var catHtml = "";
    var catCounts = countByField(state.raw.articles, "categories");
    for (var i = 0; i < state.raw.categories.length; i++) {
      var cat = state.raw.categories[i];
      var checked = f.activeCategories.has(cat) ? " checked" : "";
      catHtml += '<label><input type="checkbox" class="category-checkbox" value="' + esc(cat) + '"' + checked + '>' +
        '<span>' + esc(formatCategory(cat)) + '</span>' +
        '<span class="filter-count">' + (catCounts[cat] || 0) + '</span></label>';
    }
    el("filter-categories").innerHTML = catHtml;

    // Products
    var prodHtml = "";
    var prodCounts = countByField(state.raw.articles, "products");
    for (var j = 0; j < state.raw.products.length; j++) {
      var prod = state.raw.products[j];
      var pChecked = f.activeProducts.has(prod) ? " checked" : "";
      prodHtml += '<label><input type="checkbox" class="product-checkbox" value="' + esc(prod) + '"' + pChecked + '>' +
        '<span>' + esc(prod) + '</span>' +
        '<span class="filter-count">' + (prodCounts[prod] || 0) + '</span></label>';
    }
    el("filter-products").innerHTML = prodHtml;

    // Confidence buttons
    var confHtml = "";
    var levels = ["high", "medium", "low"];
    for (var k = 0; k < levels.length; k++) {
      var lvl = levels[k];
      var cActive = f.confidence === lvl ? " active" : "";
      confHtml += '<button class="confidence-btn' + cActive + '" data-level="' + lvl + '">' +
        lvl.charAt(0).toUpperCase() + lvl.slice(1) + '</button>';
    }
    el("filter-confidence").innerHTML = confHtml;

    // Sort (custom select)
    var sortContainer = el("sort-select");
    sortContainer.dataset.value = f.sort;
    var sortOpts = sortContainer.querySelectorAll(".custom-select-option");
    for (var s = 0; s < sortOpts.length; s++) {
      if (sortOpts[s].dataset.value === f.sort) {
        sortOpts[s].classList.add("active");
        sortContainer.querySelector(".custom-select-display").textContent = sortOpts[s].textContent;
      } else {
        sortOpts[s].classList.remove("active");
      }
    }

    // Clear filters visibility
    var clearEl = el("clear-filters");
    if (KB.State.hasActiveFilters()) {
      clearEl.classList.remove("hidden");
    } else {
      clearEl.classList.add("hidden");
    }
  }

  function countByField(articles, field) {
    var counts = {};
    for (var i = 0; i < articles.length; i++) {
      var vals = articles[i][field] || [];
      for (var j = 0; j < vals.length; j++) {
        counts[vals[j]] = (counts[vals[j]] || 0) + 1;
      }
    }
    return counts;
  }

  // === Results Info ===
  function renderResultsInfo(state) {
    var total = state.raw.articles.length;
    var shown = state.results.length;
    var parts = ['<span>Showing ' + shown + ' of ' + total + ' articles</span>'];

    // Active filter chips
    var f = state.filters;

    if (f.query.length >= 5) {
      parts.push(chip("search", '"' + truncate(f.query, 20) + '"'));
    }

    var tagIter = f.activeTags.values();
    var tagVal = tagIter.next();
    while (!tagVal.done) {
      parts.push(chip("tag", tagVal.value));
      tagVal = tagIter.next();
    }

    var catIter = f.activeCategories.values();
    var catVal = catIter.next();
    while (!catVal.done) {
      parts.push(chip("category", formatCategory(catVal.value)));
      catVal = catIter.next();
    }

    var prodIter = f.activeProducts.values();
    var prodVal = prodIter.next();
    while (!prodVal.done) {
      parts.push(chip("product", prodVal.value));
      prodVal = prodIter.next();
    }

    if (f.confidence) {
      parts.push(chip("confidence", f.confidence));
    }

    el("results-info").innerHTML = parts.join("");
  }

  function chip(type, label) {
    return '<span class="filter-chip" data-chip-type="' + esc(type) + '" data-chip-value="' + esc(label) + '">' +
      esc(label) + ' <span class="filter-chip-remove">&times;</span></span>';
  }

  // === Card Grid ===
  function renderCardGrid(results) {
    if (results.length === 0) {
      el("card-grid").innerHTML = "";
      el("empty-state").classList.remove("hidden");
      return;
    }

    el("empty-state").classList.add("hidden");

    var html = "";
    for (var i = 0; i < results.length; i++) {
      var a = results[i];
      html += '<div class="card" data-article-id="' + esc(a.article_id) + '">' +
        '<div class="card-title">' + esc(a.title) + '</div>' +
        '<div class="card-meta">' +
          '<span class="badge badge-' + esc(a.confidence || "medium") + '">' + esc(a.confidence || "unknown") + '</span>' +
          categoriesHtml(a.categories) +
          productsHtml(a.products) +
        '</div>' +
        '<div class="card-excerpt">' + esc(truncate(a.problem, 180)) + '</div>' +
        '<div class="card-tags">' + tagsHtml(a.tags) + '</div>' +
        '</div>';
    }

    el("card-grid").innerHTML = html;
  }

  function categoriesHtml(cats) {
    var h = "";
    if (!cats) return h;
    for (var i = 0; i < Math.min(cats.length, 2); i++) {
      h += '<span class="pill pill-category">' + esc(formatCategory(cats[i])) + '</span>';
    }
    if (cats.length > 2) h += '<span class="pill pill-category">+' + (cats.length - 2) + '</span>';
    return h;
  }

  function productsHtml(prods) {
    var h = "";
    if (!prods) return h;
    for (var i = 0; i < Math.min(prods.length, 2); i++) {
      h += '<span class="pill pill-product">' + esc(prods[i]) + '</span>';
    }
    if (prods.length > 2) h += '<span class="pill pill-product">+' + (prods.length - 2) + '</span>';
    return h;
  }

  function tagsHtml(tags) {
    var h = "";
    if (!tags) return h;
    for (var i = 0; i < Math.min(tags.length, 5); i++) {
      h += '<span class="pill pill-tag">' + esc(tags[i]) + '</span>';
    }
    if (tags.length > 5) h += '<span class="pill pill-tag">+' + (tags.length - 5) + '</span>';
    return h;
  }

  // === Detail View ===
  function renderDetailView(state) {
    var overlay = el("detail-overlay");
    if (!state.selectedArticleId) {
      overlay.classList.add("hidden");
      document.body.style.overflow = "";
      return;
    }

    var article = null;
    for (var i = 0; i < state.raw.articles.length; i++) {
      if (state.raw.articles[i].article_id === state.selectedArticleId) {
        article = state.raw.articles[i];
        break;
      }
    }

    if (!article) {
      overlay.classList.add("hidden");
      return;
    }

    document.body.style.overflow = "hidden";
    overlay.classList.remove("hidden");

    var html = '<h2 class="detail-title">' + esc(article.title) + '</h2>';

    // Meta row
    html += '<div class="detail-meta">';
    html += '<span class="badge badge-' + esc(article.confidence || "medium") + '">' + esc(article.confidence || "unknown") + '</span>';
    if (article.original_date) {
      html += '<span class="detail-date">' + esc(formatDate(article.original_date)) + '</span>';
    }
    var allCats = article.categories || [];
    for (var c = 0; c < allCats.length; c++) {
      html += '<span class="pill pill-category">' + esc(formatCategory(allCats[c])) + '</span>';
    }
    var allProds = article.products || [];
    for (var p = 0; p < allProds.length; p++) {
      html += '<span class="pill pill-product">' + esc(allProds[p]) + '</span>';
    }
    var versions = article.junos_versions || [];
    for (var v = 0; v < versions.length; v++) {
      html += '<span class="pill pill-tag">' + esc(versions[v]) + '</span>';
    }
    html += '</div>';

    // Problem
    html += '<div class="detail-section"><h3>Problem</h3><p>' + esc(article.problem) + '</p></div>';

    // Cause
    if (article.cause) {
      html += '<div class="detail-section"><h3>Cause</h3><p>' + esc(article.cause) + '</p></div>';
    }

    // Solution
    html += '<div class="detail-section"><h3>Solution</h3><p>' + esc(article.solution) + '</p></div>';

    // Additional Notes
    if (article.additional_notes) {
      html += '<div class="detail-section"><h3>Additional Notes</h3><p>' + esc(article.additional_notes) + '</p></div>';
    }

    // CLI Examples
    var cliExamples = article.cli_examples || [];
    if (cliExamples.length > 0) {
      html += '<div class="detail-section"><h3>CLI Examples</h3>';
      for (var ce = 0; ce < cliExamples.length; ce++) {
        var ex = cliExamples[ce];
        var ctx = ex.context || "other";
        html += '<div class="cli-example">';
        html += '<span class="cli-context-badge cli-context-' + esc(ctx) + '">' + esc(ctx) + '</span>';
        html += '<pre><code>' + esc(ex.command) + '</code></pre>';
        if (ex.description) {
          html += '<div class="cli-description">' + esc(ex.description) + '</div>';
        }
        html += '</div>';
      }
      html += '</div>';
    }

    // Doc Links
    var docLinks = article.doc_links || [];
    if (docLinks.length > 0) {
      html += '<div class="detail-section"><h3>Documentation</h3>';
      for (var dl = 0; dl < docLinks.length; dl++) {
        html += renderDocLink(docLinks[dl]);
      }
      html += '</div>';
    }

    // Related KBs
    var relatedKbs = article.related_kbs || [];
    if (relatedKbs.length > 0) {
      html += '<div class="detail-section"><h3>Related KB Articles</h3>';
      for (var rk = 0; rk < relatedKbs.length; rk++) {
        html += renderDocLink(relatedKbs[rk]);
      }
      html += '</div>';
    }

    // Tags
    var tags = article.tags || [];
    if (tags.length > 0) {
      html += '<div class="detail-section"><h3>Tags</h3><div class="card-tags">';
      for (var tg = 0; tg < tags.length; tg++) {
        html += '<span class="pill pill-tag">' + esc(tags[tg]) + '</span>';
      }
      html += '</div></div>';
    }

    // Source
    html += '<div class="detail-source">Source threads: ' +
      esc((article.source_thread_ids || []).join(", ")) + '</div>';

    el("detail-content").innerHTML = html;
  }

  function renderDocLink(link) {
    var warning = link.validated === false ?
      ' <span class="doc-link-warning">(unvalidated)</span>' : '';
    return '<a class="doc-link" href="' + esc(link.url) + '" target="_blank" rel="noopener">' +
      '<div class="doc-link-title">' + esc(link.title || link.url) + warning + '</div>' +
      '<div class="doc-link-url">' + esc(link.url) + '</div>' +
      (link.description ? '<div class="doc-link-desc">' + esc(link.description) + '</div>' : '') +
      '</a>';
  }

  // === Loading ===
  function renderLoading(isLoading) {
    if (isLoading) {
      el("loading").classList.remove("hidden");
      el("main").classList.add("hidden");
    } else {
      el("loading").classList.add("hidden");
      el("main").classList.remove("hidden");
    }
  }

  // === Main Update ===
  KB.Render = {
    update: function (state) {
      renderLoading(state.isLoading);
      if (state.isLoading) return;

      renderHeaderMeta(state.raw.meta);
      renderTagCloud(state.raw.tagCloud, state.filters.activeTags, state.filters.tagMinCount);
      renderFilters(state);
      renderResultsInfo(state);
      renderCardGrid(state.results);
      renderDetailView(state);
    }
  };
})();
