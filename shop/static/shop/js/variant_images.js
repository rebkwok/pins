// Choosing an option (variant) with its own image shows it:
// - on the product page, the image carousel moves to it, then slides on as
//   usual (the carousel's slides and the options have data-image-id)
// - on a shop page card, the card's image switches to it (the options'
//   data-card-image), or back to the product's own for an option without one
(function () {
    function switchCardImage(select) {
        const card = select.closest(".shop-card");
        const img = card && card.querySelector(".shop-card__img");
        if (!img) {
            return;
        }
        // (the src as written, to put back)
        if (!img.dataset.productImage) {
            img.dataset.productImage = img.getAttribute("src");
        }
        const option = select.selectedOptions[0];
        img.setAttribute("src", (option && option.dataset.cardImage) || img.dataset.productImage);
    }

    document.addEventListener("change", function (event) {
        const select = event.target;
        if (select.matches(".shop-card select[name=variant_id]")) {
            switchCardImage(select);
            return;
        }
        if (!select.matches(".shop-product select[name=variant_id]")) {
            return;
        }
        const imageId = select.selectedOptions[0] && select.selectedOptions[0].dataset.imageId;
        const carousel = document.querySelector(".shop-product .shop-carousel");
        if (!imageId || !carousel || !window.bootstrap) {
            return;
        }
        const slides = [...carousel.querySelectorAll(".carousel-item")];
        const index = slides.findIndex((slide) => slide.dataset.imageId === imageId);
        if (index < 0) {
            return;
        }
        if (slides[index].classList.contains("active")) {
            return;
        }
        // (Bootstrap restarts its timer, so the image gets its full turn)
        bootstrap.Carousel.getOrCreateInstance(carousel).to(index);
    });
})();
