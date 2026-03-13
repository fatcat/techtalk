(function () {
  "use strict";
  var KB = window.KB = window.KB || {};

  var listeners = [];

  var state = {
    raw: {
      articles: [],
      categories: [],
      products: [],
      tagCloud: [],
      senderAuthority: [],
      meta: {}
    },
    filters: {
      query: "",
      activeTags: new Set(),
      activeCategories: new Set(),
      activeProducts: new Set(),
      confidence: null,
      sort: "relevance",
      tagMinCount: 10
    },
    results: [],
    searchScores: new Map(),
    selectedArticleId: null,
    isLoading: true
  };

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      listeners[i](state);
    }
  }

  function recompute() {
    var articles = state.raw.articles;
    var filters = state.filters;

    // Search scoring
    if (filters.query.length >= 5 && KB.Search) {
      state.searchScores = KB.Search.query(filters.query);
      // When searching, start with only matched articles
      articles = articles.filter(function (a) {
        return state.searchScores.has(a.article_id);
      });
    } else {
      state.searchScores = new Map();
    }

    // Tag filter (AND — article must have ALL active tags)
    if (filters.activeTags.size > 0) {
      articles = articles.filter(function (a) {
        var tags = a.tags || [];
        var iter = filters.activeTags.values();
        var t = iter.next();
        while (!t.done) {
          if (tags.indexOf(t.value) === -1) return false;
          t = iter.next();
        }
        return true;
      });
    }

    // Category filter (OR — article must have at least one active category)
    if (filters.activeCategories.size > 0) {
      articles = articles.filter(function (a) {
        var cats = a.categories || [];
        for (var i = 0; i < cats.length; i++) {
          if (filters.activeCategories.has(cats[i])) return true;
        }
        return false;
      });
    }

    // Product filter (OR)
    if (filters.activeProducts.size > 0) {
      articles = articles.filter(function (a) {
        var prods = a.products || [];
        for (var i = 0; i < prods.length; i++) {
          if (filters.activeProducts.has(prods[i])) return true;
        }
        return false;
      });
    }

    // Confidence filter
    if (filters.confidence) {
      articles = articles.filter(function (a) {
        return a.confidence === filters.confidence;
      });
    }

    // Sort
    var sort = filters.sort;
    var scores = state.searchScores;

    if (sort === "relevance" && scores.size > 0) {
      articles.sort(function (a, b) {
        return (scores.get(b.article_id) || 0) - (scores.get(a.article_id) || 0);
      });
    } else if (sort === "date-desc") {
      articles.sort(function (a, b) {
        return (b.original_date || "").localeCompare(a.original_date || "");
      });
    } else if (sort === "date-asc") {
      articles.sort(function (a, b) {
        return (a.original_date || "").localeCompare(b.original_date || "");
      });
    } else if (sort === "title") {
      articles.sort(function (a, b) {
        return a.title.localeCompare(b.title);
      });
    }

    state.results = articles;
  }

  KB.State = {
    get: function () { return state; },

    init: function (kbData) {
      state.raw.articles = kbData.articles || [];
      state.raw.categories = (kbData.categories || []).slice().sort();
      state.raw.products = (kbData.products || []).slice().sort();
      state.raw.tagCloud = kbData.tag_cloud || [];
      state.raw.senderAuthority = kbData.sender_authority || [];
      state.raw.meta = {
        generated_at: kbData.generated_at,
        total_articles: kbData.total_articles || kbData.articles.length,
        total_threads: kbData.total_threads || 0,
        total_messages: kbData.total_messages || 0
      };
      state.results = state.raw.articles.slice();
      state.isLoading = false;
      notify();
    },

    onChange: function (cb) {
      listeners.push(cb);
    },

    setQuery: function (text) {
      state.filters.query = text;
      recompute();
      notify();
    },

    toggleTag: function (tag) {
      if (state.filters.activeTags.has(tag)) {
        state.filters.activeTags.delete(tag);
      } else {
        state.filters.activeTags.add(tag);
      }
      recompute();
      notify();
    },

    toggleCategory: function (cat) {
      if (state.filters.activeCategories.has(cat)) {
        state.filters.activeCategories.delete(cat);
      } else {
        state.filters.activeCategories.add(cat);
      }
      recompute();
      notify();
    },

    toggleProduct: function (prod) {
      if (state.filters.activeProducts.has(prod)) {
        state.filters.activeProducts.delete(prod);
      } else {
        state.filters.activeProducts.add(prod);
      }
      recompute();
      notify();
    },

    setConfidence: function (level) {
      state.filters.confidence = state.filters.confidence === level ? null : level;
      recompute();
      notify();
    },

    setSort: function (sortKey) {
      state.filters.sort = sortKey;
      recompute();
      notify();
    },

    selectArticle: function (id) {
      state.selectedArticleId = id || null;
      notify();
    },

    clearFilters: function () {
      state.filters.query = "";
      state.filters.activeTags.clear();
      state.filters.activeCategories.clear();
      state.filters.activeProducts.clear();
      state.filters.confidence = null;
      state.filters.sort = "relevance";
      recompute();
      notify();
    },

    hasActiveFilters: function () {
      var f = state.filters;
      return f.query.length > 0 ||
        f.activeTags.size > 0 ||
        f.activeCategories.size > 0 ||
        f.activeProducts.size > 0 ||
        f.confidence !== null;
    }
  };
})();
