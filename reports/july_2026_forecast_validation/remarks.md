# CITIMART — July 2026 Net Sales Forecast Remarks

Period reviewed: July 1–27, 2026  
Metric: All-store net sales  
Residual definition: Actual − Forecast

## Executive conclusion

The supplied residuals are correct. Reconstructing each forecast as `actual − residual` reproduces the CITIMART app's Random Forest forecast within ₹0.50 per day; the tiny difference is only whole-rupee rounding.

The model performed well overall: actual sales were ₹14,254,874 against ₹13,925,715 forecast, a net underforecast of ₹329,159 (2.31%). However, this low total bias hides larger offsetting daily errors. July WAPE was 12.65%, daily MAE was ₹66,767, RMSE was ₹82,730, and R² was 0.78.

## Accuracy assessment

| Measure | July 1–27 result | Interpretation |
|---|---:|---|
| Actual net sales | ₹14,254,874 | Supplied actual total |
| Forecast net sales | ₹13,925,715 | Reconstructed forecast total |
| Net bias | +₹329,159 | Actual exceeded forecast by 2.31% |
| MAE | ₹66,767 | Average absolute daily miss |
| RMSE | ₹82,730 | Larger misses increased the error penalty |
| MAPE | 13.54% | Average daily percentage error |
| WAPE | 12.65% | Absolute error relative to total sales |
| R² | 0.78 | Forecast explained much of the daily variation |
| Actual/forecast correlation | 0.90 | Strong directional tracking |

Fourteen of 27 days were within 10% of actual and 22 were within 20%. Five days exceeded 25% absolute error. There were 13 underforecast days and 14 overforecast days, so the issue was not a permanent one-sided count bias.

## Main finding: mid-month level shift

The first 12 days were mostly stronger than forecast:

- July 1–12: actual ₹7,338,656; forecast ₹6,438,027.
- Net underforecast: ₹900,629.
- Ten of 12 days were underforecast.

The following 15 days were mostly weaker than forecast:

- July 13–27: actual ₹6,916,218; forecast ₹7,487,687.
- Net overforecast: ₹571,469.
- Twelve of 15 days were overforecast.

This indicates a level change after July 12. Because the 27-day forecast was generated recursively without feeding new July actuals back into the model, it could not adjust to the later slowdown. Weekly retraining or forecast refreshes would address this weakness.

## Weekly pattern

| Period | Actual | Forecast | Actual − Forecast | WAPE |
|---|---:|---:|---:|---:|
| July 1–7 | ₹4,221,404 | ₹3,714,078 | +₹507,326 | 12.19% |
| July 8–14 | ₹3,961,249 | ₹3,564,237 | +₹397,012 | 11.90% |
| July 15–21 | ₹3,179,154 | ₹3,576,716 | −₹397,562 | 12.51% |
| July 22–27 | ₹2,893,067 | ₹3,070,684 | −₹177,617 | 14.48% |

## Largest daily exceptions

| Date | Actual | Forecast | Error direction | Absolute % error |
|---|---:|---:|---|---:|
| July 20 | ₹294,572 | ₹432,083 | Overforecast by ₹137,511 | 46.68% |
| July 24 | ₹314,267 | ₹433,975 | Overforecast by ₹119,708 | 38.09% |
| July 16 | ₹352,637 | ₹472,085 | Overforecast by ₹119,448 | 33.87% |
| July 27 | ₹357,560 | ₹464,539 | Overforecast by ₹106,979 | 29.92% |
| July 1 | ₹629,716 | ₹453,764 | Underforecast by ₹175,952 | 27.94% |

The peak-sales dates were tracked directionally but understated. July 12 reached ₹974,170 and was underforecast by ₹148,513; July 5 reached ₹916,867 and was underforecast by ₹91,595. This makes peak-day replenishment and staffing the main operational risk.

## Model benchmark

Random Forest was correctly selected because it had the lowest chronological holdout RMSE among the five candidates. Historical holdout performance was 17.27% WAPE, ₹94,598 MAE, and 0.49 R². July's 12.65% WAPE, ₹66,767 MAE, and 0.78 R² were better, although the two evaluation windows have different sales conditions and should not be treated as directly identical experiments.

## Recommended remarks and actions

1. Keep Random Forest as the current baseline; the supplied forecast values reconcile to the app output and the model won the chronological validation comparison.
2. Refresh forecasts weekly—or more often when sales shift—so new actuals can correct the forecast level.
3. Use a ±20% daily planning tolerance for normal operations. Escalate dates outside that band for manual review.
4. Add promotion, holiday, payday, stock availability, store closure, weather, and local-event features to improve peak and exception days.
5. Create peak-day overrides for Sundays and known high-volume dates.
6. Monitor WAPE and MAE alongside signed bias. Total bias alone is misleading because positive and negative daily errors cancel.
7. Test store-level forecasts aggregated to the company total and compare them with the current all-store daily model.
8. Review the July 16, 20, 24, and 27 business conditions before retraining; these dates may contain operational events the current calendar-only features cannot explain.

## Caveats

- The 27 supplied rows are assumed to be July 1–27 in order.
- The historical workbook ends June 30, 2026, making July a genuine out-of-sample test.
- The app's displayed interval is a fixed ±1.96 × holdout RMSE band. All July actuals fall inside it, but the band is wide and is not a calibrated probabilistic interval.
- Whole-rupee residuals create negligible rounding differences from the app's unrounded forecasts.

Exact daily reconciliation is available in `daily_reconciliation.csv`; the candidate-model comparison is in `model_validation.csv`.
