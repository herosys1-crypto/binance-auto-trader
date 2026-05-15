"""N+1 회귀 방지 테스트 — list_strategies 가 strategy 수 무관하게 bounded query 사용 (Phase 5).

배경 (2026-05-14 Phase 5):
- list_strategies 는 사용자 대시보드 메인 화면 로드 시 호출 (자주, 모든 strategy 표시).
- 운영 누적 → 수십 개 strategy 누적 가능 → N+1 발생 시 응답 시간 선형 증가.
- 현재 코드는 이미 batch fetch (templates by ids + tp_counts batch SQL) 적용돼 있음.
- 누가 향후 코드 변경 시 batch fetch 깨뜨리면 이 테스트가 즉시 catch.

검증 방법:
- SQLAlchemy event listener `before_cursor_execute` 로 SQL 호출 횟수 카운트
- 1 strategy / 5 strategies / 10 strategies 모두 같은 query 수 (templates batch + tp_counts batch).
- 추가 strategy 가 query 수 증가시키면 N+1 — 즉시 fail.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import event


def _attach_query_counter(session):
    """SQLAlchemy session 의 underlying engine 에 query counter 부착.

    Returns:
        list[str] — 실행된 SQL statements (호출자가 len() 으로 카운트).
    """
    queries: list[str] = []
    bind = session.get_bind()

    @event.listens_for(bind, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        # SAVEPOINT / RELEASE / BEGIN 같은 transaction control 은 제외 — 실제 query 만.
        s = (statement or "").strip().upper()
        if s.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK", "BEGIN", "COMMIT", "PRAGMA")):
            return
        queries.append(statement)

    return queries


class TestListStrategiesQueryCount:
    """list_strategies 가 strategy 수에 비례하는 query 수를 발생시키지 않는지 검증."""

    def _create_n_strategies(
        self, n: int,
        make_user, make_exchange_account, make_symbol, make_template, make_strategy,
    ):
        """N 개 strategy 생성. 모두 같은 user, 같은 template (batch 효과 검증용)."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()
        symbols = [f"SYM{i}USDT" for i in range(n)]
        for sym_str in symbols:
            sym = make_symbol(sym_str)
            make_strategy(
                user=u, exchange_account=ea, template=tpl, symbol_obj=sym,
                symbol_str=sym_str,
                # SHORT default 인데 같은 (user, sym, side) 중복 방지 → 다른 symbol 로 차별화
            )
        return u

    def test_query_count_bounded_for_1_strategy(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, make_strategy,
    ):
        """1 strategy: bounded query 수."""
        from app.api.v1.strategies.crud import list_strategies

        u = self._create_n_strategies(1, make_user, make_exchange_account, make_symbol, make_template, make_strategy)
        queries = _attach_query_counter(db_session)
        result = list_strategies(db=db_session, user_id=u.id)
        assert len(result) == 1
        n_queries_1 = len(queries)
        assert n_queries_1 <= 5, (
            f"1 strategy 에 {n_queries_1} queries — 너무 많음.\n"
            f"실행된 SQL:\n  " + "\n  ".join(queries[:10])
        )

    def test_query_count_does_not_grow_with_strategies(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, make_strategy,
    ):
        """strategy 5개 vs 10개 — query 수 증가 미미해야 (batch fetch 효과).

        N+1 깨지면: 5 strategies → 5+ extra queries, 10 strategies → 10+ extra queries.
        Batch 유지: 둘 다 거의 같은 query 수 (templates 1, tp_counts 1, list 1).
        """
        from app.api.v1.strategies.crud import list_strategies

        # 5 strategies 측정
        u5 = self._create_n_strategies(5, make_user, make_exchange_account, make_symbol, make_template, make_strategy)
        queries_5 = _attach_query_counter(db_session)
        result_5 = list_strategies(db=db_session, user_id=u5.id)
        assert len(result_5) == 5
        n_5 = len(queries_5)

        # 10 strategies 별도 user 로 측정 (queries list 새로 받음)
        # 위 listener 가 같은 engine 에 붙어있으므로 queries_5 도 계속 카운트되고 있음.
        # 카운터 reset: 새 list 부착해서 새로 카운트 (이전 listener 는 무시).
        queries_10 = _attach_query_counter(db_session)
        u10 = self._create_n_strategies(10, make_user, make_exchange_account, make_symbol, make_template, make_strategy)
        # 위 _create 에서 발생한 INSERT 쿼리 들 reset
        queries_10.clear()
        result_10 = list_strategies(db=db_session, user_id=u10.id)
        assert len(result_10) == 10
        n_10 = len(queries_10)

        # 핵심 단언: query 수가 strategy 수에 비례하면 안 됨.
        # 5 → 10 (2배) 이지만 query 는 < +3 증가 정도여야 함 (batch 효과).
        # 현재 구현: 3 query (list + templates batch + tp_counts batch). 5 vs 10 → 같음.
        diff = n_10 - n_5
        assert diff <= 3, (
            f"N+1 의심 — 5 strategies = {n_5} queries, 10 strategies = {n_10} queries (+{diff}).\n"
            f"Batch fetch 깨졌을 가능성 — list_strategies / _fetch_tp_counts_batch 점검 필요.\n"
            f"5-strat queries:\n  " + "\n  ".join(queries_5[:5]) + "\n"
            f"10-strat queries:\n  " + "\n  ".join(queries_10[:5])
        )

    def test_query_count_with_multiple_templates(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, make_strategy,
    ):
        """다른 template 5개 → templates batch fetch 1번이어야 (각각 N+1 쿼리 X)."""
        from app.api.v1.strategies.crud import list_strategies

        u = make_user()
        ea = make_exchange_account(user=u)
        # 5 다른 template + 5 strategy (각자 다른 template)
        for i in range(5):
            tpl = make_template(name=f"diverse_tpl_{i}")
            sym_str = f"DIV{i}USDT"
            sym = make_symbol(sym_str)
            make_strategy(
                user=u, exchange_account=ea, template=tpl, symbol_obj=sym,
                symbol_str=sym_str,
            )
        queries = _attach_query_counter(db_session)
        result = list_strategies(db=db_session, user_id=u.id)
        assert len(result) == 5
        # 5 strategies × 5 templates: 만약 N+1 이면 1 + 5 (templates 각각) + 5 (tp_counts) = 11+
        # Batch: 1 + 1 + 1 = 3
        n = len(queries)
        assert n <= 6, (
            f"5 strategies / 5 distinct templates 에 {n} queries — N+1 의심.\n"
            f"Templates batch fetch (db.query(StrategyTemplate).filter(id.in_(...))) 가 깨짐?\n"
            f"실행된 SQL:\n  " + "\n  ".join(queries[:10])
        )
