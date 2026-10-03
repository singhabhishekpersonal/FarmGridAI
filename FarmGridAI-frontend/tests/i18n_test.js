/* Exercise the language switch the way a browser would, with no browser.
 *
 * The gap this closes: node --check only proves the files parse, and the Django
 * sweep only proves the server-rendered copy is translated. Neither ever ran
 * KS.t() or pressed the Hindi button. This loads app.js into a minimal fake
 * window/document, injects a real catalog slice, and drives the switch.
 *
 * Run: node khetsathi-frontend\tests\i18n_test.js   (also run by verify.py)
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const JS_DIR = path.join(__dirname, "..", "static", "js");
const APP = path.join(JS_DIR, "app.js");
/* Must match KS.STORAGE_LANG in app.js - the language mirror in localStorage. */
const STORE_LANG = "khetsathi.lang";
const failures = [];
let checks = 0;
const pending = [];

/* A check may return a promise, and those assertions have to be awaited.

   This used to be `fn()` with the result thrown away, so every asynchronous
   check silently "passed" no matter what it asserted - a green run that proved
   nothing. Each check is now recorded and settled in order. */
function check(name, fn) {
  checks += 1;
  const settle = (err) => {
    if (err) {
      failures.push(name);
      /* Show where it came from. A rejected assertion often surfaces as a
         generic message from deep inside the api layer, and without the stack
         that is close to impossible to place. */
      const where = err.stack ? String(err.stack).split("\n").slice(1, 4).join("\n           ") : "";
      console.log("  FAIL " + name + "\n         " + err.message + (where ? "\n           " + where : ""));
    } else {
      console.log("  ok   " + name);
    }
  };
  let result;
  try {
    result = fn();
  } catch (e) {
    settle(e);
    return;
  }
  if (result && typeof result.then === "function") {
    pending.push(result.then(() => settle(null), settle));
  } else {
    settle(null);
  }
}

/* ------------------------------------------------------------------ fixtures */

/* Enough of the DOM for app.js to load and for the language buttons to work.
   querySelectorAll supports the two selectors app.js uses here. */
function makeEnv(lang, catalog, opts) {
  const options = opts || {};
  const buttons = [];
  const store = {};

  /* Stand-ins for the nav's auth-gated chrome. The real nav marks NINE separate
     elements data-ks-when-auth (seven links plus the account/sign-out group);
     modelling them as a list is what lets the test catch a regression to
     querySelector, which only ever un-hides the first one and leaves the
     sign-out button stuck on `hidden`. */
  const authOnly = options.authOnly || [{}, {}, {}];
  const anonOnly = options.anonOnly || [{}];

  function makeBtn(code) {
    const listeners = {};
    return {
      dataset: { ksLang: code },
      attributes: {},
      addEventListener: function (type, fn) {
        (listeners[type] = listeners[type] || []).push(fn);
      },
      setAttribute: function (k, v) {
        this.attributes[k] = v;
      },
      getAttribute: function (k) {
        return this.attributes[k];
      },
      click: function () {
        (listeners.click || []).forEach(function (fn) {
          fn();
        });
      },
    };
  }

  const document = {
    readyState: "loading",
    documentElement: {},
    body: { dataset: {}, classList: { add: function () {}, remove: function () {} } },
    /* auth.clear() fires `new CustomEvent("ks:auth", ...)` on the document,
       so both of these have to exist for logout to run at all. */
    dispatchEvent: function () {},
    CustomEvent: function (name, init) {
      this.type = name;
      this.detail = init && init.detail;
    },
    querySelector: function (sel) {
      if (sel === 'meta[name="ks-lang"]') return { content: lang };
      if (sel === "[data-ks-username]") return options.username || null;
      if (sel === "[data-ks-when-auth]") return authOnly[0] || null;
      if (sel === "[data-ks-when-anon]") return anonOnly[0] || null;
      return null;
    },
    querySelectorAll: function (sel) {
      if (sel === "[data-ks-lang]") return buttons;
      if (sel === "[data-ks-when-auth]") return authOnly;
      if (sel === "[data-ks-when-anon]") return anonOnly;
      if (sel === "[data-ks-logout]") return options.logoutButtons || [];
      return [];
    },
    createElement: function () {
      return { classList: { add: function () {} }, appendChild: function () {}, style: {} };
    },
    createTextNode: function (t) {
      return { text: t };
    },
    addEventListener: function (type, fn) {
      if (type === "DOMContentLoaded") document._ready = fn;
    },
  };

  const location = { pathname: "/dashboard/", search: "?tab=1", href: "" };

  const window = {
    KS_I18N: catalog,
    localStorage: {
      getItem: function (k) {
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem: function (k, v) {
        store[k] = String(v);
      },
      removeItem: function (k) {
        delete store[k];
      },
    },
location: location,
    document: document,
    /* auth.setSession/auth.clear do `new CustomEvent(...)`, which resolves
       against the sandbox global - so it has to exist on window, not only on
       the fake document. */
    CustomEvent: function (name, init) {
      this.type = name;
      this.detail = init && init.detail;
    },
    addEventListener: function () {},
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    /* The api layer does `payload instanceof FormData`, so the sandbox needs the
       constructor to exist even though these tests never upload anything. */
    FormData: function () {
      this.parts = {};
    },
    URLSearchParams: function () {
      this.parts = {};
    },
    fetch: function () {
      return Promise.resolve({ ok: true });
    },
  };
  window.window = window;

  return { window, document, buttons, store, location, makeBtn, authOnly, anonOnly };
}

/* A structurally valid, unsigned JWT. auth.isAuthenticated() only checks that a
   token string is present, so the payload does not need to verify. */
function fakeJwt() {
  const enc = function (o) {
    return Buffer.from(JSON.stringify(o)).toString('base64').replace(/=+\$/, '');
  };
  return enc({ alg: 'HS256', typ: 'JWT' }) + '.' + enc({ exp: 9999999999 }) + '.sig';
}

/* The real catalog, as JSON emitted by the same generator step that writes the
   Python modules, so this test fails if a translation is missing rather than
   testing a hand-written fixture. */
function loadCatalog() {
  const file = path.join(__dirname, "catalog_hifi.json");
  const catalog = JSON.parse(fs.readFileSync(file, "utf8"));
  assert.ok(
    Object.keys(catalog).length > 500,
    "catalog looks too small: " + Object.keys(catalog).length
  );
  return catalog;
}

/* Resolve the body of a quoted JS string literal to its value. */
function unescapeBody(body) {
  let out = "";
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (ch !== "\\") {
      out += ch;
      continue;
    }
    const next = body[i + 1];
    i += 1;
    if (next === "n") out += "\n";
    else if (next === "t") out += "\t";
    else if (next === "r") out += "\r";
    else if (next === "u") {
      out += String.fromCharCode(parseInt(body.slice(i + 1, i + 5), 16));
      i += 4;
    } else if (next === "x") {
      out += String.fromCharCode(parseInt(body.slice(i + 1, i + 3), 16));
      i += 2;
    } else out += next; // covers \' \" \\ \/ and anything else
  }
  return out;
}

function boot(env) {
  const code = fs.readFileSync(APP, "utf8");
  vm.createContext(env.window);
  vm.runInContext(code, env.window, { filename: "app.js" });
  return env.window.KS;
}

/* A fetch double that satisfies the api layer: it reads the content type off
   response.headers before deciding between .json() and .text(). Without that
   header the stub fell into the text branch and every async check failed with
   a bogus "cannot reach the server". */
function jsonResponse(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    headers: {
      get: function (name) {
        return /content-type/i.test(name) ? "application/json" : null;
      },
    },
    json: function () {
      return Promise.resolve(payload);
    },
    text: function () {
      return Promise.resolve(JSON.stringify(payload));
    },
  };
}

/* A fetch double that records each request so a test can inspect headers. */
function recordingFetch(calls, status, payload) {
  return function (url, init) {
    calls.push({ url: String(url), init: init || {} });
    return Promise.resolve(jsonResponse(status || 200, payload || {}));
  };
}

/* ---------------------------------------------------------------- the checks */

const catalog = loadCatalog();
console.log("  catalog entries loaded from apps/core: " + Object.keys(catalog).length);
console.log("");

/* 1. KS.t() reads the injected catalog and falls back to English. */
/* Assertions here are deliberately structural rather than comparing against
   hard-coded Devanagari: the point is that a label which HAS an entry renders
   as something different that contains Hindi script, not that one specific
   wording is still current. */
const DEVANAGARI = new RegExp("[\\u0900-\\u097F]");

function assertHindi(source, value, label) {
  assert.notStrictEqual(value, source, label + ": expected a translation, got the English source");
  assert.ok(DEVANAGARI.test(value), label + ": translation is not in Devanagari: " + value);
}

check("KS.t() translates a known key and falls back for an unknown one", function () {
  const env = makeEnv("hi", catalog);
  const KS = boot(env);
  assertHindi("Dashboard", KS.t("Dashboard"), "Dashboard");
  assertHindi("Run recommendation engine", KS.t("Run recommendation engine"), "Run recommendation engine");
  /* Not in the catalog: must return the English source, never blank/undefined. */
  assert.strictEqual(KS.t("A string nobody translated"), "A string nobody translated");
  assert.strictEqual(KS.t(null), "");
  assert.strictEqual(KS.t(undefined), "");
});

/* 2. On an English page the catalog is empty and KS.t is a passthrough. */
check("KS.t() is a passthrough when no catalog is injected (English)", function () {
  const env = makeEnv("en", {});
  const KS = boot(env);
  assert.strictEqual(KS.t("Dashboard"), "Dashboard");
});

/* 3. KS.language() mirrors the server meta tag. */
check("KS.language() reports the server language", function () {
  assert.strictEqual(boot(makeEnv("hi", catalog)).language(), "hi");
  assert.strictEqual(boot(makeEnv("en", {})).language(), "en");
});

/* 4. THE REGRESSION: a stale localStorage entry must not beat the server.
      Before the fix this returned "hi" on an English page, which both lit up
      the wrong button and made pressing Hindi a no-op. */
check("stale localStorage does not override an English server", function () {
  const env = makeEnv("en", {});
  env.store[STORE_LANG] = "hi"; // left over from an earlier visit
  const KS = boot(env);
  assert.strictEqual(KS.language(), "en");
  assert.strictEqual(KS.auth.language(), "en", "auth.language() must trust the server");
  /* And the mirror is repaired, so the next page load starts clean. */
  assert.strictEqual(env.store[STORE_LANG], "en");
});

check("a stale 'en' entry does not override a Hindi server", function () {
  const env = makeEnv("hi", catalog);
  env.store[STORE_LANG] = "en";
  const KS = boot(env);
  assert.strictEqual(KS.auth.language(), "hi");
  assert.strictEqual(env.store[STORE_LANG], "hi");
});

/* 5. Pressing Hindi on an English page must actually navigate to the language
      route. This is what the profile-panel copy failed to do. */
check("pressing Hindi navigates to /lang/hi/ with the current page as next", function () {
  const env = makeEnv("en", {});
  const KS = boot(env);
  const en = env.makeBtn("en");
  const hi = env.makeBtn("hi");
  env.buttons.push(en, hi);

  KS.auth.bindLanguageSwitch(env.document);
  assert.strictEqual(en.getAttribute("aria-pressed"), "true");
  assert.strictEqual(hi.getAttribute("aria-pressed"), "false");

  hi.click();
  assert.strictEqual(
    env.location.href,
    "/lang/hi/?next=%2Fdashboard%2F%3Ftab%3D1",
    "expected a navigation to the language route"
  );
});

/* 6. Pressing the already-active language must not reload the page. */
check("pressing the active language does not reload", function () {
  const env = makeEnv("hi", catalog);
  const KS = boot(env);
  const en = env.makeBtn("en");
  const hi = env.makeBtn("hi");
  env.buttons.push(en, hi);

  KS.auth.bindLanguageSwitch(env.document);
  assert.strictEqual(hi.getAttribute("aria-pressed"), "true");
  hi.click();
  assert.strictEqual(env.location.href, "", "no navigation expected");
});

/* 7. Buttons must not be bound twice: the dashboard re-renders its profile
      panel after load, and a duplicate handler would fire the navigation twice
      and double-toggle aria-pressed. */
check("a button is never bound twice", function () {
  const env = makeEnv("en", {});
  const KS = boot(env);
  const hi = env.makeBtn("hi");
  env.buttons.push(hi);

  KS.auth.bindLanguageSwitch(env.document);
  KS.auth.bindLanguageSwitch(env.document); // the dashboard re-render case
  hi.click();

  assert.strictEqual(env.location.href, "/lang/hi/?next=%2Fdashboard%2F%3Ftab%3D1");
  assert.strictEqual(hi.getAttribute("aria-pressed"), "true");
});

/* 8. Every signed-in nav group must be revealed, not just the first one.
      The nav marks nine elements data-ks-when-auth; toggling only the first
      with querySelector left the account/sign-out group on `hidden`, so the
      dashboard offered no visible way to log out. Driven through the real
      DOMContentLoaded path rather than a private helper. */
check("every signed-in nav group is revealed when authenticated", function () {
  const authOnly = [{}, {}, {}, {}, {}, {}, {}, {}, {}]; // nine, as in nav.html
  const anonOnly = [{}];
  const env = makeEnv("en", catalog, { authOnly: authOnly, anonOnly: anonOnly });

  env.store["khetsathi.access"] = fakeJwt();
  boot(env);
  env.document._ready(); // app.js init: initAuthChrome() and friends

  const stillHidden = authOnly.filter(function (el) {
    return el.hidden !== false;
  });
  assert.strictEqual(
    stillHidden.length,
    0,
    stillHidden.length + " signed-in nav group(s) left hidden, so Sign out is unreachable"
  );
  assert.strictEqual(anonOnly[0].hidden, true, "signed-out group must stay hidden");
});

check("signed-out nav shows Sign in and hides the auth-only groups", function () {
  const authOnly = [{}, {}];
  const anonOnly = [{}];
  const env = makeEnv("en", catalog, { authOnly: authOnly, anonOnly: anonOnly });
  boot(env);
  env.document._ready();

  assert.strictEqual(anonOnly[0].hidden, false, "Sign in must be visible when signed out");
  authOnly.forEach(function (el, i) {
    assert.strictEqual(el.hidden, true, "auth group " + i + " must be hidden");
  });
});

/* 9. Sign out must clear the tokens and navigate to the server-side logout
      route. It must NOT be an AJAX POST followed by a redirect: when that POST
      failed (CSRF, offline) the redirect still ran with the Django session
      alive, so /login/ redirected the visitor to /dashboard/ and the auth
      guard sent them back to /login/ - the visible three-step flicker this
      replaced. One navigation, no race. */
check("sign out clears tokens and navigates to the server logout route", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);
  env.store["khetsathi.access"] = fakeJwt();
  env.store["khetsathi.refresh"] = "a-refresh-token";
  env.window.__calls = [];
  env.window.fetch = function (url) {
    env.window.__calls.push({ url: url });
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () {
        return Promise.resolve({});
      },
    });
  };

  KS.auth.logout();

  assert.strictEqual(env.store["khetsathi.access"], undefined, "access token must be cleared");
  assert.strictEqual(env.store["khetsathi.refresh"], undefined, "refresh token must be cleared");
  assert.strictEqual(env.location.href, "/logout/", "expected one navigation to /logout/");
  assert.strictEqual(
    env.window.__calls.length,
    0,
    "sign out must not depend on an AJAX round-trip completing first"
  );
});

check("sign out reaches the server even when no token is stored", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);

  assert.ok(!KS.auth.isAuthenticated(), "precondition: already signed out");
  KS.auth.logout();
  assert.strictEqual(
    env.location.href,
    "/logout/",
    "the session is closed by the navigation, so it must happen regardless of local state"
  );
});

/* 10. A sign-out control is never wired twice, for the same reason as the
       language buttons: the dashboard injects a second one in its profile
       panel, and a double binding would fire two logout requests. */
check("a sign-out control is never bound twice", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);
  let fired = 0;
  const btn = { dataset: {}, addEventListener: function () { fired += 1; } };
  env.document.querySelectorAll = function (sel) {
    return sel === "[data-ks-logout]" ? [btn] : [];
  };

  KS.auth.bindLogout(env.document);
  KS.auth.bindLogout(env.document); // the dashboard re-render case
  assert.strictEqual(fired, 1, "expected exactly one click handler, got " + fired);
});

/* 11. Every KS.t() call site in the shipped JSat proves the JS-rendered UI will actually show Hindi. */
/* 11. CSRF on an unsafe method. login()/register() call the API with
       skipAuth: true, and the header was gated on !skipAuth, so the sign-in
       POST carried no X-CSRFToken and the server answered
       "CSRF token missing" whenever a session cookie was present.
       The header must be sent for every unsafe method. */
check("sign in sends a CSRF token even though it uses skipAuth", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);
  const calls = [];
  env.window.fetch = recordingFetch(calls, 200, { data: { access: "a", refresh: "r" } });
  env.document.cookie = "csrftoken=cookie-value";

  return KS.auth.login("farmer", "pw").then(function () {
    const call = calls.filter(function (c) { return /auth\/login/.test(c.url); })[0];
    assert.ok(call, "expected a login request");
    assert.ok(call.init.headers.Authorization === undefined,
      "skipAuth must still suppress the Authorization header");
    assert.strictEqual(call.init.headers["X-CSRFToken"], "cookie-value",
      "the sign-in POST must carry X-CSRFToken or the server rejects it");
  });
});

check("CSRF falls back to the meta tag when the cookie is absent", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);
  const calls = [];
  env.window.fetch = recordingFetch(calls, 200, {});

  /* No csrftoken cookie at all - the page still carries the meta tag. */
  env.document.cookie = "";
  env.document.querySelector = function (sel) {
    if (sel === 'meta[name="ks-lang"]') return { content: "en" };
    if (sel === 'meta[name="csrf-token"]') {
      return { getAttribute: function () { return "masked-token-from-meta"; } };
    }
    return null;
  };

  return KS.auth.login("farmer", "pw").then(function () {
    const call = calls.filter(function (c) { return /auth\/login/.test(c.url); })[0];
    assert.ok(call, "expected a login request");
    assert.strictEqual(call.init.headers["X-CSRFToken"], "masked-token-from-meta",
      "with no cookie the meta token must be used rather than an empty header");
  });
});

check("safe methods do not carry a CSRF token", function () {
  const env = makeEnv("en", catalog);
  const KS = boot(env);
  const calls = [];
  env.window.fetch = recordingFetch(calls, 200, {});
  env.document.cookie = "csrftoken=cookie-value";

  return KS.api.get("/crops/").then(function () {
    const call = calls.filter(function (c) { return /\/crops\//.test(c.url); })[0];
    assert.ok(call, "expected a GET request");
    assert.strictEqual(call.init.headers["X-CSRFToken"], undefined,
      "a GET must not send a CSRF token");
  });
});

check("every KS.t() argument in the frontend JS has a catalog entry", function () {
  const jsDir = JS_DIR;
  const files = fs.readdirSync(jsDir).filter(function (f) {
    return /\.js$/.test(f) && f !== "i18n_test.js";
  });

  const missing = [];
  let total = 0;

files.forEach(function (file) {
    const src = fs.readFileSync(path.join(jsDir, file), "utf8");
/* Match KS.t( followed by a quoted string in either quote style,
       honouring escapes. */
    const re = /KS\.t\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g;
    let m;
    while ((m = re.exec(src)) !== null) {
      const raw = m[1] !== undefined ? m[1] : m[2];
      const literal = unescapeBody(raw);
      total += 1;
      const hasHindi = DEVANAGARI.test(literal);
      if (!hasHindi && !Object.prototype.hasOwnProperty.call(catalog, literal)) {
        missing.push(file + ": " + JSON.stringify(literal).slice(0, 70));
      }
    }
  });

  assert.ok(total > 200, "expected the full set of call sites, saw " + total);
  assert.strictEqual(
    missing.length,
    0,
    missing.length + " KS.t() call site(s) have no translation:\n         " + missing.slice(0, 10).join("\n         ")
  );
  console.log("         (" + total + " KS.t() call sites, all resolvable)");
});

/* --------------------------------------------------------------------- result */

/* Settle every asynchronous check before reporting, otherwise the summary would
   print before their assertions had a chance to run. */
Promise.all(pending).then(function () {
  console.log("");
  console.log("  " + (checks - failures.length) + "/" + checks + " passed");
  console.log("  RESULT: " + (failures.length ? "FAIL" : "PASS"));
  process.exit(failures.length ? 1 : 0);
});
