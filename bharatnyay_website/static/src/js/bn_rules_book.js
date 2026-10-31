/** BharatNyay SOP rules pages — chapter tabs (Arbitration / Mediation & Conciliation) */
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
        const root = document.querySelector("[data-bn-rb]");
        if (!root) {
            return;
        }

        const tabs = Array.from(root.querySelectorAll(".bn-rb-tab"));
        const docs = Array.from(root.querySelectorAll(".bn-rb-doc"));
        const indexes = Array.from(root.querySelectorAll(".bn-rb-index"));
        if (!tabs.length) {
            return;
        }
        const ids = tabs.map(function (t) { return t.dataset.ch; });

        function show(chId, opts) {
            const idx = ids.indexOf(chId);
            if (idx === -1) {
                return;
            }
            tabs.forEach(function (tab) {
                const on = tab.dataset.ch === chId;
                tab.classList.toggle("is-active", on);
                tab.setAttribute("aria-selected", on ? "true" : "false");
                tab.tabIndex = on ? 0 : -1;
            });
            docs.forEach(function (d) { d.hidden = d.dataset.ch !== chId; });
            indexes.forEach(function (n) { n.hidden = n.dataset.ch !== chId; });

            const doc = docs[idx];
            const prev = idx > 0 ? tabs[idx - 1] : null;
            const next = idx < tabs.length - 1 ? tabs[idx + 1] : null;
            const prevBtn = doc.querySelector(".is-prev");
            const nextBtn = doc.querySelector(".is-next");
            [[prevBtn, prev], [nextBtn, next]].forEach(function (pair) {
                const btn = pair[0];
                const target = pair[1];
                btn.hidden = !target;
                if (target) {
                    btn.dataset.goto = target.dataset.ch;
                    btn.querySelector("[data-nav-label]").textContent =
                        "Chapter " + target.querySelector(".bn-rb-tab-badge").textContent.trim() +
                        " · " + target.querySelector(".bn-rb-tab-name").textContent.trim();
                }
            });

            if (opts && opts.scroll) {
                const tabBar = root.querySelector(".bn-rb-tabs-wrap");
                if (tabBar) {
                    const top = tabBar.getBoundingClientRect().top + window.pageYOffset - 90;
                    window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
                }
            }
            if (opts && opts.hash && window.history && window.history.replaceState) {
                window.history.replaceState(null, "", "#chapter-" + chId);
            }
        }

        tabs.forEach(function (tab, i) {
            tab.addEventListener("click", function () {
                show(tab.dataset.ch, { hash: true });
            });
            tab.addEventListener("keydown", function (e) {
                let target = null;
                if (e.key === "ArrowRight") {
                    target = tabs[(i + 1) % tabs.length];
                } else if (e.key === "ArrowLeft") {
                    target = tabs[(i - 1 + tabs.length) % tabs.length];
                }
                if (target) {
                    e.preventDefault();
                    target.focus();
                    target.click();
                }
            });
        });

        root.querySelectorAll("[data-goto]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (btn.dataset.goto) {
                    show(btn.dataset.goto, { scroll: true, hash: true });
                }
            });
        });

        // Open the right chapter for #chapter-chN or #rule-N deep links
        let start = ids[0];
        const hash = window.location.hash || "";
        const mc = /^#chapter-(\w+)$/.exec(hash);
        const mr = /^#rule-(\d+)$/.exec(hash);
        if (mc && ids.indexOf(mc[1]) !== -1) {
            start = mc[1];
        } else if (mr) {
            const rule = root.querySelector("#rule-" + mr[1]);
            const owner = rule && rule.closest(".bn-rb-doc");
            if (owner) {
                start = owner.dataset.ch;
            }
        }
        show(start);
        if (mr) {
            const target = document.getElementById("rule-" + mr[1]);
            if (target) {
                target.scrollIntoView();
            }
        }
    });
})();
