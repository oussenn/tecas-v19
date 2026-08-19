import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

const SLIDE_MS = 380;

/**
 * Turn the card grid of the reviews and news blocks into a looping carousel:
 * one card per click of an arrow, and no end to reach in either direction.
 *
 * Progressive enhancement, deliberately: the markup of both blocks is stored
 * in the PAGE (see models/tecas_autosync.py), so changing their templates
 * would not reach the copy the homepage holds, and rewriting that copy is the
 * operation that used to throw away the client's own edits. The cards stay as
 * they are and the carousel is built around them at runtime.
 *
 * Without javascript the row is a plain horizontal scroller — that part is
 * css — so every card stays reachable either way.
 *
 * The loop is done by rotating the DOM rather than by counting positions:
 * going forward, the track slides one card left and the first card is then
 * moved to the end with the transform reset, which lands the row exactly where
 * it started. That has no beginning and no end to special-case, and it holds
 * for any number of cards.
 */
export class TecasCarousel extends Interaction {
    static selector = ".s_tecas_reviews, .s_tecas_news";

    setup() {
        this.track = this.el.querySelector(".row");
        this.frame = this.track && this.track.parentElement;
        this.clones = [];
        this.busy = false;
    }

    start() {
        if (!this.track || !this.frame || this.track.children.length < 2) {
            return;
        }
        this.originals = [...this.track.children];
        this.frame.classList.add("s_tecas_carousel", "s_tecas_carousel_ready");

        this.buttons = ["prev", "next"].map((way) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `s_tecas_carousel_arrow s_tecas_carousel_${way}`;
            button.setAttribute("aria-label", way === "prev" ? "Précédent" : "Suivant");
            button.innerHTML = `<span aria-hidden="true">${way === "prev" ? "‹" : "›"}</span>`;
            this.addListener(button, "click", () => this.slide(way));
            this.insert(button, this.frame, "beforeend");
            return button;
        });

        this.layout();
        this.addListener(window, "resize", this.debounced(() => this.layout(), 150));
    }

    destroy() {
        // The clones are runtime-only. Leaving them behind would let the
        // website editor save duplicated cards into the page.
        this.clones.forEach((el) => el.remove());
        this.clones = [];
        if (this.track) {
            this.track.style.transition = "";
            this.track.style.transform = "";
        }
        this.frame?.classList.remove("s_tecas_carousel", "s_tecas_carousel_ready");
    }

    /** Width of one card, gutters included — the cols carry theirs as padding. */
    get step() {
        const card = this.track.children[0];
        return card ? card.getBoundingClientRect().width : this.track.clientWidth;
    }

    layout() {
        this.fill();
        this.centreArrows();
    }

    /**
     * Centre the arrows on the CARDS, not on the block.
     *
     * They are positioned against the container, which also carries the title
     * and — in the reviews block — the Google badge. A plain top: 50% would
     * therefore hang them well below the cards. The row's own offset is the
     * only honest measure, and it moves with the viewport, hence the recompute
     * on resize.
     */
    centreArrows() {
        const middle = this.track.offsetTop + this.track.clientHeight / 2;
        for (const button of this.buttons) {
            button.style.top = `${middle - button.offsetHeight / 2}px`;
        }
    }

    /**
     * A loop needs one more card than fits on screen, or the space vacated by
     * the outgoing card slides in empty. Three news articles in a row that
     * shows three is exactly that case — which is why that block appeared to
     * do nothing at all.
     *
     * Copies are added a whole set at a time. That is what keeps a card and
     * its copy at least one full set apart, so the visible window can never
     * show the same article twice.
     */
    fill() {
        const step = this.step;
        if (!step) {
            return;
        }
        const visible = Math.max(1, Math.round(this.track.clientWidth / step));
        while (this.track.children.length < visible + 1) {
            for (const original of this.originals) {
                const clone = original.cloneNode(true);
                clone.setAttribute("aria-hidden", "true");
                clone.classList.add("s_tecas_carousel_clone");
                this.track.appendChild(clone);
                this.clones.push(clone);
            }
        }
    }

    slide(way) {
        // One card per click: ignoring a second click mid-slide is what keeps
        // the rotation and the transform in step.
        if (this.busy || this.track.children.length < 2) {
            return;
        }
        this.busy = true;
        const step = this.step;
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        if (way === "prev") {
            // Bring the last card round to the front and start one card to the
            // left, so the animation itself always runs the same way.
            this.track.prepend(this.track.lastElementChild);
            this.track.style.transition = "none";
            this.track.style.transform = `translateX(${-step}px)`;
            void this.track.offsetHeight;               // commit that position
            this.track.style.transition = reduced ? "none" : `transform ${SLIDE_MS}ms ease`;
            this.track.style.transform = "translateX(0)";
            this.waitForTimeout(() => { this.busy = false; }, reduced ? 0 : SLIDE_MS);
            return;
        }

        this.track.style.transition = reduced ? "none" : `transform ${SLIDE_MS}ms ease`;
        this.track.style.transform = `translateX(${-step}px)`;
        this.waitForTimeout(() => {
            this.track.style.transition = "none";
            this.track.appendChild(this.track.firstElementChild);
            this.track.style.transform = "translateX(0)";
            this.busy = false;
        }, reduced ? 0 : SLIDE_MS);
    }
}

registry.category("public.interactions").add(
    "tecas_website_blocks.carousel", TecasCarousel);
