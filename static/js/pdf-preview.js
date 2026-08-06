/* Read-only PDF preview pane.
 *
 * Deliberately NOT viewer.js: that one is wired to the pin/note system and
 * needs #note-sheet, #notes-list, layer chips and htmx to exist. This renders
 * a page and nothing else.
 *
 * Driven by data attributes on a [data-pdf-preview] container, so it isn't
 * bound to one hardcoded document.
 */

const root = document.querySelector("[data-pdf-preview]");
if (root) init(root);

async function init(root) {
    const canvas = root.querySelector("[data-pdf-canvas]");
    const statusEl = root.querySelector("[data-pdf-status]");
    const prevBtn = root.querySelector("[data-pdf-prev]");
    const nextBtn = root.querySelector("[data-pdf-next]");
    const label = root.querySelector("[data-pdf-page]");

    let pdf = null;
    let pageNum = 1;
    let rendering = false;

    async function render() {
        if (!pdf || rendering) return;
        rendering = true;
        try {
            const page = await pdf.getPage(pageNum);
            const host = canvas.parentElement;
            // Fit to the pane, minus its padding; floor at something sane so a
            // collapsed container can't produce a zero-width canvas.
            const avail = Math.max(host.clientWidth - 24, 160);
            const base = page.getViewport({ scale: 1 });
            const viewport = page.getViewport({ scale: avail / base.width });
            const dpr = window.devicePixelRatio || 1;

            canvas.width = Math.floor(viewport.width * dpr);
            canvas.height = Math.floor(viewport.height * dpr);
            canvas.style.width = `${viewport.width}px`;
            canvas.style.height = `${viewport.height}px`;

            await page.render({
                canvasContext: canvas.getContext("2d"),
                viewport,
                transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
            }).promise;

            prevBtn.disabled = pageNum <= 1;
            nextBtn.disabled = pageNum >= pdf.numPages;
            label.textContent = `${pageNum} / ${pdf.numPages}`;
        } finally {
            rendering = false;
        }
    }

    function goTo(n) {
        if (!pdf) return;
        pageNum = Math.min(Math.max(1, n), pdf.numPages);
        render();
    }

    prevBtn.addEventListener("click", () => goTo(pageNum - 1));
    nextBtn.addEventListener("click", () => goTo(pageNum + 1));

    let resizeTimer = null;
    window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(render, 200);
    });

    try {
        const pdfjsLib = await import(root.dataset.pdfjs);
        pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.pdfjsWorker;
        pdf = await pdfjsLib.getDocument(root.dataset.pdfUrl).promise;
        statusEl.classList.add("d-none");
        canvas.classList.remove("d-none");
        await render();
    } catch (err) {
        statusEl.innerHTML =
            `<div class="alert alert-warning d-inline-block mb-0">Kunne ikke indlæse PDF'en.` +
            `<br><span class="small">${err.message}</span></div>`;
    }
}
