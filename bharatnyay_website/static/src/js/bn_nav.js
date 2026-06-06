/** BharatNyay public nav — mobile menu UX */
(function () {
    "use strict";

    function onReady(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    onReady(function () {
        const nav = document.querySelector(".bn-site-nav");
        if (!nav) {
            return;
        }

        const collapseEl = nav.querySelector("#bnNavCollapsePublic");
        const mqMobile = window.matchMedia("(max-width: 991.98px)");

        // Close hamburger menu after choosing a real link
        nav.querySelectorAll(".navbar-collapse a[href]").forEach(function (link) {
            if (link.classList.contains("dropdown-toggle")) {
                return;
            }
            link.addEventListener("click", function () {
                if (!mqMobile.matches || !collapseEl || !collapseEl.classList.contains("show")) {
                    return;
                }
                const bsCollapse = window.bootstrap && window.bootstrap.Collapse;
                if (bsCollapse) {
                    bsCollapse.getOrCreateInstance(collapseEl).hide();
                } else {
                    collapseEl.classList.remove("show");
                }
            });
        });

        // Highlight current page in nav
        const path = window.location.pathname.replace(/\/$/, "") || "/";
        nav.querySelectorAll(".navbar-nav > .nav-item > .nav-link[href]").forEach(function (link) {
            const href = link.getAttribute("href");
            if (!href || href.startsWith("/#")) {
                return;
            }
            const normalized = href.replace(/\/$/, "") || "/";
            if (path === normalized || (normalized !== "/" && path.startsWith(normalized))) {
                link.classList.add("active");
            }
        });
    });
})();
