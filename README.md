# How to use

This is a focused fix bundle, not a full repo mirror.

Replace these files in the CT project:

- `main.py`
- `Core/trade_monitor.py`

Then run the service again and watch for:
- startup banner
- database / redis health checks
- Telegram polling confirmation
- live price summaries
- candle-close analysis events
- periodic scanner runs every 30 minutes

The most important behavioral change is the scanner timer fix. Before this fix, candle events kept resetting the timer and the periodic scanner never fired.
