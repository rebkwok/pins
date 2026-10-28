// The checkout form: the "Which country?" field (with the UK-only shipping
// note) only when the address's country is "Other". (Without JavaScript, it's
// always shown.) The order summary: collapsed on phones, so the form is in
// view (the customer has just seen the basket); always open on wider screens,
// where it's beside the form.
(function () {
    const wide = window.matchMedia("(min-width: 992px)");

    function setSummary() {
        const summary = document.querySelector(".checkout-summary");
        if (summary) {
            summary.open = wide.matches;
        }
    }

    document.addEventListener("DOMContentLoaded", setSummary);
    wide.addEventListener("change", setSummary);

    function update() {
        const country = document.getElementById("id_country");
        const other = document.querySelector(".shop-other-country");
        if (country && other) {
            other.hidden = country.value !== "other";
        }
    }

    document.addEventListener("DOMContentLoaded", update);
    document.addEventListener("change", function (event) {
        if (event.target.id === "id_country") {
            update();
        }
    });
})();
