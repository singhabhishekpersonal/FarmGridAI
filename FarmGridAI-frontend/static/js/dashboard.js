/* ==========================================================================
   FarmGrid AI - Dashboard behaviour
   Page controllers for the analytics surfaces:
     - farm switcher + farm detail
     - expense dashboard, entry, summary, anomaly analysis
     - recommendations list, run, explain, feedback
     - subsidy matching and checklists
     - solar / grid / diesel comparison and projection
     - buy-vs-rent, repair-vs-replace, affordability, machinery decision
     - equipment list and per-equipment detail
     - chat session bootstrap and transcript rendering

   Each controller is registered on `KS.pages` and dispatched from the
   `[data-ks-page]` attribute on <body>.
   ========================================================================== */
(function (window, document) {
  "use strict";

  var KS = window.KS;
  if (!KS) return;

  var api = KS.api;
  var auth = KS.auth;
  var fmt = KS.fmt;
  var dom = KS.dom;
  var ui = KS.ui;
  var render = KS.render;
  var forms = KS.forms;
  var estimate = KS.estimate;

  var pages = {};
  KS.pages = pages;

  /* =====================================================================
     Farm context
     Every farm-scoped page needs the active farm id. Resolution order:
       1. data-ks-farm-id on <body> (server-rendered, authoritative)
       2. localStorage (last farm the farmer worked in)
       3. first farm from the list endpoint
     ===================================================================== */
  function farmId(scope) {
    var fromBody = dom.cfg("farmId", null);
    if (fromBody) return fromBody;
    var scopeAttr = (scope || document.body).getAttribute
      ? (scope || document.body).getAttribute("data-ks-farm-id")
      : null;
    if (scopeAttr) return scopeAttr;
    return auth.currentFarm();
  }

  function requireFarmId() {
    var id = farmId();
    if (!id) {
      ui.error("No farm selected. Add a farm first.");
      return null;
    }
    return id;
  }

  /* =====================================================================
     Shared: recommendation / decision card renderer
     Used by the machinery, solar, repair-replace and recommendation pages.
     ===================================================================== */

  /** Render the "reasons / assumptions / warnings / limitations" quartet. */
  function renderNarrative(result) {
    var r = result || {};
    var blocks = [];

    (r.reasons || []).forEach(function (x) {
      blocks.push("<li>" + dom.esc(x) + "</li>");
    });

    return (
      '<div class="ks-evidence ks-evidence--2">' +
      '<div class="ks-evidence-col">' +
      '<span class="ks-evidence-title">' + KS.t('Why this was suggested') + '</span>' +
      (blocks.length ? '<ul>' + blocks.join("") + "</ul>" : '<p class="ks-muted ks-tiny">' + KS.t('No reasons recorded.') + '</p>') +
      "</div>" +
      '<div class="ks-evidence-col">' +
      '<span class="ks-evidence-title">' + KS.t('Assumptions') + '</span>' +
      (r.assumptions && r.assumptions.length
        ? '<ul>' + r.assumptions.map(function (x) { return "<li>" + dom.esc(x) + "</li>"; }).join("") + "</ul>"
        : '<p class="ks-muted ks-tiny">' + KS.t('No assumptions recorded.') + '</p>') +
      "</div></div>"
    );
  }

  /* =====================================================================
     Shared form field builders
     ---------------------------------------------------------------------
     The attribute string carries the input type on purpose: emitting a hard
     coded type="text" alongside the caller's type="number" produced a
     duplicate attribute, and browsers honour the first one, so every numeric
     field silently rendered as a text box.
     ===================================================================== */

  /** `attrs` should carry the type; a bare text input is the default. */
  function field(label, name, value, attrs, prefix) {
    var id = (prefix || "sp-") + name;
    return (
      '<div class="ks-field"><label class="ks-label" for="' + id + '">' + dom.esc(label) + "</label>" +
      '<input class="ks-input" id="' + id + '" name="' + name + '" ' + (attrs || 'type="text"') +
      ' value="' + dom.esc(value == null ? "" : value) + '"></div>'
    );
  }

  function select(label, name, options, value, prefix) {
    var id = (prefix || "sp-") + name;
    return (
      '<div class="ks-field"><label class="ks-label" for="' + id + '">' + dom.esc(label) + "</label>" +
      '<select class="ks-select" id="' + id + '" name="' + name + '">' +
        options
          .map(function (o) {
            return '<option value="' + o + '"' + (value === o ? " selected" : "") + ">" + dom.esc(fmt.label(o)) + "</option>";
          })
          .join("") +
      "</select></div>"
    );
  }

  /** Render warnings + limitations as a prominent flag block. */
  function renderCaveats(result) {
    var r = result || {};
    var html = "";

    if (r.warnings && r.warnings.length) {
      html +=
        '<div class="ks-flag"><span class="ks-flag-icon" aria-hidden="true">⚠</span><span><strong>' + KS.t('Before you act:') + '</strong> ' +
        r.warnings.map(dom.esc).join(" ") +
        "</span></div>";
    }
    if (r.limitations && r.limitations.length) {
      html +=
        '<div class="ks-flag ks-flag-info"><span class="ks-flag-icon" aria-hidden="true">' + KS.t('ℹ') + '</span><span>' +
        r.limitations.map(dom.esc).join(" ") +
        "</span></div>";
    }
    if (r.requires_official_verification) {
      html +=
        '<div class="ks-flag"><span class="ks-flag-icon" aria-hidden="true">🔎</span><span>' +
        "This result depends on a subsidy figure. Verify it on the official portal.</span></div>";
    }
    return html;
  }

  function riskBadge(level) {
    var key = String(level || "").toLowerCase();
    if (key === "low") return '<span class="ks-badge ks-badge-ok">' + KS.t('Low risk') + '</span>';
    if (key === "medium") return '<span class="ks-badge ks-badge-warn">' + KS.t('Medium risk') + '</span>';
    if (key === "high") return '<span class="ks-badge ks-badge-danger">' + KS.t('High risk') + '</span>';
    return "";
  }

  /* =====================================================================
     PAGE: dashboard (home)
     ===================================================================== */
  pages.dashboard = function () {
    var host = dom.qs("[data-ks-dashboard]");
    if (!host) return;

    ui.loading(host, "Loading your farm overview…");

    api
      .farms()
      .then(function (farms) {
        var list = Array.isArray(farms) ? farms : farms.results || [];
        if (!list.length) {
          ui.empty(
            host,
            "No farm set up yet",
            "Add your first farm to unlock cost estimates, subsidy matching and equipment analysis.",
            '<a class="ks-btn ks-btn-secondary" href="/farms/new/">' + KS.t('Add your first farm') + '</a>'
          );
          return;
        }

        var farm = list[0];
        auth.setCurrentFarm(farm.id);
        renderFarmSummary(farm);

        return loadOpportunities(farm.id);
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });

    function renderFarmSummary(farm) {
      var loc = farm.location || {};
      var place = [loc.village, loc.district, loc.state].filter(Boolean).join(", ");

      dom.set(
        host,
        '<div class="ks-stack">' +
          '<div class="ks-farm-head">' +
            "<div>" +
              '<div class="ks-farm-title"><h1>' + dom.esc(farm.name) + "</h1>" +
              (farm.is_default ? '<span class="ks-badge ks-badge-brand">' + KS.t('Default farm') + '</span>' : "") +
              "</div>" +
              (place ? '<p class="ks-farm-loc">📍 ' + dom.esc(place) + "</p>" : "") +
            "</div>" +
            '<div class="ks-cluster">' +
              '<span class="ks-badge">' + dom.esc(fmt.area(farm.total_hectares, "hectare")) + " total</span>" +
              '<a class="ks-btn ks-btn-sm" href="/farms/' + encodeURIComponent(farm.id) + '/">' + KS.t('Open farm') + '</a>' +
            "</div>" +
          "</div>" +
          '<div class="ks-grid ks-grid-4" data-ks-dashboard-tiles></div>' +
          '<div data-ks-dashboard-recs></div>' +
        "</div>"
      );

      // Load the expense summary to fill the stat tiles.
      var tiles = dom.qs("[data-ks-dashboard-tiles]");
      ui.loading(tiles, "Loading expense summary…");

      api
        .expenseSummary(farm.id)
        .then(function (rows) {
          var list = Array.isArray(rows) ? rows : rows.results || [];
          var latest = null;
          list.forEach(function (r) {
            if (!latest || r.year > latest.year) latest = r;
          });

          if (!latest) {
            dom.set(
              tiles,
              '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Annual spending') + '</div>' +
                '<div class="ks-stat-value ks-stat-value--sm">' + KS.t('No data') + '</div>' +
                '<div class="ks-stat-foot"><a href="/farms/' + encodeURIComponent(farm.id) + '/expenses/add/">' + KS.t('Record an expense') + '</a></div></div>' +
                '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Land') + '</div>' +
                '<div class="ks-stat-value ks-stat-value--sm">' + dom.esc(fmt.hectares(farm.total_hectares)) + "</div>" +
                '<div class="ks-stat-foot">' + (farm.parcels || []).length + " parcel(s)</div></div>"
            );
            return;
          }

          dom.set(
            tiles,
            estimate.tile(
              "Recorded spend (" + latest.year + ")",
              latest.total_expected,
              latest.total_min,
              latest.total_max,
              latest.confidence
            ) +
              '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Cost per hectare') + '</div>' +
              '<div class="ks-stat-value ks-stat-value--sm">' + dom.esc(fmt.inrShort(latest.per_hectare)) + "</div>" +
              '<div class="ks-stat-foot">Across ' + dom.esc(fmt.hectares(farm.total_hectares)) + "</div></div>" +
              '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Land holding') + '</div>' +
              '<div class="ks-stat-value ks-stat-value--sm">' + dom.esc(fmt.hectares(farm.total_hectares)) + "</div>" +
              '<div class="ks-stat-foot">' + (farm.parcels || []).length + " parcel(s)</div></div>" +
              '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Data completeness') + '</div>' +
              '<div class="ks-stat-value ks-stat-value--sm">' + dom.esc(fmt.confidencePct(latest.data_completeness)) + "</div>" +
              '<div class="ks-stat-foot">' + KS.t('More records mean better estimates') + '</div></div>'
          );
        })
        .catch(function () {
          dom.set(
            tiles,
            '<div class="ks-stat"><div class="ks-stat-label">' + KS.t('Annual spending') + '</div>' +
              '<div class="ks-stat-value ks-stat-value--sm">—</div>' +
              '<div class="ks-stat-foot">' + KS.t('Could not load') + '</div></div>'
          );
        });

      loadRecommendations(farm.id);
    }

    function loadRecommendations(farmId) {
      var host = dom.qs("[data-ks-dashboard-recs]");
      if (!host) return;

      api
        .recommendations(farmId)
        .then(function (recs) {
          var list = Array.isArray(recs) ? recs : recs.results || [];
          if (!list.length) {
            dom.set(
              host,
              '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Recommendations') + '</h2></div>' +
                '<p class="ks-muted ks-small">' + KS.t('No recommendations yet. Run the engine to analyse your farm data.') + '</p>' +
                '<div class="ks-cluster"><button class="ks-btn ks-btn-sm" data-ks-run-recs>' + KS.t('Run recommendation engine') + '</button></div></div>'
            );
            bindRunRecs(host, farmId);
            return;
          }
          dom.set(host, '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Top recommendations') + '</h2>' +
            '<a class="ks-btn ks-btn-sm ks-btn-ghost" href="/farms/' + encodeURIComponent(farmId) + '/recommendations/">' + KS.t('View all') + '</a></div>' +
            '<div class="ks-grid ks-grid-2">' + list.slice(0, 4).map(recCard).join("") + "</div></div>");
        })
        .catch(function () {
          dom.set(host, "");
        });
    }

    function recCard(rec) {
      return (
        '<div class="ks-rec" data-priority="' + dom.esc(rec.priority || "low") + '">' +
        '<div class="ks-rec-head"><h3>' + dom.esc(rec.title) + "</h3>" +
        (rec.priority ? '<span class="ks-badge">' + dom.esc(fmt.label(rec.priority)) + "</span>" : "") +
        "</div>" +
        '<p class="ks-rec-text">' + dom.esc(rec.text) + "</p>" +
        (rec.expected_benefit_min !== null && rec.expected_benefit_min !== undefined
          ? '<div class="ks-rec-benefit"><span class="ks-tiny ks-muted">' + KS.t('Expected benefit') + '</span><br>' +
            '<span class="ks-money ks-money--ok ks-money-md">' +
            dom.esc(fmt.inr(rec.expected_benefit_min)) +
            (rec.expected_benefit_max && rec.expected_benefit_max !== rec.expected_benefit_min
              ? ' <span class="ks-money-range">to ' + dom.esc(fmt.inr(rec.expected_benefit_max)) + "</span>"
              : "") +
            "</span></div>"
          : "") +
        "</div>"
      );
    }

    function bindRunRecs(scope, farmId) {
      dom.on(scope, "[data-ks-run-recs]", "click", function () {
        var btn = this;
        var restore = ui.busy(btn, true, "Analysing…");
        api
          .post("/farms/" + farmId + "/recommendations/run", { use_ml_ranker: true })
          .then(function () {
            restore();
            ui.ok("Recommendations generated.");
            window.location.reload();
          })
          .catch(function (err) {
            restore();
            ui.error(err.message);
          });
      });
    }

    function loadOpportunities(id) {
      // Cost-saving opportunities are rendered on the recommendations page.
      return api
        .get("/farms/" + id + "/opportunities", null, { skipErrors: true })
        .catch(function () {
          return null;
        });
    }
  };

  /* =====================================================================
     PAGE: farm detail
     ===================================================================== */
  pages.farm = function () {
    var id = farmId();
    if (!id) {
      window.location.replace("/farms/new/");
      return;
    }

    var host = dom.qs("[data-ks-farm]");
    if (!host) return;
    ui.loading(host, "Loading farm…");

    api
      .farm(id)
      .then(function (farm) {
        auth.setCurrentFarm(farm.id);
        renderFarm(farm);
        loadFarmSummary(farm.id);
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });

    function renderFarm(farm) {
      var loc = farm.location || {};
      var place = [loc.village, loc.district, loc.state].filter(Boolean).join(", ");
      var parcels = farm.parcels || [];

      dom.set(
        host,
        '<div class="ks-farm-head">' +
          "<div>" +
            '<div class="ks-farm-title"><h1>' + dom.esc(farm.name) + "</h1>" +
            (farm.is_default ? '<span class="ks-badge ks-badge-brand">' + KS.t('Default') + '</span>' : "") +
            '<span class="ks-badge">' + dom.esc(fmt.area(farm.total_hectares, "hectare")) + "</span></div>" +
            (place ? '<p class="ks-farm-loc">📍 ' + dom.esc(place) + "</p>" : "") +
            (farm.description ? '<p class="ks-small ks-muted ks-mt-3">' + dom.esc(farm.description) + "</p>" : "") +
          "</div>" +
          '<div class="ks-cluster">' +
            '<a class="ks-btn ks-btn-sm" href="/farms/' + encodeURIComponent(farm.id) + '/expenses/">' + KS.t('Expenses') + '</a>' +
            '<a class="ks-btn ks-btn-sm" href="/farms/' + encodeURIComponent(farm.id) + '/equipment/">' + KS.t('Equipment') + '</a>' +
            '<a class="ks-btn ks-btn-sm ks-btn-secondary" href="/farms/' + encodeURIComponent(farm.id) + '/energy/solar/">' + KS.t('Solar') + '</a>' +
            '<a class="ks-btn ks-btn-sm ks-btn-secondary" href="/farms/' + encodeURIComponent(farm.id) + '/finance/">' + KS.t('Decisions') + '</a>' +
          "</div>" +
        "</div>" +

        '<div class="ks-tabs" role="tablist" data-ks-tabs>' +
          '<button class="ks-tab" role="tab" id="tab-parcels" aria-controls="panel-parcels" aria-selected="true" data-tab="parcels">' + KS.t('Land parcels') + '</button>' +
          '<button class="ks-tab" role="tab" id="tab-crops" aria-controls="panel-crops" aria-selected="false" data-tab="crops">' + KS.t('Crops') + '</button>' +
          '<button class="ks-tab" role="tab" id="tab-summary" aria-controls="panel-summary" aria-selected="false" data-tab="summary">' + KS.t('Summary') + '</button>' +
        "</div>" +

        '<div id="panel-parcels" class="ks-tabpanel" role="tabpanel" aria-labelledby="tab-parcels">' +
          '<div class="ks-between ks-mb-4"><h2>' + KS.t('Land parcels') + '</h2>' +
          '<a class="ks-btn ks-btn-sm ks-btn-secondary" href="/farms/' + encodeURIComponent(farm.id) + '/parcels/new/">' + KS.t('+ Add parcel') + '</a></div>' +
          (parcels.length
            ? '<div class="ks-grid ks-grid-3">' + parcels.map(parcelCard).join("") + "</div>"
            : ui.emptyHtml("No parcels recorded", "Add a land parcel so estimates can be scaled to your actual land.")) +
        "</div>" +

        '<div id="panel-crops" class="ks-tabpanel" role="tabpanel" aria-labelledby="tab-crops" hidden>' +
          '<div class="ks-between ks-mb-4"><h2>' + KS.t('Crop estimates') + '</h2>' +
          '<a class="ks-btn ks-btn-sm ks-btn-secondary" href="/farms/' + encodeURIComponent(farm.id) + '/crops/">' + KS.t('+ Add crop') + '</a></div>' +
          '<div data-ks-crops></div>' +
        "</div>" +

        '<div id="panel-summary" class="ks-tabpanel" role="tabpanel" aria-labelledby="tab-summary" hidden>' +
          '<div data-ks-summary></div>' +
        "</div>"
      );

      loadCrops(farm.id);
    }

    function parcelCard(p) {
      var meta = [];
      if (p.soil_type) meta.push("Soil: " + p.soil_type);
      if (p.ownership) meta.push(fmt.label(p.ownership));
      if (p.irrigated) meta.push("Irrigated");
      if (p.irrigation_source) meta.push(fmt.label(p.irrigation_source));

      // Bigha cannot be converted without a regional rule - say so, do not guess.
      var warn = p.area_requires_confirmation
        ? '<div class="ks-bigha-warn"><span aria-hidden="true">⚠</span><span>' +
          dom.esc(p.conversion_note || KS.t("This area uses a regional unit we cannot convert confidently. Please confirm the hectare figure.")) +
          "</span></div>"
        : "";

      return (
        '<div class="ks-parcel' + (p.is_primary ? " ks-parcel--primary" : "") + '">' +
        '<div class="ks-parcel-head">' +
        '<span class="ks-parcel-name">' + dom.esc(p.name || "Parcel") + "</span>" +
        (p.is_primary ? '<span class="ks-badge ks-badge-brand">' + KS.t('Primary') + '</span>' : "") +
        "</div>" +
        '<div class="ks-parcel-area">' + dom.esc(fmt.hectares(p.area_hectares)) + "</div>" +
        '<div class="ks-parcel-meta"><span>' + dom.esc(fmt.acres(p.area_acre)) + "</span>" +
        (p.unit ? "<span>· " + dom.esc(fmt.label(p.unit)) + "</span>" : "") + "</div>" +
        (meta.length ? '<div class="ks-parcel-meta">' + meta.map(function (m) { return "<span>" + dom.esc(m) + "</span>"; }).join("") + "</div>" : "") +
        warn +
        "</div>"
      );
    }

    function cropRowTotals(row) {
      // Per-crop estimate rows nest the money block under "total"; the list
      // endpoint has historically returned a flatter shape, so accept both.
      var e = row.estimate || row.total || row;
      return {
        minimum: e.minimum !== undefined ? e.minimum : e.total_min_inr,
        maximum: e.maximum !== undefined ? e.maximum : e.total_max_inr,
        expected: e.expected !== undefined ? e.expected : e.expected_total_inr,
        confidence: e.confidence,
        assumptions: e.assumptions || [],
        limitations: e.limitations || [],
      };
    }

    function cropRowsFrom(payload) {
      // /crops/estimates answers {crop_estimates, totals, farm_id}. Tolerate a
      // bare list or a paginated {results} so this keeps working either way.
      if (!payload) return { rows: [], totals: null };
      if (Array.isArray(payload)) return { rows: payload, totals: null };
      var rows = payload.crop_estimates;
      if (!Array.isArray(rows)) rows = Array.isArray(payload.results) ? payload.results : [];
      return { rows: rows, totals: payload.totals || null };
    }

    function cropTotalsBar(totals) {
      if (!totals) return "";
      var rows = [
        ["Expected", fmt.inr(totals.expected)],
        ["Minimum", fmt.inr(totals.minimum)],
        ["Maximum", fmt.inr(totals.maximum)],
      ];
      return (
        '<div class="ks-grid ks-grid-3 ks-mb-4">' +
        rows
          .map(function (r) {
            return (
              '<div class="ks-stat"><span class="ks-stat-label">' + dom.esc(r[0]) +
              '</span><span class="ks-stat-value ks-stat-value--sm">' + dom.esc(r[1]) + "</span></div>"
            );
          })
          .join("") +
        "</div>"
      );
    }

    function cropDetailPanel(row) {
      var t = cropRowTotals(row);
      var notes = [];
      if (t.assumptions.length) {
        notes.push(
          "<dt>" + KS.t("Assumptions") + "</dt><dd><ul>" +
            t.assumptions
              .map(function (a) { return "<li>" + dom.esc(a) + "</li>"; })
              .join("") +
            "</ul></dd>"
        );
      }
      if (t.limitations.length) {
        notes.push(
          "<dt>" + KS.t("Limitations") + "</dt><dd><ul>" +
            t.limitations
              .map(function (a) { return "<li>" + dom.esc(a) + "</li>"; })
              .join("") +
            "</ul></dd>"
        );
      }
      if (!notes.length) return "";
      return '<details class="ks-estimate-notes"><summary>' + KS.t('How this was calculated') + '</summary><dl class="ks-datalist">' + notes.join("") + "</dl></details>";
    }

    function renderCropTable(id, rows, totals) {
      var cols = [
        { label: "Crop", value: function (r) { return fmt.label(r.crop || r.name || "—"); } },
        {
          label: "Area",
          value: function (r) {
            var a = r.area_acres !== undefined ? r.area_acres : r.area;
            return a === undefined || a === null ? "—" : fmt.acres(a);
          },
          numeric: true,
        },
        {
          label: "Input cost (expected)",
          numeric: true,
          value: function (r) { return fmt.inr(cropRowTotals(r).expected); },
        },
        {
          label: "Range",
          numeric: true,
          value: function (r) {
            var t = cropRowTotals(r);
            var lo = t.minimum;
            var hi = t.maximum;
            return lo !== undefined && hi !== undefined && lo !== null && hi !== null
              ? fmt.inrShort(lo) + " – " + fmt.inrShort(hi)
              : "—";
          },
        },
        {
          label: "Confidence",
          value: function (r) { return render.confBadge(cropRowTotals(r).confidence); },
          html: true,
        },
        {
          label: "",
          html: true,
          value: function (r) {
            var key = r.farm_crop_id || r.id;
            if (!key) return "—";
            return (
              '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button"' +
              ' data-ks-crop-estimate="' + dom.esc(key) + '">' + KS.t('Re-estimate') + '</button>' +
              (cropDetailPanel(r) || "")
            );
          },
        },
      ];
      return cropTotalsBar(totals) + render.table(cols, rows, { empty: "No crop estimates available." });
    }

    function loadCrops(id) {
      var host = dom.qs("[data-ks-crops]");
      if (!host) return;
      ui.loading(host, "Loading crop estimates…");
      api
        .get("/farms/" + id + "/crops")
        .then(function (crops) {
          var list = Array.isArray(crops) ? crops : crops.results || [];
          if (!list.length) {
            ui.empty(host, "No crops added", "Add a crop to get input-cost estimates for the season.");
            return;
          }
          return api.get("/farms/" + id + "/crops/estimates").then(function (est) {
            var parsed = cropRowsFrom(est);
            dom.set(host, renderCropTable(id, parsed.rows, parsed.totals));
            // Re-estimate a single crop: POST recomputes that one row so the
            // farmer can refresh a cost figure after changing anything.
            dom.on(host, "[data-ks-crop-estimate]", "click", function () {
              var cropId = this.getAttribute("data-ks-crop-estimate");
              if (!cropId) return;
              var btn = this;
              ui.busy(btn, true, "Estimating…");
              api
                .post("/farms/" + id + "/crops/" + encodeURIComponent(cropId) + "/estimate", {})
                .then(function (fresh) {
                  var parsedFresh = cropRowsFrom(fresh);
                  var updated = parsedFresh.rows && parsedFresh.rows.length
                    ? parsedFresh.rows[0]
                    : fresh;
                  var i = -1;
                  for (var k = 0; k < parsed.rows.length; k++) {
                    var key = parsed.rows[k].farm_crop_id || parsed.rows[k].id;
                    if (key === cropId) { i = k; break; }
                  }
                  if (i === -1) {
                    parsed.rows.push(updated);
                    i = parsed.rows.length - 1;
                  } else {
                    parsed.rows[i] = updated;
                  }
                  ui.ok("Estimate updated for " + fmt.label(updated.crop || "crop") + ".");
                  dom.set(host, renderCropTable(id, parsed.rows, parsed.totals));
                })
                .catch(function (err) {
                  ui.busy(btn, false);
                  ui.errorState(host, err);
                });
            });
          });
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    function loadFarmSummary(id) {
      var host = dom.qs("[data-ks-summary]");
      if (!host) return;
      ui.loading(host, "Computing farm summary…");
      api
        .farmSummary(id)
        .then(function (s) {
          dom.set(
            host,
            '<div class="ks-grid ks-grid-2">' +
              '<div class="ks-card"><div class="ks-card-head"><h3 class="ks-card-title">' + KS.t('Land') + '</h3></div>' +
              render.datalist({
                "Total area": fmt.area(s.total_hectares, "hectare"),
                "Total acres": fmt.number(s.total_acre),
                "Parcels": s.parcel_count,
              }) +
              "</div>" +
              '<div class="ks-card"><div class="ks-card-head"><h3 class="ks-card-title">' + KS.t('Season') + '</h3></div>' +
              render.datalist({
                Year: s.year,
                Crops: s.crop_count,
                Equipment: s.equipment_count,
                "Data completeness": fmt.confidencePct(s.data_completeness),
              }) +
              "</div>" +
            "</div>"
          );
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }
  };

  /* =====================================================================
     PAGE: expense dashboard
     ===================================================================== */
  pages.expenses = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-expenses]");
    if (!host) return;

    var state = { page: 1, pageSize: 20, count: 0, filter: "all" };
    ui.loading(host, "Loading expenses…");

    load();

    function load() {
      api
        .get("/farms/" + id + "/expenses", { page: state.page, page_size: state.pageSize })
        .then(function (payload) {
          var rows = Array.isArray(payload) ? payload : payload.results || [];
          state.count = Array.isArray(payload) ? rows.length : payload.count || rows.length;
          renderList(rows);
          return api.expenseSummary(id);
        })
        .then(function (rows) {
          var list = Array.isArray(rows) ? rows : rows.results || [];
          if (!list.length) return;
          var latest = list.reduce(function (acc, r) {
            return !acc || r.year > acc.year ? r : acc;
          }, null);
          if (latest) renderTotals(latest);
          renderPagination();
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    function renderTotals(s) {
      var host = dom.qs("[data-ks-expense-total]");
      if (!host) return;
      dom.set(
        host,
        '<div class="ks-expense-total">' +
          "<div>" +
            "<dt>Recorded spend · " + dom.esc(s.year) + "</dt>" +
            "<dd>" + dom.esc(fmt.inr(s.total_expected)) + "</dd>" +
            '<span class="ks-expense-range">Range ' + dom.esc(fmt.inr(s.total_min)) + " – " + dom.esc(fmt.inr(s.total_max)) + "</span>" +
          "</div>" +
          '<dl class="ks-stat-inline">' +
            "<div><dt>" + KS.t("Per hectare") + "</dt><dd>" + dom.esc(fmt.inr(s.per_hectare)) + "</dd></div>" +
            "<div><dt>" + KS.t("Completeness") + "</dt><dd>" + dom.esc(fmt.confidencePct(s.data_completeness)) + "</dd></div>" +
            "<div><dt>" + KS.t("Confidence") + "</dt><dd>" + render.confBadge(s.confidence) + "</dd></div>" +
          "</dl>" +
        "</div>"
      );

      var bars = dom.qs("[data-ks-expense-bars]");
      if (bars && s.by_category) dom.set(bars, render.bars(s.by_category));
    }

    function renderList(rows) {
      var listHost = dom.qs("[data-ks-expense-list]");
      if (!listHost) return;
      if (!rows.length) {
        ui.empty(
          listHost,
          "No expenses recorded",
          "Record fuel, inputs, labour, transport and bills to unlock cost analysis.",
          '<a class="ks-btn ks-btn-secondary" href="/farms/' + encodeURIComponent(id) + '/expenses/add/">' + KS.t('Record an expense') + '</a>'
        );
        return;
      }

      dom.set(
        listHost,
        render.table(
          [
            { label: "Date", value: function (r) { return fmt.date(r.occurred_on); } },
            { label: "Category", value: function (r) { return fmt.label(r.category); } },
            { label: "Type", value: function (r) { return fmt.label(r.expense_type); } },
            { label: "Note", value: function (r) { return r.note || "—"; } },
            { label: "Amount", numeric: true, value: function (r) { return fmt.inr(r.amount); } },
          ],
          rows,
          { rowClass: function (r) { return r.is_anomaly ? "ks-row-flagged" : ""; } }
        )
      );
    }

    function renderPagination() {
      if (Array.isArray(arguments[0])) return;
      render.mountPagination(dom.qs("[data-ks-expense-pager]"), state, function (p) {
        state.page = p;
        load();
      });
    }

    // Filter chips filter the already-loaded rows client-side.
    dom.on(document, "click", "[data-ks-expense-filter]", function () {
      var chip = this;
      dom.qsa("[data-ks-expense-filter]").forEach(function (c) {
        c.setAttribute("aria-pressed", c === chip ? "true" : "false");
      });
      state.filter = chip.dataset.ksExpenseFilter;
      api
        .get("/farms/" + id + "/expenses", { page: state.page, page_size: state.pageSize })
        .then(function (payload) {
          var rows = Array.isArray(payload) ? payload : payload.results || [];
          if (state.filter !== "all") {
            rows = rows.filter(function (r) {
              return r.expense_type === state.filter || r.category === state.filter;
            });
          }
          renderList(rows);
        })
        .catch(function (err) {
          ui.errorState(dom.qs("[data-ks-expense-list]"), err);
        });
    });

    // Anomaly analysis.
    dom.on(document, "[data-ks-analyze-expenses]", "click", function () {
      var btn = this;
      var host = dom.qs("[data-ks-expense-analysis]");
      var restore = ui.busy(btn, true, "Analysing…");
      ui.loading(host, "Looking for unusual spending…");
      api
        .post("/farms/" + id + "/expenses/analysis", {})
        .then(function (result) {
          restore();
          renderAnomalies(host, result);
        })
        .catch(function (err) {
          restore();
          ui.errorState(host, err);
        });
    });

    function renderAnomalies(host, result) {
      var anomalies = result.anomalies || [];
      if (!anomalies.length) {
        dom.set(
          host,
          '<div class="ks-alert ks-alert-ok"><span aria-hidden="true">✓</span><div>' +
            "<strong class='ks-alert-title'>" + KS.t("No unusual spending detected") + "</strong>" +
            dom.esc(result.note || KS.t("Spending looks consistent with your own history.")) +
            "</div></div>"
        );
        return;
      }

      dom.set(
        host,
        '<div class="ks-alert ks-alert-warn ks-mb-4"><span aria-hidden="true">⚠</span><div>' +
          "<strong class='ks-alert-title'>" + anomalies.length + " unusual item(s) flagged</strong>" +
          dom.esc(result.note || "") +
          "</div></div>" +
          render.table(
            [
              { label: "Period", value: function (a) { return a.period; } },
              { label: "Category", value: function (a) { return fmt.label(a.category); } },
              { label: "Amount", numeric: true, value: function (a) { return fmt.inr(a.amount); } },
              { label: "Excess", numeric: true, value: function (a) { return fmt.inr(a.excess_amount); } },
              {
                label: "Severity",
                html: true,
                value: function (a) {
                  var s = String(a.severity || "").toLowerCase();
                  var cls = s === "high" ? "ks-badge-danger" : s === "medium" ? "ks-badge-warn" : "ks-badge";
                  return '<span class="ks-badge ' + cls + '">' + dom.esc(fmt.label(a.severity)) + "</span>";
                },
              },
              { label: "Why", value: function (a) { return a.explanation || a.label; } },
            ],
            anomalies,
            { rowClass: function () { return "ks-row-flagged"; } }
          ) +
          '<div class="ks-mt-4 ks-small ks-muted">Method: ' + dom.esc(fmt.label(result.model)) +
          " · Rows analysed: " + dom.esc(result.rows_analysed) +
          " · Data completeness: " + dom.esc(fmt.confidencePct(result.data_completeness)) + "</div>"
      );
    }
  };

  /* =====================================================================
     PAGE: expense entry
     ===================================================================== */
  pages.expenseEntry = function () {
    var id = requireFarmId();
    if (!id) return;

    /* The receipt picker files documents against ExpenseCategory.code. Pull the
       seeded rows so labels stay server-owned; on any failure the template's
       static options remain in place, because the codes are a stable contract
       and an unreachable list must not block uploading a bill. */
    var docCategory = dom.qs("[data-ks-doc-category]");
    if (docCategory) {
      api
        .get("/farms/" + id + "/expenses/categories")
        .then(function (rows) {
          if (!rows || !rows.length) return;
          var chosen = docCategory.value;
          while (docCategory.firstChild) docCategory.removeChild(docCategory.firstChild);
          docCategory.appendChild(dom.el("option", { value: "", text: "General receipt" }));
          rows.forEach(function (row) {
            docCategory.appendChild(dom.el("option", { value: row.code, text: row.name }));
          });
          docCategory.value = chosen;
        })
        .catch(function () {
          /* keep the static options */
        });
    }

    var TYPES = [
      { key: "fuel", icon: "⛽", label: "Fuel / Diesel", hint: "Petrol, diesel" },
      { key: "input", icon: "🌱", label: "Seeds & Fertilizer", hint: "Crop inputs" },
      { key: "labour", icon: "👷", label: "Labour", hint: "Person-days, wages" },
      { key: "electricity", icon: "💡", label: "Electricity Bill", hint: "Tariff, units" },
      { key: "transport", icon: "🚜", label: "Transport", hint: "Distance, vehicle" },
      { key: "rental", icon: "🔧", label: "Equipment Rental", hint: "Hours or days" },
    ];

    var typeCards = dom.qs("[data-ks-type-picker]");
    if (typeCards) {
      dom.set(
        typeCards,
        TYPES.map(function (t, i) {
          return (
            '<button type="button" class="ks-type-card" data-ks-type="' + t.key + '" aria-pressed="' + (i === 0 ? "true" : "false") + '">' +
            '<span class="ks-type-icon" aria-hidden="true">' + t.icon + "</span>" +
            '<span class="ks-type-name">' + dom.esc(t.label) + "</span>" +
            '<span class="ks-type-hint">' + dom.esc(t.hint) + "</span>" +
            "</button>"
          );
        }).join("")
      );

      dom.qsa("[data-ks-type]", typeCards).forEach(function (btn) {
        btn.addEventListener("click", function () {
          dom.qsa("[data-ks-type]", typeCards).forEach(function (b) {
            b.setAttribute("aria-pressed", b === btn ? "true" : "false");
          });
          var key = btn.dataset.ksType;
          dom.qsa("[data-ks-type-form]").forEach(function (panel) {
            panel.hidden = panel.dataset.ksTypeForm !== key;
          });
        });
      });

      // Activate the first type panel.
      var first = dom.qs('[data-ks-type-form="' + TYPES[0].key + '"]');
      if (first) first.hidden = false;
    }

    var selectedType = "fuel";
    dom.on(document, "click", "[data-ks-type]", function () {
      selectedType = this.dataset.ksType;
    });

    // One endpoint per typed expense model; the generic list is the fallback.
    var ENDPOINTS = {
      fuel: "/expenses/fuel",
      input: "/expenses/inputs",
      labour: "/expenses/labour",
      electricity: "/expenses/electricity",
      transport: "/expenses/transport",
      rental: "/expenses/rental",
    };

    var form = dom.qs("[data-ks-expense-form]");
    if (!form) return;

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      forms.clearSummary(dom.qs("[data-ks-error-summary]", form));
      if (!forms.validate(form)) return;

      var data = forms.read(form);
      var endpoint = ENDPOINTS[selectedType] || "/expenses";
      var body = buildTypedBody(selectedType, data);

      ui.submit(form, function () {
        return api.post("/farms/" + id + endpoint, body);
      })
        .then(function () {
          ui.ok("Expense saved.");
          window.location.href = "/farms/" + id + "/expenses/";
        })
        .catch(function (err) {
          if (err instanceof KS.ApiError) forms.showErrorSummary(form, err);
        });
    });

    /**
     * The bill month input is <input type="month">, which yields "2026-06".
     * ElectricityBillSerializer declares bill_month as a DateField, so the
     * raw value is rejected with "Date has wrong format." Normalise a bare
     * year-month to the first of that month and leave everything else alone.
     */
    function monthToDate(value) {
      var raw = (value || "").trim();
      if (!raw) return null;
      if (/^\d{4}-\d{2}$/.test(raw)) return raw + "-01";
      return raw;
    }

    function buildTypedBody(type, d) {
      var base = { occurred_on: d.occurred_on, note: d.note || "" };
      if (type === "fuel") {
        return Object.assign(base, {
          amount: Number(d.amount),
          litre_volume: d.litre_volume ? Number(d.litre_volume) : null,
          price_per_litre: d.price_per_litre ? Number(d.price_per_litre) : null,
          fuel_type: d.fuel_type || "diesel",
          purpose: d.purpose || "",
        });
      }
      if (type === "input") {
        return Object.assign(base, {
          amount: Number(d.amount),
          input_type: d.input_type || "general",
          product_name: d.product_name || "",
          quantity: d.quantity ? Number(d.quantity) : null,
          quantity_unit: d.quantity_unit || "kg",
        });
      }
      if (type === "labour") {
        return Object.assign(base, {
          amount: Number(d.amount),
          labour_type: d.labour_type || "general",
          person_days: d.person_days ? Number(d.person_days) : null,
          wage_per_day: d.wage_per_day ? Number(d.wage_per_day) : null,
        });
      }
      if (type === "electricity") {
        return Object.assign(base, {
          amount: Number(d.amount),
          provider: d.provider || "",
          units_kwh: d.units_kwh ? Number(d.units_kwh) : null,
          bill_month: monthToDate(d.bill_month),
        });
      }
      if (type === "transport") {
        return Object.assign(base, {
          amount: Number(d.amount),
          vehicle_type: d.vehicle_type || "tractor",
          distance_km: d.distance_km ? Number(d.distance_km) : null,
        });
      }
      return Object.assign(base, {
        amount: Number(d.amount),
        equipment_class: d.equipment_class || "tractor",
        rental_hours: d.rental_hours ? Number(d.rental_hours) : null,
        rental_days: d.rental_days ? Number(d.rental_days) : null,
      });
    }
  };

  /* =====================================================================
     PAGE: recommendations
     ===================================================================== */
  pages.recommendations = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-recs]");
    if (!host) return;
    ui.loading(host, "Loading recommendations…");

    load();

    dom.on(document, "[data-ks-run-recs]", "click", function () {
      var btn = this;
      var restore = ui.busy(btn, true, "Analysing your farm…");
      api
        .post("/farms/" + id + "/recommendations/run", { use_ml_ranker: true })
        .then(function (result) {
          restore();
          ui.ok("Analysis complete.");
          dom.set(
            dom.qs("[data-ks-run-summary]"),
            '<div class="ks-alert ks-alert-ok ks-mb-4"><span aria-hidden="true">✓</span><div>' +
              "<strong class='ks-alert-title'>" + KS.t("Analysis complete") + "</strong>" +
              dom.esc((result && result.summary) || KS.t("Recommendations were regenerated from your latest farm data.")) +
              "</div></div>"
          );
          load();
        })
        .catch(function (err) {
          restore();
          ui.error(err.message);
        });
    });

    function load() {
      api
        .recommendations(id)
        .then(function (recs) {
          var list = Array.isArray(recs) ? recs : recs.results || [];
          renderList(list);
          loadRunHistory();
          return loadOpportunities();
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    /* Run history from GET /farms/{id}/recommendation-runs. Each row carries the
       run status, an overall score and the models that participated. */
    var runHistoryHost = dom.qs("[data-ks-run-history]");

    function runSummaryText(summaryJson) {
      if (!summaryJson) return "";
      if (typeof summaryJson === "string") return summaryJson;
      if (typeof summaryJson.summary === "string") return summaryJson.summary;
      var parts = [];
      if (summaryJson.summary) parts.push(summaryJson.summary);
      if (summaryJson.total !== undefined) parts.push(fmt.number(summaryJson.total) + " total");
      if (summaryJson.count !== undefined) parts.push(summaryJson.count + " items");
      return parts.join(" · ");
    }

    function renderRunHistory(runs) {
      if (!runHistoryHost) return;
      if (!runs.length) {
        dom.set(
          runHistoryHost,
          '<p class="ks-muted ks-small">' + KS.t('No analysis runs recorded yet. Run the engine to create the first one.') + '</p>'
        );
        return;
      }
      dom.set(
        runHistoryHost,
        render.table(
          [
            { label: "When", value: function (r) { return fmt.dateTime(r.created_at); } },
            {
              label: "Status",
              html: true,
              value: function (r) {
                var v = String(r.status || "");
                var tone = /complete|success|done/i.test(v)
                  ? "ks-badge-ok"
                  : /fail|error/i.test(v)
                  ? "ks-badge-warn"
                  : "ks-badge";
                return '<span class="ks-badge ' + tone + '">' + dom.esc(fmt.label(v || "—")) + "</span>";
              },
            },
            {
              label: "Score",
              numeric: true,
              value: function (r) { return r.score === null || r.score === undefined ? "—" : fmt.number(r.score, 3); },
            },
            { label: "Summary", value: function (r) { return runSummaryText(r.summary_json); } },
            {
              label: "Models used",
              html: true,
              value: function (r) {
                var m = r.models_used_json;
                var list = Array.isArray(m) ? m : m && typeof m === "object" ? Object.keys(m) : [];
                if (!list.length) return "—";
                return list
                  .map(function (n) { return '<span class="ks-badge">' + dom.esc(fmt.label(n)) + "</span>"; })
                  .join(" ");
              },
            },
          ],
          runs,
          { empty: "No analysis runs recorded yet." }
        )
      );
    }

    function loadRunHistory() {
      if (!runHistoryHost) return;
      ui.loading(runHistoryHost, "Loading run history…");
      api
        .get("/farms/" + id + "/recommendation-runs")
        .then(function (payload) {
          var runs = Array.isArray(payload) ? payload : payload.results || [];
          runs.sort(function (a, b) {
            return String(b.created_at || "").localeCompare(String(a.created_at || ""));
          });
          renderRunHistory(runs);
        })
        .catch(function (err) {
          ui.errorState(runHistoryHost, err);
        });
    }

    function renderList(list) {
      if (!list.length) {
        ui.empty(
          host,
          "No recommendations yet",
          "Run the engine to analyse your expenses, crop costs and energy usage.",
          '<button class="ks-btn" data-ks-run-recs>' + KS.t('Run recommendation engine') + '</button>'
        );
        return;
      }

      dom.set(
        host,
        '<div class="ks-cluster ks-mb-4">' +
          '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-run-recs>' + KS.t('Re-run analysis') + '</button>' +
          '<span class="ks-badge">' + list.length + " recommendation(s)</span>" +
        "</div>" +
        '<div class="ks-grid ks-grid-2">' + list.map(card).join("") + "</div>"
      );

      dom.qsa("[data-ks-explain]", host).forEach(function (btn) {
        btn.addEventListener("click", function () {
          explain(btn.dataset.ksExplain, btn);
        });
      });
    }

    function card(rec) {
      var steps = rec.next_steps || [];
      return (
        '<div class="ks-rec" data-priority="' + dom.esc(rec.priority || "low") + '">' +
        '<div class="ks-rec-head">' +
          "<h3>" + dom.esc(rec.title) + "</h3>" +
          '<div class="ks-cluster">' +
            (rec.priority ? '<span class="ks-badge">' + dom.esc(fmt.label(rec.priority)) + "</span>" : "") +
            (rec.confidence ? render.confBadge(rec.confidence) : "") +
          "</div>" +
        "</div>" +
        '<p class="ks-rec-text">' + dom.esc(rec.text) + "</p>" +
        (rec.expected_benefit_min !== null && rec.expected_benefit_min !== undefined
          ? '<div class="ks-rec-benefit"><span class="ks-tiny ks-muted">' + KS.t('Expected benefit') + '</span><br>' +
            '<span class="ks-money ks-money--ok ks-money-md">' + dom.esc(fmt.inr(rec.expected_benefit_min)) +
            (rec.expected_benefit_max && rec.expected_benefit_max !== rec.expected_benefit_min
              ? '<span class="ks-money-range"> to ' + dom.esc(fmt.inr(rec.expected_benefit_max)) + "</span>"
              : "") +
            "</span></div>"
          : "") +
        (rec.financial_risk_level
          ? '<div class="ks-mb-3">' + riskBadge(rec.financial_risk_level) + "</div>"
          : "") +
        (steps.length
          ? '<div class="ks-rec-nextsteps"><strong>' + KS.t('Next steps') + '</strong><ol>' +
            steps.map(function (s) { return "<li>" + dom.esc(s) + "</li>"; }).join("") +
            "</ol></div>"
          : "") +
        '<div class="ks-rec-nextsteps" data-ks-explain-host="' + dom.esc(rec.id) + '"></div>' +
        '<div class="ks-cluster ks-mt-3">' +
          '<button class="ks-btn ks-btn-sm ks-btn-ghost" data-ks-explain="' + dom.esc(rec.id) + '">' + KS.t('Why this?') + '</button>' +
          '<button class="ks-btn ks-btn-sm ks-btn-ghost" data-ks-helpful="' + dom.esc(rec.id) + '">' + KS.t('Helpful') + '</button>' +
          '<button class="ks-btn ks-btn-sm ks-btn-ghost" data-ks-nothelpful="' + dom.esc(rec.id) + '">' + KS.t('Not helpful') + '</button>' +
        "</div>" +
        "</div>"
      );
    }

    function explain(recId, btn) {
      var host = dom.qs('[data-ks-explain-host="' + recId + '"]');
      if (!host) return;
      if (host.dataset.open === "true") {
        dom.set(host, "");
        host.dataset.open = "false";
        btn.textContent = "Why this?";
        return;
      }
      ui.loading(host, "Building explanation…");
      api
        .get("/farms/" + id + "/recommendations/" + recId + "/explain")
        .then(function (ex) {
          host.dataset.open = "true";
          btn.textContent = "Hide";
          dom.set(
            host,
            renderNarrative({
              reasons: ex.reasons || (ex.evidence || []).map(function (e) { return e.description; }),
              assumptions: ex.assumptions || (ex.assumptions || []).map(function (a) { return a.assumption; }),
            }) +
              ((ex.evidence || []).length
                ? '<div class="ks-evidence-col ks-mt-3"><span class="ks-evidence-title">' + KS.t('Evidence') + '</span><ul>' +
                  ex.evidence
                    .map(function (e) {
                      return (
                        "<li>" + dom.esc(e.description || e.evidence_type) +
                        (e.data_reference ? '<br><span class="ks-evidence-ref">' + dom.esc(e.data_reference) + "</span>" : "") +
                        "</li>"
                      );
                    })
                    .join("") +
                  "</ul></div>"
                : "") +
              renderCaveats(ex)
          );
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    function feedback(recId, helpful) {
      api
        .post("/farms/" + id + "/recommendations/" + recId + "/feedback", {
          helpful: helpful,
          accurate: helpful,
          rating: helpful ? 5 : 2,
          comment: "",
        })
        .then(function () {
          ui.ok("Thanks — your feedback improves future suggestions.");
        })
        .catch(function (err) {
          ui.error(err.message);
        });
    }

    dom.on(document, "click", "[data-ks-helpful]", function () {
      feedback(this.dataset.ksHelpful, true);
    });
    dom.on(document, "click", "[data-ks-nothelpful]", function () {
      feedback(this.dataset.ksNothelpful, false);
    });

    function loadOpportunities() {
      var host = dom.qs("[data-ks-opportunities]");
      if (!host) return;
      ui.loading(host, "Loading cost-saving ideas…");
      api
        .get("/farms/" + id + "/opportunities")
        .then(function (rows) {
          var list = Array.isArray(rows) ? rows : rows.results || [];
          if (!list.length) {
            dom.set(host, "");
            return;
          }
          dom.set(
            host,
            '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Cost-saving opportunities') + '</h2></div>' +
              render.table(
                [
                  { label: "Opportunity", value: function (r) { return r.title; } },
                  { label: "Category", value: function (r) { return fmt.label(r.category); } },
                  { label: "Potential saving", numeric: true, value: function (r) { return fmt.inr(r.savings_min) + " – " + fmt.inr(r.savings_max); } },
                  { label: "Confidence", value: function (r) { return render.confBadge(r.confidence); }, html: true },
                ],
                list
              ) +
              "</div>"
          );
        })
        .catch(function () {
          dom.set(host, "");
        });
    }
  };

  /* =====================================================================
     PAGE: subsidies
     ===================================================================== */
  pages.subsidies = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-subsidies]");
    if (!host) return;
    ui.loading(host, "Checking scheme eligibility…");

    api
      .get("/farms/" + id + "/subsidies/recommendations")
      .then(function (matches) {
        var list = Array.isArray(matches) ? matches : matches.results || [];
        renderMatches(list);
        return loadChecklists(list);
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });

    dom.on(document, "click", "[data-ks-rematch]", "click", function () {
      var btn = this;
      var restore = ui.busy(btn, true, "Re-checking…");
      api
        .post("/farms/" + id + "/subsidies/match", {})
        .then(function () {
          restore();
          ui.ok("Eligibility re-checked.");
          window.location.reload();
        })
        .catch(function (err) {
          restore();
          ui.error(err.message);
        });
    });

    function renderMatches(list) {
      if (!list.length) {
        ui.empty(host, "No schemes matched yet", "Add your land, location and equipment details to improve matching.");
        return;
      }
      dom.set(
        host,
        '<div class="ks-alert ks-alert-warn ks-mb-4"><span aria-hidden="true">⚠</span><div>' +
          "<strong class='ks-alert-title'>" + KS.t("Preliminary matches only") + "</strong>" +
          "Eligibility shown here is a rule-based estimate from your farm data. Confirm every detail on the official government portal before applying." +
          "</div></div>" +
          '<div class="ks-grid ks-grid-2">' +
          list
            .map(function (m) {
              var scheme = m.scheme || {};
              var reasons = m.reasons_json || [];
              return (
                '<div class="ks-scheme" data-matched="' + (m.matched ? "true" : "false") + '">' +
                '<div class="ks-scheme-head">' +
                  "<h3>" + dom.esc(scheme.name) + "</h3>" +
                  (m.matched ? '<span class="ks-badge ks-badge-ok">' + KS.t('Likely eligible') + '</span>' : '<span class="ks-badge">' + KS.t('Review') + '</span>') +
                "</div>" +
                '<div class="ks-scheme-meta">' +
                  "<span>" + dom.esc(fmt.label(scheme.category)) + "</span>" +
                  (scheme.state ? "<span>· " + dom.esc(scheme.state) + "</span>" : "") +
                  (scheme.last_verified_at ? "<span>· verified " + dom.esc(fmt.date(scheme.last_verified_at)) + "</span>" : "") +
                "</div>" +
                (scheme.benefit_max_inr || scheme.benefit_min_inr
                  ? '<div class="ks-scheme-benefit"><span class="ks-tiny ks-muted">' + KS.t('Indicative benefit') + '</span><br>' +
                    '<span class="ks-money ks-money-md">' +
                    dom.esc(scheme.benefit_max_inr ? fmt.inr(scheme.benefit_min_inr) + " – " + fmt.inr(scheme.benefit_max_inr) : fmt.inr(scheme.benefit_min_inr)) +
                    "</span></div>"
                  : "") +
                (reasons.length
                  ? '<ul class="ks-scheme-reasons">' + reasons.map(function (r) { return "<li>" + dom.esc(r) + "</li>"; }).join("") + "</ul>"
                  : "") +
                (scheme.application_steps && scheme.application_steps.length
                  ? '<details class="ks-estimate-notes"><summary>How to apply (' + scheme.application_steps.length + " steps)</summary>" +
                    '<ol class="ks-note-list">' + scheme.application_steps.map(function (s) { return "<li>" + dom.esc(s) + "</li>"; }).join("") + "</ol></details>"
                  : "") +
                '<div class="ks-mt-3">' +
                  (scheme.official_url
                    ? '<a class="ks-btn ks-btn-sm" href="' + dom.esc(scheme.official_url) + '" target="_blank" rel="noopener noreferrer">' + KS.t('Open official portal') + '</a> '
                    : "") +
                  (scheme.id
                    ? '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-scheme-detail="' + dom.esc(scheme.id) + '">' + KS.t('Scheme details') + '</button> '
                    : "") +
                  '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-docs="' + dom.esc(m.id) + '">' + KS.t('Documents needed') + '</button>' +
                "</div>" +
                '<div data-ks-scheme-host="' + dom.esc(scheme.id || m.id) + '"></div>' +
                '<div data-ks-docs-host="' + dom.esc(m.id) + '"></div>' +
                "</div>"
              );
            })
            .join("") +
          "</div>"
      );

      dom.qsa("[data-ks-docs]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          toggleDocs(btn.dataset.ksDocs, btn);
        });
      });
      dom.qsa("[data-ks-scheme-detail]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          toggleSchemeDetail(btn.getAttribute("data-ks-scheme-detail"), btn);
        });
      });
    }

    /* Full scheme record from GET /subsidies/{id}: rules, documents, notes and
       verification metadata that the shortlist cards deliberately omit. */
    function schemeDetailHtml(s) {
      var rules = Array.isArray(s.rules) ? s.rules : [];
      var docs = Array.isArray(s.documents) ? s.documents : [];
      var steps = Array.isArray(s.application_steps) ? s.application_steps : [];

var meta = {};
      meta["Category"] = fmt.label(s.category);
      if (s.administrative_level) meta["Administrative level"] = fmt.label(s.administrative_level);
      if (s.state) meta["State"] = s.state;
      if (s.district) meta["District"] = s.district;
      if (s.benefit_type) meta["Benefit type"] = s.benefit_type;
      if (s.benefit_min_inr !== null && s.benefit_min_inr !== undefined) {
        meta["Indicative benefit"] = s.benefit_max_inr
          ? fmt.inr(s.benefit_min_inr) + " – " + fmt.inr(s.benefit_max_inr)
          : fmt.inr(s.benefit_min_inr);
      }
      if (s.effective_from) meta["Effective from"] = fmt.date(s.effective_from);
      if (s.effective_to) meta["Effective to"] = fmt.date(s.effective_to);
      if (s.last_verified_at) meta["Last verified"] = fmt.date(s.last_verified_at);
      if (s.scheme_version) meta["Scheme version"] = s.scheme_version;

      var blocks = [];
      blocks.push(render.datalist(meta));
      if (rules.length) {
        blocks.push(
          "<h4>" + KS.t("Rules") + "</h4><ul class=\"ks-note-list\">" +
            rules
              .map(function (r) { return "<li>" + dom.esc(typeof r === "string" ? r : r.rule || r.text || "") + "</li>"; })
              .join("") +
            "</ul>"
        );
      }
      if (docs.length) {
        blocks.push(
          "<h4>" + KS.t("Documents") + "</h4><ul class=\"ks-note-list\">" +
            docs
              .map(function (d) { return "<li>" + dom.esc(typeof d === "string" ? d : d.name || d.document || "") + "</li>"; })
              .join("") +
            "</ul>"
        );
      }
      if (steps.length) {
        blocks.push(
          "<h4>" + KS.t("How to apply") + "</h4><ol class=\"ks-note-list\">" +
            steps.map(function (s2) { return "<li>" + dom.esc(s2) + "</li>"; }).join("") +
            "</ol>"
        );
      }
      if (s.notes) {
        blocks.push(
          '<div class="ks-alert ks-alert-info ks-mt-3"><span aria-hidden="true">' + KS.t('i') + '</span><div>' +
            dom.esc(s.notes) + "</div></div>"
        );
      }
      if (s.is_illustrative) {
        blocks.push(
          '<p class="ks-tiny ks-muted ks-mt-3">' + KS.t('This record is illustrative reference data, not an official publication.') + '</p>'
        );
      }
      if (s.official_url) {
        blocks.push(
          '<div class="ks-mt-3"><a class="ks-btn ks-btn-sm" href="' + dom.esc(s.official_url) +
            '" target="_blank" rel="noopener noreferrer">' + KS.t('Open official portal') + '</a></div>'
        );
      }
      return '<div class="ks-scheme-detail">' + blocks.join("") + "</div>";
    }

    function toggleSchemeDetail(schemeId, btn) {
      var host = dom.qs('[data-ks-scheme-host="' + schemeId + '"]');
      if (!host) return;
      if (host.dataset.open === "true") {
        dom.set(host, "");
        host.dataset.open = "false";
        btn.textContent = "Scheme details";
        return;
      }
      host.dataset.open = "true";
      ui.loading(host, "Loading scheme details…");
      api
        .get("/subsidies/" + encodeURIComponent(schemeId))
        .then(function (scheme) {
          dom.set(host, schemeDetailHtml(scheme));
          btn.textContent = "Hide details";
        })
        .catch(function (err) {
          host.dataset.open = "false";
          ui.errorState(host, err);
        });
    }

    /* ------------------------------------------------- scheme catalogue
       GET /subsidies lists every scheme we hold, including ones that did not
       match this farm, so the farmer can still read the terms. */
    var catalogueHost = dom.qs("[data-ks-scheme-catalogue]");
    var catalogueRows = [];

    function schemeCard(s, matched) {
      return (
        '<div class="ks-scheme" data-matched="' + (matched ? "true" : "false") + '">' +
        '<div class="ks-scheme-head"><h3>' + dom.esc(s.name) + "</h3>" +
        (matched ? '<span class="ks-badge ks-badge-ok">' + KS.t('Matched') + '</span>' : '<span class="ks-badge">' + KS.t('Reference') + '</span>') +
        "</div>" +
        '<div class="ks-scheme-meta">' +
        "<span>" + dom.esc(fmt.label(s.category)) + "</span>" +
        (s.state ? "<span>· " + dom.esc(s.state) + "</span>" : "") +
        (s.administrative_level ? "<span>· " + dom.esc(fmt.label(s.administrative_level)) + "</span>" : "") +
        "</div>" +
        (s.benefit_type
          ? '<p class="ks-small ks-mt-3">' + dom.esc(s.benefit_type) + "</p>"
          : "") +
        '<div class="ks-mt-3">' +
        '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-scheme-detail="' + dom.esc(s.id) + '">' + KS.t('Details') + '</button>' +
        (s.official_url
          ? ' <a class="ks-btn ks-btn-sm" href="' + dom.esc(s.official_url) + '" target="_blank" rel="noopener noreferrer">' + KS.t('Official portal') + '</a>'
          : "") +
        "</div>" +
        '<div data-ks-scheme-host="' + dom.esc(s.id) + '"></div>' +
        "</div>"
      );
    }

    function bindSchemeDetail(root) {
      dom.qsa("[data-ks-scheme-detail]", root).forEach(function (btn) {
        btn.addEventListener("click", function () {
          toggleSchemeDetail(btn.getAttribute("data-ks-scheme-detail"), btn);
        });
      });
    }

    function renderCatalogue() {
      if (!catalogueHost) return;
      var q = (dom.qs("[data-ks-catalogue-filter]") || {}).value || "";
      var needle = q.trim().toLowerCase();
      var rows = catalogueRows.filter(function (s) {
        if (!needle) return true;
        return [s.name, s.category, s.state, s.district, s.benefit_type]
          .filter(Boolean)
          .some(function (v) { return String(v).toLowerCase().indexOf(needle) !== -1; });
      });
      if (!rows.length) {
        dom.set(
          catalogueHost,
          ui.emptyHtml(
            "No schemes match that filter",
            "Try a different keyword, or clear the filter to see all " + catalogueRows.length + " schemes."
          )
        );
        return;
      }
      dom.set(
        catalogueHost,
        '<p class="ks-muted ks-tiny ks-mb-3">' + rows.length + " of " + catalogueRows.length + " schemes</p>" +
        '<div class="ks-grid ks-grid-2">' +
        rows.map(function (s) { return schemeCard(s, false); }).join("") +
        "</div>"
      );
      bindSchemeDetail(catalogueHost);
    }

    function loadCatalogue() {
      if (!catalogueHost) return;
      ui.loading(catalogueHost, "Loading scheme catalogue…");
      api
        .get("/subsidies")
        .then(function (payload) {
          catalogueRows = Array.isArray(payload) ? payload : payload.results || [];
          renderCatalogue();
        })
        .catch(function (err) {
          ui.errorState(catalogueHost, err);
        });
    }

    var catalogueFilter = dom.qs("[data-ks-catalogue-filter]");
    if (catalogueFilter) {
      catalogueFilter.addEventListener("input", renderCatalogue);
    }
    loadCatalogue();

    function toggleDocs(matchId, btn) {
      var host = dom.qs('[data-ks-docs-host="' + matchId + '"]');
      if (!host) return;
      if (host.dataset.open === "true") {
        dom.set(host, "");
        host.dataset.open = "false";
        return;
      }
      host.dataset.open = "true";
      ui.loading(host, "Loading checklist…");
      api
        .get("/farms/" + id + "/subsidies/checklists")
        .then(function (payload) {
          var checklists = Array.isArray(payload) ? payload : payload.results || [];
          var items = [];
          checklists.forEach(function (c) {
            (c.items_json || []).forEach(function (item) {
              var name = typeof item === "string" ? item : item.name || item.document;
              var required = typeof item === "string" ? true : item.required !== false;
              items.push({ name: name, required: required });
            });
          });
          if (!items.length) {
            dom.set(host, '<p class="ks-muted ks-tiny ks-mt-3">' + KS.t('No document checklist recorded for this scheme yet.') + '</p>');
            return;
          }
          dom.set(
            host,
            '<ul class="ks-checklist ks-mt-3">' +
              items
                .map(function (i) {
                  return (
                    '<li><span class="ks-checklist-box" data-required="' + (i.required ? "true" : "false") + '"></span>' +
                    '<span class="ks-checklist-text">' + dom.esc(i.name) + "</span></li>"
                  );
                })
                .join("") +
              "</ul>"
          );
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    function loadChecklists() {
      // Checklists load lazily per scheme to keep the page light.
      return Promise.resolve();
    }
  };

  /* =====================================================================
     PAGE: solar comparison
     ===================================================================== */
  pages.solar = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-solar]");
    var inputsHost = dom.qs("[data-ks-solar-config]");
    if (!host) return;
    ui.loading(host, "Comparing solar, grid and diesel…");

    // The inputs card is re-rendered after every save, so its delegated
    // handlers are bound once and read their state from the DOM at click time.
    if (inputsHost && !inputsHost.getAttribute("data-ks-bound")) {
      inputsHost.setAttribute("data-ks-bound", "1");
      dom.on(inputsHost, "[data-ks-input-edit]", "click", function () {
        var panel = dom.qs("[data-ks-input-panel]", inputsHost);
        if (!panel) return;
        var open = panel.hasAttribute("hidden");
        if (open) {
          panel.removeAttribute("hidden");
        } else {
          panel.setAttribute("hidden", "hidden");
        }
        this.textContent = open ? "Hide pump details" : "Add or correct my pump details";
      });

      dom.on(inputsHost, "[data-ks-pump-form]", "submit", function (ev) {
        ev.preventDefault();
        savePump(ev.target);
      });

      dom.on(inputsHost, "[data-ks-solar-form]", "submit", function (ev) {
        ev.preventDefault();
        saveSolarConfig(ev.target);
      });

      dom.on(inputsHost, "[data-ks-run-analysis]", "click", function () {
        var restore = ui.busy(this, true, "Analysing…");
        api
          .post("/farms/" + id + "/energy/analyze", {})
          .then(function () {
            restore();
            ui.ok("Analysis saved to your farm.");
            load();
          })
          .catch(function (err) {
            restore();
            ui.error(err.message);
          });
      });
    }

    load();

    function load() {
      api
        .get("/farms/" + id + "/energy/solar-comparison")
        .then(function (payload) {
          loadInputs();
          render(payload);
        })
        .catch(function (err) {
          ui.errorState(host, err);
        });
    }

    // Prefill both forms from the GET endpoints added for this page. An empty
    // profile comes back as {} (the response envelope drops nulls), so check for
    // the id rather than testing the object itself.
    function loadInputs() {
      if (!inputsHost) return Promise.resolve();
      return Promise.all([
        api.get("/farms/" + id + "/pump-profile").catch(function () { return {}; }),
        api.get("/farms/" + id + "/solar-configuration").catch(function () { return {}; })
      ]).then(function (rows) {
        dom.set(inputsHost, inputsCard(rows[0], rows[1]));
      });
    }

    function savePump(form) {
      var restore = ui.busy(dom.qs('[type="submit"]', form), true, "Saving…");
      var d = forms.read(form);
      api
        .post("/farms/" + id + "/pump-profile", {
          pump_type: d.pump_type || "submersible",
          horsepower: d.horsepower === "" ? null : Number(d.horsepower),
          power_kw: d.power_kw === "" ? null : Number(d.power_kw),
          water_source: (d.water_source || "").trim(),
          operating_hours_per_day: d.operating_hours_per_day === "" ? null : Number(d.operating_hours_per_day),
          irrigation_days_per_year: d.irrigation_days_per_year === "" ? null : Number(d.irrigation_days_per_year),
          existing_annual_maintenance: d.existing_annual_maintenance === "" ? null : Number(d.existing_annual_maintenance)
        })
        .then(function () {
          restore();
          ui.ok("Pump details saved.");
          load();
        })
        .catch(function (err) {
          restore();
          forms.applyServerErrors(form, err);
          ui.error(err.message);
        });
    }

    function saveSolarConfig(form) {
      var restore = ui.busy(dom.qs('[type="submit"]', form), true, "Saving…");
      var d = forms.read(form);
      api
        .post("/farms/" + id + "/solar-configuration", {
          system_kw: d.system_kw === "" ? null : Number(d.system_kw),
          pump_hp: d.pump_hp === "" ? null : Number(d.pump_hp),
          pump_cost_inr: d.pump_cost_inr === "" ? null : Number(d.pump_cost_inr),
          installation_cost_inr: d.installation_cost_inr === "" ? null : Number(d.installation_cost_inr),
          panel_types: (d.panel_types || "").trim(),
          storage_kwh: d.storage_kwh === "" ? null : Number(d.storage_kwh),
          estimated_subsidy_inr: d.estimated_subsidy_inr === "" ? null : Number(d.estimated_subsidy_inr),
          loan_amount_inr: d.loan_amount_inr === "" ? null : Number(d.loan_amount_inr),
          loan_years: d.loan_years === "" ? null : Number(d.loan_years),
          loan_interest_rate_pct: d.loan_interest_rate_pct === "" ? 10 : Number(d.loan_interest_rate_pct),
          annual_maintenance_inr: d.annual_maintenance_inr === "" ? null : Number(d.annual_maintenance_inr)
        })
        .then(function () {
          restore();
          ui.ok("Solar configuration saved.");
          load();
        })
        .catch(function (err) {
          restore();
          forms.applyServerErrors(form, err);
          ui.error(err.message);
        });
    }

    function render(payload) {
      // The endpoint nests everything: {input_summary, comparison, recommendation}.
      // The previous code read a flat shape that no longer exists, so all three
      // columns rendered as dashes, the reason came out as "[object object]" and
      // the year timeline was always empty.
      var comparison = payload.comparison || {};
      var rec = payload.recommendation || {};
      var summary = payload.input_summary || {};
      var scenarios = comparison.scenarios || [];
      var expected = scenarios.filter(function (s) { return s.scenario === "expected"; })[0] || scenarios[0] || {};

      // Only compare the sources the farmer actually uses - the backend never
      // projects a reference it has no consumption for.
      var usesGrid = (parseFloat(summary.annual_kwh) || 0) > 0;
      var usesDiesel = (parseFloat(summary.litres_per_year) || 0) > 0;

      if (!usesGrid && !usesDiesel) {
        dom.set(
          host,
          '<div class="ks-alert ks-alert-warn ks-mb-4"><span aria-hidden="true">⚠</span><div>' +
            "<strong class='ks-alert-title'>" + KS.t("We have no energy usage for this farm yet") + "</strong>" +
            "This comparison works out how much electricity or diesel your pump burns, so it " +
            "cannot produce a break-even year from nothing. Add your pump type, running hours " +
            "and days irrigated above, and the comparison will update. " +
            "We would rather show you nothing than a number we cannot stand behind." +
            "</div></div>"
        );
        return;
      }

      var grid = parseFloat(expected.grid_cumulative_10y) || 0;
      var diesel = parseFloat(expected.diesel_cumulative_10y) || 0;
      var solar = parseFloat(expected.solar_cumulative_10y) || 0;
      var upfront = parseFloat(comparison.upfront_cost_inr) || 0;
      var breakEven = comparison.break_even_year;

      var options = [];
      if (usesGrid) options.push({ k: "grid", v: grid });
      if (usesDiesel) options.push({ k: "diesel", v: diesel });
      options.push({ k: "solar", v: solar });
      var cheapest = options.reduce(function (best, o) { return !best || o.v < best.v ? o : best; }, null);

      dom.set(
        host,
        '<div class="ks-grid ks-grid-3 ks-mb-4">' +
          (usesGrid ? col("Grid (electricity)", grid, cheapest && cheapest.k === "grid") : "") +
          (usesDiesel ? col("Diesel pump", diesel, cheapest && cheapest.k === "diesel") : "") +
          col("Solar", solar, cheapest && cheapest.k === "solar") +
        "</div>" +

        (upfront
          ? '<div class="ks-alert ks-alert-info ks-mb-4"><span aria-hidden="true">☀</span><div>' +
            "<strong class='ks-alert-title'>Upfront " + dom.esc(fmt.inr(upfront)) + "</strong>" +
            "System cost plus installation, minus the subsidy you entered. The totals above add " +
            "running and maintenance on top of that. Prices are illustrative - get a written quote." +
            "</div></div>"
          : "") +

        (breakEven
          ? '<div class="ks-alert ks-alert-ok ks-mb-4"><span aria-hidden="true">☀</span><div>' +
            "<strong class='ks-alert-title'>Break-even in year " + dom.esc(breakEven) + "</strong>" +
            dom.esc(rec.reason || KS.t("Solar cumulative cost falls below what you spend today within the modelled horizon.")) +
            "</div></div>"
          : '<div class="ks-alert ks-alert-warn ks-mb-4"><span aria-hidden="true">⚠</span><div>' +
            "<strong class='ks-alert-title'>" + KS.t("No break-even within 10 years") + "</strong>" +
            dom.esc(rec.reason || KS.t("Solar cumulative cost does not fall below grid or diesel within the modelled years.")) +
            " We do not publish a break-even year when the data does not support one." +
            "</div></div>") +

        renderCaveats({
          warnings: rec.warnings || [],
          limitations: comparison.limitations || []
        }) +
        renderNarrative({
          reasons: [rec.reason].filter(Boolean),
          assumptions: comparison.assumptions || []
        })
      );
    }

    // Every column is a 10-year total now: the backend returns cumulative
    // costs, not annual ones, so labelling these "annual" would understate them.
    function col(name, value, recommended) {
      return (
        '<div class="ks-compare-col" data-recommended="' + (recommended ? "true" : "false") + '">' +
        '<div class="ks-compare-name">' + dom.esc(name) + "</div>" +
        '<div class="ks-compare-value">' + (isNil(value) ? "—" : dom.esc(fmt.inrShort(value))) + "</div>" +
        '<div class="ks-compare-meta">' + KS.t('10-year total cost') + '</div>' +
        (recommended ? '<span class="ks-compare-flag">' + KS.t('✓ Cheapest on these inputs') + '</span>' : "") +
        "</div>"
      );
    }

    // The inputs the analytics read. Rendered from the GET endpoints so the
    // farmer can see (and correct) exactly what is driving the comparison.
    function inputsCard(pump, solar) {
      var hasPump = !!(pump && pump.id);
      var hasSolar = !!(solar && solar.id);

      return (
        '<div class="ks-card ks-mb-4"><div class="ks-card-head">' +
          "<h2 class='ks-card-title'>" + KS.t("What this comparison is built on") + "</h2>" +
          '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-input-edit>' + KS.t('Add or correct my pump details') + '</button>' +
          "</div>" +

          '<div class="ks-stack ks-mb-4">' +
            (hasPump
              ? render.datalist(
                  {
                    "Pump type": pump.pump_type,
                    Horsepower: pump.horsepower,
                    "Power (kW)": pump.power_kw,
                    "Water source": pump.water_source,
                    "Hours/day": pump.operating_hours_per_day,
                    "Irrigation days/year": pump.irrigation_days_per_year,
                    "Annual maintenance": pump.existing_annual_maintenance ? fmt.inr(pump.existing_annual_maintenance) : null
                  },
                  { columns: 2 }
                )
              : '<p class="ks-muted ks-small">' + KS.t('No pump profile saved. Without it we cannot work out your electricity or diesel use, so the comparison below stays empty.') + '</p>') +
            (hasSolar
              ? render.datalist(
                  {
                    "System size (kW)": solar.system_kw,
                    "Pump cost": solar.pump_cost_inr ? fmt.inr(solar.pump_cost_inr) : null,
                    "Installation cost": solar.installation_cost_inr ? fmt.inr(solar.installation_cost_inr) : null,
                    "Total upfront": solar.total_upfront ? fmt.inr(solar.total_upfront) : null,
                    Panels: solar.panel_types,
                    "Storage (kWh)": solar.storage_kwh,
                    "Subsidy entered": solar.estimated_subsidy_inr ? fmt.inr(solar.estimated_subsidy_inr) : null
                  },
                  { columns: 2 }
                )
              : '<p class="ks-muted ks-small">' + KS.t('No solar configuration saved, so the upfront cost uses a placeholder price. Add yours for a real number.') + '</p>') +
          "</div>" +

          '<div class="ks-form-actions ks-mb-4">' +
            '<button class="ks-btn" data-ks-run-analysis>' + KS.t('Run and save this analysis') + '</button>' +
          "</div>" +

          '<div data-ks-input-panel hidden>' +
            pumpForm(pump, hasPump) +
            solarForm(solar, hasSolar) +
          "</div>" +
        "</div>"
      );
    }

    function pumpForm(pump, hasPump) {
      pump = pump || {};
      return (
        '<form class="ks-form ks-mb-4" data-ks-pump-form novalidate>' +
          '<h3 class="ks-card-title">' + (hasPump ? "Correct your pump details" : "Add your pump details") + "</h3>" +
          '<div data-ks-error-summary></div>' +
          '<div class="ks-grid ks-grid-2">' +
            select("Pump type", "pump_type", ["submersible", "centrifugal", "diesel", "solar", "other"], pump.pump_type || "submersible") +
            field("Horsepower", "horsepower", pump.horsepower, 'type="number" step="0.1" min="0" inputmode="decimal"') +
            field("Power in kW", "power_kw", pump.power_kw, 'type="number" step="0.001" min="0" inputmode="decimal"') +
            field("Water source", "water_source", pump.water_source, 'maxlength="40"') +
            field("Hours run per day", "operating_hours_per_day", pump.operating_hours_per_day, 'type="number" step="0.1" min="0" inputmode="decimal"') +
            field("Irrigation days per year", "irrigation_days_per_year", pump.irrigation_days_per_year, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Annual maintenance (Rs)", "existing_annual_maintenance", pump.existing_annual_maintenance, 'type="number" step="1" min="0" inputmode="numeric"') +
          "</div>" +
          '<p class="ks-muted ks-tiny">' + KS.t('Leave a field blank if you do not know it. Only hours and days drive the energy estimate.') + '</p>' +
          '<div class="ks-form-actions"><button class="ks-btn" type="submit">' + KS.t('Save pump details') + '</button></div>' +
        "</form>"
      );
    }

    function solarForm(solar, hasSolar) {
      solar = solar || {};
      return (
        '<form class="ks-form" data-ks-solar-form novalidate>' +
          '<h3 class="ks-card-title">' + (hasSolar ? "Correct your solar configuration" : "Add a solar configuration") + "</h3>" +
          '<div data-ks-error-summary></div>' +
          '<div class="ks-grid ks-grid-2">' +
            field("System size (kW)", "system_kw", solar.system_kw, 'type="number" step="0.01" min="0" inputmode="decimal"') +
            field("Pump HP", "pump_hp", solar.pump_hp, 'type="number" step="0.1" min="0" inputmode="decimal"') +
            field("Pump cost (Rs)", "pump_cost_inr", solar.pump_cost_inr, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Installation cost (Rs)", "installation_cost_inr", solar.installation_cost_inr, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Panel types", "panel_types", solar.panel_types, 'maxlength="60"') +
            field("Storage (kWh)", "storage_kwh", solar.storage_kwh, 'type="number" step="0.01" min="0" inputmode="decimal"') +
            field("Subsidy you expect (Rs)", "estimated_subsidy_inr", solar.estimated_subsidy_inr, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Annual maintenance (Rs)", "annual_maintenance_inr", solar.annual_maintenance_inr, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Loan amount (Rs)", "loan_amount_inr", solar.loan_amount_inr, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Loan tenure (years)", "loan_years", solar.loan_years, 'type="number" step="1" min="0" inputmode="numeric"') +
            field("Loan interest (% p.a.)", "loan_interest_rate_pct", solar.loan_interest_rate_pct, 'type="number" step="0.01" min="0" inputmode="decimal"') +
          "</div>" +
          '<p class="ks-muted ks-tiny">' + KS.t('Subsidy is your own expectation, not a verified figure. Check it with the state department.') + '</p>' +
          '<div class="ks-form-actions"><button class="ks-btn" type="submit">' + KS.t('Save solar configuration') + '</button></div>' +
        "</form>"
      );
    }

    loadRateSources();
  };

  /**
   * "Where these rates come from" disclosure.
   *
   * Both benchmark endpoints filter is_verified=True and the seeder ships
   * everything unverified, so an empty result is expected on a fresh install.
   * The panel is hidden until a response arrives so it never shows as a
   * permanently broken box, and it says plainly when nothing is published
   * rather than implying the comparison used no rates at all.
   */
  function loadRateSources() {
    var host = dom.qs("[data-ks-rates]");
    var body = dom.qs("[data-ks-rates-body]");
    if (!host || !body) return;

    var stateEl = dom.qs("[data-ks-farm-state]");
    var state = stateEl ? stateEl.getAttribute("data-ks-farm-state") : null;

    Promise.all([
      // Tariffs are state-scoped.
      api.get("/energy/tariff-benchmarks", state ? { state: state } : null, { skipErrors: true }).catch(function () { return []; }),
      // Diesel benchmarks are national; the view takes no filters.
      api.get("/energy/diesel-price-benchmarks", null, { skipErrors: true }).catch(function () { return []; }),
      api.get("/system/data-source-status", null, { skipErrors: true }).catch(function () { return null; })
    ]).then(function (out) {
      var tariffs = asRows(out[0]);
      var diesel = asRows(out[1]);
      var status = out[2] || null;

      var parts = [];

      if (tariffs.length) {
        parts.push(
          "<h3 class=\"ks-card-title ks-mt-4\">" + KS.t("Electricity tariffs") + "</h3>" +
            tariffTable(tariffs)
        );
      }
      if (diesel.length) {
        parts.push(
          "<h3 class=\"ks-card-title ks-mt-4\">" + KS.t("Diesel prices") + "</h3>" +
            '<div class="ks-table-wrap"><table class="ks-table"><thead><tr>' +
            "<th>" + KS.t("Region") + "</th><th>" + KS.t("Price (Rs/litre)") + "</th><th>" + KS.t("Observed") + "</th>" +
            "</tr></thead><tbody>" +
            diesel
              .map(function (d) {
                return (
                  "<tr><td>" + dom.esc((d.state || KS.t("All India")) + (d.district ? " · " + d.district : "")) + "</td>" +
                  "<td>" + dom.esc(fmt.inrExact(d.price_per_litre)) + "</td>" +
                  "<td>" + dom.esc(d.observed_on) + "</td></tr>"
                );
              })
              .join("") +
            "</tbody></table></div>"
        );
      }

      if (!tariffs.length && !diesel.length) {
        parts.push(
          '<div class="ks-alert ks-alert-info"><span aria-hidden="true">&#9432;</span><div>' +
            "No verified tariff or diesel benchmarks are published on this server, so " +
            "this comparison is using built-in reference rates rather than current " +
            "official ones. Treat the payback period as indicative and confirm rates " +
            "with your DISCOM or fuel dealer." +
            "</div></div>"
        );
      }

      if (status && status.sources_total !== undefined) {
        var byStatus = status.by_approval_status || {};
        parts.push(
          render.datalist(
            {
              "Registered data sources": status.sources_total,
              Approved: byStatus.approved || 0,
              "Awaiting approval": byStatus.pending || 0,
              "Needs manual review": byStatus.manual_review || 0,
              Blocked: byStatus.blocked || 0,
              Rejected: byStatus.rejected || 0
            },
            { columns: 2 }
          )
        );
      }

      dom.set(body, parts.join(""));
      host.removeAttribute("hidden");
    });
  }

  function asRows(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.results)) return payload.results;
    return [];
  }

  function tariffTable(rows) {
    return (
      '<div class="ks-table-wrap"><table class="ks-table"><thead><tr>' +
      "<th>" + KS.t("State") + "</th><th>" + KS.t("Provider") + "</th><th>" + KS.t("Slab") + "</th><th>" + KS.t("Rs per kWh") + "</th>" +
      "</tr></thead><tbody>" +
      rows
        .map(function (t) {
          return (
            "<tr><td>" + dom.esc(t.state) + "</td>" +
            "<td>" + dom.esc(t.provider || KS.t("not recorded")) + "</td>" +
            "<td>" + dom.esc(t.slab_name || KS.t("not recorded")) + "</td>" +
            "<td>" + dom.esc(fmt.inrExact(t.per_kwh_inr)) + "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div>"
    );
  }

  /* =====================================================================
     PAGE: finance / machinery decisions
     ===================================================================== */
  pages.finance = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-finance]");
    if (!host) return;
    dom.set(host, ui.skeleton(3, true));

    api
      .get("/farms/" + id + "/finance/scenarios")
      .then(function (rows) {
        var list = Array.isArray(rows) ? rows : rows.results || [];
        if (!list.length) {
          dom.set(
            host,
            '<div class="ks-empty"><span class="ks-empty-icon" aria-hidden="true">🧮</span>' +
              '<span class="ks-empty-title">' + KS.t('No decisions analysed yet') + '</span>' +
              "<p>" + KS.t("Use the calculators below to compare buying, renting, repairing and replacing.") + "</p></div>"
          );
          return;
        }
        dom.set(
          host,
          render.table(
            [
              { label: "Suggested option", value: function (r) { return fmt.label(r.option); } },
              { label: "Purchase price", numeric: true, value: function (r) { return fmt.inr(r.purchase_price_inr); } },
              { label: "Est. subsidy", numeric: true, value: function (r) { return fmt.inr(r.estimated_subsidy_inr); } },
              { label: "Computed", value: function (r) { return fmt.dateTime(r.created_at); } },
            ],
            list,
            { caption: "Past decisions (most recent 20)" }
          )
        );
      })
      .catch(function (err) {
        dom.set(host, ui.skeleton(1, true));
        ui.errorState(host, err);
      });

    // The four calculators. The template names each one after its endpoint;
    // `key` is the short form the renderer below is written against. The old
    // handler read data-ks-calc off a <div> and then looked up "#form-<kind>"
    // and "[data-ks-out-<kind>]", neither of which existed in the template, so
    // every calculator returned early and did nothing at all.
    var CALCS = {
      "buy-vs-rent": { key: "buy-rent", path: "/finance/buy-vs-rent" },
      "repair-vs-replace": { key: "repair-replace", path: "/finance/repair-vs-replace" },
      "affordability": { key: "affordability", path: "/finance/affordability" },
      "machinery-decision": { key: "machinery", path: "/finance/machinery-decision" }
    };

    dom.on(document, "form[data-ks-calc-form]", "submit", function (ev) {
      ev.preventDefault();
      var cfg = CALCS[this.dataset.ksCalcForm];
      if (!cfg) return;
      var form = this;
      var out = dom.qs("[data-ks-out-" + cfg.key + "]");
      if (!out) return;
      if (!forms.validate(form)) return;

      var data = forms.read(form);
      var restore = ui.busy(dom.qs('[type="submit"]', form), true, "Calculating…");
      api
        .post("/farms/" + id + cfg.path, data)
        .then(function (result) {
          restore();
          renderResult(cfg.key, out, result);
        })
        .catch(function (err) {
          restore();
          ui.error(err.message);
        });
    });

    /* ---------------------------------------------------------------------
       Income profile
       ---------------------------------------------------------------------
       The affordability and machinery calculators take an annual income, and
       the backend substituted Rs 300,000 when none was sent - so the farmer
       saw a confident percentage for a number they never gave us. Record the
       real figure once and pre-fill both calculators from it.
       --------------------------------------------------------------------- */

    var incomeHost = dom.qs("[data-ks-income-profile]");
    if (incomeHost && !incomeHost.getAttribute("data-ks-bound")) {
      incomeHost.setAttribute("data-ks-bound", "1");

      dom.on(incomeHost, "[data-ks-income-edit]", "click", function () {
        var panel = dom.qs("[data-ks-income-panel]", incomeHost);
        if (!panel) return;
        var open = panel.hasAttribute("hidden");
        if (open) {
          panel.removeAttribute("hidden");
        } else {
          panel.setAttribute("hidden", "hidden");
        }
        this.textContent = open ? "Hide income details" : "Add or correct my income";
      });

      dom.on(incomeHost, "[data-ks-income-form]", "submit", function (ev) {
        ev.preventDefault();
        if (!forms.validate(ev.target)) return;
        saveIncome(ev.target);
      });
    }
    loadIncome();

    function loadIncome() {
      if (!incomeHost) return;
      api
        .get("/farms/" + id + "/income-profile")
        .then(function (row) {
          var data = row || {};
          if (data.id) prefillIncome(data);
          dom.set(incomeHost, incomeCard(data));
        })
        .catch(function () {
          dom.set(incomeHost, incomeCard({}));
        });
    }

    function saveIncome(form) {
      var restore = ui.busy(dom.qs('[type="submit"]', form), true, "Saving…");
      var d = forms.read(form);
      api
        .post("/farms/" + id + "/income-profile", {
          year: d.year,
          crop_income: d.crop_income,
          livestock_income: d.livestock_income,
          off_farm_income: d.off_farm_income,
          other_income: d.other_income,
          existing_emi_total: d.existing_emi_total
        })
        .then(function () {
          restore();
          ui.ok("Income saved.");
          loadIncome();
        })
        .catch(function (err) {
          restore();
          forms.applyServerErrors(form, err);
          ui.error(err.message);
        });
    }

    // Only fill blanks: a farmer who typed their own figure keeps it, and
    // re-saving income must not stomp the field they are editing.
    function setIfBlank(formId, name, value) {
      if (value === null || value === undefined || value === "") return;
      var input = dom.qs('#' + formId + ' [name="' + name + '"]');
      if (input && String(input.value).trim() === "") input.value = value;
    }

    function prefillIncome(row) {
      setIfBlank("form-affordability", "annual_income_inr", row.total_income);
      setIfBlank("form-affordability", "existing_emi_total_inr", row.existing_emi_total || 0);
      setIfBlank("form-machinery", "annual_income", row.total_income);
      setIfBlank("form-machinery", "existing_emi", row.existing_emi_total || 0);
    }

    function incomeCard(row) {
      var has = !!(row && row.id);
      return (
        '<div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Your recorded income') + '</h2>' +
        '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-income-edit>' + KS.t('Add or correct my income') + '</button></div>' +
        (has
          ? render.datalist(
              {
                Year: row.year,
                "Crop income": row.crop_income ? fmt.inr(row.crop_income) : null,
                "Livestock income": row.livestock_income ? fmt.inr(row.livestock_income) : null,
                "Off-farm income": row.off_farm_income ? fmt.inr(row.off_farm_income) : null,
                "Other income": row.other_income ? fmt.inr(row.other_income) : null,
                "Total income": fmt.inr(row.total_income),
                "Existing EMI per month": row.existing_emi_total ? fmt.inr(row.existing_emi_total) : null
              },
              { columns: 2 }
            )
          : '<p class="ks-muted ks-small">No income recorded yet. Until you enter it, ' +
            '"What can I afford" and "Shared machinery" fall back to a placeholder of Rs 300,000 a year, ' +
            "so their percentages are not about your farm. Nothing else on this page is affected.</p>") +
        '<div data-ks-income-panel hidden>' + incomeForm(row) + "</div>"
      );
    }

    function incomeForm(row) {
      row = row || {};
      var year = row.year || new Date().getFullYear();
      return (
        '<form class="ks-form" data-ks-income-form novalidate>' +
          '<div data-ks-error-summary></div>' +
          '<div class="ks-grid ks-grid-2">' +
            field("Year", "year", year, 'type="number" step="1" min="1900" inputmode="numeric" required', "inc-") +
            field("Crop income (Rs)", "crop_income", row.crop_income, 'type="number" step="1" min="0" inputmode="numeric"', "inc-") +
            field("Livestock income (Rs)", "livestock_income", row.livestock_income, 'type="number" step="1" min="0" inputmode="numeric"', "inc-") +
            field("Off-farm income (Rs)", "off_farm_income", row.off_farm_income, 'type="number" step="1" min="0" inputmode="numeric"', "inc-") +
            field("Other income (Rs)", "other_income", row.other_income, 'type="number" step="1" min="0" inputmode="numeric"', "inc-") +
            field("Existing EMI per month (Rs)", "existing_emi_total", row.existing_emi_total, 'type="number" step="1" min="0" inputmode="numeric"', "inc-") +
          "</div>" +
          '<p class="ks-muted ks-tiny">' + KS.t('Blank fields count as zero. Use your best estimate for the year - rough figures are fine.') + '</p>' +
          '<div class="ks-form-actions"><button class="ks-btn" type="submit">' + KS.t('Save income') + '</button></div>' +
        "</form>"
      );
    }

    function renderResult(kind, out, r) {
      var html = "";

      if (kind === "buy-rent") {
        var suggested = String(r.suggested_option || "");
        html =
          '<div class="ks-compare ks-compare--2 ks-mb-4">' +
            '<div class="ks-compare-col" data-recommended="' + (suggested === "buy" ? "true" : "false") + '">' +
            '<div class="ks-compare-name">' + KS.t('Buy') + '</div>' +
            '<div class="ks-compare-value">' + dom.esc(fmt.inrShort(r.buy && r.buy.annual_total)) + "</div>" +
            '<div class="ks-compare-meta">Net price ' + dom.esc(fmt.inrShort(r.net_purchase_price)) +
            " · " + dom.esc(fmt.inr(r.buy && r.buy.cost_per_hour)) + "/hour</div></div>" +
            '<div class="ks-compare-col" data-recommended="' + (suggested === "rent" ? "true" : "false") + '">' +
            '<div class="ks-compare-name">' + KS.t('Rent') + '</div>' +
            '<div class="ks-compare-value">' + dom.esc(fmt.inrShort(r.rent_annual)) + "</div>" +
            '<div class="ks-compare-meta">' + KS.t('Per year') + '</div></div>' +
          "</div>" +
          estimate.block(
            estimate.fromTriple(
              "Utilisation score",
              r.utilization_score,
              null,
              null,
              r.data_confidence,
              { formatter: fmt.number }
            )
          );
      } else if (kind === "repair-replace") {
        var choice = String(r.suggested_option || "");
        html =
          '<div class="ks-compare ks-compare--2 ks-mb-4">' +
            '<div class="ks-compare-col" data-recommended="' + (choice === "repair_existing" ? "true" : "false") + '">' +
            '<div class="ks-compare-name">' + KS.t('Repair existing') + '</div>' +
            '<div class="ks-compare-value">' + dom.esc(fmt.inrShort(r.expected_annual_repair)) + "</div>" +
            '<div class="ks-compare-meta">' + KS.t('Per year') + '</div></div>' +
            '<div class="ks-compare-col" data-recommended="' + (choice === "replace" ? "true" : "false") + '">' +
            '<div class="ks-compare-name">' + KS.t('Replace') + '</div>' +
            '<div class="ks-compare-value">' + dom.esc(fmt.inrShort(r.replacement_annual_cost_equivalent)) + "</div>" +
            '<div class="ks-compare-meta">' + KS.t('Annual cost equivalent') + '</div></div>' +
          "</div>" +
          '<div class="ks-datalist ks-mb-4">' +
            "<div><dt>" + KS.t("Remaining life estimate") + "</dt><dd>" + dom.esc(fmt.number(r.remaining_life_years_estimate, 1)) + " years</dd></div>" +
            "<div><dt>" + KS.t("Financial risk") + "</dt><dd>" + dom.esc(fmt.label(r.financial_risk_level)) + "</dd></div>" +
          "</div>";
      } else if (kind === "affordability") {
        html =
          estimate.block(
            estimate.fromTriple(
              "Income burden",
              r.income_burden_pct,
              null,
              r.safe_burden_pct,
              r.data_confidence,
              {
                // A percentage, not rupees: the block defaults to fmt.inr.
                formatter: fmt.percent,
                assumptions: r.assumptions || [],
                limitations: r.limitations || [],
                requiresConfirmation: r.requires_farmer_confirmation,
                requiresVerification: false,
              }
            )
          ) +
          '<div class="ks-datalist ks-mt-4">' +
            "<div><dt>" + KS.t("Safe burden limit") + "</dt><dd>" + dom.esc(fmt.percent(r.safe_burden_pct)) + " of income</dd></div>" +
            "<div><dt>" + KS.t("Assessment") + "</dt><dd>" + (r.affordable ? "Within limit" : "Above limit") + "</dd></div>" +
            "<div><dt>" + KS.t("Financial risk") + "</dt><dd>" + dom.esc(fmt.label(r.financial_risk_level)) + "</dd></div>" +
          "</div>";
      } else {
        html =
          '<div class="ks-result-head"><span aria-hidden="true">🧭</span>' + KS.t('Suggested:') + '<strong>' +
          dom.esc(fmt.label(r.suggested_option)) + "</strong>" + riskBadge(r.financial_risk_level) + "</div>" +
          (r.alternatives
            ? '<div class="ks-datalist ks-mb-4"><div><dt>' + KS.t('Alternatives considered') + '</dt><dd>' +
              dom.esc(r.alternatives.map(fmt.label).join(", ")) + "</dd></div></div>"
            : "") +
          (r.key_calculations ? render.datalist({
            "Utilisation score": fmt.number(r.key_calculations.utilization_score),
            "Income burden": r.key_calculations.income_burden_pct === null
              ? "Not assessed"
              : fmt.percent(r.key_calculations.income_burden_pct),
            "Repair-to-residual ratio": fmt.number(r.key_calculations.repair_to_residual_ratio, 3),
          }, { columns: 2 }) : "");
      }

      dom.set(
        out,
        '<div class="ks-result">' + html + renderNarrative(r) + renderCaveats(r) + "</div>"
      );
      out.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  };

  /* =====================================================================
     PAGE: equipment list + detail
     ===================================================================== */
  pages.equipment = function () {
    var id = requireFarmId();
    if (!id) return;

    var host = dom.qs("[data-ks-equipment]");
    if (!host) return;
    ui.loading(host, "Loading equipment…");

    api
      .equipment(id)
      .then(function (rows) {
        var list = Array.isArray(rows) ? rows : rows.results || [];
        if (!list.length) {
          ui.empty(
            host,
            "No equipment recorded",
            "Add your tractor, pump or implements to get operating-cost estimates and brand identification.",
            '<a class="ks-btn" href="/farms/' + encodeURIComponent(id) + '/equipment/new/">' + KS.t('Add equipment') + '</a>'
          );
          return;
        }
        dom.set(
          host,
          '<div class="ks-grid ks-grid-3">' +
            list
              .map(function (e) {
                return (
                  '<div class="ks-equip-card">' +
                  '<a href="/farms/' + encodeURIComponent(id) + "/equipment/" + encodeURIComponent(e.id) + '/">' +
                  '<div class="ks-equip-thumb ks-equip-thumb--placeholder" aria-hidden="true">🚜</div></a>' +
                  '<div class="ks-equip-body">' +
                    "<h3>" + dom.esc(e.display_name) + "</h3>" +
                    '<dl class="ks-equip-specs">' +
                      (e.horsepower ? "<div><dt>" + KS.t("HP") + "</dt><dd>" + dom.esc(e.horsepower) + "</dd></div>" : "") +
                      (e.purchase_year ? "<div><dt>" + KS.t("Year") + "</dt><dd>" + dom.esc(e.purchase_year) + "</dd></div>" : "") +
                      (e.age_years !== null && e.age_years !== undefined ? "<div><dt>" + KS.t("Age") + "</dt><dd>" + dom.esc(fmt.number(e.age_years, 1)) + " yr</dd></div>" : "") +
                      (e.condition ? "<div><dt>" + KS.t("Condition") + "</dt><dd>" + dom.esc(fmt.label(e.condition)) + "</dd></div>" : "") +
                    "</dl>" +
                    '<div class="ks-equip-foot">' +
                      '<span class="ks-badge">' + dom.esc(fmt.label(e.fuel_type || "—")) + "</span>" +
                      (e.is_operational ? '<span class="ks-badge ks-badge-ok">' + KS.t('Working') + '</span>' : '<span class="ks-badge ks-badge-warn">' + KS.t('Idle') + '</span>') +
                    "</div>" +
                  "</div></div>"
                );
              })
              .join("") +
          "</div>"
        );
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });
  };

  pages.equipmentDetail = function () {
    var id = requireFarmId();
    var equipId = dom.cfg("equipId", null);
    if (!id || !equipId) return;

    var host = dom.qs("[data-ks-equip-detail]");
    if (!host) return;
    ui.loading(host, "Loading equipment…");

    // Latest server state, so the inline editor re-opens with fresh values after
    // a save re-renders this page.
    var current = null;

    api
      .get("/farms/" + id + "/equipment/" + equipId)
      .then(function (e) {
        current = e;
        dom.set(
          host,
          '<div class="ks-page-head"><h1>' + dom.esc(e.display_name) + "</h1>" +
          '<p class="ks-lede">' + dom.esc(fmt.label(e.fuel_type || KS.t("unknown fuel")) + " · " + fmt.label(e.condition || KS.t("condition not recorded"))) + "</p></div>" +
          '<div class="ks-grid ks-grid-2 ks-mb-4">' +
            '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Details') + '</h2>' +
            '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-edit-equip>' + KS.t('Correct these') + '</button></div>' +
            '<div data-ks-equip-fields>' +
            render.datalist({
              "Horsepower": e.horsepower,
              "Purchase year": e.purchase_year,
              "Age (years)": e.age_years,
              "Purchase price": e.purchase_price ? fmt.inr(e.purchase_price) : null,
              "Usage hours/year": e.usage_hours_per_year,
              "Area served": e.area_served_acres ? fmt.acres(e.area_served_acres) : null,
              "Operational": e.is_operational,
              "Notes": e.notes,
            }, { columns: 2 }) +
            "</div></div>" +
            '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Actions') + '</h2></div>' +
            '<div class="ks-stack">' +
              '<a class="ks-btn" href="/farms/' + encodeURIComponent(id) + "/equipment/" + encodeURIComponent(equipId) + '/upload/">' + KS.t('📷 Upload a photo to identify the brand') + '</a>' +
              '<button class="ks-btn ks-btn-secondary" data-ks-opcost>' + KS.t('Estimate operating cost') + '</button>' +
              '<button class="ks-btn ks-btn-danger" data-ks-delete-equip>' + KS.t('Remove equipment') + '</button>' +
            "</div></div>" +
          "</div>" +
          '<div data-ks-opcost-out></div>'
        );

        // This page re-renders itself after a save, so delegated handlers must
        // bind exactly once. Re-binding stacked a fresh listener per save,
        // making one click fire several operating-cost requests / delete
        // confirmations. `openEditor` reads `current`, not the stale `e`.
        if (!host.getAttribute("data-ks-equip-bound")) {
          host.setAttribute("data-ks-equip-bound", "1");

          // Brand/model correction. This is the durable answer to a wrong photo
          // identification, so it has to be reachable from the photo page's
          // "update the equipment record" instruction.
          dom.on(host, "[data-ks-edit-equip]", "click", function () {
            var e = current;
            var mount = dom.qs("[data-ks-equip-fields]", host);
            if (!mount) return;

            dom.set(
              mount,
              '<form class="ks-form" data-ks-equip-edit novalidate>' +
              '<div data-ks-error-summary></div>' +
              '<div class="ks-grid ks-grid-2">' +
                '<div class="ks-field"><label class="ks-label" for="ee-brand">' + KS.t('Brand') + '</label>' +
                '<input class="ks-input" type="text" id="ee-brand" name="custom_brand" maxlength="80" value="' +
                dom.esc(e.custom_brand || "") + '"></div>' +
                '<div class="ks-field"><label class="ks-label" for="ee-model">' + KS.t('Model') + '</label>' +
                '<input class="ks-input" type="text" id="ee-model" name="custom_model" maxlength="120" value="' +
                dom.esc(e.custom_model || "") + '"></div>' +
                '<div class="ks-field"><label class="ks-label" for="ee-hp">' + KS.t('Horsepower') + '</label>' +
                '<input class="ks-input" type="number" id="ee-hp" name="horsepower" step="0.1" min="0" inputmode="decimal" value="' +
                dom.esc(e.horsepower == null ? "" : e.horsepower) + '"></div>' +
                '<div class="ks-field"><label class="ks-label" for="ee-year">' + KS.t('Purchase year') + '</label>' +
                '<input class="ks-input" type="number" id="ee-year" name="purchase_year" step="1" min="1950" inputmode="numeric" value="' +
                dom.esc(e.purchase_year == null ? "" : e.purchase_year) + '"></div>' +
                '<div class="ks-field"><label class="ks-label" for="ee-cond">' + KS.t('Condition') + '</label>' +
                '<select class="ks-select" id="ee-cond" name="condition">' +
                  ["unknown", "good", "moderate", "poor"]
                    .map(function (c) {
                      return '<option value="' + c + '"' +
                        (e.condition === c ? " selected" : "") + ">" + fmt.label(c) + "</option>";
                    })
                    .join("") +
                "</select></div>" +
                '<div class="ks-field"><label class="ks-label" for="ee-fuel">' + KS.t('Fuel type') + '</label>' +
                '<select class="ks-select" id="ee-fuel" name="fuel_type">' +
                  ["diesel", "petrol", "electric", "solar", "manual", "unknown"]
                    .map(function (f) {
                      return '<option value="' + f + '"' +
                        (e.fuel_type === f ? " selected" : "") + ">" + fmt.label(f) + "</option>";
                    })
                    .join("") +
                "</select></div>" +
              "</div>" +
              '<div class="ks-field"><label class="ks-label" for="ee-notes">' + KS.t('Notes') + '</label>' +
              '<textarea class="ks-textarea" id="ee-notes" name="notes" rows="2" maxlength="500">' +
              dom.esc(e.notes || "") + "</textarea></div>" +
              '<div class="ks-form-actions">' +
                '<button class="ks-btn" type="submit">' + KS.t('Save correction') + '</button>' +
                '<button class="ks-btn ks-btn-secondary" type="button" data-ks-cancel-edit>' + KS.t('Cancel') + '</button>' +
              "</div>" +
              "</form>"
            );

            var editForm = dom.qs("[data-ks-equip-edit]", mount);

            dom.on(dom.qs("[data-ks-cancel-edit]", mount), "click", function () {
              dom.qs("[data-ks-edit-equip]", host).click();
            });

            editForm.addEventListener("submit", function (ev) {
              ev.preventDefault();
              var restore = ui.busy(dom.qs('[type="submit"]', editForm), true, "Saving…");
              var d = forms.read(editForm);
              api
                .patch("/farms/" + id + "/equipment/" + equipId, {
                  custom_brand: (d.custom_brand || "").trim(),
                  custom_model: (d.custom_model || "").trim(),
                  horsepower: d.horsepower === "" ? null : Number(d.horsepower),
                  purchase_year: d.purchase_year === "" ? null : Number(d.purchase_year),
                  condition: d.condition || "unknown",
                  fuel_type: d.fuel_type || "diesel",
                  notes: (d.notes || "").trim(),
                })
                .then(function () {
                  restore();
                  ui.ok("Equipment updated.");
                  // Re-render from the server so we show what was actually stored.
                  pages.equipmentDetail();
                })
                .catch(function (err) {
                  restore();
                  forms.applyServerErrors(editForm, err);
                  ui.error(err.message);
                });
            });
          });

          // Resolve `out` at click time: the re-render above replaces it, so a
          // captured node would be detached after the first save.
          dom.on(host, "[data-ks-opcost]", "click", function () {
            var out = dom.qs("[data-ks-opcost-out]", host);
            if (!out) return;
            var restore = ui.busy(this, true, "Calculating…");
            api
              .post("/farms/" + id + "/equipment/" + equipId + "/operating-cost", {})
              .then(function (r) {
                restore();
                dom.set(
                  out,
                  '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Operating cost estimate') + '</h2>' +
                    (r.estimate_type ? '<span class="ks-badge">' + dom.esc(r.estimate_type) + "</span>" : "") +
                    "</div>" +
                    render.datalist({
                      "Annual operating cost": r.annual_cost_inr ? fmt.inr(r.annual_cost_inr) : null,
                      "Cost per hour": r.cost_per_hour_inr ? fmt.inrExact(r.cost_per_hour_inr) : null,
                      "Cost per acre": r.cost_per_acre_inr ? fmt.inrExact(r.cost_per_acre_inr) : null,
                      Confidence: r.confidence,
                    }, { columns: 2 }) +
                    renderCaveats(r) +
                    renderNarrative(r) +
                    "</div>"
                );
              })
              .catch(function (err) {
                restore();
                ui.error(err.message);
              });
          });

          dom.on(host, "[data-ks-delete-equip]", "click", function () {
            if (!ui.confirm("Remove this equipment from your farm?")) return;
            var restore = ui.busy(this, true, "Removing…");
            api
              .del("/farms/" + id + "/equipment/" + equipId)
              .then(function () {
                ui.ok("Equipment removed.");
                window.location.href = "/farms/" + id + "/equipment/";
              })
              .catch(function (err) {
                restore();
                ui.error(err.message);
              });
          });
        }
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });
  };

  /* =====================================================================
     PAGE: chat
     ===================================================================== */
  pages.chat = function () {
    var id = farmId() || null;
    var log = dom.qs("[data-ks-chat-log]");
    if (!log) return;

    var sessionId = null;

    // Reuse an existing session when one is stored, else create a new one.
    function start() {
      api
        .post("/chat/sessions", { farm: id, language: auth.language() })
        .then(function (session) {
          sessionId = session.id;
          return api.get("/chat/sessions/" + sessionId + "/messages", null, { skipErrors: true });
        })
        .then(function (history) {
          var list = Array.isArray(history) ? history : history.results || [];
          if (!list.length) {
            appendAssistant(
              "Namaste! I can help you understand crop costs, equipment decisions, solar irrigation, subsidies and your own expense patterns.\n\nAsk me anything about your farm finances. Every answer I give is a pointer — please verify scheme amounts and prices with official sources."
            );
          } else {
            list.forEach(function (m) {
              appendMessage(m.role === "user" ? "user" : "assistant", m.content, m.sources, m.is_fallback);
            });
          }
          renderSuggestions([
            "What will my input costs be this season?",
            "Should I buy or rent a tractor?",
            "Am I eligible for a subsidy?",
            "Is solar better than diesel for my pump?",
          ]);
          scrollToEnd();
        })
        .catch(function (err) {
          dom.set(log, '<div class="ks-alert ks-alert-danger"><span aria-hidden="true">⚠</span><div>' +
            "<strong class='ks-alert-title'>" + KS.t("Could not start the assistant") + "</strong>" + dom.esc(err.message) + "</div></div>");
        });
    }

    start();

    var form = dom.qs("[data-ks-chat-form]");
    var sending = false;
    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        // The field is a <textarea name="message">, so selecting by tag name
        // would return null and `input.value` would throw - which is what used
        // to make the Send button do nothing at all. Prefer the explicit hook
        // and fall back to the name for markup written by hand.
        var input = dom.qs("[data-ks-chat-input]", form) || dom.qs('[name="message"]', form);
        if (!input) return;
        var text = String(input.value || "").trim();
        if (!text) return;
        if (!sessionId || sending) return;

        sending = true;
        var sendBtn = dom.qs("[data-ks-chat-send]", form);
        if (sendBtn) {
          sendBtn.disabled = true;
          sendBtn.textContent = "Sending…";
        }

        input.value = "";
        appendMessage("user", text);
        scrollToEnd();

        var typing = appendTyping();
        var finish = function () {
          sending = false;
          if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.textContent = "Send";
          }
        };
        api
          .post("/chat/sessions/" + sessionId + "/ask", { message: text })
          .then(function (result) {
            removeTyping(typing);
            appendAssistant(result.reply, result.sources, result.is_fallback);
            if (result.suggestions && result.suggestions.length) {
              renderSuggestions(result.suggestions);
            } else {
              renderSuggestions([]);
            }
            scrollToEnd();
          })
          .catch(function (err) {
            removeTyping(typing);
            appendAssistant("I could not answer that just now: " + err.message);
            scrollToEnd();
          })
          .then(finish, finish);
      });
    }

    dom.on(document, "click", "[data-ks-ask]", function () {
      var input = dom.qs("[data-ks-chat-input]") || dom.qs('[name="message"]');
      if (!input) return;
      input.value = this.dataset.ksAsk;
      var form = dom.qs("[data-ks-chat-form]");
      if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
    });

    function appendMessage(role, content, sources, isFallback) {
      var bubble = document.createElement("div");
      bubble.className = "ks-msg ks-msg--" + (role === "user" ? "user" : "assistant");

      var avatar = document.createElement("div");
      avatar.className = "ks-msg-avatar";
      avatar.textContent = role === "user" ? "You" : "KS";
      avatar.setAttribute("aria-hidden", "true");

      var body = document.createElement("div");
      body.className = "ks-msg-bubble";
      // Chat text is plain prose with simple **bold** markers; escape first.
      body.innerHTML = dom
        .esc(content)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n\n/g, "</p><p>")
        .replace(/\n/g, "<br>");
      body.innerHTML = "<p>" + body.innerHTML + "</p>";

      if (isFallback) {
        var flag = document.createElement("div");
        flag.className = "ks-msg-fallback";
        flag.textContent = "No verified answer matched — please confirm with a human advisor.";
        body.appendChild(flag);
      }

      if (sources && sources.length) {
        var det = document.createElement("details");
        det.className = "ks-msg-sources";
        det.innerHTML =
          "<summary>Sources (" + sources.length + ")</summary><ul>" +
          sources
            .map(function (s) {
              return "<li>📄 " + dom.esc(s.title || s.topic || "Reference") + "</li>";
            })
            .join("") +
          "</ul>";
        body.appendChild(det);
      }

      bubble.appendChild(avatar);
      bubble.appendChild(body);
      log.appendChild(bubble);
    }

    function appendAssistant(text) {
      appendMessage("assistant", text, [], false);
    }

    function appendTyping() {
      var node = document.createElement("div");
      node.className = "ks-msg ks-msg--assistant";
      node.innerHTML =
        '<div class="ks-msg-avatar" aria-hidden="true">' + KS.t('KS') + '</div>' +
        '<div class="ks-msg-bubble"><span class="ks-typing" aria-label="' + KS.t('Assistant is typing') + '">' +
        "<span></span><span></span><span></span></span></div>";
      log.appendChild(node);
      scrollToEnd();
      return node;
    }

    function removeTyping(node) {
      if (node && node.parentNode) node.parentNode.removeChild(node);
    }

    function renderSuggestions(list) {
      var host = dom.qs("[data-ks-chat-suggestions]");
      if (!host) return;
      if (!list || !list.length) {
        dom.set(host, "");
        return;
      }
      dom.set(
        host,
        list
          .map(function (s) {
            return '<button type="button" class="ks-chip" data-ks-ask="' + dom.esc(s) + '">' + dom.esc(s) + "</button>";
          })
          .join("")
      );
    }

    function scrollToEnd() {
      log.scrollTop = log.scrollHeight;
    }
  };

  /* =====================================================================
     PAGE: profile
     ===================================================================== */
  pages.profile = function () {
    var host = dom.qs("[data-ks-profile]");
    if (!host) return;

    api
      .me()
      .then(function (profile) {
        render(profile);
        return api.get("/auth/consents/", null, { skipErrors: true });
      })
      .then(function (consents) {
        renderConsents(Array.isArray(consents) ? consents : (consents && consents.results) || []);
      })
      .catch(function (err) {
        ui.errorState(host, err);
      });

    function render(profile) {
      var user = profile.user || {};
      var pct = completeness(profile);
      var missing = todoItems(profile);

      dom.set(
        host,
        '<div class="ks-progress-large ks-mb-4">' +
          '<div class="ks-progress-ring" style="--ks-ring-value:' + pct + '"><span>' + pct + "%</span></div>" +
          "<div>" +
            "<h1>" + dom.esc(profile.full_name || user.username) + "</h1>" +
            '<p class="ks-small ks-muted">' + dom.esc(user.email || "") + " · " + dom.esc(user.phone || KS.t("no phone")) + "</p>" +
            '<p class="ks-small ks-mt-3">' + KS.t('More complete data gives') + '<strong>' + KS.t('more reliable estimates') + '</strong>' + KS.t('. Fill in what is missing below.') + '</p>' +
          "</div>" +
        "</div>" +

        (missing.length
          ? '<div class="ks-card ks-mb-4"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Complete your profile') + '</h2></div>' +
            '<ul class="ks-todo">' +
            missing
              .map(function (m) {
                return '<li data-done="false"><span class="ks-todo-box"></span><span>' + dom.esc(m) + "</span></li>";
              })
              .join("") +
            "</ul></div>"
          : '<div class="ks-alert ks-alert-ok ks-mb-4"><span aria-hidden="true">✓</span><div><strong class="ks-alert-title">' + KS.t('Profile complete') + '</strong>' + KS.t('Your estimates are running at full data quality.') + '</div></div>') +

        '<div class="ks-grid ks-grid-2">' +
          '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Farm details') + '</h2>' +
          '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-toggle-profile>' + KS.t('Edit') + '</button></div>' +
          '<form data-ks-profile-form>' +
            '<div data-ks-error-summary></div>' +
            '<div class="ks-stack">' +
              field("full_name", "Full name", "text", profile.full_name) +
              field("phone", "Mobile number", "tel", profile.phone, "phone") +
              field("state", "State", "text", profile.state) +
              field("district", "District", "text", profile.district) +
              field("village", "Village", "text", profile.village) +
              field("pincode", "Pincode", "text", profile.pincode, "pincode") +
              field("land_size", "Land size", "number", profile.land_size, "positive", { step: "0.001", min: "0" }) +
              field("land_unit", "Land unit", "select", profile.land_unit, null, {
                options: [
                  ["acre", "Acre"],
                  ["hectare", "Hectare"],
                  ["guntha", "Guntha"],
                  ["bigha", "Bigha (region specific)"],
                  ["cent", "Cent"],
                ],
              }) +
              field("yearly_farm_income_min", "Yearly farm income (min)", "number", profile.yearly_farm_income_min, "nonnegative", { min: "0" }) +
              field("yearly_farm_income_max", "Yearly farm income (max)", "number", profile.yearly_farm_income_max, "nonnegative", { min: "0" }) +
            "</div>" +
            '<div class="ks-form-actions mt-4"><button class="ks-btn" type="submit">' + KS.t('Save profile') + '</button></div>' +
          "</form></div>" +

          '<div class="ks-card"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Land summary') + '</h2></div>' +
            render.datalist({
              "Land size": profile.land_size ? profile.land_size + " " + fmt.label(profile.land_unit || "acre") : null,
              "In hectares": profile.normalized_land_hectares ? fmt.hectares(profile.normalized_land_hectares) : null,
              "In acres": profile.area_in_hectares ? fmt.acres(profile.area_in_hectares) : null,
              "Ownership": profile.land_ownership,
              "Irrigated": profile.irrigated,
              "Irrigation source": profile.irrigation_source,
            }) +
            '<div class="ks-mt-4"><a class="ks-btn ks-btn-sm" href="/farms/new/">' + KS.t('Manage farms') + '</a></div>' +
          "</div>" +
        "</div>" +

        '<div class="ks-card ks-mt-4"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Privacy &amp; consent') + '</h2></div>' +
          '<p class="ks-small ks-muted">' + KS.t('You control what FarmGrid may use. Withdrawing consent never deletes your data — it stops future processing.') + '</p>' +
          '<div data-ks-consents></div>' +
        "</div>" +

        '<div class="ks-card ks-mt-4"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Language') + '</h2></div>' +
          '<div class="ks-lang">' +
            '<button type="button" data-ks-lang="en">' + KS.t('English') + '</button>' +
            '<button type="button" data-ks-lang="hi">' + KS.t('हिंदी') + '</button>' +
          "</div>" +
          '<p class="ks-tiny ks-muted ks-mt-3">' + KS.t('Hindi is available across the site.') + '</p>' +
        "</div>" +

        '<div class="ks-card ks-mt-4"><div class="ks-card-head"><h2 class="ks-card-title">' + KS.t('Session') + '</h2></div>' +
          '<button class="ks-btn ks-btn-secondary" data-ks-logout>' + KS.t('Sign out') + '</button>' +
        "</div>"
      );

      // Re-bind the language switcher and logout for the freshly injected
      // markup. auth.bindLanguageSwitch is the single implementation: the copy
      // that used to live here only wrote localStorage and posted the
      // preference, so pressing हिं from the profile panel left the page itself
      // in English.
      auth.bindLanguageSwitch(document);
      auth.bindLogout(document);

        var form = forms.bind(
          "[data-ks-profile-form]",
          function (data) {
            return data;
          },
          function (body) {
            // Toast inside the success path only - forms.bind surfaces API
            // errors itself, so claiming success here would be a lie.
            return api.patch("/auth/profile/", body).then(function (saved) {
              ui.ok("Profile updated.");
              return saved;
            });
          }
        );
        if (form) form.addEventListener("submit", function () { /* handled by forms.bind */ });

      dom.on(host, "[data-ks-toggle-profile]", "click", function () {
        var inputs = dom.qsa("[data-ks-profile-form] input, [data-ks-profile-form] select");
        var anyDisabled = inputs.some(function (i) { return i.disabled; });
        inputs.forEach(function (i) { i.disabled = !anyDisabled; });
        this.textContent = anyDisabled ? "Cancel" : "Edit";
      });
    }

    function field(name, label, type, value, validate, attrs) {
      var extra = attrs || {};
      var control;
      if (type === "select") {
        control =
          '<select class="ks-select" name="' + name + '" id="f-' + name + '">' +
          (extra.options || [])
            .map(function (o) {
              return (
                '<option value="' + dom.esc(o[0]) + '"' +
                (String(value || "").toLowerCase() === o[0] ? " selected" : "") + ">" +
                dom.esc(o[1]) + "</option>"
              );
            })
            .join("") +
          "</select>";
      } else {
        control =
          '<input class="ks-input" type="' + type + '" name="' + name + '" id="f-' + name + '"' +
          (extra.step ? ' step="' + extra.step + '"' : "") +
          (extra.min ? ' min="' + extra.min + '"' : "") +
          ' value="' + dom.esc(isNil(value) ? "" : value) + '"' +
          (validate ? ' data-validate="' + validate + '"' : "") +
          ">";
      }
      return (
        '<div class="ks-field">' +
        '<label class="ks-label" for="f-' + name + '">' + dom.esc(label) + "</label>" +
        control +
        "</div>"
      );
    }

    function completeness(p) {
      var checks = [
        p.full_name, p.phone, p.state, p.district, p.village, p.pincode,
        p.land_size, p.yearly_farm_income_min,
      ];
      var filled = checks.filter(function (v) { return !isNil(v) && v !== ""; }).length;
      return Math.round((filled / checks.length) * 100);
    }

    function todoItems(p) {
      var items = [];
      if (!p.phone) items.push("Add your mobile number for important scheme alerts");
      if (!p.state) items.push("Add your state — subsidy rules and tariffs are state-specific");
      if (!p.district) items.push("Add your district for more accurate matches");
      if (isNil(p.land_size)) items.push("Add your land size so costs scale correctly");
      if (isNil(p.yearly_farm_income_min)) items.push("Add your yearly income to check affordability");
      if (!p.user || !p.user.email) items.push("Add an email address");
      return items;
    }

    function renderConsents(list) {
      var host = dom.qs("[data-ks-consents]");
      if (!host) return;
      if (!list.length) {
        dom.set(host, '<p class="ks-muted ks-small">' + KS.t('No consent records yet.') + '</p>');
        return;
      }
      dom.set(
        host,
        '<div class="ks-check-grid">' +
          list
            .map(function (c) {
              return (
                '<label class="ks-check">' +
                '<input type="checkbox" data-ks-consent="' + dom.esc(c.purpose) + '"' + (c.granted ? " checked" : "") + ">" +
                '<span class="ks-check-text"><span class="ks-check-title">' + dom.esc(c.purpose_label || fmt.label(c.purpose)) + "</span>" +
                '<span class="ks-check-desc">' + (c.granted ? "Granted" : "Not granted") + "</span></span></label>"
              );
            })
            .join("") +
        "</div>"
      );

      dom.qsa("[data-ks-consent]").forEach(function (input) {
        input.addEventListener("change", function () {
          // ConsentsView is POST-only with a flat body ({"purpose", "granted"}).
          // This used to PUT a {"consents": [...]} array, which 405'd and left
          // the checkbox silently reverting.
          api
            .post("/auth/consents/", {
              purpose: input.dataset.ksConsent,
              granted: input.checked,
            })
            .then(function () {
              ui.ok("Consent preference updated.");
            })
            .catch(function (err) {
              ui.error(err.message);
              input.checked = !input.checked; // revert on failure
            });
        });
      });
    }
  };

  /* =====================================================================
     PAGE: home / landing (public)
     ===================================================================== */
  pages.home = function () {
    var host = dom.qs("[data-ks-status]");
    if (!host) return;
    ui.loading(host, "Checking platform status…");

    Promise.all([api.health(), api.modelStatus()])
      .then(function (results) {
        var health = results[0] || {};
        var models = (results[1] && results[1].models) || [];
        var active = models.filter(function (m) { return m.status === "active"; });

        dom.set(
          host,
          '<div class="ks-status-strip">' +
            '<div class="ks-status-item"><span class="ks-health-dot ks-health-dot--ok"></span><dt>' + KS.t('API') + '</dt><dd>' +
            dom.esc(health.status || "ok") + "</dd></div>" +
            '<div class="ks-status-item"><span class="ks-health-dot ' + (active.length ? "ks-health-dot--ok" : "ks-health-dot--warn") + '"></span>' +
            "<dt>" + KS.t("Models") + "</dt><dd>" + active.length + " active</dd></div>" +
            '<div class="ks-status-item"><span class="ks-health-dot ks-health-dot--ok"></span><dt>' + KS.t('Estimates') + '</dt><dd>' + KS.t('Ranges only, never fixed claims') + '</dd></div>' +
          "</div>"
        );
      })
      .catch(function () {
        dom.set(
          host,
          '<div class="ks-status-strip"><div class="ks-status-item"><span class="ks-health-dot ks-health-dot--warn"></span>' +
            "<dt>" + KS.t("Status") + "</dt><dd>" + KS.t("Offline - estimates run on your data once reconnected") + "</dd></div></div>"
        );
      });
  };

  /* =====================================================================
     PAGE: authentication forms
     ===================================================================== */

  /** Where to go after a successful sign-in. Defaults to the dashboard. */
  function nextUrl(fallback) {
    var params = new URLSearchParams(window.location.search);
    var next = params.get("next");
    // Only same-origin paths, so ?next= cannot be used as an open redirect.
    if (next && /^\/[a-z0-9\-_/]*$/i.test(next) && next.charAt(0) === "/") return next;
    return fallback;
  }

  pages.login = function () {
    var form = dom.qs("[data-ks-login-form]");
    if (!form) return;
    var target = nextUrl("/dashboard/");

    forms.bind(
      "[data-ks-login-form]",
      function (d) {
        return { username: (d.username || "").trim(), password: d.password || "" };
      },
      function (body) {
        return auth.login(body.username, body.password).then(function () {
          ui.ok("Welcome back.");
          window.location.href = target;
        });
      }
    );
  };

  pages.register = function () {
    var form = dom.qs("[data-ks-register-form]");
    if (!form) return;

    forms.bind(
      "[data-ks-register-form]",
      function (d) {
        // consent is a UI acknowledgement, not a server field on RegisterSerializer.
        return {
          username: (d.username || "").trim(),
          email: (d.email || "").trim(),
          password: d.password || "",
          full_name: (d.full_name || "").trim(),
          phone: (d.phone || "").trim(),
          state: (d.state || "").trim(),
          district: (d.district || "").trim(),
          village: (d.village || "").trim(),
          pincode: (d.pincode || "").trim(),
          land_size: d.land_size === "" || d.land_size === undefined ? null : Number(d.land_size),
          land_unit: d.land_unit || "acre",
        };
      },
      function (body) {
        return auth.register(body).then(function (data) {
          // Signing up is itself the agreement, but the audit trail needs its
          // own timestamped records, and the purposes are a fixed enum on the
          // server: profile data + location for scheme matching.
          var purposes = ["profile", "location"];
          var record = purposes.reduce(function (chain, purpose) {
            return chain.then(function () {
              return api
                .raw("POST", "/auth/consents/", { purpose: purpose, granted: true }, { skipErrors: true })
                .catch(function () { return null; });
            });
          }, Promise.resolve(null));

          return record.then(function () {
            ui.ok("Account created. Let us set up your farm.");
            window.location.href = "/farms/new/";
            return data;
          });
        });
      }
    );
  };

  /* =====================================================================
     PAGE: forms that create records
     ===================================================================== */

  pages.farmCreate = function () {
    var form = dom.qs("[data-ks-farm-form]");
    if (!form) return;

    forms.bind(
      "[data-ks-farm-form]",
      function (d) {
        return {
          name: (d.name || "").trim(),
          description: (d.description || "").trim(),
          is_default: !!d.is_default,
          state: (d.state || "").trim(),
          district: (d.district || "").trim(),
          village: (d.village || "").trim(),
          pincode: (d.pincode || "").trim(),
          parcel_area: d.parcel_area === "" ? null : Number(d.parcel_area),
          parcel_unit: d.parcel_unit || "acre",
        };
      },
      function (body) {
        return api.post("/farms/", body).then(function (farm) {
          auth.setCurrentFarm(farm.id);
          ui.ok("Farm saved.");
          window.location.href = "/farms/" + encodeURIComponent(farm.id) + "/";
          return farm;
        });
      }
    );
  };

  pages.parcel = function () {
    var id = requireFarmId();
    if (!id) return;
    var form = dom.qs("[data-ks-parcel-form]");
    if (!form) return;

    forms.bind(
      "[data-ks-parcel-form]",
      function (d) {
        return {
          name: (d.name || "").trim(),
          area: d.area === "" ? null : Number(d.area),
          unit: d.unit || "acre",
          ownership: d.ownership || "owned",
          irrigated: d.irrigated || "rainfed",
          irrigation_source: d.irrigation_source || "other",
          soil_type: (d.soil_type || "").trim(),
          is_primary: !!d.is_primary,
        };
      },
      function (body) {
        return api.post("/farms/" + id + "/land-parcels", body).then(function (parcel) {
          ui.ok("Parcel saved.");
          window.location.href = "/farms/" + encodeURIComponent(id) + "/";
          return parcel;
        });
      }
    );

    loadBighaRules();
    loadLandConverter();
  };

  function unique(value, index, list) {
    return list.indexOf(value) === index;
  }

  /**
   * "How we convert bigha" disclosure on the parcel form.
   *
   * A bigha is not a fixed size, so the app needs a regional rule before it can
   * convert. Showing the farmer the actual verified rules - and saying plainly
   * when there are none - is more honest than silently applying a default.
   */
  function loadBighaRules() {
    var host = dom.qs("[data-ks-bigha-rules]");
    var list = dom.qs("[data-ks-bigha-rules-list]");
    if (!host || !list) return;

    api
      .get("/bigha-rules", null, { skipErrors: true })
      .then(function (rows) {
        var rules = Array.isArray(rows) ? rows : rows.results || [];
        if (!rules.length) {
          // The endpoint filters is_verified=True, so an empty list is the normal
          // case on a fresh install rather than an error worth shouting about.
          dom.set(
            list,
            '<div class="ks-alert ks-alert-info"><span aria-hidden="true">' +
              "&#9432;</span><div>No verified bigha rules are published on this server " +
              "yet. If you enter area in bigha we will ask you to confirm the size " +
              "rather than guess. Entering area in acre or hectare avoids the issue " +
              "entirely.</div></div>"
          );
        } else {
          dom.set(
            list,
            render.datalist(
              {
                "Regions covered": rules
                  .map(function (r) {
                    return r.district ? r.state + " (" + r.district + ")" : r.state;
                  })
                  .filter(unique)
                  .join(", "),
                "Rules available": rules.length
              },
              { columns: 2 }
            ) +
              '<div class="ks-table-wrap ks-mt-4"><table class="ks-table">' +
              "<thead><tr><th>" + KS.t("Region") + "</th><th>" + KS.t("1 bigha (sq m)") + "</th><th>" + KS.t("Verified on") + "</th></tr></thead><tbody>" +
              rules
                .map(function (r) {
                  return (
                    "<tr><td>" + dom.esc(r.state + (r.district ? " · " + r.district : "")) + "</td>" +
                    "<td>" + dom.esc(fmt.number(r.sq_meters_per_bigha, 2)) + "</td>" +
                    "<td>" + dom.esc(r.last_verified_at || KS.t("not recorded")) + "</td></tr>"
                  );
                })
                .join("") +
              "</tbody></table></div>"
          );
        }
        host.removeAttribute("hidden");
      })
      .catch(function () {
        dom.set(
          list,
          '<p class="ks-muted ks-small">Bigha conversion rules could not be loaded. ' +
            "Enter area in acre or hectare to avoid the issue.</p>"
        );
        host.removeAttribute("hidden");
      });
  }

  /**
   * "Convert an area before saving" disclosure on the parcel form.
   *
   * Farmer-facing surface for /land-units/convert. It calls the same service the
   * parcel save path uses, so the number shown here is the number that will be
   * stored. Bigha with no matching verified rule comes back as
   * requires_confirmation, and we say so instead of inventing a factor.
   */
  function loadLandConverter() {
    var host = dom.qs("[data-ks-land-convert]");
    var form = dom.qs("[data-ks-convert-form]");
    var out = dom.qs("[data-ks-convert-out]");
    if (!host || !form || !out) return;

    var parcelForm = dom.qs("[data-ks-parcel-form]");
    var valueInput = form.querySelector('[name="value"]');
    var unitSelect = form.querySelector('[name="unit"]');

    // Start from whatever the farmer already typed in the parcel form.
    if (parcelForm) {
      var parcelArea = parcelForm.querySelector('[name="area"]');
      var parcelUnit = parcelForm.querySelector('[name="unit"]');
      if (parcelArea && parcelArea.value) valueInput.value = parcelArea.value;
      if (parcelUnit && parcelUnit.value) unitSelect.value = parcelUnit.value;
    }

    forms.bind("[data-ks-convert-form]", null, function (data) {
      var value = data.value === "" || data.value === null ? NaN : Number(data.value);
      var unit = data.unit || "acre";
      if (isNaN(value)) {
        forms.setError(valueInput, "Enter the area to convert.");
        return Promise.reject(new Error("invalid"));
      }
      return api
        .post("/land-units/convert", { value: value, unit: unit })
        .then(function (payload) {
          var result = (payload && payload.result) || payload || {};
          dom.set(out, convertResultHtml(result, value, unit));
          var apply = out.querySelector("[data-ks-convert-apply]");
          if (apply) {
            apply.addEventListener("click", function () {
              if (!parcelForm || result.value_ha == null) return;
              parcelForm.querySelector('[name="area"]').value = result.value_ha;
              parcelForm.querySelector('[name="unit"]').value = "hectare";
              ui.ok("Filled the parcel area in hectares.");
            });
          }
          return result;
        });
    });

    host.removeAttribute("hidden");
  }

  function convertResultHtml(result, value, unit) {
    if (result.value_ha == null || result.requires_confirmation) {
      return (
        '<div class="ks-alert ks-alert-warn"><span aria-hidden="true">&#9888;</span><div>' +
        "We do not have a verified conversion for " +
        dom.esc(fmt.number(value, 3) + " " + fmt.label(unit)) +
        " in your region, so we will not guess. Save the parcel in acre or hectare, " +
        "or confirm the size when the app asks.</div></div>"
      );
    }
    var rows =
      render.datalist(
        {
          "You entered": fmt.number(value, 3) + " " + fmt.label(unit),
          Hectares: fmt.number(result.value_ha, 4) + " ha",
          Acres: fmt.number(result.value_acre, 3) + " acre"
        },
        { columns: 2 }
      ) +
      '<p class="ks-muted ks-small">Method: ' +
      dom.esc(result.method || KS.t("standard factor")) +
      (result.rule_label ? " &middot; " + dom.esc(result.rule_label) : "") +
      "</p>";
    return (
      rows +
      '<button class="ks-btn ks-btn-secondary ks-btn-sm" type="button" data-ks-convert-apply>' +
      "Use hectares in the parcel form</button>"
    );
  }


  /**
   * Equipment create, then hand off to the photo uploader.
   *
   * `category` is a required foreign key, so the select is populated from
   * /equipment/categories rather than hard-coded - adding a category to the
   * catalogue must not require a frontend change.
   */
  pages.equipmentUpload = function () {
    var id = requireFarmId();
    if (!id) return;
    var form = dom.qs("[data-ks-equipment-form]");
    if (!form) return;

    loadCategories();
    loadCatalogPicker(form);

    function loadCategories() {
      var mount = dom.qs("[data-ks-equip-category]");
      if (!mount) return;

      api
        .get("/equipment/categories", null, { skipErrors: true })
        .then(function (rows) {
          var cats = Array.isArray(rows) ? rows : rows.results || [];
          if (!cats.length) {
            dom.set(
              mount,
              '<div class="ks-alert ks-alert-danger"><span aria-hidden="true">⚠</span>' +
              "<div>" + KS.t("The equipment catalogue has not been loaded on this server, so equipment cannot be added.") + "</div></div>"
            );
            return;
          }
          dom.set(
            mount,
            '<div class="ks-field">' +
            '<label class="ks-label" for="eq-category">' + KS.t('Equipment type') + '<span class="ks-req">*</span></label>' +
            '<select class="ks-select" id="eq-category" name="category" required data-validate="required">' +
            cats
              .map(function (c) {
                var range = c.typical_hp_min
                  ? " (" + fmt.number(c.typical_hp_min) + "–" + fmt.number(c.typical_hp_max) + " hp)"
                  : "";
                return '<option value="' + dom.esc(c.id) + '">' + dom.esc(c.name + range) + "</option>";
              })
              .join("") +
            "</select>" +
            '<p class="ks-help">' + KS.t('Pick the closest match — it decides which operating-cost assumptions we use.') + '</p>' +
            "</div>"
          );
        })
        .catch(function () {
          dom.set(
            mount,
            '<div class="ks-alert ks-alert-danger"><span aria-hidden="true">⚠</span>' +
            "<div>" + KS.t("Could not load the equipment catalogue. Check your connection and reload.") + "</div></div>"
          );
        });
    }

    /**
     * Searchable catalogue picker (GET /equipment/catalog).
     *
     * The endpoint has no free-text search - only ?brand and ?category, where
     * category matches the category *code* - and it returns at most 200 rows
     * filtered to is_verified=True. So the whole list is fetched once and
     * filtered client-side, which is both simpler and avoids a request per
     * keystroke.
     *
     * Picking a row fills the manual fields rather than owning them: a farmer
     * whose machine is not listed can still type the model by hand.
     */
    function loadCatalogPicker(form) {
      var host = dom.qs("[data-ks-catalog-picker]");
      var list = dom.qs("[data-ks-catalog-list]");
      if (!host || !list) return;

      api
        .get("/equipment/catalog", null, { skipErrors: true })
        .then(function (rows) {
          var items = Array.isArray(rows) ? rows : rows.results || [];
          if (!items.length) {
            dom.set(
              list,
              '<p class="ks-muted ks-small">No verified models are published on this ' +
                "server yet, so please enter the brand and model by hand below.</p>"
            );
            return;
          }

          // Resolve category_code -> category UUID, which is what the POST wants.
          var catSelect = form ? form.querySelector('[name="category"]') : null;
          var codeToId = {};
          if (catSelect) {
            Array.prototype.forEach.call(catSelect.options, function (opt) {
              var label = opt.textContent.toLowerCase();
              items.forEach(function (it) {
                if (
                  codeToId[it.category_code] === undefined &&
                  label.indexOf(String(it.category_name || "").toLowerCase()) === 0
                ) {
                  codeToId[it.category_code] = opt.value;
                }
              });
            });
          }

          dom.set(
            list,
            '<div class="ks-field">' +
              '<label class="ks-label" for="eq-cat-search">' + KS.t('Search the catalogue') + '</label>' +
              '<input class="ks-input" type="search" id="eq-cat-search" ' +
              'data-ks-catalog-search maxlength="60" ' +
              'placeholder="e.g. Mahindra, 575, tractor">' +
              "</div>" +
              '<div data-ks-catalog-results></div>'
          );

          var results = dom.qs("[data-ks-catalog-results]", list);
          var search = dom.qs("[data-ks-catalog-search]", list);

          function draw() {
            var q = String(search.value || "").trim().toLowerCase();
            var matched = q
              ? items.filter(function (it) {
                  return (
                    String(it.brand).toLowerCase().indexOf(q) !== -1 ||
                    String(it.model).toLowerCase().indexOf(q) !== -1 ||
                    String(it.category_name).toLowerCase().indexOf(q) !== -1
                  );
                })
              : items;
            var shown = matched.slice(0, 25);

            if (!shown.length) {
              dom.set(
                results,
                '<p class="ks-muted ks-small">Nothing matches "' + dom.esc(q) + '". ' +
                  "Enter the model by hand below.</p>"
              );
              return;
            }

            dom.set(
              results,
              '<p class="ks-tiny ks-muted">' +
                (matched.length > shown.length
                  ? "Showing " + shown.length + " of " + matched.length + " matches."
                  : matched.length + " model" + (matched.length === 1 ? "" : "s") + " listed.") +
                "</p>" +
                '<ul class="ks-checklist ks-mt-4">' +
                shown
                  .map(function (it) {
                    var price =
                      it.price_expected || it.price_min || it.price_max || null;
                    var meta = [];
                    if (it.hp) meta.push(fmt.number(it.hp) + " hp");
                    if (it.fuel_type) meta.push(it.fuel_type);
                    if (price) meta.push(fmt.inrShort(price) + " typical");
                    return (
                      '<li><label class="ks-check">' +
                      '<input type="radio" name="catalog_choice" value="' +
                      dom.esc(it.id) + '">' +
                      "<span><strong>" + dom.esc(it.brand + " " + it.model) + "</strong> " +
                      '<span class="ks-badge">' + dom.esc(it.category_name) + "</span><br>" +
                      '<span class="ks-tiny ks-muted">' +
                      dom.esc(meta.join(" · ") || KS.t("no extra details published")) +
                      "</span></span></label></li>"
                    );
                  })
                  .join("") +
                "</ul>"
            );

            dom.qsa('input[name="catalog_choice"]', results).forEach(function (input) {
              input.addEventListener("change", function () {
                applyCatalogPick(this.value, items, form, codeToId);
              });
            });
          }

          search.addEventListener("input", draw);
          draw();
        })
        .catch(function () {
          dom.set(
            list,
            '<p class="ks-muted ks-small">The model catalogue could not be loaded. ' +
              "Enter the brand and model by hand below.</p>"
          );
        });
    }

    function applyCatalogPick(id, items, form, codeToId) {
      var picked = null;
      for (var i = 0; i < items.length; i++) {
        if (items[i].id === id) {
          picked = items[i];
          break;
        }
      }
      if (!picked || !form) return;

      function put(name, value) {
        if (value === null || value === undefined || value === "") return;
        var el = form.querySelector('[name="' + name + '"]');
        if (el && el.value === "") el.value = value;
      }

      // category: the POST wants the category UUID, not the code.
      if (codeToId[picked.category_code]) {
        var sel = form.querySelector('[name="category"]');
        if (sel) sel.value = codeToId[picked.category_code];
      }
      put("custom_brand", picked.brand);
      put("custom_model", picked.model);
      put("horsepower", picked.hp);
      put("fuel_type", picked.fuel_type);
      put("purchase_price", picked.price_expected || picked.price_min || null);

      ui.ok("Filled in from the catalogue. Check the details and edit anything wrong.");
    }

    forms.bind(
      "[data-ks-equipment-form]",
      function (d) {
        return {
          category: d.category,
          custom_brand: (d.custom_brand || "").trim(),
          custom_model: (d.custom_model || "").trim(),
          horsepower: d.horsepower === "" ? null : Number(d.horsepower),
          purchase_year: d.purchase_year === "" ? null : Number(d.purchase_year),
          purchase_price: d.purchase_price === "" ? null : Number(d.purchase_price),
          usage_hours_per_year: d.usage_hours_per_year === "" ? null : Number(d.usage_hours_per_year),
          area_served_acres: d.area_served_acres === "" ? null : Number(d.area_served_acres),
          condition: d.condition || "unknown",
          fuel_type: d.fuel_type || "diesel",
          is_owned: !!d.is_owned,
          is_operational: !!d.is_operational,
          notes: (d.notes || "").trim(),
        };
      },
      function (body) {
        return api.post("/farms/" + id + "/equipment", body).then(function (item) {
          ui.ok("Equipment saved. Now add a photo of its name plate.");
          window.location.href =
            "/farms/" + encodeURIComponent(id) + "/equipment/" + encodeURIComponent(item.id) + "/upload/";
          return item;
        });
      }
    );
  };

  /**
   * Add a crop.
   *
   * The crop catalogue is server-owned and filterable via ?search=, so it is
   * loaded here rather than hard-coded. A small in-page search box narrows the
   * select so a farmer is not scrolling 40+ options on a phone.
   */
  pages.cropCreate = function () {
    var id = requireFarmId();
    if (!id) return;
    var form = dom.qs("[data-ks-crop-form]");
    if (!form) return;

    var pick = dom.qs("[data-ks-crop-pick]");
    var count = dom.qs("[data-ks-crop-count]");
    var search = dom.qs("[data-ks-crop-search]");
    var all = [];

    api
      .get("/crops", null, { skipErrors: true })
      .then(function (rows) {
        all = Array.isArray(rows) ? rows : rows.results || [];
        if (!all.length) {
          if (pick) {
            dom.set(
              pick,
              '<option value="">' + KS.t('No crops in the catalogue') + '</option>'
            );
            pick.disabled = true;
          }
          if (count) {
            dom.set(count, "The crop catalogue is empty on this server, so a crop cannot be added yet.");
          }
          return;
        }
        renderOptions("");
        if (count) {
          dom.set(count, all.length + " crops available. Type above to narrow the list.");
        }
        if (search) search.disabled = false;
      })
      .catch(function () {
        if (pick) {
          dom.set(pick, '<option value="">' + KS.t('Could not load the crop list') + '</option>');
          pick.disabled = true;
        }
        if (count) dom.set(count, "Check your connection and reload the page.");
      });

    function renderOptions(term) {
      var needle = term.trim().toLowerCase();
      var matches = needle
        ? all.filter(function (c) {
            return (c.name || "").toLowerCase().indexOf(needle) !== -1;
          })
        : all;

      var opts = matches
        .map(function (c) {
          // local_name is what farmers actually say; primary_season sets the
          // default. is_synthetic_benchmark flags catalog rows whose cost data
          // is modelled rather than observed - the estimate page says so again.
          var bits = [c.local_name || c.name];
          if (c.primary_season) bits.push(c.primary_season);
          if (c.is_synthetic_benchmark) bits.push("indicative cost data");
          return (
            '<option value="' + dom.esc(c.id) + '">' + dom.esc(bits.join(" · ")) + "</option>"
          );
        })
        .join("");

      if (!matches.length) {
        dom.set(pick, '<option value="">No crop matches "' + dom.esc(needle) + '"</option>');
        pick.disabled = true;
        return;
      }

      pick.disabled = false;
      dom.set(pick, opts);
    }

    if (search) {
      search.addEventListener("input", function () {
        renderOptions(search.value || "");
      });
    }

    forms.bind(
      "[data-ks-crop-form]",
      function (d) {
        return {
          crop: d.crop,
          season: d.season,
          year: d.year === "" ? null : Number(d.year),
          area: d.area === "" ? null : Number(d.area),
          area_unit: d.area_unit || "acre",
          expected_yield_qtl_per_acre:
            d.expected_yield_qtl_per_acre === "" ? null : Number(d.expected_yield_qtl_per_acre),
          is_planned: !!d.is_planned,
        };
      },
      function (body) {
        return api.post("/farms/" + id + "/crops", body).then(function (row) {
          ui.ok("Crop added.");
          window.location.href = "/farms/" + encodeURIComponent(id) + "/";
          return row;
        });
      }
    );
  };

  /* =====================================================================
     PAGE: staff data-ingestion console

     A thin client over /api/v1/data-ingestion/*. Every endpoint here is
     permission-gated to staff server-side, so this controller does no
     security work of its own - it renders what the API allows and shows the
     refusal when it says no.

     Three shapes of `data` matter here and they are not interchangeable:
       - list endpoints return a BARE ARRAY (never {results: [...]});
       - artifact/record detail return the object FLAT plus a `provenance` key;
       - provenance-report returns a different object per ?kind.
     `asRows` normalises the array-or-results ambiguity, but the other two are
     handled explicitly.
     ===================================================================== */
  pages.staffDataIngestion = function () {
    var BASE = "/data-ingestion";

    var sourcesHost = dom.qs("[data-ks-sources]");
    var queueHost = dom.qs("[data-ks-queue]");
    var runsHost = dom.qs("[data-ks-runs]");
    var artifactsHost = dom.qs("[data-ks-artifacts]");
    var recordsHost = dom.qs("[data-ks-records]");
    var srcDetail = dom.qs("[data-ks-src-detail]");
    var runDetail = dom.qs("[data-ks-run-detail]");
    var artifactDetail = dom.qs("[data-ks-artifact-detail]");
    var recordDetail = dom.qs("[data-ks-record-detail]");
    var collectOut = dom.qs("[data-ks-collect-out]");

    var sourceRows = [];
    var allSources = [];

    // ---------------------------------------------------------------- utils

    function asRows(payload) {
      if (Array.isArray(payload)) return payload;
      if (payload && Array.isArray(payload.results)) return payload.results;
      return [];
    }

    // dom.on binds one scope and rejects an array, so multi-element wiring goes
    // through this loop. Kept local so the call sites read like the rest of the file.
    function onEach(nodes, selector, event, handler) {
      Array.prototype.forEach.call(nodes, function (node) {
        dom.on(node, selector, event, handler);
      });
    }

    function badge(value) {
      var v = String(value || "");
      var tone =
        /approved|completed|valid|published|allowed/.test(v)
          ? "ks-badge-ok"
          : /rejected|failed|denied|blocked|invalid|duplicate/.test(v)
            ? "ks-badge-warn"
            : /pending|running|manual_review|review|needs_changes|partial|dry_run/.test(v)
              ? "ks-badge"
              : "ks-badge";
      return '<span class="ks-badge ' + tone + '">' + dom.esc(fmt.label(v || "—")) + "</span>";
    }

    function when(iso) {
      if (!iso) return "—";
      var d = new Date(iso);
      return isNaN(d.getTime()) ? dom.esc(iso) : dom.esc(d.toLocaleString());
    }

    function shortId(uuid) {
      return uuid ? String(uuid).slice(0, 8) : "—";
    }

    function table(headers, rows) {
      if (!rows.length) {
        return '<p class="ks-muted ks-small">' + KS.t('Nothing to show.') + '</p>';
      }
      return (
        '<div class="ks-table-wrap"><table class="ks-table"><thead><tr>' +
        headers.map(function (h) { return "<th>" + dom.esc(h) + "</th>"; }).join("") +
        "</tr></thead><tbody>" +
        rows.join("") +
        "</tbody></table></div>"
      );
    }

    // ui.errorState writes into the node itself, so this must not also pass the
    // result to dom.set - that would blank the message it just rendered.
    function fail(host, err) {
      if (host) ui.errorState(host, err);
    }

    // -------------------------------------------------------------- sources

    function loadSources() {
      if (!sourcesHost) return;
      dom.set(sourcesHost, ui.skeleton(3, true));

      var query = {};
      dom.qsa("[data-ks-src-filter]").forEach(function (el) {
        if (el.value) query[el.dataset.ksSrcFilter] = el.value;
      });

      api
        .get(BASE + "/sources", query)
        .then(function (rows) {
          sourceRows = asRows(rows);
          allSources = sourceRows;
          renderSources();
          populateCategoryFilter();
          populateSourceSelect();
        })
        .catch(function (err) {
          fail(sourcesHost, err);
        });
    }

    function renderSources() {
      dom.set(
        sourcesHost,
        sourceRows.length
          ? render.datalist(
              {
                "Sources listed": sourceRows.length,
                Approved: sourceRows.filter(function (s) { return s.approval_status === "approved"; }).length,
                Pending: sourceRows.filter(function (s) { return s.approval_status === "pending"; }).length,
                "Collection enabled": sourceRows.filter(function (s) { return s.collection_enabled; }).length
              },
              { columns: 2 }
            ) +
            '<div class="ks-table-wrap ks-mt-4"><table class="ks-table"><thead><tr>' +
            "<th>" + KS.t("Name") + "</th><th>" + KS.t("Type") + "</th><th>" + KS.t("Status") + "</th><th>" + KS.t("Collect") + "</th><th>" + KS.t("Last compliance") + "</th><th>" + KS.t("Actions") + "</th>" +
            "</tr></thead><tbody>" +
            sourceRows
              .map(function (s) {
                return (
                  "<tr><td><strong>" + dom.esc(s.name) + "</strong><br>" +
                  '<span class="ks-tiny ks-muted">' + dom.esc(s.organization || s.base_url) + "</span></td>" +
                  "<td>" + dom.esc(fmt.label(s.source_type)) + "</td>" +
                  "<td>" + badge(s.approval_status) + "</td>" +
                  "<td>" + (s.collection_enabled ? "enabled" : "disabled") + "</td>" +
                  "<td>" + when(s.last_compliance_check_at) + "</td>" +
                  '<td><button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
                  'data-ks-src-detail="' + dom.esc(s.pk) + '">' + KS.t('View') + '</button> ' +
                  '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
                  'data-ks-src-compliance="' + dom.esc(s.pk) + '">' + KS.t('Compliance') + '</button></td></tr>'
                );
              })
              .join("") +
            "</tbody></table></div>"
          : '<p class="ks-muted ks-small">' + KS.t('No sources match these filters.') + '</p>'
      );

      dom.on(sourcesHost, "[data-ks-src-detail]", "click", function () {
        showSource(this.dataset.ksSrcDetail);
      });
      dom.on(sourcesHost, "[data-ks-src-compliance]", "click", function () {
        runCompliance(this.dataset.ksSrcCompliance);
      });
    }

    function populateCategoryFilter() {
      var sel = dom.qs('[data-ks-src-filter="category"]');
      if (!sel || sel.dataset.ksFilled === "1") return;
      sel.dataset.ksFilled = "1";
      var seen = {};
      var html = sel.innerHTML;
      sourceRows.forEach(function (s) {
        if (s.category && !seen[s.category]) {
          seen[s.category] = true;
          html += '<option value="' + dom.esc(s.category) + '">' + dom.esc(fmt.label(s.category)) + "</option>";
        }
      });
      sel.innerHTML = html;
    }

    // Only approved + collection_enabled sources can collect, so offering the
    // others just produces a guaranteed 400.
    function populateSourceSelect() {
      var sel = dom.qs("[data-ks-approved-sources]");
      if (!sel) return;
      var usable = allSources.filter(function (s) {
        return s.approval_status === "approved" && s.collection_enabled;
      });
      dom.set(
        sel,
        usable.length
          ? usable
              .map(function (s) {
                return '<option value="' + dom.esc(s.pk) + '">' + dom.esc(s.name) + "</option>";
              })
              .join("")
          : '<option value="">' + KS.t('No approved source is collection-enabled') + '</option>'
      );
    }

    function showSource(sourceId) {
      if (!srcDetail) return;
      dom.set(srcDetail, ui.skeleton(2, true));
      api
        .get(BASE + "/sources/" + encodeURIComponent(sourceId))
        .then(function (s) {
          dom.set(
            srcDetail,
            '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">🔎</span> ' +
              "<strong>" + dom.esc(s.name) + "</strong> " + badge(s.approval_status) + "</div>" +
              render.datalist(
                {
                  "Base URL": s.base_url,
                  "Source type": fmt.label(s.source_type),
                  Category: fmt.label(s.category),
                  Organisation: s.organization || "—",
                  Region: [s.state, s.district].filter(Boolean).join(" · ") || "—",
                  "Approval reason": s.approval_reason || "—",
                  "robots.txt": s.robots_status,
                  Terms: s.terms_status,
                  "Rate limit": s.rate_limit_per_minute + " /min",
                  "Request delay": fmt.number(s.request_delay_seconds, 1) + " s",
                  "Max pages/run": s.max_pages_per_run,
                  "Allows images": s.allows_images ? "yes" : "no",
                  "Allows documents": s.allows_documents ? "yes" : "no",
                  "Allows structured data": s.allows_structured_data ? "yes" : "no",
                  Attribution: s.attribution_text || "—",
                  Notes: s.notes || "—",
                  Registered: when(s.created_at)
                },
                { columns: 2 }
              ) +
              '<div class="ks-form-actions">' +
              '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
              'data-ks-src-edit="' + dom.esc(s.pk) + '">' + KS.t('Edit') + '</button> ' +
              '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
              'data-ks-src-runs="' + dom.esc(s.pk) + '">' + KS.t('Show this source\'s runs') + '</button>' +
              "</div>" +
              '<div class="ks-mt-4" data-ks-src-edit-out></div></div>'
          );
          dom.on(srcDetail, "[data-ks-src-runs]", "click", function () {
            showSourceRuns(this.dataset.ksSrcRuns);
          });
          dom.on(srcDetail, "[data-ks-src-edit]", "click", function () {
            revealSourceEdit(s);
          });
        })
        .catch(function (err) {
          fail(srcDetail, err);
        });
    }

    /**
     * Inline PATCH editor for a source. The register form already enumerates the
     * categories, so the editor borrows those options rather than keeping a
     * second list that could drift. Approval status and collection_enabled are
     * read-only server-side, so they are shown but never posted back.
     */
    function revealSourceEdit(s) {
      var mount = dom.qs("[data-ks-src-edit-out]");
      if (!mount) return;

      var registerSelect = dom.qs('[data-ks-source-form] [name="category"]');
      var categoryOptions = registerSelect
        ? Array.prototype.map
            .call(registerSelect.options, function (o) {
              return (
                '<option value="' + dom.esc(o.value) + '"' +
                (o.value === s.category ? " selected" : "") + ">" +
                dom.esc(o.textContent) + "</option>"
              );
            })
            .join("")
        : "";

      dom.set(
        mount,
        '<form class="ks-form" data-ks-src-edit-form novalidate>' +
          '<div data-ks-error-summary></div>' +
          '<h3 class="ks-card-title">' + KS.t('Edit source') + '</h3>' +
          '<div class="ks-grid ks-grid-2">' +
          editField("Name", "name", s.name, "text") +
          editField("Organisation", "organization", s.organization, "text") +
          '<div class="ks-field"><label class="ks-label" for="edit-category">' + KS.t('Category') + '</label>' +
          '<select class="ks-select" id="edit-category" name="category">' +
          categoryOptions +
          "</select></div>" +
          editField("Geographic scope", "geographic_scope", s.geographic_scope, "text") +
          editField("State", "state", s.state, "text") +
          editField("District", "district", s.district, "text") +
          editField("robots.txt URL", "robots_url", s.robots_url, "text") +
          editField("Terms URL", "terms_url", s.terms_url, "text") +
          editField("Licence URL", "license_url", s.license_url, "text") +
          editField("Attribution", "attribution_text", s.attribution_text, "text") +
          editField("Rate limit (req/min)", "rate_limit_per_minute", s.rate_limit_per_minute, "number") +
          editField("Request delay (s)", "request_delay_seconds", s.request_delay_seconds, "number") +
          editField("Max pages per run", "max_pages_per_run", s.max_pages_per_run, "number") +
          "</div>" +
          '<div class="ks-consent">' +
          editCheck("Provides images", "allows_images", s.allows_images) +
          editCheck("Provides documents", "allows_documents", s.allows_documents) +
          editCheck("Provides structured data", "allows_structured_data", s.allows_structured_data) +
          "</div>" +
          '<div class="ks-field"><label class="ks-label" for="edit-notes">' + KS.t('Notes') + '</label>' +
          '<textarea class="ks-textarea" id="edit-notes" name="notes" rows="2" maxlength="500">' +
          dom.esc(s.notes || "") +
          "</textarea></div>" +
          '<div class="ks-form-actions">' +
          '<button class="ks-btn ks-btn-sm" type="submit">' + KS.t('Save changes') + '</button>' +
          '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" data-ks-src-edit-cancel>' + KS.t('Cancel') + '</button>' +
          "</div></form>"
      );

      dom.on(mount, "[data-ks-src-edit-cancel]", "click", function () {
        dom.set(mount, "");
      });

      forms.bind("[data-ks-src-edit-form]", function (d) {
        var body = {
          name: (d.name || "").trim(),
          organization: (d.organization || "").trim(),
          category: d.category || s.category,
          geographic_scope: (d.geographic_scope || "").trim(),
          state: (d.state || "").trim(),
          district: (d.district || "").trim(),
          robots_url: (d.robots_url || "").trim(),
          terms_url: (d.terms_url || "").trim(),
          license_url: (d.license_url || "").trim(),
          attribution_text: (d.attribution_text || "").trim(),
          allows_images: !!d.allows_images,
          allows_documents: !!d.allows_documents,
          allows_structured_data: !!d.allows_structured_data
        };
        ["rate_limit_per_minute", "request_delay_seconds", "max_pages_per_run"].forEach(function (k) {
          if (d[k] !== "" && d[k] !== undefined) body[k] = Number(d[k]);
        });
        return body;
      }, function (body) {
        return api.patch(BASE + "/sources/" + encodeURIComponent(s.pk), body).then(function (updated) {
          ui.ok("Source updated.");
          loadSources();
          showSource(updated.pk);
          return updated;
        });
      });
    }

    function editField(label, name, value, type) {
      return (
        '<div class="ks-field"><label class="ks-label" for="edit-' + dom.esc(name) + '">' +
        dom.esc(label) + "</label>" +
        '<input class="ks-input" type="' + dom.esc(type) + '" id="edit-' + dom.esc(name) +
        '" name="' + dom.esc(name) + '"' +
        (type === "number" ? ' step="any" inputmode="decimal"' : "") +
        ' value="' + dom.esc(value === null || value === undefined ? "" : value) + '"></div>'
      );
    }

    function editCheck(label, name, checked) {
      return (
        '<label class="ks-check"><input type="checkbox" name="' + dom.esc(name) + '" value="true"' +
        (checked ? " checked" : "") + "><span>" + dom.esc(label) + "</span></label>"
      );
    }

    function runCompliance(sourceId) {
      if (!srcDetail) return;
      var runId = (dom.qs("#col-run") || {}).value || "";
      dom.set(srcDetail, ui.skeleton(2, true));
      api
        .post(BASE + "/sources/" + encodeURIComponent(sourceId) + "/compliance-check", { run_id: runId })
        .then(function (check) {
          dom.set(
            srcDetail,
            '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">🛡</span> ' +
              "Compliance decision: " + badge(check.decision) + "</div>" +
              render.datalist(
                {
                  "Run id": check.run_id || "—",
                  "Checked at": when(check.checked_at),
                  "robots.txt retrieved": check.robots_retrieved ? "yes" : "no",
                  "robots.txt allows target paths": check.robots_allows_target_paths ? "yes" : "no",
                  "Terms manual review": check.terms_manual_review_required ? "yes" : "no",
                  "Login required": check.login_required_detected ? "yes" : "no",
                  Captcha: check.captcha_detected ? "yes" : "no",
                  Paywall: check.paywall_detected ? "yes" : "no",
                  "Blocked reason": check.blocked_reason || "—",
                  "Evidence path": check.evidence_path || "—",
                  "Evidence hash": check.evidence_hash || "—"
                },
                { columns: 2 }
              ) +
              "</div>"
          );
          loadSources();
        })
        .catch(function (err) {
          fail(srcDetail, err);
        });
    }

    function showSourceRuns(sourceId) {
      if (!srcDetail) return;
      dom.set(srcDetail, ui.skeleton(2, true));
      api
        .get(BASE + "/sources/" + encodeURIComponent(sourceId) + "/runs")
        .then(function (rows) {
          dom.set(
            srcDetail,
            '<div class="ks-result"><h3 class="ks-card-title">' + KS.t('Runs for this source') + '</h3>' +
              renderRunsTable(asRows(rows)) +
              "</div>"
          );
        })
        .catch(function (err) {
          fail(srcDetail, err);
        });
    }

    function renderRunsTable(rows, linkable) {
      return table(
        ["Run", "Status", "Started", "Pages", "Records", "Dupes", "Blocked", "Dry run"],
        rows.map(function (r) {
          return (
            "<tr" + (linkable ? ' data-run="' + dom.esc(r.pk) + '" style="cursor:pointer"' : "") + ">" +
            "<td>" + dom.esc(r.run_id) + "</td>" +
            "<td>" + badge(r.status) + "</td>" +
            "<td>" + when(r.started_at) + "</td>" +
            '<td class="num">' + dom.esc(r.pages_collected) + " / " + dom.esc(r.pages_attempted) + "</td>" +
            '<td class="num">' + dom.esc(r.records_extracted) + "</td>" +
            '<td class="num">' + dom.esc(r.duplicates_skipped) + "</td>" +
            '<td class="num">' + dom.esc(r.blocked_items) + "</td>" +
            "<td>" + (r.is_dry_run ? "yes" : "no") + "</td></tr>"
          );
        })
      );
    }

    // ------------------------------------------------------ source register

    var sourceForm = dom.qs("[data-ks-source-form]");
    if (sourceForm) {
      dom.on(dom.qs("[data-ks-src-toggle]"), "click", function () {
        var panel = dom.qs("[data-ks-src-panel]");
        if (panel) panel.toggleAttribute("hidden");
      });

      forms.bind(
        "[data-ks-source-form]",
        function (d) {
          return {
            name: (d.name || "").trim(),
            base_url: (d.base_url || "").trim(),
            source_type: d.source_type || "public_dataset",
            category: d.category || "equipment_images",
            organization: (d.organization || "").trim(),
            state: (d.state || "").trim(),
            robots_url: (d.robots_url || "").trim(),
            terms_url: (d.terms_url || "").trim(),
            license_url: (d.license_url || "").trim(),
            attribution_text: (d.attribution_text || "").trim(),
            rate_limit_per_minute: Number(d.rate_limit_per_minute) || 10,
            request_delay_seconds: Number(d.request_delay_seconds) || 0,
            allows_images: !!d.allows_images,
            allows_documents: !!d.allows_documents,
            allows_structured_data: !!d.allows_structured_data,
            notes: (d.notes || "").trim()
          };
        },
        function (body) {
          return api.post(BASE + "/sources", body).then(function (created) {
            ui.ok("Source registered. It is pending until approved in the admin.");
            sourceForm.reset();
            loadSources();
            return created;
          });
        }
      );
    }

    // ------------------------------------------------- collect / import

    var collectForm = dom.qs("[data-ks-collect-form]");
    if (collectForm) {
      dom.on(dom.qs("#col-mode"), "change", syncCollectMode);
      syncCollectMode();

      function syncCollectMode() {
        var mode = (dom.qs("#col-mode") || {}).value;
        dom.qsa("[data-ks-when]").forEach(function (el) {
          if (el.dataset.ksWhen === mode) {
            el.removeAttribute("hidden");
          } else {
            el.setAttribute("hidden", "hidden");
          }
        });
      }

      dom.on(collectForm, "submit", function (ev) {
        ev.preventDefault();
        if (!forms.validate(collectForm)) return;

        var sourceId = (dom.qs('[name="source_id"]', collectForm) || {}).value;
        if (!sourceId) {
          ui.error("No approved source is available to collect from.");
          return;
        }
        var mode = (dom.qs("#col-mode") || {}).value;
        var runId = (dom.qs("#col-run") || {}).value || "";
        var maxImages = (dom.qs("#col-max") || {}).value || "";
        var executeEl = dom.qs('[name="execute"]', collectForm);
        var execute = !!(executeEl && executeEl.checked);

        var body;
        var url;
        if (mode === "manual-import") {
          url = BASE + "/manual-import";
          body = {
            source_id: sourceId,
            path: ((dom.qs("#col-path") || {}).value || "").trim(),
            label_hint: runId
          };
        } else {
          url = BASE + "/sources/" + encodeURIComponent(sourceId) + "/collect";
          var urls = ((dom.qs("#col-urls") || {}).value || "")
            .split(/\r?\n/)
            .map(function (l) { return l.trim(); })
            .filter(Boolean);
          body = {
            image_urls: urls,
            execute: execute,
            label_hint: runId
          };
          if (maxImages) body.max_images = Number(maxImages);
        }

        var restore = ui.busy(dom.qs('[type="submit"]', collectForm), true, "Running…");
        dom.set(collectOut, "");
        api
          .post(url, body)
          .then(function (report) {
            restore();
            dom.set(
              collectOut,
              '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">📦</span> ' +
                (report.dry_run === true ? "Dry run completed — nothing was downloaded." : "Completed.") +
                "</div>" +
                render.datalist(
                  {
                    Requested: report.requested === undefined ? "—" : report.requested,
                    Imported: report.imported === undefined ? "—" : report.imported,
                    Downloaded: report.downloaded === undefined ? "—" : report.downloaded,
                    Valid: report.valid === undefined ? "—" : report.valid,
                    Invalid: report.invalid,
                    Duplicates: report.duplicates,
                    Blocked: report.blocked === undefined ? "—" : report.blocked,
                    "Artifacts created": (report.artifacts || []).length,
                    Failures: (report.failures || []).length
                  },
                  { columns: 2 }
                ) +
                ((report.failures || []).length
                  ? '<div class="ks-alert ks-alert-warn ks-mt-4"><span aria-hidden="true">⚠</span><div>' +
                    (report.failures || []).map(dom.esc).join("<br>") +
                    "</div></div>"
                  : "") +
                "</div>"
            );
            loadSources();
          })
          .catch(function (err) {
            restore();
            fail(collectOut, err);
          });
      });
    }

    // ------------------------------------------------------- review queue

    function loadQueue() {
      if (!queueHost) return;
      dom.set(queueHost, ui.skeleton(3, true));
      var query = {};
      dom.qsa("[data-ks-queue-filter]").forEach(function (el) {
        if (el.value) query[el.dataset.ksQueueFilter] = el.value;
      });

      api
        .get(BASE + "/review-queue", query)
        .then(function (rows) {
          var items = asRows(rows);
          dom.set(
            queueHost,
            items.length
              ? table(
                  ["Target", "Action", "Risk", "Validation", "Decision", "Actions"],
                  items.map(function (q) {
                    var v = q.validation_result || {};
                    return (
                      "<tr><td>" + dom.esc(q.proposed_target_model || "—") + "</td>" +
                      "<td>" + dom.esc(fmt.label(q.proposed_action)) + "</td>" +
                      "<td>" + badge(q.risk_level) + "</td>" +
                      "<td>" + (v.ok ? "passed" : "failed") +
                      ((v.errors || []).length
                        ? '<br><span class="ks-tiny ks-muted">' + dom.esc((v.errors || []).join("; ")) + "</span>"
                        : "") +
                      "</td>" +
                      "<td>" + badge(q.decision) +
                      (q.decided_at ? '<br><span class="ks-tiny ks-muted">' + when(q.decided_at) + "</span>" : "") +
                      "</td>" +
                      '<td>' +
                      '<button class="ks-btn ks-btn-sm" type="button" data-ks-q-approve="' + dom.esc(q.pk) + '">' + KS.t('Approve') + '</button> ' +
                      '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" data-ks-q-reject="' + dom.esc(q.pk) + '">' + KS.t('Reject') + '</button> ' +
                      '<button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" data-ks-q-publish="' + dom.esc(q.pk) + '">' + KS.t('Publish') + '</button>' +
                      "</td></tr>"
                    );
                  })
                )
              : '<p class="ks-muted ks-small">' + KS.t('The review queue is empty for these filters.') + '</p>'
          );

          ["approve", "reject", "publish"].forEach(function (action) {
            dom.on(queueHost, "[data-ks-q-" + action + "]", "click", function () {
              decide(this.getAttribute("data-ks-q-" + action), action);
            });
          });
        })
        .catch(function (err) {
          fail(queueHost, err);
        });
    }

    function decide(queueId, action) {
      var notes = window.prompt("Decision note (optional):", "");
      if (notes === null) return;
      api
        .post(BASE + "/review-queue/" + encodeURIComponent(queueId) + "/" + action, { notes: notes })
        .then(function () {
          ui.ok("Queue item " + action + "d.");
          loadQueue();
        })
        .catch(function (err) {
          ui.error(err.message);
          loadQueue();
        });
    }

    // ------------------------------------------------------------- runs

    function loadRuns() {
      if (!runsHost) return;
      dom.set(runsHost, ui.skeleton(3, true));
      api
        .get(BASE + "/runs")
        .then(function (rows) {
          var items = asRows(rows);
          dom.set(runsHost, renderRunsTable(items, true));
          dom.on(runsHost, "tr[data-run]", "click", function () {
            showRun(this.getAttribute("data-run"));
          });
        })
        .catch(function (err) {
          fail(runsHost, err);
        });
    }

    function showRun(runId) {
      if (!runDetail) return;
      dom.set(runDetail, ui.skeleton(2, true));
      api
        .get(BASE + "/runs/" + encodeURIComponent(runId))
        .then(function (r) {
          dom.set(
            runDetail,
            '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">🏃</span> ' +
              "<strong>" + dom.esc(r.run_id) + "</strong> " + badge(r.status) + "</div>" +
              render.datalist(
                {
                  Source: shortId(r.source),
                  Started: when(r.started_at),
                  Completed: r.completed_at ? when(r.completed_at) : "still running",
                  "Collector version": r.collector_version || "—",
                  "Dry run": r.is_dry_run ? "yes" : "no",
                  "Pages collected": r.pages_collected + " of " + r.pages_attempted,
                  "Records extracted": r.records_extracted,
                  "Documents": r.documents_downloaded,
                  Images: r.images_downloaded,
                  "Duplicates skipped": r.duplicates_skipped,
                  "Validation failures": r.validation_failures,
                  "Blocked items": r.blocked_items,
                  "Report path": r.report_path || "—",
                  Warnings: (r.warnings || []).join("; ") || "—"
                },
                { columns: 2 }
              ) +
              "</div>"
          );
        })
        .catch(function (err) {
          fail(runDetail, err);
        });
    }

    // --------------------------------------------------------- artifacts

    function loadArtifacts() {
      if (!artifactsHost) return;
      dom.set(artifactsHost, ui.skeleton(3, true));
      api
        .get(BASE + "/artifacts")
        .then(function (rows) {
          dom.set(
            artifactsHost,
            table(
              ["Sha256", "Type", "Size", "Validation", "Approved", "Duplicate", "Retrieved", ""],
              asRows(rows).map(function (a) {
                return (
                  '<tr><td><code>' + dom.esc(String(a.sha256 || "").slice(0, 12)) + "</code></td>" +
                  "<td>" + dom.esc(fmt.label(a.artifact_type)) + "</td>" +
                  '<td class="num">' + dom.esc(a.file_size) + "</td>" +
                  "<td>" + badge(a.validation_status) + "</td>" +
                  "<td>" + (a.is_approved ? "yes" : "no") + "</td>" +
                  "<td>" + (a.is_duplicate ? "yes" : "no") + "</td>" +
                  "<td>" + when(a.retrieved_at) + "</td>" +
                  '<td><button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
                  'data-ks-artifact="' + dom.esc(a.pk) + '">' + KS.t('View') + '</button></td></tr>'
                );
              })
            )
          );
          dom.on(artifactsHost, "[data-ks-artifact]", "click", function () {
            showArtifact(this.getAttribute("data-ks-artifact"));
          });
        })
        .catch(function (err) {
          fail(artifactsHost, err);
        });
    }

    function showArtifact(artifactId) {
      if (!artifactDetail) return;
      dom.set(artifactDetail, ui.skeleton(2, true));
      api
        .get(BASE + "/artifacts/" + encodeURIComponent(artifactId))
        .then(function (a) {
          var prov = a.provenance || {};
          dom.set(
            artifactDetail,
            '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">🗂</span> ' +
              "<strong>" + dom.esc(String(a.sha256 || "").slice(0, 16)) + "</strong> " +
              badge(a.validation_status) + "</div>" +
              render.datalist(
                {
                  Type: fmt.label(a.artifact_type),
                  sha256: a.sha256,
                  "Original URL": a.original_url || "—",
                  "Final URL": a.final_url || "—",
                  "Local path": a.local_path || "—",
                  "File size": a.file_size,
                  "Content type": a.content_type || "—",
                  "HTTP status": a.http_status,
                  Retrieved: when(a.retrieved_at),
                  Approved: a.is_approved ? "yes" : "no",
                  Duplicate: a.is_duplicate ? "yes" : "no",
                  Retention: fmt.label(a.retention_status),
                  Attribution: a.attribution || "—"
                },
                { columns: 2 }
              ) +
              sourceBlock(prov.source) +
              render.datalist(
                {
                  "Run id": (prov.run || {}).run_id || "—",
                  "Run status": (prov.run || {}).status || "—",
                  "Run started": (prov.run || {}).started_at ? when(prov.run.started_at) : "—",
                  "Collector version": (prov.run || {}).collector_version || "—"
                },
                { columns: 2 }
              ) +
              "</div>"
          );
        })
        .catch(function (err) {
          fail(artifactDetail, err);
        });
    }

    // ----------------------------------------------------------- records

    function loadRecords() {
      if (!recordsHost) return;
      dom.set(recordsHost, ui.skeleton(3, true));
      var query = {};
      dom.qsa("[data-ks-record-filter]").forEach(function (el) {
        if (el.value) query[el.dataset.ksRecordFilter] = el.value;
      });

      api
        .get(BASE + "/records", query)
        .then(function (rows) {
          dom.set(
            recordsHost,
            table(
              ["Type", "Status", "Confidence", "Source", "Hash", "Retrieved", "Reviewed", ""],
              asRows(rows).map(function (r) {
                return (
                  "<tr><td>" + dom.esc(fmt.label(r.record_type)) + "</td>" +
                  "<td>" + badge(r.verification_status) + "</td>" +
                  "<td>" + dom.esc(r.confidence) + "</td>" +
                  "<td>" + dom.esc(shortId(r.source)) + "</td>" +
                  "<td><code>" + dom.esc(String(r.content_hash || "—").slice(0, 10)) + "</code></td>" +
                  "<td>" + when(r.retrieved_at) + "</td>" +
                  "<td>" + (r.reviewed_at ? when(r.reviewed_at) : "—") + "</td>" +
                  '<td><button class="ks-btn ks-btn-sm ks-btn-secondary" type="button" ' +
                  'data-ks-record="' + dom.esc(r.pk) + '">' + KS.t('View') + '</button></td></tr>'
                );
              })
            )
          );
          dom.on(recordsHost, "[data-ks-record]", "click", function () {
            showRecord(this.getAttribute("data-ks-record"));
          });
        })
        .catch(function (err) {
          fail(recordsHost, err);
        });
    }

    function showRecord(recordId) {
      if (!recordDetail) return;
      dom.set(recordDetail, ui.skeleton(2, true));
      api
        .get(BASE + "/records/" + encodeURIComponent(recordId))
        .then(function (r) {
          var prov = r.provenance || {};
          var data = r.normalized_data_json;
          dom.set(
            recordDetail,
            '<div class="ks-result"><div class="ks-result-head"><span aria-hidden="true">📄</span> ' +
              "<strong>" + dom.esc(fmt.label(r.record_type)) + "</strong> " +
              badge(r.verification_status) + "</div>" +
              render.datalist(
                {
                  Confidence: r.confidence,
                  "Source URL": r.source_url || "—",
                  "Source locator": r.source_locator || "—",
                  "Published date": r.source_published_date || "—",
                  Retrieved: when(r.retrieved_at),
                  "Content hash": r.content_hash || "—",
                  Reviewed: r.reviewed_at ? when(r.reviewed_at) : "—"
                },
                { columns: 2 }
              ) +
              (data
                ? '<details class="ks-mt-4"><summary class="ks-small">' + KS.t('Normalized data') + '</summary>' +
                  "<pre class=\"ks-pre\">" + dom.esc(JSON.stringify(data, null, 2)) + "</pre></details>"
                : "") +
              sourceBlock(prov.source) +
              render.datalist(
                {
                  "Artifact sha256": (prov.artifact || {}).sha256 || "—",
                  "Run id": (prov.run || {}).run_id || "—",
                  "Run status": (prov.run || {}).status || "—"
                },
                { columns: 2 }
              ) +
              "</div>"
          );
        })
        .catch(function (err) {
          fail(recordDetail, err);
        });
    }

    function populateRecordTypes() {
      var sel = dom.qs('[data-ks-record-filter="record_type"]');
      if (!sel || sel.dataset.ksFilled === "1") return;
      sel.dataset.ksFilled = "1";
      var html = sel.innerHTML;
      [
        "scheme", "crop_benchmark", "energy_benchmark", "diesel_benchmark",
        "machinery_benchmark", "equipment_spec", "equipment_image", "catalog_item", "other"
      ].forEach(function (code) {
        html += '<option value="' + dom.esc(code) + '">' + dom.esc(fmt.label(code)) + "</option>";
      });
      sel.innerHTML = html;
    }

    // ------------------------------------------------------------ reports

    function loadDatasetReport() {
      var host = dom.qs("[data-ks-dataset-report]");
      if (!host) return;
      dom.set(host, ui.skeleton(2, true));
      api
        .get(BASE + "/dataset-report")
        .then(function (report) {
          var plan = report.expanded_plan || {};
          dom.set(
            host,
            render.datalist(
              {
                "Eligible reviewed records": report.eligible_reviewed_records,
                "Current total": plan.current_total,
                "Candidate total": plan.candidate_total
              },
              { columns: 2 }
            ) +
              '<div class="ks-table-wrap ks-mt-4"><table class="ks-table"><thead><tr>' +
              "<th>" + KS.t("Class") + "</th><th>" + KS.t("Target") + "</th><th>" + KS.t("Current") + "</th><th>" + KS.t("Approved candidates") + "</th><th>" + KS.t("Shortfall") + "</th>" +
              "</tr></thead><tbody>" +
              (plan.rows || [])
                .map(function (row) {
                  return (
                    "<tr><td>" + dom.esc(row.label) + "</td>" +
                    '<td class="num">' + dom.esc(row.target) + "</td>" +
                    '<td class="num">' + dom.esc(row.current) + "</td>" +
                    '<td class="num">' + dom.esc(row.approved_source_candidates_in_review) + "</td>" +
                    '<td class="num">' + dom.esc(row.shortfall_after_candidates) + "</td></tr>"
                  );
                })
                .join("") +
              "</tbody></table></div>" +
              '<p class="ks-tiny ks-muted ks-mt-4">' + dom.esc(plan.recommendation || "") + "</p>"
          );
        })
        .catch(function (err) {
          fail(host, err);
        });
    }

    var provForm = dom.qs("[data-ks-provenance-form]");
    if (provForm) {
      dom.on(provForm, "submit", function (ev) {
        ev.preventDefault();
        if (!forms.validate(provForm)) return;
        var kind = (dom.qs('[name="kind"]', provForm) || {}).value || "record_id";
        var id = ((dom.qs('[name="target_id"]', provForm) || {}).value || "").trim();
        var out = dom.qs("[data-ks-provenance-out]");
        if (!out) return;
        dom.set(out, ui.skeleton(2, true));

        var query = {};
        query[kind] = id;

        api
          .get(BASE + "/provenance-report", query)
          .then(function (p) {
            // The shape differs per ?kind, so render by key rather than guessing.
            if (p.record) return renderRecordProvenance(p);
            if (p.artifact) return renderArtifactProvenance(p);
            if (p.source) return renderSourceHistory(p);
            dom.set(out, '<p class="ks-muted ks-small">' + KS.t('No provenance returned.') + '</p>');
          })
          .catch(function (err) {
            fail(out, err);
          });
      });
    }

    function sourceBlock(s) {
      if (!s) return "";
      return render.datalist(
        {
          Name: s.name,
          Organisation: s.organization || "—",
          "Base URL": s.base_url,
          Type: fmt.label(s.source_type),
          Category: fmt.label(s.category),
          Approval: fmt.label(s.approval_status),
          "Approval reason": s.approval_reason || "—",
          "Approved by": s.approved_by || "—",
          "Approved at": s.approved_at ? when(s.approved_at) : "—",
          robots: s.robots_status,
          Terms: s.terms_status,
          "Collection enabled": s.collection_enabled ? "yes" : "no",
          Licence: s.license_url || "—",
          Attribution: s.attribution_text || "—"
        },
        { columns: 2 }
      );
    }

    function renderSourceHistory(p) {
      return (
        '<div class="ks-result"><h3 class="ks-card-title">' + KS.t('Source history') + '</h3>' +
        sourceBlock(p.source) +
        "<h4 class=\"ks-card-title ks-mt-4\">" + KS.t("Compliance checks") + "</h4>" +
        table(
          ["Run", "Checked", "Decision", "robots allows", "Terms review", "Blocked reason"],
          (p.compliance_checks || []).map(function (c) {
            return (
              "<tr><td>" + dom.esc(c.run_id || "—") + "</td>" +
              "<td>" + when(c.checked_at) + "</td>" +
              "<td>" + badge(c.decision) + "</td>" +
              "<td>" + (c.robots_allows ? "yes" : "no") + "</td>" +
              "<td>" + (c.terms_manual_review ? "yes" : "no") + "</td>" +
              "<td>" + dom.esc(c.blocked_reason || "—") + "</td></tr>"
            );
          })
        ) +
        "<h4 class=\"ks-card-title ks-mt-4\">" + KS.t("Runs") + "</h4>" +
        table(
          ["Run", "Status", "Started", "Pages", "Records", "Duplicates"],
          (p.runs || []).map(function (r) {
            return (
              "<tr><td>" + dom.esc(r.run_id) + "</td>" +
              "<td>" + badge(r.status) + "</td>" +
              "<td>" + when(r.started_at) + "</td>" +
              '<td class="num">' + dom.esc(r.pages) + "</td>" +
              '<td class="num">' + dom.esc(r.records) + "</td>" +
              '<td class="num">' + dom.esc(r.duplicates) + "</td></tr>"
            );
          })
        ) +
        "</div>"
      );
    }

    function renderRecordProvenance(p) {
      var r = p.record || {};
      return (
        '<div class="ks-result"><h3 class="ks-card-title">' + KS.t('Record provenance') + '</h3>' +
        render.datalist(
          {
            "Record id": r.id,
            Type: fmt.label(r.record_type),
            Status: fmt.label(r.status),
            Confidence: r.confidence,
            "Content hash": r.content_hash || "—",
            "Source URL": r.source_url || "—",
            Retrieved: when(r.retrieved_at),
            Reviewed: r.reviewed_at ? when(r.reviewed_at) : "—",
            Reviewer: r.reviewer || "—"
          },
          { columns: 2 }
        ) +
        sourceBlock(p.source) +
        render.datalist(
          {
            "Artifact sha256": (p.artifact || {}).sha256 || "—",
            "Run id": (p.run || {}).run_id || "—",
            "Run status": (p.run || {}).status || "—"
          },
          { columns: 2 }
        ) +
        (p.review_queue
          ? "<h4 class=\"ks-card-title ks-mt-4\">" + KS.t("Review decision") + "</h4>" +
            render.datalist(
              {
                "Target model": p.review_queue.proposed_target_model || "—",
                Action: fmt.label(p.review_queue.proposed_action),
                Risk: fmt.label(p.review_queue.risk_level),
                Decision: fmt.label(p.review_queue.decision),
                "Decided by": p.review_queue.decided_by || "—",
                "Decided at": p.review_queue.decided_at ? when(p.review_queue.decided_at) : "—",
                Notes: p.review_queue.notes || "—"
              },
              { columns: 2 }
            )
          : "") +
        "</div>"
      );
    }

    function renderArtifactProvenance(p) {
      var a = p.artifact || {};
      return (
        '<div class="ks-result"><h3 class="ks-card-title">' + KS.t('Artifact provenance') + '</h3>' +
        render.datalist(
          {
            "Artifact id": a.id,
            Type: fmt.label(a.type),
            sha256: a.sha256,
            "Original URL": a.original_url || "—",
            "Final URL": a.final_url || "—",
            "Local path": a.local_path || "—",
            "File size": a.file_size,
            "HTTP status": a.http_status,
            Retrieved: when(a.retrieved_at),
            Approved: a.is_approved ? "yes" : "no",
            Duplicate: a.is_duplicate ? "yes" : "no",
            Validation: fmt.label(a.validation_status),
            "Records extracted": a.records_extracted
          },
          { columns: 2 }
        ) +
        sourceBlock(p.source) +
        render.datalist(
          {
            "Run id": (p.run || {}).run_id || "—",
            "Run status": (p.run || {}).status || "—",
            "Run started": (p.run || {}).started_at ? when(p.run.started_at) : "—",
            "Collector version": (p.run || {}).collector_version || "—"
          },
          { columns: 2 }
        ) +
        "</div>"
      );
    }

    // --------------------------------------------------------------- wire

    onEach(dom.qsa("[data-ks-src-filter]"), "", "change", loadSources);
    onEach(dom.qsa("[data-ks-src-filter]"), "", "input", loadSources);
    onEach(dom.qsa("[data-ks-queue-filter]"), "", "change", loadQueue);
    onEach(dom.qsa("[data-ks-record-filter]"), "", "change", loadRecords);

    // Tabs: only fetch a tab's data the first time it is opened, so opening the
    // console does not fire six requests.
    var loaded = { sources: true };
    onEach(dom.qsa("[data-ks-tabs] [data-tab]"), "", "click", function () {
      var tab = this.dataset.tab;
      if (loaded[tab]) return;
      loaded[tab] = true;
      if (tab === "queue") loadQueue();
      if (tab === "runs") loadRuns();
      if (tab === "artifacts") loadArtifacts();
      if (tab === "records") loadRecords();
      if (tab === "reports") loadDatasetReport();
    });

    // Only the landing tab loads eagerly. Other tabs wait for their first click
    // so opening the console does not fire six requests. (The reports tab was
    // previously fetched here and then again on click.)
    populateRecordTypes();
    loadSources();
  };

  /* =====================================================================
     Dispatch
     ===================================================================== */
  document.addEventListener("DOMContentLoaded", function () {
    var name = document.body ? document.body.dataset.ksPage : null;
    if (name && pages[name]) {
      try {
        pages[name]();
      } catch (err) {
        if (window.console) window.console.error("[FarmGrid] page error:", err);
        var host = dom.qs("[data-ks-page-error]") || null;
        if (host) ui.errorState(host, { message: "This page could not load. Please refresh." });
      }
    }
  });
})(window, document);


