
# Dashboard blank diagnosis — 2026-08-12

## Root cause

The deployed `/dashboard/api/overview` endpoint returned HTTP 200 with populated `overview`, `events`, symbols, capital, prices, and `websocket_connected=true`. The blank UI was therefore not caused by the bot state or API. Static parsing of the deployed inline JavaScript with Node reported `SyntaxError: Unexpected token ')'` in `renderCycle`, in the `wsError` ternary expression. Because the script failed to parse, `refresh()` never ran and all cards remained `—`.

## Fix verification

The extra closing parenthesis was removed from `wsError`. Node syntax check now passes, the full Python test suite passes (`23 passed`), and the local browser now shows `آخر تحديث` plus populated KPI cards after the public fetch. The deployed service must be redeployed with this template fix.
