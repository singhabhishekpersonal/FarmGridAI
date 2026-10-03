/* ==========================================================================
   FarmGrid AI - Upload & analysis module
   Handles:
     - equipment photo upload (drag/drop + file picker)
     - client-side pre-validation against the server's constraints
     - upload progress
     - running the ML analysis pipeline (classify + OCR + condition)
     - rendering the prediction with its full provenance
     - explicit farmer confirmation of a predicted class
     - expense document upload

   The server re-validates every upload; these checks exist to give the farmer
   fast feedback, not to enforce security.
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

  /* ---------------------------------------------------------------------
     File validation
     --------------------------------------------------------------------- */

  function extensionOf(name) {
    var i = String(name || "").lastIndexOf(".");
    return i === -1 ? "" : String(name).slice(i).toLowerCase();
  }

  function validateImageFile(file) {
    if (!file) return "No file selected.";
    if (KS.ALLOWED_IMAGE_EXT.indexOf(extensionOf(file.name)) === -1) {
      return "Unsupported file type. Use JPG, PNG or WEBP.";
    }
    if (file.size > KS.MAX_IMAGE_BYTES) {
      return "Image is too large. Maximum " + Math.round(KS.MAX_IMAGE_BYTES / 1048576) + " MB.";
    }
    if (file.size === 0) return "The selected file is empty.";
    return null;
  }

  function validateDocumentFile(file) {
    if (!file) return "No file selected.";
    var allowed = [".pdf", ".jpg", ".jpeg", ".png", ".webp"];
    if (allowed.indexOf(extensionOf(file.name)) === -1) {
      return "Unsupported file type. Use PDF, JPG, PNG or WEBP.";
    }
    if (file.size > KS.MAX_DOC_BYTES) {
      return "File is too large. Maximum " + Math.round(KS.MAX_DOC_BYTES / 1048576) + " MB.";
    }
    if (file.size === 0) return "The selected file is empty.";
    return null;
  }

  /* ---------------------------------------------------------------------
     Generic dropzone wiring
     Gives click, keyboard and drag/drop behaviour plus pre-validation.
     --------------------------------------------------------------------- */
  function wireDropzone(zone, input, onFile, validator) {
    if (!zone || !input) return;

    var hint = dom.qs("[data-ks-dz-hint]", zone);
    var originalHint = hint ? hint.innerHTML : "";

    function showError(message) {
      zone.classList.add("is-invalid");
      if (hint) hint.textContent = message;
    }

    function clearError() {
      zone.classList.remove("is-invalid");
      if (hint) hint.innerHTML = originalHint;
    }

    zone.addEventListener("click", function (e) {
      if (e.target !== input) input.click();
    });

    zone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var err = validator ? validator(file) : validateImageFile(file);
      if (err) {
        showError(err);
        input.value = "";
        return;
      }
      clearError();
      onFile(file);
    });

    ["dragenter", "dragover"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.add("is-dragover");
      });
    });

    ["dragleave", "drop"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.remove("is-dragover");
      });
    });

    zone.addEventListener("drop", function (e) {
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      var err = validator ? validator(file) : validateImageFile(file);
      if (err) {
        showError(err);
        return;
      }
      clearError();
      onFile(file);
    });
  }

  /* ---------------------------------------------------------------------
     Progress bar
     fetch() cannot report upload progress, so we show an indeterminate bar
     that fills to ~90% and completes on response. Honest and simple.
     --------------------------------------------------------------------- */
  function progress(host, pct) {
    if (!host) return;
    dom.set(
      host,
      '<div class="ks-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' +
        Math.round(pct) + '"><div class="ks-progress-bar" style="width:' + pct.toFixed(0) + '%"></div></div>'
    );
  }

  function startProgressTimer(host) {
    var pct = 0;
    progress(host, 4);
    var timer = window.setInterval(function () {
      // Approach 90% asymptotically; never reaches 100 until the server replies.
      pct = pct + (90 - pct) * 0.18;
      progress(host, pct);
    }, 220);
    return function () {
      window.clearInterval(timer);
      progress(host, 100);
    };
  }

  /* ---------------------------------------------------------------------
     Equipment photo upload + ML analysis
     --------------------------------------------------------------------- */
  KS.uploads = KS.uploads || {};

  KS.uploads.initEquipment = function () {
    var zone = dom.qs("[data-ks-dropzone]");
    var input = dom.qs("[data-ks-file]");
    var gallery = dom.qs("[data-ks-gallery]");
    var progressHost = dom.qs("[data-ks-progress]");
    var status = dom.qs("[data-ks-upload-status]");

    if (!zone || !input || !gallery) return;

    var farmId = dom.cfg("farmId", auth.currentFarm());
    var equipId = dom.cfg("equipId", null);
    if (!farmId || !equipId) {
      dom.set(
        status,
        '<div class="ks-alert ks-alert-danger"><span aria-hidden="true">⚠</span><div>' + KS.t('No equipment selected. Go back and open an equipment record first.') + '</div></div>'
      );
      return;
    }

    wireDropzone(zone, input, handleFile, validateImageFile);

    // The visible button is a second, keyboard-reachable way into the same
    // picker - the dropzone is a div, so it needs a real control alongside it.
    var trigger = dom.qs("[data-ks-upload-btn]");
    if (trigger) {
      dom.on(trigger, "click", function () {
        if (trigger.disabled) return;
        input.click();
      });
    }

    function handleFile(file) {
      var form = new FormData();
      form.append("image", file);
      form.append("is_primary", String(gallery.children.length === 0));

      if (status) dom.set(status, "");
      var stop = startProgressTimer(progressHost);
      var restore = ui.busy(dom.qs("[data-ks-upload-btn]"), true, "Uploading…");

      api
        .post("/farms/" + farmId + "/equipment/" + equipId + "/images", form)
        .then(function (result) {
          stop();
          restore();
          var imageId = result.image_id || result.id;
          if (progressHost) window.setTimeout(function () { dom.set(progressHost, ""); }, 700);
          ui.ok("Photo uploaded.");
          addPreview(file, imageId);
          return analyze(imageId);
        })
        .catch(function (err) {
          stop();
          restore();
          if (progressHost) dom.set(progressHost, "");
          ui.error(err.message);
        });
    }

    function addPreview(file, imageId) {
      var url = URL.createObjectURL(file);
      var card = dom.el("div", { class: "ks-upload-preview" });
      card.dataset.imageId = imageId || "";
      card.innerHTML =
        '<img src="' + url + '" alt="Uploaded equipment photo">' +
        '<button type="button" class="ks-upload-remove" aria-label="' + KS.t('Remove photo') + '">✕</button>' +
        '<div class="ks-upload-preview-meta"><span>' + dom.esc(file.name) + "</span>" +
        '<span class="ks-badge ks-badge-ok">' + KS.t('Uploaded') + '</span></div>';

      dom.on(dom.qs(".ks-upload-remove", card), "click", function () {
        URL.revokeObjectURL(url);
        if (card.parentNode) card.parentNode.removeChild(card);
        ui.toast(KS.t("Removed from this device. The stored copy stays on the server."), "info");
      });

      gallery.insertBefore(card, gallery.firstChild);
    }

    function analyze(imageId) {
      var host = dom.qs("[data-ks-analysis]");
      if (!host || !imageId) return;

      dom.set(
        host,
        '<div class="ks-ml-panel"><div class="ks-ml-head"><span class="ks-ml-title">' + KS.t('Analysing photo…') + '</span>' +
          '<span class="ks-badge">' + KS.t('Running model') + '</span></div>' +
          '<div class="ks-ml-body">' + ui.skeleton(4) + "</div></div>"
      );

      api
        .post("/farms/" + farmId + "/equipment/" + equipId + "/images/" + imageId + "/analyze", {})
        .then(function (result) {
          dom.set(host, renderAnalysis(result, imageId));
          bindConfirm(host, imageId);
        })
        .catch(function (err) {
          dom.set(host, '<div class="ks-alert ks-alert-danger"><span aria-hidden="true">⚠</span><div>' +
            "<strong class='ks-alert-title'>" + KS.t("Analysis failed") + "</strong>" + dom.esc(err.message) + "</div></div>");
        });
    }

    /** Render the full classify + OCR + condition result. */
    function renderAnalysis(result, imageId) {
      var p = result.prediction || {};
      var ocr = result.ocr || {};
      var cond = result.condition_assessment || {};

      var conf = parseFloat(p.confidence) || 0;
      var top = p.top_predictions || [];

      // Model provenance: name, version, and whether the real artifact ran.
      var provenance = [];
      provenance.push(["Model", p.model_name || "equipment_classifier"]);
      provenance.push(["Version", p.model_version || "fallback"]);
      provenance.push(["Source", fmt.label(p.source || "fallback")]);
      provenance.push(["Trained model used", p.used_ml ? "Yes" : "No — fallback rules"]);
      if (p.unknown_threshold) provenance.push(["Unknown threshold", fmt.number(p.unknown_threshold, 2)]);
      if (p.input_hash) provenance.push(["Image SHA-256", String(p.input_hash).slice(0, 16) + "…"]);

      var html =
        '<div class="ks-ml-panel">' +
        '<div class="ks-ml-head">' +
          '<span class="ks-ml-title">' + KS.t('🔎 Brand identification') + '</span>' +
          '<div class="ks-cluster">' +
            (p.used_ml
              ? '<span class="ks-badge ks-badge-ok">' + KS.t('CNN model') + '</span>'
              : '<span class="ks-badge ks-badge-warn">' + KS.t('Fallback rules') + '</span>') +
            '<span class="ks-badge">' + dom.esc(fmt.label(p.confidence_label)) + " confidence</span>" +
          "</div>" +
        "</div>" +
        '<div class="ks-ml-body">' +

        '<div class="ks-ml-prediction">' +
          "<div>" +
            '<div class="ks-ml-brand">' + dom.esc(p.predicted_brand || KS.t("Unknown brand")) + "</div>" +
            '<div class="ks-tiny ks-muted">Class: ' + dom.esc(fmt.label(p.predicted_class || "unknown")) + "</div>" +
          "</div>" +
          '<div class="ks-ml-confidence">' +
            '<div class="ks-between ks-mb-3"><span class="ks-tiny ks-muted">' + KS.t('Model confidence') + '</span>' +
            "<strong>" + dom.esc(fmt.confidencePct(conf)) + "</strong></div>" +
            render.meter(conf) +
          "</div>" +
        "</div>" +

        (top.length
          ? '<div class="ks-mt-4"><span class="ks-evidence-title">' + KS.t('All class probabilities') + '</span><div class="ks-probs">' +
            top
              .map(function (t, i) {
                var prob = parseFloat(t.probability) || 0;
                return (
                  '<div class="ks-prob-row" data-top="' + (i === 0 ? "true" : "false") + '">' +
                  '<span class="ks-prob-name">' + dom.esc(fmt.label(t.label)) + "</span>" +
                  '<span class="ks-prob-value">' + dom.esc(fmt.percent(prob * 100, 1)) + "</span>" +
                  '<div class="ks-prob-track"><div class="ks-prob-fill" style="width:' + (prob * 100).toFixed(1) + '%"></div></div>' +
                  "</div>"
                );
              })
              .join("") +
            "</div></div>"
          : "") +

        (ocr && (ocr.brand_candidates || ocr.model_candidates || ocr.raw_text) ? ocrBlock(ocr) : "") +

        (cond.visible_condition_score !== undefined ? conditionBlock(cond) : "") +

        // Mandatory confirmation. A prediction is never treated as fact.
        '<div class="ks-mt-4"><div class="ks-flag"><span class="ks-flag-icon" aria-hidden="true">✓</span><span>' +
        "<strong>" + KS.t("Please confirm this identification.") + "</strong> The model sees a brand logo — it cannot see engine condition, " +
        "fuel mileage, manufacturing year or service history." +
        "</span></div>" +

        '<div class="ks-cluster ks-mt-3">' +
          '<button class="ks-btn ks-btn-sm" data-ks-confirm="' + dom.esc(p.predicted_brand || p.predicted_class) + '">' + KS.t('✓ This is correct') + '</button>' +
          '<button class="ks-btn ks-btn-sm ks-btn-secondary" data-ks-dispute>' + KS.t('✗ That is wrong') + '</button>' +
        "</div></div>" +

        "</div>" +

        '<div class="ks-ml-foot"><dl>' +
        provenance
          .map(function (row) {
            return '<div class="ks-ml-foot-row"><span>' + dom.esc(row[0]) + "</span><span>" + dom.esc(row[1]) + "</span></div>";
          })
          .join("") +
        "</dl>" +
        '<p class="ks-tiny ks-muted ks-mt-3">' + dom.esc(result.platform_note || "") + "</p>" +
        "</div></div>";

      return html;
    }

    function ocrBlock(ocr) {
      var rows = [];
      if (ocr.brand_candidates && ocr.brand_candidates.length) {
        rows.push(["Brand text found", ocr.brand_candidates.join(", ")]);
      }
      if (ocr.model_candidates && ocr.model_candidates.length) {
        rows.push(["Model text found", ocr.model_candidates.join(", ")]);
      }
      if (ocr.confidence !== undefined && ocr.confidence !== null) {
        rows.push(["OCR confidence", fmt.confidencePct(ocr.confidence)]);
      }
      if (ocr.error) rows.push(["OCR note", ocr.error]);
      if (!rows.length && !ocr.raw_text) return "";

      return (
        '<div class="ks-evidence-col ks-mt-4"><span class="ks-evidence-title">' + KS.t('📄 Text read from the image (OCR)') + '</span>' +
        (rows.length
          ? '<ul>' + rows.map(function (r) { return "<li>" + dom.esc(r[0]) + ": <strong>" + dom.esc(r[1]) + "</strong></li>"; }).join("") + "</ul>"
          : "") +
        (ocr.raw_text
          ? '<details class="ks-estimate-notes ks-mt-3"><summary>' + KS.t('Full extracted text') + '</summary>' +
            '<pre class="ks-tiny ks-mono" style="white-space:pre-wrap">' + dom.esc(String(ocr.raw_text).slice(0, 800)) + "</pre></details>"
          : "") +
        "</div>"
      );
    }

    function conditionBlock(cond) {
      var score = parseInt(cond.visible_condition_score, 10);
      var band = String(cond.condition_band || "unknown").toLowerCase();
      var bandBadge = band === "good" ? "ks-badge-ok" : band === "moderate" ? "ks-badge-warn" : "ks-badge-danger";

      return (
        '<div class="ks-evidence-col ks-mt-4"><span class="ks-evidence-title">' + KS.t('🔧 Visible condition (rules-based)') + '</span>' +
        '<div class="ks-cluster ks-mb-3">' +
          '<span class="ks-badge ' + bandBadge + '">' + dom.esc(fmt.label(band)) + "</span>" +
          '<span class="ks-badge">Score ' + dom.esc(score) + "/100</span>" +
          '<span class="ks-badge">' + dom.esc(fmt.label(cond.method)) + "</span>" +
        "</div>" +
        (cond.issue_tags && cond.issue_tags.length
          ? '<ul>' + cond.issue_tags.map(function (t) { return "<li>" + dom.esc(fmt.label(t)) + "</li>"; }).join("") + "</ul>"
          : '<p class="ks-tiny ks-muted">' + KS.t('No age or condition concerns flagged from your records.') + '</p>') +
        '<p class="ks-tiny ks-muted ks-mt-3">' + KS.t('This is derived from the condition and age you recorded, not from a mechanical inspection.') + '</p>' +
        "</div>"
      );
    }

    /**
     * Attach the confirm / dispute handlers to an analysis result.
     *
     * Honesty note: the model output and the photo *are* persisted by
     * POST .../images/{id}/analyze, but there is no endpoint for the farmer's
     * confirmation itself, so it cannot be described as "recorded". The
     * prediction stays on the server; the answer stays in this page. The
     * durable action is correcting the brand/model on the equipment record.
     * Wire the API call here if a confirmation endpoint is ever added.
     */
    function bindConfirm(host, imageId) {
      dom.qsa("[data-ks-confirm]", host).forEach(function (btn) {
        btn.addEventListener("click", function () {
          btn.disabled = true;
          var panel = dom.closest(btn, ".ks-flag");
          if (panel) {
            panel.className = "ks-flag ks-flag-ok";
            panel.innerHTML =
              '<span class="ks-flag-icon" aria-hidden="true">✓</span><span><strong>' + KS.t('Confirmed.') + '</strong> ' +
              "Thanks — the model output is saved with this photo, and your confirmation " +
              "applies for now. To make the correction permanent, update the brand and " +
              "model on the equipment record.</span>";
          }
          ui.ok("Confirmed for this session.");
        });
      });

      dom.qsa("[data-ks-dispute]", host).forEach(function (btn) {
        btn.addEventListener("click", function () {
          btn.disabled = true;
          var panel = dom.closest(btn, ".ks-flag");
          if (panel) {
            panel.className = "ks-flag ks-flag-warn";
            panel.innerHTML =
              '<span class="ks-flag-icon" aria-hidden="true">⚠</span><span>' +
              "<strong>" + KS.t("Noted as a correction.") + "</strong> Please set the correct make and " +
              "model on the equipment record so later estimates use the right one.</span>";
          }
          ui.toast(KS.t("Noted for this session. Update the equipment record to make it stick."), "info");
        });
      });
    }
  };

  /* ---------------------------------------------------------------------
     Expense document upload (bills, receipts)
     --------------------------------------------------------------------- */
  KS.uploads.initDocument = function () {
    var zone = dom.qs("[data-ks-doczone]");
    var input = dom.qs("[data-ks-doc-file]");
    var list = dom.qs("[data-ks-doc-list]");
    var progressHost = dom.qs("[data-ks-doc-progress]");
    var status = dom.qs("[data-ks-doc-status]");

    if (!zone || !input || !list) return;

    var farmId = dom.cfg("farmId", auth.currentFarm());
    if (!farmId) return;

    var selected = null;

    wireDropzone(
      zone,
      input,
      function (file) {
        selected = file;
        dom.set(
          list,
          '<div class="ks-upload-preview"><div class="ks-upload-preview-meta">' +
            "<span>📄 " + dom.esc(file.name) + "</span>" +
            '<span class="ks-badge">' + dom.esc(fmt.number(file.size / 1024)) + " KB</span></div></div>"
        );
        var btn = dom.qs("[data-ks-doc-upload]");
        if (btn) btn.disabled = false;
        if (status) dom.set(status, "");
      },
      validateDocumentFile
    );

    dom.on(document, "[data-ks-doc-upload]", "click", function () {
      if (!selected) {
        ui.error("Choose a file first.");
        return;
      }
      var button = this;
      var restore = ui.busy(button, true, "Uploading…");
      var stop = startProgressTimer(progressHost);

      var form = new FormData();
      form.append("document", selected);
      // The server accepts an optional category so the bill can be filed correctly.
      var category = dom.qs("[data-ks-doc-category]");
      if (category && category.value) form.append("category", category.value);

      api
        .post("/farms/" + farmId + "/expenses/documents", form)
        .then(function (result) {
          stop();
          restore();
          button.disabled = true;
          if (progressHost) window.setTimeout(function () { dom.set(progressHost, ""); }, 700);
          selected = null;
          if (input) input.value = "";
          dom.set(
            list,
            '<div class="ks-upload-preview"><div class="ks-upload-preview-meta">' +
              "<span>📄 " + dom.esc((result && result.original_name) || "Document") + "</span>" +
              '<span class="ks-badge ks-badge-ok">' + KS.t('Stored on server') + '</span></div></div>'
          );
          ui.ok("Document uploaded.");
        })
        .catch(function (err) {
          stop();
          restore();
          if (progressHost) dom.set(progressHost, "");
          ui.error(err.message);
        });
    });
  };

  /* ---------------------------------------------------------------------
     Boot: initialise any uploader present on the page
     --------------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", function () {
    if (dom.qs("[data-ks-dropzone]")) KS.uploads.initEquipment();
    if (dom.qs("[data-ks-doczone]")) KS.uploads.initDocument();
  });
})(window, document);


