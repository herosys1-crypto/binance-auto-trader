"""모델 가격표 + 비용 계산 (2026-06-24 기준, Anthropic 1st-party API).

⚠️ 가격은 **캐시된 표**다. 바뀔 수 있으니 큰 배치를 돌리기 전에
   `python -m tools.batch.run models` 로 살아 있는 모델 목록을 확인해라.

## 검증된 사실 (claude-api 스킬 레퍼런스)

  Batch API      모든 토큰 사용량에 **50%**. 한 배치 최대 100,000건 / 256MB.
                 대개 1시간 내 완료, 최대 24시간. 결과는 29일 보관.
  캐시 읽기      기본 입력가의 **~0.1배**
  캐시 쓰기      5분 TTL **1.25배** / 1시간 TTL **2배**
  손익분기       5분 TTL 은 2건, 1시간 TTL 은 3건부터 이득

🚨 **배치에는 1시간 TTL 을 쓴다.** 배치는 요청들이 최대 1시간에 걸쳐 처리되므로
   5분 TTL 은 중간에 만료된다. 그리고 배치 요청에는 `max_tokens: 0` keep-alive 를
   쓸 수 없어서(레퍼런스 명시) 1시간 TTL 말고는 방법이 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MODELS", "ModelPrice", "estimate", "fmt_usd"]


@dataclass(frozen=True)
class ModelPrice:
    model_id: str
    label: str
    input_per_mtok: float
    output_per_mtok: float
    context: str

    # 캐시 배수 (레퍼런스 검증값)
    cache_read_mult: float = 0.10
    cache_write_5m_mult: float = 1.25
    cache_write_1h_mult: float = 2.00


MODELS: dict[str, ModelPrice] = {
    "opus": ModelPrice("claude-opus-5", "Claude Opus 5", 5.00, 25.00, "1M"),
    "sonnet": ModelPrice("claude-sonnet-5", "Claude Sonnet 5", 2.00, 10.00, "1M"),
    "haiku": ModelPrice("claude-haiku-4-5", "Claude Haiku 4.5", 1.00, 5.00, "200K"),
}

BATCH_DISCOUNT = 0.50


def fmt_usd(v: float) -> str:
    if v >= 1:
        return f"${v:,.2f}"
    if v >= 0.01:
        return f"${v:.3f}"
    return f"${v:.5f}"


def estimate(
    tier: str,
    *,
    n_requests: int,
    shared_prefix_tokens: int,
    per_request_tokens: int,
    output_tokens: int,
    batch: bool = True,
    cache_ttl: str = "1h",
) -> dict:
    """한 배치의 비용을 추정한다.

    캐시 모형: 공유 접두부는 **한 번 쓰고**(write) 나머지 요청이 읽는다(read).
      ⚠️ 배치는 요청이 병렬 처리돼서 **캐시 히트가 보장되지 않는다.**
         그래서 두 가지를 함께 낸다 — 캐시가 다 맞았을 때(최선)와
         하나도 안 맞았을 때(최악). 실제 청구는 그 사이에 떨어진다.
    """
    p = MODELS[tier]
    write_mult = p.cache_write_1h_mult if cache_ttl == "1h" else p.cache_write_5m_mult
    disc = BATCH_DISCOUNT if batch else 1.0

    def _in(tok: float, mult: float = 1.0) -> float:
        return tok / 1_000_000 * p.input_per_mtok * mult * disc

    out_cost = output_tokens * n_requests / 1_000_000 * p.output_per_mtok * disc
    var_in = _in(per_request_tokens * n_requests)

    # 캐시 없음 = 매 요청이 공유 접두부를 통째로 다시 보낸다
    no_cache = _in(shared_prefix_tokens * n_requests) + var_in + out_cost
    # 캐시 최선 = 1건 write + (n-1)건 read
    best = (_in(shared_prefix_tokens, write_mult)
            + _in(shared_prefix_tokens * max(0, n_requests - 1), p.cache_read_mult)
            + var_in + out_cost)
    # 캐시 최악 = 전부 write (배치 병렬성으로 히트를 못 잡은 경우)
    worst = _in(shared_prefix_tokens * n_requests, write_mult) + var_in + out_cost

    # 실시간 정가(배치 할인 없음, 캐시 없음) — 절감액 비교 기준
    full_price = no_cache / disc

    return {
        "model": p.model_id,
        "label": p.label,
        "n": n_requests,
        "no_cache": no_cache,
        "cache_best": best,
        "cache_worst": worst,
        "full_price_no_batch": full_price,
        "saving_vs_full": full_price - best,
    }


def render(est: dict) -> str:
    lines = [
        f"  모델            {est['label']} ({est['model']})",
        f"  요청 수         {est['n']}건",
        f"  캐시 최선       {fmt_usd(est['cache_best'])}   (공유 접두부 1회 write + 나머지 read)",
        f"  캐시 최악       {fmt_usd(est['cache_worst'])}   (배치 병렬성으로 히트 못 잡음)",
        f"  캐시 없음       {fmt_usd(est['no_cache'])}",
    ]
    if est["full_price_no_batch"] != est["no_cache"]:
        lines.append(
            f"  ── 실시간 정가  {fmt_usd(est['full_price_no_batch'])}"
            f"  →  최대 절감 {fmt_usd(est['saving_vs_full'])}"
        )
    return "\n".join(lines)
