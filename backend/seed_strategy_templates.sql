INSERT INTO strategy_templates (
    name, strategy_type, side, leverage, total_capital,
    stage1_capital, stage2_capital, stage3_capital, stage4_capital,
    stage2_trigger_percent, stage3_trigger_percent, stage4_trigger_mode, stage4_trigger_percent,
    tp1_percent, tp2_percent, tp3_percent,
    tp1_qty_ratio, tp2_qty_ratio, tp3_qty_ratio,
    stop_loss_percent_of_capital, reentry_policy, is_active
) VALUES
('short_2x_trend','TREND_SHORT_PYRAMID','SHORT',2,1100,100,200,300,500,10,20,'LIQUIDATION_BUFFER',5,10,20,30,25,50,25,50,'manual_ready',TRUE),
('long_1x_pullback','PULLBACK_LONG_SCALEIN','LONG',1,1100,100,200,300,500,10,20,'PRICE_DOWN_PCT',20,10,20,30,25,50,25,50,'manual_ready',TRUE);
