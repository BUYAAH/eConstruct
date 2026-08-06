const root = document.getElementById("viewer-root");
const wrap = document.getElementById("page-wrap");
const canvas = document.getElementById("pdf-canvas");
const status = document.getElementById("pdf-status");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const pageInput = document.getElementById("page-input");
const pageCount = document.getElementById("page-count");
const pinLayer = document.getElementById("pin-layer");
const addBtn = document.getElementById("add-note-btn");
const addHint = document.getElementById("add-note-hint");
const sheetEl = document.getElementById("note-sheet");

const pdfjsLib = await import(root.dataset.pdfjs);
pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.pdfjsWorker;

let pdf = null;
let pageNum = 1;
let rendering = false;
let addMode = false;

window.mickiCurrentPage = 1;

function updateControls() {
    prevBtn.disabled = pageNum <= 1;
    nextBtn.disabled = pageNum >= pdf.numPages;
    pageInput.value = pageNum;
    pageInput.max = pdf.numPages;
}

async function renderPage() {
    if (rendering) return;
    rendering = true;
    try {
        const page = await pdf.getPage(pageNum);
        const container = root.parentElement;
        const targetWidth = Math.min(container.clientWidth, 900);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = targetWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });
        const dpr = window.devicePixelRatio || 1;

        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        wrap.style.width = `${viewport.width}px`;
        wrap.style.height = `${viewport.height}px`;

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

// --- Add-note mode ----------------------------------------------------------

function setAddMode(on) {
    addMode = on;
    addBtn.classList.toggle("btn-warning", on);
    addBtn.classList.toggle("btn-primary", !on);
    addBtn.textContent = on ? "Annullér" : "+ Registrering";
    addHint.classList.toggle("d-none", !on);
    pinLayer.classList.toggle("add-mode", on);
}

addBtn.addEventListener("click", () => setAddMode(!addMode));

pinLayer.addEventListener("click", (e) => {
    if (!addMode || e.target !== pinLayer) return;
    const rect = pinLayer.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width * 100).toFixed(3);
    const y = ((e.clientY - rect.top) / rect.height * 100).toFixed(3);
    setAddMode(false);
    htmx.ajax("GET", root.dataset.noteFormUrl, {
        target: "#note-sheet-body",
        swap: "innerHTML",
        values: { x, y, page: pageNum, drawing: root.dataset.drawingId },
    });
});

// --- Bottom sheet -----------------------------------------------------------

document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "note-sheet-body" && e.detail.target.innerHTML.trim() !== "") {
        bootstrap.Offcanvas.getOrCreateInstance(sheetEl).show();
    }
});

document.body.addEventListener("micki:close-sheet", () => {
    bootstrap.Offcanvas.getOrCreateInstance(sheetEl).hide();
});

// --- Discipline filter chips -------------------------------------------------------

function applyDisciplineFilter() {
    const hidden = new Set(
        [...document.querySelectorAll(".discipline-chip:not(.active)")].map((c) => c.dataset.discipline)
    );
    pinLayer.querySelectorAll(".pin").forEach((pin) => {
        pin.classList.toggle("pin-hidden", hidden.has(pin.dataset.discipline));
    });
}

document.querySelectorAll(".discipline-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        chip.classList.toggle("active");
        applyDisciplineFilter();
    });
});

pinLayer.addEventListener("htmx:afterSwap", applyDisciplineFilter);

// --- List below the viewer: tapping a row jumps to its page ------------------

document.getElementById("notes-list").addEventListener("click", (e) => {
    const row = e.target.closest(".reg-row");
    if (row && row.dataset.page) goTo(parseInt(row.dataset.page, 10));
});

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
