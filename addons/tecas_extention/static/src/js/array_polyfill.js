/** @odoo-module **/

// Safe polyfill for Chrome 109 (Windows 7) - only toReversed is needed by Odoo 19 HistoryPlugin
// We patch Array.prototype only if missing, no other methods touched
(function() {
    if (typeof Array.prototype.toReversed === 'undefined') {
        Object.defineProperty(Array.prototype, 'toReversed', {
            value: function toReversed() {
                return Array.prototype.slice.call(this).reverse();
            },
            writable: true,
            configurable: true,
            enumerable: false  // critical: non-enumerable so for...in loops are unaffected
        });
    }
})();
