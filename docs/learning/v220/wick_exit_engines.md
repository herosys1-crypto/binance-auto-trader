# v2.20 wick-vs-close trailing exit — journal replay

rows 2992 · dates 2026-08-16..2026-09-05 · CV cells = parity(e/o) x half(e=< 2026-08-26 / l) · engines: E0 house (SL-5/TP+15), E1 wick r5 (~live 15s mark poll), E1x wick+ambiguous same-bar, E2 close-only r5, E3 wick+close-confirm 3%p, E4 wick r3, E5 wick r8, E6 = E1 but SL judged on close only (fill at close). Trailing armed at ROI>=+5. SL on extremes in E0-E5.

### bottom_331 first fire (recomputed; matches dump) (LONG)

| group | engine | n(first) | mean | win% | TRAIL/TP% | SL% | TIME% | wick-unconf% | SL-unconf% | base | delta | n(all) | mean(all) | CV(ee/el/oe/ol) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| UP | E0_house_SL5_TP15 | 898 | +0.61 | 40.0 | 16.0 | 51.9 | 32.1 | 0.0 | 0.0 | +0.35 | +0.27 | 1660 | +0.42 | +1.23(194) / -0.04(218) / +1.35(225) / +0.06(261) |
| UP | E1_wick_r5 | 898 | +0.69 | 54.6 | 42.9 | 40.3 | 16.8 | 21.5 | 26.1 | +0.35 | +0.34 | 1660 | +0.56 | +1.09(194) / +0.45(218) / +1.23(225) / +0.13(261) |
| UP | E1x_wick_r5_ambig | 898 | +0.05 | 55.2 | 44.1 | 39.6 | 16.3 | 33.2 | 25.5 | -0.30 | +0.35 | 1660 | -0.07 | +0.18(194) / +0.03(218) / +0.41(225) / -0.34(261) |
| UP | E2_close_r5 | 898 | +0.54 | 44.2 | 30.6 | 45.9 | 23.5 | 0.0 | 29.3 | +0.20 | +0.34 | 1660 | +0.30 | +0.74(194) / -0.14(218) / +1.19(225) / +0.40(261) |
| UP | E3_wick_r5_closeconf3 | 898 | +0.67 | 51.7 | 42.9 | 40.3 | 16.8 | 0.0 | 26.1 | +0.30 | +0.37 | 1660 | +0.48 | +1.10(194) / +0.44(218) / +1.08(225) / +0.19(261) |
| UP | E4_wick_r3 | 898 | +0.85 | 55.3 | 47.1 | 39.5 | 13.4 | 19.9 | 25.4 | +0.41 | +0.44 | 1660 | +0.65 | +1.36(194) / +0.63(218) / +1.23(225) / +0.32(261) |
| UP | E5_wick_r8 | 898 | +0.44 | 41.5 | 33.3 | 42.4 | 24.3 | 18.2 | 27.4 | +0.24 | +0.20 | 1660 | +0.24 | +0.88(194) / -0.19(218) / +1.07(225) / +0.09(261) |
| UP | E6_wick_r5_SLclose | 898 | +1.19 | 62.7 | 49.8 | 30.4 | 19.8 | 23.8 | 0.0 | +0.57 | +0.62 | 1660 | +0.87 | +1.72(194) / +0.93(218) / +1.50(225) / +0.76(261) |
| UP | _fire_ | rows 1050 fired 898 (85.5%) | hours: {'0-1h': 9.4, '1-3h': 22.7, '3-6h': 18.0, '6-12h': 22.7, '12-24h': 27.2} | | | | | | | | | | | |
| DOWN | E0_house_SL5_TP15 | 920 | +1.06 | 46.1 | 14.0 | 45.4 | 40.5 | 0.0 | 0.0 | +0.17 | +0.89 | 1653 | +0.60 | +1.47(206) / +1.35(220) / +0.98(222) / +0.58(272) |
| DOWN | E1_wick_r5 | 920 | +0.75 | 57.3 | 41.7 | 37.5 | 20.8 | 20.1 | 23.3 | +0.17 | +0.59 | 1653 | +0.46 | +1.21(206) / +0.93(220) / +0.49(222) / +0.48(272) |
| DOWN | E1x_wick_r5_ambig | 920 | +0.18 | 57.4 | 42.6 | 37.4 | 20.0 | 29.0 | 23.2 | -0.35 | +0.53 | 1653 | -0.07 | -0.03(206) / +0.40(220) / +0.11(222) / +0.23(272) |
| DOWN | E2_close_r5 | 920 | +1.00 | 49.7 | 28.4 | 41.1 | 30.5 | 0.0 | 25.7 | +0.17 | +0.83 | 1653 | +0.52 | +1.02(206) / +1.32(220) / +1.03(222) / +0.70(272) |
| DOWN | E3_wick_r5_closeconf3 | 920 | +0.69 | 54.3 | 41.6 | 37.5 | 20.9 | 0.0 | 23.3 | +0.14 | +0.55 | 1653 | +0.40 | +1.13(206) / +1.06(220) / +0.28(222) / +0.40(272) |
| DOWN | E4_wick_r3 | 920 | +0.91 | 57.7 | 46.1 | 37.1 | 16.8 | 21.4 | 23.0 | +0.30 | +0.60 | 1653 | +0.60 | +0.90(206) / +1.10(220) / +0.88(222) / +0.78(272) |
| DOWN | E5_wick_r8 | 920 | +0.78 | 47.4 | 29.1 | 38.8 | 32.1 | 16.6 | 24.3 | +0.10 | +0.68 | 1653 | +0.42 | +1.08(206) / +1.01(220) / +0.67(222) / +0.46(272) |
| DOWN | E6_wick_r5_SLclose | 920 | +0.99 | 63.0 | 45.5 | 29.6 | 24.9 | 21.6 | 0.0 | +0.34 | +0.66 | 1653 | +0.72 | +1.82(206) / +0.93(220) / +0.82(222) / +0.57(272) |
| DOWN | _fire_ | rows 1050 fired 920 (87.6%) | hours: {'0-1h': 13.4, '1-3h': 21.4, '3-6h': 19.0, '6-12h': 25.0, '12-24h': 21.2} | | | | | | | | | | | |
| UP35_DOWN24 | E0_house_SL5_TP15 | 246 | +0.59 | 36.6 | 17.9 | 58.1 | 24.0 | 0.0 | 0.0 | -0.06 | +0.66 | 482 | +0.37 | +0.24(46) / +2.01(63) / +0.52(55) / -0.24(82) |
| UP35_DOWN24 | E1_wick_r5 | 246 | +0.49 | 52.8 | 48.0 | 45.5 | 6.5 | 22.0 | 26.4 | +0.14 | +0.36 | 482 | +0.32 | +1.35(46) / +1.12(63) / +0.62(55) / -0.55(82) |
| UP35_DOWN24 | E1x_wick_r5_ambig | 246 | -0.29 | 53.3 | 48.8 | 45.1 | 6.1 | 33.7 | 26.0 | -0.56 | +0.27 | 482 | -0.32 | -0.37(46) / +0.10(63) / +0.03(55) / -0.77(82) |
| UP35_DOWN24 | E2_close_r5 | 246 | +0.81 | 41.1 | 36.2 | 51.2 | 12.6 | 0.0 | 30.5 | +0.17 | +0.64 | 482 | +0.39 | +0.09(46) / +1.65(63) / +1.18(55) / +0.31(82) |
| UP35_DOWN24 | E3_wick_r5_closeconf3 | 246 | +0.47 | 49.6 | 48.0 | 45.5 | 6.5 | 0.0 | 26.4 | +0.05 | +0.42 | 482 | +0.26 | +1.16(46) / +1.28(63) / +0.60(55) / -0.64(82) |
| UP35_DOWN24 | E4_wick_r3 | 246 | +0.83 | 53.3 | 49.6 | 45.1 | 5.3 | 17.5 | 26.4 | +0.30 | +0.53 | 482 | +0.60 | +0.95(46) / +1.45(63) / +1.25(55) / -0.00(82) |
| UP35_DOWN24 | E5_wick_r8 | 246 | +0.44 | 39.0 | 39.0 | 48.0 | 13.0 | 17.5 | 28.0 | +0.05 | +0.39 | 482 | +0.25 | +1.01(46) / +1.31(63) / +0.37(55) / -0.51(82) |
| UP35_DOWN24 | E6_wick_r5_SLclose | 246 | +0.75 | 61.0 | 53.7 | 36.2 | 10.2 | 24.0 | 0.0 | +0.20 | +0.55 | 482 | +0.59 | +2.42(46) / +0.70(63) / +1.35(55) / -0.54(82) |
| UP35_DOWN24 | _fire_ | rows 273 fired 246 (90.1%) | hours: {'0-1h': 16.7, '1-3h': 16.7, '3-6h': 15.0, '6-12h': 25.2, '12-24h': 26.4} | | | | | | | | | | | |
| ALL | E0_house_SL5_TP15 | 2603 | +0.94 | 44.9 | 13.9 | 45.6 | 40.5 | 0.0 | 0.0 | +0.35 | +0.58 | 4659 | +0.64 | +1.34(568) / +0.81(634) / +1.17(616) / +0.56(785) |
| ALL | E1_wick_r5 | 2603 | +0.78 | 56.1 | 40.5 | 37.5 | 22.1 | 21.0 | 23.9 | +0.31 | +0.47 | 4659 | +0.57 | +1.25(568) / +0.68(634) / +0.81(616) / +0.49(785) |
| ALL | E1x_wick_r5_ambig | 2603 | +0.22 | 56.4 | 41.5 | 37.1 | 21.3 | 30.0 | 23.7 | -0.23 | +0.45 | 4659 | +0.05 | +0.26(568) / +0.25(634) / +0.26(616) / +0.13(785) |
| ALL | E2_close_r5 | 2603 | +0.86 | 48.4 | 27.7 | 41.3 | 31.0 | 0.0 | 26.4 | +0.29 | +0.58 | 4659 | +0.53 | +1.10(568) / +0.69(634) / +1.03(616) / +0.71(785) |
| ALL | E3_wick_r5_closeconf3 | 2603 | +0.77 | 53.5 | 40.3 | 37.5 | 22.2 | 0.0 | 24.0 | +0.28 | +0.50 | 4659 | +0.53 | +1.25(568) / +0.75(634) / +0.70(616) / +0.50(785) |
| ALL | E4_wick_r3 | 2603 | +0.87 | 56.6 | 45.1 | 37.0 | 17.9 | 21.0 | 23.6 | +0.38 | +0.49 | 4659 | +0.67 | +1.09(568) / +0.86(634) / +0.94(616) / +0.66(785) |
| ALL | E5_wick_r8 | 2603 | +0.74 | 45.6 | 28.8 | 39.0 | 32.2 | 16.7 | 25.0 | +0.23 | +0.51 | 4659 | +0.48 | +1.12(568) / +0.56(634) / +0.85(616) / +0.53(785) |
| ALL | E6_wick_r5_SLclose | 2603 | +1.12 | 62.3 | 44.9 | 28.5 | 26.6 | 22.6 | 0.0 | +0.48 | +0.64 | 4659 | +0.86 | +1.80(568) / +0.91(634) / +1.11(616) / +0.81(785) |
| ALL | _fire_ | rows 2992 fired 2603 (87.0%) | hours: {'0-1h': 11.2, '1-3h': 21.9, '3-6h': 19.0, '6-12h': 25.2, '12-24h': 22.7} | | | | | | | | | | | |

### confirm_peak_111 first fire (600 UP rows, date-stratified) (SHORT)

| group | engine | n(first) | mean | win% | TRAIL/TP% | SL% | TIME% | wick-unconf% | SL-unconf% | base | delta | n(all) | mean(all) | CV(ee/el/oe/ol) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| UP | E0_house_SL5_TP15 | 590 | -0.13 | 36.4 | 10.7 | 58.1 | 31.2 | 0.0 | 0.0 | -0.66 | +0.53 | 2076 | -0.44 | -1.12(130) / +0.23(143) / -0.87(151) / +1.01(166) |
| UP | E1_wick_r5 | 590 | -0.13 | 49.0 | 38.6 | 46.8 | 14.6 | 16.8 | 25.3 | -0.48 | +0.34 | 2076 | -0.03 | -1.02(130) / +0.37(143) / -1.46(151) / +1.33(166) |
| UP | E1x_wick_r5_ambig | 590 | -0.53 | 49.2 | 39.2 | 46.6 | 14.2 | 25.9 | 25.1 | -0.81 | +0.28 | 2076 | -0.51 | -1.17(130) / -0.15(143) / -1.79(151) / +0.79(166) |
| UP | E2_close_r5 | 590 | -0.52 | 39.7 | 23.1 | 52.0 | 24.9 | 0.0 | 28.8 | -0.68 | +0.16 | 2076 | -0.52 | -1.41(130) / -0.14(143) / -1.16(151) / +0.41(166) |
| UP | E3_wick_r5_closeconf3 | 590 | -0.30 | 44.7 | 38.6 | 46.8 | 14.6 | 0.0 | 25.3 | -0.56 | +0.26 | 2076 | -0.26 | -1.20(130) / +0.41(143) / -1.57(151) / +0.93(166) |
| UP | E4_wick_r3 | 590 | +0.29 | 49.3 | 42.2 | 46.4 | 11.4 | 14.1 | 25.1 | -0.26 | +0.55 | 2076 | +0.28 | -0.59(130) / +0.83(143) / -1.14(151) / +1.81(166) |
| UP | E5_wick_r8 | 590 | -0.31 | 38.1 | 26.4 | 48.3 | 25.3 | 13.6 | 26.1 | -0.69 | +0.38 | 2076 | -0.43 | -1.31(130) / +0.05(143) / -1.18(151) / +0.94(166) |
| UP | E6_wick_r5_SLclose | 590 | -0.19 | 54.4 | 43.2 | 40.2 | 16.6 | 18.6 | 0.0 | -0.52 | +0.34 | 2076 | -0.09 | -1.25(130) / +0.19(143) / -1.24(151) / +1.27(166) |
| UP | _fire_ | rows 600 fired 590 (98.3%) | hours: {'0-1h': 28.0, '1-3h': 19.7, '3-6h': 17.8, '6-12h': 25.6, '12-24h': 9.0} | | | | | | | | | | | |
| DOWN | E0_house_SL5_TP15 | 0 | | | | | | | | | | | | |
| DOWN | E1_wick_r5 | 0 | | | | | | | | | | | | |
| DOWN | E1x_wick_r5_ambig | 0 | | | | | | | | | | | | |
| DOWN | E2_close_r5 | 0 | | | | | | | | | | | | |
| DOWN | E3_wick_r5_closeconf3 | 0 | | | | | | | | | | | | |
| DOWN | E4_wick_r3 | 0 | | | | | | | | | | | | |
| DOWN | E5_wick_r8 | 0 | | | | | | | | | | | | |
| DOWN | E6_wick_r5_SLclose | 0 | | | | | | | | | | | | |
| DOWN | _fire_ | rows 0 fired 0 (None%) | hours: {} | | | | | | | | | | | |
| UP35_DOWN24 | E0_house_SL5_TP15 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E1_wick_r5 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E1x_wick_r5_ambig | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E2_close_r5 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E3_wick_r5_closeconf3 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E4_wick_r3 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E5_wick_r8 | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | E6_wick_r5_SLclose | 0 | | | | | | | | | | | | |
| UP35_DOWN24 | _fire_ | rows 0 fired 0 (None%) | hours: {} | | | | | | | | | | | |
| ALL | E0_house_SL5_TP15 | 590 | -0.13 | 36.4 | 10.7 | 58.1 | 31.2 | 0.0 | 0.0 | -0.66 | +0.53 | 2076 | -0.44 | -1.12(130) / +0.23(143) / -0.87(151) / +1.01(166) |
| ALL | E1_wick_r5 | 590 | -0.13 | 49.0 | 38.6 | 46.8 | 14.6 | 16.8 | 25.3 | -0.48 | +0.34 | 2076 | -0.03 | -1.02(130) / +0.37(143) / -1.46(151) / +1.33(166) |
| ALL | E1x_wick_r5_ambig | 590 | -0.53 | 49.2 | 39.2 | 46.6 | 14.2 | 25.9 | 25.1 | -0.81 | +0.28 | 2076 | -0.51 | -1.17(130) / -0.15(143) / -1.79(151) / +0.79(166) |
| ALL | E2_close_r5 | 590 | -0.52 | 39.7 | 23.1 | 52.0 | 24.9 | 0.0 | 28.8 | -0.68 | +0.16 | 2076 | -0.52 | -1.41(130) / -0.14(143) / -1.16(151) / +0.41(166) |
| ALL | E3_wick_r5_closeconf3 | 590 | -0.30 | 44.7 | 38.6 | 46.8 | 14.6 | 0.0 | 25.3 | -0.56 | +0.26 | 2076 | -0.26 | -1.20(130) / +0.41(143) / -1.57(151) / +0.93(166) |
| ALL | E4_wick_r3 | 590 | +0.29 | 49.3 | 42.2 | 46.4 | 11.4 | 14.1 | 25.1 | -0.26 | +0.55 | 2076 | +0.28 | -0.59(130) / +0.83(143) / -1.14(151) / +1.81(166) |
| ALL | E5_wick_r8 | 590 | -0.31 | 38.1 | 26.4 | 48.3 | 25.3 | 13.6 | 26.1 | -0.69 | +0.38 | 2076 | -0.43 | -1.31(130) / +0.05(143) / -1.18(151) / +0.94(166) |
| ALL | E6_wick_r5_SLclose | 590 | -0.19 | 54.4 | 43.2 | 40.2 | 16.6 | 18.6 | 0.0 | -0.52 | +0.34 | 2076 | -0.09 | -1.25(130) / +0.19(143) / -1.24(151) / +1.27(166) |
| ALL | _fire_ | rows 600 fired 590 (98.3%) | hours: {'0-1h': 28.0, '1-3h': 19.7, '3-6h': 17.8, '6-12h': 25.6, '12-24h': 9.0} | | | | | | | | | | | |

## Live code (what the real trailing/force-SL compares)
- `app/services/risk_service.py:575-590` evaluate_take_profit_level: mark price = Redis `get_mark_price` (stream cache) at each call; pnl_ratio computed from that single sample.
- `risk_service.py:606` + `:898-945` `_update_peak_pnl`: peak = max(current sample, Redis stored, DB max_profit_pct) -> peak is the max of the 15 s samples (sub-bar).
- `risk_service.py:826-839` fires TRAILING_TP when `pnl_ratio <= peak - retrace` at any sample (Fix 335: armed after any TP partial, value-independent).
- `risk_service.py:421-433` force SL uses the same per-poll mark price. `risk_constants.py:81` FORCE_SL_ROI_DEFAULT=5, `:127` TRAILING_RETRACE_PCT=5.
- `app/workers/scheduler_runner.py:599` tp_sl job = IntervalTrigger(seconds=15).
=> Live is a 15-second mark-price sampler, i.e. intra-bar / wick-sensitive, NOT a bar-close engine. E1 (bar extremes) is the upper bound of that sensitivity.

## Findings
1. Wick-only exits exist: in E1, 17-22% of first-fire trades exit on a trailing wick the close did not confirm (LONG ALL 21.0%, SHORT UP 16.8%), and a further 24-29% exit on an SL wick the close did not confirm.
2. Removing them does not help. LONG ALL: E1 +0.78 / E3 (wick + close-confirm 3%p) +0.77 / E2 (close only) +0.86 -> +0.08, and E2 vs E1 by CV cell = ee 1.10 vs 1.25 (wick), el 0.69 vs 0.68 (tie), oe 1.03 vs 0.81 (close), ol 0.71 vs 0.49 (close): 2/4. LONG UP the wick engine is better (+0.69 vs +0.54). LONG DOWN close is better (+1.00 vs +0.75).
3. SHORT is the opposite of the spec claim: E1 -0.13 / E3 -0.30 / E2 -0.52 (n=590). Close-only trailing is worse by 0.39 per trade and worse in 3/4 CV cells; the unconfirmed wick on a SHORT is usually the start of the next leg against you in this regime.
4. The retrace width matters more than wick-vs-close: r3 > r5 > r8 on both sides (LONG ALL +0.87/+0.78/+0.74; SHORT UP +0.29/-0.13/-0.31). Grid 3/5/8 pre-declared; best cell optimistic. E4 on LONG ALL passes 4/4 cells (+1.09/+0.86/+0.94/+0.66, n=2603, base +0.38) but on SHORT only 2/4. Conflicts with 2026-09-01 real-trade finding (5 best) -> shadow, not adopt.
5. The house engine E0 (hard TP +15, no trailing) is the best LONG engine (ALL +0.94, 4/4 cells, DOWN +1.06) - trailing from +5 caps the winners that the +15 TP lets run. On SHORT E0 = E1 (-0.13).
6. E6 (SL judged on close) gains +0.34 on LONG (ALL +1.12, 4/4) but loses on SHORT (-0.19 vs -0.13) and its worst fill is -25.1 ROI (mean SL fill -6.14 vs -5.00): side-asymmetric = up-drift regime, not "wick noise". Shadow only.
7. E1x (ambiguous same-bar case counted as a fire) drops LONG ALL to +0.22 and SHORT to -0.53: the result is sensitive to intra-bar path assumptions, so the E1/E2/E3 differences (<0.1 on LONG) are inside model error.
