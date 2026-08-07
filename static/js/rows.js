/* Whole-row navigation for data tables.
 *
 * A <tr> can't be wrapped in an <a>, so a row carries data-row-href and this
 * follows it on click. It is a mouse convenience only: every such row also
 * holds a real anchor in its first meaningful cell, and that stays the
 * keyboard and screen-reader path. Removing this file would cost the click
 * target, not the ability to reach the page.
 */
document.addEventListener("click", (event) => {
    const row = event.target.closest("[data-row-href]");
    if (!row) return;

    // Let anything already interactive handle its own click — the subject
    // link, a delete button, a checkbox.
    if (event.target.closest("a, button, input, label, select, textarea")) return;

    // Don't navigate out from under someone selecting text in a cell.
    if (window.getSelection().toString()) return;

    const href = row.dataset.rowHref;

    // Honour the usual open-in-new-tab gestures, which window.location eats.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
        window.open(href, "_blank", "noopener");
        return;
    }
    window.location = href;
});
