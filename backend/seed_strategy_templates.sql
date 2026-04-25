-- =============================================================================
-- 구 4단계 템플릿 (호환용, stage1~4 컬럼 사용)
-- =============================================================================
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

-- =============================================================================
-- 동적 N단계 신규 템플릿 (stages_config 사용)
-- =============================================================================

-- 3단계 SHORT 예시: 100 / 200 / 350 (총 650), 마지막은 LIQUIDATION_BUFFER 5%
INSERT INTO strategy_templates (
    name, strategy_type, side, leverage, total_capital,
    stages_config,
    tp1_percent, tp2_percent, tp3_percent,
    tp1_qty_ratio, tp2_qty_ratio, tp3_qty_ratio,
    stop_loss_percent_of_capital, reentry_policy, is_active
) VALUES (
    'short_3stage_v2', 'DYNAMIC_SHORT', 'SHORT', 2, 650,
    '{"capitals":["100","200","350"],"trigger_percents":[null,10,null],"last_stage_trigger_mode":"LIQUIDATION_BUFFER","last_stage_trigger_percent":"5"}'::jsonb,
    10, 20, 30,
    25, 50, 25,
    50, 'manual_ready', TRUE
);

-- 5단계 SHORT 예시: 300 / 500 / 700 / 900 / 1200 (총 3600)
INSERT INTO strategy_templates (
    name, strategy_type, side, leverage, total_capital,
    stages_config,
    tp1_percent, tp2_percent, tp3_percent,
    tp1_qty_ratio, tp2_qty_ratio, tp3_qty_ratio,
    stop_loss_percent_of_capital, reentry_policy, is_active
) VALUES (
    'short_5stage_v2', 'DYNAMIC_SHORT', 'SHORT', 2, 3600,
    '{"capitals":["300","500","700","900","1200"],"trigger_percents":[null,8,12,15,null],"last_stage_trigger_mode":"LIQUIDATION_BUFFER","last_stage_trigger_percent":"5"}'::jsonb,
    10, 20, 30,
    25, 50, 25,
    50, 'manual_ready', TRUE
);

-- 10단계 SHORT 예시: 1000 / 3000 / 5000 / 9000 / 12000 / 15000 / 20000 / 30000 / 40000 / 70000 (총 205000)
INSERT INTO strategy_templates (
    name, strategy_type, side, leverage, total_capital,
    stages_config,
    tp1_percent, tp2_percent, tp3_percent,
    tp1_qty_ratio, tp2_qty_ratio, tp3_qty_ratio,
    stop_loss_percent_of_capital, reentry_policy, is_active
) VALUES (
    'short_10stage_v2', 'DYNAMIC_SHORT', 'SHORT', 2, 205000,
    '{"capitals":["1000","3000","5000","9000","12000","15000","20000","30000","40000","70000"],"last_stage_trigger_mode":"LIQUIDATION_BUFFER","last_stage_trigger_percent":"5"}'::jsonb,
    10, 20, 30,
    25, 50, 25,
    50, 'manual_ready', TRUE
);
