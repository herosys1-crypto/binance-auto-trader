"""배치 실행기 — 실시간이 아니어도 되는 작업을 Message Batches API 로 50%에 돌린다.

    python -m tools.batch.run models                 # 살아 있는 모델·가격 확인
    python -m tools.batch.run plan docstring_audit   # 대상·토큰·비용 추정 (API 호출 없음)
    python -m tools.batch.run warm docstring_audit   # 공유 접두부를 캐시에 미리 써 둔다
    python -m tools.batch.run submit docstring_audit # 배치 제출 (승인 필요)
    python -m tools.batch.run status                 # 진행 중 배치 상태
    python -m tools.batch.run collect <batch_id>     # 결과 회수 + **실제 청구 비용** 보고

## 왜 `warm` 이 따로 있나

배치는 요청이 **병렬로** 처리돼서 「첫 요청이 캐시를 쓰고 나머지가 읽는다」가
보장되지 않는다. 그런데 1시간 TTL 캐시 **쓰기**는 1배가 아니라 **2배**다.
전부 write 로 처리되면 캐싱을 안 한 것보다 **비싸진다**:

    Haiku 200건 예시   캐시 최선 $0.41 / 캐시 없음 $1.48 / 캐시 최악 $2.68

그래서 `warm` 이 실시간 요청 **한 건**(max_tokens=1)으로 공유 접두부를 먼저 캐시에
써 넣는다. 그 다음 배치를 내면 모든 요청이 read(0.1배)로 들어간다.
`collect` 가 **실제** `cache_read_input_tokens` 를 보고하므로 효과를 눈으로 확인할 수 있다.

## 인증

`ANTHROPIC_API_KEY` 를 환경변수로 주거나 `ant auth login` 으로 프로필을 만든다.
Claude Code 자체 로그인과는 **별개**다 — 이 스크립트는 일반 API 를 직접 호출한다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.batch import pricing  # noqa: E402
from tools.batch.jobs import JOBS, REPO, SHARED_CONTEXT, Job, collect_targets  # noqa: E402

STATE_DIR = Path(__file__).resolve().parent / ".state"
OUT_DIR = REPO / "docs" / "batch-out"
CACHE_TTL = "1h"          # 배치는 최대 1시간에 걸쳐 처리된다 → 5분 TTL 은 만료된다
CHARS_PER_TOKEN = 3.4     # 추정용 (한글·코드 혼재 기준 보수적)

# 🚨 **최소 캐시 가능 접두부는 모델마다 512~4096 토큰**이고, 그보다 짧으면
#    조용히 캐싱되지 않는다(에러도 안 난다). 그런데 1h TTL 쓰기는 2배다 —
#    즉 짧은 접두부에 cache_control 을 붙이면 이득 0에 위험만 남는다.
#    안전하게 4096 을 넘길 때만 붙인다.
MIN_CACHEABLE_TOKENS = 4096



# ══════════════════════════════════════════════════════════════════════
def _client():
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic SDK 가 없다:  pip install anthropic")
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        print("⚠️  ANTHROPIC_API_KEY 가 없다. `ant auth login` 프로필이 있으면 그것을 쓴다.",
              file=sys.stderr)
    return anthropic.Anthropic()


def _context_text(docs: tuple[str, ...]) -> str:
    """저장소 규약 문서를 접두부에 싣는다. 없는 파일은 조용히 건너뛴다.

    두 가지를 동시에 해결한다:
      ① 접두부가 최소 캐시 크기를 넘겨 **캐싱이 실제로 걸린다**
      ② 모델이 이 저장소의 사고 이력을 알고 판단해서 **결과 품질이 올라간다**
    """
    parts = []
    for rel in docs:
        p = REPO / rel
        if p.is_file():
            parts.append(f"# 저장소 규약: {rel}\n\n"
                         + p.read_text(encoding="utf-8", errors="replace"))
    return "\n\n---\n\n".join(parts)


def _shared_system(job: Job) -> list[dict]:
    """모든 요청이 공유하는 접두부. **여기에만** 캐시 표시를 붙인다.

    🚨 캐시는 **접두부 일치**다. 이 블록 안에 시각·파일명·요청 ID 같은
       요청마다 바뀌는 값이 들어가면 캐시가 통째로 깨진다.
    🚨 접두부가 MIN_CACHEABLE_TOKENS 미만이면 **cache_control 을 안 붙인다** —
       그보다 짧으면 어차피 캐싱이 안 되는데(조용히), 1h 쓰기 2배 위험만 진다.
    """
    blocks: list[dict] = [{"type": "text", "text": SHARED_CONTEXT}]
    ctx = _context_text(job.context_docs)
    if ctx:
        blocks.append({"type": "text", "text": ctx})
    blocks.append({"type": "text",
                   "text": f"# 이번 작업: {job.label}\n\n{job.instruction}"})

    if _tok("".join(b["text"] for b in blocks)) >= MIN_CACHEABLE_TOKENS:
        blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": CACHE_TTL}
    return blocks


def _user_block(path: Path) -> str:
    rel = path.relative_to(REPO).as_posix()
    body = path.read_text(encoding="utf-8", errors="replace")
    return f"파일: {rel}\n\n```python\n{body}\n```"


def _params(job: Job, path: Path) -> dict:
    p = pricing.MODELS[job.tier]
    d: dict = {
        "model": p.model_id,
        "max_tokens": job.max_tokens,
        "system": _shared_system(job),
        "messages": [{"role": "user", "content": _user_block(path)}],
        "output_config": {"effort": job.effort},
    }
    if job.tier in ("sonnet", "opus"):
        d["thinking"] = {"type": "adaptive"}
    return d


def _tok(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


# ══════════════════════════════════════════════════════════════════════
def cmd_models() -> None:
    print("표에 캐시된 가격 (1M 토큰당, Anthropic 1st-party):\n")
    print("  %-8s %-22s %8s %9s  %s" % ("티어", "모델 ID", "입력", "출력", "컨텍스트"))
    for k, m in pricing.MODELS.items():
        print("  %-8s %-22s %7.2f$ %8.2f$  %s"
              % (k, m.model_id, m.input_per_mtok, m.output_per_mtok, m.context))
    print("\n  배치 = 위 가격의 50% / 캐시 읽기 = 입력가의 10% / 1h TTL 쓰기 = 200%")
    try:
        c = _client()
        print("\n살아 있는 모델 (Models API):")
        for m in c.models.list(limit=20):
            print("  ", m.id)
    except Exception as e:
        print(f"\n  (Models API 조회 실패 — 자격증명 없음? {str(e)[:90]})")


def cmd_plan(job_key: str, limit: int | None, exact: bool) -> dict:
    job = JOBS[job_key]
    targets = collect_targets(job, limit)
    if not targets:
        sys.exit(f"대상 파일 없음: {job.globs}")

    sys_blocks = _shared_system(job)
    cached = any("cache_control" in b for b in sys_blocks)
    shared = "".join(b["text"] for b in sys_blocks)
    shared_tok = _tok(shared)
    per = [_tok(_user_block(p)) for p in targets]

    if exact:
        c = _client()
        m = pricing.MODELS[job.tier].model_id
        shared_tok = c.messages.count_tokens(
            model=m, system=_shared_system(job),
            messages=[{"role": "user", "content": "x"}]).input_tokens
        per = [c.messages.count_tokens(
            model=m, messages=[{"role": "user", "content": _user_block(p)}]).input_tokens
            for p in targets]

    avg = sum(per) // len(per)
    print(f"\n작업   {job.label}  ({job.key})")
    print(f"모델   {pricing.MODELS[job.tier].label} / effort={job.effort} / "
          f"max_tokens={job.max_tokens}")
    print(f"대상   {len(targets)}개 파일{'  (--exact 로 정확 계산)' if not exact else '  (정확)'}")
    print(f"토큰   공유 접두부 {shared_tok:,} / 파일당 평균 {avg:,} "
          f"(최대 {max(per):,})")
    print(f"캐시   {'적용' if cached else '미적용'} "
          + ("(1h TTL)" if cached
             else f"— 접두부가 {MIN_CACHEABLE_TOKENS:,} 토큰 미만이라 어차피 캐싱이 안 된다"))
    print()
    est = pricing.estimate(job.tier, n_requests=len(targets),
                           shared_prefix_tokens=shared_tok if cached else 0,
                           per_request_tokens=avg,
                           output_tokens=job.est_output_tokens,
                           batch=True, cache_ttl=CACHE_TTL)
    print(pricing.render(est))
    if cached and est["cache_worst"] > est["no_cache"]:
        print(f"\n  🚨 캐시가 안 맞으면 캐싱을 안 한 것보다 비싸다 "
              f"({pricing.fmt_usd(est['cache_worst'])} > {pricing.fmt_usd(est['no_cache'])}).")
        print(f"     → 제출 **전에** `warm {job.key}` 를 먼저 돌려 접두부를 캐시에 써 둬라.")
    over = [p for p, t in zip(targets, per) if t > 150_000]
    if over:
        print(f"\n  ⚠️ 너무 큰 파일 {len(over)}개는 컨텍스트를 많이 먹는다: "
              f"{', '.join(x.name for x in over[:3])}")
    return {"job": job, "targets": targets, "est": est}


def cmd_warm(job_key: str) -> None:
    """공유 접두부를 캐시에 **미리 써 둔다** (실시간 요청 1건)."""
    job = JOBS[job_key]
    c = _client()
    p = pricing.MODELS[job.tier]
    r = c.messages.create(
        model=p.model_id, max_tokens=1,
        system=_shared_system(job),
        messages=[{"role": "user", "content": "ok"}],
    )
    u = r.usage
    print(f"캐시 예열 완료 ({job.label})")
    print(f"  write {getattr(u, 'cache_creation_input_tokens', 0):,} tok"
          f" / read {getattr(u, 'cache_read_input_tokens', 0):,} tok")
    print(f"  이 접두부는 {CACHE_TTL} 동안 살아 있다. 지금 바로 submit 해라.")


def cmd_submit(job_key: str, limit: int | None, yes: bool) -> None:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    plan = cmd_plan(job_key, limit, exact=False)
    job, targets = plan["job"], plan["targets"]
    if not yes:
        ans = input(f"\n{len(targets)}건 제출한다. 진행할까? [y/N] ").strip().lower()
        if ans != "y":
            sys.exit("취소")

    c = _client()
    reqs = [
        Request(custom_id=f"{job.key}--{i:04d}",
                params=MessageCreateParamsNonStreaming(**_params(job, p)))
        for i, p in enumerate(targets)
    ]
    batch = c.messages.batches.create(requests=reqs)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{batch.id}.json").write_text(json.dumps({
        "batch_id": batch.id, "job": job.key, "tier": job.tier,
        "out_ext": job.out_ext,
        "created": datetime.now(timezone.utc).isoformat(),
        "map": {f"{job.key}--{i:04d}": p.relative_to(REPO).as_posix()
                for i, p in enumerate(targets)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n✅ 제출됨: {batch.id}  ({len(reqs)}건)")
    print(f"   대개 1시간 내 완료, 최대 24시간. 결과는 29일 보관.")
    print(f"   진행:  python -m tools.batch.run status")
    print(f"   회수:  python -m tools.batch.run collect {batch.id}")


def cmd_status(batch_id: str | None) -> None:
    c = _client()
    ids = [batch_id] if batch_id else [
        p.stem for p in sorted(STATE_DIR.glob("*.json"))] if STATE_DIR.exists() else []
    if not ids:
        for b in c.messages.batches.list(limit=10):
            print(f"  {b.id}  {b.processing_status}")
        return
    for bid in ids:
        try:
            b = c.messages.batches.retrieve(bid)
        except Exception as e:
            print(f"  {bid}  조회 실패: {str(e)[:80]}")
            continue
        rc = b.request_counts
        print(f"  {b.id}  {b.processing_status}  "
              f"처리중 {rc.processing} / 성공 {rc.succeeded} / 실패 {rc.errored} / "
              f"만료 {rc.expired} / 취소 {rc.canceled}")


def cmd_collect(batch_id: str) -> None:
    c = _client()
    st_path = STATE_DIR / f"{batch_id}.json"
    if not st_path.exists():
        sys.exit(f"상태 파일이 없다: {st_path} (다른 머신에서 제출했나?)")
    st = json.loads(st_path.read_text(encoding="utf-8"))
    job = JOBS[st["job"]]
    p = pricing.MODELS[st["tier"]]

    b = c.messages.batches.retrieve(batch_id)
    if b.processing_status != "ended":
        sys.exit(f"아직 안 끝났다: {b.processing_status}")

    out_root = OUT_DIR / st["job"]
    out_root.mkdir(parents=True, exist_ok=True)

    n_ok = n_err = 0
    tot = {"in": 0, "out": 0, "cw": 0, "cr": 0}
    errs: list[str] = []

    for res in c.messages.batches.results(batch_id):
        src = st["map"].get(res.custom_id, res.custom_id)
        if res.result.type != "succeeded":
            n_err += 1
            errs.append(f"{src}: {res.result.type}")
            continue
        msg = res.result.message
        text = "".join(bl.text for bl in msg.content if bl.type == "text")
        u = msg.usage
        tot["in"] += u.input_tokens
        tot["out"] += u.output_tokens
        tot["cw"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        tot["cr"] += getattr(u, "cache_read_input_tokens", 0) or 0
        name = Path(src).stem + st["out_ext"]
        (out_root / name).write_text(
            (f"<!-- {src} / {job.label} / {p.model_id} -->\n\n" if st["out_ext"] == ".md"
             else f"# 자동 생성 초안 — {src} / {p.model_id}\n# 사람이 검토하기 전에 커밋하지 마라.\n\n")
            + text, encoding="utf-8")
        n_ok += 1

    # ── 실제 청구 비용 (추정이 아니라 usage 기반) ──
    d = pricing.BATCH_DISCOUNT
    cost = (tot["in"] / 1e6 * p.input_per_mtok
            + tot["cw"] / 1e6 * p.input_per_mtok * p.cache_write_1h_mult
            + tot["cr"] / 1e6 * p.input_per_mtok * p.cache_read_mult
            + tot["out"] / 1e6 * p.output_per_mtok) * d
    naive = ((tot["in"] + tot["cw"] + tot["cr"]) / 1e6 * p.input_per_mtok
             + tot["out"] / 1e6 * p.output_per_mtok)

    print(f"\n회수 완료 → {out_root}")
    print(f"  성공 {n_ok} / 실패 {n_err}")
    print(f"  토큰  입력 {tot['in']:,} / 캐시쓰기 {tot['cw']:,} / "
          f"캐시읽기 {tot['cr']:,} / 출력 {tot['out']:,}")
    hit = tot["cr"] / max(1, tot["cr"] + tot["cw"]) * 100
    print(f"  캐시 히트율 {hit:.0f}%  "
          f"{'✅' if hit > 60 else '🚨 warm 을 먼저 돌렸나? 히트가 낮으면 절감이 안 난다'}")
    print(f"  실제 청구  {pricing.fmt_usd(cost)}   (실시간·무캐시였다면 {pricing.fmt_usd(naive)})")
    print(f"  절감       {pricing.fmt_usd(naive - cost)}  ({(1 - cost / max(naive, 1e-9)) * 100:.0f}%)")
    if errs:
        print("\n  실패:")
        for e in errs[:10]:
            print("   -", e)
    print("\n  🚨 생성물은 **초안**이다. 사람이 검토하기 전에 코드에 반영하지 마라.")


# ══════════════════════════════════════════════════════════════════════
def main() -> None:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        print("사용 가능한 작업:")
        for k, j in JOBS.items():
            print(f"  {k:18s} {j.label:22s} [{j.tier}/{j.effort}]")
        return
    cmd, rest = a[0], a[1:]
    limit = None
    if "--limit" in rest:
        limit = int(rest[rest.index("--limit") + 1])
    yes = "--yes" in rest
    exact = "--exact" in rest
    pos = [x for x in rest if not x.startswith("--")]
    if limit is not None and str(limit) in pos:
        pos.remove(str(limit))

    if cmd == "models":
        cmd_models()
    elif cmd == "plan":
        cmd_plan(pos[0], limit, exact)
    elif cmd == "warm":
        cmd_warm(pos[0])
    elif cmd == "submit":
        cmd_submit(pos[0], limit, yes)
    elif cmd == "status":
        cmd_status(pos[0] if pos else None)
    elif cmd == "collect":
        cmd_collect(pos[0])
    else:
        sys.exit(f"모르는 명령: {cmd}  (--help)")


if __name__ == "__main__":
    main()
