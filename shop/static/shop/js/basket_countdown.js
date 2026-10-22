// Count down the basket's time left (#countdown) every second, from the
// seconds left that the server gave when it was last checked (so the visitor's
// clock doesn't matter). htmx checks the server every minute, replacing
// #countdown, and when the countdown reaches 0 ("countdown-ended").
(function () {
    function tick() {
        const countdown = document.getElementById("countdown");
        if (!countdown) {
            return;
        }
        if (countdown.dataset.deadline === undefined) {
            // New from the server
            countdown.dataset.deadline =
                Date.now() + Number(countdown.dataset.secondsLeft) * 1000;
        }
        const secondsLeft = Math.max(
            0, Math.ceil((Number(countdown.dataset.deadline) - Date.now()) / 1000)
        );
        countdown.textContent = `${Math.floor(secondsLeft / 60)}m ${secondsLeft % 60}s`;
        if (secondsLeft === 0 && countdown.dataset.ended === undefined) {
            countdown.dataset.ended = "true";
            htmx.trigger(countdown, "countdown-ended");
        }
    }
    setInterval(tick, 1000);
})();
