const root = document.getElementById("viewer-root");
const stage = document.getElementById("viewer-stage");
const scroller = document.getElementById("viewer-scroller");
const wrap = document.getElementById("page-wrap");
const canvas = document.getElementById("pdf-canvas");
const status = document.getElementById("pdf-status");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const pageInput = document.getElementById("page-input");
const pageCount = document.getElementById("page-count");
const zoomInBtn = document.getElementById("zoom-in");
const zoomOutBtn = document.getElementById("zoom-out");
const pinLayer = document.getElementById("pin-layer");
const sheetEl = document.getElementById("note-sheet");

const pdfjsLib = await import(root.dataset.pdfjs);
pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.pdfjsWorker;

// 4x fit width is where text on a 1:100 plan becomes legible at phone width;
// past that the canvas cost outruns what anyone can see.
const MAX_ZOOM = 4;
// iOS Safari refuses a canvas much larger than this, and a 4x A0 at a phone's
// device pixel ratio would be several times it. Over the cap the render is
// done at a lower ratio instead — softer, but it renders.
const MAX_CANVAS_PIXELS = 16_000_000;

let pdf = null;
let pageNum = 1;
let rendering = false;
let renderAgain = false;
// Multiplier on fit-to-width. Kept across pages: the zoom is about how close
// you need to look at this drawing, not at this sheet of it.
let zoom = 1;
// The point of the page that must stay under the cursor or fingers across a
// re-render, as fractions of the page plus its offset in the scroller.
let anchor = null;

window.mickiCurrentPage = 1;

function updateControls() {
    prevBtn.disabled = pageNum <= 1;
    nextBtn.disabled = pageNum >= pdf.numPages;
    pageInput.value = pageNum;
    pageInput.max = pdf.numPages;
    zoomInBtn.disabled = zoom >= MAX_ZOOM;
    zoomOutBtn.disabled = zoom <= 1;
}

async function renderPage() {
    // A zoom or resize that lands mid-render is not dropped but queued, or
    // the last gesture of a pinch would be the one that got lost.
    if (rendering) {
        renderAgain = true;
        return;
    }
    rendering = true;
    try {
        const page = await pdf.getPage(pageNum);
        // The stage, not the page: from xxl up the list takes a column of its
        // own and the drawing gets what is left.
        const fitWidth = Math.min(stage.clientWidth, 900);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = (fitWidth / baseViewport.width) * zoom;
        const viewport = page.getViewport({ scale });
        let dpr = window.devicePixelRatio || 1;
        const pixels = viewport.width * viewport.height * dpr * dpr;
        if (pixels > MAX_CANVAS_PIXELS) dpr *= Math.sqrt(MAX_CANVAS_PIXELS / pixels);

        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        wrap.style.width = `${viewport.width}px`;
        wrap.style.height = `${viewport.height}px`;
        if (anchor) {
            scroller.scrollLeft = anchor.fx * viewport.width + wrap.offsetLeft - anchor.cx;
            scroller.scrollTop = anchor.fy * viewport.height + wrap.offsetTop - anchor.cy;
            anchor = null;
        }

        await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport,
            transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
        }).promise;

        window.mickiCurrentPage = pageNum;
        updateControls();
        // The pin layer listens for this (hx-trigger) and re-fetches its pins.
        wrap.dispatchEvent(new CustomEvent("micki:page-rendered", { bubbles: true, detail: { pageNum } }));
    } finally {
        rendering = false;
        if (renderAgain) {
            renderAgain = false;
            renderPage();
        }
    }
}

function goTo(n) {
    if (!pdf) return;
    pageNum = Math.min(Math.max(1, n), pdf.numPages);
    renderPage();
}

prevBtn.addEventListener("click", () => goTo(pageNum - 1));
nextBtn.addEventListener("click", () => goTo(pageNum + 1));
pageInput.addEventListener("change", () => goTo(parseInt(pageInput.value, 10) || 1));

let resizeTimer = null;
window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderPage, 200);
});

// --- Zoom -------------------------------------------------------------------

/* The page is re-rendered at the new scale rather than stretched, so it stays
 * crisp, and it scrolls inside #viewer-scroller so the toolbar stays put.
 * Pins keep their size at every zoom: they are UI, not drawing, and at 4x a
 * scaled pin would cover the very thing you zoomed in to look at. Their
 * percent coordinates make placing and reading them zoom-independent.
 *
 * `focal` is a client-space point (cursor, pinch centre) that must stay put;
 * without one the centre of the view does.
 */
function setZoom(next, focal) {
    if (!pdf) return;
    next = Math.min(MAX_ZOOM, Math.max(1, next));
    if (next === zoom) return;
    const rect = scroller.getBoundingClientRect();
    const cx = focal ? focal.x - rect.left : scroller.clientWidth / 2;
    const cy = focal ? focal.y - rect.top : scroller.clientHeight / 2;
    anchor = {
        fx: (scroller.scrollLeft + cx - wrap.offsetLeft) / wrap.offsetWidth,
        fy: (scroller.scrollTop + cy - wrap.offsetTop) / wrap.offsetHeight,
        cx,
        cy,
    };
    zoom = next;
    renderPage();
}

zoomInBtn.addEventListener("click", () => setZoom(zoom * 1.5));
zoomOutBtn.addEventListener("click", () => setZoom(zoom / 1.5));

// Ctrl+wheel, which is also what a trackpad pinch arrives as.
scroller.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    setZoom(zoom * (e.deltaY < 0 ? 1.25 : 0.8), { x: e.clientX, y: e.clientY });
}, { passive: false });

// Pinch. Touch events rather than pointer events: with touch-action set to
// pan-x pan-y the browser claims a two-finger gesture as a scroll and cancels
// the pointers, while a non-passive touchmove can still say no to it. One
// finger is never handled here — that is a native scroll of the scroller.
//
// During the gesture the page is only transformed, which is instant; the
// real render at the new scale happens once the fingers lift.
let pinch = null;

function touchDistance(t) {
    return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
}

function touchCentre(t) {
    return { x: (t[0].clientX + t[1].clientX) / 2, y: (t[0].clientY + t[1].clientY) / 2 };
}

scroller.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 2 || !pdf) return;
    const centre = touchCentre(e.touches);
    const rect = wrap.getBoundingClientRect();
    pinch = { start: touchDistance(e.touches), factor: 1, centre };
    wrap.style.transformOrigin = `${centre.x - rect.left}px ${centre.y - rect.top}px`;
}, { passive: true });

scroller.addEventListener("touchmove", (e) => {
    if (!pinch || e.touches.length !== 2) return;
    e.preventDefault();
    const wanted = zoom * (touchDistance(e.touches) / pinch.start);
    pinch.factor = Math.min(MAX_ZOOM, Math.max(1, wanted)) / zoom;
    pinch.centre = touchCentre(e.touches);
    wrap.style.transform = `scale(${pinch.factor})`;
}, { passive: false });

function endPinch() {
    if (!pinch) return;
    const { factor, centre } = pinch;
    pinch = null;
    wrap.style.transform = "";
    wrap.style.transformOrigin = "";
    setZoom(zoom * factor, centre);
}

scroller.addEventListener("touchend", endPinch);
scroller.addEventListener("touchcancel", endPinch);

// Drag to pan with a mouse. Touch pans natively; a mouse would otherwise be
// left with the scrollbars. A drag that moved must not end in a click, or
// letting go would file a registration where the cursor stopped.
let drag = null;
let swallowClick = false;

scroller.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0 || e.target.closest(".pin")) return;
    drag = { x: e.clientX, y: e.clientY, left: scroller.scrollLeft, top: scroller.scrollTop, moved: false };
});

scroller.addEventListener("pointermove", (e) => {
    if (!drag) return;
    // The button was released outside the scroller before capture kicked in,
    // so no pointerup reached us: forget the drag rather than panning with
    // nothing pressed.
    if (!(e.buttons & 1)) {
        drag = null;
        return;
    }
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    if (!drag.moved) {
        drag.moved = true;
        // Capture only once this is a drag. Capturing on pointerdown
        // retargets the pointerup to the scroller, and the browser then fires
        // the click at the common ancestor of down and up — the scroller — so
        // a plain click never reached #pin-layer and nothing opened.
        scroller.setPointerCapture(e.pointerId);
        scroller.classList.add("dragging");
    }
    scroller.scrollLeft = drag.left - dx;
    scroller.scrollTop = drag.top - dy;
});

function endDrag() {
    if (!drag) return;
    swallowClick = drag.moved;
    drag = null;
    scroller.classList.remove("dragging");
}

scroller.addEventListener("pointerup", endDrag);
scroller.addEventListener("pointercancel", endDrag);

// The click that ends a drag lands on the scroller (captured, see above) or
// on the layer (browsers that keep the pointerdown target). Capture phase on
// the scroller sees both before anything else does, so the flag is always
// cleared here and can never swallow the next real click instead.
scroller.addEventListener("click", (e) => {
    if (!swallowClick) return;
    swallowClick = false;
    e.stopPropagation();
}, true);

// --- New registration: tap the drawing where it belongs ---------------------

// Only the layer itself. Pins are buttons on top of it and open their own
// detail sheet; a tap on one must not also start a new registration.
pinLayer.addEventListener("click", (e) => {
    if (e.target !== pinLayer) return;
    const rect = pinLayer.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width * 100).toFixed(3);
    const y = ((e.clientY - rect.top) / rect.height * 100).toFixed(3);
    htmx.ajax("GET", root.dataset.noteFormUrl, {
        target: "#note-sheet-body",
        swap: "innerHTML",
        values: { x, y, page: pageNum, drawing: root.dataset.drawingId },
    });
});

// --- Registration modal -----------------------------------------------------

document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "note-sheet-body" && e.detail.target.innerHTML.trim() !== "") {
        bootstrap.Modal.getOrCreateInstance(sheetEl).show();
    }
});

document.body.addEventListener("micki:close-sheet", () => {
    bootstrap.Modal.getOrCreateInstance(sheetEl).hide();
});

// --- Filter chips: faggruppe in the toolbar, status over the list -----------

const notesList = document.getElementById("notes-list");
const notesFilteredEmpty = document.getElementById("notes-filtered-empty");
const statusChips = [...document.querySelectorAll(".status-chip")];

/* One chip drives both views of the same data.
 *
 * The chips used to hide pins only, which left the list below the drawing
 * showing rows for trades you had just switched off — the page disagreed with
 * itself about what you were looking at.
 *
 * Filtering is client-side rather than a round trip: both sets are already in
 * the DOM, the drawing must not re-render to change which pins show, and on a
 * site tablet over mobile data a request per chip tap would be felt.
 */
function switchedOff(selector, key) {
    return new Set([...document.querySelectorAll(selector)].map((c) => c.dataset[key]));
}

function applyFilters() {
    const disciplines = switchedOff(".discipline-chip:not(.active)", "discipline");
    const states = switchedOff(".status-chip:not(.active)", "state");
    const hidden = (el) => disciplines.has(el.dataset.discipline) || states.has(el.dataset.state);

    pinLayer.querySelectorAll(".pin").forEach((pin) => {
        pin.classList.toggle("pin-hidden", hidden(pin));
    });

    const rows = notesList.querySelectorAll(".reg-row");
    let visible = 0;
    rows.forEach((row) => {
        const off = hidden(row);
        row.classList.toggle("d-none", off);
        if (!off) visible += 1;
    });

    // Only when rows exist but every one is filtered out. An empty drawing
    // already has its own message from the table's {% empty %} branch, and
    // two "nothing here" notices stacked would be worse than none.
    notesFilteredEmpty.classList.toggle("d-none", visible > 0 || rows.length === 0);
}

// Counted from the rows, which cover every page of the drawing, so the chips
// answer for the whole drawing rather than the page on screen.
function updateStatusCounts() {
    const rows = [...notesList.querySelectorAll(".reg-row")];
    statusChips.forEach((chip) => {
        chip.querySelector("[data-count]").textContent =
            rows.filter((row) => row.dataset.state === chip.dataset.state).length;
    });
}

document.querySelectorAll(".discipline-chip, .status-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        chip.classList.toggle("active");
        applyFilters();
    });
});

// Both halves are swapped in by HTMX after this script runs, and again on
// every save, so the filter has to be reapplied to whatever arrives.
pinLayer.addEventListener("htmx:afterSwap", applyFilters);
notesList.addEventListener("htmx:afterSwap", () => {
    updateStatusCounts();
    applyFilters();
});

// --- List below the viewer: tapping a row opens it, like tapping its pin ----

// The subject link keeps its href as the keyboard and open-in-new-tab path to
// the full page; a plain click on it is intercepted with the rest of the row.
// The page jump happens too, so the pin is in view once the modal closes.
notesList.addEventListener("click", (e) => {
    const row = e.target.closest(".reg-row");
    if (!row || !row.dataset.detailUrl) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    // Only when the pin is on another page: goTo always re-renders, and a
    // redraw behind the opening modal looks like a flicker.
    const page = parseInt(row.dataset.page, 10);
    if (page && page !== pageNum) goTo(page);
    htmx.ajax("GET", row.dataset.detailUrl, { target: "#note-sheet-body", swap: "innerHTML" });
});

// --- Hover: a pin and its row light up together ------------------------------

// The row's pin may be on another page, in which case there is nothing to
// light up; the row still highlights itself through the table's own hover.
function linkHover(container, selector, counterpartFor) {
    container.addEventListener("mouseover", (e) => {
        const el = e.target.closest(selector);
        if (!el || !container.contains(el)) return;
        counterpartFor(el)?.classList.add("is-linked");
    });
    container.addEventListener("mouseout", (e) => {
        const el = e.target.closest(selector);
        if (!el || el.contains(e.relatedTarget)) return;
        counterpartFor(el)?.classList.remove("is-linked");
    });
}

linkHover(pinLayer, ".pin", (pin) => notesList.querySelector(`.reg-row[data-pk="${pin.dataset.pk}"]`));
linkHover(notesList, ".reg-row", (row) => pinLayer.querySelector(`.pin[data-pk="${row.dataset.pk}"]`));

// --- Load the document --------------------------------------------------------

try {
    pdf = await pdfjsLib.getDocument(root.dataset.pdfUrl).promise;
    pageCount.textContent = pdf.numPages;
    status.classList.add("d-none");
    wrap.classList.remove("d-none");
    await renderPage();
} catch (err) {
    status.innerHTML = `<div class="alert alert-warning d-inline-block">Tegningen kunne ikke indlæses.<br><span class="small">${err.message}</span></div>`;
}
