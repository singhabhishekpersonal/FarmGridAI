/* ==========================================================================
   FarmGrid AI - Core application JavaScript
   Exposes a single global namespace `KS`:
     KS.api      - fetch wrapper for the /api/v1 envelope + JWT handling
     KS.auth     - token storage, login/logout, session state
     KS.fmt      - INR / area / date / confidence formatters (en-IN locale)
     KS.dom      - DOM helpers, escaping, rendering primitives
     KS.ui       - toasts, empty/loading/error states, confirm dialogs
     KS.forms    - form binding, client validation, submit handling
     KS.estimate - builders for the shared "estimate contract" components

   No build step, no framework, no bundler. Plain ES2018 in one file so the
   pages stay light on low-bandwidth rural connections.
   ========================================================================== */
(function (window, document) {
  "use strict";

  var KS = {};

  /* ---------------------------------------------------------------------
     Constants
     --------------------------------------------------------------------- */
  KS.API_BASE = "/api/v1";
  KS.STORAGE_TOKEN = "khetsathi.access";
  KS.STORAGE_REFRESH = "khetsathi.refresh";
  KS.STORAGE_FARM = "khetsathi.farm";
  KS.STORAGE_LANG = "khetsathi.lang";

  /* Maximum upload sizes mirrored from settings.py. */
  KS.MAX_IMAGE_BYTES = 10 * 1024 * 1024;
  KS.MAX_DOC_BYTES = 10 * 1024 * 1024;
  KS.ALLOWED_IMAGE_EXT = [".jpg", ".jpeg", ".png", ".webp"];

  var INDIAN_DIGITS_FREE = true; // keep ASCII digits; they are more legible at small sizes

  /* ---------------------------------------------------------------------
     Translation

     `window.KS_I18N` is injected by base.html from apps/core/i18n_text.py -
     the same catalog the `{% t %}` template tag uses, so there is exactly one
     source of truth. KS.t() returns the English source unchanged when there is
     no entry, which keeps an untranslated label readable instead of blank.
     --------------------------------------------------------------------- */
  KS.t = function (text) {
    if (text === null || text === undefined) return "";
    var table = window.KS_I18N || {};
    return Object.prototype.hasOwnProperty.call(table, text) ? table[text] : text;
  };

  /* Active language, mirrored from the server-rendered meta tag so the two
     can never disagree. */
  KS.language = function () {
    var meta = document.querySelector('meta[name="ks-lang"]');
    return (meta && meta.content) || "en";
  };

  /* ---------------------------------------------------------------------
     Small utilities
     --------------------------------------------------------------------- */
  function isNil(v) {
    return v === null || v === undefined || v === "";
  }

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait || 250);
    };
  }

  KS.util = { isNil: isNil, clamp: clamp, debounce: debounce };

  /* ---------------------------------------------------------------------
     KS.dom - DOM helpers
     --------------------------------------------------------------------- */
  var dom = {};

  /**
   * Escape untrusted text before it reaches innerHTML. Every dynamic value
   * rendered by this app passes through here (or through KS.dom.text).
   */
  dom.esc = function (value) {
    if (isNil(value)) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  dom.el = function (tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) {
          node.setAttribute(k, attrs[k]);
        }
      });
    }
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  };

  dom.qs = function (sel, root) {
    return (root || document).querySelector(sel);
  };

  dom.qsa = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  /**
   * Event binding with optional delegation. Accepts any of these forms:
   *   dom.on(node, "click", handler, opts)          - direct binding
   *   dom.on("#sel", "click", handler, opts)        - resolves #sel first
   *   dom.on(scope, "click", "[data-x]", handler)   - delegated, event first
   *   dom.on(scope, "[data-x]", "click", handler)   - delegated, selector first
   * Delegated handlers run with `this` bound to the matched element, which
   * keeps callers such as `dom.on(document, "[data-ks-doc-upload]", ...)`
   * able to use `this.disabled = true` inside the callback.
   */
  var DOM_EVENTS = {
    click: 1, dblclick: 1, contextmenu: 1, mousedown: 1, mouseup: 1, mousemove: 1,
    mouseenter: 1, mouseleave: 1, mouseover: 1, mouseout: 1, wheel: 1,
    touchstart: 1, touchend: 1, touchmove: 1, touchcancel: 1,
    keydown: 1, keyup: 1, keypress: 1,
    focus: 1, blur: 1, focusin: 1, focusout: 1,
    input: 1, change: 1, submit: 1, reset: 1, select: 1, invalid: 1,
    drag: 1, dragstart: 1, dragend: 1, dragenter: 1, dragover: 1, dragleave: 1, drop: 1,
    load: 1, error: 1, scroll: 1, paste: 1, copy: 1, cut: 1, toggle: 1, close: 1
  };

  function isEventName(value) {
    return typeof value === "string" && DOM_EVENTS[value.toLowerCase()] === 1;
  }

  function matchesSelector(node, selector) {
    if (!node || node.nodeType !== 1) return false;
    var fn = node.matches || node.msMatchesSelector || node.webkitMatchesSelector;
    return fn ? fn.call(node, selector) : false;
  }

  dom.on = function (a, b, c, d, e) {
    var scope = a;
    var selector = null;
    var event = null;
    var handler = null;
    var opts;

    if (isEventName(b) && typeof c === "function") {
      // (target, event, handler, opts)
      event = b;
      handler = c;
      opts = d;
    } else if (isEventName(b) && typeof c === "string") {
      // (scope, event, selector, handler, opts)
      event = b;
      selector = c;
      handler = d;
      opts = e;
    } else if (typeof b === "string" && isEventName(c)) {
      // (scope, selector, event, handler, opts)
      selector = b;
      event = c;
      handler = d;
      opts = e;
    } else {
      return;
    }

    if (typeof scope === "string") scope = dom.qs(scope);
    if (!scope || !handler) return;

    if (!selector) {
      scope.addEventListener(event, handler, opts);
      return;
    }

    scope.addEventListener(
      event,
      function (ev) {
        var node = ev.target;
        while (node && node !== scope) {
          if (matchesSelector(node, selector)) {
            handler.call(node, ev);
            return;
          }
          node = node.parentNode;
        }
      },
      opts
    );
  };

  /** Nearest ancestor (inclusive) of `node` matching `selector`, or null. */
  dom.closest = function (node, selector) {
    while (node && node.nodeType === 1) {
      if (matchesSelector(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
  };

  /**
   * Is this input actually reachable by the farmer right now?
   *
   * Multi-panel forms (e.g. the expense entry page hides five of six panels
   * behind a type picker) reuse the same field names across panels. Reading or
   * validating hidden fields would either pick up the wrong panel's values or
   * block submit on fields the farmer cannot even see, so every form helper
   * filters through this.
   */
  dom.isVisible = function (input) {
    if (!input || input.disabled) return false;
    if (dom.closest(input, "[hidden]")) return false;
    if (input.type === "radio" && !input.checked) return false;
    // getClientRects() is empty for display:none subtrees; guard for old engines.
    if (typeof input.getClientRects === "function" && input.getClientRects().length === 0) {
      // An element inside a <details> that is not open reports zero rects, but
      // so does one inside a closed panel. Only treat it as hidden when it is
      // also detached from the layout by an explicit style.
      var style = window.getComputedStyle ? window.getComputedStyle(input) : null;
      if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    }
    return true;
  };

  /** Replace a container's contents with an HTML string. */
  dom.set = function (target, html) {
    var node = typeof target === "string" ? dom.qs(target) : target;
    if (node) node.innerHTML = html;
    return node;
  };

  /** Read a Django data-* attribute off the <body> or a script tag. */
  dom.cfg = function (key, fallback) {
    // Templates render data-ks-farm-id / data-ks-equip-id, while callers pass
    // camelCase (dom.cfg("farmId")). Normalise so both spellings resolve to the
    // same attribute - a silent mismatch here just yields a null farm id.
    var attr = "data-ks-" + String(key).replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
    var node = dom.qs("[" + attr + "]");
    if (!node) return fallback;
    return node.getAttribute(attr);
  };

  dom.cfgBool = function (key, fallback) {
    var raw = dom.cfg(key, null);
    if (raw === null) return fallback;
    return raw === "true" || raw === "1";
  };

  dom.cfgInt = function (key, fallback) {
    var raw = dom.cfg(key, null);
    if (raw === null) return fallback;
    var n = parseInt(raw, 10);
    return isNaN(n) ? fallback : n;
  };

  KS.dom = dom;

  /* ---------------------------------------------------------------------
     KS.fmt - formatters (Indian locale)
     --------------------------------------------------------------------- */
  var fmt = {};

  var inrNumber = new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 0,
  });

  var inrNumber2 = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  var num2 = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  /** 1234567 -> "Rs 12,34,567" (Indian digit grouping). */
  fmt.inr = function (value) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    return "₹" + inrNumber.format(Math.round(parseFloat(value)));
  };

  /** Same, but keeps paise - used for tariffs and per-unit rates. */
  fmt.inrExact = function (value) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    return "₹" + inrNumber2.format(parseFloat(value));
  };

  /** Full precision with the rupee sign, for computed ratios. */
  fmt.amount = function (value) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    return "₹" + num2.format(parseFloat(value));
  };

  /** Plain number with up to 2 decimals. */
  fmt.number = function (value, digits) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    var n = parseFloat(value);
    if (typeof digits === "number") {
      return new Intl.NumberFormat("en-IN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(n);
    }
    return num2.format(n);
  };

  /** Compact currency for tight stat tiles: 1250000 -> "₹12.5L". */
  fmt.inrShort = function (value) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    var n = Math.abs(parseFloat(value));
    var sign = parseFloat(value) < 0 ? "-" : "";
    if (n >= 10000000) return sign + "₹" + (n / 10000000).toFixed(2) + "Cr";
    if (n >= 100000) return sign + "₹" + (n / 100000).toFixed(2) + "L";
    if (n >= 1000) return sign + "₹" + (n / 1000).toFixed(1) + "K";
    return sign + "₹" + inrNumber.format(n);
  };

  /** Land area with unit suffix; hectares are the canonical internal unit. */
  fmt.area = function (hectares, unit) {
    if (isNil(hectares) || isNaN(parseFloat(hectares))) return "—";
    var n = parseFloat(hectares);
    var u = unit || "hectare";
    return num2.format(n) + " " + (n === 1 ? u : u + "s");
  };

  fmt.hectares = function (hectares) {
    if (isNil(hectares) || isNaN(parseFloat(hectares))) return "—";
    return num2.format(parseFloat(hectares)) + " ha";
  };

  fmt.acres = function (acres) {
    if (isNil(acres) || isNaN(parseFloat(acres))) return "—";
    return num2.format(parseFloat(acres)) + " ac";
  };

  /** 12.5 -> "12.5%" */
  fmt.percent = function (value, digits) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    var d = typeof digits === "number" ? digits : 1;
    return parseFloat(value).toFixed(d) + "%";
  };

  /** 0.873 -> "87.3%" (confidence comes back as a 0-1 float). */
  fmt.confidencePct = function (value) {
    if (isNil(value) || isNaN(parseFloat(value))) return "—";
    var n = parseFloat(value);
    if (n > 1) n = n / 100;
    return (n * 100).toFixed(1) + "%";
  };

  /** ISO date -> "12 Mar 2026" */
  fmt.date = function (value) {
    if (isNil(value)) return "—";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  };

  fmt.month = function (value) {
    if (isNil(value)) return "—";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  };

  fmt.dateTime = function (value) {
    if (isNil(value)) return "—";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  /** "2026-03-12" for <input type="date"> */
  fmt.inputDate = function (value) {
    if (isNil(value)) return "";
    var d = new Date(value);
    if (isNaN(d.getTime())) return "";
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  };

  /** Title-case an API enum/choice: "electricity_bill" -> "Electricity bill". */
  fmt.label = function (value) {
    if (isNil(value)) return "—";
    var s = String(value).replace(/[_-]+/g, " ").trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
  };

  /** Relative time: "3 days ago". */
  fmt.ago = function (value) {
    if (isNil(value)) return "—";
    var d = new Date(value).getTime();
    if (isNaN(d)) return "—";
    var secs = Math.floor((Date.now() - d) / 1000);
    if (secs < 60) return "just now";
    if (secs < 3600) return Math.floor(secs / 60) + " min ago";
    if (secs < 86400) return Math.floor(secs / 3600) + " hr ago";
    if (secs < 2592000) return Math.floor(secs / 86400) + " d ago";
    return fmt.date(value);
  };

  KS.fmt = fmt;

  /* ---------------------------------------------------------------------
     KS.auth - JWT session management
     Tokens live in localStorage. On 401 we attempt one silent refresh
     before giving up and redirecting to the login page.
     --------------------------------------------------------------------- */
  var auth = {};

  auth.token = function () {
    try {
      return window.localStorage.getItem(KS.STORAGE_TOKEN) || "";
    } catch (e) {
      return "";
    }
  };

  auth.refreshToken = function () {
    try {
      return window.localStorage.getItem(KS.STORAGE_REFRESH) || "";
    } catch (e) {
      return "";
    }
  };

  auth.setSession = function (access, refresh) {
    try {
      if (access) window.localStorage.setItem(KS.STORAGE_TOKEN, access);
      if (refresh) window.localStorage.setItem(KS.STORAGE_REFRESH, refresh);
    } catch (e) {
      /* storage blocked (private mode) - session stays in-memory only */
    }
    document.dispatchEvent(new CustomEvent("ks:auth", { detail: { authenticated: true } }));
  };

  auth.clear = function () {
    try {
      window.localStorage.removeItem(KS.STORAGE_TOKEN);
      window.localStorage.removeItem(KS.STORAGE_REFRESH);
      window.localStorage.removeItem(KS.STORAGE_FARM);
    } catch (e) {
      /* noop */
    }
    document.dispatchEvent(new CustomEvent("ks:auth", { detail: { authenticated: false } }));
  };

  auth.isAuthenticated = function () {
    return !!auth.token();
  };

  /** Remember the farm the farmer is currently working in. */
  auth.currentFarm = function () {
    try {
      return window.localStorage.getItem(KS.STORAGE_FARM) || "";
    } catch (e) {
      return "";
    }
  };

  auth.setCurrentFarm = function (id) {
    try {
      if (id) window.localStorage.setItem(KS.STORAGE_FARM, id);
      else window.localStorage.removeItem(KS.STORAGE_FARM);
    } catch (e) {
      /* noop */
    }
  };

  /* The server is authoritative for the active language: it chose the cookie,
     decided which copy was rendered, and injected the catalog that KS.t()
     reads. localStorage is only a mirror, kept so the control can show the
     right pressed state before the first paint - it is rewritten from the
     server value on every page load, so a stale entry left by an older visit
     can never disagree with what the farmer is actually looking at. */
  auth.language = function () {
    var fromServer = KS.language();
    try {
      if (window.localStorage.getItem(KS.STORAGE_LANG) !== fromServer) {
        window.localStorage.setItem(KS.STORAGE_LANG, fromServer);
      }
    } catch (e) {
      /* Private mode: the mirror is a nicety, the server still decides. */
    }
    return fromServer;
  };

  auth.setLanguage = function (code) {
    try {
      window.localStorage.setItem(KS.STORAGE_LANG, code);
    } catch (e) {
      /* noop */
    }
  };

  /** Decode a JWT payload without verifying it (display purposes only). */
  auth.claims = function () {
    var token = auth.token();
    if (!token) return {};
    var parts = token.split(".");
    if (parts.length < 2) return {};
    try {
      var b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      var pad = b64.length % 4;
      if (pad) b64 += new Array(5 - pad).join("=");
      var json = decodeURIComponent(
        atob(b64)
          .split("")
          .map(function (c) {
            return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
          })
          .join("")
      );
      return JSON.parse(json);
    } catch (e) {
      return {};
    }
  };

  /** Display name from the JWT, falling back to the username claim. */
  auth.displayName = function () {
    var claims = auth.claims();
    return claims.name || claims.first_name || claims.username || "Farmer";
  };

  auth.login = function (username, password) {
    return api.raw("POST", "/auth/login/", { username: username, password: password }, { skipAuth: true }).then(function (payload) {
      var data = payload && payload.data ? payload.data : payload;
      auth.setSession(data.access, data.refresh);
      return data;
    });
  };

    auth.register = function (payload) {
      return api.raw("POST", "/auth/register/", payload, { skipAuth: true }).then(function (body) {
        var data = body && body.data ? body.data : body;
        // RegisterView nests the token pair under "tokens" alongside user + profile.
        var tokens = (data && data.tokens) || data || {};
        if (tokens.access) auth.setSession(tokens.access, tokens.refresh);
        return data;
      });
    };

  /* Sign out in a single navigation to the server-side logout route.

     The previous version POSTed /auth/logout/ and then redirected. That is two
     steps, and it raced: if the POST failed (CSRF, offline) the redirect still
     happened with the Django session still alive, so /login/ redirected the
     visitor to /dashboard/, whose auth guard sent them back to /login/ - a
     visible three-step flicker. Letting the server close the session in the
     response that performs the redirect removes the race, and also drops the
     dead POST round-trip. Tokens are cleared here because only the client has
     them; /api/v1/auth/logout/ remains for non-browser clients. */
  auth.logout = function () {
    auth.clear();
    window.location.href = "/logout/";
  };

  /* Bind every sign-out control inside `root` (defaults to the whole document).

     Exposed for the same reason as bindLanguageSwitch: the dashboard injects a
     profile panel containing its own button, and two independent bindings mean
     one click fires auth.logout twice. The dataset guard makes the second pass
     a no-op. */
  auth.bindLogout = function (root) {
    dom.qsa("[data-ks-logout]", root).forEach(function (btn) {
      if (btn.dataset.ksLogoutBound === "1") return;
      btn.dataset.ksLogoutBound = "1";
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        auth.logout();
      });
    });
  };

  /* Bind the language buttons inside `root` (defaults to the whole document).

     Exposed so markup injected later - the dashboard profile panel builds its
     own card - can reuse this instead of re-implementing it. A second copy is
     how the profile panel ended up switching the cookie without ever asking
     the server to re-render the page. */
  auth.bindLanguageSwitch = function (root) {
    dom.qsa("[data-ks-lang]", root).forEach(function (btn) {
      if (btn.dataset.ksLangBound === "1") return; // never bind the same button twice
      btn.dataset.ksLangBound = "1";

      btn.setAttribute("aria-pressed", btn.dataset.ksLang === auth.language() ? "true" : "false");
      btn.addEventListener("click", function () {
        var code = btn.dataset.ksLang;
        if (code === auth.language()) return; // already active, no reload needed

        auth.setLanguage(code);
        dom.qsa("[data-ks-lang]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });

        /* Nearly all page copy is rendered by Django, so flipping a class or a
           dictionary cannot rewrite it. Hand off to the server, which sets the
           language cookie, records the preference and re-renders the page in the
           new language. `next` keeps the farmer's place instead of dumping them
           on the dashboard. One navigation does all of it - a fetch first would
           only add a round trip that the reload immediately discards. */
        location.href =
          "/lang/" + encodeURIComponent(code) + "/?next=" + encodeURIComponent(location.pathname + location.search);
      });
    });
  };

  KS.auth = auth;

  /* ---------------------------------------------------------------------
     KS.api - fetch wrapper
     Every backend endpoint answers with the standard envelope:
       { success, message, data, meta: { request_id, timestamp, version }, errors }
     This wrapper unwraps `data` and converts `errors` into a thrown ApiError
     so calling code can rely on a single happy path.
     --------------------------------------------------------------------- */
  function ApiError(message, errors, status, requestId) {
    this.name = "ApiError";
    this.message = message || KS.t("Request failed.");
    this.errors = errors || [];
    this.status = status || 0;
    this.requestId = requestId || "";
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /** First field message, for inline form errors. */
  ApiError.prototype.fieldMessage = function (field) {
    var i;
    for (i = 0; i < this.errors.length; i += 1) {
      if (!field || this.errors[i].field === field) return this.errors[i].message;
    }
    return this.message;
  };

  KS.ApiError = ApiError;

  var api = {};
  var refreshing = null;

  function buildUrl(path, query) {
    var url = path.indexOf("http") === 0 ? path : KS.API_BASE + path;
    if (query && typeof query === "object") {
      var parts = [];
      Object.keys(query).forEach(function (k) {
        var v = query[k];
        if (isNil(v) || v === "") return;
        parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
      });
      if (parts.length) url += (url.indexOf("?") === -1 ? "?" : "&") + parts.join("&");
    }
    return url;
  }

  function parseBody(response) {
    var type = response.headers.get("Content-Type") || "";
    if (type.indexOf("application/json") !== -1) {
      return response.json().catch(function () {
        return {};
      });
    }
    return response.text().then(function (t) {
      return { message: t };
    });
  }

  function toError(body, response) {
    var meta = (body && body.meta) || {};
    return new ApiError(
      (body && body.message) || KS.t("Request failed."),
      (body && body.errors) || [],
      response.status,
      meta.request_id
    );
  }

  /** Attempt a single silent token refresh. Concurrent callers share it. */
  function attemptRefresh() {
    var refresh = auth.refreshToken();
    if (!refresh) return Promise.reject(new ApiError("Session expired.", [], 401, ""));

    if (!refreshing) {
      refreshing = fetch(buildUrl("/auth/login/refresh/"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: refresh }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (body) {
          var data = body && body.data ? body.data : body;
          if (!data || !data.access) throw new ApiError("Session expired.", [], 401, "");
          auth.setSession(data.access, data.refresh);
          refreshing = null;
          return data.access;
        })
        .catch(function (err) {
          refreshing = null;
          auth.clear();
          throw err;
        });
    }
    return refreshing;
  }

  /**
   * The session cookie authenticates us, and DRF's SessionAuthentication
   * rejects unsafe methods without a CSRF token. The login/register pages are
   * served with @ensure_csrf_cookie, so read that cookie and echo it back.
   *
   * The cookie is not the only source. base.html also renders
   * <meta name="csrf-token" content="{{ csrf_token }}">, and Django accepts
   * that masked token in the header. Falling back to it matters because an
   * absent cookie used to send the header as an empty string, which the server
   * rejects outright with "CSRF token missing" - and a cookie can legitimately
   * be gone (cleared, expired, or blocked) while the page still carries a
   * valid token.
   */
  var UNSAFE_METHODS = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    /* No cookie - fall back to the token base.html rendered into the page. */
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  /**
   * Core request. Returns the unwrapped `data` payload.
   * opts: { query, body, skipAuth, skipRefresh, skipErrors, raw }
   */
  function request(method, path, options) {
    var opts = options || {};
    var init = {
      method: method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };

    if (!opts.skipAuth && auth.isAuthenticated()) {
      init.headers.Authorization = "Bearer " + auth.token();
    }

    var payload = opts.body;
    if (payload instanceof FormData) {
      init.body = payload; // let the browser set the multipart boundary
    } else if (payload !== undefined && payload !== null) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(payload);
    }

    /* CSRF is required for every unsafe method, whatever skipAuth says.
       skipAuth only suppresses the Authorization header, and login/register
       are both called with skipAuth: true - so gating this on !skipAuth meant
       the sign-in POST carried no X-CSRFToken at all and the server rejected
       it with "CSRF token missing" as soon as a session cookie was present. */
    if (UNSAFE_METHODS[method]) {
      var token = csrfToken();
      if (token) init.headers["X-CSRFToken"] = token;
    }

    return fetch(buildUrl(path, opts.query), init)
      .then(function (response) {
        return parseBody(response).then(function (body) {
          if (response.ok) {
            if (opts.raw) return body;
            return body && body.data !== undefined ? body.data : body;
          }

          // 401 with a stored refresh token: retry once, silently.
          if (response.status === 401 && !opts.skipRefresh && auth.refreshToken()) {
            return attemptRefresh().then(function () {
              var retryOpts = {};
              Object.keys(opts).forEach(function (k) {
                retryOpts[k] = opts[k];
              });
              retryOpts.skipRefresh = true;
              return request(method, path, retryOpts);
            });
          }

          if (opts.skipErrors) return null;
          throw toError(body, response);
        });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        // Network failure, offline, DNS, CORS - all land here.
        throw new ApiError(
          "Cannot reach the server. Check your connection and try again.",
          [{ field: null, message: String(err && err.message ? err.message : err) }],
          0,
          ""
        );
      });
  }

  /** Shallow-copy opts so callers can safely reuse a single options object. */
  function withOpts(opts, extra) {
    var o = {};
    Object.keys(opts || {}).forEach(function (k) {
      o[k] = opts[k];
    });
    Object.keys(extra || {}).forEach(function (k) {
      o[k] = extra[k];
    });
    return o;
  }

  /**
   * Escape hatch for verbs without a shorthand, and for the endpoints that
   * answer with a body outside the standard {success, data} envelope.
   *
   * Signature is (method, path, body, opts) - NOT request()'s (method, path,
   * options). Aliasing request() directly dropped every body on the floor, so
   * login/register/logout silently POSTed an empty payload.
   */
  api.raw = function (method, path, body, opts) {
    return request(method, path, withOpts(opts, { body: body }));
  };

  api.get = function (path, query, opts) {
    return request("GET", path, withOpts(opts, { query: query }));
  };

  api.post = function (path, body, opts) {
    return request("POST", path, withOpts(opts, { body: body }));
  };

  api.patch = function (path, body, opts) {
    return request("PATCH", path, withOpts(opts, { body: body }));
  };

  api.put = function (path, body, opts) {
    return request("PUT", path, withOpts(opts, { body: body }));
  };

  api.del = function (path, opts) {
    return request("DELETE", path, opts || {});
  };

  /** Convenience wrappers for the most-used endpoints. */
  api.me = function () {
    return api.get("/auth/profile/");
  };
  api.farms = function (query) {
    return api.get("/farms/", query);
  };
  api.farm = function (id) {
    // No trailing slash: farms/urls.py declares "<uuid:farm_id>" without one,
    // so the slash only bought an extra 301 on every farm load.
    return api.get("/farms/" + id);
  };
  api.farmSummary = function (id) {
    return api.get("/farms/" + id + "/summary");
  };
  api.equipment = function (farmId) {
    return api.get("/farms/" + farmId + "/equipment");
  };
  api.expenseSummary = function (farmId) {
    return api.get("/farms/" + farmId + "/expenses/summary");
  };
  api.recommendations = function (farmId) {
    return api.get("/farms/" + farmId + "/recommendations");
  };
  api.subsidyMatches = function (farmId) {
    return api.get("/farms/" + farmId + "/subsidies/recommendations");
  };

  /** Fetch the model registry status for the system status strip. */
  api.modelStatus = function () {
    return api.get("/system/model-status", null, { skipAuth: true });
  };

  api.capabilities = function () {
    return api.get("/system/capabilities", null, { skipAuth: true });
  };

  api.health = function () {
    return api.get("/health", null, { skipAuth: true, skipErrors: true });
  };

  KS.api = api;

  /* ---------------------------------------------------------------------
     KS.ui - toasts, states, buttons
     --------------------------------------------------------------------- */
  var ui = {};

  function toastHost() {
    var host = dom.qs(".ks-toasts");
    if (!host) {
      host = dom.el("div", { class: "ks-toasts", role: "status", "aria-live": "polite" });
      document.body.appendChild(host);
    }
    return host;
  }

  ui.toast = function (message, kind, ms) {
    if (isNil(message)) return;
    var node = dom.el("div", { class: "ks-toast ks-toast--" + (kind || "info"), text: String(message) });
    toastHost().appendChild(node);
    window.setTimeout(function () {
      node.style.opacity = "0";
      window.setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, 200);
    }, ms || 4200);
  };

  ui.ok = function (m) { ui.toast(m, "ok"); };
  ui.error = function (m) { ui.toast(m, "error", 6000); };
  ui.warn = function (m) { ui.toast(m, "warn", 5200); };

  /** Toggle a button into its busy state and return a restore function. */
  ui.busy = function (button, isBusy, busyLabel) {
    if (!button) return function () {};
    if (isBusy) {
      button.dataset.ksOriginalText = button.textContent;
      button.dataset.loading = "true";
      button.setAttribute("aria-busy", "true");
      button.disabled = true;
      if (busyLabel) button.textContent = busyLabel;
    } else {
      button.dataset.loading = "false";
      button.removeAttribute("aria-busy");
      button.disabled = false;
      if (button.dataset.ksOriginalText) {
        button.textContent = button.dataset.ksOriginalText;
        delete button.dataset.ksOriginalText;
      }
    }
    return function () { ui.busy(button, false); };
  };

  ui.skeleton = function (rows, titleRow) {
    var html = "";
    if (titleRow !== false) html += '<div class="ks-skeleton ks-skeleton--title"></div>';
    for (var i = 0; i < (rows || 3); i += 1) html += '<div class="ks-skeleton ks-skeleton--text"></div>';
    return html;
  };

  ui.loading = function (target, message) {
    dom.set(
      target,
      '<div class="ks-empty" role="status" aria-live="polite">' +
        '<span class="ks-empty-icon" aria-hidden="true">⏳</span>' +
        "<strong>" + dom.esc(message || "Loading…") + "</strong>" +
        "</div>"
    );
  };

  /**
   * Empty-state markup as a string, for use inside a larger template literal.
   */
  ui.emptyHtml = function (title, hint, action) {
    return (
      '<div class="ks-empty">' +
        '<span class="ks-empty-icon" aria-hidden="true">🌾</span>' +
        '<span class="ks-empty-title">' + dom.esc(title || KS.t("Nothing here yet")) + "</span>" +
        (hint ? "<p>" + dom.esc(hint) + "</p>" : "") +
        (action || "") +
      "</div>"
    );
  };

  /** Render an empty state into a container. Returns the container node. */
  ui.empty = function (target, title, hint, action) {
    return dom.set(target, ui.emptyHtml(title, hint, action));
  };

  /** Render an API error into a container. Includes the request id for support. */
  ui.errorState = function (target, err) {
    var msg = err && err.message ? err.message : "Something went wrong.";
    var rid = err && err.requestId ? err.requestId : "";
    dom.set(
      target,
      '<div class="ks-alert ks-alert-danger" role="alert">' +
        '<span aria-hidden="true">⚠️</span>' +
        "<div><strong class='ks-alert-title'>" + KS.t("Could not load this") + "</strong>" +
        "<div>" + dom.esc(msg) + "</div>" +
        (rid ? "<div class='ks-tiny ks-mt-3'>" + KS.t("Request ID:") + "<code>" + dom.esc(rid) + "</code></div>" : "") +
        "</div></div>"
    );
  };

  /** Wrap a promise: show a busy button, surface errors as a toast. */
  ui.submit = function (form, run) {
    var button = dom.qs('[type="submit"]', form);
    var restore = ui.busy(button, true, "Working…");
    return Promise.resolve()
      .then(run)
      .then(function (result) {
        restore();
        return result;
      })
      .catch(function (err) {
        restore();
        if (err && err instanceof ApiError) {
          if (err.status === 401) {
            auth.clear();
            window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
            return;
          }
          ui.error(err.message);
        } else {
          ui.error("Unexpected error. Please try again.");
        }
        throw err;
      });
  };

  /**
   * Ask for confirmation before a destructive action.
   * Uses window.confirm - dependable and dependency-free.
   */
  ui.confirm = function (message) {
    return window.confirm(message);
  };

  KS.ui = ui;

  /* ---------------------------------------------------------------------
     KS.forms - form binding and validation
     --------------------------------------------------------------------- */
  var forms = {};

  /** Read a form into a plain object. Checkboxes become booleans. */
  forms.read = function (form) {
      var out = {};
      dom.qsa("input, select, textarea", form).forEach(function (input) {
        if (!input.name || input.disabled) return;
        // Skip fields in panels the farmer cannot see, so repeated field names
        // across panels resolve to the visible one.
        if (!dom.isVisible(input)) return;
        if (input.type === "checkbox") {
        out[input.name] = input.checked;
      } else if (input.type === "radio") {
        if (input.checked) out[input.name] = input.value;
      } else if (input.type === "number") {
        if (input.value === "") return;
        var n = parseFloat(input.value);
        if (!isNaN(n)) out[input.name] = n;
      } else if (input.type === "file") {
        /* files are uploaded separately */
      } else {
        out[input.name] = input.value;
      }
    });
    return out;
  };

  /** Read a form, omitting keys the farmer left blank. */
  forms.readFilled = function (form) {
    var all = forms.read(form);
    var out = {};
    Object.keys(all).forEach(function (k) {
      if (!isNil(all[k]) && all[k] !== "") out[k] = all[k];
    });
    return out;
  };

  /** Mark a field invalid and show the message. */
  forms.setError = function (input, message) {
    var field = input && input.closest ? input.closest(".ks-field") : null;
    if (!field) return;
    field.dataset.invalid = "true";
    delete field.dataset.valid;
    var slot = dom.qs(".ks-error", field);
    if (!slot) {
      slot = dom.el("div", { class: "ks-error" });
      slot.innerHTML = '<span class="ks-error-icon" aria-hidden="true">!</span><span></span>';
      field.appendChild(slot);
    }
    dom.qs("span:last-child", slot).textContent = message;
    if (input && input.setAttribute) input.setAttribute("aria-invalid", "true");
  };

  forms.clearError = function (input) {
    var field = input && input.closest ? input.closest(".ks-field") : null;
    if (!field) return;
    delete field.dataset.invalid;
    var slot = dom.qs(".ks-error", field);
    if (slot && slot.parentNode) slot.parentNode.removeChild(slot);
    if (input && input.removeAttribute) input.removeAttribute("aria-invalid");
  };

  /** Map server-side field errors back onto the matching inputs. */
  forms.applyServerErrors = function (form, err) {
      if (!err || !err.errors || !err.errors.length) return;
      var mapped = 0;
      err.errors.forEach(function (item) {
        if (!item.field) return;
        // Prefer a visible match: the same name can exist in several panels.
        var matches = dom.qsa('[name="' + item.field + '"]', form);
        var input = null;
        for (var i = 0; i < matches.length; i += 1) {
          if (dom.isVisible(matches[i])) { input = matches[i]; break; }
        }
        if (!input) input = matches[0] || null;
        if (input) {
          forms.setError(input, item.message);
          mapped += 1;
        }
      });
      if (!mapped) ui.error(err.message);
    };

  /** Show a summary block above the form for any unmapped errors. */
  forms.showErrorSummary = function (target, err) {
    if (!err || !err.errors || !err.errors.length) return;
    var host = typeof target === "string" ? dom.qs(target) : target;
    if (!host) return;
    dom.set(
      host,
      '<div class="ks-error-summary" role="alert">' +
        "<strong>" + KS.t("Please fix the following:") + "</strong><ul>" +
        err.errors
          .map(function (item) {
            return "<li>" + (item.field ? "<code>" + dom.esc(item.field) + "</code>: " : "") + dom.esc(item.message) + "</li>";
          })
          .join("") +
        "</ul></div>"
    );
    host.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  forms.clearSummary = function (target) {
    var host = typeof target === "string" ? dom.qs(target) : target;
    if (host) dom.set(host, "");
  };

  /**
   * Validate against native constraints plus data-validate hints.
   * Returns true when the form may be submitted.
   */
  forms.validate = function (form) {
      var ok = true;
      var firstBad = null;

      dom.qsa("input, select, textarea", form).forEach(function (input) {
        if (input.disabled) return;
        // Never block the farmer on a field inside a hidden panel.
        if (!dom.isVisible(input)) return;
        forms.clearError(input);

      var rule = input.dataset.validate;

      if (input.required && input.type !== "file" && String(input.value).trim() === "") {
        forms.setError(input, "This field is required.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (String(input.value).trim() === "") return;

      if (rule === "phone" && !/^[0-9]{10}$/.test(input.value.trim())) {
        forms.setError(input, "Enter a valid 10-digit Indian mobile number.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (rule === "pincode" && !/^[0-9]{6}$/.test(input.value.trim())) {
        forms.setError(input, "Enter a valid 6-digit pincode.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (rule === "positive" && parseFloat(input.value) <= 0) {
        forms.setError(input, "Enter a value greater than zero.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (rule === "nonnegative" && parseFloat(input.value) < 0) {
        forms.setError(input, "This value cannot be negative.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (input.minLength > 0 && input.value.length < input.minLength) {
        forms.setError(input, "Must be at least " + input.minLength + " characters.");
        ok = false;
        if (!firstBad) firstBad = input;
        return;
      }

      if (input.type === "email" && input.value.indexOf("@") === -1) {
        forms.setError(input, "Enter a valid email address.");
        ok = false;
        if (!firstBad) firstBad = input;
      }
    });

    if (firstBad && firstBad.focus) firstBad.focus();
    return ok;
  };

  /**
   * Wire a form: validate, build the payload, run the submit handler.
   * `builder(formData, formEl)` returns the body to POST.
   * `handler(body, formEl)` returns a promise.
   */
  forms.bind = function (formSelector, builder, handler) {
    var form = typeof formSelector === "string" ? dom.qs(formSelector) : formSelector;
    if (!form) return null;

    var summary = dom.qs("[data-ks-error-summary]", form);

    form.setAttribute("novalidate", "novalidate");

    form.addEventListener(
      "submit",
      function (event) {
        event.preventDefault();
        forms.clearSummary(summary);
        if (!forms.validate(form)) return;

        var data = forms.read(form);
        var body = builder ? builder(data, form) : data;

        ui.submit(form, function () {
          return Promise.resolve(handler(body, form));
        }).catch(function (err) {
          if (err instanceof ApiError) forms.applyServerErrors(form, err);
        });
      },
      false
    );

    // Clear a field's error as soon as the farmer edits it.
    form.addEventListener(
      "input",
      function (event) {
        if (event.target && event.target.name) forms.clearError(event.target);
      },
      false
    );

    return form;
  };

  /* Serialise a form for a URL-encoded POST (used by Django form posts). */
  forms.readUrlEncoded = function (form) {
    var data = forms.readFilled(form);
    return Object.keys(data)
      .map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(data[k]);
      })
      .join("&");
  };

  KS.forms = forms;

  /* ---------------------------------------------------------------------
     KS.estimate - builders for the shared "estimate contract"
     Every analytical value on the platform carries a range, a confidence
     level, assumptions, limitations and confirmation flags. Rendering them
     consistently is what keeps the UI honest.
     --------------------------------------------------------------------- */
  var estimate = {};

  var CONFIDENCE_ORDER = { high: 0, medium: 1, low: 2 };

  estimate.confidenceClass = function (level) {
    var key = String(level || "low").toLowerCase();
    if (key === "high") return "ks-conf-high";
    if (key === "medium") return "ks-conf-medium";
    return "ks-conf-low";
  };

  estimate.badge = function (level) {
    var key = String(level || "low").toLowerCase();
    if (key === "high") return "ks-badge-ok";
    if (key === "medium") return "ks-badge-warn";
    return "ks-badge-danger";
  };

  /**
   * Full estimate block.
   * spec: {
   *   label, expected, minimum, maximum, currency, confidence,
   *   assumptions[], limitations[], requiresConfirmation,
   *   requiresVerification, completeness, formatter
   * }
   */
  estimate.block = function (spec) {
    var s = spec || {};
    var conf = String(s.confidence || "low").toLowerCase();
    var money = fmt.inr;
    var format = s.formatter || (s.currency === "INR" || s.currency === undefined ? money : null);

    var expectedHtml;
    if (isNil(s.expected)) {
      expectedHtml = '<span class="ks-money--muted">' + KS.t('Not enough data') + '</span>';
    } else if (format) {
      expectedHtml = dom.esc(format(s.expected));
    } else {
      expectedHtml = dom.esc(fmt.number(s.expected));
    }

    // Range line: only meaningful when min and max differ from expected.
    var rangeHtml = "";
    if (!isNil(s.minimum) && !isNil(s.maximum) && parseFloat(s.minimum) !== parseFloat(s.maximum)) {
      var lo = format ? format(s.minimum) : fmt.number(s.minimum);
      var hi = format ? format(s.maximum) : fmt.number(s.maximum);
      rangeHtml =
        '<span class="ks-estimate-range">Likely range: ' + dom.esc(lo) + " – " + dom.esc(hi) + "</span>";
    }

    var notes = [];
    (s.assumptions || []).forEach(function (a) {
      notes.push("Assumed: " + a);
    });
    (s.limitations || []).forEach(function (l) {
      notes.push("Limitation: " + l);
    });

    var notesHtml = "";
    if (notes.length) {
      notesHtml =
        '<details class="ks-estimate-notes"><summary>Assumptions &amp; limitations (' +
        notes.length +
        ")</summary><ul class='ks-note-list'>" +
        notes.map(function (n) { return "<li>" + dom.esc(n) + "</li>"; }).join("") +
        "</ul></details>";
    }

    // The mandatory confirmation reminder.
    var flagHtml = "";
    if (s.requiresVerification) {
      flagHtml =
        '<div class="ks-flag"><span class="ks-flag-icon" aria-hidden="true">🔎</span><span>' +
        "Verify scheme amounts and eligibility on the official portal before applying.</span></div>";
    } else if (s.requiresConfirmation !== false) {
      flagHtml =
        '<div class="ks-flag"><span class="ks-flag-icon" aria-hidden="true">✓</span><span>' +
        "This is an estimate. Please confirm it matches your situation before acting.</span></div>";
    }

    var completeness = "";
    if (!isNil(s.completeness)) {
      completeness =
        '<span class="ks-badge" title="' + KS.t('How complete your input data was') + '">Data ' +
        fmt.confidencePct(s.completeness) + "</span>";
    }

    return (
      '<div class="ks-estimate" data-confidence="' + dom.esc(conf) + '">' +
      (s.label ? '<div class="ks-estimate-label">' + dom.esc(s.label) + "</div>" : "") +
      '<div class="ks-estimate-value">' + expectedHtml + "</div>" +
      rangeHtml +
      '<div class="ks-estimate-meta">' +
      '<span class="ks-badge ' + estimate.badge(conf) + '"><span class="ks-dot"></span>' +
      dom.esc(fmt.label(conf)) + " confidence</span>" +
      completeness +
      (s.dataCompleteness !== undefined ? "" : "") +
      "</div>" +
      notesHtml +
      flagHtml +
      "</div>"
    );
  };

  /** Compact inline estimate for use inside stat tiles. */
  estimate.tile = function (label, expected, min, max, confidence, formatter) {
    var format = formatter || fmt.inr;
    var sub = "";
    if (!isNil(min) && !isNil(max) && parseFloat(min) !== parseFloat(max)) {
      sub = '<span class="ks-money-range">' + dom.esc(format(min)) + " – " + dom.esc(format(max)) + "</span>";
    }
    return (
      '<div class="ks-stat">' +
      '<div class="ks-stat-label">' + dom.esc(label) + "</div>" +
      '<div class="ks-stat-value ks-stat-value--sm">' +
      (isNil(expected) ? "—" : dom.esc(format(expected))) +
      "</div>" +
      (sub || "") +
      (confidence
        ? '<div class="ks-stat-foot"><span class="ks-badge ' + estimate.badge(confidence) + '">' +
          dom.esc(fmt.label(confidence)) + "</span></div>"
        : "") +
      "</div>"
    );
  };

  /** Convert a Django/Python dict or list into the estimate spec shape. */
  estimate.fromApi = function (raw) {
    if (!raw || typeof raw !== "object") return null;
    return {
      label: raw.label,
      expected: raw.expected,
      minimum: raw.minimum,
      maximum: raw.maximum,
      currency: raw.currency || "INR",
      confidence: raw.confidence,
      assumptions: raw.assumptions || [],
      limitations: raw.limitations || [],
      requiresConfirmation: raw.requires_farmer_confirmation,
      requiresVerification: raw.requires_official_verification,
      completeness: raw.data_completeness,
      estimateType: raw.estimate_type,
    };
  };

  /**
   * Render an estimate from either a canonical API object or a loose
   * *_min / *_max / *_expected triple used across older endpoints.
   */
  estimate.fromTriple = function (label, expected, min, max, confidence, extra) {
    var s = estimate.fromApi({
      label: label,
      expected: expected,
      minimum: min,
      maximum: max,
      confidence: confidence,
    });
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        s[k] = extra[k];
      });
    }
    return s;
  };

  KS.estimate = estimate;

  /* ---------------------------------------------------------------------
     Shared renderers used by several pages
     --------------------------------------------------------------------- */
  var render = {};

  /** Horizontal bar breakdown from a {name: value} map. */
  render.bars = function (map, options) {
    var opts = options || {};
    var entries = Object.keys(map || {})
      .map(function (k) {
        return { name: fmt.label(k), value: parseFloat(map[k]) || 0, raw: k };
      })
      .sort(function (a, b) {
        return b.value - a.value;
      });

    if (!entries.length) return '<p class="ks-muted ks-small">' + KS.t('No data yet.') + '</p>';

    var max = entries.reduce(function (m, e) { return Math.max(m, e.value); }, 0) || 1;

    return (
      '<div class="ks-bars' + (opts.slim ? " ks-bars--slim" : "") + '">' +
      entries
        .map(function (e) {
          var pct = (e.value / max) * 100;
          var color = opts.colorFor ? opts.colorFor(e.raw, e) : "";
          return (
            '<div class="ks-bar-row">' +
            '<div class="ks-bar-head"><span class="ks-bar-name">' + dom.esc(e.name) + "</span>" +
            '<span class="ks-bar-value">' + dom.esc(opts.valueFormat ? opts.valueFormat(e.value) : fmt.inr(e.value)) + "</span></div>" +
            '<div class="ks-bar-track"><div class="ks-bar-fill ' + color + '" style="width:' + pct.toFixed(1) + '%"></div></div>' +
            "</div>"
          );
        })
        .join("") +
      "</div>"
    );
  };

  /** Coloured bar list for an array of {label, value, color} rows. */
  render.barRows = function (rows, valueFormat) {
    if (!rows || !rows.length) return '<p class="ks-muted ks-small">' + KS.t('No data yet.') + '</p>';
    var max = rows.reduce(function (m, r) { return Math.max(m, Math.abs(parseFloat(r.value) || 0)); }, 0) || 1;
    return (
      '<div class="ks-bars">' +
      rows
        .map(function (r) {
          var v = parseFloat(r.value) || 0;
          var pct = (Math.abs(v) / max) * 100;
          return (
            '<div class="ks-bar-row">' +
            '<div class="ks-bar-head"><span class="ks-bar-name">' + dom.esc(r.label) + "</span>" +
            '<span class="ks-bar-value">' + dom.esc((valueFormat || fmt.inr)(v)) + "</span></div>" +
            '<div class="ks-bar-track"><div class="ks-bar-fill ' + (r.color || "") + '" style="width:' + pct.toFixed(1) + '%"></div></div>' +
            "</div>"
          );
        })
        .join("") +
      "</div>"
    );
  };

  /** Confidence meter with a coloured fill. */
  render.meter = function (fraction) {
    var pct = clamp((parseFloat(fraction) || 0) * 100, 0, 100);
    var cls = "";
    if (pct < 40) cls = "ks-meter-fill--danger";
    else if (pct < 70) cls = "ks-meter-fill--warn";
    return (
      '<div class="ks-meter"><div class="ks-meter-fill ' + cls + '" style="width:' + pct.toFixed(1) + '%"></div></div>'
    );
  };

  /** Definition list from a flat object, skipping null values. */
  render.datalist = function (obj, options) {
    var opts = options || {};
    var rows = Object.keys(obj || {})
      .filter(function (k) {
        return !isNil(obj[k]) && obj[k] !== "" && (!opts.only || opts.only.indexOf(k) !== -1);
      })
      .map(function (k) {
        var v = obj[k];
        if (typeof v === "number") v = fmt.number(v);
        else if (typeof v === "boolean") v = v ? "Yes" : "No";
        else if (Array.isArray(v)) v = v.join(", ");
        return (
          "<div><dt>" + dom.esc(opts.labels && opts.labels[k] ? opts.labels[k] : fmt.label(k)) + "</dt>" +
          "<dd>" + dom.esc(v) + "</dd></div>"
        );
      });
    if (!rows.length) return '<p class="ks-muted ks-small">' + KS.t('No information recorded yet.') + '</p>';
    return '<dl class="ks-datalist' + (opts.columns === 2 ? " ks-datalist--2" : "") + '">' + rows.join("") + "</dl>";
  };

  /** Table from rows + column definitions. */
  render.table = function (columns, rows, options) {
    var opts = options || {};
    if (!rows || !rows.length) {
      return '<p class="ks-muted ks-small">' + dom.esc(opts.empty || KS.t("Nothing to show yet.")) + "</p>";
    }
    var head = columns
      .map(function (c) {
        return "<th" + (c.numeric ? ' class="num"' : "") + ">" + dom.esc(c.label) + "</th>";
      })
      .join("");
    var body = rows
      .map(function (row, i) {
        var tds = columns
          .map(function (c) {
            var raw = c.value(row, i);
            var content = c.html ? raw : dom.esc(isNil(raw) ? "—" : raw);
            return "<td" + (c.numeric ? ' class="num"' : "") + ">" + content + "</td>";
          })
          .join("");
        return "<tr" + (opts.rowClass ? ' class="' + opts.rowClass(row) + '"' : "") + ">" + tds + "</tr>";
      })
      .join("");
    return (
      '<div class="ks-table-wrap"><table class="ks-table">' +
      (opts.caption ? "<caption>" + dom.esc(opts.caption) + "</caption>" : "") +
      "<thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table></div>"
    );
  };

  /** Status badge for a confidence level. */
  render.confBadge = function (level) {
    var key = String(level || "low").toLowerCase();
    return '<span class="ks-badge ' + estimate.badge(key) + '"><span class="ks-dot"></span>' + dom.esc(fmt.label(key)) + "</span>";
  };

  /** Simple pager. onPage is called with the 1-based page number. */
  render.pagination = function (state, onPage) {
    if (!state || state.count <= 1) return "";
    var total = Math.ceil(state.count / (state.pageSize || 20));
    var current = state.page || 1;
    var from = (current - 1) * (state.pageSize || 20) + 1;
    var to = Math.min(current * (state.pageSize || 20), state.count);

    var buttons = "";
    buttons +=
      "<button type='button' data-page='" + (current - 1) + "'" +
      (current <= 1 ? " disabled" : "") + ">" + KS.t("Previous") + "</button>";
    for (var p = 1; p <= total; p += 1) {
      if (total > 7 && p !== 1 && p !== total && Math.abs(p - current) > 1) {
        if (Math.abs(p - current) === 2) buttons += "<span>…</span>";
        continue;
      }
      buttons +=
        "<button type='button' data-page='" + p + "'" +
        (p === current ? " aria-current='page'" : "") + ">" + p + "</button>";
    }
    buttons +=
      "<button type='button' data-page='" + (current + 1) + "'" +
      (current >= total ? " disabled" : "") + ">" + KS.t("Next") + "</button>";

    var host = dom.el("div", { class: "ks-pagination", html: buttons });
    dom.qsa("button", host).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var page = parseInt(btn.dataset.page, 10);
        if (page >= 1 && page <= total) onPage(page);
      });
    });

    return host;
  };

  /** Convenience: mount a pager into a container element. */
  render.mountPagination = function (target, state, onPage) {
    var host = typeof target === "string" ? dom.qs(target) : target;
    if (!host) return;
    dom.set(host, "");
    var pager = render.pagination(state, onPage);
    if (pager) {
      host.appendChild(pager);
      var info = dom.el("div", {
        class: "ks-pagination-info",
        text: "Showing " + (state.page - 1) * (state.pageSize || 20) + 1 + "–" +
          Math.min(state.page * (state.pageSize || 20), state.count) + " of " + state.count,
      });
      host.appendChild(info);
    }
  };

  KS.render = render;

  /* ---------------------------------------------------------------------
     Shared behaviours wired on every page
     --------------------------------------------------------------------- */
  function initNav() {
    var toggle = dom.qs("[data-ks-nav-toggle]");
    var drawer = dom.qs("[data-ks-nav-drawer]");
    if (toggle && drawer) {
      toggle.addEventListener("click", function () {
        var open = drawer.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      });
      dom.qsa("a", drawer).forEach(function (link) {
        link.addEventListener("click", function () {
          drawer.classList.remove("is-open");
          toggle.setAttribute("aria-expanded", "false");
          toggle.setAttribute("aria-label", "Open menu");
        });
      });
    }
  }

  function initAuthChrome() {
    var userName = dom.qs("[data-ks-username]");
    var isIn = auth.isAuthenticated();

    if (userName && isIn) {
      userName.textContent = auth.displayName();
    }

    /* qsa, not qs: the nav marks nine separate elements data-ks-when-auth
       (seven links plus the account/sign-out group). Toggling only the first
       match left the sign-out control stuck on `hidden`, so the dashboard had
       no reachable way to log out. */
    dom.qsa("[data-ks-when-auth]").forEach(function (el) {
      el.hidden = !isIn;
    });
    dom.qsa("[data-ks-when-anon]").forEach(function (el) {
      el.hidden = isIn;
    });

    auth.bindLogout(document);
  }

  function initLanguageSwitch() {
    auth.bindLanguageSwitch(document);
  }

  function initTabs() {
    dom.qsa("[data-ks-tabs]").forEach(function (group) {
      var tabs = dom.qsa('[role="tab"]', group);
      tabs.forEach(function (tab, index) {
        tab.addEventListener("click", function () {
          tabs.forEach(function (t) {
            t.setAttribute("aria-selected", "false");
            var panel = dom.qs("#" + t.getAttribute("aria-controls"));
            if (panel) panel.hidden = true;
          });
          tab.setAttribute("aria-selected", "true");
          var panel = dom.qs("#" + tab.getAttribute("aria-controls"));
          if (panel) {
            panel.hidden = false;
            document.dispatchEvent(new CustomEvent("ks:tab", { detail: { id: tab.dataset.tab } }));
          }
        });
        tab.addEventListener("keydown", function (e) {
          if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
          e.preventDefault();
          var next = e.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
          tabs[next].focus();
          tabs[next].click();
        });
      });
    });
  }

  function initConfirmActions() {
    dom.qsa("[data-ks-confirm]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        if (!ui.confirm(el.dataset.ksConfirm)) {
          e.preventDefault();
          e.stopPropagation();
        }
      });
    });
  }

  /** Show/hide password fields - useful on shared or low-end devices. */
  function initPasswordReveal() {
    dom.qsa("[data-ks-reveal]").forEach(function (btn) {
      var input = document.getElementById(btn.dataset.ksReveal);
      if (!input) return;
      btn.addEventListener("click", function () {
        var hidden = input.type === "password";
        input.type = hidden ? "text" : "password";
        btn.textContent = hidden ? "Hide" : "Show";
        btn.setAttribute("aria-label", (hidden ? "Hide" : "Show") + " password");
      });
    });
  }

  /** Redirect anonymous visitors to the login page before rendering a page. */
  function initAuthGuard() {
    if (!document.body || document.body.dataset.ksRequireAuth !== "true") return;
    if (auth.isAuthenticated()) return;
    var next = window.location.pathname + window.location.search;
    window.location.replace("/login/?next=" + encodeURIComponent(next));
  }

  function initYear() {
    dom.qsa("[data-ks-year]").forEach(function (n) {
      n.textContent = String(new Date().getFullYear());
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAuthGuard();
    initNav();
    initAuthChrome();
    initLanguageSwitch();
    initTabs();
    initConfirmActions();
    initPasswordReveal();
    initYear();
  });

  window.KS = KS;
})(window, document);

