// The product's edit page in the admin: show only the stock fields that apply.
// - "No stock limit" and "Variants share stock" can't both be ticked: ticking
//   one disables the other (the form also checks this).
// - The shared stock is only used if the variants share stock.
// - Each variant's own stock is only used if neither is ticked. (For a saved
//   product that shares stock or has no limit, the variants' stock fields
//   aren't in the form; they appear once it's saved with neither ticked.)
(function () {
    function wrapper(input) {
        return input && input.closest("[data-field-wrapper]");
    }

    // the field with its label, to hide it
    function panel(input) {
        return input && (input.closest(".w-panel__wrapper") || wrapper(input));
    }

    function setNote(checkbox, text) {
        const field = wrapper(checkbox);
        if (!field) {
            return;
        }
        let note = field.querySelector(".shop-stock-note");
        if (!note) {
            note = document.createElement("p");
            note.className = "help shop-stock-note";
            field.appendChild(note);
        }
        note.textContent = text;
        note.hidden = !text;
    }

    function update() {
        const unlimited = document.getElementById("id_unlimited_stock");
        const shares = document.getElementById("id_shares_stock");
        if (!unlimited || !shares) {
            return;
        }
        shares.disabled = unlimited.checked;
        unlimited.disabled = shares.checked;
        setNote(shares, unlimited.checked ? "Not used: the product has no stock limit." : "");
        setNote(unlimited, shares.checked ? "Untick 'Variants share stock' to use this." : "");

        const sharedStock = panel(document.getElementById("id_stock"));
        if (sharedStock) {
            sharedStock.hidden = !shares.checked || unlimited.checked;
        }
        document.querySelectorAll("input[name^='variants-'][name$='-stock']").forEach((input) => {
            const field = panel(input);
            if (field) {
                field.hidden = shares.checked || unlimited.checked;
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (!document.getElementById("id_unlimited_stock")) {
            return;
        }
        update();
        document.addEventListener("change", function (event) {
            if (event.target.id === "id_unlimited_stock" || event.target.id === "id_shares_stock") {
                update();
            }
        });
        // variants added with "Add variant"
        const variants = document.getElementById("id_variants-FORMS");
        if (variants) {
            new MutationObserver(update).observe(variants, { childList: true });
        }
    });
})();
