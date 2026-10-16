# Forex and gold strategy research for prediction-engine

Research date: 16 October 2026. Status: research proposal, not an implemented or validated trading system.

## Confirmed brief and current state

- Use `https://github.com/cuppucino/prediction-engine.git`. Cloned into the selected workspace; the remote repository was empty.
- Focus exclusively on EUR/USD and XAU/USD, with Telegram as the user interface and no frontend. The user's latest selection expands the original forex-only scope to include gold CFDs.
- The intended product executes automatically and sends updates through Telegram.
- Live broker: OANDA MT5, server `OANDA_Global-Live-1` (OANDA Global Markets). The user has no Windows VPS.
- Start locally on the user's Mac. A VPS is optional for later unattended operation, not a prerequisite for development, backtesting or local demo execution with a compatible MT5 connection.
- The user has now created an OANDA demo account and is using MT5 mobile. Its actual server and contract settings have not been inspected. The earlier `MetaQuotes-Demo` account is not the intended validation environment.
- Compare intraday and swing strategies before selecting the first trading policy.
- Start directly with OANDA demo execution once the local connector and execution controls work; separate simulated wallets are optional. The user proposes a local workspace of strategy agents and asks to test Telegram group inputs; see the [strategy-agent lab research](STRATEGY_AGENT_LAB_RESEARCH.md) for the current architecture proposal and access constraints.
- Account currency, intended capital and risk tolerance remain unconfirmed. Instrument selection is EUR/USD and XAU/USD only.

The supplied [MT5 adaptation guide](/Users/admin/moopredict-ai/docs/MT5_FOREX_ADAPTATION_GUIDE.md) is background material, not authorization to implement its instructions or place trades. This research does not activate execution, connect an account or buy hosting.

MooPredict's [paper-trader runbook](/Users/admin/moopredict-ai/docs/INTRADAY_PAPER_TRADER.md) and [forecast experiment](/Users/admin/moopredict-ai/docs/FOUR_HOUR_PAPER_EXPERIMENT.md) describe useful patterns: immutable forecasts, versioned strategies, durable Telegram delivery, persistent positions, and separate measurement of forecasts and net trading results. These are documented patterns to consider reusing; their implementation has not been audited here. The stock strategy, position sizing and market calendar should not transfer unchanged.

## Recommendation

Start with a transparent **swing trend baseline** and one **intraday session-breakout challenger**, with risk budgets and costs recorded explicitly. Direct OANDA demo testing can begin once the connector, frozen rules and execution controls are verified; historical validation can proceed alongside it and is not a prerequisite for starting demo tests. Shared-account strategy results are conditional on the coordinator's allocation policy. Select a strategy from evidence, including the possibility that neither qualifies.

The later multi-agent proposal retains these as core baselines while considering additional pullback and range workers in a shared local evaluation harness. The [agent-lab research](STRATEGY_AGENT_LAB_RESEARCH.md) distinguishes separate simulated portfolios from actual shared-account demo execution and proposes a controlled comparison with and without permitted Telegram inputs. The initial worker count and full implementation design remain open.

My provisional preference is slower trend trading because it is easier to audit and makes fewer execution decisions. This is an engineering and research priority, not a finding that it will be profitable. Overnight financing can reverse the ranking.

Research EUR/USD and XAU/USD only, following the user's updated selection. A small universe limits the search space, but the selection itself does not establish an edge. Treat each instrument's results separately; an acceptable EUR/USD result must not automatically authorize the same strategy on gold.

### EUR/USD and XAU/USD: separate instrument policies

XAU/USD represents gold priced in US dollars and is offered in OANDA's metals CFD category. It is not a second currency pair. OANDA Global Markets currently lists different trading schedules: forex trades from 17:05 to 16:59 New York time, with a daily six-minute break; XAU/USD trades from 18:05 to 16:59, implying a longer daily closure. Use the actual symbol session schedule and holiday notices rather than one shared forex timer. [OANDA Global Markets trading hours](https://www.oanda.com/bvi-en/cfds/hours-of-operation/).

OANDA's current help table lists minimum MT5 sizes of 0.01 lots for FX CFDs and 0.001 lots for gold CFDs. These are published reference values, not verified settings for the user's accounts. Read each symbol's contract size, tick size/value, volume step/minimum, stop constraints and financing from MT5 before sizing. Equal lots or equal numerical stop distances do not mean equal monetary risk. [OANDA minimum sizes](https://help.oanda.com/bvi/en/faqs/minimum-trade-size.htm), [MT5 symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).

Proposed research matrix:

| Instrument | Swing trial | Intraday trial | Required separation |
|---|---|---|---|
| EUR/USD | Daily trend baseline, with a separately registered H4 variant | M15 session-range breakout | FX contract, spreads, financing and session calendar |
| XAU/USD | Independently evaluated daily trend baseline; H4 variant if justified | Independently evaluated M15 breakout; do not assume the FX session choice is optimal | Gold contract, spreads, financing, daily closure and volatility |

Use a common strategy interface and equal planned monetary risk when comparing results, with separate execution/cost settings and scorecards. Estimate stops from each instrument's own volatility, not copied pip values. Stress simultaneous losses and shared USD sensitivity; do not assume stable correlation or diversification merely because the instruments differ. The reviewed FX-specific research does not establish an XAU/USD edge. Currency carry/value portfolios below remain background research outside the initial two-instrument scope.

## Strategy comparison

The rule sketches below are proposals to test. Their parameter choices and timeframes are not validated by the cited literature.

| Strategy | Mechanism and candidate horizon | Evidence and applicability | Main failure modes | Priority |
|---|---|---|---|---|
| Time-series trend | Follow a pair's own established direction using completed daily bars; later test an H4 variant | Stronger historical evidence for the broad family, mainly much slower and more diversified than a retail bot | Choppy reversals, financing, concentrated currency exposure | First baseline |
| Session breakout | Trade a completed M15 break of a range fixed before London activity, optionally aligned with H1 trend | Plausible, testable intraday hypothesis; no reviewed source proves this exact setup at OANDA | False breaks, news jumps, spreads, delayed fills | First challenger |
| Range mean reversion | Fade a large deviation from a rolling mean when prior data suggests a stable range; M15/H1 | Price reversal evidence does not imply profitable retail execution | Sustained trends, intervention, costs consuming a small target | Later experiment |
| Carry | Hold currencies with attractive financing relative to funding currencies; days to months | Historical currency portfolio evidence, with material crash risk; retail swaps differ from institutional carry | Sudden unwinds, broker financing markups, leverage | Later, conditional on actual swaps |
| Value / relative strength | Long undervalued or stronger currencies against weaker ones; weeks to months | Currency portfolio research exists, but needs broader data and careful construction | Slow convergence, macro regime changes, overlapping exposures | Later |
| ML trade filter | Estimate which already-defined setups are worth taking; same horizon as the underlying strategy | A modeling option, not an independent demonstrated edge | Leakage, small samples, overfitting, false probability claims | Only after credible baselines |

### What the strongest evidence actually says

Moskowitz, Ooi and Pedersen document return persistence over roughly one to twelve months across futures and forwards, including currencies. Their diversified historical result motivates testing trend following; it does **not** validate a daily channel rule, an H4 moving-average crossover, this two-instrument portfolio or today's retail execution. [Original paper, *Time Series Momentum*](https://fairmodel.econ.yale.edu/ec439/mosk.pdf).

Neely and Weller's intraday FX study found no excess returns for its tested rules after realistic transaction costs and trading hours. This is older evidence, not a universal impossibility theorem; it makes cost-sensitive testing essential. [Federal Reserve Bank of St. Louis paper](https://fraser.stlouisfed.org/docs/publications/frbsl_wp/1999-016.pdf).

Krohn, Mueller and Whelan's published 2024 study documents intraday reversals around FX fixings, but finds that the tested liquidity-demanding reversal returns become negative after transaction costs. It distinguishes customer trading from earning a premium as a liquidity provider. This is a concrete reason to keep generic RSI/Bollinger mean reversion out of the first release; those indicators are not replications of the fixing strategy. [*Foreign Exchange Fixings and Returns around the Clock*, section E/Table X](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13306).

Carry research documents crash risk and abrupt unwinds, rather than risk-free interest income. Value and cross-sectional momentum research includes currencies, but does not establish short-horizon retail profitability. These belong to broader portfolio research outside the initial EUR/USD–XAU/USD engine; gold financing is not a replication of currency carry. [Brunnermeier, Nagel and Pedersen](https://www.nber.org/papers/w14473), [Asness, Moskowitz and Pedersen](https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere).

For ML, the proposed first experiment is a modest classifier trained on the net outcomes of a frozen baseline's candidate trades. Prior volatility, observed spread, session and scheduled-event proximity are possible features. Start with logistic regression, compare against taking every baseline signal at comparable risk, and measure calibration on later data. This is our research proposal, not a literature-backed claim of FX alpha; rejecting trades can remove the few large winners that make a trend strategy work.

### Candidate A: slower trend baseline

An intentionally simple first trial could use:

1. A long signal when the completed D1 close exceeds the highest high of the previous 50 completed daily bars; a short signal below their lowest low. Exclude the signal bar from that range.
2. Entry at the first eligible executable quote after the signal, outside maintenance/news/spread blackouts. Apply a documented expiry and price-deviation limit.
3. An initial stop two times the prior completed 20-day average true range from the actual entry price, subject to the agreed risk budget and broker constraints.
4. A long exit after a completed close below the previous 20-day low, with the mirror rule for shorts; the protective stop remains active between daily decisions. No fixed profit target in this baseline.
5. At most one position per pair, no averaging down, and a shared currency-exposure limit.

This trial can hold for days to weeks; it is not constrained to a two-day holding period. Record all financing. Fix weekend handling before testing. An H4 version or forced shorter holding period is a separate trial, not an unnoticed modification. A slower monthly momentum benchmark can help distinguish failure of the trend family from failure of this implementation.

### Candidate B: intraday session breakout

An illustrative challenger could freeze a range from 00:00 to 07:00 `Europe/London`, then consider completed M15 closes outside it during a predefined morning entry window. A simple H1 trend filter may be tested as a separate registered variant.

Define the stop, target, maximum holding time and end-of-day exit before running the trial. For example, a one-ATR stop and two-risk-unit target are test inputs, not established optimal settings. Enter only after the signal bar completes, at an executable bid/ask quote. Expire stale signals and cap entries per pair/session. Never give a retrospective fill at the range boundary after observing a close beyond it.

This is a London-clock range, not a claim to reproduce a fixed Tokyo session throughout the year. Test whether the range rule adds value over a simple trend rule at the same intraday horizon. Start without numerous indicator confirmations; every additional threshold increases the search space.

### Intraday versus swing

| Consideration | Intraday | Swing |
|---|---|---|
| Cost sensitivity | More entries and smaller targets make spread/slippage proportionally important | Fewer entries, but overnight financing accumulates |
| Data requirement | Historical bid/ask or ticks strongly preferred for execution validation | Daily/H4 bars can screen ideas; execution still needs realistic quotes and costs |
| Operations | Frequent decisions; quote delays and outages can invalidate signals quickly | Fewer decisions; protective orders and reconciliation still require reliable operation |
| News and weekends | Can avoid planned releases and finish flat, but cannot avoid all surprise events | Carries overnight/event exposure; weekend policy must be explicit |
| Evidence transfer | Reviewed intraday evidence is cautionary | Broad trend literature is more supportive, but slower than most proposed retail rules |
| Research decision | Keep as a challenger until net results justify complexity | Preferred first baseline, subject to financing and validation |

## OANDA MT5 and hosting

The reported live server matches OANDA's documented Global Markets server. OANDA's official API documentation says the v20 account/API is unavailable to **OANDA Global Markets and OANDA TMS BROKERS S.A.** Therefore v20 is not an execution shortcut for this user's current live account. [OANDA MT5 server guide](https://help.oanda.com/bvi/en/faqs/mt5-user-guide-bvi.htm), [OANDA API introduction](https://developer.oanda.com/rest-live-v20/introduction/).

The user reports creating an OANDA demo account and using MT5 mobile. Before broker-specific tests, verify that the selected account is the intended demo, expected on the documented `OANDA_Global-Demo-1` server, and compare its specifications with the live account. The earlier `MetaQuotes-Demo` account's pricing and settings must not substitute for OANDA's. Demo execution remains a simulation. [OANDA MT5 guide](https://help.oanda.com/bvi/en/faqs/mt5-user-guide-bvi.htm).

MT5 mobile is the user's account-monitoring/manual-trading client, not the host for this Python engine. OANDA describes automated Expert Advisors running on an internet-connected computer; the Python integration likewise needs the desktop terminal/runtime. This computer can be local: renting a VPS is not required. Telegram can provide updates/controls while MT5 mobile shows the same account. [OANDA automation instructions](https://help.oanda.com/bvi/en/faqs/mt5-user-guide-bvi.htm), [MT5 Python integration](https://www.mql5.com/en/docs/python_metatrader5).

The agreed development direction is local first and direct demo execution: build the strategy workers and Telegram controls on the Mac, validate a compatible local MT5 connection, and route their orders through a demo-only execution coordinator. Historical backtests and local simulation are useful parallel or later research, not mandatory earlier phases. A Windows environment hosting the official Python package or a separately tested MQL5 bridge are connection options to investigate; neither is configured yet. Continuous local automation requires the relevant computer, terminal and engine to stay running and connected. Consider a VPS later only if the user wants operation independent of their computer.

OANDA Global Markets documents MT5 servers `OANDA_Global-Live-1` and `OANDA_Global-Demo-1`, supports Expert Advisors, and offers a Mac terminal installer. A Mac terminal installer is not evidence of native macOS support for the Python package. The currently listed official `MetaTrader5` wheels target Windows x86-64, and the integration communicates with a terminal. [OANDA MT5 guide](https://help.oanda.com/bvi/en/faqs/mt5-user-guide-bvi.htm), [MetaTrader5 package](https://pypi.org/project/metatrader5/), [Python integration](https://www.mql5.com/en/docs/python_metatrader5).

| Option | Assessment for this project |
|---|---|
| Develop and backtest on the Mac using exported history | Selected starting approach; local engine, simulation and Telegram can be developed without a VPS |
| Local Windows x64 PC with MT5 + Python engine | Direct local option for the official Python integration if available |
| Full Windows VPS with MT5 + Python engine | Optional later hosting for operation independent of the user's computer; not required to start |
| Local Windows VM / Wine-based environment | Possible investigation, but terminal launch alone does not prove Python IPC works; validate the exact CPU/OS/runtime combination |
| Native MQL5 Expert Advisor | An alternative architecture with execution in MT5 and a separate research/reporting service; more integration work if models remain Python |
| OANDA REST API | Unavailable for the confirmed OANDA Global Markets account under the current v20 documentation |

MetaTrader's integrated virtual hosting migrates terminal charts, Expert Advisors and indicators. Treat it as a different product from a general Windows VPS; do not assume it can host the Python engine and database. [MetaTrader virtual-hosting documentation](https://www.metatrader5.com/en/terminal/help/virtual_hosting/virtual_hosting_migration).

## Corrections to the supplied migration guide

| Guide assumption | Research correction / proposed handling |
|---|---|
| Fixed EST and MYT session windows | Use UTC internally and named timezones (`America/New_York`, `Europe/London`, `Asia/Kuala_Lumpur`). Derive DST-aware windows and load entity-specific broker holidays/maintenance. |
| Forex has no daily close | OANDA Global Markets publishes a daily FX break and a longer closure for XAU/USD. Validate the actual symbol sessions and holidays; gold cannot use the FX schedule unchanged. |
| A universal 15-minute news buffer and predictable pip jump | Treat event buffers as conservative configurable policies, not proven sufficient protection. Releases and press conferences can require distinct windows. Unscheduled news remains possible. |
| Spread must be below 1.5 times its average | Test both an absolute limit and a session-conditioned relative limit. Also compare total cost with stop/target distance; a historically normal spread can still make a trade unattractive. |
| $10 per pip per lot and 0.01 lot minimum everywhere | Read contract size, tick size/value, volume minimum/step, account currency and conversion. Compute loss in account currency; skip trades that cannot fit minimum size within the risk budget. |
| Fixed commission and Wednesday triple swap | Use the user's actual pricing and historical financing where available. Swap direction, holidays and instrument rules matter; do not apply today's rate unchanged across years. |
| Hardcoded IOC filling | Discover permitted modes and check return codes/partial fills. OANDA Global's guide currently describes IOC for market execution, but other accounts/symbols must be checked. |
| Tick volume is a reliable substitute for exchange volume | Treat it as activity on the observed feed. Test its incremental value; do not relabel a tick-weighted indicator as consolidated market VWAP or import stock volume thresholds. |
| `confidence: 0.78` implies a 78% success chance | Keep a score separate from a probability. A probability needs a defined outcome, horizon and held-out calibration. |

Sources: [OANDA Global hours and instrument schedules](https://www.oanda.com/bvi-en/cfds/hours-of-operation/), [OANDA Global financing](https://help.oanda.com/bvi/en/faqs/financing-costs.htm), [MT5 symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), [account-currency profit calculation](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py).

MT5's Python bar API identifies bar zero as the current bar and limits history to what is available in the terminal. Its documentation specifies UTC tick/bar timestamps. Use completed bars, validate historical coverage, and test the adapter's time conversion against known sessions. [Bar indexing](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py), [bar range/time documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py).

Scheduled news is knowable in advance: use provider calendars and verify major events against [Federal Reserve calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) and [BLS schedules](https://www.bls.gov/schedule/news_release/), plus the relevant central banks/statistical agencies for each currency. The guide's contrast with known earnings dates is misleading. MQL5 economic-calendar functions use trade-server time and require a separate adapter or MQL5 bridge; they are not listed among the standard Python integration functions. [MQL5 calendar](https://www.mql5.com/en/docs/calendar), [Python API list](https://www.mql5.com/en/docs/python_metatrader5).

## Proposed engine boundaries and Telegram behavior

This is a proposed direction, not a completed architecture specification:

`broker data → validated completed bars → versioned strategy → risk/cost checks → execution adapter → persistent trade ledger → Telegram`

The same strategy should run in historical replay, paper simulation and broker demo. Execution adapters account for differences; broker demo fills are still not proof of live execution quality.

- Strategy output: signal ID, pair, long/short/flat, observation time, expiry, strategy version, entry conditions, stop, exit policy, input provenance and reason codes.
- Risk layer: equity-based sizing, broker minimum/step rounding down, margin checks, portfolio exposure, daily equity-loss halt, spread/news/rollover gates. EUR/USD and XAU/USD require separate instrument limits plus a combined loss/exposure cap; simultaneous long positions must not be treated as independent bets without evidence.
- Execution: broker-side protective stop where supported, one order owner, durable intent before submission, order/position reconciliation after timeout or restart, and no blind retry that can duplicate a trade.
- Telegram: `/status`, `/positions`, `/why`, `/stats`, `/pause`, `/resume`; pause prevents new entries while protection and monitoring continue. A separate explicit emergency-close command can be designed later.
- Reports: entries/exits with costs and reasons, rejected setups, stale data/disconnections, daily net P&L and drawdown, and weekly strategy comparisons. State demo/live and strategy version clearly.
- Access: allowlisted Telegram user/chat IDs; deduplicate commands and expire stale ones. Keep bot and broker secrets outside messages and Git.

Telegram long polling supports this interface without building a public website. Persist the update offset and use a durable outbound queue; transport retries must never become trade retries. These reliability choices build on MooPredict's documented pattern. [Telegram Bot API](https://core.telegram.org/bots/api#getupdates).

An LLM can explain structured decisions and summarize news. It should not invent prices, probabilities, lot sizes or change a production policy from a transcript. If transcript learning returns later, store suggestions as research candidates that undergo the same evaluation.

## How to decide whether a strategy qualifies

These are proposed research controls, not claims that any trial has passed:

Trying many configurations and selecting the best backtest creates a selection problem, even when the winning chart looks convincing. Bailey and coauthors formalize this in [*The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). Keep an experiment ledger and report uncertainty using time blocks rather than pretending correlated trades are independent observations.

1. **Register each trial.** Freeze its rules, parameters, pair universe, holding policy, costs and primary metric before inspecting test results. Keep losing trials in the ledger.
2. **Audit data.** Check timestamps, gaps, duplicates, price sides, symbol changes and executable sessions. Prefer the intended OANDA feed. A different provider can screen a hypothesis but cannot validate OANDA fills.
3. **Validate chronologically.** Train/tune only on earlier periods, evaluate later periods, and reserve a final untouched period. Remove samples whose future outcome windows cross a split; fit preprocessing/calibration on training data only. Split related pairs together in time.
4. **Simulate executable prices.** Buys enter at ask and close at bid; shorts reverse this. Add commissions, slippage and applicable financing. Do not charge an extra full spread if bid/ask fills already include it. Use ticks/lower-resolution data for stop/target ordering; otherwise apply a documented conservative assumption when both occur in a candle.
5. **Compare fair baselines.** Include no trade, a simple trend rule, and the identical setup without each added filter. Compare strategies at equal planned portfolio risk. Measure each candidate independently before combining them.
6. **Measure net outcomes.** Net expectancy, drawdown, profit factor, turnover, total costs, exposure, tail losses and uncertainty by time/pair/regime. Win rate alone cannot select a strategy. Report missing and unresolved records, not just completed winners.
7. **Stress assumptions.** Test worse spreads/slippage, financing changes, delayed entry, missing quotes, calendar changes and connection restarts. Examine sensitivity around parameters rather than celebrating one optimum.
8. **Run forward demo.** Freeze a version, compare observed signals/fills with replay, verify protection/recovery and retain all results. Set a sample-size and precision target from observed variability; a few profitable weeks or a magic trade count do not prove an edge.

For prediction outputs, score direction/range/calibration separately from realized trading results. If a classifier filters trades, compare it against the unfiltered rule on the same opportunity set, including rejected trades. Promotion should require credible net improvement and operational correctness, not an attractive confidence score.

## Decisions still needed

The next design depends on account currency and intended capital. The OANDA demo has been created; its connection and contract settings still need verification before forward execution tests. Agree the maximum acceptable drawdown, per-trade/portfolio exposure and overnight/weekend policy. Development starts locally; a VPS budget is not a prerequisite. Instrument scope is fixed to EUR/USD and XAU/USD. Financial settings cannot be inferred from the old MooPredict account, its $100 paper balance or an arbitrary large default demo balance.

No broker history has been collected and no strategy backtest has been run in this research task. The next useful deliverable is a reproducible comparison of the two registered candidates using the intended account's data and costs.
