/* ATAK-CX: makes OpenTAKServer's web map look and work like the Manager.
   - always the dark tactical theme, with the team's name and emblem
   - one login with the Manager: the web map's own login page hands over to the team login
     (/manage/login), and logging out of either logs out of both
   - the Manager's pages (admins) and "Change my password" (everyone) in the sidebar
   Installed by `takcx webmap-theme on` (brand.js, loaded first, sets window.TAKCX).
   Add ?native=1 to a web map address to get OpenTAKServer's own login page. */
(function () {
  "use strict";
  var B = window.TAKCX || {};
  var d = document;

  function get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) {
    try { if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch (e) { /* private mode */ }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Always dark (the app reads this before it draws anything).
  set("mantine-color-scheme-value", "dark");
  d.documentElement.setAttribute("data-mantine-color-scheme", "dark");
  d.documentElement.classList.add("takcx");
  if (B.team) d.title = B.team + " · Map";

  var native = /[?&]native=1(&|$)/.test(location.search);
  var shared = B.manager && !native;

  // ---- one login with the Manager ----
  function status(url) {
    try {
      var x = new XMLHttpRequest();
      x.open("GET", url, false);  // before the app starts, so its own login page never flashes up
      x.setRequestHeader("Accept", "application/json");
      x.send();
      return x;
    } catch (e) { return { status: 0 }; }
  }
  function managerUp() { return status("/manage/login").status === 200; }
  function toLogin(next) {
    location.replace("/manage/login?next=" + encodeURIComponent(!next || next === "/login" ? "/" : next));
  }
  if (shared && !/^\/(reset|register|confirm)/.test(location.pathname)) {
    // The web map remembers "logged in" in the browser; keep that in step with the real,
    // shared login. Asked before the app starts, so its own login page never flashes up.
    var me = null;
    var r = status("/api/me");
    try { if (r.status === 200) me = JSON.parse(r.responseText); } catch (e) { me = null; }
    if (me && me.username) {
      var admin = (me.roles || []).some(function (r) { return r && r.name === "administrator"; });
      if (get("username") !== me.username) set("administrator", null);
      set("loggedIn", "true");
      set("username", me.username);
      set("email", String(me.email));
      if (me.token) set("token", me.token);
      set("administrator", admin ? "true" : null);
      B.user = me.username;
      B.admin = admin;
      if (location.pathname === "/login") location.replace(admin ? "/dashboard" : "/map");
    } else {
      ["loggedIn", "username", "email", "token", "administrator"].forEach(function (k) { set(k, null); });
      if (managerUp()) {
        toLogin(location.pathname === "/login" ? "/" : location.pathname + location.search);
        return;
      }
      shared = false;  // the Manager isn't answering: let OpenTAKServer's own login page do it
    }
  }
  if (shared) {
    // After "Log Out" (or a login ending) the app sends itself to /login: use the team login instead.
    ["pushState", "replaceState"].forEach(function (fn) {
      var orig = window.history[fn];
      window.history[fn] = function (state, title, url) {
        if (url != null && String(url).replace(location.origin, "").split(/[?#]/)[0] === "/login" && managerUp()) {
          toLogin("/");
          return;
        }
        return orig.apply(this, arguments);
      };
    });
  } else {
    B.admin = get("administrator") === "true";
  }

  // ---- the team's badge in the header, and the Manager's links in the sidebar ----
  var I = B.icons || {};
  function ico(name) {
    return '<svg class="ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (I[name] || "") + "</svg>";
  }

  function decorate() {
    var header = d.querySelector(".mantine-AppShell-header");
    if (header && !header.querySelector(".takcx-brand")) {
      var logo = header.querySelector("img");
      var spot = logo ? logo.parentNode : header.querySelector(".mantine-Group-root");
      if (spot) {
        var a = d.createElement("a");
        a.className = "takcx-brand";
        a.href = B.admin && shared ? "/manage/" : "/map";
        a.innerHTML = (B.emblem || "") + "<span><b>" + esc(B.team || "ATAK-CX") + "</b><small>Live map</small></span>";
        spot.appendChild(a);
      }
    }
    var nav = d.querySelector(".mantine-AppShell-navbar");
    if (nav && shared && !nav.querySelector(".takcx-nav")) {
      var content = nav.querySelector(".mantine-ScrollArea-viewport > div") || nav;
      var main = content.firstElementChild;
      if (main) {
        var links = B.admin ? [["/manage/", "status", "Status"], ["/manage/people", "people", "People"],
          ["/manage/drones", "drone", "Drones"], ["/manage/addons", "addons", "Add-ons"],
          ["/manage/settings", "settings", "Settings"], ["/manage/troubleshoot", "troubleshoot", "Troubleshoot"]] : [];
        links.push(["/manage/password", "key", "Change my password"]);
        var box = d.createElement("div");
        box.className = "takcx-nav";
        box.innerHTML = '<div class="takcx-nav-title">' + (B.admin ? "Manager" : "Account") + "</div>" +
          links.map(function (l) { return '<a class="takcx-link" href="' + l[0] + '">' + ico(l[1]) + esc(l[2]) + "</a>"; }).join("");
        main.parentNode.insertBefore(box, main.nextSibling);
      }
    }
    // The theme is always dark here, so the app's dark-mode switch has nothing to do.
    var labels = d.querySelectorAll(".mantine-NavLink-label");
    for (var i = 0; i < labels.length; i++) {
      if (labels[i].textContent === "Dark Mode") {
        var row = labels[i].closest(".mantine-NavLink-root");
        if (row && !row.classList.contains("takcx-hidden")) row.classList.add("takcx-hidden");
      }
    }
  }

  var queued = false;
  function soon() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(function () { queued = false; decorate(); });
  }
  function start() {
    decorate();
    new MutationObserver(soon).observe(d.body, { childList: true, subtree: true });
  }
  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", start);
  else start();
})();
