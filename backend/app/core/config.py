from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Binance Futures Auto Trading Platform"
    app_env: str = "local"

    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/binance_auto_trader"
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    binance_futures_base_url: str = "https://fapi.binance.com"
    binance_futures_testnet_base_url: str = "https://testnet.binancefuture.com"

    encryption_key: str = "change_me"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    enable_metrics: bool = True

    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0

    # 일일 손실 한도 (USDT) — 양수. None 또는 0 이면 기능 비활성 (deploy-safe default).
    # daily_loss_aggregator 가 active 계정의 unrealized 합산이 이 값을 넘기면 kill-switch 발동.
    # 운영자가 `.env` 의 DAILY_LOSS_LIMIT_USDT=50 같은 식으로 설정.
    daily_loss_limit_usdt: float | None = None

    # ─── 자본 상한 / 동시성 / 화이트리스트 (MAINNET-CHECKLIST 3-3, 2026-05-07 추가) ───
    # 동시 활성 strategy 수 한도 (계정당). 초과 시 신규 create 거부.
    # 거래소 API rate limit 보호 + 모니터링 단순화. 0 또는 음수면 1로 강제.
    max_concurrent_strategies_per_account: int = 10
    # 단일 strategy 의 자본이 가용 잔액의 N% 이하여야 함 (예: 5.0 = 5%).
    # None 또는 0/음수면 비활성. mainnet 초기 권장값 5~10%.
    max_strategy_capital_pct_of_balance: float | None = None
    # 심볼 화이트리스트 (CSV, 예: "BTCUSDT,ETHUSDT"). None / 빈 문자열이면 모든 심볼 허용.
    # mainnet 초기엔 BTC/ETH 같은 high-liquidity 심볼만 허용 권장.
    allowed_symbols_csv: str | None = None
    # 최대 leverage (사용자 override 포함). Binance Futures 는 최대 125x 까지 허용하지만
    # 청산 위험 큼. mainnet 권장 5x. None / 0 / 음수면 비활성 (Binance API 한도까지).
    max_leverage: int | None = None

    # System heartbeat 텔레그램 주기 (시간). 24/7 운영 신뢰성 — 정기적으로 시스템 상태
    # 요약 알림. None / 0 이면 비활성 (default). 권장 6 (하루 4번).
    heartbeat_interval_hours: int | None = None

    # 일일 운영 보고 (Layer 3, 2026-05-09): 매일 KST 09:00 「전일 24h 요약」 텔레그램.
    # health_check 명령 안 돌려도 자동으로 받음. False 면 scheduler 등록 X.
    daily_report_enabled: bool = True

    # 2026-05-10 (사용자 요청): 같은 심볼+방향 중복 strategy 차단 토글.
    # default False — Binance 단일 포지션 정책 보호 (#120 같은 사고 예방).
    # True 로 설정 시: 같은 QUSDT SHORT 두 strategy 동시 가능. 단, 익절/손절 신호가
    # 같은 거래소 포지션에 충돌해 부분 체결 / 잔량 mismatch / orphan 감지 가능성 ↑.
    # 사용자가 위험 인지하고 자유 거래 원할 때만 True.
    allow_duplicate_symbol_strategies: bool = False

    # 진입 시 추정 청산가까지 최소 거리 (%, MAINNET-CHECKLIST 3-5).
    # 거리 = |start_price - liq_price| / start_price × 100. 이 값 미만이면 진입 거부.
    # leverage=10x 일 때 거리 ≈ 9.95%. None / 0 이면 비활성. mainnet 권장 5~10.
    min_liquidation_distance_pct: float | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_symbols_set(self) -> set[str] | None:
        """allowed_symbols_csv 를 set 으로 파싱. None / 빈 값이면 None (모든 심볼 허용)."""
        if not self.allowed_symbols_csv:
            return None
        symbols = {s.strip().upper() for s in self.allowed_symbols_csv.split(",") if s.strip()}
        return symbols or None


settings = Settings()
