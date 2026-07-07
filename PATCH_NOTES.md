# Modified Decision Engine Patch

This bundle contains the edited decision engine logic.

## What changed

- Added a unified decision trace with explicit boolean checks:
  - score >= threshold
  - quality >= threshold
  - confidence >= threshold
  - probability >= threshold
  - risk <= max_risk
  - htf_alignment
  - smc_required
  - regime_allowed
  - strategy_valid
  - rr_ok

- Printed the trace before the final verdict is returned.
- Unified the rejection reasons and final verdict around the same checks.
- Prevented `get_trade_params()` from treating non-BUY sides as SELL by default.
- Kept `OrderBlock` inside SMC presence detection for diagnostics.

## Notes

This environment could not clone the full GitHub repository directly, so the zip is a patch bundle centered on the edited strategy engine file.
