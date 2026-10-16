# Four strategy agents, initial v1

These are deterministic, experimental trading rules, not validated profitable models. An agent is a separately versioned strategy with its own signals and trade attribution, running in the same local Python process. No paid model calls or Docker containers are necessary. Both **EURUSD** and **XAUUSD** run each rule. Gold is a metal CFD, not a currency pair.

All calculations use chronological **completed** broker candles; at least 120 candles are required (the bridge requests 240). EMA is seeded by the first period's simple mean then updated with alpha 2/(period+1). ATR14 is the simple mean of the last 14 true ranges, including gaps. These choices are frozen in v1; they are not Wilder ATR. Broker timestamps identify candles; they are not assumed UTC.

| Agent | Frame | Buy entry (sell is mirrored) | Initial stop | Initial target |
|---|---|---|---|---|
| Trend | H4 | EMA20 crosses above EMA50 on the latest completed candle | 2 ATR below signal close | 3 ATR above signal close |
| Breakout | M15 | Close exceeds previous 20 candle highs; previous close had not already exceeded its own preceding 20 candle highs | 1.5 ATR below close | 3 ATR above close |
| Pullback | H1 | EMA20 is above EMA50 on both latest candles; previous close was at/below EMA20 and latest closes back above EMA20 | 1.5 ATR below close | 3 ATR above close |
| Range reversion | M15 | Previous close below the lower band; latest recovers into the band below the mean; abs(EMA20−EMA50) < 0.5 ATR | 1.5 ATR below close | Frozen range mean |

The range band uses the **20 closes before both the excursion and recovery candles**, mean ±2 population standard deviations. A range signal requires at least 0.8 units of reward per unit of intended stop risk. There is no averaging down or adding to a losing trade.

The actual entry is the next eligible market quote, not the candle close. A move beyond 10% of the planned stop distance rejects the signal, as does a spread exceeding 8% of that distance. Stops are normalized to the instrument's tick size and checked again in MT5. These tolerances are deliberately restrictive and adjustable downward. Stops/targets remain fixed after entry. There is no trailing stop, time exit or news/calendar filter in this version; positions may remain open overnight and incur financing.

The coordinator records a signal once by strategy/version/symbol/candle. A rejected signal is not retried later on the same candle. A stable rotation based on candle time chooses between simultaneous candidates. One command may be unresolved at a time, and one position per instrument may be open; this avoids netting conflicts. When several candidates arrive together, only the accepted one is executed and other decisions remain in SQLite. All four strategies get opportunities but do not have independent brokerage balances.

Position size is calculated in the terminal using `OrderCalcProfit`, the **actual account currency**, broker minimum/maximum volume and step. A minimum lot that exceeds the risk allowance causes a rejection. The 10,000 starting balance reported by the user is not hard-coded. With 10,000 equity the default per-trade intended stop risk is 25 account-currency units; aggregate open stop risk is 50, and the daily loss threshold starts at 200. Market gaps, execution slippage, fees and financing can exceed these intended amounts.

`/stats` reports cumulative recorded deal P&L including deal commission/swap/fees, grouped by agent and symbol. It includes entry fees on positions that remain open and excludes unrealized P&L. Exit deals are attributed via the position identifier even if a phone/manual exit has magic=0. Brokerage-wide cash adjustments or standalone charges without a position link cannot be allocated reliably to agents. Daily recap is an account-equity observation plus explicitly cumulative strategy totals, not a clean independent-agent experiment.

Evaluate each strategy separately by instrument, costs, sample size, drawdown and market regime before changing rules. The research reports in `docs/research/` explain motivation and limitations. A successful software test or a short demo winning streak is not evidence of profitability.

Manual additions or netting reversals can retain an agent's original position identifier. Such mixed lifecycles are permanently excluded from strategy statistics and flagged for review; new entries are blocked while the mixed position remains open. A simple manual close of an otherwise clean position is still attributable.
