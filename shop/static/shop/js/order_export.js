// Orders admin: download the ticked orders. Ticking the box at the top of the
// list downloads all the orders shown (on every page), with any filters.
(function () {
    function rowCheckboxes() {
        return [...document.querySelectorAll("[data-order-select]")];
    }

    function selection() {
        const selectAll = document.querySelector("[data-order-select-all]");
        if (selectAll && selectAll.checked) {
            const download = document.querySelector("[data-order-download]");
            return { all: true, ids: [], count: Number(download.dataset.total) };
        }
        const ids = rowCheckboxes()
            .filter((checkbox) => checkbox.checked)
            .map((checkbox) => checkbox.value);
        return { all: false, ids, count: ids.length };
    }

    function update() {
        const { all, count } = selection();
        const orders = `order${count === 1 ? "" : "s"}`;
        document.querySelectorAll("[data-order-export]").forEach((button) => {
            button.disabled = count === 0;
            const label = button.querySelector("[data-order-export-label]");
            const format = label.dataset.orderExportLabel;
            if (count === 0) {
                label.textContent = `Download (${format})`;
            } else if (all) {
                label.textContent = `Download all ${count} ${orders} (${format})`;
            } else {
                label.textContent = `Download ${count} ${orders} (${format})`;
            }
        });
    }

    document.addEventListener("change", (event) => {
        const selectAll = document.querySelector("[data-order-select-all]");
        if (event.target === selectAll) {
            rowCheckboxes().forEach((checkbox) => {
                checkbox.checked = selectAll.checked;
            });
        } else if (event.target.matches("[data-order-select]") && selectAll) {
            // Unticking an order means only the ticked orders
            if (!event.target.checked) {
                selectAll.checked = false;
            }
        } else {
            return;
        }
        update();
    });

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-order-export]");
        if (!button || button.disabled) {
            return;
        }
        const { all, ids } = selection();
        const params = new URLSearchParams(window.location.search);
        params.delete("p");
        params.delete("order");
        params.set("export", button.dataset.orderExport);
        if (!all) {
            ids.forEach((id) => params.append("order", id));
        }
        window.location.href = `${window.location.pathname}?${params}`;
    });

    // The CSV button is only added to the page when its menu opens, and the
    // results (and checkboxes) are replaced when filtering
    document.addEventListener("w-dropdown:shown", update);
    document.addEventListener("w-swap:success", update);
})();
