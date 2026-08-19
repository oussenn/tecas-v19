import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * Turn the card grid of the reviews and news blocks into a horizontal
 * scroller with arrows on either side.
 *
 * Progressive enhancement, deliberately: the markup of both blocks is stored
 * in the PAGE (see models/tecas_autosync.py), so changing their templates
 * would not reach the copy the homepage holds, and rewriting that copy is
 * exactly the operation that used to throw away the client's own edits. The
 * cards stay as they are and the scroller is built around them at runtime, so
 * this works on the homepage, on any other page the blocks are dropped on, and
 * on copies that were edited by hand.
 *
 * Without javascript the row is still a scroller — that part is css — so the
 * cards past the third are reachable by touch or trackpad either way. The
 * arrows are the addition, and they only appear when there is something to
 * scroll to.
 */
export class TecasCarousel extends Interaction {
    static selector = ".s_tecas_reviews, .s_tecas_news";

    setup() {
        this.track = this.el.querySelector(".row");
        this.frame = this.track && this.track.parentElement;
        this.buttons = [];
    }

    start() {
        if (!this.track || !this.frame || this.track.children.length < 2) {
            return;
        }
        this.frame.classList.add("s_tecas_carousel");
        this.buttons = ["prev", "next"].map((way) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `s_tecas_carousel_arrow s_tecas_carousel_${way}`;
            button.setAttribute(
                "aria-label", way === "prev" ? "Précédent" : "Suivant");
            button.innerHTML = `<span aria-hidden="true">${way === "prev" ? "‹" : "›"}</span>`;
            this.addListener(button, "click", () => this.scrollOne(way));
            this.insert(button, this.frame, "beforeend");
            return button;
        });
        this.addListener(this.track, "scroll", () => this.refresh());
        this.addListener(window, "resize", () => this.refresh());
        this.refresh();
    }

    /** One card, gap included — falls back to most of the visible width. */
    get step() {
        const card = this.track.children[0];
        if (!card) {
            return this.track.clientWidth;
        }
        const gap = parseFloat(getComputedStyle(this.track).columnGap) || 0;
        return Math.max(card.getBoundingClientRect().width + gap,
                        this.track.clientWidth * 0.5);
    }

    scrollOne(way) {
        this.track.scrollBy({
            left: way === "prev" ? -this.step : this.step,
            behavior: "smooth",
        });
    }

    /**
     * Arrows appear only when they lead somewhere. Three news cards fill the
     * row exactly on a desktop, and an arrow that cannot move is worse than no
     * arrow at all; the same row on a phone shows one card and does scroll.
     */
    refresh() {
        const max = this.track.scrollWidth - this.track.clientWidth;
        // Sub-pixel layout rounding leaves a stray pixel or two of "scrollable"
        // on a row that visibly fits, so this needs a tolerance, not > 0.
        const scrollable = max > 2;
        this.frame.classList.toggle("s_tecas_carousel_active", scrollable);
        const [prev, next] = this.buttons;
        prev.disabled = !scrollable || this.track.scrollLeft <= 2;
        next.disabled = !scrollable || this.track.scrollLeft >= max - 2;
    }
}

registry.category("public.interactions").add(
    "tecas_website_blocks.carousel", TecasCarousel);
