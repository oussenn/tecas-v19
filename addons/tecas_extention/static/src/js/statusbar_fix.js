/** @odoo-module **/

import { whenReady } from "@odoo/owl";

// Chrome 109 / Windows 7 — clip-path ::before covers button text
// Fix: inject inline styles directly on every arrow button after render

function fixStatusbarButtons() {
    document.querySelectorAll('.o_arrow_button:not(.d-none)').forEach(btn => {
        // Force the button to establish a stacking context
        btn.style.setProperty('position', 'relative', 'important');
        btn.style.setProperty('z-index', '1', 'important');
        btn.style.setProperty('overflow', 'visible', 'important');

        // Force all spans above the ::before pseudo-element
        btn.querySelectorAll('span').forEach(span => {
            span.style.setProperty('position', 'relative', 'important');
            span.style.setProperty('z-index', '99', 'important');
            span.style.setProperty('display', 'inline', 'important');
        });

        // Active state
        if (btn.classList.contains('o_arrow_button_current')) {
            btn.style.setProperty('color', '#ffffff', 'important');
            btn.querySelectorAll('span').forEach(span => {
                span.style.setProperty('color', '#ffffff', 'important');
            });
        }
    });
}

// Run on initial load
whenReady(() => {
    // Use MutationObserver to catch every time statusbar renders
    const observer = new MutationObserver(() => {
        if (document.querySelector('.o_arrow_button')) {
            fixStatusbarButtons();
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Also run immediately
    fixStatusbarButtons();
});
