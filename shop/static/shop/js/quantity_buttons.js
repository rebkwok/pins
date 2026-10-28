// The shop's product forms. The quantity -/+ buttons: disable "-" at 1 and "+" at the most that can be
// added (the quantity field's max in the basket, or if the server said it
// couldn't be increased; otherwise the selected variant's data-available on the
// shop and product pages). The server still checks (stock
// may have changed since the page loaded), and says if it can't increase.
// Also what's in the basket from the product ("N in your basket").
(function () {
    function maxQuantity(input) {
        if (input.max) {
            return Number(input.max);
        }
        const variant = input.form && input.form.querySelector("[name=variant_id]");
        const option = variant && variant.tagName === "SELECT" ? variant.selectedOptions[0] : variant;
        if (option && option.dataset.available !== undefined) {
            return Number(option.dataset.available);
        }
        return null;
    }

    function update(group) {
        const input = group.querySelector("input.quantity");
        if (!input) {
            return;
        }
        const max = maxQuantity(input);
        let value = Number(input.value) || 1;
        if (max !== null && max > 0 && value > max) {
            // e.g. a variant with less stock was chosen
            value = max;
            input.value = value;
        }
        const fewer = group.querySelector("[aria-label=Fewer]");
        const more = group.querySelector("[aria-label=More]");
        if (fewer) {
            fewer.disabled = value <= 1;
        }
        if (more) {
            more.disabled = max !== null && value >= max;
        }
    }

    // What's in the basket from this product (the variants' data-in-basket):
    // "N in your basket", or with a choice of variants, which ones, e.g. "In
    // your basket: Black, S × 1, Black, L × 2" (whichever is selected)
    function setNote(note, text) {
        if (note) {
            note.hidden = !text;
            note.querySelector("a").textContent = text;
        }
    }

    function updateInBasket(form) {
        // the variants: the drop-down's options, the one variant's input, or
        // if it's out of stock, an input for each
        const variants = [...form.querySelectorAll("[data-in-basket]")];
        const inBasket = variants.filter((variant) => Number(variant.dataset.inBasket || 0) > 0);
        const total = inBasket.reduce((sum, variant) => sum + Number(variant.dataset.inBasket), 0);
        let text = "";
        if (variants.length > 1 && inBasket.length) {
            text = "In your basket: " + inBasket
                .map((variant) => `${variant.dataset.name} × ${variant.dataset.inBasket}`)
                .join(", ");
        } else if (total) {
            text = `${total} in your basket`;
        }
        setNote(form.querySelector(".shop-in-basket"), text);
        // a shop page card on phones, where the form is hidden: just the total
        const card = form.closest(".shop-card");
        setNote(
            card && card.querySelector(".shop-in-basket--compact"),
            total ? `${total} in your basket` : ""
        );
    }

    function updateAll() {
        document.querySelectorAll(".input-group.quantity").forEach(update);
        document.querySelectorAll("form.shop-form").forEach(updateInBasket);
    }

    document.addEventListener("DOMContentLoaded", updateAll);
    // after htmx replaces a quantity field or the variant options
    document.addEventListener("htmx:afterSettle", updateAll);
    // choosing another variant (its own limit replaces any max the server
    // gave for the previous one), or typing a quantity
    document.addEventListener("change", function (event) {
        if (event.target.matches("select[name=variant_id]")) {
            const input = event.target.form.querySelector("input.quantity");
            if (input) {
                input.removeAttribute("max");
            }
            updateAll();
        }
    });
    document.addEventListener("input", function (event) {
        if (event.target.matches("input.quantity")) {
            update(event.target.closest(".input-group.quantity"));
        }
    });
})();
