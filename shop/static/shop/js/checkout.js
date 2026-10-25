// The checkout form: the "Which country?" field (with the UK-only shipping
// note) only when the address's country is "Other". (Without JavaScript, it's
// always shown.)
(function () {
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
