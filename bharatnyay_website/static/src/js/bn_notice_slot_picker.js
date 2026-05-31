(function () {
    "use strict";

    function qs(sel, root) {
        return (root || document).querySelector(sel);
    }

    function initNoticeSlotPicker() {
        const form = qs("#bn_notice_form");
        if (!form) {
            return;
        }
        const slotsUrl = form.dataset.slotsUrl;
        const arbSelect = qs('select[name="arbitrator_id"]', form);
        const dateInput = qs("#bn_scheduler_date", form);
        const section = qs("#bn_slot_section", form);
        const gridEl = qs("#bn_slot_grid", form);
        const hiddenIndex = qs("#bn_grid_selected_index", form);
        const hintEl = qs("#bn_slot_hint", form);
        if (!slotsUrl || !arbSelect || !dateInput || !section || !gridEl || !hiddenIndex) {
            return;
        }

        let selectedIndex = 0;
        let loading = false;

        function setHint(text) {
            if (hintEl) {
                hintEl.textContent = text || "";
            }
        }

        function clearSelection() {
            selectedIndex = 0;
            hiddenIndex.value = "0";
        }

        function renderSlots(slots) {
            gridEl.innerHTML = "";
            if (!slots || !slots.length) {
                gridEl.innerHTML =
                    '<p class="bn-slot-empty mb-0">No slots for this day. Pick another date or arbitrator.</p>';
                return;
            }
            for (const slot of slots) {
                const btn = document.createElement("button");
                btn.type = "button";
                const status = slot.status || (slot.available ? "free" : "booked");
                btn.className = "bn-slot-cell bn-slot-cell--" + status;
                if (status !== "free") {
                    btn.disabled = true;
                }
                btn.dataset.index = String(slot.index);
                btn.setAttribute("aria-label", "Slot " + slot.index + " " + slot.label);
                btn.innerHTML =
                    '<span class="bn-slot-num">' +
                    slot.index +
                    "</span><span class=\"bn-slot-time\">" +
                    (slot.label || "") +
                    "</span>";
                if (slot.index === selectedIndex && status === "free") {
                    btn.classList.add("bn-slot-cell--selected");
                }
                btn.addEventListener("click", () => {
                    if (status !== "free") {
                        return;
                    }
                    selectedIndex = slot.index;
                    hiddenIndex.value = String(slot.index);
                    gridEl.querySelectorAll(".bn-slot-cell--selected").forEach((el) => {
                        el.classList.remove("bn-slot-cell--selected");
                    });
                    btn.classList.add("bn-slot-cell--selected");
                    setHint("Selected: " + slot.label + " on " + dateInput.value);
                });
                gridEl.appendChild(btn);
            }
        }

        async function loadSlots() {
            const arbId = arbSelect.value;
            const day = dateInput.value;
            clearSelection();
            if (!arbId || !day) {
                section.style.display = "none";
                setHint("");
                return;
            }
            section.style.display = "";
            if (loading) {
                return;
            }
            loading = true;
            setHint("Loading available slots…");
            gridEl.innerHTML = '<p class="bn-slot-empty mb-0">Loading…</p>';
            try {
                const url =
                    slotsUrl +
                    "?arbitrator_id=" +
                    encodeURIComponent(arbId) +
                    "&scheduler_date=" +
                    encodeURIComponent(day);
                const res = await fetch(url, { credentials: "same-origin" });
                if (!res.ok) {
                    throw new Error("HTTP " + res.status);
                }
                const data = await res.json();
                renderSlots(data.slots || []);
                const free = (data.slots || []).filter((s) => s.status === "free").length;
                setHint(
                    free
                        ? "Tap a green slot (09:00–17:00, 30 minutes each)."
                        : "No free slots this day — try another date."
                );
            } catch (e) {
                gridEl.innerHTML =
                    '<p class="bn-slot-empty mb-0 text-danger">Could not load slots. Refresh and try again.</p>';
                setHint("");
            } finally {
                loading = false;
            }
        }

        arbSelect.addEventListener("change", loadSlots);
        dateInput.addEventListener("change", loadSlots);
        if (arbSelect.value && dateInput.value) {
            loadSlots();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initNoticeSlotPicker);
    } else {
        initNoticeSlotPicker();
    }
})();
