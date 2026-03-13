(function () {
  "use strict";
  var KB = window.KB = window.KB || {};

  var index = null;

  KB.Search = {
    init: function (articles) {
      if (typeof MiniSearch === "undefined") {
        console.warn("MiniSearch not loaded — search disabled");
        return;
      }

      index = new MiniSearch({
        fields: ["title", "problem", "solution", "tagsText", "productsText"],
        storeFields: ["article_id"],
        searchOptions: {
          boost: { title: 3, tagsText: 2, problem: 1.5, solution: 1, productsText: 1 },
          fuzzy: 0.2,
          prefix: true,
          combineWith: "AND"
        }
      });

      var docs = articles.map(function (a) {
        return {
          id: a.article_id,
          article_id: a.article_id,
          title: a.title || "",
          problem: a.problem || "",
          solution: a.solution || "",
          tagsText: (a.tags || []).join(" "),
          productsText: (a.products || []).join(" ")
        };
      });

      index.addAll(docs);
    },

    query: function (text) {
      var scores = new Map();
      if (!index || !text || text.length < 5) return scores;

      var results = index.search(text);
      for (var i = 0; i < results.length; i++) {
        scores.set(results[i].id, results[i].score);
      }
      return scores;
    }
  };
})();
