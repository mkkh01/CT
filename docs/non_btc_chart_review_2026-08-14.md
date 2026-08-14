
## Reproduction

Selecting ETHUSDT initially left the chart header showing BTCUSDT while the request was still pending. After waiting for the asynchronous refresh to finish, the chart correctly changed to ETHUSDT and displayed candles. This indicates a UI race/feedback issue rather than a permanent backend data issue: the interface needs a visible loading state and should not leave the previous symbol's chart looking like the newly selected symbol is empty during the request.
