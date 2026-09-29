# Backtest report `bt_7102412ef0109c46`

> Research output of a personal analytics engine. Paper mode only. Not betting advice. Historical performance does not guarantee anything.

## FACT - data and setup

- Competitions: ITA1
- Test window: 1995-07-01 -> 2025-06-30  (burn-in for calibration from 1992-07-01)
- Final holdout starts: 2025-07-01 (used: False)
- Dataset fingerprint: `15f94fcc1a17ce21` | code: `d31076301368` | experiment: `exp_74997e2fc19c8371`
- Sources: engsoccerdata, openfootball, statsbomb
- Fixtures evaluated: 10734 | predictions per model: {'climatology': 10733, 'dixon_coles': 10733, 'elo': 10733, 'poisson': 10733, 'poisson_weighted': 10733}
- Decision-time policies: {'start_of_match_day': 6174, 'kickoff_minus_lead': 4560}
- Runtime: 811.0s
- NOTE: 1 match(es) with disputed scores excluded from evaluation

## MODEL OUTPUT - probability quality (out-of-sample, walk-forward)

| model | probs | n | log loss | Brier | RPS | mean ECE | slope H | slope D | slope A |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| climatology | calibrated | 10733 | 1.0646 | 0.6432 | 0.2222 | 0.0125 | 0.82 | 0.53 | 0.93 |
| climatology | raw | 10733 | 1.0645 | 0.6431 | 0.2222 | 0.0110 | 0.90 | 0.59 | 0.92 |
| dixon_coles | calibrated | 10733 | 0.9846 | 0.5877 | 0.1953 | 0.0169 | 1.01 | 0.86 | 1.06 |
| dixon_coles | raw | 10733 | 0.9846 | 0.5877 | 0.1953 | 0.0169 | 1.01 | 0.86 | 1.06 |
| elo | calibrated | 10733 | 0.9839 | 0.5864 | 0.1948 | 0.0180 | 0.95 | 0.64 | 1.02 |
| elo | raw | 10733 | 0.9820 | 0.5865 | 0.1948 | 0.0192 | 0.96 | 0.73 | 1.02 |
| poisson | calibrated | 10733 | 0.9911 | 0.5916 | 0.1968 | 0.0236 | 1.00 | 0.81 | 1.06 |
| poisson | raw | 10733 | 0.9912 | 0.5915 | 0.1968 | 0.0255 | 1.00 | 0.93 | 1.07 |
| poisson_weighted | calibrated | 10733 | 0.9869 | 0.5889 | 0.1955 | 0.0216 | 1.02 | 0.79 | 1.08 |
| poisson_weighted | raw | 10733 | 0.9874 | 0.5890 | 0.1956 | 0.0258 | 1.02 | 0.92 | 1.09 |

Lower is better for log loss / Brier / RPS / ECE; calibration slope 1.0 is ideal.

## UNCERTAINTY - paired comparisons (log loss, block bootstrap by week)

| comparison | mean diff | 95% CI | P(first better) | n |
|---|---:|---|---:|---:|
| climatology_vs_elo | +0.0807 | [+0.0715, +0.0890] | 0.00 | 10733 |
| dixon_coles_vs_climatology | -0.0801 | [-0.0868, -0.0730] | 1.00 | 10733 |
| dixon_coles_vs_elo | +0.0006 | [-0.0042, +0.0048] | 0.37 | 10733 |
| elo_vs_climatology | -0.0807 | [-0.0890, -0.0715] | 1.00 | 10733 |
| poisson_vs_climatology | -0.0735 | [-0.0803, -0.0665] | 1.00 | 10733 |
| poisson_vs_elo | +0.0072 | [+0.0018, +0.0121] | 0.01 | 10733 |
| poisson_weighted_vs_climatology | -0.0777 | [-0.0845, -0.0705] | 1.00 | 10733 |
| poisson_weighted_vs_elo | +0.0030 | [-0.0022, +0.0076] | 0.11 | 10733 |

Negative mean diff = first model has lower log loss.

## MODEL OUTPUT - per season (calibrated probabilities, log loss)

| season | climatology | dixon_coles | elo | poisson | poisson_weighted |
|---|---:|---:|---:|---:|---:|
| 1995 | 1.0099 | 0.9356 | 0.9334 | 0.9330 | 0.9373 |
| 1996 | 1.0593 | 1.0145 | 1.0028 | 1.0234 | 1.0252 |
| 1997 | 1.0721 | 0.9764 | 0.9782 | 0.9935 | 0.9815 |
| 1998 | 0.9996 | 0.9730 | 0.9744 | 0.9796 | 0.9745 |
| 1999 | 1.0431 | 0.9792 | 0.9565 | 0.9898 | 0.9885 |
| 2000 | 1.0611 | 0.9973 | 0.9960 | 1.0112 | 1.0017 |
| 2001 | 1.0682 | 0.9978 | 0.9955 | 1.0106 | 1.0029 |
| 2002 | 1.0570 | 1.0067 | 0.9882 | 1.0076 | 1.0122 |
| 2003 | 1.0831 | 0.9590 | 0.9699 | 0.9701 | 0.9664 |
| 2004 | 1.0714 | 1.0526 | 1.0356 | 1.0630 | 1.0592 |
| 2005 | 1.0627 | 0.9556 | 0.9536 | 0.9585 | 0.9554 |
| 2006 | 1.0646 | 0.9891 | 0.9714 | 1.0032 | 0.9846 |
| 2007 | 1.0625 | 1.0007 | 0.9960 | 1.0068 | 1.0059 |
| 2008 | 1.0427 | 0.9809 | 0.9836 | 0.9804 | 0.9831 |
| 2009 | 1.0473 | 1.0077 | 1.0012 | 1.0088 | 1.0079 |
| 2010 | 1.0606 | 1.0145 | 1.0202 | 1.0187 | 1.0147 |
| 2011 | 1.0672 | 1.0194 | 1.0135 | 1.0276 | 1.0222 |
| 2012 | 1.0627 | 0.9916 | 0.9873 | 0.9946 | 0.9921 |
| 2013 | 1.0555 | 0.9659 | 0.9585 | 0.9753 | 0.9663 |
| 2014 | 1.0976 | 1.0413 | 1.0450 | 1.0516 | 1.0456 |
| 2015 | 1.0639 | 0.9877 | 0.9852 | 0.9862 | 0.9867 |
| 2016 | 1.0490 | 0.9244 | 0.9175 | 0.9303 | 0.9221 |
| 2017 | 1.0704 | 0.9118 | 0.9296 | 0.9126 | 0.9111 |
| 2018 | 1.0794 | 0.9695 | 1.0302 | 0.9717 | 0.9715 |
| 2019 | 1.0744 | 0.9886 | 0.9853 | 0.9951 | 0.9862 |
| 2020 | 1.0822 | 0.9492 | 0.9492 | 0.9580 | 0.9523 |
| 2021 | 1.0871 | 0.9896 | 0.9930 | 0.9945 | 0.9921 |
| 2022 | 1.0802 | 0.9937 | 0.9906 | 1.0076 | 0.9953 |
| 2023 | 1.0889 | 0.9860 | 0.9860 | 0.9958 | 0.9886 |
| 2024 | 1.0905 | 0.9733 | 0.9782 | 0.9740 | 0.9762 |

## ESTIMATE - calibration choices (selected on earlier out-of-sample seasons only)

- climatology: {'identity': 31, 'dirichlet': 2}
- dixon_coles: {'identity': 33}
- elo: {'identity': 31, 'dirichlet': 1, 'ovr_isotonic': 1}
- poisson: {'identity': 31, 'dirichlet': 2}
- poisson_weighted: {'identity': 30, 'dirichlet': 3}

## MARKET DATA - paper betting simulation

> Decisions below are *hypothetical*: they assume the model had passed the market-benchmark gate. In live paper mode a model that has not passed it cannot produce candidates (MODEL_NOT_VALIDATED_VS_MARKET).

- Not available: no market odds in the data for the test window

## INTERPRETATION (conservative, generated from the intervals above)

- dixon_coles: beats the league base-rate baseline (log-loss diff -0.0801, 95% CI [-0.0868, -0.0730]).
- elo: beats the league base-rate baseline (log-loss diff -0.0807, 95% CI [-0.0890, -0.0715]).
- poisson: beats the league base-rate baseline (log-loss diff -0.0735, 95% CI [-0.0803, -0.0665]).
- poisson_weighted: beats the league base-rate baseline (log-loss diff -0.0777, 95% CI [-0.0845, -0.0705]).
- MARKET BENCHMARK UNAVAILABLE: the data used contains no odds for this window, so it is impossible to say whether any model adds information beyond the market. No betting conclusion can be drawn.
- elo: sequential calibration made out-of-sample log loss WORSE by 0.0019; the raw probabilities are preferable for this model.
- poisson_weighted: sequential calibration improved out-of-sample log loss by 0.0005.

---
A losing prediction does not mean the model was wrong; a profitable backtest does not mean it is valid. Model quality (calibration, log loss) and decision performance (CLV, P/L) are reported separately on purpose.
