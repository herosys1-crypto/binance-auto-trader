# 새 PC 환경 이전 핸드오프 — 2026-09-03

> 작성: 2026-09-03 (KST) · 대상 저장소 `herosys1-crypto/binance-auto-trader`
> · **VPS 배포 HEAD `ded22f3` (Fix 327)** · **저장소 `origin/main` = `e51d9a8`** (= `ded22f3` + 핸드오프 문서 커밋)
> 조사관 8명이 섹션을 쓰고 검증관 24명이 실측으로 고친 것을 하나로 합친 문서다.
> **이 문서 안에 비밀 「값」은 없다.** 키 이름과 「어디서 얻는가」만 적혀 있다.

---

## ⚡ 30초 요약

1. **실제 자금이 도는 바이낸스 선물 자동매매 시스템**을 다른 PC 로 옮긴다. 운영은 VPS(`root@159.65.137.250`)에서 계속 돌고 있고, 지금도 **포지션 8건**이 물려 있다.
2. **`git clone` 만으로는 안 된다.** 지식의 90%(사장님 매매 사상·헌법·반증 기록 83개 메모리)와 비밀값(`.env`)·SSH 키·미커밋 작업이 **저장소 밖**에 있다.
3. 옛 PC 를 밀기 전에 반드시 챙길 4가지 = **① 메모리 83개 ② `ENCRYPTION_KEY` 포함 `.env` ③ SSH 개인키(또는 새 키 등록) ④ `infallible-euler` worktree 의 미커밋 3,666줄**.
4. 🚨 **새 PC 에서 앱(스케줄러)을 켜지 마라.** `.env` 만 있으면 로컬이 **운영과 같은 계정·같은 DB 에 붙은 두 번째 매매엔진**이 된다 → 중복 주문·이중 손절·IP ban.
5. 시작점 = 아래 **「🚨 가장 먼저: 옛 PC 에서 챙길 것」** 체크리스트 → **「📋 이전 시나리오」** 0단계부터 순서대로.

---

## 🚨 가장 먼저: 옛 PC 에서 챙길 것

> **여기 있는 것을 놓치면 복구가 불가능하다.** clone 으로 따라오지 않는 것들이다.
> 각 항목의 상세 근거는 오른쪽 링크의 섹션에 있다.

- [ ] **① 프로젝트 메모리 83개** — `C:\Users\user\.claude\projects\C--Users-user------binance-auto-trader\memory\` (764K)
      → 사장님 사상 verbatim·헌법·**반증된 가설**(돈으로 값을 치른 실험 기록) 전부.
      ✅ 사본이 커밋 `e51d9a8` 로 `origin/main` 에 이미 올라가 있다 (`docs/handoff/memory-backup-2026-09-03/`).
      그래도 **USB 로도 한 벌 빼 둘 것** — 그 폴더는 비밀번호 마스킹 작업으로 지워질 수 있다. → [Claude Code 로컬 상태](#sec-2)
- [ ] **② `backend/.env` 의 비밀값 — 특히 `ENCRYPTION_KEY`**
      → 이걸 잃으면 DB 의 `exchange_accounts.api_key_enc` 를 **영영 복호화 못 한다.** 앱은 뜨는데 거래만 조용히 실패한다.
      🚫 채팅·이메일·클라우드 금지. 비밀번호 관리자 또는 USB(쓰고 나면 삭제). → [비밀·설정 인벤토리](#sec-3)
- [ ] **③ SSH 개인키 `~/.ssh/id_ed25519`** (411B) — 없으면 **VPS 에 아예 접속이 안 되고 이 문서의 절반이 실행 불가**다.
      ⚠️ 이 키에는 **passphrase 가 없다(실측)**. 파일 하나만 새면 누구나 운영 서버 root 로 들어온다.
      ✅ 권장 = 복사하지 말고 **새 PC 에서 새 키를 만들어 VPS `authorized_keys` 에 `>>` 로 추가**. → [VPS 운영환경](#sec-5) §9
- [ ] **④ `infallible-euler-6dc297` worktree 의 미커밋 작업 3,666줄 (215KB)**
      `backend/app/api/v1/terminal.py`(1,185줄, 미추적) / `backend/app/static/perp-terminal.html`(2,481줄, 미추적) / `backend/app/api/router.py`(+2줄, 수정).
      🚨 **원격 어디에도 없고, `wip-backup-2026-09-03/` 백업 폴더에도 이 worktree 만 빠져 있다.**
      새 PC 에서 clone 하면 **영구 소실**. → [이번 세션에서 한 일](#sec-8) §6-3
- [ ] **⑤ `.claude/settings.local.json` 4개 (합집합 1,116건)** — 명령 권한 허용목록.
      🚨 안에 **VPS IP 가 박힌 ssh 명령**과 **`ENCRYPTION_KEY` 평문 17건**, `git reset`/`git push`/`docker restart` 자동승인이 들어 있다.
      공개 저장소에 절대 넣지 말고, **위험 항목 197개를 걷어내 919개로 줄인 뒤** USB 로. → [Claude Code 로컬 상태](#sec-2) §4.3
- [ ] **⑥ 전역 gitignore `~/.config/git/ignore`** — 위 ⑤가 실수로 커밋되는 것을 막는 유일한 장치.
- [ ] **⑦ (선택) 세션 트랜스크립트 `~/.claude/projects/*/*.jsonl` 1.1GB** — `--resume` 용. 지식은 메모리에 증류돼 있어 없어도 된다.
- [ ] **🚫 복사하면 안 되는 것**: `~/.claude/.credentials.json` (새 PC 에서 새로 로그인할 것)

> ### ⛔ 옛 PC 를 최소 2주는 지우지 마라
> 이 이전의 **유일한 완전한 롤백은 옛 PC 가 그대로 남아 있는 것**이다.
> 새 PC 가 [15단계 최종 검증](#step-15)을 **전부** 통과하고 실제로 한 세션을 문제없이 돌린 뒤에
> 정리를 시작한다. 그 전에 `git worktree remove` · `rm -rf` · 포맷 금지.

---

## 📋 목차

**시작**
- [⚡ 30초 요약](#-30초-요약)
- [🚨 가장 먼저: 옛 PC 에서 챙길 것](#-가장-먼저-옛-pc-에서-챙길-것)
- [📋 이전 시나리오 (0~16단계)](#-이전-시나리오-순서대로)

**본문 8개 섹션**
1. [사장님 매매 사상과 헌법 — 가장 먼저 읽어야 할 것](#sec-1)
2. [Claude Code 로컬 상태 — 저장소 밖 자산](#sec-2)
3. [비밀·설정 인벤토리 (값 없이 이름만)](#sec-3)
4. [로컬 개발환경 재구축](#sec-4)
5. [VPS 운영환경과 배포 절차](#sec-5)
6. [코드 구조 지도 — 어디를 봐야 하나](#sec-6)
7. [현재 운영 상태 — 무엇이 돌고 있나](#sec-7)
8. [이번 세션에서 한 일과 다음 할 일](#sec-8)

**마무리**
- [⚠️ 알려진 공백 (156건)](#-알려진-공백)
- [🆘 막혔을 때](#-막혔을-때)

---

## 📋 이전 시나리오 (순서대로)

> **읽는 법**
> - 🖥️ **[옛 PC]** = 지금 쓰던 사무실 PC / 🆕 **[새 PC]** = 새로 만드는 환경
> - 모든 명령은 **Git Bash** 기준이다 (PowerShell·cmd 아님 — `$HOME`, `/c/...`, `printf` 가 다르다).
> - 경로에 한글 「바이낸스」가 있다. **명령에서 반드시 따옴표로 감싼다.**
> - 각 단계는 **무엇을 / 명령 / 성공 판정 / 실패하면** 으로 되어 있다. 성공 판정을 통과하지 못하면 다음 단계로 가지 마라.

### 🚦 시작 전 — 이 3가지는 사장님만 결정할 수 있다

| # | 사안 | 실측 | 결정해야 할 것 |
|---|---|---|---|
| **A** | **저장소가 public 이다** — `curl https://api.github.com/repos/herosys1-crypto/binance-auto-trader` → `"private": false`, `"visibility": "public"` | 실자금 매매 시스템의 전 소스·전략 로직·기획서가 공개돼 있다. 이미 공개된 `docs/handoff/` 102개 파일 중 **8개에 VPS root SSH 엔드포인트**가 박혀 있다 | private 로 바꿀지. 바꾸면 **VPS 의 `git pull` 인증이 끊길 수 있다** — 함께 검토 필요 |
| **B** | 🚨 **`SECRET_KEY` 가 공개 저장소에 평문으로 있다** — `HANDOFF-2026-04-30-NEXT-SESSION.md:197,210`, VPS `.env` 현재 값과 **md5 일치** | `SECRET_KEY` 는 `app/core/security.py:45,49` 의 JWT 서명키이고, 포트 8000 이 인터넷에 열려 있다(`curl http://159.65.137.250:8000/health` → 200). **누구든 로그인 토큰을 위조해 실자금 API 에 접근 가능**하다 | 키 교체 (VPS 쓰기 = 사장님만) |
| **C** | 🚨 **Neon DB 비밀번호가 공개 저장소에 평문으로 있다** — `docs/handoff/memory-backup-2026-09-03/project_overview.md:385,386,389` (커밋 `e51d9a8`, 이미 push 됨). 인증 없이 `raw.githubusercontent.com` 에서 읽힌다 | 파일을 지워도 **git 이력에 남는다.** 유효 여부는 확인 못 했으므로 **유효하다고 가정**해야 한다 | Neon Console 에서 비밀번호 재교체 → VPS `.env` 갱신 → `api`/`scheduler` 재시작 (순서를 지키지 않으면 실거래 엔진이 DB 접속 실패로 멈춘다) |

> ⚠️ **유출의 원천이 하나 더 있다**: 메모리 **원본**(`~/.claude/projects/.../memory/project_overview.md`)에도 같은 3줄이 그대로 있다.
> 저장소 안 사본만 마스킹하면 **다음 백업 때 그대로 재생성된다.** 원본을 먼저 마스킹해야 재발이 끊긴다.
>
> ⚠️ 그 외 이미 공개된 비밀: **Grafana admin 비밀번호**(`backend/docker-compose.yml:99` 평문),
> Neon 접속문자열 옛 비번(`HANDOFF-2026-04-28-HOME-TO-OFFICE.md:27,138,179` — md5 비교 결과 **이미 교체됨**).

---

### 0단계 🖥️ [옛 PC] — 이 핸드오프 문서를 저장소에 올린다

**무엇을**: `docs/handoff/2026-09-03/` 8개 파일과 이 통합 문서는 **아직 untracked** 다 (`git status` = `?? docs/handoff/2026-09-03/`).
올리지 않으면 **새 PC 에서 clone 해도 이 문서가 따라오지 않는다.**

> 🚦 위 **결정 A(저장소 public 여부)** 를 먼저 정해야 한다. 지금 커밋하는 것은 곧 **공개 게시**다.

**① 먼저 무엇이 올라가는지 본다** (문서만이어야 한다. `backend/` 가 보이면 **멈춰라**):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git add docs/handoff/2026-09-03 HANDOFF-2026-09-03-NEW-PC-MIGRATION.md && git status --short && git diff --cached --stat -- backend/
```

**성공 판정**: 마지막 `git diff --cached --stat -- backend/` 가 **빈 출력**.

**실패하면**: 뭔가 나오면 코드가 섞인 것이다 — 실자금 시스템의 `main` 에 검증 안 된 코드가 들어간다.
`git restore --staged backend` 로 그 부분만 내리고 다시 확인한다.
(이 워크트리에는 다른 작업자의 미커밋 코드 변경 `M backend/app/api/router.py`, `?? backend/app/api/v1/terminal.py` 가 실제로 있다.)

**② 커밋·푸시** (①에서 문서 전용임을 확인한 뒤에만):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git fetch origin && git commit -m "docs(handoff): 2026-09-03 새 PC 이전 핸드오프" && git push origin HEAD:main
```

**실패하면**: `rejected` 가 나와도 **`--force` 를 붙이지 마라.** `origin/main` 이 그새 움직였다는 뜻이고,
force 를 붙이면 그 커밋들이 사라진다(실자금 코드일 수 있다).
`git fetch origin && git merge --no-edit origin/main` 후 다시 푸시한다.

⏪ **되돌리기**: `git revert --no-edit <올린커밋> && git push origin HEAD:main`.
`git reset --hard` + force push 는 **금지**(파괴적 작업 = 사장님께 묻는다).

---

### 1단계 🖥️ [옛 PC] — 미커밋 작업 3,666줄을 살린다 (가장 놓치기 쉬움)

**무엇을**: `infallible-euler-6dc297` worktree 에만 있는 perp 터미널 작업을 보존한다.
**실측 확인**: `git ls-files backend/app/api/v1/terminal.py` → 출력 없음 / VPS `grep -c terminal backend/app/api/router.py` → **0** /
VPS `ls backend/app/api/v1/terminal.py` → No such file / `docs/handoff/wip-backup-2026-09-03/` 에는 main·charming-albattani·loving-rhodes **3개뿐**.

**(A) 권장 — 커밋해서 GitHub 으로 보낸다** (화면·API 파일이라 배포와 무관하게 안전하다. 단 `router.py` 2줄은 코드다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git switch -c wip/perp-terminal-$(date +%m%d-%H%M) && git add backend/app/api/v1/terminal.py backend/app/static/perp-terminal.html backend/app/api/router.py && git commit -m "wip(terminal): perp 터미널 화면 + 읽기 전용 조회 API" && git push -u origin HEAD
```

**(B) 커밋하고 싶지 않으면 최소한 백업 폴더에 복사해 둔다** (파괴적 명령 없음):

```bash
mkdir -p "C:/Users/user/바이낸스/binance-auto-trader/docs/handoff/wip-backup-2026-09-03/infallible-euler-6dc297/untracked" && cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && cp backend/app/api/v1/terminal.py backend/app/static/perp-terminal.html "C:/Users/user/바이낸스/binance-auto-trader/docs/handoff/wip-backup-2026-09-03/infallible-euler-6dc297/untracked/" && git diff -- backend/app/api/router.py > "C:/Users/user/바이낸스/binance-auto-trader/docs/handoff/wip-backup-2026-09-03/infallible-euler-6dc297/router.py.patch"
```

**성공 판정**: (A) 라면 그 worktree 에서 `git status --short` 가 **비어 있다**. (B) 라면 백업 폴더에 3개 파일이 보인다.

**실패하면**: 옛 PC 를 밀지 마라. 이 작업은 원격 어디에도 없다.

> ⚠️ **새 PC 에서 `perp-terminal.html` 을 열기 전에 확인할 것**: 짝인 `terminal.py` 는 `@router.get` 6개뿐(POST 0개)이라
> 그 라우터만으로는 주문이 안 나간다. 하지만 **HTML 2,481줄이 기존 주문 API 를 호출하는지는 읽지 않았다.**

---

### 2단계 🖥️ [옛 PC] — 권한 허용목록을 합치고, 위험 항목을 걷어낸다

**무엇을**: `settings.local.json` 은 **4개이고 내용이 다르다.** 메인 것만 복사하면 15%(164개)만 따라온다.

**① 4개를 합친다** (읽기만 하고 원본은 건드리지 않는다. `E:` 는 실제 USB 드라이브 문자로 바꿀 것):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && python -c "
import json,glob
seen,allow=set(),[]
for p in ['.claude/settings.local.json']+sorted(glob.glob('.claude/worktrees/*/.claude/settings.local.json')):
    for x in json.load(open(p,encoding='utf-8'))['permissions']['allow']:
        if x not in seen: seen.add(x); allow.append(x)
json.dump({'permissions':{'allow':sorted(allow)}}, open('/e/handoff-settings.local.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('merged allow:', len(allow))"
```

**성공 판정**: `merged allow: 1116`

**② 🚨 반드시 이어서 — 위험 항목을 제거한다** (섹션 2 §4.3). 합친 직후에는
`git reset *` / `git stash *` / `git push *` / `docker restart *` / **운영 컨테이너 임의 파이썬 실행**이
새 PC 에서 **묻지 않고** 실행되는 상태다.

**성공 판정**: `kept 919 / removed 197`

**실패하면**: USB 가 없으면 `/e/...` 대신 `$HOME/handoff-settings.local.json` 으로. **공개 저장소에는 절대 넣지 마라** (ssh 항목에 VPS IP 가 있다).

> 🚨 이 허용목록에서 이 문서·메모리·`reference_vps.md` 어디에도 없는 **두 번째 서버 `152.42.232.195`(사용자 `trader`)** 가 발견됐다.
> `docker compose restart` 와 `.env.production` 복사 항목이 있어 운영 계열로 보이지만 **정체 확인 못 함.**
> 새 PC 작업 전에 사장님이 확인해야 한다.

---

### 3단계 🖥️ [옛 PC] — 메모리 83개를 USB 로도 뺀다

**무엇을**: 저장소 사본(`e51d9a8`)이 이미 있지만, 그 폴더는 비밀번호 마스킹 작업으로 지워질 수 있다. 이중화한다.

```bash
cp -r "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" "/e/handoff-memory" && ls "/e/handoff-memory" | wc -l
```

**성공 판정**: `83`

**저장소 사본 확인** (🚨 `git ls-files` 로 재지 마라 — 옛 PC 의 main 워크트리는 `origin/main` 보다 30커밋 뒤처져 있어 **`0` 이 나온다**):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader" && git fetch origin && git ls-tree -r --name-only origin/main -- docs/handoff/memory-backup-2026-09-03 | wc -l
```

**성공 판정**: `83`

---

### 4단계 🖥️ [옛 PC] — 비밀값을 안전하게 준비한다

**무엇을**: `ENCRYPTION_KEY` 를 포함한 `.env` 값. **값을 채팅·이메일·클라우드에 올리지 마라.**

- `ENCRYPTION_KEY` 는 **VPS 의 현재 값 그대로**여야 한다. 새로 만들면 DB 의 `api_key_enc` 를 못 읽어 **「기동은 성공, 거래만 실패」** 고장이 난다.
- 되도록 **비밀번호 관리자**에 넣는다. USB 를 쓴다면 옮긴 뒤 **지운다**.
- 지문(값 노출 없이 같은 값인지 대조하는 법)은 섹션 3 §4 / 섹션 4 §5-4 ④ 에 있다.

**성공 판정**: 옛 PC 와 VPS 에서 각각 지문 명령을 돌려 **앞 12자가 같다.**

**실패하면**: 다르면 어느 쪽이 운영값인지 확정될 때까지 새 PC 에 `.env` 를 만들지 마라.

> ⚠️ **아직 아무도 확인하지 못했다** — 옛 PC 와 VPS 의 `ENCRYPTION_KEY` 가 실제로 같은 값인지.
> 사장님이 양쪽에서 지문 명령을 각각 돌려 직접 대조해야 한다.
>
> ⚠️ **`ENCRYPTION_KEY` 를 이미 잃어버린 경우의 복구 절차는 이 문서에 없다.**
> `backend/scripts/rotate_encryption_key.py` 는 247행 `old_key = settings.encryption_key` 로 **옛 키를 요구**하므로 분실 시 대안이 아니다.
> 그 상황이면 거래소 계정 행을 지우고 바이낸스 키를 재발급·재등록해야 하는데, 그 절차는 검증되지 않았다.

---

### 5단계 🖥️🆕 [양쪽] — SSH 키: 복사하지 말고 새로 만든다

**무엇을**: VPS 접속 수단 확보. 이게 없으면 이 문서의 VPS 관련 명령이 **전부** `Permission denied (publickey)` 로 실패한다.

**① 새 PC 에서 새 키를 만든다** (passphrase 를 꼭 넣을 것):

```bash
ssh-keygen -t ed25519 -C "new-pc-$(date +%F)" && cat "$HOME/.ssh/id_ed25519.pub"
```

**② 그 공개키 한 줄을 옛 PC 에서 VPS 에 덧붙인다.**
🚨 **`>` 가 아니라 `>>` 다.** `>` 로 쓰면 기존 키가 지워져 **옛 PC 까지 접속이 끊긴다**(자물쇠 안에 갇힌다).

**성공 판정**: 새 PC 에서 `ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname'` 이 응답.

**실패하면**: ⏪ **새 키로 접속이 성공하는 것을 확인하기 전에는 옛 키를 `authorized_keys` 에서 지우지 마라.**
두 키가 동시에 유효한 상태를 거쳐서 넘어간다.

> 🚨 **SSH 가 잠겼을 때의 유일한 탈출구는 DigitalOcean 웹 콘솔(Recovery Console)** 이다.
> **root 비밀번호를 알고 계신지 이전 전에 반드시 확인**할 것 — 모르는 상태로 진행하면 VPS 에 손을 못 대게 된다.
> (DO 콘솔 접근 여부는 이 조사에서 확인하지 못했다.)

---

### 6단계 🆕 [새 PC] — 사전 설치물

| 순서 | 설치 | 확인 명령 |
|---|---|---|
| 1 | **Python 3.12** (PATH 체크) | `python --version` |
| 2 | **Git for Windows** (Git Bash 포함) | `git --version` |
| 3 | Docker Desktop | `docker --version` |
| 4 | Claude Code | `claude --version` |

git 전역 설정 (섹션 4 §2-1, §2-2):

```bash
git config --global user.name "..." && git config --global user.email "herosys1@gmail.com" && git config --global init.defaultBranch main && git config --global core.longpaths true
```

**성공 판정**: `git config --global --list` 에 위 3줄이 보인다 (`credential.helper`·`core.autocrlf` 는 설치만 하면 자동).

**사용자명 확인** — 🚨 이게 다르면 **이 문서의 경로를 전부 바꿔 읽어야 한다**:

```bash
echo $HOME
```

**성공 판정**: `/c/Users/user`

---

### 7단계 🆕 [새 PC] — 저장소 clone

**무엇을**: 경로를 **옛 PC 와 똑같이** 둔다. 그래야 메모리 슬러그가 저절로 같아진다.

```bash
mkdir -p "/c/Users/user/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git "/c/Users/user/바이낸스/binance-auto-trader" && cd "/c/Users/user/바이낸스/binance-auto-trader" && git log --oneline -3
```

**성공 판정**: 로그인 창이 **안 뜬다** (저장소가 public 이라 clone 에 인증이 필요 없다).
첫 줄이 `e51d9a8` 또는 그 이후 커밋.

**실패하면**: `push` 할 때는 인증이 필요하다 — 첫 push 때 Git Credential Manager 창이 뜨면 브라우저로 로그인한다 (사장님은 `gh` CLI 를 쓰지 않는다).

---

### 8단계 🆕 [새 PC] — 메모리 83개를 Claude 가 읽는 자리로 복원

**무엇을**: 메모리 디렉터리 이름은 **저장소 절대경로에서 자동 생성되는 슬러그**다.
`C:\Users\user\바이낸스\binance-auto-trader` → `C--Users-user------binance-auto-trader`
(드라이브·역슬래시 → `-`, 한글 「바이낸스」 5글자 → `-` 5개).

**① 슬러그를 계산해 확인한다**:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && python -c "import re,os; print(re.sub(r'[^A-Za-z0-9]','-',os.getcwd()))"
```

**성공 판정**: `C--Users-user------binance-auto-trader`.
다르면 **아래 명령의 그 부분을 출력값으로 바꿔 쓴다.**

> 🚨 더 확실한 방법: **clone 한 그 디렉터리 안에서** Claude Code 를 한 번 실행해 종료하면 슬러그 디렉터리가 자동 생성된다.
> `ls "$HOME/.claude/projects/"` 로 실제 이름을 눈으로 확인한다.
> ⚠️ 그 **첫 세션은 사장님 사상·헌법·반증 기록을 하나도 모르는 상태로 실자금 저장소에서 열린다** —
> **그 세션에서는 코드를 만지지 마라.** 슬러그 확인만 하고 끝낸다.

**② 복사한다** — 원본은 둘 중 하나:

```bash
# (a) clone 안의 사본 (가장 간단)
mkdir -p "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" && cp -r "/c/Users/user/바이낸스/binance-auto-trader/docs/handoff/memory-backup-2026-09-03/." "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/"

# (b) USB (3단계에서 뺀 것)
mkdir -p "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" && cp -r "/e/handoff-memory/." "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/"
```

**③ 개수 검증**:

```bash
ls "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" | wc -l
```

**성공 판정**: **83**

**④ 색인 검증**:

```bash
head -1 "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/MEMORY.md"
```

**성공 판정**: 첫 줄이 2026-09-03 항목.

**실패하면**: `docs/handoff/memory-backup-2026-09-03/` 가 clone 에 없으면 이미 지워진 뒤다(마스킹 작업으로 함께 지웠을 수 있다) → (b) 를 쓴다.

> 🚨 **「파일이 있다」와 「Claude 가 읽는다」는 다르다.** 진짜 검증은 [15단계](#step-15) 에 있다.

---

### 9단계 🆕 [새 PC] — gitignore → 권한 허용목록 (순서 중요)

**① 전역 gitignore 를 먼저 만든다.** 🚨 아래 (a) 는 `>` 라 **기존 파일을 통째로 덮어쓴다.** 먼저 확인:

```bash
[ -f "$HOME/.config/git/ignore" ] && cp "$HOME/.config/git/ignore" "$HOME/.config/git/ignore.bak.$(date +%F)" && echo "기존 파일 백업함 — (b) 로" || echo "기존 파일 없음 — (a) 로"
```

```bash
# (a) 파일이 없던 경우
mkdir -p "$HOME/.config/git" && printf '**/.claude\\settings.local.json\n\n**/.claude/settings.local.json\n' > "$HOME/.config/git/ignore"

# (b) 파일이 이미 있던 경우 — 덮지 말고 이어붙인다 (중복도 막는다)
grep -qxF '**/.claude/settings.local.json' "$HOME/.config/git/ignore" || printf '\n**/.claude/settings.local.json\n' >> "$HOME/.config/git/ignore"
```

**② 그 다음에 허용목록을 복사한다** (2단계에서 위험 항목을 걷어낸 파일):

```bash
cp "/e/handoff-settings.local.json" "/c/Users/user/바이낸스/binance-auto-trader/.claude/settings.local.json" && python -c "import json;print(len(json.load(open(r'C:/Users/user/바이낸스/binance-auto-trader/.claude/settings.local.json',encoding='utf-8'))['permissions']['allow']))"
```

**성공 판정**: **919**
- **1116** → 위험 항목 제거를 안 돌렸다. 2단계 ②부터 다시.
- **164** → 병합을 안 하고 메인 파일만 복사했다. 2단계 ①부터 다시.

**③ 제외되는지 확인** (①을 먼저 한 뒤에):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git check-ignore -v .claude/settings.local.json; echo "exit=$?"
```

**성공 판정**: 경로가 출력되고 `exit=0`.

**실패하면**: 🚨 **아무것도 안 나오고 `exit=1`** = ①이 안 됐다. **조용히 실패하므로 「출력이 없으니 괜찮다」고 읽지 마라.**
이 상태로 커밋하면 VPS IP 가 공개 저장소로 나간다.

**④ 에이전트 3종이 clone 으로 따라왔는지**:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git ls-files .claude
```

**성공 판정**: 3줄 (`impl`/`locator`/`mech`).

⏪ **되돌리기**: `settings.local.json` 은 지워도 안전하다. 지우면 권한 프롬프트가 다시 뜰 뿐 기능은 멀쩡하다.
**의심스러우면 넣지 않는 쪽이 항상 안전하다 — 프롬프트가 뜨는 것은 고장이 아니라 안전장치다.**

---

### 10단계 🆕 [새 PC] — Python 의존성

**무엇을**: venv 를 만들고 섹션 4 §4-3 ②번의 **23개 핀 고정 설치**를 한다.
🚨 `fastapi` 를 핀 없이 깔면 **mainnet 전 API 500 사고**(메모리 기록)와 같은 형태가 재현될 수 있다.

**성공 판정**:

```bash
pip freeze | grep -i "^fastapi=="
```
→ `fastapi==0.135.3`

> ✅ 확인됨: 이 23개 핀은 **Python 3.12 / win_amd64 wheel 로 전이 의존성 포함 54개 전부 존재**한다
> (`pip download --python-version 3.12 --only-binary=:all: --platform win_amd64` 로 실측, 해석 실패 0건).
>
> ℹ️ `make` 는 설치할 필요 없다 — `backend/Makefile` 14개 타깃 전부를 실제 명령으로 풀어 섹션 4 §8-5 표에 적어 뒀다.

---

### 11단계 🆕 [새 PC] — `.env` 는 「필요할 때만」 만든다

**무엇을**: 먼저 **자기가 어느 쪽인지** 정한다. 이 판단을 건너뛰면 안 만들어도 될 위험을 새 PC 에 들인다.

| 새 PC 에서 할 일 | `.env` 필요한가 | 근거 |
|---|---|---|
| 코드 편집 + git push + Claude Code 대화 | ❌ **불필요** | 배포는 VPS 에서 한다. 로컬은 소스만 다룬다 |
| `pytest` 실행 | ❌ **불필요** | `backend/tests/conftest.py:6` 이 `sqlite+pysqlite:///:memory:` 를 쓴다 — 실 DB·실 키를 안 본다 |
| 로컬에서 앱을 띄움 (`docker compose up`) | ✅ 필요 | `app/core/config.py:69` 가 `env_file=".env"`, `backend/docker-compose.yml` 이 `env_file` 참조 |

🚨 **대부분의 경우는 첫 줄이다 → `.env` 를 아예 만들지 마라.**
비밀을 옮기지 않는 것이 비밀을 안전하게 옮기는 것보다 항상 낫다.

만들었다면 **키 개수 확인** (값은 안 찍히고 개수만 나온다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -cE "^[A-Za-z_0-9]+=" .env
```

**성공 판정**: 옛 PC `.env` 를 참고해 채웠으면 **22**, `cp .env.example .env` 로 시작했으면 **18**.
더 적으면 `ENCRYPTION_KEY` 포함 뭔가 빠진 것이다.

🚨 **이번 이전에서 가장 위험한 한 줄** — DB/Redis 가 어디를 가리키는지 **호스트만** 뽑아 본다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -E "^(DATABASE_URL|TEST_DATABASE_URL|REDIS_URL)=" .env | sed -E 's#://[^@]*@#://***:***@#'
```

**성공 판정**: `localhost:5433` / `redis://localhost:6380/0` 같은 **로컬 주소**.

**실패하면**: 출력에 `neon.tech` 같은 **운영 DB 호스트**가 보이면 **거기서 멈춘다.**
운영 주소를 그대로 둔 채 앱을 켜면 **로컬에서 실자금 DB 를 건드린다.**

**커밋 방지 확인**:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git check-ignore -v backend/.env
```

**성공 판정**: `.gitignore:7` 이 잡는다. 출력이 없으면 🚨 **멈춰라** — 그대로 커밋하면 유출 사고가 반복된다. 저장소는 public 이다.

> ⚠️ **최신 `DATABASE_URL` 을 이 문서가 제공할 수 없다.** 사무실 PC 의 값은 비밀번호가 만료돼 인증 실패(실측)이고,
> 유효한 값은 Neon 콘솔 또는 VPS `.env` 에서 **사장님이 직접** 가져와야 한다.
> = 이 문서만으로는 새 PC 에서 DB 에 붙는 단계까지 갈 수 없다. 반드시 사람이 개입하는 지점이 하나 남는다.

---

### 12단계 🆕 [새 PC] — 테스트 (10~12분)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q
```

**성공 판정**: `.env` 를 만들었으면 **`44 failed, 1722 passed`**, `.env` 없이 돌렸으면 **`52 failed, 1714 passed`**.

🚨 **숫자보다 「실패 테스트 이름」을 비교하라.** 위 기준선은 **Python 3.14.2 + 옛 PC 전역 패키지**에서 잰 것이고,
6단계는 3.12 를 권한다 — **3.12 + venv 기준선은 아직 실측되지 않았다.**

**실패 목록이 다르면**: 새 PC 환경 문제일 수 있다. `ModuleNotFoundError` 는 「테스트 실패」가 아니라 「환경 없음」이다 — 10단계로 돌아간다.

> ✅ 이 기준선은 `git archive origin/main` 으로 **순정 트리를 따로 뽑아 저장소 밖에서 전체 실행**해 확인했다 —
> `44 failed, 1722 passed`, **실패 목록까지 완전히 동일**.
>
> ⚠️ **CI 는 지금 빨간불이다** (새 PC 탓이 아니다). `main` 최근 100건에 `success` **0건**(최소 2026-08-29 `#557` 이후 연속),
> 실패 job 은 「사장님 사상 단위 테스트」 하나이고 원인은 로컬 7건 실패와 **같은** `test_martingale_stage_entry.py` 다.
> 🚨 마틴게일 = **실자금 증액 로직**이라 새 PC 에서 우선 확인이 필요하다.

---

### 13단계 🆕 [새 PC] — 앱 기동 (선택, 그리고 위험)

**⛔ 워커(`scheduler` / `user-stream` / `mark-price-stream`)는 VPS 를 내렸다는 확신이 없으면 켜지 않는다.**

실계정 API 키는 `.env` 가 아니라 **DB 에 암호화되어** 들어 있고(`exchange_accounts.api_key_enc`),
`.env` 의 **`DATABASE_URL`(운영 Neon) + `ENCRYPTION_KEY`** 두 개만 맞으면 **그대로 복호화된다.**
즉 로컬에서 띄우는 순간 **VPS 스케줄러와 같은 계정·같은 DB 에 붙은 두 번째 스케줄러**가 된다
→ 중복 주문 / 손절 취소 / 익절 이중 실행 / API 호출량 2배 → **418 IP ban**.

api 만 띄우려면:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis api && docker compose ps --services --filter status=running
```

**성공 판정**: 출력에 `db` `redis` `api` **3개만**. `http://localhost:8000` 에서 대시보드 HTML.
(참고: `/` 는 200 이 아니라 **307 → `/admin-ui`** 다.)

**실패하면**: 🚨 **`docker compose up -d` 를 인자 없이 쳤는지 되짚는다.** 인자가 없으면 워커 3종 포함 9개가 전부 뜨고,
`restart: unless-stopped` 라 **재부팅해도 되살아난다.** 보이면 즉시:

```bash
docker compose stop scheduler user-stream mark-price-stream
```

⏪ **이미 띄워 버렸다면**: 즉시 `docker compose down`. 그 다음 **바이낸스 화면에서 그 시간대의 주문·포지션을 눈으로 확인**한다.
DB 를 손으로 고치지 말고 사장님께 보고할 것.

> 🆘 **거래를 즉시 멈추는 정식 경로 = Kill-Switch API**
> `POST /api/v1/admin/kill-switch/{exchange_account_id}/enable` (해제는 `/disable`)
> — `app/api/v1/admin/operations.py:257`, `:274`. 로그인 토큰 필요, 계정 소유권 검증 있음.
> ⚠️ **만능이 아니다**(메모리 「Kill-Switch 3대 공백」): KS 를 켜도 **증거금 주입은 계속되고**,
> **해제하는 순간 밀려 있던 알람이 일괄 발사**되며, dust orphan 포지션 하나가 **계정 전체를 차단**한 전력이 있다.

---

### 14단계 🆕 [새 PC] — VPS 접속 확립 (전부 읽기 전용)

```bash
ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname && uptime && df -h /'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && git log --oneline -3 && git rev-parse --abbrev-ref HEAD'
```

```bash
ssh root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic current'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

**성공 판정** (2026-09-03 09:20 UTC 실측):

| 확인 | 기대 출력 | 다르면 |
|---|---|---|
| 컨테이너 | **9개 전부 `Up`** | Exit/Restarting 이 있으면 섹션 5 §7 로그부터 |
| 브랜치 / HEAD | `main` / `ded22f3` (또는 그 이후) | 다른 브랜치면 **배포 상태가 아니다** |
| `/health` | `{"status":"ok"}` | api 가 죽었거나 기동 중 |
| alembic | `0034_surge_ladder (head)`, `current == heads` | 다르면 섹션 5 §6-3 |
| ban 키 | **빈 값** (아무것도 안 나옴) | 숫자가 나오면 🚨 섹션 5 §8 즉시 |

**실패하면**: `Permission denied (publickey)` 는 고장이 아니라 **5단계 SSH 키가 아직 없다는 뜻**이다.

---

<a id="step-15"></a>
### 15단계 🆕 [새 PC] — 🏁 이전이 끝났는지 확인하는 최종 검증

> **이 5개를 전부 통과해야 이전이 끝난 것이다.** 하나라도 실패하면 옛 PC 를 지우지 마라.

**① 메모리를 Claude 가 실제로 읽는가** — 「파일이 있다」가 아니라 「읽힌다」를 본다.
슬러그가 한 글자라도 틀리면 파일은 멀쩡한데 Claude Code 는 **조용히 못 읽는다.**

1. `cd "/c/Users/user/바이낸스/binance-auto-trader"` 후 **Claude Code 를 연다.**
2. 이렇게 묻는다: **「메모리에서 Fix 298 이 무엇이었는지 말해줘」**

**성공 판정**: 「볼밴 분할 손절 후 재진입에서 사장님 사다리(10/300/600)를 써 **이중 마틴게일**이 될 뻔한 것을 검증에서 잡았다」는 취지의 답.
**실패**: 「모른다 / 코드에서 찾아보겠다」 → 메모리가 안 읽히고 있다. 8단계로 돌아가 슬러그를 다시 계산하고,
계산값과 `ls "$HOME/.claude/projects"` 의 실제 폴더명을 눈으로 대조한다.
(이 질문의 답은 코드에는 없고 `MEMORY.md` 에만 있다 — 그래서 판별식이 된다.)

**② 사상 단위 테스트가 도는가**:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest tests/unit -q -k "sasang or doctrine or sajangnim" 2>&1 | tail -3
```

**성공 판정**: 옛 PC 와 **같은 결과**. (섹션 1 §4-2 기준 `28 passed in 1.05s` 인 집합이 있다.)

**③ 전체 테스트 기준선**:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q 2>&1 | tail -3
```

**성공 판정**: `44 failed, 1722 passed`(`.env` 있음) 또는 `52 failed, 1714 passed`(`.env` 없음).
숫자보다 **실패 테스트 이름 목록이 같은지**를 본다.

**④ VPS 접속 + 배포 커밋 일치**:

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && git rev-parse --short HEAD' && cd "/c/Users/user/바이낸스/binance-auto-trader" && git rev-parse --short origin/main
```

**성공 판정**: VPS 가 `ded22f3` 또는 그 이후. 두 값이 다르면 **VPS 가 아직 배포 안 된 커밋이 있다는 뜻**이지 고장이 아니다 —
배포 여부는 사장님이 결정한다.

**⑤ DB 가 진짜 Neon 인지** (🚨 이게 가장 중요한 자가진단):

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"strategy_instances:\", db.execute(text(\"select count(*) from strategy_instances\")).scalar())
"'
```

**성공 판정**: 숫자가 나온다 — **2026-09-03 실측 `1487`**.

**실패하면**: 🚨 **`0` 이 나오면 데이터가 날아간 게 아니라 빈 로컬 `db` 컨테이너를 보고 있는 것**이다.
DB 는 로컬 `db` 컨테이너가 아니라 **외부 Neon** 이다. `docker compose exec db psql` 로 조회하면 **빈 DB** 가 나와
「테이블이 없다」는 오진에 이른다. 반드시 위처럼 **api 컨테이너의 앱 세션**으로 접근한다
(`PYTHONPATH=/app` 을 빼면 `ModuleNotFoundError`, 쿼리가 실패하면 `db.rollback()` 을 해야 다음 쿼리가 돈다).

---

### 16단계 — 🚨 옛 PC 는 아직 지우지 않는다

15단계 5개를 **전부** 통과하고 **실제로 한 세션을 문제없이 돌린 뒤**에 정리를 시작한다.
그때까지 옛 PC 의 `~/.claude/`, `~/.ssh/`, 저장소, worktree 를 **최소 2주** 그대로 둔다.
🚨 그 전에 `git worktree remove` · `rm -rf` · 디스크 포맷 금지.

---

<a id="sec-1"></a>

## 1. 사장님 매매 사상과 헌법 — 가장 먼저 읽어야 할 것

> 조사 시점 2026-09-03 · 코드 기준 커밋 `ded22f3` (Fix 327) · 브랜치 `claude/infallible-euler-6dc297`
> 이 섹션은 **새 PC 의 새 세션이 첫 5분에 읽어야 할 것**만 담는다.
> 코드·인프라 이전 절차는 다른 섹션에 있다.
>
> 📌 **현재 HEAD = `e51d9a8`** (= `origin/main`). `ded22f3` → `e51d9a8` 은
> `docs/handoff/` 102개 파일만 추가한 **문서 전용 커밋**이라 (`git diff --stat ded22f3 e51d9a8 -- backend/` = 빈 출력)
> 아래 코드 인용은 HEAD 에서도 전부 그대로다 (본 검증에서 재확인).

#### 🧭 이 문서의 명령을 새 PC 에서 돌리는 법 — **먼저 읽을 것**

아래 모든 `cd` 명령은 **옛 사무실 PC 의 worktree 경로**로 적혀 있다.
`.claude/worktrees/infallible-euler-6dc297` 는 Claude Code 가 그때 만든 임시 worktree라
**새 PC 에는 존재하지 않는다.** 그 브랜치는 이미 `origin/main` 에 머지돼 있으므로
새 PC 에서는 **clone 한 저장소 루트를 그대로 쓰면 된다.**

Git Bash 를 열 때마다 한 번 정의해 두고, 문서의 `cd "C:/Users/.../infallible-euler-6dc297"`
자리를 `cd "$REPO"` 로 바꿔 읽어라.

```bash
REPO="/c/Users/user/바이낸스/binance-auto-trader" && cd "$REPO" && git fetch origin && git status -sb | head -1
```

(다른 경로에 clone 했으면 `REPO` 값을 그 경로로 바꾼다.
🚨 단, **경로를 바꾸면 §1-2 의 메모리 폴더 이름도 달라진다** — §1-2 를 반드시 읽을 것.)

🚨🚨 **`main` 이 나온다고 최신인 것이 아니다 — 여기서 사고가 난다.**
「브랜치 이름만」 보는 `git rev-parse --abbrev-ref HEAD` 는 **뒤처짐을 못 본다.**
본 검증에서 **옛 사무실 PC 의 `$REPO`(= main 워크트리)는 `main` 브랜치이면서
`origin/main` 보다 커밋 30개 뒤처져 있었다** (`git rev-list --left-right --count origin/main...main` = `30  0`).
= **Fix 299~327 이 통째로 없는 옛 코드다.**

그래서 위 명령은 `git fetch` 를 먼저 하고 `git status -sb` 로 **뒤처짐 숫자까지** 본다.

- `## main...origin/main` (뒤에 아무것도 없음) → 최신. 정상.
- `## main...origin/main [behind 30]` → 🚨 **옛 코드다.** 이 상태에서 코드를 읽거나
  인용하거나 배포하면 전부 틀린다. 먼저 최신으로 맞춘다:

```bash
cd "$REPO" && git merge --ff-only origin/main
```

🚨 **`git reset --hard` / `git checkout .` / `git clean -fd` 로 맞추지 마라.** 커밋 안 된
작업이 **복구 불가능하게** 사라진다. `--ff-only` 는 실패하면 아무것도 바꾸지 않으니 안전하다.
`--ff-only` 가 거절되면 로컬에만 있는 커밋이 있다는 뜻이니 **멈추고 `git log origin/main..HEAD` 로 무엇인지 먼저 볼 것.**

---

### 0. 30초 요약 — 이것만은 반드시

| # | 절대 잊지 말 것 | 왜 |
|---|---|---|
| 1 | **실자금 메인넷이다.** 지금 이 순간 활성 전략 24건이 돌고 있다 | VPS 실측(아래 §7) |
| 2 | **사장님 사상 > 코드.** 코드가 사상과 다르면 코드가 틀린 것이다 | `DEVELOPMENT_PRINCIPLES_2026-06-07.md:21` |
| 3 | **말하기 전에 재라.** 이 저장소에서 추론으로 말한 진단은 반복해서 반증됐다 | §5 표 20행 |
| 4 | **고치기 전에 검증하라(오케스트라).** 사장님이 20번 반복 지적하신 사안 | §4-2 |
| 5 | **묻지 말고 진행하라.** 단, 실자금 조작·파괴적 작업·사상 변경은 예외 | §4-1 |
| 6 | 🚨 **사상·헌법·반증 기록은 저장소 밖 메모리에 있다. git clone 만으로는 안 따라온다** | §1 |
| 7 | 🚨 **`ENCRYPTION_KEY` 를 새로 만들지 마라.** 잃으면 DB 의 바이낸스 API 키(`exchange_accounts.api_key_enc`)를 **영원히 복호화할 수 없다** | §0-1 · `secrets.md` |
| 8 | 🚨 **새 PC 에서 앱·워커를 로컬로 띄우지 마라.** VPS 가 같은 키로 이미 돌고 있어 **중복 주문**이 나가고, **IP ban(418)** 은 집 IP 로도 똑같이 걸린다. 안전한 것은 pytest 와 읽기 전용 SSH 조회뿐 | §4-2 끝 |
| 9 | 🚨 **`main` 에 푸시 = 실자금 배포 대상을 바꾸는 것.** `backend/` 가 바뀌었으면 실행 테스트 + alembic 확인을 먼저. **force push 금지** | §4-1 |
| 10 | 🚨 **`git stash` / `reset --hard` / `clean -fd` 를 맨손으로 쓰지 마라.** 이 저장소는 **worktree 5개를 공유**하고 stash 스택은 저장소 전체가 하나다 | §4-1 |

#### 0-1. 🚨 비밀 값은 이 문서에 없다 — 그리고 그래야 한다

이 문서(사상·헌법)에는 **비밀 값이 한 개도 들어 있지 않다.** 앞으로도 넣지 마라.
새 PC 의 `.env` 구성은 **`docs/handoff/2026-09-03/secrets.md` 가 정본**이다.

새 PC 로 옮기기 전에 이것만은 알고 시작할 것:

| 🚨 | 왜 치명적인가 |
|---|---|
| **`ENCRYPTION_KEY` 는 Fernet 대칭키 하나뿐이다** (`backend/app/core/crypto.py:33-56`) | 이 키로만 `exchange_accounts.api_key_enc` / `api_secret_enc` 가 열린다. **백도어도 관리자 재설정도 없다** — 잃으면 바이낸스에서 키를 **새로 발급**받는 것 말고 방법이 없다 |
| `deploy/generate-secrets.sh` 는 **새 `ENCRYPTION_KEY` 도 같이 만든다** | 출력을 통째로 `.env` 에 붙이면 **기존 DB 의 API 키가 즉시 복호화 불가**가 된다. 이건 「완전히 새 DB 로 시작할 때」용 스크립트다 |
| 기존 DB 를 계속 쓸 것이므로 | `ENCRYPTION_KEY` 는 **글자 하나도 바꾸지 말고 그대로** 옮긴다 (회전이 정말 필요하면 `secrets.md` §3-3 의 재암호화 절차와 **반드시 같이**) |

🚨 **비밀을 옮기는 방법** — 값은 **채팅·이메일·이슈·스크린샷·커밋에 절대 넣지 않는다.**
Claude 에게도 값을 붙여넣지 마라(대화 로그에 남는다). 비밀번호 관리자나
사장님이 직접 접근하는 VPS `.env` 에서 **사장님 손으로** 옮긴다.
같은지 확인만 필요하면 값이 아니라 **SHA-256 앞 12자리 지문**을 비교한다 (`secrets.md` §4).

#### 0-2. 🚨🚨 이 저장소는 **공개(public)** 다 — 핸드오프를 커밋하기 전에 반드시 읽을 것

본 검증에서 **실측**했다 (2026-09-03, 인증 없는 요청):

```bash
curl -s https://api.github.com/repos/herosys1-crypto/binance-auto-trader | grep '"visibility"'
```

→ `"private": false,` / `"visibility": "public"` = **인터넷의 누구나 읽을 수 있다.**

그런데 §1-1 은 「핸드오프 문서를 커밋·푸시하라」고 지시한다. **그 푸시는 공개 게시다.**
현재 상태 (실측):

| 항목 | 실측 |
|---|---|
| 이미 푸시돼 **공개된** `docs/handoff/` 파일 | **102개** (커밋 `e51d9a8`) |
| 그중 VPS **root SSH 엔드포인트**(`root@159.65.137.250`)가 적힌 파일 | **8개** — 공개 상태 |
| 공개된 handoff 파일에 **실제 비밀 값** | ✅ **0건** (본 검증에서 키·토큰·DSN·개인키 패턴 전수 스캔) |
| `secrets.md` 의 지문 | ✅ 안전 — SHA-256 앞 12자리라 **역산 불가** |

⇒ **비밀 값은 새지 않았다.** 하지만 **실자금 메인넷 서버의 root 접속 주소와 운영 구조 전체가
공개**돼 있다. SSH 키가 없으면 바로 들어오지는 못해도, 공격 대상이 특정된 상태다.

**떠나기 전에 사장님이 결정하실 것 (내가 임의로 바꾸지 않았다 — 설정 변경이라 승인 사안):**

1. **저장소를 private 으로 바꾼다** (가장 확실. Settings → General → Danger Zone → Change visibility).
   핸드오프에 운영 정보를 계속 담을 거면 이게 정답이다.
2. private 으로 못 바꾸면 → VPS 에서 **비밀번호 로그인 금지 + root 직접 로그인 금지 + fail2ban**
   을 확인하고, 방화벽에서 SSH 를 **사장님 IP 만** 허용한다.
3. 어느 쪽이든 **`.env` 가 커밋된 적 없는지** 확인한다:

```bash
cd "$REPO" && git log --all --oneline -- "backend/.env" "**/.env" | head
```

→ **아무것도 안 나와야 정상.** 뭔가 나오면 그 커밋에 비밀이 박제된 것이니
**키를 즉시 새로 발급**하고(히스토리는 지워도 이미 복제됐다고 가정) `secrets.md` §3-3 회전 절차를 탄다.

🚨 **공개 저장소라는 사실을 모른 채 「핸드오프니까 자세할수록 좋다」고 쓰면 사고가 난다.**
앞으로 이 폴더에 무언가 적을 때는 **「이게 공개돼도 괜찮은가」를 먼저 묻는다.**

---

### 1. 🚨 최우선 블로커 — 지식의 90%가 저장소 밖에 있다

이 프로젝트의 **사장님 사상 verbatim, 헌법 번호, 반증된 가설, 사고 이력**은
git 저장소가 아니라 **Claude Code 자동 메모리**에 있다.

```
실제 위치: C:\Users\user\.claude\projects\C--Users-user------binance-auto-trader\memory\
파일 수  : 83개 (MEMORY.md 인덱스 1 + 본문 82)
크기     : 764K
```

확인한 사실:

| 항목 | 실측 |
|---|---|
| 메모리 디렉터리가 저장소 안에 있는가 | ❌ 저장소 **밖** (`~/.claude/projects/<slug>/memory/`) |
| 저장소에 백업이 있는가 | ✅ `docs/handoff/memory-backup-2026-09-03/` 83개 — **내용 완전 일치**(`diff -rq` 차이 0건, 본 검증에서 재실행) |
| 그 백업이 git 에 커밋돼 있는가 | ✅ **커밋·푸시 완료** (커밋 `e51d9a8`, `git ls-files docs/handoff` = **102건**, `origin/main` 과 0/0). ⚠️ 이 문서 초안 작성 시점엔 untracked 였고 그 뒤 커밋됐다 |
| `.gitignore` 가 막고 있는가 | 아니다 (`git check-ignore` exit=1) |
| 복원 절차 정식 문서 | ✅ `docs/handoff/RESTORE-2026-09-03.md` (커밋돼 있다). §1-2 보다 **자세하니 새 PC 에서는 그쪽을 정본으로 볼 것** |
| 저장소에 `CLAUDE.md` 가 있는가 | ❌ 없다 (`git ls-files \| grep -i claude` = `.claude/agents/{impl,locator,mech}.md` 뿐) |

**⇒ `git clone` 만으로는 사상·헌법·반증 기록이 「저장소 안의 백업 폴더」로만 따라온다.
Claude Code 가 자동으로 읽는 자리(`~/.claude/projects/<SLUG>/memory/`)로 §1-2 처럼 **직접 복사해야** 한다.
복사하지 않으면 새 세션은 이 지식을 하나도 모른 채 시작한다.**

#### 1-1. 사무실 PC 에서 먼저 할 일 — ✅ **이미 끝났다**

메모리 백업 83개는 커밋 `e51d9a8` 로 `origin/main` 에 푸시돼 있다. 다시 할 필요 없다.
확인만 하려면 — 🚨 **반드시 `origin/main` 을 직접 봐야 한다:**

```bash
cd "$REPO" && git fetch origin && git ls-tree -r --name-only origin/main -- docs/handoff/memory-backup-2026-09-03 | wc -l
```

→ `83` 이 나와야 한다.

🚨🚨 **`git ls-files` 로 재지 마라 — 여기서 속는다.**
`git ls-files` 는 **지금 체크아웃된 커밋**만 본다. 옛 사무실 PC 의 `$REPO`(main 워크트리)는
`origin/main` 보다 **30 커밋 뒤처져 있어서**(프롤로그 참조) 백업 커밋을 아직 모른다.
그래서 거기서 `git ls-files docs/handoff/memory-backup-2026-09-03 | wc -l` 을 돌리면
**`0` 이 나온다** (본 검증에서 실제로 재현했다).
그 `0` 을 보고 「백업이 없구나」 하고 다시 만들면 **헛수고 + 중복 커밋**이다.
`git ls-tree ... origin/main` 은 체크아웃 상태와 무관하게 원격 내용을 보므로 속지 않는다.

🚨 **아직 안 된 것**: 이 핸드오프 문서 폴더 `docs/handoff/2026-09-03/` 자체는
**untracked 다**(`git status` = `?? docs/handoff/2026-09-03/`, 8개 파일).
새 PC 에서 읽으려면 **떠나기 전 사무실 PC 에서** 커밋·푸시해야 한다:

**① 먼저 무엇이 올라가는지 본다** (문서 8개만이어야 한다. `backend/` 가 보이면 **멈춰라**):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git add docs/handoff/2026-09-03 && git status --short && git diff --cached --stat -- backend/
```

마지막 `git diff --cached --stat -- backend/` 가 **빈 출력**이어야 한다.
🚨 뭔가 나오면 코드가 섞인 것이다 — 실자금 시스템의 `main` 에 검증 안 된 코드가
들어간다. `git restore --staged backend` 로 그 부분만 내리고 다시 확인할 것.

**② 커밋·푸시** (문서 전용임을 ①에서 확인한 뒤에만):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git fetch origin && git commit -m "docs(handoff): 2026-09-03 새 PC 이전 핸드오프 문서 8종" && git push origin HEAD:main
```

🚨 **`rejected` 가 나오면 `--force` 를 붙이지 마라.** `origin/main` 이 그새 움직였다는
뜻이고, force 를 붙이면 **그 커밋들이 사라진다**(실자금 코드일 수 있다).
`git fetch origin && git merge --no-edit origin/main` 후 다시 푸시한다.

**되돌리는 법** (잘못 올렸을 때): `main` 은 배포 대상이므로 **히스토리를 지우지 말고 되돌린다.**

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git revert --no-edit <올린커밋> && git push origin HEAD:main
```

(`git reset --hard` + force push 는 **금지** — §4-1 의 「파괴적 작업 = 사장님께 묻는다」에 해당한다.)

#### 1-2. 새 PC 에서 — 메모리를 제자리에 복원

> 📖 **정본은 `docs/handoff/RESTORE-2026-09-03.md`** (clone 하면 같이 온다). 아래는 요약이다.

**순서가 중요하다. 위에서 아래로 그대로 한다.**

**① 먼저 저장소를 clone 한다** (이게 없으면 아래 명령이 전부 실패한다).
경로를 **옛 PC 와 똑같이** 두는 것이 가장 안전하다 — 그래야 아래 슬러그가 저절로 같아진다:

```bash
mkdir -p "/c/Users/user/바이낸스" && cd "/c/Users/user/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git && REPO="/c/Users/user/바이낸스/binance-auto-trader"
```

**② 슬러그를 확인한다.**
메모리 디렉터리 이름은 **저장소 절대경로에서 자동 생성되는 슬러그**다.
`C:\Users\user\바이낸스\binance-auto-trader` → `C--Users-user------binance-auto-trader`
(드라이브·역슬래시 → `-`, 한글 「바이낸스」 5글자 → `-` 5개).

🚨 **새 PC 의 사용자명이나 clone 경로가 다르면 슬러그가 달라진다.** 그러면 옛 이름 그대로
복사해도 메모리가 안 읽힌다. **①에서 clone 한 그 디렉터리 안에서** Claude Code 를 한 번
실행해 종료하면 슬러그 디렉터리가 자동 생성된다. (다른 폴더에서 실행하면 **엉뚱한 슬러그**가
생기니 반드시 저장소 안에서 실행할 것.)

```bash
cd "$REPO" && claude
```

그런 다음 실제로 생긴 슬러그를 확인한다:

```bash
ls "$HOME/.claude/projects/"
```

**③ 그 이름 아래로 복사한다.**
`$REPO` 가 정의돼 있어야 하고, 없으면 `cd` 로 저장소 안에 있어야 한다:

🚨 **`mkdir -p` 를 그냥 쓰면 안 된다 — 이 명령이 §1-2 의 경고를 스스로 무력화한다.**
`<SLUG>` 를 **오타 내거나 옛 PC 이름을 그대로 붙여넣으면** `mkdir -p` 가 그 틀린 이름의
디렉터리를 **군말 없이 만들어 준다.** 복사는 「성공」하고 `wc -l` 도 `83` 이 나오는데
**Claude Code 는 그걸 영영 읽지 않는다.** 지식이 없는 채로 실자금 시스템을 만지게 된다.

그래서 **디렉터리를 만들지 말고, ②에서 실제로 생긴 것을 그대로 쓴다.**
아래는 슬러그를 손으로 적지 않고 **자동으로 고르는** 방법이다 (`$SLUGDIR` 확인용):

```bash
SLUGDIR="$(ls -1d "$HOME"/.claude/projects/*binance-auto-trader 2>/dev/null | tail -1)"; echo "SLUGDIR=$SLUGDIR"; test -d "$SLUGDIR" && echo "OK: 존재한다" || echo "🚨 없다 — ②(저장소 안에서 claude 1회 실행)를 먼저 하라"
```

🚨 여러 줄이 나오면 슬러그 후보가 둘 이상이라는 뜻이다(옛 폴더가 남아 있는 등).
**멈추고 `ls "$HOME/.claude/projects/"` 로 눈으로 고른 뒤 `SLUGDIR` 을 직접 지정하라.**

**③-a 덮어쓰기 전에 기존 메모리를 먼저 백업한다.**
②에서 `claude` 를 한 번 돌렸다면 그 세션이 이미 `MEMORY.md` 를 썼을 수 있고,
아래 `cp` 는 **같은 이름 파일을 말없이 덮어쓴다.** 복구 지점을 먼저 만든다:

```bash
test -d "$SLUGDIR/memory" && cp -a "$SLUGDIR/memory" "$SLUGDIR/memory.bak-$(date +%Y%m%d-%H%M%S)" && echo "백업 완료" || echo "기존 memory 없음 — 백업 불필요"
```

**③-b 복사한다** (디렉터리를 새로 만들지 않는다):

```bash
cd "$REPO" && cp -a "$REPO/docs/handoff/memory-backup-2026-09-03/." "$SLUGDIR/memory/"
```

**④ 복원 검증** (`83` 이 나와야 한다. 인덱스 `MEMORY.md` 1 + 본문 82):

```bash
ls "$SLUGDIR/memory" | wc -l
```

`83` 이 아니면 복사가 덜 된 것이다. **이 숫자를 확인하기 전에는 다음 단계로 가지 마라.**
🚨 그리고 **`83` 은 「Claude 가 읽는다」를 증명하지 않는다** — 위 경고대로 엉뚱한
디렉터리여도 `83` 은 나온다. 진짜 확인은 **새 세션을 열어 「사장님 사상 ⑦ 자본 사다리
숫자가 뭐냐」고 물어 `10 / 300 / 600` 이 나오는지** 보는 것이다.

#### 1-3. 🚨 헌법 번호의 정본 목록은 **어디에도 없다**

메모리와 코드 주석은 「헌법 78」「헌법 161」「헌법 170」처럼 **번호로** 원칙을 참조한다.
그런데 저장소에는 **번호가 참조될 뿐 정의돼 있지 않다.** 저장소에서 언급되는 가장 큰
번호들을 보는 명령 (본 검증에서 실행 확인, exit=0):

```bash
cd "$REPO" && grep -rohn "헌법 [0-9]\+" --include=*.md --include=*.py . | grep -o "헌법 [0-9]*" | sort -u -t' ' -k2 -n | tail -5
```

출력:

```
헌법 161
헌법 162
헌법 167
헌법 169
헌법 170
```

⚠️ 이건 **「언급된」 번호이지 「정의된」 번호가 아니다.** 정의는 어디에도 없다:

- `DEVELOPMENT_PRINCIPLES_2026-06-07.md` (저장소 **루트**에 있다) = **헌법 원본**이지만
  번호 목록이 아니라 **5대 원칙 + 5 사고 패턴**의 서술문이다 (361줄 — 본 검증에서 `wc -l` 확인).
  예: 「사장님 사상 > 코드」는 21행 부근 `### 2️⃣ 사장님 사상 = 코드보다 우선` 이다.
- 번호 18개까지의 목록은 **저장소가 아니라 메모리**의 `project_overview.md`(756줄) 754행 부근에
  한 줄 요약으로만 있다 — §1-2 를 끝내야 볼 수 있다.
- **19~172 번은 각 세션 메모리 파일 말미에 흩어져 있고 통합 목록이 없다.**

⇒ 새 세션이 「헌법 161」을 보면 **정의를 찾을 수 없다.** 번호를 인용하지 말고
   그 번호가 적힌 메모리 파일을 직접 열어 문맥으로 읽어라.
   ⚠️ 확인 못 함 — 통합 목록을 만드는 작업은 사장님 지시가 없어 하지 않았다
   (§4-4 「요구 이외 기능 추가 금지」).

---

### 2. 사장님 매매 사상 (verbatim)

> 🚨 **요약하면 왜곡된다.** 아래 인용은 원문 그대로다. 원본은
> `memory/project_2026-08-30_sajangnim_strategy_doctrine_v3.md` (사상 v3) 과
> `memory/project_2026-08-25_sajangnim_long_short_philosophy_v2.md` (v2).

#### ① 급등 정점 SHORT — 주력

> "당일 급등하는 심볼을 모니터링하면서 15분차트와 obv 최고점 macd rsi cci 모든 지표가
> **최고점에서 하락과 지지를 여러번 반복**하고 하락을 시작할 심볼에 투자하는거야"

> "15분봉의 빠른 움직임으로 **4시간봉 최상단 볼밴 최상단밖** obv 최고점 macd rsi cci
> 모든 지표가 최고점에서 하락하면 본격적으로 포지션 진입하기 시작하고
> **전체자산에 1-2% 분할 진입**해서 하락을 기다리는거야"

2026-09-02 에 진입 판정이 확정됐다 — **봉수·심도는 후보 감지, 진입은 「극값에서 꺾일 때」**.
사장님 마지막 문장이 지배한다:

> "고정은 아니야… **최고점 최저점이라 판단되면 무조건**"

| 항목 | 상태 | 근거 |
|---|---|---|
| 꺾임 판정 도입 효과 | SHORT 건당 +0.673 → **+1.800** (승률 70.0→77.0%) | `memory/project_2026-09-02_bb_entry_extreme_turn.md` |
| **전체자산 1~2% 분할** | 🔴 **미구현** — 고정 USDT (10/300/600) | `backend/app/services/sajangnim_capital.py:57` |
| 4H 볼밴 상단 밖 확인 | 🟡 2026-08-31 감사 때 「읽는 코드 0건」이었으나 **지금은 판정에 쓰인다** | `surge_peak_ladder.py:281`+`:288`, `surge_peak_ladder_worker.py:274`,`:281` |

> ⚠️ **`surge_peak_ladder.py:280` 을 근거로 인용하지 마라.** 280 은 `d["bb4h_broken"] = …`
> 로 **디버그 dict 에 기록만** 하는 줄이라, 이것만 보면 「기록뿐, 판정엔 안 쓴다」로 잘못 읽힌다.
> 실제로 강제하는 줄은 **281** (`c["4H 상단 경험"] = …`) 과 **288**
> (`v.ok = all(x is True for x in c.values())`) 이다. 값이 `None`(모름)이면 **fail-closed 로 진입 거부**다
> (`tests/unit/test_surge_peak_ladder.py:177` = `assert not _ev(bb4h_broken=None).ok`).

#### ② LONG = 급등 중 조정 → 다시 급등 (사장님 1순위)

> "롱은 당일 **급등후 큰조정**에 롱으로 들어가서 분할 익절은 우리가 만들어둔
> **볼밴 중간 전략**을 사용하면됨"
> "롱은 지금 **급등중인 심볼**을 찾아 **지속상승**에 투자가 확실해 —
> 지속적으로 상승과 조정후 **몇일 이상 상승**하는 심볼에 투자 해야해"

🚨 **2026-08-31 사장님 직접 정정** — 이전 세션(나)이 사상을 잘못 옮겼다:

> "이건 내가 **급등락 종목을 찾아서 포지션 진입을 한다**고 했어. 이렇게 제안은 내가 하지 않았어.
> **급등중에 조정은 다시 급등으로 간다**고 했어 **바로 수익을 많이 낼수 있고** 했고
> 급락한건 **언제 어떤 심볼이 급등하는 찾는게 힘들다**고 헀어
> **포지션 진입을 하지 않는다고 안헀어**"

⇒ 세 가지가 확정됐다:
1. **급락 종목 LONG 진입을 금지한 적이 없다.** 「타이밍 찾기가 어렵다」는 난이도 서술이었다.
2. **주력은 「급등 중 조정 → 다시 급등」**이고 이유는 **「바로 수익을 많이 낼 수 있다」**(빠른 회수).
3. 🚨 코드의 **「LONG = 급락만」(헌법 78 / Fix 87)은 사장님 제안이 아니다.**

🚨 **그런데 코드는 지금도 사장님과 정반대다.** HEAD 에서 직접 확인:

```
backend/app/workers/long_bottom_detector_worker.py:409
    if PATTERN_A_MIN_CHG <= chg24 <= PATTERN_A_MAX_CHG:   # +5% ~ +15% 상승
        return None          # skip!  (헌법 78 = LONG = 급락만!)
```

= 사장님이 1순위로 지목한 **「급등 중 조정」이 후보 단계에서 버려진다.**

#### ③ 급락 종목 SHORT

> "당일 급등하는 심볼은 상승후 조정을 차는거고 **급락한것은 이전급등에 대한 급락**이라
> 확실한 숏으로 급반등하는 위험을 줄이고 꾸준하게 수익을 만들수있어"
> "볼밴 중간하락 이후 와 **볼밴 하단 이탈시 지속적인 하락**에 포지션 진입.
> **볼밴 지지와 상승 / 볼밴 지지선 붕괴와 지속하락**을 찾아서 분할 포지션 진입이다"
> "한번 하락하는 심볼은 **원점으로 가는** 내려가는거야"

#### ④ OBV 가 방향의 최종 심판

> "무엇보다 **obv가 하락하지 않으면 결국은 obv 방향으로 간다**는거야.
> **볼밴 중단을 이탈했다가 다시 가는 경우가많아. 볼밴 하단까지 갔다가도
> obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"

우선순위: **OBV(방향) > 4H(확정된 흐름) > 15m(진입 타이밍)**.

🚨 코드의 실제 강제력은 **정반대로 뒤집혀 있다** (2026-08-31 감사):

| | 사장님 | 코드의 실제 강제력 |
|---|---|---|
| **OBV** | 방향의 **최종 심판** | fail-open 극단 거부권 (`obv_gate.py:180`) |
| **4H** | **확정된 흐름** | 참고 / 역방향일 때만 veto |
| **15m** | 진입 **타이밍만** | 🔴 **유일한 필수 관문** (`peak_confirmation.py:186, :199`) |

출처 `docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md:181-185`.
⚠️ 그 문서는 커밋 `f7ecec5` 기준이라 일부 항목은 이후 수정됐다(§2-① 4H 항목 참조).
**인용 전에 반드시 HEAD 에서 다시 grep 할 것.**

#### ⑤ 시간프레임 역할 — 구조의 뼈대

> "**4시간을 확정된 흐름으로 보고** 만들어줘.
> 4시간이 조정인데 **지속상승하는 심볼은 롱으로 미리미리 분할 진입**해서
> 큰 수익을 만들어가면 좋겠어"

```
4시간봉 = 확정된 흐름   → 방향·국면(regime)을 정한다. 여기가 상위 권한.
15분봉  = 진입 타이밍   → 그 방향 안에서 언제 들어갈지만 정한다.
```

🌟 **「미리미리」** = 바닥을 **확인하고** 들어가는 게 아니라, **조정 구간에 미리 나눠 깔아둔다**.
2026-09-03 Fix 327 의 실측이 이 사상을 독립적으로 확인했다 — §5 표 3~5행.

#### ⑥ 🚨 인간의 한계 — 시스템이 존재하는 이유 (**설계 제약**)

> "그런데 인간이라 **욕심을 제어 하지 못했어**. 이렇게 움직이는 심볼을 실시간으로
> 관찰하지 못해서 큰상승 큰하락에 **적절한 손절을 못했어**. 다시 빠른 진입할수 있으면
> 청산하고 다시 **손실금액보다 더 많은 포지션** 진입하고 싶어. 그런데 **충분히 기다려서
> 진입한 시점**에 포지션 진입을 할수 있게 로직을 만들고 싶어. 그런데 이렇게 하지 못하고
> **큰금액을 손실보면 그때부터는 더 빠른 시간에 큰수익을 위해서 무리한 투자**를 하면서
> 손실과 청산을 지속적으로 하게되었어"

🚨 **이 문단은 감상이 아니라 설계 제약이다.**
「손실 후 2배 재진입」은 **반드시 조건부**여야 한다 — 아무 때나 2배가 아니라
**「충분히 기다린 진입 시점」이 성립할 때만**.
**무제한 마틴게일로 구현하면 사장님이 겪은 그 실패를 자동화하는 것이 된다.**

실측이 이 위험을 그대로 확인했다 (최근 3일 종료 151건):

| 추가 횟수 | 건수 | 합계 | 건당 | 배수 |
|---|---|---|---|---|
| 추가 없음 | 97 | −1,288.42 | **−13.28** | — |
| 추가 1회 | 34 | −1,459.43 | **−42.92** | 3.2배 |
| 추가 2회 | 15 | −964.05 | **−64.27** | 4.8배 |
| 추가 7회 | 1 | −724.80 | −724.80 | 자본 6,800 |

**원인은 산수다.** 손절은 ROI(%) 기준인데 추가로 자본이 커지면 같은 ROI 라도
손실 **금액**이 그만큼 커진다. (`memory/project_2026-09-01_reentry_dead_and_peak_stall.md`)

#### ⑦ 자본 사다리 10 / 300 / 600 — 3단 재도전

> "급등과 급락을 하는 시장이야. **급등도 한계점이 있어. 그 한계점을 우리가 공략하는거야.**
> 그래서 실패하면 2번 더 기회가 있고, **첫번째는 실패할 확률이 매우 높지만**
> 최대한 실패하지 않을 위치에서 진입하고, 잘되면 추가 포지션 2번까지 진입해서 수익을 올린다."
> "실제로 **내가 욕심만 버리고 장기전을 하면 충분히 가능해.**
> 그렇게 24시간 이 일을 할 수 없어. **이 시스템이 필요한거야.**"

**사장님 숫자가 전부 정확하다** (검산 완료, `docs/spec/SAJANGNIM_3STEP_LADDER_2026-09-02.md`):

| 시도 | 1차 진입 | 추가1 | 추가2 | 총 투입 | TP1 15% | 사장님 말씀 |
|---|---|---|---|---|---|---|
| 1차 | **10** | 300 | 300 | 610 | **91.5** | "95부터" ✅ |
| 2차 | **300** | 300 | 300 | 900 | **135.0** | "135" ✅ |
| 3차 | **600** | 300 | 300 | 1200 | **180.0** | "180" ✅ |

| 시도별 승률 | 3연패 확률 | **심볼당 기대값** |
|---|---|---|
| 20% | 0.512 | **+27.98** |
| 27% (실측 자동 승률 하단) | 0.389 | **+49.19** |
| 34% (실측 자동 승률 상단) | 0.287 | **+66.04** |

🌟 **승률 20%에서도 흑자다.** 「3번 기회 + 손실 제한 + 큰 익절」이 그걸 만든다.
이것이 사장님 사상의 수학적 근거이며, 승률을 올리자는 제안보다 **구조를 지키는 것**이 먼저다.

코드 정의:

```bash
cd "$REPO" && sed -n '57p' backend/app/services/sajangnim_capital.py
```

→ `DEFAULT_CAPITAL_LADDER = [Decimal("10"), Decimal("300"), Decimal("600")]`

🚨 **미해결**: v219 템플릿에는 **2·3단계가 아예 없다**(`stages_count:1`, `capitals:[10.0]`).
그래서 사다리가 「단계」가 아니라 **재진입(전량 청산 후 새 전략) + 피라미딩**으로만 돈다.
템플릿에 2·3단계를 넣으면 전략당 자본이 10 → 910 이 된다 = **사장님 결정 대기**.

#### ⑧ 부분 손절 — 「10 USDT 만 남기고 청산」

> "1단계 100이든 1000이든 **10usdt 남기고**, 모든 단계에서 청산은 10usdt 만 남기고
> 모두 청산하고 다음 단계 진입하게 해줘"
> "기본전략과 같이 10usdt 남기고 청산하고 다음단계 진입하는 걸로 해줘
> **전략 인스턴스에 남겨둬야 겠어**"
> "왜 이것도 **10usdt 남기고 부분손절**을 해야 하는데 왜 이런거야"

핵심 3가지:

| 무엇 | 값 | 근거 |
|---|---|---|
| 「10 usdt」의 단위 | 🚨 **명목이 아니라 증거금** (레버 2면 명목 20) | 사장님이 직접 주신 수치를 코드로 재현해 소수점까지 일치 — Fix 324 (`61e19a8`) |
| **1단계는 정리하지 않는다** | 사장님 수치의 총 증거금 **310 = 10 + 300** 이 증거 | Fix 324 |
| 왜 0 이 아니라 10 을 남기나 | 전량 청산하면 전략이 종료돼 **화면에서 사라진다.** 잔량이 있어야 단계 감시가 이어진다 | `backend/app/services/stage_trim.py:1-30` |

세 가지 행동으로 갈린다 (`stage_trim.py` / Fix 316·326):

```
TRIM  → 10 USDT(증거금)만 남기고 부분 청산 → 다음 단계 진입
SKIP  → 이미 잔량 수준이다 → 손절도 진입도 하지 않고 그대로 둔다
BLOCK → 판정 불가 → 전량 청산 (안전측)
```

🚨 **`0` 하나로 「불필요」와 「불가능」을 같이 표현하면 안 된다** — 그렇게 만들었더니
호출부가 구분 못 해 사장님 사다리 1단계(명목 20)가 통째로 차단됐고, 단위 테스트
57건이 **각자 옳아서 전부 통과**하는데도 사양이 안 돌았다 (Fix 316).

🚨 잔량이 여전히 손절 ROI 아래라 **다음 사이클에 또 손절 대상**이 된다.
그때 SKIP 을 「전량 청산」으로 처리하면 12~17초 만에 남긴 것이 사라진다 (Fix 326 실서버 로그).
내가 근거로 적었던 **"손절을 건너뛰면 손실이 무한정 커진다"는 틀렸다** —
잔량 증거금이 10 USDT 면 **최대 손실도 10 USDT** 다.

#### ⑨ 🚨 세 방식은 완전히 다르다 (사장님이 세 번 강조)

> "**obv 자동과 확실하게 구분해야해**"
> "**기본전략과 obv자동은 완전히 다른거야**"
> "이건 아니야 **기본전략은 정해진 트리거에 진입하는거야.** 전략인스턴스에 선택한 옵션으로
> 부분 손절하고 다음 트리거 단가에 포지션 진입하고 또 손실이면 부분청산하고
> 다음단계 트리거 단가에 포지션 진입입니다."
> "v219 자동매매에서도 … **첫진입이 10이라 손절없이 그냥** 좋은 포지션에 2단계 300으로
> 진입후 손실이면 부분손절후 10 남기고 다음단계 모니터링 해서 **좋은 포지션에 진입**"

| 방식 | 진입 판정 | 식별 |
|---|---|---|
| **기본 방식** | **정해진 트리거 단가에 즉시** — 판정 없음 | `strategy_type` 접두사 없음, `mode='fixed'` |
| **OBV 자동** | `stage_entry_signal` **4중 게이트** (①OBV ②양방향 blocklist ③regime ③-b 진입창 ④정점확인) | `trigger_mode = OBV_REVERSE` (모달 경로만) |
| **v219 사다리** | 1단계 자본 **10** = 모니터링 후 좋은 포지션 | `auto_bb_break_SAJANGNIM_*` |

🚨 **셋 다 `trigger_mode = PRICE_DOWN_PCT` 라 `trigger_mode` 로는 구분이 안 된다.**
`strategy_type` 접두사로 갈라야 한다.

🚨 내가 저지른 오해 — **「좋은 포지션에 진입」을 「꺾임 판정을 추가하라」로 읽고
기본전략에 게이트를 붙이려 했다.** 사장님 설계와 정면으로 어긋났다.
정답은 후자였다: **부분 손절로 평단이 리셋되는 것 자체가 「좋은 포지션」**이다.

🔁 **「좋은 포지션」 같은 말을 들으면 「판정을 추가하라」인지 「이미 좋은 자리이므로
   그냥 하라」인지 반드시 확인할 것.**

#### ⑩ 모니터링 대상 — 급등 50 + 급락 50

> "당일 상승 50위까지 50개 하락 50위까지 50개 **100개를 매일 모니터링**해서
> 포지션에 진입이 가능하면 진입해줘"

이전 지시(「당분간 당일 10%이상 상승과 하락한 심볼만」, 절대값 기준)는 조용한 날
대상이 **252 → 26개(10.3%)** 로 급감해서, 순위 방식으로 바뀌었다 (Fix 325, `0459e8f`).
설정 `entry_rank_top_n`(기본 50) / `entry_chg24_gate_mode = rank|abs`.

---

### 3. 사상 vs 코드 — **정반대로 도는 것 8건**

`docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md:26-44` 의 한 장 요약.
⚠️ **커밋 `f7ecec5` 기준이라 일부는 이후 고쳐졌다.** 아래 「HEAD 재확인」 열은 내가 직접 확인한 것만 채웠다.

| 사상 | 코드 (2026-08-31 감사) | 판정 | HEAD(`ded22f3` = 코드상 `e51d9a8`) 재확인 |
|---|---|---|---|
| ① 4H 볼밴 상단 밖 확인 | 계산은 하는데 **읽는 코드 0건** | 🔴 모순 | ✅ **고쳐짐** — `surge_peak_ladder.py:281`(조건 등록)+`:288`(`all()` 강제). ⚠️ `:280` 은 기록만 하는 줄이니 근거로 쓰지 말 것(§2-① 주석) |
| ① 전체자산 **1~2%** 분할 | 고정 USDT (10/300/600) | 🔴 미구현 | 🔴 그대로 (`sajangnim_capital.py:57`) |
| ② LONG 대상 = 몇일 이상 지속상승 | 3일 +30% 이상이면 **후보 제외** | 🔴 정반대 | 🔴 **그대로** — `TREND_EXTREME_BULL_PCT_3D = 30.0` 이 `long_bottom_detector_worker.py:73,167` · `auto_long_at_bottom_worker.py:166,385` 에서 **실제 비교에 쓰인다**(죽은 상수 아님) |
| ⑤ LONG = 큰상승 시작 심볼 | LONG 후보 = 24h −15%~−3% **급락만** | 🔴 정반대 | 🔴 **그대로** (`long_bottom_detector_worker.py:409`) |
| ③ 급락 = 확실한 SHORT | `pump_completed_dumping` 으로 SHORT **차단** | 🔴 정반대 | 🔴 **그대로** — `pump_dump_regime.py:72-76 is_regime_blocked_for_short` 가 살아 있고 `stage_entry_signal.py:102` + 워커 6곳이 부른다 |
| ③ 볼밴 하단 **이탈**에 분할 SHORT | 분할 SHORT 는 **반등해서 밴드 위로 올라올 때** | 🔴 정반대 | ⚠️ 확인 못 함 |
| ④ 우선순위 OBV > 4H > 15m | 실제 강제력 **15m > 4H > OBV** | 🔴 뒤집힘 | ⚠️ 확인 못 함 |
| ⑥ 4H = 확정된 흐름 / 15m = 타이밍 | 15m 만 하드 게이트 | 🔴 뒤집힘 | ⚠️ 확인 못 함 |
| ⑥ 4H 조정 구간 LONG **미리 분할** | **국면 자체가 없음** | 🔴 없음 | ⚠️ 확인 못 함 |
| ⑤ 되돌림 비율 판정 | **주석에만 있고 계산 코드 0건** | 🔴 없음 | ✅ **고쳐졌다 (이 문서의 초안이 틀렸다)** — `backend/app/services/retracement.py`(Fix 236) 가 `retracement_ratio()` 로 정확히 그 식을 계산하고, `surge_pullback.py:45,143` 와 `auto_bb_breakdown_worker.py:1615-1623` 이 **실제로 LONG 진입을 차단**한다 |
| ⑦ 「욕심 제어」 계좌 단위 제동 | 일일 손실 한도 **기본 미설정** | 🟡 부분 | 🔴 **그대로 — 운영 DB 로 확인.** `exchange_accounts.daily_loss_limit_usdt` 가 **계정 2개 모두 NULL**, `system_settings` 에 `daily_loss%` 행 **0건**, `config.py:33` 기본값도 `None`. `daily_loss_aggregator` 는 **no-op 로 돌고 있다**(`daily_loss_aggregator.py:9,53-65`) = 지금 **계좌 단위 제동이 사실상 없다** |

새 세션이 HEAD 에서 위 4행을 한 번에 재확인하는 명령 (본 검증에서 실행 확인):

```bash
cd "$REPO" && grep -rn "PATTERN_A_MIN_CHG <= chg24" backend/app/workers/long_bottom_detector_worker.py && grep -rn "TREND_EXTREME_BULL_PCT_3D" backend/app --include=*.py && grep -rn "def is_regime_blocked_for_short" backend/app/services/pump_dump_regime.py && grep -rn "retracement_ratio" backend/app --include=*.py
```

🚨 **되돌림 판정 없이 LONG 필터만 열면 안 된다** — 사상 ⑤ 의 「원점 회귀 종목」과
「추세 중 조정」을 가르는 계산이 필요하다.

✅ **그 계산은 이미 있다.** (이 문서 초안은 「코드에 없다」고 썼지만 **틀렸다** — 재봤더니
2026-08-31 감사 이후 `Fix 236` 으로 들어와 있었다. 이 저장소의 단골 함정 그대로다.)

```
backend/app/services/retracement.py  —  retracement_ratio(closes, lookback=4H)

되돌림 비율 = (고점 − 현재가) / (고점 − 상승 시작가)     ※ 상승 시작가 = 고점 이전 최저 종가
0.00~0.30  고점 부근      아직 조정이 얕다
0.30~0.60  추세 중 조정   ✅ LONG 자리 (사장님 「급등후 큰조정」)
0.60~0.70  깊은 조정      회색지대 (막지 않는다)
0.70 이상  원점 회귀      🚫 RETRACE_BLOCK_MIN — LONG 차단
1.00 이상  원점 아래      상승 시작가보다 낮다 = 최악
```

⚠️ **다만 「있다」와 「모든 LONG 경로에 걸려 있다」는 다르다.** 실제로 부르는 곳은
`surge_pullback.py:143` 과 `auto_bb_breakdown_worker.py:1615-1623` **2곳뿐**이다.
`long_bottom_detector_worker.py` 의 급락 LONG 경로는 이 판정을 **거치지 않는다.**
🔁 그러니 LONG 필터를 열 때는 **그 경로에도 되돌림이 걸리는지 호출 체인을 따라갈 것**(§4-2 1번).

🚨 `retracement_ratio` 는 판정 불가 시 `None` 을 돌려주고 **그건 「안전」이 아니라 「모름」**이다.
호출자가 fail-open/closed 를 스스로 정해야 한다 (파일 docstring 에 명시돼 있다).

---

### 4. 작업 규칙 — 사장님이 Claude 에게 준 지시

#### 4-1. 「묻지 말고 진행」 — 범위와 예외

> "앞으로 이런건 내게 묻지말고 진행해줘"
> "이것도 묻지말고 진행해줘 **머지도** 특별히 내가 결정해야 하는거 빼고는 모두 자동으로"
> "이런것도 묻지말고 자동으로 진행해줘"  (2026-08-30, **세 번 반복**)
> "**내게 묻지말고 모두 개발 완료해줘**"  (2026-08-25)

| 하는 것 | 여전히 묻는 것 (예외) |
|---|---|
| 근거 대고 **결정 → 실행 → 되돌리는 법과 함께 보고** | 🚨 **실제 자금이 나가는 조작** (주문/취소/청산) |
| A/B 선택지 제시 금지 — 「이 근거로 이렇게 했습니다. 다르면 한 줄로 되돌립니다」 | 🚨 **파괴적 작업** (DB 삭제·롤백·force push) |
| **머지도 자동** | 🚨 **사장님 사상 자체가 바뀌는 변경** |
| 코드 변경·조사·분석·UI 개선 | — |
| — | **배포(재시작)는 사장님이 하신다** |

🚨 `gh` CLI 가 없다. GitHub 웹 UI PR 을 기다리지 말고 직접 머지한다.
**`git fetch` 를 먼저 해야 한다** — 안 하면 `origin/main` 이 로컬에 캐시된 옛 커밋이라
「머지할 게 없다」는 거짓 성공이 난다:

```bash
cd "$REPO" && git fetch origin && git merge --no-edit origin/main
```

🚨🚨 **`main` 은 실자금 배포 대상이다. 푸시 전에 이 3가지를 반드시 통과시켜라.**
「머지도 자동」은 **검증 없이 자동**이라는 뜻이 아니다 — §4-2 가 그 반대를 말한다.

```bash
cd "$REPO" && git diff --stat origin/main...HEAD -- backend/ && echo "--- 마이그레이션 ---" && git diff --name-only origin/main...HEAD -- backend/alembic/versions/
```

1. **실행 테스트** — `backend/` 가 한 줄이라도 바뀌었으면 §4-2 의 pytest 를 **먼저 돌린다.**
   초록이 아니면 푸시하지 않는다. (정적 검사만으로는 Fix 318·311·315 를 못 잡았다.)
2. 🚨 **alembic 마이그레이션** — 위 두 번째 목록이 **비어 있지 않으면** 코드만 올려서는 안 된다.
   새 리비전이 섞인 채 사장님이 VPS 를 재시작하면 **스키마가 코드보다 옛것**이라
   워커가 실자금 포지션을 든 채 죽는다. **그 사실을 사장님께 명시해서 보고하고**,
   `alembic upgrade head` 를 **재시작 전에** 돌려야 한다고 함께 적어라.
   (배포·재시작은 사장님이 하신다 — 나는 순서를 알려드릴 뿐이다.)
3. **문서만 바뀐 푸시인지** — `backend/` diff 가 비어 있으면 1·2 는 건너뛰어도 된다.

```bash
cd "$REPO" && git push origin HEAD:main
```

(작업 브랜치가 아니라 `main` 에서 직접 작업 중이면 `git push origin main` 이어도 같다.
푸시가 `rejected` 면 다시 `git fetch origin && git merge --no-edit origin/main` 후 재시도.
🚨 **`--force` / `--force-with-lease` 는 절대 붙이지 마라** — `main` 의 남의 커밋이 사라진다.
force push 는 §4-1 표의 「파괴적 작업 = 사장님께 묻는다」다.)

🚨 **머지 충돌이 났을 때** — 충돌 파일을 손으로 고쳐 `git add` → `git commit` 한다.
**다음 명령들로 「깨끗하게」 만들지 마라. 커밋 안 된 작업이 복구 불가능하게 사라진다:**
`git reset --hard` · `git checkout .` · `git restore .` · `git clean -fd`.
빠져나오려면 `git merge --abort` 하나면 된다(머지 전 상태로 안전 복귀).

🚨🚨 **`git stash` / `git stash pop` 을 맨손으로 쓰지 마라.**
이 저장소는 **worktree 를 여러 개 공유한다** (본 검증에서 5개 확인:
`main` · `infallible-euler-6dc297` · `charming-albattani-3f588f` · `loving-rhodes-52788c` · 임시 baseline).
**stash 는 워크트리별이 아니라 저장소 전체에서 하나의 스택(`refs/stash`)을 공유한다.**
한 워크트리에서 `stash` 하고 다른 워크트리에서 `pop` 하면 **엉뚱한 브랜치에 변경이 쏟아지고**,
충돌하면 그 stash 는 `pop` 도 실패한 채 애매하게 남는다.
치워둘 일이 있으면 stash 말고 **브랜치에 커밋**해라 (`git switch -c wip/설명 && git commit -am wip`).
꼭 stash 를 써야 하면 `git stash list` 로 **남의 stash 가 없는지 먼저 확인**하고,
`pop`(빼면서 삭제) 대신 `git stash apply`(남겨둠) 를 쓴 뒤 확인하고 지운다.

**되돌리는 법** — `main` 에 잘못 올렸으면 **히스토리를 지우지 말고 되돌린다**:
`git revert --no-edit <커밋>` (머지 커밋이면 `git revert -m 1 <머지커밋>`) 후 다시 푸시.

**왜**: 사장님은 1인 개발·운영이고 VPS 명령을 직접 붙여넣는다. 매 결정마다 왕복이
생기면 사장님 시간이 그대로 소모된다. **근거를 대고 판단하는 것이 내 일이다.**

보조 원칙: 위험한 선택은 **막는 쪽(보수적)으로** 먼저 넣고 실측 로그를 붙여
하루 뒤 데이터로 조정한다. **감으로 완화하지 않는다.**

#### 4-2. 🚨 오케스트라 에이전트 **사전** 검증 필수 — 사장님이 20번 지적하신 것

> "기능하나 만들는데 이런 저런 문제가 계속 나오는데 나오지 않게 해줘
> 오케스트라 에이전트는 구성되어 있는 각각의 에이전트팀에 일을 지휘하고 문제가 없게 해줘
> 그많은 에이전트팀을 그냥 두기만 하는건가?
> 개발을 할때 기능을 추가하거나 삭제할때 **모든 에이전트팀와 소통을 통해서만 개발을 시작해**"  (2026-08-22)

> "아니 몇번을 이야기해야하는거야 오케스트라 총관지휘자는 뭐하는거야
> **이것을 내가 20번은 이야기 하는것 같은데**"  (2026-09-03)

2026-09-03 에 Fix 299~318 을 **전부 사전 검증 없이** 만들고 배포한 결과:

| 무엇 | 어떻게 드러났나 |
|---|---|
| Fix 304 | 켠 **직후** 전수 감사가 차단 요인 **5건** 발견 |
| Fix 311 | 검증이 「사장님 사양(1단계→2단계)을 통째로 막는다」고 발견 |
| Fix 313 | 전역 스위치라 **볼밴 분할 설계를 파괴**할 뻔 |
| Fix 318 | **엉뚱한 함수에 붙였다** — 사장님 손절은 `_execute_force_stop_loss` 로 가는데 `_execute_stop_loss` 에 붙여 **아무 효과 없음**. #2046 AKEUSDT 전량 청산 |
| Fix 321 | 내가 Fix 315 로 **손절을 다시 잠갔다** (피해 0 — 검증이 잡음) |

**코드를 고치기 전에 반드시 이 순서:**

1. **호출 체인을 끝까지 확인** — 내가 고치려는 함수가 **실제로 불리는 그 함수**인가?
   (같은 이름의 비슷한 함수가 둘 이상 있는지 반드시 grep)
2. **Agent / Workflow 로 검증** — 사장님이 정하신 5종:
   - 참조 필드 존재 확인 (모델에 그 필드가 실제로 있는가)
   - 함수/import 존재 + 시그니처 (인자 개수·이름, 반환 튜플 길이)
   - SQL 문법 + 테이블·컬럼명 (`strategies`(X) vs `strategy_instances`(O))
   - 다른 파일과 호환성 (시그니처·반환값 변경이 깨는 곳)
   - fail-open / fail-closed 방향이 옳은가 (주석이 선언한 방향과 코드가 같은가)
3. 검증 통과 → commit → 배포
4. 지적 → 수정 → **재검증**

**큰 fix(필수)**: 3+ 파일 / DB 스키마 참조 / 신 외부 함수 호출 / **공용 함수 시그니처 변경**
**작은 fix(skip 가능)**: typo, 주석
**예외(즉시 처리 OK)**: 실 자금 위험 fix, 사장님 직접 지시 fix — 그래도 **최소한 호출 체인 확인 + 정적 검사**는 한다.

🌟 **정적 검사(소스에 이 문자열이 있나)는 「그 함수가 실제로 불린다」를 증명하지 못한다.**
2026-09-03 의 세 사고(Fix 318 엉뚱한 함수 / 311 사양 차단 / 315 마커 미저장)가
**전부 정적 검사를 통과**했다. 그래서 **실행 테스트**를 신설했다:

```bash
cd "$REPO/backend" && python -m pytest tests/test_stop_loss_execution_path.py tests/test_stage_flow_execution.py -q
```

기대 출력 (본 검증에서 실제 실행): `28 passed in 1.05s`.
🚨 **선행 조건**: `pytest` 와 backend 의존성이 깔려 있어야 한다. 새 PC 라면
**핸드오프의 `local-env.md` 를 먼저 끝내라.** `ModuleNotFoundError` 가 나면
테스트가 실패한 게 아니라 **환경이 아직 없는 것**이다 — 둘을 혼동하지 말 것.

증명: Fix 319 를 일시 제거하니 **4건 즉시 실패**(정적 13건은 하나도 못 잡았다).
🌟 **자금이 움직이는 경로는 실행 테스트로만 검증한다.**

✅ **이 pytest 는 네트워크도 실 DB 도 건드리지 않는다** — 본 검증에서 확인했다:
`backend/tests/conftest.py` 가 `sqlite+pysqlite:///:memory:` 를 쓰고, `.env` 없이도 통과한다
(worktree 의 `backend/` 에는 `.env` 자체가 없고 `.env.example` 만 있다).
**그래서 새 PC 에서 마음 놓고 돌려도 되는 유일한 검증**이다.

##### 🚨🚨 새 PC 에서 「앱·워커를 로컬로 띄워 보는 것」은 위 pytest 와 전혀 다르다

새 PC 에 `.env` 를 채우고 `docker compose up` 이나 워커 스크립트를 돌리면
**메인넷 실계좌에 진짜로 붙는다.** 두 가지가 동시에 터진다:

| 위험 | 무슨 일이 나나 |
|---|---|
| 🚨 **중복 주문 — 이게 제일 크다** | VPS 가 지금 이 순간 활성 전략 24건을 돌리고 있다(§7). 같은 API 키로 로컬 워커를 띄우면 **같은 포지션에 두 인스턴스가 각자 주문을 낸다.** 진입이 2배로 나가고, 한쪽이 청산한 걸 다른 쪽이 다시 열고, 손절이 서로를 덮어쓴다. **실제 돈이 즉시 나간다.** |
| 🚨 **IP ban (418, `-1003`)** | 2026-08-26 에 실제로 당했다. Binance 는 **ban 기간 중의 요청도 카운트해 ban 을 연장**해서 `06:08 → 06:28 → 06:30 → 06:34 → 06:45` 로 스스로 밀렸다. ban 은 **IP 단위**라 집 IP 로도 똑같이 걸린다. 걸리면 **단계 진입·증거금 추가·수동 진입까지 전부 실패**한다. |

⇒ **규칙**: 새 PC 에서 확인 목적으로 돌리는 것은 **위 pytest 와 읽기 전용 SSH 조회(§7)뿐**이다.
로컬에서 앱·워커·백테스트를 메인넷 키로 띄우려면 **사장님 승인을 먼저 받아라.**
꼭 필요하면 ① **VPS 를 먼저 멈추고**(사장님만 하신다) ② 테스트넷 키나 **읽기 전용 키**로
③ 심볼 수를 줄여서 돌린다. 「잠깐만 확인」이 ban 을 만든다.

자세한 ban 복구 절차(요청을 0으로 만들고 기다리는 것이 유일한 해법)는
`memory/project_2026-08-26_ip_ban_spiral.md` 에 있다.

#### 4-3. 완료 전 실 검증 필수 — 헌법 69 / 70 / 71

> "내가 개발을 요청 모든 내용은 메모리해서 기억해줘"
> "이런 일이 없게 내가 지시한 모든것은 메모리하는거 아닌가?"  (2026-08-23)

| 헌법 | 내용 |
|---|---|
| **69** | 사장님 요구 = **즉시 메모리 저장**. TaskCreate 마킹 ≠ 완료 |
| **70** | **완료 = 실 검증 3단계 후만.** 코드 커밋 ≠ 구현 완료, 배포 커밋 ≠ 배포 완료 |
| **71** | 사장님 verbatim("네, 잘 작동합니다") 또는 스크린샷 전까지는 **"pending"** |

실 검증 3단계 (매 Fix 커밋에 이 3줄 필수):

```
[ ] VPS 로그 확인: docker compose logs [service] | grep [keyword]
[ ] API/DB 확인 : curl [endpoint] or SELECT ...
[ ] UI 확인     : 사장님 스크린샷 or verbatim "잘 됩니다"
```

🚨 **`docker compose exec ... grep` 은 디스크를 읽는다** — 돌고 있는 파이썬 프로세스의
코드가 아니다. **배포 여부는 프로세스 시작 시각 vs 파일 수정 시각으로만 판정한다.**

#### 4-4. 사장님 요구 이외 기능 추가 금지 (헌법 62)

> "아니 왜 계속 다음세션이 있는거지"
> "그래 내가 요청한것까지만 하고 나머진 진행하면서 추가하는걸로 해줘"  (2026-08-21)

사고 이력: 사장님 명시 요구는 v207 까지였는데 「다음세션으로 진행」을 무한 확장으로
오해해 **v208~v216(9 버전)을 자체 판단으로 추가** → 미배포 90 commits + 검증 없음 → **롤백**.

예외(자체 판단 OK): CRITICAL fix(사장님 자본 보호) / 명시 요구 완성에 필수적인 sub-task /
silent bug 감지 + 즉시 fix.

#### 4-5. 🚨 말하기 전에 **재라**

> "짜증나 몇번을 하는거야"  (2026-08-28)
> "몇번을 하는거야"  (2026-08-30, 하루에 오진 3건)

| 내 주장 | 실측 | 갈린 방법 |
|---|---|---|
| 「−5% 강제손절이 볼밴을 자른다」 | 볼밴은 전부 `force_sl_roi_override=10.00` | `event_payload.threshold` 1줄 |
| 「Fix 203 이 프로세스에 안 올라갔다」 | 코드 12:58 / 스케줄러 시작 14:10 = **살아 있음** | `docker inspect StartedAt` vs `ls -l` |
| 「템플릿이 OBV_REVERSE 라 가격 경로를 안 탄다」 | 17건 전부 `PRICE_DOWN_PCT` | 템플릿 1컬럼 |

**Why**: 실자금이 걸린 시스템에서 틀린 진단은 시간만 쓰는 게 아니다 — 사장님이 그걸
믿고 설정을 바꾸거나 포지션을 정리하면 **돈이 나간다.**

적용:
- **가설이 떠오르면 먼저 「이걸 가르는 한 줄은 뭔가」를 쓴다.** 그 한 줄이 없으면 가설을 말하지 않는다.
- **여러 후보를 한 번에 재는 명령 하나**를 만든다. 하나씩 말하고 하나씩 틀리는 게 제일 나쁘다.
- **「확정」과 「후보」를 분리해서** 쓴다.
- 틀렸으면 **한 문장으로 정정하고 바로 다음 측정으로 간다.** 길게 사과하지 않는다.

#### 4-6. 🚨 진입 근거 기록은 **필수**

> "분명이 이것을 학습하고 메모리에 저장하라고 했는데 정말 믿을수 없네 왜 이러는거지
> 오케스트라 지휘자는 뭘한거야 확실하게 꼭 이것을 학습하고 포지션 진입시 기록 메모리해서
> 차후에 분석하고 활용할수 있게 꼭만들어서 활용해"  (2026-08-29)

- **진입 판정에 쓰인 원시값은 전부 남긴다** — 통과/탈락 bool 이 아니라 **비교한 숫자 그대로**.
- **경로가 여러 개면 경로마다 같은 스키마로** 남긴다.
- **기록 누락을 스스로 감지**하게 한다 (필드 누락률을 로그로).
- 🚨 **임계값을 바꾸기 전에 반드시** ① 그 상수가 실제로 쓰이는지 **grep** ② **승/패 분포 비교**.
  둘 중 하나라도 못 하면 「데이터가 없어서 못 한다」고 말할 것. **감으로 올리지 말 것.**

**죽은 상수** (값을 바꿔도 아무 일 안 일어난다 — 확인된 것):

| 상수 | 상태 |
|---|---|
| `RSI_OVERSOLD_MAX` / `RSI_MIN_TURNUP` / `CCI_OVERSOLD_MAX` / `CCI_MIN_TURNUP` | 정의만 있고 사용 0곳 |
| `OBV_EXTREME_RATIO=0.6` | 비교하는 `if` 없음. 🚨 **주석은 「게이트 유지」라고 거짓 서술** |
| `OBV_MIN_SLOPE_PCT` | 소비 함수가 호출 0곳 |
| `OBV_DECLINE_MIN_PCT` | 참조 0곳 |
| `auto_obv_min_confidence` (0.95) | **한 번도 비교되지 않는다** — 후보에 라벨로만 찍힘 |

---

### 5. 🚨 반증된 가설 목록 — **이 프로젝트에서 가장 값진 자산**

「재봤더니 반대였다」는 이 저장소에서 **반복해서** 일어났다.
아래 항목을 **다시 제안하기 전에 반드시 이 표를 읽어라.**

#### 5-1. 사장님 가설이 반증된 것 (측정 보고 사장님이 철회하셨다)

| # | 가설 | 실측 결과 | 근거 |
|---|---|---|---|
| 1 | **「99% 청산하고 1% 남겨두면 재진입 감시가 이어진다」** | 🚫 **정반대.** `realtime_reentry_worker` 는 후보를 `TERMINAL_STATUSES`(청산 완료)에서만 고르고 그다음 `if symbol in active_syms: continue` 로 산 것을 건너뛴다 → 1% 를 남기면 **두 관문에 다 걸려 영구 제외**. 게다가 MIN_NOTIONAL 5.00 이라 1차 10×레버2 의 1% = **0.20 USDT = dust orphan**(계정 차단 전력) | `memory/project_2026-09-03_reentry_visibility_and_tp.md:10-30` |
| 2 | **「반대매매(역방향 진입)」** | 🚫 즉시 **−86 ~ −237**. 「주춤 5봉」은 표본 절반이 정반대 = 과적합 | `memory/project_2026-09-01_reentry_dead_and_peak_stall.md` |
| 3 | 「LONG 손절은 −5% 가 15m 알트 노이즈에 잘리니 −10% 로」 (Fix 87) | 🚫 이익 중 LONG 13건의 **최저 ROI 가 −0.1 ~ −4.3%** — **−5% 를 건드린 승자가 한 건도 없다.** 느슨한 손절은 승률을 못 올리고 **잃는 크기만 2배**로 키웠다. LONG 이틀 연속 승자 0명 → Fix 253 으로 5% 복귀 | `memory/project_2026-08-31_trade_data_learning.md:185-205` |

🚨 **1번은 절반만 반증이다.** 사장님이 원하신 건 두 가지였고 감시자가 서로 다르다:
- **다른 전략으로의 재진입**(`realtime_reentry_worker`) → 잔량이 있으면 **막힌다** = 반증
- **같은 전략 안의 단계 진행**(`stage_trigger_worker`) → 잔량이 **살아 있어야 돈다** = §2-⑧ 이 유효
🔁 **감시자가 여러 개면 어느 감시자 얘기인지 먼저 구분할 것.**

#### 5-2. 지표·신호 가설이 반증된 것 (Fix 327, 30심볼 × 15m/1h/4h × 300봉 + 실거래 1,419건)

| # | 가설 | 실측 결과 | 근거 |
|---|---|---|---|
| 4 | **「아래꼬리가 길면 반등 신호」** | 🚫 효과크기 **d = −0.45 (부호 반대)** | 커밋 `ded22f3` |
| 5 | 「RSI 상향 전환이면 반등」 | 🚫 d = **−0.303** (지정가 가정하면 +0.080 = 아티팩트) | 〃 |
| 6 | 「거래량 급증이 반등 신호」 | 🚫 두 그룹에서 **부호가 뒤집힘** | 〃 |
| 7 | 「15m MACD hist 3봉 상승중 = 좋다」 | 🚫 d = −0.380 → **역방향으로 채택** | 〃 |
| 8 | **「볼밴 하단이 지지선」 / 「fib 0.5·0.618 이 지지선」** | 🚫 OOS **−0.125 / −0.72 / −0.66**, 그룹을 바꾸면 정반대 → **기각**. 채택된 것은 `swing_low`(좌우 3봉 피벗, 96봉) 뿐 | 〃 |
| 9 | **「손절당한 자리가 재진입에 더 좋다」** | 🚫 직전 접촉 손절 n=55 **49.1%** vs 직전 반등 n=72 57.4% vs 기준선 55.0%. ⚠️ 순진하게 재면 36.8%/69.7% 라는 극적인 값이 나오는데 **234건 중 102건(43.6%)이 미래참조**. 그 숫자로 코딩하면 안 된다 | 〃 |

🌟 **4~7 을 합치면 하나의 결론이다: 「반등을 보고 들어가면 진다. 지지선에 미리 걸어놔야 이긴다.」**
사장님 사상 ⑤ 의 **「미리미리 분할, 바닥 확인 X」**와 정확히 일치한다.

채택된 판정식 (7점 등가중, 기준선 55.0% / n=264):

```
score >= 6  LONG   승률 70.6%      1H : MACDh>0 / close>EMA20 / RSI12>=50
score <= 1  SHORT  승률 63.9%      15m: NOT(MACDh 3봉 상승) / RSI24>=45
2~5         관망                        / 96봉 낙폭>=-15% / close>EMA50
```

#### 5-3. Claude(내) 가설이 반증된 것

| # | 내 주장 | 실측 결과 | 근거 |
|---|---|---|---|
| 10 | 「트레일링 되돌림 3%p 는 좁다, 넓히자」 | 🚫 **현행이 최고** — 3%p +123.64 / 8%p +110.36 / peak30% +108.38. 넓히면 −10% 강제손절에 걸리는 건수가 늘어 손해 | `project_2026-09-01:98` |
| 11 | 「TP1 을 3% 로 낮추면 추가(피라미딩) 전에 익절돼 버린다」 | 🚫 **TP1 은 물량의 25%만 닫는다.** 나머지 75%가 그대로 ROI 5% 까지 간다(추가 63회 발생) | `project_2026-09-03:69` |
| 12 | 「봉수를 4 → 2 로 완화하면 정점을 더 잡는다」 | 🚫 **4번 재서 4번 반증.** 상한 10 이면 **4봉 +196 > 2봉 +152** (무제한에서만 2봉 우세) | `project_2026-09-02:124` |
| 13 | 「6h/24h 급등률 조건을 더하면 좋아진다」 | 🚫 건당 +1.681 → **−0.854**. 하락폭이 커도 **변동성 때문에 손절에 먼저 걸린다** | 〃 |
| 14 | 「SHORT 에 24h 급등 조건을 더하자」 | 🚫 +276 → **−44**. 사장님 「무조건」이 실측으로도 맞았다 | `project_2026-09-02` |
| 15 | 「방향을 15m MACD 로 판정하자」 | 🚫 지지 +214 → **−294**. **자리는 15분, 방향은 4H**(사상 ⑤) | 〃 |
| 16 | 「간격 1.5% 가 최적 / 화면 기본 트리거 10%·20% 가 사다리를 막는다」 | 🚫 **전제가 틀렸다.** 내 시뮬은 "손절되면 사이클 끝"으로 모델링했는데 사장님 설계는 잔량이 살아 있어 **간격이 손절폭보다 커도 된다** → 지적 철회 | Fix 324 (`61e19a8`) |
| 17 | 「손절을 건너뛰면 손실이 무한정 커진다」 (Fix 318 의 근거) | 🚫 **틀렸다.** 잔량 증거금이 10 USDT 면 **최대 손실도 10 USDT** | Fix 326 (`1d04598`) |
| 18 | 「−5% 강제손절이 볼밴을 자른다」 | 🚫 볼밴은 전부 `force_sl_roi_override=10.00`, −10% 에서 잘렸다 | `feedback_measure_before_hypothesis.md` |
| 19 | 「Fix 203 이 프로세스에 안 올라갔다」 | 🚫 코드 12:58 / 스케줄러 시작 14:10 = **살아 있었다** | 〃 |
| 20 | 「평단이 심볼 단위로 오염됐다」 | 🚫 **청산 판정은 전부 정확했다** (`#1711` 주문기준 0.5254598699 vs 판정 0.52545991) | `project_2026-08-30_bbsplit_stage3_zero_root_cause.md:84` |
| 21 | 「fail-OFF 는 그림자 키 때문이다」 | 🚫 그 행은 **존재한 적이 없고**, 내 Fix 188 이 오히려 그걸 **만들어내고** 있었다 | `project_2026-08-28_failoff_settings_screen.md:15` |
| 22 | 「kill-switch = 우회 경로 없는 확실한 정지」(사장님께 그렇게 보고했다) | 🚫 **틀렸다** — 3대 공백(증거금 계속 주입 / dust orphan 계정 차단 / 해제 시 알람 일괄 발사) | `project_2026-08-26_killswitch_gaps.md:30` |
| 23 | 「LONG 승률 15.2%」 | 🚫 **데이터 결손 함정.** `COMPLETED` 가 `stopped_at` 미기록 → **성공 234건 +23,302 집계 누락** | `project_2026-08-28_bbsplit_dead_stage_pyramiding.md` |

#### 5-4. 에이전트·감사 결론이 반증된 것

| # | 감사 결론 | 실측 결과 | 근거 |
|---|---|---|---|
| 24 | **「OBV 게이트 산식이 임계값과 다른 자로 잰다 → 고쳐야」** (85 에이전트) | 코드 분석은 **정확했다. 그런데 고치면 나빠진다** — 통과 승률 36.4% → **34.7%**, 차단이 4%→21% 로 5배 늘고 **그 늘어난 차단이 전부 손해**(차단된 것의 승률 66.7% > 전체 37.5%) → **고치지 않는다** | `project_2026-09-03:519` |
| 25 | 「백테스트는 +5% 전량 청산인데 실제는 25%만 → 사다리 기대값이 뒤집힌다」 (3명 중 0명 반증) | **사실관계는 맞지만 결론이 틀렸다.** 같은 표본에 실제 익절 모형을 넣어 재니 사다리가 **더 좋았다** (중단 저항 +0.821 → **+1.132**) | `project_2026-09-02:102` |
| 26 | 「캐시버스터 문제는 배포 차단급이다」 | 🚫 **실행으로 반증** | `project_2026-08-28_bbsplit_dead_stage_pyramiding.md:99` |

#### 5-5. 🌟 반증에서 뽑은 메타 원칙

| 원칙 | 몇 번 나왔나 |
|---|---|
| 🚨 **효과크기 ≠ 손익.** 구간표가 아무리 매력적이어도 조건으로 쓰면 변동성이 손절을 먼저 친다 | **3번** (24h 급등률 / 6h 급등률 / MACD hist) |
| 🚨 **생산자가 쓰는 문자열과 소비자가 찾는 문자열을 직접 대조하라.** 「워커 정상 + 로그가 정직하게 0」 ≠ 「대상이 없다」 | **3번** (Fix 308 이벤트명 / Fix 208 학습 스키마 / Fix 197 `STAGE_1_OPEN` 오타) |
| 🚨 **슬롯이 병목이면 「총 수익」이 아니라 「슬롯당 수익」으로 판단.** 잘 도는 규칙은 기회의 87%를 의도적으로 버린다 | Fix 293 |
| 🚨 **읽는 코드를 만들면 쓰는 코드도 같이 만들었는지 grep 하라.** 「정의 + 읽기」만 있고 **대입이 0곳**이면 그 기능은 존재하지 않는 것과 같다 | Fix 321 |
| 🚨 **`0` 하나로 「불필요」와 「불가능」을 같이 표현하지 마라.** 단위 테스트는 각자 옳아서 상호작용을 못 잡는다 | Fix 316 |
| 🚨 **fail-CLOSED 는 「영구 정지」를 만들 수 있다.** 막는 조건이 매번 참이면 그 심볼은 영원히 멈춘다 | Fix 305 |
| 🚨 **전역 설정 하나로 여러 전략을 켜는 함수는 `strategy` 를 인자로 받아라.** 「내 전략에 좋은 것」이 「다른 전략의 설계 파괴」가 된다 | Fix 313 |
| 🚨 **손절이 「설정돼 있다」와 「발동한다」는 다르다.** 상위 게이트가 조건부로 막고 있을 수 있다 — **게이트 체인까지 따라갈 것** | Fix 317 (1,221건 중 **371건(30%)** 이 손절이 안 열린 채 돌았다) |
| 🚨 **결손값의 fallback 이 판정을 뒤집지 않는지 확인하라.** 로그는 정상으로 보였다 | Fix 296 |
| 🚨 **평단을 리셋하는 설계를 넣으면 「평단 기준 지표」가 전부 리셋된다.** ROI·손절·화면이 전부 평단에 걸려 있다 | Fix 306 |
| 🚨 **일일 집계는 청산일이 아니라 진입일로 갈라라** | 2026-09-02 |
| 🚨 **너무 좋은 결과는 미래참조를 의심하라** | 헌법 144, Fix 327(43.6% 미래참조) |
| 🌟 **사장님이 숫자를 주시면 그대로 재현해 볼 것** — 말로 오간 3번의 왕복보다 수치 하나가 정확했다 | Fix 324 |

---

### 6. 새 세션이 읽어야 할 문서 — **순서대로 상위 7개**

| 순서 | 파일 | 왜 이 순서인가 | 분량 |
|---|---|---|---|
| 1 | `<메모리>/MEMORY.md` | **전체 인덱스.** 항목 **68개**(`grep -c "^- \["`)에 세션 82개가 압축돼 있다. 전부 읽어라 — 여기만 읽어도 사고 이력의 80%를 안다 | 28K |
| 2 | `docs/handoff/2026-09-03/` (이 핸드오프 전체) | 새 PC 이전 절차 + 본 문서 | — |
| 3 | `<메모리>/project_2026-08-30_sajangnim_strategy_doctrine_v3.md` | **사장님 매매 사상 원본 verbatim.** 요약본을 먼저 읽으면 왜곡된다 | 10K |
| 4 | `<메모리>/project_2026-09-03_reentry_visibility_and_tp.md` | **최신 세션(Fix 299~324).** 지금 도는 코드의 근거가 전부 여기 있다. 🚨 **Fix 325·326·327 은 이 파일에 없다** — 메모리에서 가장 큰 Fix 번호는 324 다(`grep -o "Fix 3[0-9][0-9]" \| sort -u` 로 확인). 그 3건은 커밋 메시지(`git log --oneline -5`)와 §2-⑩ / §5-2 / `docs/spec/CHART_REGIME_ANALYSIS_2026-09-03.md` 로만 알 수 있다 | 37K |
| 5 | `docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md` | **사상 vs 코드 정반대 8건** — 「전략이 사상대로 안 움직인다」의 실체. ⚠️ `f7ecec5` 기준이라 HEAD 재확인 필요 | 426줄 |
| 6 | `$REPO/DEVELOPMENT_PRINCIPLES_2026-06-07.md` | **헌법 원본.** 5대 원칙 + 5 사고 패턴 + 우선순위(자본 보호 > 사상 > 안정성 > 품질 > 속도). 🚨 `docs/` 가 아니라 **저장소 루트**에 있다 — `docs/SYSTEM_DEVELOPMENT_PRINCIPLES_2026-06-11.md` 는 **다른 파일**이니 헷갈리지 말 것 | 361줄 |
| 7 | `<메모리>/feedback_*.md` **9개 전부** | 작업 규칙. 파일당 2~4K 로 짧지만 **이걸 안 읽으면 §4 를 전부 어기게 된다** | 22K |

`<메모리>` = `$HOME/.claude/projects/<SLUG>/memory` (§1-2 에서 복원한 그 자리).
`docs/spec/*` 와 `DEVELOPMENT_PRINCIPLES_*` 는 **저장소 안**(`$REPO/...`)이라 clone 만으로 온다.

먼저 셸 변수를 잡아 둔다 (`<SLUG>` 는 §1-2 ②에서 확인한 값):

```bash
MEM="$HOME/.claude/projects/<SLUG>/memory" && ls "$MEM" | wc -l
```

→ `83` 이 나와야 한다. 아니면 §1-2 로 돌아간다.

한 번에 읽는 명령:

```bash
cat "$MEM/MEMORY.md"
```

```bash
cd "$MEM" && for f in feedback_*.md; do echo "=== $f ==="; cat "$f"; done
```

(위 for 문은 **9개 파일**을 출력한다 — 본 검증에서 실제 개수 9 확인:
`decide_and_proceed` / `entry_recording_mandatory` / `measure_before_hypothesis` /
`no_ask_full_auto_dev` / `no_unrequested_features` / `orchestra_agent_validation` /
`pr_workflow` / `verify_before_complete` / `workflow`.)

🚨 **§1-2 를 아직 안 했으면 위 두 명령은 전부 실패한다.** 메모리는 clone 으로 오지 않는다.
급하면 저장소 안의 백업을 그대로 읽어도 내용은 동일하다(`diff -rq` 차이 0건 확인):
`$REPO/docs/handoff/memory-backup-2026-09-03/`.
단, **그건 사람이 읽는 용도일 뿐 Claude Code 가 자동으로 읽지는 않는다.**

**그 다음 순위** (필요할 때만): `docs/spec/SAJANGNIM_3STEP_LADDER_2026-09-02.md`(자본 사다리 검산) ·
`docs/SAJANGNIM_SASANG_REGISTRY.md`(사상 27건 → 구현 파일 매핑) ·
`docs/spec/CHART_REGIME_ANALYSIS_2026-09-03.md`(Fix 327 근거) · `SYSTEM-SPEC.md`(40K, 마스터).

---

### 7. 사상이 지금 실제로 어떻게 돌고 있나 (VPS 실측, 2026-09-03 조회)

읽기 전용 조회만 했다. 명령:

🚨 **선행 조건 2가지 — 새 PC 에서는 먼저 해결해야 이 명령이 돈다.**
1. **VPS SSH 키가 새 PC 에 있어야 한다.** 개인키는 저장소에 없다 — 핸드오프의
   `vps-ops.md` / `secrets.md` 절차를 먼저 끝내라. 키가 없으면 `Permission denied (publickey)` 가 난다.
2. 🚨 **DB 는 로컬 `db` 컨테이너가 아니라 외부 Neon 이다.** `docker compose exec db psql` 로
   조회하면 **빈 DB** 가 나와 「테이블이 없다」는 오진에 이른다. 반드시 아래처럼
   **`api` 컨테이너의 앱 세션**(`PYTHONPATH=/app`)으로 접근할 것. `PYTHONPATH=/app` 을 빼면
   `ModuleNotFoundError` 가 난다. 쿼리가 실패하면 `db.rollback()` 을 해야 다음 쿼리가 돈다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
q = text(\"select key, value from system_settings where key like :a or key like :b or key like :c order by key\")
for r in db.execute(q, {\"a\":\"stage_trim%\",\"b\":\"sajangnim_ladder%\",\"c\":\"entry_%\"}).fetchall(): print(r[0], \"=\", r[1])
"'
```

출력:

```
entry_chg24_gate_enabled = 1
entry_window_short_enabled = true
sajangnim_ladder_stages_enabled = 1
stage_trim_before_next_enabled = 1
```

| 확인한 것 | 값 | 뜻 |
|---|---|---|
| `stage_trim_before_next_enabled` | **1 (켜짐)** | 「10 USDT 남기고 부분 손절」이 **실제로 돌고 있다** |
| `sajangnim_ladder_stages_enabled` | **1 (켜짐)** | 사장님 사다리 단계 방식 활성 |
| `entry_chg24_gate_enabled` | **1 (켜짐)** | 급등 50 / 급락 50 진입 게이트 활성 |
| `support_score_gate_enabled` | **행 없음** | Fix 327 지지선 7점 게이트는 **기본 OFF** |
| 활성 전략 수 / `capital_management_mode` | **24건, 전부 `fixed`** | 🚨 `stage_ladder` 마커가 붙은 전략은 **0건** — Fix 322 의 「기본 방식」 상황 그대로 |

활성 전략 수를 새 PC 에서 직접 다시 재는 명령 (읽기 전용. 본 검증에서 실행 → `('fixed', 24)`):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select capital_management_mode, count(*) from strategy_instances where status not in (\x27COMPLETED\x27,\x27STOPPED\x27,\x27CANCELLED\x27) group by 1\")).fetchall(): print(r)
"'
```

참고: 전체 `status` 분포는 `STOPPED 1173 / COMPLETED 290 / REENTRY_READY 16 / STAGE1_OPEN 8`
(= 활성 24 = `REENTRY_READY` 16 + `STAGE1_OPEN` 8). 테이블 이름은 `strategies`(X)가 아니라
**`strategy_instances`(O)** 다 — §4-2 검증 항목에 적힌 그 함정이다.

🚨 **이 스위치 8개를 켜고 끌 UI·API 가 아직 0곳이다.** 본 검증에서 키 8개를 하나씩
`grep -rl` 로 다시 재서 **전부 0** 을 확인했다:

```bash
cd "$REPO" && for k in stage_trim_before_next_enabled sajangnim_ladder_stages_enabled entry_chg24_gate_enabled support_score_gate_enabled entry_rank_top_n entry_chg24_gate_mode entry_window_short_enabled stage_trim_keep_notional; do echo "$k -> $(grep -rl "$k" backend/app/api backend/app/static 2>/dev/null | wc -l)"; done
```

현재는 **DB 직접 INSERT 로 켜 둔 상태**다. 새 PC 에서 화면만 보면 **꺼져 있는 줄 안다.**

🚨🚨 **그렇다고 새 PC 에서 이 표를 보고 `INSERT`/`UPDATE` 를 따라 치지 마라.**
- 이 섹션의 SSH 명령은 **전부 `select` 뿐이다. 읽기 전용을 유지하라.**
  `insert` · `update` · `delete` 로 바꿔 실행하는 순간 **활성 전략 24건의 매매 동작이
  즉시 바뀐다.** 스위치 하나가 「진입 게이트」와 「부분 손절」을 좌우한다 —
  끄면 손절이 안 열리고, 켜면 없던 진입이 나간다. **재시작 없이도 다음 사이클에 반영된다.**
- **설정 변경은 사장님 결정 사항이다**(§4-1: 실자금 조작 = 묻는다). 값이 잘못됐다고
  판단되면 **근거를 보고하고 사장님이 바꾸시게 하라.**
- 부득이 바꿔야 한다면 **바꾸기 전 현재 값을 먼저 `select` 로 찍어 남겨라.** 그게 유일한
  되돌리기 수단이다 — 이 테이블에는 이력이 없다(위 「언제·누가 넣었는지 확인 못 함」이 그 증거다).
- 🚨 `docker compose restart` · `down` · `up -d` 같은 **서비스 조작도 금지**다.
  포지션을 든 채 워커가 죽으면 손절이 돌지 않는다. **배포·재시작은 사장님이 하신다.**

⚠️ **확인 못 함**: 이 값들이 언제·누가 넣었는지, `stage_trim_keep_notional` 등 나머지
설정 키의 현재 값. (조회 범위를 사상 관련 4개 접두사로 좁혔다.)

---

### 8. ⚠️ 확인하지 못한 것 / 사장님 결정 대기

| 항목 | 상태 |
|---|---|
| 헌법 19~172 번의 **정본 목록** | ⚠️ **어디에도 없다.** 메모리 파일에 산재 |
| §3 표의 「⚠️ 확인 못 함」 | **6건 → 4건으로 줄었다** (본 검증에서 ②·③·⑤되돌림·⑦ 를 HEAD·운영DB 에서 재확인). 남은 4건 = ③볼밴 하단 이탈 SHORT / ④OBV>4H>15m 강제력 / ⑥4H vs 15m 하드게이트 / ⑥4H 조정 LONG 미리분할 |
| 🚨 **이 핸드오프 폴더가 아직 untracked** | `docs/handoff/2026-09-03/` 8개 파일이 커밋 안 됨. 새 PC 에서 못 본다 → §1-1 마지막 명령을 **떠나기 전에** 실행할 것 |
| §2-⑧ 「10 usdt = 증거금」 재현 | Fix 324 의 소수점 재현 계산을 본 검증에서 **다시 돌려보지는 못했다** (사장님 원 수치가 문서에 없음) |
| 🚨 **Fix 325·326·327 이 메모리에 없다** | 메모리 최대 Fix 번호는 **324**. 헌법 69(「요구는 즉시 메모리 저장」)대로면 **메모리에 남겨야 한다** — 새 세션이 §4-3 을 따라 첫 작업으로 하기 좋다 |
| v219 템플릿에 2·3단계 자본·트리거를 넣을 것인가 | 🚨 **사장님 결정 대기** — 넣으면 전략당 자본이 10 → 910 (**91배**). ⚠️ 아래 경고 반드시 읽을 것 |
| 배치 파이프라인 `ANTHROPIC_API_KEY` | 🚨 **사장님이 넣으셔야 함.** 어디서 얻나 = console.anthropic.com 에서 **새로 발급**(기존 키를 찾아 옮기는 게 아니다). 쓰는 곳은 `tools/batch/run.py:67` — 저장소 코드가 아니라 **로컬 배치 도구**라 VPS·매매와 무관하다. `ANTHROPIC_AUTH_TOKEN` 또는 `ant auth login` 도 가능. 🚨 **값을 이 문서·채팅·커밋에 넣지 말 것** |
| 스위치 8종의 UI·API | 미구현 — DB 직접 조작 중 |
| `docs/handoff/` 의 `wip-backup-2026-09-03/` 3개 브랜치 백업 | 내용 미확인 (내 담당 밖) |

#### 8-1. 🚨🚨 「전략당 10 → 910」을 켜기 전에 — 이 한 줄이 제일 위험하다

위 표의 한 칸이지만 **이 문서에서 실자금 피해가 가장 큰 항목**이다.

- 지금 활성 전략이 **24건**이다(§7 실측). 전략당 910 이면 **총 노출이 약 21,840 USDT** 가 된다.
  현재(전략당 10)는 약 240 USDT 다. **약 91배.**
- 사장님 사상 ⑥ 이 정확히 이걸 경고한다 — **손절은 ROI(%) 기준이라 자본이 커지면
  같은 %에서도 손실 금액이 그만큼 커진다.** §2-⑥ 실측표가 이미 그 모양이다
  (추가 없음 −13.28/건 → 추가 2회 −64.27/건 → 추가 7회 −724.80).
- 그러므로 **「사장님이 결정하시면 켠다」로 끝내지 마라.** 켜기 전에 최소한:
  1. **계좌 잔고로 21,840 노출이 감당되는지 먼저 계산해 보고**드린다(레버리지 배수까지 곱해서).
  2. **일일 손실 한도를 먼저 설정**한다 — §3 표에서 **「기본 미설정」**으로 남아 있는 항목이다.
     한도 없이 91배를 켜면 사장님이 겪으신 그 실패(사상 ⑥)를 **자동화**하는 것이 된다.
  3. **전체가 아니라 소수 전략에 먼저** 적용해 하루 실측을 본다. 전역 스위치로 한 번에
     켜지 마라 — Fix 313 이 정확히 그 실수였다(전역 스위치가 볼밴 분할 설계를 파괴할 뻔).
  4. **되돌리는 법을 먼저 적어두고** 켠다: 켜기 전 템플릿·설정 값을 `select` 로 떠서 보관.

⚠️ 위 21,840 은 **활성 24건 × 910 의 단순 산수**다. 실제로 어느 전략에 어떻게 적용되는지,
레버리지가 몇인지는 **확인 못 함** — 켜기 전에 반드시 실측할 것.


---

<a id="sec-2"></a>

## 2. Claude Code 로컬 상태 — 저장소 밖 자산

> 조사 시각: 2026-09-03 / 조사 대상 PC: `desktop-rhugutf` (Windows 11, Claude Code v2.1.258)
> 근거: 아래 모든 주장은 실제 명령 출력 또는 `파일:줄번호`로 뒷받침한다.

### 0. 한 줄 요약

**원래 `git clone` 만으로는 이 프로젝트의 「기억」이 하나도 따라오지 않는다**
(2026-09-03 에 사본을 저장소에 넣어 일부는 따라오게 됐다 — 아래 ※, 그 대가는 §5).
저장소 밖에 원래 있던 것이 네 덩어리다:

| 덩어리 | 위치 | 크기 | clone 으로 따라오나 |
|---|---|---|---|
| 프로젝트 메모리 83개 | `~/.claude/projects/C--Users-user------binance-auto-trader/memory/` | 764K | ❌ (원본은 안 따라옴 — 단 **사본이 저장소 안에 이미 커밋·push 돼 있다**, 아래 ※) |
| 권한 허용목록 (**파일이 4개, 합쳐서 1,116개**) | `<repo>/.claude/settings.local.json` **+ worktree 3곳 각각의 것** | 20K+42K+9K+107K | ❌ (전역 gitignore 로 제외) |
| 전역 gitignore 파일 | `~/.config/git/ignore` | 2줄 | ❌ |
| 서브에이전트 3종 | `<repo>/.claude/agents/*.md` | 5K | ✅ (git 추적됨 — 아래 실측) |
| 🚨 **SSH 개인키** (초안에서 누락돼 있던 것) | `~/.ssh/id_ed25519` (+`.pub`, `known_hosts`) | 411B | ❌ — **없으면 VPS 접속 자체가 불가**(§8.1) |

여기에 **worktree 3개의 미커밋 작업**이 더 있다 (§7).

> 🚨 **위험 검증관 경고 — 이 문서를 실행하기 전에 반드시 읽을 것**
>
> 1. **§5 를 먼저 읽어라.** 옛 Neon 비밀번호가 **이미 공개 저장소에 올라가 있다**(가정이 아님).
> 2. **§4.2/§4.3 — 권한 허용목록을 그대로 복사하지 마라.** 그 안에는 `git reset *` /
>    `git stash *` / `git push *` / `docker restart *` / **운영 컨테이너 임의 파이썬 실행**을
>    **묻지 않고** 통과시키는 항목이 들어 있다. 반드시 §4.3 으로 걷어낸 뒤 넣는다.
> 2-b. **§4.4 — 그 허용목록 안에 `ENCRYPTION_KEY` 평문이 17군데 박혀 있다**(서로 다른 키 2개).
>    「권한 설정 파일」이 아니라 **비밀 파일**로 취급하라. USB 로 합쳐 옮기기 전에 §4.3 필터 필수.
> 3. **§6-13 — 새 PC 에서 앱을 띄우지 마라.** 운영 `.env` 로 띄우면 같은 계좌에
>    **매매엔진이 두 벌** 돌아간다(중복 주문·IP ban).
> 4. **§6-14 — 새 PC 검증이 끝날 때까지 옛 PC 를 지우지 마라.** 그게 유일한 롤백이다.

> ※ **2026-09-03 시점의 실제 상태**: 다른 에이전트가 메모리 83개와 WIP 백업을 저장소 안
> `docs/handoff/` 에 넣어 **커밋 `e51d9a8` 로 origin/main 에 push 해 두었다.**
> 그래서 **clone 만 해도 메모리 사본은 손에 들어온다**(§6-3 이 그걸 쓴다).
> 대신 그 대가로 **옛 Neon DB 비밀번호가 공개 저장소에 올라갔다 — §5 를 먼저 읽어라.**
> 반대로 `settings.local.json` 은 VPS IP 가 들어 있어 **일부러 저장소에 넣지 않았다** →
> 이것만은 USB 등으로 직접 옮겨야 한다(§6-0).

---

### 1. 프로젝트 메모리 — 이게 무엇인가

```bash
ls "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" | wc -l
```

실측 출력: `83`. `du -sh` → `764K`. 전체 합계 **564,194 바이트 / 10,752 줄**.
파일 날짜 범위 **2026-05-07 ~ 2026-09-03** (약 4개월치).

| 접두사 | 개수 | 내용 |
|---|---|---|
| `MEMORY.md` | 1 | **색인** — 82개 파일 전부를 한 줄 요약 + 링크로 묶은 목차 (28,457 바이트) |
| `project_*.md` | 70 | 세션별 사고 원인 / Fix 근거 / 반증된 가설 / 사장님 사상 verbatim |
| `feedback_*.md` | 9 | 사장님이 직접 내린 작업 방식 지시 (묻지 말고 진행, 재고 나서 말해라 등) |
| `reference_*.md` | 2 | `reference_vps.md`(VPS 경로·서비스명·DB명), `reference_sessions.md` |
| `user_profile.md` | 1 | 1인 개발+운영, 한국어, `gh` CLI 미사용, 사무실↔집 핸드오프 |

가장 큰 5개:

| 파일 | 바이트 |
|---|---|
| `project_overview.md` | 57,771 |
| `project_2026-09-03_reentry_visibility_and_tp.md` | 37,143 |
| `MEMORY.md` | 28,457 |
| `project_2026-08-14_v137_ema_vcp_strategy.md` | 26,788 |
| `project_2026-08-31_trade_data_learning.md` | 17,823 |

#### 왜 이게 저장소보다 중요할 수 있나

`MEMORY.md` 를 읽어 보면 여기 들어 있는 것은 **코드가 아니라 코드가 왜 그렇게 됐는지**다.
저장소에는 결과만 있고, 여기에는 **판단의 근거와 이미 틀린 것으로 판명된 길**이 있다.

1. **사장님 매매 사상의 원본(verbatim)** — `project_2026-08-30_sajangnim_strategy_doctrine_v3.md`,
   `project_2026-08-25_sajangnim_long_short_philosophy_v2.md`. 코드는 이 사상의 *번역본*이고,
   `project_2026-08-31_doctrine_vs_code_audit.md` 는 **번역이 8곳에서 정반대로 됐다**는 감사 기록이다.
   이걸 잃으면 「코드가 곧 사상」이라고 착각하게 된다.
2. **반증된 가설 목록** — 예: 「99% 남기면 재진입이 감시한다」(2026-09-03에 반증),
   「반대매매가 유리하다」(2026-09-01에 반증), 「봉수 완화가 유리하다」(4번 재서 4번 반증).
   이게 없으면 **이미 돈으로 값을 치른 실험을 다시 한다.**
3. **사고 원인 카탈로그** — IP ban 무한연장, dust orphan 하나로 계정 차단,
   피라미딩이 볼밴 평단을 반대로 밀어 −252, 「모름」이 「꺼짐」으로 표시된 fail-OFF 등.
   전부 **실자금 손실을 동반한 사고**이고, 재발 방지 조건이 여기에만 문장으로 남아 있다.
4. **함정 메타지식** — 「`docker exec grep` 은 디스크다, 배포 판정은 프로세스 시작 시각으로」,
   「함수 안 `from X import Y` 가 UnboundLocalError 를 만든다(2회 사고)」,
   「죽은 상수를 바꿔도 아무 일이 안 난다 — 임계값 변경 전 grep 필수」.

🚨 **저장소 코드는 GitHub 에 이중화돼 있지만, 이 메모리는 이 PC 한 대에만 있다.**
(저장소 안 `backend/memory/constitution/INDEX.md:35` 가 스스로 「모든 헌법 = 프로젝트 memory 참조
(`~/.claude/projects/*/memory/`)」라고 적어 두었다 = 저장소가 이 디렉터리에 **의존**한다.)

---

### 2. 🚨 메모리 디렉터리 이름은 「저장소 경로」에서 파생된다 — 최대 함정

#### 파생 규칙 (실측 검증)

**절대경로의 `[A-Za-z0-9]` 가 아닌 문자를 전부 `-` 하나로 바꾼다.** 그게 폴더 이름이다.

`C:\Users\user\바이낸스\binance-auto-trader` 를 한 글자씩 보면:

| 원문 | `C` | `:` | `\` | `Users` | `\` | `user` | `\` | `바` `이` `낸` `스` | `\` | `binance-auto-trader` |
|---|---|---|---|---|---|---|---|---|---|---|
| 변환 | `C` | `-` | `-` | `Users` | `-` | `user` | `-` | `-` `-` `-` `-` | `-` | `binance-auto-trader` |

→ `C--Users-user------binance-auto-trader` (`user` 뒤 대시 6개 = 구분자 1 + **한글 4글자** + 구분자 1).

이 규칙을 실제 5개 디렉터리 전부에 대해 프로그램으로 대조했고 **5/5 일치**했다:

```
OK  C--Users-user------binance-auto-trader
OK  C--Users-user------binance-auto-trader--claude-worktrees-charming-albattani-3f588f
OK  C--Users-user------binance-auto-trader--claude-worktrees-infallible-euler-6dc297
OK  C--Users-user------binance-auto-trader--claude-worktrees-infallible-euler-6dc297-backend
OK  C--Users-user------binance-auto-trader--claude-worktrees-loving-rhodes-52788c
```

#### 🚨 위험 — 새 PC 에서 저장소를 다른 경로에 두면 옛 메모리를 못 읽는다

경로가 바뀌면 폴더 이름이 바뀌고, Claude Code 는 **새 빈 폴더를 만들어 「메모리 없음」 상태로 시작**한다.
에러가 나지 않는다. 조용히 기억을 잃은 채로 작동하고, 그러면 **이미 반증된 가설을 다시 실험한다.**

| 새 PC 의 저장소 경로 | 생기는 폴더 이름 | 옛 메모리 |
|---|---|---|
| `C:\Users\user\바이낸스\binance-auto-trader` (동일) | `C--Users-user------binance-auto-trader` | ✅ 읽힘 |
| `C:\Users\**lee**\바이낸스\binance-auto-trader` | `C--Users-lee------binance-auto-trader` | ❌ 못 읽음 |
| `C:\Users\user\**binance**\binance-auto-trader` | `C--Users-user-binance-binance-auto-trader` | ❌ 못 읽음 |
| `D:\바이낸스\binance-auto-trader` | `D-------binance-auto-trader` (대시 7개: `:` `\` + 한글4 + `\`) | ❌ 못 읽음 |
| `C:\dev\binance-auto-trader` | `C--dev-binance-auto-trader` | ❌ 못 읽음 |

#### 대처법 — 둘 중 하나

**(A) 권장 — 새 PC 의 경로를 똑같이 맞춘다.** 윈도우 사용자명이 `user` 라면 이게 제일 안전하다.

```bash
mkdir -p "/c/Users/user/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git "/c/Users/user/바이낸스/binance-auto-trader"
```

**(B) 경로를 못 맞추면 — 실제 경로에서 폴더 이름을 계산해서 그리로 복사한다.**

🚨 **`sed` 로 계산하지 마라.** Git Bash 로케일이 C 이면 한글 1글자를 3바이트로 세어 대시가
4개가 아니라 12개가 된다. 실측:

```
python 방식 : C--Users-user------binance-auto-trader        ← 맞음
sed    방식 : C--Users-user--------------binance-auto-trader ← 틀림(대시 14개)
```

반드시 **저장소 안에서** 이 파이썬 한 줄로 계산한다 (Windows 파이썬이 `os.getcwd()` 로
역슬래시 절대경로를 돌려주므로 정확하다):

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "import re,os; print(re.sub(r'[^A-Za-z0-9]','-',os.getcwd()))"
```

그 출력값을 `<슬러그>` 라 하고, 메모리를 그 아래 `memory/` 로 넣는다:

```bash
mkdir -p "$HOME/.claude/projects/<슬러그>/memory"
```

#### 보너스 관찰 — worktree 에서도 메인 저장소의 메모리를 읽는다

이 조사 세션의 cwd 는 worktree(`...\worktrees\infallible-euler-6dc297`)이고,
대화 기록은 worktree 슬러그 폴더에 쌓이는데, **주입된 메모리는 메인 저장소 슬러그의 것**이었다
(세션 컨텍스트가 `...\C--Users-user------binance-auto-trader\memory\MEMORY.md` 라고 명시).
실제로 worktree 슬러그 폴더 3개 안에는 `memory/` 가 **없다**(위 `ls -la` 출력).
→ **메모리는 메인 저장소 경로 하나만 맞추면 된다.** worktree 경로는 신경 쓸 필요 없다.

---

### 3. `~/.claude/` 아래 전체 목록 — 무엇을 옮기고 무엇을 두고 갈 것인가

```bash
ls -la "$HOME/.claude/"
```

실측 결과:

| 항목 | 크기 | 정체 | 새 PC 로 |
|---|---|---|---|
| `projects/<슬러그>/memory/` | 764K | **프로젝트 메모리 83개** | 🔴 **필수 이전** |
| `projects/<슬러그>/*.jsonl` | **1.1G** | 세션 대화 기록(트랜스크립트). 가장 큰 것 하나가 406MB | 🟡 선택 — §3.1 |
| `.credentials.json` | 6.5K | Claude 로그인 자격증명 | 🚫 **복사하지 마라** — 새 PC 에서 새로 로그인 |
| `.claude.json` (홈 루트, `.claude/` 밖) | 47K | 신뢰 다이얼로그 승인·플러그인 사용 이력·캐시 | 🟢 불필요 (새로 생성됨) |
| `settings.json` | 38B | `{"skipWorkflowUsageWarning": true}` 한 줄뿐 | 🟢 불필요 |
| `backups/` | 244K | `.claude.json` 자동 백업 5개 | 🟢 불필요 |
| `tasks/` | 165K | 옛 세션 2개의 백그라운드 작업 기록 | 🟢 불필요 |
| `shell-snapshots/` | 84K | 셸 환경 스냅샷 19개 (매번 재생성) | 🟢 불필요 |
| `sessions/` | 10K | 현재 실행 중 프로세스의 잠금파일(pid 12832) | 🟢 불필요 |
| `session-env/` | 4K | **빈 디렉터리** | 🟢 불필요 |
| `CLAUDE.md` / `commands/` / `skills/` / `plugins/` | — | **존재하지 않음** (`ls` 확인) | — |

플러그인은 전부 `@inline`(Claude 앱 내장)이다 — `.claude.json` 의 `pluginUsage` 키가
`anthropic-skills@inline, design@inline, engineering@inline, productivity@inline,
finance@inline, data@inline, cowork-plugin-management@inline`.
→ **사용자가 설치한 마켓플레이스 플러그인은 없으므로 옮길 것이 없다.**
MCP 서버 설정도 없다 (`.claude.json` 최상위에 `mcpServers` 키 없음, 프로젝트별
`mcpServers` 는 빈 dict, 저장소에 `.mcp.json` 없음).

#### 3.1 세션 기록(`*.jsonl`) — 옮길지 말지

```bash
du -sh "$HOME/.claude/projects"
```

실측 `1.1G`. 내역:

| 슬러그 | 크기 | 비고 |
|---|---|---|
| `...-infallible-euler-6dc297` | 649M | 단일 파일 406MB (현재 세션) |
| `...-loving-rhodes-52788c` | 401M | |
| `C--Users-user------binance-auto-trader` | 33M | 여기 안에 **memory/** 가 있다 |
| `...-charming-albattani-3f588f` | 20M | |
| `...-infallible-euler-6dc297-backend` | 68K | |

**권장: 옮기지 않는다.** 이건 `--resume` 용 대화 로그이고, 지식은 이미 `memory/` 로
증류돼 있다. 1.1GB 를 옮기는 비용 대비 이득이 작다.
꼭 남기고 싶으면 **압축해서 별도 보관**(새 PC 의 `~/.claude/` 에 넣지 말 것 — 넣으면 그냥 용량만 먹는다):

```bash
tar -czf "/c/Users/user/claude-transcripts-2026-09-03.tar.gz" -C "$HOME/.claude" projects
```

---

### 4. 저장소 안 `.claude/` — 에이전트 3종 + 권한 파일

경로: `C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297/.claude/`

| 파일 | 크기 | 정체 |
|---|---|---|
| `agents/impl.md` | 1,807B | **일반 구현 전담 서브에이전트** (model: sonnet). UI/JS/HTML, API 라우터, 문서, 스크립트, 테스트, 순수 리팩터링을 맡는다. 🚨 손절(`force_sl_*`)·익절(`tp*`)·자본/수량 계산·레버리지·진입 판정·지표 임계값은 **거절하고 보고**하도록 지시돼 있다 |
| `agents/locator.md` | 1,884B | **코드 위치 탐색 전용** (model: haiku). 본문을 안 가져오고 「정의 위치 + 읽는 곳 N군데 + 결론」만 돌려줘 컨텍스트를 아낀다. 「죽은 상수인가」·「설정이 두 곳에 있나」·「어떤 워커가 이 전략을 집어가나」가 상용 질문으로 박혀 있다 |
| `agents/mech.md` | 1,431B | **기계적 점검 전용** (model: haiku). pytest 실행 후 신규/기존 실패 분류, `ast.parse`·`node --check` 문법 검사, 로그 패턴 세기. 매매 로직 판단은 금지 |
| `settings.local.json` | 42,065B | **권한 허용목록** — `permissions.allow` 에 **345개** 항목. 🚨 **이건 이 worktree 것 하나일 뿐이다 — 아래 §4.1** |

세 에이전트 파일은 이 저장소에서 실제로 겪은 사고가 규칙으로 굳어 있다
(예: `impl.md` 의 「함수 안 `from X import Y` 가 UnboundLocalError 를 낸다 — 실제로 두 번 사고가 났다」).

#### git 추적 여부 — 실제 확인

```bash
cd /c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297 && git ls-files .claude
```

실측 출력:

```
.claude/agents/impl.md
.claude/agents/locator.md
.claude/agents/mech.md
```

```bash
cd /c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297 && git check-ignore -v .claude/settings.local.json
```

실측 출력:

```
"C:\\Users\\user/.config/git/ignore":3:**/.claude/settings.local.json	.claude/settings.local.json
```

| 파일 | git 추적 | clone 으로 따라오나 |
|---|---|---|
| `.claude/agents/impl.md` | ✅ 추적됨 | ✅ 따라옴 |
| `.claude/agents/locator.md` | ✅ 추적됨 | ✅ 따라옴 |
| `.claude/agents/mech.md` | ✅ 추적됨 | ✅ 따라옴 |
| `.claude/settings.local.json` | ❌ **전역 gitignore** 로 제외 | ❌ **안 따라옴** |
| `.claude/worktrees/` | ❌ 저장소 `.gitignore:106` 로 제외 | ❌ 안 따라옴 |

#### 🚨 전역 gitignore 파일 자체도 저장소 밖이다

`~/.config/git/ignore` (`git config --get core.excludesFile` → **출력 없음(exit 1)** = 미설정이라
Git 기본 XDG 경로를 쓴다).
내용은 **패턴 2줄 + 사이의 빈 줄 = 총 3줄**이다(`wc -l` → `3`):

```
1: **/.claude\settings.local.json     ← 실제로는 무효 (gitignore 에서 \ 는 이스케이프 문자라
                                        「.claudesettings.local.json」을 뜻하게 된다)
2: (빈 줄)
3: **/.claude/settings.local.json     ← 실제로 일하는 줄. check-ignore 가 ":3:" 을 보고하는 이유
```

→ 아래 재생성 명령은 **옛 PC 와 바이트 단위로 같게** 만들려고 무효한 1줄까지 그대로 쓴다.
줄여도 되지만 그러면 `check-ignore` 출력이 `:3:` 이 아니라 `:1:` 로 바뀌니 §6-8 기대값을 같이 고칠 것.

새 PC 에 이 파일이 없으면 **`settings.local.json` 이 git status 에 뜨고 실수로 커밋된다.**
(345개 허용목록 안에는 VPS IP 가 박힌 ssh 명령이 13개 있다 — 공개 저장소에 올릴 물건이 아니다.)

```bash
mkdir -p "$HOME/.config/git" && printf '**/.claude\\settings.local.json\n\n**/.claude/settings.local.json\n' > "$HOME/.config/git/ignore"
```

#### 4.1 🚨 `settings.local.json` 은 **하나가 아니다 — 4개이고 내용이 전부 다르다**

이 문서 검증 중에 발견했다. worktree 마다 별도 파일이 쌓여 있고, **메인 저장소 것이 가장 빈약하다**:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "
import json,glob
for p in ['.claude/settings.local.json']+sorted(glob.glob('.claude/worktrees/*/.claude/settings.local.json')):
    print(len(json.load(open(p,encoding='utf-8'))['permissions']['allow']), p)"
```

실측:

| 파일 | 크기 | allow 개수 | ssh 항목 |
|---|---|---|---|
| `.claude/settings.local.json` (**메인 저장소**) | 20,766B | **164** | 13 |
| `.claude/worktrees/infallible-euler-6dc297/.claude/settings.local.json` | 42,065B | **345** | 13 |
| `.claude/worktrees/charming-albattani-3f588f/.claude/...` | 9,106B | **71** | 0 |
| `.claude/worktrees/loving-rhodes-52788c/.claude/...` | 107,338B | **731** | 84 |
| **중복 제거 합집합** | 158,304B | **1,116** | — |

🚨 **그래서 「`settings.local.json` 을 복사한다」만으로는 부족하다.** 메인 저장소 것만 옮기면
1,116개 중 164개(15%)만 따라오고, 나머지는 새 PC 에서 다시 프롬프트로 물어본다.
worktree 는 §7 대로 새 PC 에서 재현하지 않으므로, **4개를 합쳐 메인 저장소 자리 하나로 넣는 것**이 맞다
(합치는 명령은 §6-0). 합집합 안에 **`WebFetch` 5 / `WebSearch` 1 / `mcp__Claude_Preview__preview_start` 1**
처럼 메인 파일에는 아예 없는 종류도 들어 있다.

안 옮기면 **새 PC 에서 같은 명령마다 권한 프롬프트가 다시 뜬다**(pytest, git, ssh 조회, awk/grep 등).
작업 흐름이 크게 느려진다.

#### 4.2 🚨🚨 그러나 — 이 파일은 「편의 파일」이 아니라 **안전장치를 끄는 파일**이다

> **2026-09-03 위험 검증관 추가.** 원래 이 자리에는 「운영에 지장은 없지만 작업 흐름이 느려진다」고
> 적혀 있었다. **그 문장은 틀렸다.** 합친 1,116개가 무엇을 자동 승인하는지 실제로 세어 봤다.

`permissions.allow` 에 들어 있는 항목은 **Claude 가 사장님께 묻지 않고 즉시 실행**한다.
그리고 이 목록에는 **와일드카드(`*`)로 끝나는 항목이 34개**(345개 기준) 있어, 접두사만 맞으면
**뒤에 무엇이 오든** 통과한다. 합집합 1,116개를 패턴으로 센 실측:

| 자동 승인되는 것 | 개수 | 무슨 일이 날 수 있나 |
|---|---|---|
| `Bash(git stash *)` | 1 | 🚨 `git stash pop` / `drop` / `clear` 가 **묻지 않고** 실행된다. 이 저장소는 worktree 를 공유하므로 stash 는 **다른 worktree 의 미커밋 작업을 날릴 수 있다** |
| `Bash(git reset *)` / `Bash(git checkout *)` | 2 | 🚨 `git reset --hard` / `git checkout .` 이 **묻지 않고** 실행 → **미커밋 작업 즉시 소멸, 되돌릴 수 없다** |
| `Bash(git push *)` | 1 | 🚨 `git push --force` 가 **묻지 않고** 실행 → 공개 저장소 이력 파괴 |
| `Bash(docker restart *)` | 1 | 🚨 **실거래 중인 `api`/`scheduler` 컨테이너를 묻지 않고 재시작.** 포지션 감시가 끊긴다 |
| `ssh … 'docker exec binance-auto-trader-api python -c "` **+ `*`** | 4 | 🚨🚨 **운영 컨테이너 안에서 임의의 파이썬이 묻지 않고 실행된다.** 그 파이썬은 DB 세션과 바이낸스 클라이언트를 그대로 쥐고 있다 → **주문 생성·취소·DB 쓰기가 기술적으로 가능하다** |
| `ssh … docker compose restart` (**다른 호스트** `152.42.232.195`) | 1 | 🚨 이 문서가 한 번도 언급하지 않은 **두 번째 서버**를 재시작한다 |
| VPS `.env` 를 `grep` 해서 **화면에 찍는** 명령 | 3 | 🚨 `DATABASE_URL` 이 그대로 출력된다 → **§5 의 비밀 유출이 바로 이 경로로 일어났다고 보는 게 자연스럽다** |
| `rm -rf …` | 4 | 캐시/`__pycache__` 삭제. 경로가 고정이라 위험은 낮다 |

그리고 **`deny` 목록은 존재하지 않는다** (`permissions` 키는 `allow` 하나뿐 — 실측).
= **금지선이 하나도 안 걸려 있다.**

🔴 **결론: 이 파일을 새 PC 에 그대로 넣는 것은 「빠르게 일하기」가 아니라
「검증되지 않은 새 환경에서 안전장치를 미리 꺼 두기」다.**
새 PC 는 아직 `.env` 도, 슬러그도, 메모리도 검증되지 않은 상태다. 그 상태에서 Claude 가
운영 컨테이너에 임의 파이썬을 **묻지 않고** 날릴 수 있으면 안 된다.

#### 4.3 ✅ 그래서 이렇게 옮긴다 — 위험 항목만 빼고 넣는다

§6-0 의 합치기 명령 뒤에 **이 한 줄을 더 돌려서** 위험 항목을 걷어낸다.
(걷어낸 것은 없어지는 게 아니라, 새 PC 에서 **그때그때 사장님께 물어보게** 되는 것뿐이다.)

```bash
python -c "
import json,re
p='/e/handoff-settings.local.json'
d=json.load(open(p,encoding='utf-8'))
BAD=r'git (stash|reset|checkout|push)|docker restart|docker compose (restart|up|down)|python -c|rm -rf|DATABASE_URL|ENCRYPTION_KEY|\.env'
keep=[a for a in d['permissions']['allow'] if not re.search(BAD,a,re.I)]
drop=[a for a in d['permissions']['allow'] if re.search(BAD,a,re.I)]
d['permissions']['allow']=keep
d['permissions']['deny']=['Bash(git push --force*)','Bash(git reset --hard*)','Bash(git stash*)','Bash(docker restart*)','Bash(rm -rf *)']
json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print('kept',len(keep),'/ removed',len(drop))
for a in drop: print('  제외:',a[:110])"
```

> 이 명령은 **USB 로 뺀 사본만** 고친다. 옛 PC 의 원본 4개는 건드리지 않으므로
> 되돌리고 싶으면 §6-0 의 합치기를 다시 돌리면 된다.
> `deny` 는 `allow` 보다 우선하므로, 나중에 실수로 다시 추가돼도 막힌다.

#### 4.4 🚨🚨 `settings.local.json` 안에 **`ENCRYPTION_KEY` 평문이 박혀 있다**

> **위험 검증관이 §4.3 필터를 시험하다 발견했다. 이 문서에서 두 번째로 심각한 비밀 노출이다.**

허용목록 항목은 **명령어 문자열 통째로** 저장된다. 그래서 과거에
`ENCRYPTION_KEY=<값> python -m pytest …` 같은 식으로 **환경변수를 앞에 붙여 실행한 명령**은
**그 값까지 그대로** 파일에 남았다. 실측(값은 절대 옮기지 않는다 — 개수만):

| 파일 | `ENCRYPTION_KEY=` 가 박힌 항목 | 서로 다른 키 값 |
|---|---|---|
| `.claude/settings.local.json` (메인) | 0 | 0 |
| `worktrees/charming-albattani-3f588f/.claude/settings.local.json` | 🚨 **17** | 🚨 **2** |
| `worktrees/infallible-euler-6dc297/.claude/settings.local.json` | 0 | 0 |
| `worktrees/loving-rhodes-52788c/.claude/settings.local.json` | 0 | 0 |

세는 명령 (값을 찍지 않고 개수만 낸다):

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "
import json,glob
for p in ['.claude/settings.local.json']+sorted(glob.glob('.claude/worktrees/*/.claude/settings.local.json')):
    n=sum('ENCRYPTION_KEY=' in x for x in json.load(open(p,encoding='utf-8'))['permissions']['allow'])
    print(n,p)"
```

🔴 **왜 심각한가**

- `ENCRYPTION_KEY` 는 §5.1 이 「**잃어버리면 되돌릴 방법이 없는 유일한 비밀**」이라고 못 박은 그 키다.
  거꾸로 **새면 DB 의 `api_key_enc`(바이낸스 API 키·시크릿)를 복호화할 수 있다는 뜻**이다.
- §6-0 은 이 파일 4개를 **하나로 합쳐 USB 로 들고 가라**고 한다.
  → 아무 조치 없이 합치면 **그 USB 파일이 암호화 키를 담은 비밀 파일이 된다.**
  「권한 설정 파일」이라는 이름 때문에 **비밀 파일로 취급되지 않는 것**이 진짜 위험이다.
- §8 은 이 파일을 저장소에 넣지 말라는 이유로 「VPS IP」를 들었다.
  **실제 이유는 그보다 훨씬 무겁다 — 암호화 키가 들어 있다.**

✅ **조치 (§4.3 필터가 이미 이걸 처리한다 — 그래서 필터는 선택이 아니라 필수다)**

§4.3 의 `BAD` 정규식에 `ENCRYPTION_KEY` 가 들어 있어 **17개 항목이 전부 제거된다.**
실제로 돌려서 확인했다: **1,116개 → 유지 919 / 제거 197**(제거분에 위 17개 포함).

필터를 돌린 뒤 **0 이 나오는지 반드시 확인한다**:

```bash
python -c "
import json
a=json.load(open('/e/handoff-settings.local.json',encoding='utf-8'))['permissions']['allow']
print('키가 남은 항목:',sum('ENCRYPTION_KEY=' in x for x in a))"
```

> 🚨 **이미 이 파일을 어딘가로 보낸 적이 있다면**(메신저·메일·클라우드·다른 저장소)
> 그 키는 유출된 것으로 간주해야 한다. 다만 `ENCRYPTION_KEY` 교체는
> **DB 의 기존 암호문을 전부 못 읽게 만드는 작업**이라 §5.1 대로
> 「거래소 계정 재등록」이 함께 필요하다 — **사장님 판단 사항이고, 혼자 하지 말 것.**

---

### 5. 🚨🚨 비밀값 — 「위험」이 아니라 **이미 일어났다** (2026-09-03 실측 확인)

> **아래 3가지를 이 문서 검증 중에 실제 명령으로 확인했다. 가정이 아니다.**
>
> | 확인 항목 | 명령 | 결과 |
> |---|---|---|
> | 저장소 공개 여부 | `curl -s https://api.github.com/repos/herosys1-crypto/binance-auto-trader \| tr ',' '\n' \| grep '"visibility"'` | **`"visibility": "public"`** — 인증 없이 200. **공개 저장소다** |
> | 메모리 사본이 커밋됐는가 | `git ls-files docs/handoff/memory-backup-2026-09-03 \| wc -l` | **83** — 전부 커밋됨 (커밋 `e51d9a8`) |
> | 그게 GitHub 에 올라갔는가 | `git ls-remote origin main` | `e51d9a8...` — **origin/main = 그 커밋. 이미 push 됐다** |
> | 옛 비밀번호가 공개로 읽히는가 | `curl -s https://raw.githubusercontent.com/herosys1-crypto/binance-auto-trader/main/docs/handoff/memory-backup-2026-09-03/project_overview.md \| grep -c "npg_"` | **2** — 로그인 없이 누구나 읽힌다 |
>
> 🔴 **그러므로 아래 「대처 1·2」(커밋하지 마라 / 마스킹해서 커밋하라)는 이미 시점이 지났다.
> 지금 유효한 것은 「대처 3 = Neon 비밀번호 재교체」 하나뿐이고, 이건 선택이 아니라 필수다.**
> (지운다고 사라지지 않는다 — git 히스토리와 GitHub 캐시에 남는다. 값을 무효화하는 것만이 유일한 해결이다.)

다른 에이전트가 이미 메모리 사본을 저장소 안에 만들어 두었다:

```bash
ls /c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297/docs/handoff/memory-backup-2026-09-03 | wc -l
```

실측 `83`, `du -sh` → `764K` (원본과 동일).

🚨 **그런데 그 안의 `project_overview.md` 에 Neon DB 자격증명이 남아 있다.**
사본을 줄 단위로 재검사한 결과 **노출은 2건이 아니라 3건**이다 (값은 여기 옮기지 않는다 — 줄번호와 길이만):

| 사본 줄 | 형태 | 실측 | 마스킹 흔적(`***` / `<…>` / `…`) |
|---|---|---|---|
| `project_overview.md:385` | `npg_` 로 시작하는 비밀번호 토큰 (16자) | 길이 58자 줄 | **없음 = 평문** |
| `project_overview.md:386` | `npg_` 로 시작하는 비밀번호 토큰 (16자) | 길이 97자 줄 | **없음 = 평문** |
| `project_overview.md:389` | **`postgresql://` 전체 접속 문자열** | 길이 126자 줄 | **없음 = 평문** |

🚨 **389 줄이 새로 발견된 것이다.** 앞선 기록은 `npg_` 만 세어서 **2건**이라고 봤지만,
그 문자열은 호스트·DB명·사용자명·비밀번호가 **한 줄에 다 들어 있는 접속 URL** 이라
비밀번호 토큰 하나보다 위험도가 높다(그대로 붙여넣으면 접속이 된다).

- 「옛 password 2개 + 새 password 는 마스킹」이라던 앞선 서술은 **틀렸다.**
  위 3줄 어디에도 마스킹 문자가 없다. **어느 것이 현재 유효한지는 문서만으로 판별 불가**이며,
  판별하려고 접속을 시도해서도 안 된다 → **그래서 「전부 유효하다고 가정하고 교체」가 유일한 안전 경로다.**
- 저장소는 **public 이고 이미 push 됐다**(위 표) → **영구 공개 기록이 됐다.**

**대처 — 지금 해야 할 것 (순서대로):**

1. 🔴 **Neon Console 에서 DB 비밀번호를 지금 교체한다.** (문서상 「옛 것」이라 해도, 실제로
   무효화됐는지는 확인된 바 없다 — §9. 무효라면 교체 비용은 0 이고, 유효하다면 이게 유일한 방어다.)
   교체 후 VPS `~/binance-auto-trader/backend/.env` 의 `DATABASE_URL` 갱신 + 서비스 재시작이 필요하다
   (**이건 사장님이 직접** — 이 문서의 다른 에이전트는 VPS 쓰기 금지).
2. 그 다음 저장소에서 해당 3줄을 마스킹하고 커밋한다. **단, 이건 미래의 열람만 줄인다 —
   git 히스토리(`e51d9a8`)에는 그대로 남으므로 1번을 대체하지 못한다.**
3. 앞으로 **메모리는 저장소를 통해 옮기지 않는다** — USB / 암호화 zip 을 쓴다.

> 참고로 이 사고 자체가 이 프로젝트의 반복 패턴이다 — 「사본을 만들어 두는 편리함」이
> 「사본이 공개된다」를 덮었다. 옮기기 전에 `git ls-files` 로 **이미 추적 중인지** 먼저 볼 것.

자가 점검 (출력이 0 줄이어야 안전 — **지금은 나온다 = 아직 남아 있다**).

🚨 앞서 쓰던 점검은 `npg_` 하나만 셌고, 그래서 **389줄의 `postgresql://` 접속 문자열을 놓쳤다.**
아래처럼 **여러 종류를 한 번에** 봐야 한다. 값은 찍지 않고 `파일:줄번호`만 나온다(`-o` 없이 `-n` + `cut`):

```bash
cd /c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297/docs/handoff/memory-backup-2026-09-03 && grep -rnE 'npg_|postgres(ql)?://|redis://[^ ]*:[^ ]*@|[0-9]{8,10}:[A-Za-z0-9_-]{30,}|BEGIN [A-Z ]*PRIVATE KEY|(ghp_|github_pat_)[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}' . 2>/dev/null | cut -d: -f1,2
```

각 패턴이 무엇을 잡는가: `npg_`=Neon 비밀번호 / `postgres://`·`redis://…@`=자격증명 박힌 접속 URL /
`숫자:문자` 40자=텔레그램 봇 토큰 / `PRIVATE KEY`=SSH·TLS 개인키 / `ghp_`·`github_pat_`=GitHub 토큰 /
`AKIA`=AWS 키. **바이낸스 API 키·시크릿은 고정 접두사가 없어 이 정규식으로 못 잡는다** —
아래 §5.1 의 「`.env` 는 절대 저장소에 넣지 않는다」 규칙으로 막는 수밖에 없다.

> 참고: 위 명령을 **저장소 전체**(`memory-backup` 말고 리포지토리 루트)에 한 번 돌려 보는 것도 권장한다.
> 커밋 전에 돌리면 이번 같은 사고를 막는다.

#### 5.1 🔴 `ENCRYPTION_KEY` — 잃어버리면 **되돌릴 방법이 없는** 유일한 비밀

새 PC 이전에서 **가장 조용하게, 가장 크게 망가질 수 있는 지점**이다.
다른 비밀은 잃어버려도 재발급하면 되지만, 이것만은 **잃으면 기존 DB 데이터가 영구히 못 읽는 상태가 된다.**

근거 (저장소 코드 실측):

| 사실 | 근거 |
|---|---|
| 거래소 API 자격증명은 DB 에 **암호화되어** 저장된다 | `backend/app/models/exchange_account.py:13-15` — `api_key_enc` / `api_secret_enc` / `passphrase_enc` |
| 암호화 방식은 **Fernet(대칭키)** 이고 키는 `ENCRYPTION_KEY` 하나뿐 | `backend/app/core/crypto.py` — `encrypt_text` / `decrypt_text` 가 `_get_fernet()` 만 쓴다 |
| 키가 다르면 복호화가 **실패**한다 | `crypto.py:decrypt_text` → `InvalidToken` → `CryptoError("Failed to decrypt: invalid token")` |
| 키가 없거나 기본값이면 **앱이 아예 안 뜬다** | `backend/app/main.py:46` `validate_encryption_key()` — startup 에서 즉시 raise |
| 키 기본값은 `change_me` (= 무효) | `backend/app/core/config.py:19` |

🚨 **그래서 이런 일이 난다:**

- `ENCRYPTION_KEY` 를 **새로 생성해서** 새 환경에 넣으면 → 앱은 정상 기동한다(키가 valid 하니까).
  그런데 **DB 에 이미 들어 있는 `api_key_enc` 는 옛 키로 암호화된 것**이라 복호화가 전부 실패한다.
  즉 **「기동은 성공, 거래만 실패」** — 가장 알아채기 어려운 형태로 고장난다.
  (그때 뜨는 메시지: `backend/app/api/v1/strategies/lifecycle.py:324`
  「⚠️ API key 복호화 실패: … — ENCRYPTION_KEY 확인 필요」. **이 문구가 보이면 키가 틀린 것이다.**)
- DB 는 외부 Neon 이라 **새 PC 로 옮겨도 같은 DB 를 본다** → 옛 암호문이 그대로 남아 있다.
  로컬 PC 를 바꾸는 것만으로 이 문제가 저절로 풀리지 않는다.

**규칙:**

1. **`ENCRYPTION_KEY` 는 절대 새로 만들지 마라.** 운영 중인 값을 **그대로** 가져와야 한다.
2. 값의 출처는 **운영 VPS 의 `~/binance-auto-trader/backend/.env`** 다. (이 문서는 값을 싣지 않는다.)
3. 만약 정말 잃어버렸다면 — 복구는 불가능하고, **바이낸스에서 API 키를 새로 발급받아
   화면에서 거래소 계정을 다시 등록**하는 것이 유일한 길이다(그러면 새 키로 재암호화된다).
   `api_key_enc` 자체를 되살릴 방법은 없다.

#### 5.2 비밀을 새 PC 로 **안전하게** 옮기는 법

이 문서는 **어떤 비밀 값도 싣지 않는다.** 키 **이름**과 **어디서 얻는가**만 적는다.

옮겨야 하는 것 (전부 VPS `~/binance-auto-trader/backend/.env` 에서 얻는다):

| 키 이름 | 무엇 | 새로 만들어도 되나 |
|---|---|---|
| `ENCRYPTION_KEY` | DB 자격증명 암·복호화 Fernet 키 | 🔴 **안 됨** — §5.1 |
| `DATABASE_URL` | Neon Postgres 접속 문자열 | 비밀번호 교체 시 갱신 (§5 대처 1) |
| `SECRET_KEY` | JWT 서명 키 | 바꾸면 기존 로그인 세션만 무효 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 알림 | BotFather 에서 재발급 가능 |
| `REDIS_URL`, `SENTRY_DSN` 등 | 부가 | 각 콘솔에서 재확인 가능 |

전체 키 목록은 **`backend/.env.example`** 에 있다(값 없이 이름만 — 저장소에 안전하게 들어 있다).

🚨 **하지 말 것:**

- ❌ 카카오톡·이메일·메신저·Claude 대화창에 키를 붙여넣어 보내기
  (평문으로 서버에 영구 저장된다. 이번 §5 사고와 같은 종류의 실수다.)
- ❌ `.env` 를 저장소에 커밋하기 — **저장소는 public 이다**(§5 표).
  ✅ 다행히 이건 이미 막혀 있다 — 실측 `git check-ignore -v backend/.env` →
  `.gitignore:7:backend/.env`. (`.gitignore:2-10` 이 `.env`, `.env.*`, `backend/.env*` 를 막고
  `.env.example` 만 예외로 허용한다.) **새 PC 에서도 clone 직후 이 명령으로 한 번 확인할 것** —
  이 방어가 살아 있어야 `.env` 를 그 자리에 만들어도 안전하다.
- ❌ USB 에 평문 `.env` 를 넣고 분실하기

✅ **권장:** 새 PC 에서 **VPS 에 직접 SSH 로 붙어 값을 눈으로 보고 손으로 입력**한다
(중간 저장 매체를 아예 만들지 않는 것이 가장 안전하다):

```bash
ssh root@159.65.137.250 'grep -o "^[A-Z_]*=" ~/binance-auto-trader/backend/.env'
```

> 위 명령은 **키 이름만** 출력한다(`-o "^[A-Z_]*="` 로 `=` 뒤를 잘라낸다).
> 무엇이 필요한지 목록을 먼저 확보한 뒤, 값은 필요한 것만 개별적으로 확인해 옮긴다.
> 값을 화면에 띄웠다면 그 터미널 스크롤백을 지우는 것까지가 한 세트다.

---

### 6. 새 PC 복구 절차 — 순서대로

> **읽는 법**: 0번은 **옛 PC(지금 이 PC)** 에서, 1번부터는 **새 PC** 에서 한다.
> 모든 명령은 **Git Bash** 기준이다(PowerShell/cmd 아님 — `$HOME`, `/c/...`, `printf` 가 다르다).
> 새 PC 에 먼저 깔아야 하는 것: **Git for Windows(Git Bash 포함)**, **Python 3**
> (2번의 슬러그 계산에 쓴다. `python --version` 이 안 되면 https://python.org 에서 설치하고
> 설치 시 "Add python.exe to PATH" 를 켤 것), **Claude Code**.

**0) 🚨 옛 PC 에서 먼저 — 저장소로 못 옮기는 것 1개를 USB 로 뺀다**

메모리 83개는 이미 저장소 안에 들어 있어 clone 으로 따라온다(§0 ※).
**하지만 `settings.local.json` 은 VPS IP 가 박힌 ssh 명령 때문에 공개 저장소에 넣으면 안 된다.**
그래서 이것만 손으로 옮긴다. (`E:` 는 USB 드라이브 문자 — 실제 값으로 바꿀 것)

🚨 그냥 `cp` 하면 안 된다 — 이 파일은 **4개이고 내용이 다르다**(§4.1).
아래 명령이 4개를 합쳐(중복 제거) USB 로 내보낸다. **실측 1,116개**가 나와야 한다:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "
import json,glob
seen,allow=set(),[]
for p in ['.claude/settings.local.json']+sorted(glob.glob('.claude/worktrees/*/.claude/settings.local.json')):
    for x in json.load(open(p,encoding='utf-8'))['permissions']['allow']:
        if x not in seen: seen.add(x); allow.append(x)
json.dump({'permissions':{'allow':sorted(allow)}}, open('/e/handoff-settings.local.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('merged allow:', len(allow))"
```

> ⚠️ 여기서 끝내지 말 것 — 합친 직후에는 **위험 항목이 그대로 들어 있다.**
> 반드시 이어서 **§4.3 의 제거 한 줄**을 돌려 919 개로 줄인 뒤에 새 PC 로 가져간다.
>
> 이 명령은 이 문서 검증 중 실제로 돌려 **`merged allow: 1116`** 을 확인했다
> (읽기만 하고 원본 4개는 건드리지 않는다).
> USB 가 없으면 `/e/handoff-settings.local.json` 대신 `$HOME/handoff-settings.local.json` 로 바꿔
> 만든 뒤 원하는 매체로 옮긴다. **공개 저장소에는 넣지 말 것**(ssh 항목에 VPS IP 가 있다).

메모리를 저장소 경유가 아니라 USB 로 옮기고 싶으면(§5 권장) 이것도 같이 뺀다:

```bash
cp -r "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" "/e/handoff-memory"
```

옮긴 뒤 개수 확인 — **83** 이 나와야 한다:

```bash
ls "/e/handoff-memory" | wc -l
```

**1) 저장소를 같은 경로에 clone** (§2 (A))

저장소는 **public** 이므로 clone 자체는 로그인 없이 된다. 다만 **push 하려면** GitHub 인증이
따로 필요하다 — 첫 push 때 Git Credential Manager 창이 뜨면 브라우저로 로그인하면 된다
(사장님은 `gh` CLI 를 쓰지 않는다). clone 만으로는 이 단계가 안 나오니 미리 놀라지 말 것.

```bash
mkdir -p "/c/Users/user/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git "/c/Users/user/바이낸스/binance-auto-trader"
```

**2) 메모리 폴더 이름을 실제 경로에서 계산해 확인**

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "import re,os; print(re.sub(r'[^A-Za-z0-9]','-',os.getcwd()))"
```

기대 출력: `C--Users-user------binance-auto-trader`. 다르면 **아래 3~5번 경로의 그 부분을 출력값으로 바꿔 쓴다.**
(`python` 이 없으면 `py -c "..."` 로 해 본다. 둘 다 없으면 Python 을 먼저 깔 것 — 위 준비물 참고.)

**3) 메모리 83개 복사** — 원본은 둘 중 하나를 고른다

```bash
mkdir -p "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory"
```

**(a) clone 안의 사본을 쓴다 (가장 간단, 추가 매체 불필요)**

```bash
cp -r "/c/Users/user/바이낸스/binance-auto-trader/docs/handoff/memory-backup-2026-09-03/." "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/"
```

**(b) USB 로 뺀 것을 쓴다 (§6-0 에서 `/e/handoff-memory` 를 만든 경우)**

```bash
cp -r "/e/handoff-memory/." "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/"
```

> ⚠️ `docs/handoff/memory-backup-2026-09-03/` 가 clone 에 없으면 이미 지워진 뒤다(§5-2 마스킹 작업으로
> 함께 지웠을 수 있다) → (b) 를 쓴다. `ls` 로 먼저 확인할 것.

**4) 개수 검증 — 반드시 83 이 나와야 한다**

```bash
ls "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory" | wc -l
```

**5) 색인이 읽히는지 검증 — 첫 줄이 2026-09-03 항목이어야 한다**

```bash
head -1 "$HOME/.claude/projects/C--Users-user------binance-auto-trader/memory/MEMORY.md"
```

**6) 전역 gitignore 복원** (§4)

🚨 **이 명령은 `>` 다. 기존 파일이 있으면 통째로 덮어쓴다.**
새 PC 에 이미 `~/.config/git/ignore` 가 있다면(다른 프로젝트에서 만들어 뒀을 수 있다)
그 규칙이 **말없이 사라진다**. 그래서 **먼저 백업하고, 있으면 덮지 말고 이어붙인다**:

```bash
[ -f "$HOME/.config/git/ignore" ] && cp "$HOME/.config/git/ignore" "$HOME/.config/git/ignore.bak.$(date +%F)" && echo "기존 파일 백업함 — 아래 (b) 로 갈 것" || echo "기존 파일 없음 — 아래 (a) 로 갈 것"
```

**(a) 파일이 없던 경우** — 새로 만든다:

```bash
mkdir -p "$HOME/.config/git" && printf '**/.claude\\settings.local.json\n\n**/.claude/settings.local.json\n' > "$HOME/.config/git/ignore"
```

**(b) 파일이 이미 있던 경우** — 덮지 말고 **이어붙인다**(`>>`). 중복 추가도 막는다:

```bash
grep -qxF '**/.claude/settings.local.json' "$HOME/.config/git/ignore" || printf '\n**/.claude/settings.local.json\n' >> "$HOME/.config/git/ignore"
```

> ⏪ **되돌리기**: `cp "$HOME/.config/git/ignore.bak.<날짜>" "$HOME/.config/git/ignore"`
> (b) 로 갔다면 `check-ignore` 출력의 줄번호가 `:3:` 이 아닐 수 있다 — **줄번호는 신경 쓰지 말고
> 8번에서 `exit=0` 인지만 본다.**

**7) 권한 허용목록 복사** (§6-0 에서 USB 로 뺀 파일. `/e/...` 는 실제 경로로 바꿀 것)

`.claude/` 디렉터리는 에이전트 3종이 git 추적이라 clone 시점에 이미 존재한다 — 따로 만들 필요 없다.

🚨 **먼저 §4.3 의 「위험 항목 제거」 한 줄을 돌린 뒤에 복사한다.**
그냥 복사하면 `git reset *` / `git stash *` / `git push *` / `docker restart *` /
**운영 컨테이너 임의 파이썬 실행**이 새 PC 에서 **묻지 않고** 실행된다(§4.2).

```bash
cp "/e/handoff-settings.local.json" "/c/Users/user/바이낸스/binance-auto-trader/.claude/settings.local.json"
```

넣은 뒤 **위험 항목이 정말 빠졌는지** 확인한다 — 출력이 **0** 이어야 한다:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && python -c "
import json,re
a=json.load(open('.claude/settings.local.json',encoding='utf-8'))['permissions']['allow']
bad=[x for x in a if re.search(r'git (stash|reset|checkout|push)|docker restart|python -c',x,re.I)]
print('위험 항목 남은 개수:',len(bad))
for x in bad: print('  ',x[:110])"
```

> ⏪ **되돌리기**: 이 파일은 지워도 안전하다 — 지우면 권한 프롬프트가 다시 뜰 뿐, 기능은 멀쩡하다.
> `rm "/c/Users/user/바이낸스/binance-auto-trader/.claude/settings.local.json"`
> **의심스러우면 넣지 않는 쪽이 항상 안전하다.** 프롬프트가 뜨는 것은 고장이 아니라 안전장치다.

개수 확인 — **919** 가 나와야 한다(§6-0 합집합 1,116 에서 §4.3 이 위험 항목 197개를 걷어낸 값.
이 문서 검증 중 실제로 돌려 `kept 919 / removed 197` 을 확인했다):

```bash
python -c "import json;print(len(json.load(open(r'C:/Users/user/바이낸스/binance-auto-trader/.claude/settings.local.json',encoding='utf-8'))['permissions']['allow']))"
```

- **1116** 이 나오면 → §4.3 을 안 돌린 것이다. 위험 항목이 그대로 들어 있으니 §4.3 부터 다시 한다.
- **164** 가 나오면 → 병합을 안 하고 메인 파일만 복사한 것이다(§4.1).

**8) 제외되는지 확인 — 반드시 6번을 먼저 한 뒤에 실행한다**

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git check-ignore -v .claude/settings.local.json; echo "exit=$?"
```

- ✅ 정상: `"C:\\Users\\user/.config/git/ignore":3:**/.claude/settings.local.json` + `exit=0`
- 🚨 실패: **아무것도 안 나오고 `exit=1`** — 6번이 안 됐다는 뜻이다. 조용히 실패하므로
  「출력이 없으니 괜찮다」고 읽지 말 것. 이 상태로 커밋하면 VPS IP 가 공개 저장소로 나간다.

교차 확인(권장) — 아래 출력에 `settings.local.json` 이 **없어야** 한다:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git status --porcelain
```

**9) 에이전트 3종은 clone 으로 따라왔는지 확인 (3줄 나와야 함)**

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git ls-files .claude
```

**10) Claude 로그인** — `.credentials.json` 을 복사하지 말고 새 PC 에서 새로 로그인한다.

**11) 🔴 비밀값(`.env`) 은 「필요할 때만」 만든다** (그리고 만들었다면 **13번을 반드시 읽을 것**)

먼저 **자기가 어느 쪽인지** 정한다. 이 판단을 건너뛰면 안 만들어도 될 위험을 새 PC 에 들인다:

| 새 PC 에서 할 일 | `.env` 필요한가 | 근거 |
|---|---|---|
| 코드 편집 + git push + Claude Code 대화 | ❌ **불필요** | 배포는 VPS 에서 한다. 로컬은 소스만 다룬다 |
| `pytest` 실행 | ❌ **불필요** | `backend/tests/conftest.py:6` 이 `sqlite+pysqlite:///:memory:` 를 쓴다 — 실 DB·실 키를 안 본다 |
| 로컬에서 앱을 띄움 (`docker compose up`) | ✅ 필요 | `backend/app/core/config.py:69` 가 `env_file=".env"`, `backend/docker-compose.yml` 이 `env_file` 참조 |

🚨 **대부분의 경우는 첫 줄이다 → `.env` 를 아예 만들지 마라.**
비밀을 옮기지 않는 것이 비밀을 안전하게 옮기는 것보다 항상 낫다.

정말 로컬에서 앱을 띄워야 할 때만, **§5.2 의 방법으로** `backend/.env` 를 만든다.
그때 `ENCRYPTION_KEY` 는 **반드시 VPS 의 현재 값 그대로** — 새로 생성하면 §5.1 의
「기동은 성공, 거래만 실패」 고장이 난다.

만든 뒤 반드시 추적되지 않는지 확인한다 (**`.gitignore:7` 에 걸려야 정상**):

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git check-ignore -v backend/.env
```

출력이 없으면 🚨 **멈춰라** — 그대로 커밋하면 §5 사고가 반복된다. 저장소는 public 이다.

**12) ✅ 진짜 검증 — 「파일이 있다」가 아니라 「Claude 가 읽는다」를 확인한다**

4~5번은 *디스크에 파일이 있는지*만 본다. 슬러그가 한 글자라도 틀리면 파일은 멀쩡한데
Claude Code 는 **조용히 못 읽는다**(§2). 그래서 마지막에 반드시 이걸 한다:

1. 새 PC 에서 `cd /c/Users/user/바이낸스/binance-auto-trader` 후 **Claude Code 를 연다.**
2. 이렇게 묻는다: **「메모리에서 Fix 298 이 무엇이었는지 말해줘」**
3. ✅ 정상 = 「볼밴 분할 손절 후 재진입에서 사장님 사다리(10/300/600)를 써 **이중 마틴게일**이
   될 뻔한 것을 검증에서 잡았다」는 취지의 답이 나온다.
   🚨 실패 = 「모른다 / 코드에서 찾아보겠다」 → **메모리가 안 읽히고 있다.** 2번으로 돌아가
   슬러그를 다시 계산하고, 계산값과 `ls "$HOME/.claude/projects"` 의 실제 폴더명을 눈으로 대조한다.

이 질문의 답은 코드에는 없고 `MEMORY.md` 에만 있다 — 그래서 판별식이 된다.

**13) 🔴🔴 앱을 로컬에서 띄우기 전에 — 「두 번째 매매엔진」 사고를 막는다**

> **위험 검증관 추가. 이 문서에서 실제 자금 손실로 이어질 수 있는 가장 큰 구멍이다.**

§6-11 은 「로컬에서 앱을 띄우려면 `.env` 가 필요하다」고만 적었다. 그런데 그 `.env` 는
**운영과 똑같은 바이낸스 API 키와 똑같은 Neon DB** 를 가리킨다. 그대로 `docker compose up` 하면:

- 🚨 **VPS 의 엔진과 새 PC 의 엔진이 같은 계좌를 동시에 굴린다.** 두 워커가 같은 포지션을 보고
  각자 주문을 낸다 → **중복 진입 / 손절 취소 / 익절 이중 실행.** 어느 쪽이 낸 주문인지 구분도 안 된다.
- 🚨 **같은 DB 에 두 스케줄러가 쓴다.** 이 프로젝트 사고의 다수가 「상태가 두 곳에 저장됐다」였다
  (메모리: 「마지막 단계 트리거가 두 곳에 저장 = 화면 30% / 엔진 120%」). 엔진을 두 벌 돌리는 것은
  그 사고를 전면적으로 재현하는 것이다.
- 🚨 **API 호출량이 2배가 되어 418(IP ban) 을 부른다.** 이 프로젝트는 이미 IP ban 무한연장 사고를
  겪었다(메모리 `project_2026-08-26_ip_ban_spiral.md`). 새 PC 는 **공인 IP 가 다르므로** 밴이 나면
  새 PC 가 막히지만, 계정 단위 제한에 걸리면 **운영까지 같이 멈춘다.**

✅ **규칙:**

1. **기본은 「로컬에서 앱을 띄우지 않는다」.** 코드 편집·git·Claude Code 대화는 `.env` 없이 다 된다(§6-11 표).
2. 정말 띄워야 하면 **운영 `.env` 를 그대로 쓰지 마라.** 최소한 **바이낸스 테스트넷 키**로 바꾸고,
   `DATABASE_URL` 도 운영 Neon 이 아닌 별도 DB 를 가리키게 한다.
3. **로컬에서 바이낸스 API 를 직접 때리는 스크립트·백테스트를 돌리기 전에 한 번 더 생각한다.**
   조회(klines)라도 반복문에 들어가면 밴을 부른다. 복구 절차는 메모리의 IP ban 문서에 있다.
4. VPS 는 **조회만**. 재시작·배포는 **사장님이 직접**(헌법).

⏪ **이미 띄워 버렸다면**: 즉시 내린다 — `cd backend && docker compose down`.
그 다음 **바이낸스 화면에서 그 시간대의 주문·포지션을 눈으로 확인**한다(중복 주문이 남아 있을 수 있다).
DB 를 손으로 고치지 말고 사장님께 보고할 것.

**14) 옛 PC 를 아직 지우지 마라 — 이 이전 전체의 유일한 롤백**

이 문서의 어떤 단계도 되돌리기가 완벽하지 않다. **진짜 롤백은 옛 PC 가 그대로 남아 있는 것 하나뿐이다.**

- 옛 PC 의 `~/.claude/`, `~/.ssh/`, 저장소, worktree 를 **최소 2주는 그대로 둔다.**
- 새 PC 가 **§6-4(83개)·§6-5(색인)·§6-8(`exit=0`)·§6-9(3줄)·§6-12(메모리 질문)** 를 전부 통과하고
  실제로 한 세션을 문제없이 돌린 뒤에 옛 PC 정리를 시작한다.
- 🚨 그 전에 옛 PC 에서 `git worktree remove`, `rm -rf`, 디스크 포맷을 하지 마라.

---

### 7. 🚨 worktree 3개 — 미커밋 작업 실측

메인 저장소 기준 worktree 목록:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git worktree list
```

실측 4개(+메인). 각각의 상태 (숫자는 2026-09-03 재검증분 — 조사 중에도 커밋이 늘어 HEAD 는 변한다.
**값이 다르면 위 명령으로 다시 재라. 이 표가 아니라 명령 출력이 진실이다**):

| worktree | 브랜치 | HEAD | 미커밋 | origin 대비 |
|---|---|---|---|---|
| `binance-auto-trader` (메인) | `main` | `2586555` | 미추적 2건 | **origin/main 보다 30 커밋 뒤짐** (`git rev-list --left-right --count HEAD...origin/main` → `0  30`) |
| `.claude/worktrees/charming-albattani-3f588f` | `feat/external-positions` | `f346fee` | 미추적 1건 | 동기 (0/0) |
| `.claude/worktrees/infallible-euler-6dc297` | `claude/infallible-euler-6dc297` | `e51d9a8` | 미추적 1건 (`docs/handoff/2026-09-03/` = 이 문서) | ✅ **origin/main == e51d9a8** (`git ls-remote origin main` 으로 원격 실측) |
| `.claude/worktrees/loving-rhodes-52788c` | `feat/c-full-archive-filter-restore` | `a3e5a02` | **수정 2 + 미추적 3** | 업스트림 없음 |
| `%TEMP%\claude\...\scratchpad\baseline` | detached `2a17a26` | — | 삭제 대량 | 임시 스크래치 — 버려도 됨 |

#### 7.1 진짜 사라지는 것 — 미추적 문서 3개 🚨

`git ls-tree origin/main` 으로 대조한 결과 **origin/main 에 존재하지 않는다**:

| 파일 | 위치 | 크기 |
|---|---|---|
| `docs/CURRENT_STATE_2026-08-24_END_OF_DAY.md` | 메인 worktree | 164줄 |
| `docs/ROLLBACK_GUIDE_2026-08-24.md` | 메인 worktree | 328줄 — 「사장님 긴급 상황 대응용 롤백 가이드」 |
| `HANDOFF-2026-05-21-SAFETY-NETS.md` | charming-albattani | 7,173B |

🚨 **원래 위치(`docs/`, 저장소 루트)에는 새 PC 에서 clone 해도 없다.**
`ROLLBACK_GUIDE_2026-08-24.md` 는 스스로 「대상: 사장님 (긴급 상황 대응용)」이라고 적혀 있다.

✅ **다만 「영영 사라진다」는 아니다** — 이 3개는 §7.3 의 `wip-backup-2026-09-03/*/untracked/` 로
복사돼 **`e51d9a8` 에 커밋·push 됐다**. 즉 clone 하면 `docs/handoff/` **아래에는** 들어 있다.
원래 자리로 되돌리려면 새 PC 에서:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && cp docs/handoff/wip-backup-2026-09-03/main/untracked/docs/*.md docs/ && cp docs/handoff/wip-backup-2026-09-03/charming-albattani_feat-external-positions/untracked/HANDOFF-2026-05-21-SAFETY-NETS.md .
```

#### 7.2 loving-rhodes 의 미커밋 변경 — **살릴 필요 없음** (실측 근거 있음)

수정된 추적 파일 2개(총 9줄):

- `backend/app/api/v1/strategies.py` — `_count_active_tps` 를 `range(1,11)` → `range(1,21)` (TP20 확장)
- `backend/app/workers/scheduler_runner.py` — `long_bottom_detector` / `auto_long_at_bottom` 스케줄 등록

미추적 파일 2개: `auto_long_at_bottom_worker.py`(12,019B), `long_bottom_detector_worker.py`(27,244B) — 둘 다 **2026-08-24 07:08** 자 파일.

**origin/main 에 같은 이름의 파일이 이미 있고, 그쪽이 더 최신이다:**

```
b096463 2026-09-01  backend/app/workers/auto_long_at_bottom_worker.py
74fc949 2026-08-30  backend/app/workers/long_bottom_detector_worker.py
```

→ 로컬 미커밋본은 **8/24 초안**, origin/main 본은 8/30~9/1 까지 계속 수정된 후속본.
TP20 확장도 메모리 `project_2026-08-27_pyramid_bbsplit_tp20.md`(「TP10→TP20 확장」)로 이미 반영됨.
**결론: 고유한 작업 손실 없음. 이 worktree 는 버려도 된다.**
(단, 판단 근거가 「더 최신 커밋이 존재한다」이므로, 만약을 위해 §7.3 백업은 이미 떠 있다.)

🚨 **「버려도 된다」 ≠ 「지금 지워라」.** 지우는 것은 **새 PC 가 §6-4/§6-5 검증을 통과한 뒤**다.
그리고 지운다면 **`rm -rf` 로 지우지 마라** — worktree 를 손으로 지우면 메인 저장소의
`.git/worktrees` 에 유령 등록이 남아 이후 `git worktree add` 가 실패한다. 정식 절차는:

```bash
cd /c/Users/user/바이낸스/binance-auto-trader && git worktree remove .claude/worktrees/loving-rhodes-52788c
```

- 미커밋 변경이 남아 있으면 이 명령은 **거부하며 멈춘다 — 그게 정상이고, 그게 안전장치다.**
- 🚨 **`--force` 를 붙이지 마라.** 붙이면 위 미커밋 5건이 **경고 없이 사라진다.**
  거부당했다면 그건 「§7.3 백업이 정말 그 내용을 담고 있는지」를 다시 확인하라는 신호다.
- ⏪ **되돌리기**: 없다. worktree 삭제는 비가역이다. 그래서 순서가 전부다 —
  **새 PC 검증 통과 → 그 다음 삭제.** 애초에 옛 PC 를 그대로 두면 지울 이유가 없다.

#### 7.3 이미 떠 있는 WIP 백업

다른 에이전트가 `docs/handoff/wip-backup-2026-09-03/` 에 worktree 3곳의
`uncommitted.patch` / `staged.patch` / `untracked/` / `untracked-list.txt` / `unpushed-commits.txt`
(charming-albattani 는 `unpushed/0001-feat-positions.patch` 도) 를 이미 만들어 두었다(120K).
**이 폴더도 `e51d9a8` 로 이미 커밋·push 돼 있다** — 즉 clone 만 해도 따라온다.
§7.1 의 미추적 문서 3개도 그 안 `untracked/` 에 들어 있다 — **이 폴더가 실제 구조선**이다.

```bash
find /c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297/docs/handoff/wip-backup-2026-09-03 -type f
```

🚨 메인 worktree 가 **origin/main 보다 30 커밋 뒤져** 있으므로, 새 PC 에서는
옛 로컬 main 을 흉내내지 말고 **origin/main 을 그대로 clone** 하면 된다(위 §6-1).

---

### 8. 저장소 밖 이전 대상 목록 (최종·우선순위)

| 순위 | 대상 | 원본 경로 | 크기 | 없으면 무슨 일이 나나 | 이전 방법 |
|---|---|---|---|---|---|
| 🔴 **0** | **`ENCRYPTION_KEY` 를 포함한 `.env` 비밀값** | VPS `~/binance-auto-trader/backend/.env` (로컬 저장소엔 `.gitignore:7` 로 없음) | 18개 키 | 🚨 **새로 만들면 앱은 뜨는데 DB 의 `api_key_enc` 를 못 읽어 거래만 조용히 실패**한다 (§5.1) | VPS 에서 직접 확인해 손으로 입력. **채팅·이메일 금지** (§5.2) |
| 🔴 1 | **프로젝트 메모리 83개** | `~/.claude/projects/C--Users-user------binance-auto-trader/memory/` | 764K | 사장님 사상 원본·사고 원인·반증된 가설 전부 소실 → **돈으로 값 치른 실험을 다시 함** | **사본이 이미 `e51d9a8` 로 push 됨 → clone 으로 확보 가능**(§6-3a). 앞으로는 USB/암호화 zip (§5) |
| 🔴 2 | **미추적 문서 3개** (롤백 가이드 등) | `wip-backup-2026-09-03/*/untracked/` | ~25K | 긴급 롤백 절차 소실 | **이미 push 됨 → clone 으로 따라옴.** 원래 자리로 되돌리는 명령은 §7.1 |
| 🔴 3 (🚨 **비밀 파일**) | **`.claude/settings.local.json` × 4개** (합집합 1,116 허용) — **`ENCRYPTION_KEY` 평문 17건 포함**(§4.4), **위험 명령 자동승인 포함**(§4.2). 옮기기 전 **§4.3 필터 필수** | `<repo>/.claude/` + `<repo>/.claude/worktrees/*/.claude/` | 합 179K → 병합 시 158K | 명령마다 권한 프롬프트 재발 → 작업 속도 급락. **메인 것만 옮기면 15%(164개)만 따라온다**(§4.1) | 🚨 **저장소에 없는 유일한 항목 — §6-0 병합 명령으로 합쳐 USB 로.** VPS IP 때문에 공개 저장소 금지 |
| 🔴 **3.5** | 🚨 **SSH 개인키 `~/.ssh/id_ed25519`** (+ `.pub`, `known_hosts`) | `~/.ssh/` | 411B / 101B / 2,070B | 🚨 **VPS 에 아예 접속이 안 된다.** 허용목록의 ssh 명령 13~84건이 전부 실패하고, §5.2 의 「VPS 에서 `.env` 값 확인」도 못 한다 = **이 문서의 상당 부분이 실행 불가** | 🚫 **채팅·이메일·공개 저장소 금지.** USB 로 직접 옮기거나, **새 키를 만들어 VPS `~/.ssh/authorized_keys` 에 등록**하는 편이 더 안전하다 (아래 §8.1) |
| 🟠 4 | **전역 gitignore** | `~/.config/git/ignore` | 패턴 2줄(파일은 3줄) | 위 파일이 실수로 커밋됨 (VPS IP 포함 ssh 13건) | §6-6 명령으로 재생성 |
| 🟡 5 | 세션 트랜스크립트 | `~/.claude/projects/*/*.jsonl` | **1.1G** | `--resume` 불가. 지식은 메모리에 증류돼 있음 | 별도 압축 보관 권장(§3.1) |
| 🟢 6 | `.claude/agents/*.md` 3종 | `<repo>/.claude/agents/` | 5K | — **git 추적됨, clone 으로 따라옴** | 조치 불필요 |
| 🚫 7 | `.credentials.json` | `~/.claude/.credentials.json` | 6.5K | — | **복사 금지, 새로 로그인** |
| 🟢 8 | `~/.claude` 나머지 전부 | backups / tasks / sessions / shell-snapshots / session-env / settings.json / `.claude.json` | ~550K | 자동 재생성 | 조치 불필요 |

#### 8.1 🚨 SSH 개인키 — 원래 목록에 **빠져 있던** 항목 (검증관 추가)

이 문서 초안은 `~/.ssh/` 를 한 번도 언급하지 않았다. 그런데 실측하면 존재한다:

```bash
ls -la "$HOME/.ssh"     # id_ed25519(411B) / id_ed25519.pub(101B) / known_hosts(2,070B)
```

**이게 없으면 VPS 접속이 전부 실패한다.** 허용목록의 ssh 명령도, §5.2 의 「VPS 에서 `.env` 를
직접 보고 손으로 옮긴다」도 전부 이 키에 의존한다.

🚨 **그런데 개인키는 「그냥 복사」하면 안 되는 물건이다.**

- **이 키에는 passphrase 가 없다 — 추측이 아니라 실측이다.** 다음 명령이 키를 화면에 찍지 않고
  「빈 암호로 열리는가」만 검사하는데, `NO_PASSPHRASE` 가 나왔다:

  ```bash
  ssh-keygen -y -f "$HOME/.ssh/id_ed25519" -P "" >/dev/null 2>&1 && echo NO_PASSPHRASE || echo HAS_PASSPHRASE
  ```

  = **파일 하나만 새면 누구나 운영 서버 root 로 들어온다.** 실자금이 도는 서버다.
  파일 권한도 `-rw-r--r--` 로 느슨하다.
- ❌ 카카오톡·이메일·클라우드 드라이브·Claude 대화창에 붙여넣지 마라.
- ❌ 저장소에 넣지 마라 — **저장소는 public 이다**(§5).

✅ **권장 — 옮기지 말고 새로 만든다** (분실·유출 위험이 0 이고, 옛 PC 를 나중에 폐기할 때도 안전하다):

```bash
ssh-keygen -t ed25519 -C "new-pc-$(date +%F)"      # 새 PC 에서. passphrase 를 꼭 넣을 것
cat "$HOME/.ssh/id_ed25519.pub"                     # 이 공개키 한 줄만 옮기면 된다 (공개키는 비밀이 아니다)
```

그 공개키 한 줄을 **옛 PC 에서** VPS 의 `~/.ssh/authorized_keys` 에 덧붙인다.
🚨 **`>` 가 아니라 `>>` 다.** `>` 로 쓰면 기존 키가 지워져 **옛 PC 까지 접속이 끊긴다**(자물쇠 안에 갇힌다).

⏪ **되돌리기 / 안전장치**: 새 키로 접속이 **성공하는 것을 확인하기 전에는**
옛 키를 `authorized_keys` 에서 지우지 마라. 두 키가 동시에 유효한 상태를 거쳐서 넘어간다.

> 🚨 **덤으로 발견된 것**: 허용목록 안에 이 문서가 한 번도 언급하지 않은
> **두 번째 서버 `152.42.232.195`**(사용자 `trader`, `-i ~/.ssh/id_ed25519`)로
> `docker compose restart` 와 `.env.production` 복사를 하는 항목이 있다.
> 이 서버가 무엇인지는 **확인 못 함**(§9). 새 PC 에서 이 명령이 자동 승인되지 않도록
> §4.3 의 제거를 반드시 거칠 것.

---

### 9. ⚠️ 확인 못 함

| 항목 | 왜 |
|---|---|
| ~~GitHub 저장소의 public/private 여부~~ | ✅ **해소됨 — `public` 으로 확인**(§5 상단 표, `api.github.com` 인증 없이 200 + `"visibility":"public"`). 「확인 못 함」이 아니라 **최악의 경우가 사실**이었다 |
| `project_overview.md:385~386` 의 옛 Neon 비밀번호가 **실제로** 무효화됐는지 | 문서에 「옛」이라고 적혀 있을 뿐, DB 에 확인 쿼리를 보내지 않았다(비밀값 취급 금지 규칙). 확인이 안 되므로 §5-1(재교체)을 **무조건** 실행하는 것이 맞다 |
| 새 PC 의 Windows 사용자명 | `user` 가 아니면 §2 (B) 경로를 써야 한다 |
| 새 PC 의 Claude Code 버전이 같은 슬러그 규칙을 쓰는지 | 현재 PC 는 v2.1.258 (`~/.claude/sessions/12832.json`). 규칙이 바뀌면 §6-2 계산값과 실제 생성 폴더가 다를 수 있다 → **§6-4 개수 검증(83)이 그래서 필수다** |
| loving-rhodes 미커밋본과 origin/main 본의 **내용 방향** | 파일이 다르다는 것과 origin/main 쪽 커밋이 더 최신(8/30~9/1)이라는 것만 확인했다. 줄 단위 우열은 비교하지 않았다 |
| `%TEMP%` 의 `baseline` worktree 에 고유 작업이 있는지 | 대량 삭제 상태의 스크래치로 보이나 상세 조사는 안 했다 |
| 🚨 **두 번째 서버 `152.42.232.195`(사용자 `trader`) 의 정체** | 허용목록에서 발견했다(§8.1). `docker compose restart` 와 `.env.production` 복사를 하는 항목이 있어 **운영 계열로 보이지만**, 이 문서·메모리·`reference_vps.md` 어디에도 언급이 없다. 접속해서 확인하지 않았다(VPS 읽기전용 + 정체 불명 호스트). **사장님만 답할 수 있다 — 새 PC 작업 전에 확인 필요** |
| 🚨 **허용목록의 위험 항목이 실제로 사고를 낸 적이 있는지** | 「자동 승인된다」는 것은 `settings.local.json` 을 읽어 확인했다(§4.2). 그 명령이 과거에 실행됐는지는 트랜스크립트 1.1GB 를 뒤지지 않아 모른다. **사고 이력과 무관하게 새 PC 에는 넣지 않는 것이 맞다** |
| `~/.ssh/known_hosts` 에 등록된 호스트 목록 | 파일 존재와 크기(2,070B)만 봤다. 내용을 열지 않았다 |
| `project_overview.md:389` 의 `postgresql://` 접속 문자열이 **현재 유효한지** | 줄의 **존재·길이(126자)·마스킹 없음**만 확인했다. 값은 읽지도 옮기지도 않았다(비밀값 취급 금지). 385·386 과 마찬가지로 **유효하다고 가정하고 교체**하는 것이 맞다 |
| VPS `.env` 의 `ENCRYPTION_KEY` **값** | 일부러 읽지 않았다(비밀값 금지 + VPS 읽기전용). 이 문서는 **키 이름과 얻는 위치만** 싣는다 — §5.2 |
| 현재 DB 의 `api_key_enc` 가 **지금 VPS 의 `ENCRYPTION_KEY` 로 실제 복호화되는지** | 복호화 시도 자체가 비밀값 취급이라 하지 않았다. 운영이 정상 매매 중이므로 **맞다고 추정**할 뿐이다. 새 환경에서 확인하려면 화면에서 거래소 계정 조회가 되는지 보면 된다(`lifecycle.py:324` 오류 문구가 안 뜨면 정상) |
| `.env` 의 나머지 키(`SECRET_KEY`, `TELEGRAM_*` 등)가 **VPS 에 실제로 몇 개 설정돼 있는지** | 키 이름 목록조차 VPS 에서 조회하지 않았다. §5.2 표는 **저장소의 `backend/.env.example` 18개**를 근거로 한 것이라, 운영에 추가 키가 있을 수 있다 |


---

<a id="sec-3"></a>

## 3. 비밀·설정 인벤토리 (값 없이 이름만)

> # 🚨🚨 이 문서를 깃에 커밋하기 전에 반드시 읽을 것 — **이 저장소는 공개(public)다**
>
> 2026-09-03 실측:
> ```
> $ curl -s https://api.github.com/repos/herosys1-crypto/binance-auto-trader | grep visibility
>   "visibility": "public",     # "private": false
> ```
> 그리고 `docs/handoff/` 는 **이미 깃에 추적되는 디렉터리**다 (커밋된 파일 102개 — `git ls-files docs/handoff/`).
> 즉 **이 파일을 커밋해서 push 하면 아래 내용이 전 세계에 공개된다.**
>
> - 운영 VPS 공인 IP + **root 로 SSH 접속한다**는 사실
> - **`ufw` 가 꺼져 있고 redis `6380` 이 비밀번호 없이 열려 있다**는 사실 (§9-5) — 이건 그대로 침입 안내문이다
> - 안전장치가 전부 해제돼 있다는 사실 (일일 손실 한도 0 / 레버리지 125 / 청산거리 검사 0)
> - 운영 비밀들의 지문
>
> 값 자체는 없으니 「즉시 계정이 털린다」는 뜻은 아니지만, **공격자에게 어디를 어떻게 두드릴지 알려주는 문서**다.
>
> **권장 (순서대로):**
> 1. **커밋하지 않는다.** 이 파일은 `docs/handoff/2026-09-03/` 에 있고 지금은 `??`(미추적) 상태다 — 그대로 두고 USB·비밀번호 관리자로만 옮긴다.
> 2. 굳이 저장소에 두려면 **저장소를 private 으로 바꾼 뒤**에 한다 (GitHub → Settings → Danger Zone → Change visibility).
> 3. 그래도 커밋하겠다면 **§9-5(redis/ufw)와 §0 의 VPS IP 를 먼저 지운다.**
>
> ⚠️ 이미 커밋·push 한 뒤라면 파일을 지우는 것만으로는 부족하다 — **깃 히스토리에 남는다.** 그때는 (a) 저장소를 private 으로 전환하고 (b) redis 를 `127.0.0.1` 로 묶고 `ufw` 를 켜는 것이 실질적인 대응이다.
>
> (참고: 2026-09-03 기준 **이미 커밋된 102개 handoff 문서에서는 비밀 값이 발견되지 않았다** — Grafana 비번·Neon 엔드포인트·봇 토큰·개인키 패턴 전부 0건.)
>
> 🚨 **다만 handoff 문서가 아닌 곳에 이미 새어 있는 것이 하나 있다.**
> `backend/docker-compose.yml:98-99` 의 **Grafana admin 비밀번호는 평문으로 이미 이 공개 저장소에 커밋돼 있다.**
> 「앞으로 조심하자」가 아니라 **지금 이미 공개된 상태**다. 이전 작업과 별개로 처리하실 것:
> ① Grafana 비밀번호를 바꾸고 ② compose 에서 값을 빼 `.env` 참조(`${GF_SECURITY_ADMIN_PASSWORD}`)로 돌린다.
> (다행히 Grafana 는 `127.0.0.1:3000` 바인딩이라 인터넷에서 직접 로그인창에 닿지는 않는다. 하지만
> `ufw` 가 꺼져 있고 같은 비밀번호를 다른 데 쓰셨다면 위험이 번진다.)
> 🚨 **이 조치는 저장소를 private 으로 바꿔도 끝나지 않는다** — 이미 공개돼 있던 값이므로 **비밀번호 자체를 교체**해야 한다.

> 조사 일시: 2026-09-03 / 대상: 로컬 사무실 PC + 운영 VPS `159.65.137.250`
> **이 문서에는 어떤 비밀 값도 적혀 있지 않다.** 키 이름 · 「어디서 얻는가」 · 지문(SHA-256 앞 12자리, 역산 불가) 만 기록했다.
> (초안에는 Grafana admin 비밀번호가 평문으로 한 군데 들어가 있었다 — 비밀 검토에서 발견해 **삭제**했다. §9-5b. 이 문서를 고칠 때 값을 다시 넣지 마시라.)
> VPS 는 조회만 했고 아무것도 바꾸지 않았다.

---

### 0. 먼저 읽을 것 — 이번 이전에서 가장 위험한 5가지

| # | 위험 | 왜 위험한가 | 근거 |
|---|---|---|---|
| 🚨 1 | **`ENCRYPTION_KEY` 를 잃으면 DB 의 바이낸스 API 키를 영원히 복호화할 수 없다** | Fernet 대칭키. 키가 없으면 `exchange_accounts.api_key_enc` 는 복구 불가능한 쓰레기 문자열이 된다. 바이낸스에서 키를 **새로 발급**받는 것 말고는 방법이 없다 | `backend/app/core/crypto.py:33-56`, `deploy/generate-secrets.sh:107` |
| 🚨 2 | **사무실 PC 의 `backend/.env` 가 운영 Neon DB 를 가리킨다** — DATABASE_URL 만 최신값으로 채우는 순간 **VPS 와 똑같은 실계좌로 매매하는 엔진이 하나 더 뜬다** | 로컬 `.env` 의 DATABASE_URL 은 호스트·DB·사용자·쿼리까지 VPS 와 **전부 동일**하고 **비밀번호만 다르다**. 그 비밀번호는 이미 만료돼 지금 그대로는 **인증 실패**한다(실측). 하지만 `ENCRYPTION_KEY` 지문이 VPS 와 **완전히 같으므로**, DB 만 붙으면 mainnet 키가 그대로 복호화된다 | 아래 §4 지문 비교 (2026-09-03 실측: 로컬 DSN 연결 시 `AUTH_FAIL`) |
| 🚨 3 | **VPS SSH 접속 키가 새 PC 에 없으면 VPS 를 아예 못 만진다 — 비밀번호로 들어가는 우회로가 없다** | `~/.ssh/authorized_keys` 에 등록된 공개키가 **딱 1개**(`ssh-ed25519 … binance-trader-vps`) 이고, 그 짝인 개인키는 사무실 PC 의 `~/.ssh/id_ed25519` 하나뿐이다. 게다가 서버는 **비밀번호 로그인이 꺼져 있다**(`passwordauthentication no`) → 키를 잃으면 SSH 로는 **어떤 방법으로도** 못 들어간다. 그때 남는 유일한 길은 **DigitalOcean 웹 콘솔(Recovery Console)** 로 붙어 새 공개키를 직접 넣는 것이다 (사장님의 DigitalOcean 로그인 필요) | VPS `wc -l authorized_keys` = 1 / `sshd -T` → `permitrootlogin yes`, `passwordauthentication no`, `pubkeyauthentication yes` (2026-09-03 읽기 전용 실측) / 로컬 `id_ed25519.pub` 주석이 `binance-trader-vps` 로 일치 |
| 🚨 4 | **새 PC 에서 `alembic upgrade head` 를 그냥 치면 운영 Neon DB 에 마이그레이션이 걸린다** | alembic 은 `.env` 의 `DATABASE_URL` 을 그대로 따라간다. 로컬 `.env` 가 운영 Neon 을 가리키므로(위험 2), 「로컬 스키마 만들려고」 친 명령이 **실운영 DB 를 변경**한다. DDL 은 롤백 스크립트가 없다. ⚠️ 지금 이 순간은 그 비밀번호가 만료돼 있어 인증 단계에서 먼저 막히지만(§4-1), **최신 DATABASE_URL 을 채운 직후부터는 진짜로 걸린다** | §7-2 의 안전 절차를 **반드시** 먼저 볼 것 |
| 🚨 5 | **새 PC 에서 바이낸스를 직접 호출하면 IP ban(418) 위험** | 새 PC 공인 IP 는 바이낸스 화이트리스트에 없다 → 서명 요청이 전부 거부되고, 재시도가 반복되면 **IP 밴이 스스로 연장**된다(2026-08-26 실사고). 밴은 그 IP 전체에 걸리므로 조사 중 VPS 까지 영향받을 수 있다 | §7-2b (초안의 `§7-5` 는 존재하지 않는 절 — 링크 수정함) |

> **⚠️ 위험 4·5 는 「읽기만 하려던 명령」에서 났다.** 이 문서의 명령 중 `alembic`, `check_binance_key.py`, `rotate_encryption_key.py` 셋은 **읽기 명령이 아니다.** 치기 전에 해당 절을 끝까지 읽을 것.

---

### 1. `.env` 키 인벤토리

#### 1-1. `backend/.env.example` 의 18개 키 (신규 환경의 최소 집합)

`backend/.env.example` 전체 (값은 전부 더미이므로 그대로 읽어도 안전).

| # | 키 | 무엇인가 | 누가 만드나 | 새 PC/새 배포에서 얻는 법 |
|---|---|---|---|---|
| 1 | `APP_NAME` | 앱 표시 이름 | 코드 기본값 | 그대로 두면 됨 (`config.py:5`) |
| 2 | `APP_ENV` | `local` / `production` | 사장님 | 직접 입력. **미설정 시 `local`** (`config.py:6`) |
| 3 | `SECRET_KEY` | JWT 서명키 (로그인 토큰) | **명령으로 생성** | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — 바꾸면 전 사용자 재로그인 필요 |
| 4 | `JWT_ALGORITHM` | 고정 `HS256` | 코드 기본값 | 건드리지 말 것 |
| 5 | `ACCESS_TOKEN_EXPIRE_MINUTES` | 토큰 유효시간(분) | 사장님 | 운영값 `10080`(7일) |
| 6 | `POSTGRES_PASSWORD` | 로컬 `db` 컨테이너 비번 | **명령으로 생성** | Neon 을 쓰면 **실질적으로 안 쓰임** (§6 참고). `docker-compose.yml:10` 이 참조 |
| 7 | `DATABASE_URL` | 실제 DB 접속 문자열 | **Neon 콘솔에서 복사** | https://console.neon.tech → 프로젝트 → Connection details 복사. 🚨 현재 운영 DB 를 가리킴 |
| 8 | `TEST_DATABASE_URL` | 테스트용 DB | 사장님 | 로컬 `db` 컨테이너 그대로 두면 됨 |
| 9 | `REDIS_URL` | Redis 주소 | 코드 기본값 | 컨테이너 내부는 `redis://redis:6379/0` 고정 |
| 10 | `BINANCE_FUTURES_BASE_URL` | 메인넷 엔드포인트 | 코드 기본값 | `https://fapi.binance.com` 고정 |
| 11 | `BINANCE_FUTURES_TESTNET_BASE_URL` | 테스트넷 엔드포인트 | 코드 기본값 | `https://testnet.binancefuture.com` 고정 |
| 12 | 🚨 `ENCRYPTION_KEY` | **DB 의 API 키 암복호화 Fernet 키** | **명령으로 생성 — 단 기존 DB 를 쓸 거면 절대 새로 만들면 안 됨** | §3 전체를 읽을 것 |
| 13 | `ENABLE_METRICS` | Prometheus 지표 노출 | 사장님 | VPS 현재 `false` |
| 14 | `TELEGRAM_BOT_TOKEN` | 알림 봇 토큰 | **사장님이 BotFather 에서** | 텔레그램 `@BotFather` → `/mybots` → 기존 봇 토큰 재사용 또는 `/newbot` |
| 15 | `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID | **사장님** | 봇과 1:1 대화 후 `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| 16 | `SENTRY_DSN` | 오류 수집 DSN | **사장님이 sentry.io 에서** | https://sentry.io → 프로젝트 → Client Keys(DSN). 비워도 동작함 |
| 17 | `SENTRY_TRACES_SAMPLE_RATE` | 트레이스 표본율 | 코드 기본값 | `0.1` |
| 18 | `SENTRY_PROFILES_SAMPLE_RATE` | 프로파일 표본율 | 코드 기본값 | `0.0` |

> ⚠️ 위 표의 `python -c "…"` 명령은 **Windows 새 PC 에서 `python3` 이 아니라 `python`** 이다 (사무실 PC 실측: `python3` 은 없다). 실행 전 §2 의 주의사항을 먼저 읽을 것.
> ⚠️ 이 18개는 **「완전히 새 환경을 처음부터 만들 때」의 최소 집합**이다. 이번 이전은 그게 아니라 **기존 `.env` 를 그대로 옮기는 것**이므로, 실제로 새로 만들 값은 **`DATABASE_URL` 하나뿐**이다 (§4-1). 나머지를 새로 만들면 오히려 사고가 난다.

#### 1-2. 운영 VPS `.env` 에 실제로 들어있는 키 = **26개** (example 보다 8개 많음)

VPS 에서 키 이름만 뽑은 결과. **APP_NAME / APP_ENV 두 개가 빠져 있다.**

| 키 | example 대비 | 현재 운영값 | 해설 |
|---|---|---|---|
| `SECRET_KEY` | 동일 | (비밀) | 길이 64 |
| `JWT_ALGORITHM` | 동일 | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 동일 | `10080` | 7일 |
| `POSTGRES_PASSWORD` | 동일 | (비밀) | 로컬 db 컨테이너용 — Neon 쓰므로 사실상 미사용 |
| `DATABASE_URL` | 동일 | Neon `ep-…(엔드포인트 ID 마스킹).ap-southeast-1.aws.neon.tech/neondb` | 🚨 운영 DB. 정확한 엔드포인트는 https://console.neon.tech → Connection details 에서 확인 |
| `TEST_DATABASE_URL` | 동일 | (비밀) | |
| `REDIS_URL` | 동일 | `redis://redis:6379/0` | 비밀번호 없음 |
| `BINANCE_FUTURES_BASE_URL` | 동일 | `https://fapi.binance.com` | |
| `BINANCE_FUTURES_TESTNET_BASE_URL` | 동일 | `https://testnet.binancefuture.com` | |
| 🚨 `ENCRYPTION_KEY` | 동일 | (비밀, 길이 44 = 정상 Fernet) | §3 |
| `ENABLE_METRICS` | 동일 | `false` | Prometheus 스크레이프 비활성 |
| `TELEGRAM_BOT_TOKEN` | 동일 | (비밀) | |
| `TELEGRAM_CHAT_ID` | 동일 | (비밀) | |
| `SENTRY_DSN` | 동일 | (비밀) | 설정돼 있음 |
| `SENTRY_ENV` | **➕ 추가** | `mainnet` | ⚠️ **코드에서 이 키를 읽는 곳이 하나도 없다** — `grep -rn "SENTRY_ENV\|sentry_env" backend/app/` 결과 0건. 죽은 키 |
| `SENTRY_TRACES_SAMPLE_RATE` | 동일 | `0.1` | |
| `SENTRY_PROFILES_SAMPLE_RATE` | 동일 | `0.0` | |
| `ALLOWED_SYMBOLS_CSV` | **➕ 추가** | (빈 값) | 비어 있음 = **모든 심볼 허용** (`config.py:74-77`) |
| `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` | **➕ 추가** | `100` | 계정당 동시 전략 상한. 템플릿 권장 3~5 인데 운영은 100 |
| `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` | **➕ 추가** | `100` | 단일 전략이 잔액의 100%까지 = **사실상 무제한** |
| `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | **➕ 추가** | `false` | 같은 심볼+방향 중복 전략 차단 (`config.py:62`) |
| `DAILY_LOSS_LIMIT_USDT` | **➕ 추가** | `0` | **0 = 일일 손실 한도 비활성** (`config.py:33`) |
| `MAX_LEVERAGE` | **➕ 추가** | `125` | 바이낸스 최대치 = 상한 없음과 동일 |
| `MIN_LIQUIDATION_DISTANCE_PCT` | **➕ 추가** | `0` | **0 = 청산가 거리 검사 비활성** |
| `HEARTBEAT_INTERVAL_HOURS` | **➕ 추가** | `6` | 하루 4번 텔레그램 생존 알림 |
| `WALLET_LIMIT_PCT` | **➕ 추가** | `130` | 지갑 대비 투입 상한 %. ⚠️ pydantic 이 아니라 `os.environ` 으로 직접 읽는다 (`app/services/capital_calculator.py:38`) → `config.py` 에 정의가 **없다** |
| `APP_NAME` | **➖ 없음** | — | 코드 기본값 사용 |
| `APP_ENV` | **➖ 없음** | — | ⚠️ 미설정 → `config.py:6` 기본값 **`local`** 로 운영 중. 운영 서버인데 `local` 로 뜬다 |

#### 1-3. 사무실 PC `backend/.env` = **22개** (VPS 와 다름)

경로: `C:\Users\user\바이낸스\binance-auto-trader\backend\.env` (2026-05-10 수정, 1380 bytes)

- VPS 에 있고 로컬에 **없는** 키: `SENTRY_ENV`, `DAILY_LOSS_LIMIT_USDT`, `MAX_LEVERAGE`, `MIN_LIQUIDATION_DISTANCE_PCT`, `HEARTBEAT_INTERVAL_HOURS`, `WALLET_LIMIT_PCT`
- 로컬에 있고 VPS 에 **없는** 키: `APP_NAME`, `APP_ENV`(=`local`)
- `SENTRY_DSN` 은 로컬만 **빈 값**
- ⚠️ **키 이름은 같은데 값이 다른 것 2개** (2026-09-03 실측):
  - `ALLOWED_SYMBOLS_CSV` — VPS 는 **빈 값**(모든 심볼 허용)인데 로컬은 **심볼 2개가 들어 있다**. 로컬 엔진을 띄우면 그 2개만 거래된다. 사본을 새 PC 로 옮길 때 「VPS 와 같은 설정」이 아님을 알고 있을 것
  - `DATABASE_URL` — **비밀번호만 다르고 이미 만료됐다.** §4-1 참고
- 🚨 `DATABASE_URL` 호스트 = **VPS 와 동일한 운영 Neon** (`ep-…(마스킹)/neondb`)

> ⚠️ 워크트리(`.claude/worktrees/infallible-euler-6dc297/backend/`) 에는 `.env` 가 없다. 있는 건 본 저장소 쪽뿐이다.

---

### 2. 사장님이 직접 해야 하는 것 vs 코드/명령이 만드는 것

> **이 세션의 규칙: Claude 는 API 키를 발급하지도, 입력하지도 않는다. 아래 「사장님」 항목은 전부 사장님이 직접 하신다.**

| 구분 | 항목 | 방법 |
|---|---|---|
| 🙋 **사장님이 직접** | 바이낸스 API Key / Secret | https://www.binance.com/en/my/settings/api-management 에서 발급. Futures ✅ / 출금 ❌ / 신뢰 IP 제한 ✅ |
| 🙋 **사장님이 직접** | 바이낸스 IP 화이트리스트에 새 IP 추가 | 새 PC 나 새 서버에서 바이낸스를 직접 호출할 거면 그 공인 IP 를 등록해야 함 |
| 🙋 **사장님이 직접** | Neon DB 접속 문자열 | https://console.neon.tech → Connection details |
| 🙋 **사장님이 직접** | 텔레그램 봇 토큰 / Chat ID | @BotFather |
| 🙋 **사장님이 직접** | Sentry DSN | https://sentry.io |
| 🙋 **사장님이 직접** | GitHub 로그인 | 원격이 HTTPS 이고 credential helper = `manager` → 새 PC 첫 push 때 브라우저 로그인 창이 뜬다 |
| 🙋 **사장님이 직접** | SSH 개인키 이전 | §7 참고 |
| ⚙️ **명령이 생성** | `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| ⚙️ **명령이 생성** | `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — 🚨 **기존 DB 를 계속 쓸 거면 새로 만들면 안 된다** |
| ⚙️ **명령이 생성** | `POSTGRES_PASSWORD` / `REDIS_PASSWORD` | `deploy/generate-secrets.sh` 가 한번에 만들어 줌 — 🚨 **바로 아래 경고를 먼저 읽을 것** (그 스크립트는 `ENCRYPTION_KEY` 도 새로 만든다). ⚠️ `REDIS_PASSWORD` 는 **넣어도 아무 일이 안 일어난다**: 코드에도 compose 에도 이 키를 읽는 곳이 **0곳**이고(`grep -rn REDIS_PASSWORD` → 생성 스크립트와 템플릿 주석뿐), redis 는 `--requirepass` 없이 뜬다. 실제로 잠그려면 ① compose 의 redis `command` 에 `--requirepass` 추가 ② `REDIS_URL` 을 `redis://:<비번>@redis:6379/0` 으로 변경, 두 가지를 같이 해야 한다 (§9-5) |
| 🤖 **코드가 자동 생성** | `api_key_enc` / `api_secret_enc` | 사장님이 평문 키를 넣으면 `encrypt_text()` 가 암호화해 저장 (`app/api/v1/exchange_accounts.py:103-104`) |
| 🤖 **코드가 자동 생성** | `password_hash` | `hash_password()` (`scripts/create_admin.py:59`) |
| 🤖 **코드가 자동 생성** | `system_settings` 63행 | 워커/UI 가 씀 — §5 |

자동 생성 가능한 것들을 한 번에 뽑는 명령:

```bash
bash deploy/generate-secrets.sh > /tmp/new-secrets.env
```

> 🚨 **이번 이전에서는 이 스크립트를 쓰지 마시라.** 두 가지 이유다.
>
> 1. **이 스크립트는 새 `ENCRYPTION_KEY` 도 같이 만든다** (`generate-secrets.sh:39,47`). 출력을 통째로 `.env` 에 붙여 넣으면 **DB 의 바이낸스 키가 즉시 복호화 불가**가 된다 (§3-2). 이건 「완전히 새 DB 로 처음부터 시작할 때」 쓰는 스크립트다.
> 2. **Windows 새 PC 에서는 아예 안 돈다.** 스크립트가 `python3` 을 요구하는데(`:23-26`) Windows 파이썬은 `python` 이라는 이름만 설치된다. 2026-09-03 사무실 PC 에서 실행해 확인:
>    ```
>    $ bash deploy/generate-secrets.sh > /tmp/new-secrets.env
>    ERROR: python3 가 필요합니다 (sudo apt install python3)
>    exit=1
>    ```
>    쓰려면 VPS 같은 Linux 에서 돌리거나, Git Bash 라면 `python3` 별칭을 먼저 만들어야 한다:
>    ```bash
>    alias python3=python && bash deploy/generate-secrets.sh > /tmp/new-secrets.env
>    ```
> 3. **경로 주의**: `generate-secrets.sh` 는 **저장소 루트**의 `deploy/` 에 있다 (`backend/deploy/` 아님 — 실측). 이 문서의 다른 명령은 대부분 `backend/` 에서 도는데 이것만 루트다. `cd "…/binance-auto-trader"` 에서 실행할 것.
> 4. 🚨 **`/tmp/new-secrets.env` 는 평문 비밀 파일이다.** 만들었으면 반드시 쓰고 나서 지운다. 그냥 두면 재부팅 전까지 디스크에 남는다.
>    ```bash
>    shred -u /tmp/new-secrets.env 2>/dev/null || rm -f /tmp/new-secrets.env
>    ```
>    (Git Bash 의 `/tmp` 는 실제로는 Windows 사용자 임시폴더다. `shred` 가 없으면 `rm` 이라도 반드시 칠 것.)

**이번 이전에서 필요한 건 아래 두 줄이 전부다** (기존 DB·기존 키를 그대로 쓰므로).

`SECRET_KEY` 만 새로 만들 때 (만들면 전 사용자 재로그인 필요 — 안 만들어도 된다):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`ENCRYPTION_KEY` 를 **정말로** 새로 만들 때 (§3-3 (B) 회전 절차와 반드시 같이):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ 두 명령 모두 **Windows 에서는 `python3` 이 아니라 `python`** 이다 (`python3` 은 없다 — 실측).
> ⚠️ 두 번째 명령은 `cryptography` 패키지가 있어야 돈다. 새 PC 의 맨 파이썬에는 없다. `ModuleNotFoundError: No module named 'cryptography'` 가 나면:
> ```bash
> pip install cryptography
> ```
> (또는 `python -m pip install cryptography`. 정상이면 44자짜리 키가 한 줄 출력된다.)

---

### 3. 🚨 `ENCRYPTION_KEY` — 이전에서 가장 위험한 지점

#### 3-1. API 키가 DB 에 저장되는 구조

1. 사장님이 **평문** API key/secret 을 입력한다 — 경로는 두 가지뿐이다.
   - REST: `POST /api/v1/exchange-accounts` (`app/api/v1/exchange_accounts.py:95-117`) / 교체는 `PATCH /{id}/credentials` (`:148`)
   - CLI: `backend/scripts/create_admin.py --binance-api-key ... --binance-api-secret ...` (`:79-80`)
2. `encrypt_text()` 가 **Fernet** 으로 암호화한다 (`app/core/crypto.py:40-45`).
3. 결과 문자열이 `exchange_accounts.api_key_enc` / `api_secret_enc` 컬럼에 들어간다 (`app/models/exchange_account.py:13-14`).
4. 워커가 주문을 낼 때마다 `decrypt_text()` 로 되돌린다 (`app/core/crypto.py:48-56`). 호출처는 워커·에이전트·API 전반에 수십 곳.
5. Fernet 키는 **`settings.encryption_key` 하나뿐** — 즉 `.env` 의 `ENCRYPTION_KEY` (`crypto.py:35`).

#### 3-2. 키를 잃으면 어떻게 되는가

> **Fernet 은 대칭키다. 토큰 안에 키 힌트가 들어있지 않다.**
> `ENCRYPTION_KEY` 를 잃으면 `api_key_enc` 는 **수학적으로 복구 불가능**하다. 백도어도, 복구 절차도, 「관리자 재설정」도 없다.

- 앱은 부팅 시 `validate_encryption_key()` 로 키 형식을 검사하고, 형식이 틀리면 **즉시 죽는다** (`app/main.py:46` → `crypto.py:12-30`).
- 형식은 맞는데 **값이 다른** 키면 부팅은 되고, 첫 주문 시점에 `CryptoError("Failed to decrypt: invalid token")` 가 난다 (`crypto.py:54-55`). 이게 더 나쁘다 — 조용히 매매가 멈춘다.
- 복구 방법은 **바이낸스에서 API 키를 새로 발급받아 다시 등록**하는 것뿐이다. 그러면 IP 화이트리스트도 다시 설정해야 한다.

#### 3-3. 그래서 이전 절차는 둘 중 하나다

**(A) 기존 DB 를 계속 쓴다 (권장, 지금 상황)**
→ `ENCRYPTION_KEY` 를 **글자 하나도 바꾸지 말고 그대로 옮긴다.** 새로 생성하면 안 된다.
→ 옮기는 방법: 1Password / Bitwarden 같은 비밀번호 관리자, 또는 USB. **채팅·이메일·텔레그램·깃·스크린샷·클라우드 드라이브 금지.**
→ 🚨 **Claude(나) 에게 값을 붙여넣지 마시라.** 이 문서를 만드는 동안에도 나는 `.env` 의 값을 한 번도 읽지 않았다. 옮기는 일은 사장님만 하신다.
→ USB 를 썼으면 **옮긴 뒤 그 파일을 지우고 휴지통도 비운다.** USB 는 잃어버리기 쉽다.
→ 제대로 옮겨졌는지는 **값을 열어보지 말고 §4 의 지문(fingerprint)으로 대조**한다. 눈으로 44자를 비교하지 말 것 — 한 글자 차이를 못 잡는다.

**(B) 키를 새로 만든다 (회전)**
→ 반드시 전용 도구를 쓴다. `.env` 만 바꾸면 DB 가 통째로 잠긴다.

> 🚨 **어디서 돌리는가가 중요하다.** 이 스크립트는 `.env` 의 **옛** `ENCRYPTION_KEY` 로 복호화하면서 동시에 **운영 DB 에 접속**한다. 즉 아래 세 조건이 동시에 맞는 곳에서만 돈다.
> - `DATABASE_URL` 이 **실제로 붙는** 값일 것 → **새 PC 의 `.env` 는 지금 인증 실패한다** (§4-1). 그래서 **새 PC 에서는 돌아가지 않는다.**
> - 앱 의존성(`sqlalchemy`, `cryptography`, `psycopg2`)이 깔려 있을 것
> - 옛 `ENCRYPTION_KEY` 가 그 `.env` 에 그대로 있을 것
>
> 현실적으로 **VPS 의 api 컨테이너 안**이 유일한 실행 장소다. 다만 이건 **운영 DB 에 쓰는 작업**이라 이번 세션 범위(읽기 전용) 밖이고, **사장님이 직접** 하셔야 한다:
> ```bash
> # dry-run (DB 변경 없음)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app -e NEW_ENCRYPTION_KEY="<새-Fernet-키>" api python scripts/rotate_encryption_key.py --dry-run'
> ```
> 로컬(Windows)에서 굳이 돌린다면 `backend/` 안에서 아래 형태이지만, 위 세 조건 때문에 **현 상태로는 실패한다**:
> ```bash
> NEW_ENCRYPTION_KEY="<새-Fernet-키>" python scripts/rotate_encryption_key.py --dry-run
> ```
>
> 🚨 **위 두 명령은 새 Fernet 키를 「명령줄」에 적는다.** 그러면 그 키가 세 군데에 흔적을 남긴다.
> - Git Bash `~/.bash_history` / VPS `~/.bash_history` — 파일로 영구히 남는다
> - ssh 로 보낸 경우 **VPS 의 `~/.bash_history` 에도** 남는다
> - 실행 중에는 `ps aux` 로 같은 서버의 누구나 볼 수 있다
>
> 그래서 회전을 실제로 할 때는 **키를 명령줄에 쓰지 말고 파일로 넘기는 편이 안전하다.** 예: VPS 에서
> ```bash
> # ① 키를 600 권한 파일에 넣는다 (편집기로 직접 붙여넣기 — 명령줄에 쓰지 않는다)
> umask 077 && vi /root/.rotate_key.env      # NEW_ENCRYPTION_KEY=... 한 줄
> # ② 파일에서 읽어 실행
> cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app \
>   --env-file /root/.rotate_key.env api python scripts/rotate_encryption_key.py --dry-run
> # ③ 끝나면 지운다
> shred -u /root/.rotate_key.env 2>/dev/null || rm -f /root/.rotate_key.env
> ```
> ⚠️ `docker compose exec` 의 `--env-file` 지원 여부는 compose 버전을 탄다 — **이 절차는 실제로 돌려보지 않았다.** 안 되면 ①의 파일을 `source` 한 뒤 `-e NEW_ENCRYPTION_KEY` (값 없이 이름만) 로 넘기면 된다. 어느 쪽이든 **끝난 뒤 `history -c` 로 히스토리를 정리**할 것.

dry-run 이 `failed=0` 이면 `--dry-run` 만 떼고 같은 명령을 다시 실행한다 (컨테이너 안이면 위 ssh 줄에서 `--dry-run` 만 제거).

- 이 스크립트는 옛 키로 복호화 → 새 키로 재암호화 → **즉시 round-trip 검증**까지 한다 (`scripts/rotate_encryption_key.py:140-159`).
- 한 행이라도 실패하면 **전체를 롤백**하고 DB 를 건드리지 않는다 (`:263-271`).
- 백업 JSON(`key-rotation-backup-*.json`)이 자동 생성된다. 🚨 **이 파일에는 옛 암호문이 그대로 들어있다** — 안전한 곳으로 옮기고 검증 후 폐기 (`:181-189`). ⚠️ **`--dry-run` 에서도 이 파일이 만들어진다** (`:274`, 주석 「dry-run 도 백업 만듦」) — 「연습만 했으니 남는 게 없다」고 생각하면 안 된다.
- 되돌리기: `python scripts/rotate_encryption_key.py --restore-from <backup.json>` (`:234-243`)
- 🚨 **이 스크립트는 옛/새 `ENCRYPTION_KEY` 의 앞 8자를 화면에 출력한다** (`:257-258`, `old_key head=… / new_key head=…`). 출력을 채팅·스크린샷에 붙이지 말 것.

##### 🚨🚨 회전의 진짜 위험 — 「DB 만 바뀌고 엔진은 옛 키를 들고 있는 구간」

**스크립트가 성공한 순간, 실매매는 즉시 고장 난다.** 이건 스크립트 버그가 아니라 구조다.

- `settings.encryption_key` 는 프로세스 **기동 시점에 한 번** 읽혀 메모리에 남는다 (`config.py` 의 `settings = Settings()` 모듈 전역).
- 그래서 DB 를 새 키로 재암호화해도, **이미 떠 있는 api / scheduler / user-stream / mark-price-stream 은 옛 키를 계속 쓴다.**
- 그 순간부터 주문·청산·손절 경로가 전부 `CryptoError("Failed to decrypt: invalid token")` 로 실패한다.
  **부팅은 멀쩡하고 헬스체크도 초록이다.** §3-2 가 말한 「조용히 매매가 멈춘다」가 바로 이 상태다.
- 🚨 **손절이 안 나가는 구간**이라는 뜻이다. 포지션이 열려 있으면 이건 금전 손실로 직결된다.

**그래서 회전은 「포지션이 없을 때」 정비 작업으로만 한다.** 순서를 지킨다:

1. **활성 포지션·전략을 먼저 정리하거나, 최소한 신규 진입을 멈춘다** (Kill-Switch / 토글 OFF).
   포지션을 연 채로 회전하지 말 것.
2. `--dry-run` → `failed=0` 확인.
3. 백업 JSON 을 **먼저 안전한 곳으로 복사**해 둔다. 이게 유일한 되돌리기 수단이다.
4. 실행 (`--dry-run` 제거).
5. **VPS `.env` 의 `ENCRYPTION_KEY` 를 새 값으로 교체.** ← 이걸 빼면 4번의 고장이 계속된다.
6. **컨테이너 재시작** — `docker compose up -d --force-recreate api scheduler user-stream mark-price-stream`.
   (재시작은 사장님 판단·사장님 손으로. 이번 세션은 읽기 전용이었다.)
7. `validate_encryption_key()` + §3-4 의 복호화 확인이 통과하는지 본다.
8. 통과한 뒤에야 매매를 다시 켠다. 백업 JSON 은 검증 완료 후 폐기.

**되돌리기 (4~6 사이에서 문제가 생겼을 때)**

- DB 는 이미 새 키다. `.env` 만 옛 값으로 되돌리면 **복호화가 안 된다** — 반쪽 롤백은 상황을 더 나쁘게 만든다.
- 제대로 된 롤백은 **둘을 같이** 되돌리는 것이다:
  `--restore-from <backup.json>` 으로 DB 를 옛 암호문으로 복원 **하고**, `.env` 도 옛 `ENCRYPTION_KEY` 로 되돌린 **뒤 재시작**.
- 따라서 **백업 JSON 과 옛 키 둘 다 없으면 롤백이 불가능하다.** 3번 단계를 절대 건너뛰지 말 것.
- 어느 쪽으로도 복구가 안 되면 남는 길은 하나뿐이다 — **바이낸스에서 키 재발급 후 재등록**(§3-2).

> 정리: **지금 상황(§3-3 (A), 기존 DB 유지)에서는 회전할 이유가 없다.**
> 회전은 「키가 유출됐을 때」의 사고 대응 절차이지, PC 이전 절차가 아니다.
> 이전만 하실 거라면 (B) 를 통째로 건너뛰는 것이 가장 안전하다.

#### 3-4. 현재 상태 — 정상 확인됨

VPS 에서 실제로 복호화가 되는지 확인했다 (평문은 출력하지 않고 길이만).

```
ENCRYPTION_KEY_VALID_FERNET = True
account id=1 testnet=False active=True {'api_key_enc': 'DECRYPT_OK(plain_len=64)', 'api_secret_enc': 'DECRYPT_OK(plain_len=64)'}
account id=2 testnet=True  active=False {'api_key_enc': 'DECRYPT_OK(plain_len=3)',  'api_secret_enc': 'DECRYPT_OK(plain_len=3)'}
```

- id=1 = 실계좌. 평문 64자 = 바이낸스 표준 길이 → **정상**
- id=2 = 테스트넷, 비활성. 평문 3자 = 더미 자리채움

새 PC 에서 같은 검증을 하려면:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.crypto import validate_encryption_key; validate_encryption_key(); print(\"OK\")"'
```

> 🚨 `backend/scripts/check_binance_key.py` 도 진단에 쓸 수 있지만, 이 스크립트는 **API key 앞 10자와 API _secret_ 앞 10자를 둘 다 화면에 출력한다** (`:38-39` — `[key] head=… / [sec] head=…`). 특히 **secret 이 찍히는 게 위험하다.** 출력을 채팅·스크린샷·이슈에 붙이지 말 것. 되도록 이 스크립트 대신 위의 `validate_encryption_key()` 한 줄을 쓸 것.

---

### 4. 사무실 PC ↔ VPS 값 일치 여부 (지문 비교, 값 노출 없음)

SHA-256 앞 12자리. 역산 불가능하며, 같은지 다른지만 알려준다.

> ℹ️ **왜 지문을 문서에 적어도 되는가.** 여기 나오는 값들은 전부 **난수로 생성된 고엔트로피 비밀**이다(Fernet 키 32바이트, `token_urlsafe(48)`, 봇 토큰, Neon 발급 비번). 해시를 역산하거나 후보를 전수 대입하는 게 계산적으로 불가능하다.
> 🚨 **사람이 정한 비밀번호에는 이 방법을 쓰지 마시라.** 짧고 흔한 비번은 해시만 있으면 사전 대입으로 몇 초 만에 뚫린다. 그런 값은 지문도 적지 말고 **「일치 / 불일치」만** 적을 것.

| 키 | 사무실 PC | VPS | 판정 |
|---|---|---|---|
| `ENCRYPTION_KEY` | `1728f1f33e3b` | `1728f1f33e3b` | ✅ **완전히 같음** |
| `SECRET_KEY` | `6b4d0d3e9d6f` | `6b4d0d3e9d6f` | ✅ 같음 |
| `TELEGRAM_BOT_TOKEN` | `a9eed4f168b3` | `a9eed4f168b3` | ✅ 같음 |
| `DATABASE_URL` | `4396df2704d2` | `a41b3c08b8a7` | ⚠️ **비밀번호만 다르다** — 아래 §4-1 참고 |

#### 4-1. `DATABASE_URL` 이 정확히 어디가 다른가 (2026-09-03 실측, 값 노출 없음)

URL 을 조각내 조각별로 지문을 떠서 비교했다.

| 조각 | 사무실 PC | VPS | 판정 |
|---|---|---|---|
| scheme (`postgresql+psycopg2`) | `a9dc07587109` | `a9dc07587109` | ✅ 같음 |
| user (`neondb_owner`) | `6f1981911003` | `6f1981911003` | ✅ 같음 |
| **password** | `23deba5d81e3` | `3980cf61167a` | 🚨 **다름** (둘 다 Neon 이 발급한 같은 형식·같은 길이) |
| host (Neon 엔드포인트) | `8f0c4435395b` | `8f0c4435395b` | ✅ 같음 |
| DB 이름 (`/neondb`) | `779b9128cc47` | `779b9128cc47` | ✅ 같음 |
| query (`?sslmode=…`) | `0c864f1972b8` | `0c864f1972b8` | ✅ 같음 |

**그리고 사무실 PC 의 그 비밀번호는 이미 만료됐다.** 실제로 붙여 봤다 (읽기 전용 `select 1`):

```
LOCAL DATABASE_URL: CONNECT_FAIL kind= AUTH_FAIL
```

→ 즉 **사무실 `.env` 를 그대로 복사하면 DB 에 붙지 않는다.** Neon 비밀번호가 언젠가 리셋됐고 VPS 만 갱신된 것이다.

**결론: 사무실 PC 의 `backend/.env` 는 `DATABASE_URL` 한 줄만 낡은 「운영 비밀 사본」이다.**
→ 이전 방법: **이 파일을 그대로 새 PC 로 손으로 옮기되, `DATABASE_URL` 한 줄만 최신값으로 교체한다.**
→ 최신 `DATABASE_URL` 얻는 법 (둘 중 하나. 값이 화면에 찍히므로 스크린샷·채팅 금지):
> - **(권장)** Neon 콘솔 https://console.neon.tech → 프로젝트 → **Connection details** 에서 새로 복사. 드라이버 접두어를 `postgresql+psycopg2://` 로 바꾸고 `?sslmode=require` 를 유지할 것 (VPS 값과 같은 형식).
> - VPS 것을 그대로 가져온다: `ssh root@159.65.137.250 'grep "^DATABASE_URL=" ~/binance-auto-trader/backend/.env'`
>
> 🚨 교체 전에 **§7-2 를 먼저 읽을 것.** 최신 DATABASE_URL 을 넣는 순간 새 PC 는 운영 DB 에 붙고, `ENCRYPTION_KEY` 가 같으므로 실계좌 키까지 복호화된다. 「DB 가 안 붙는다」가 지금은 우연한 안전장치 역할을 하고 있다.

새 PC 에서 옮긴 뒤 지문으로 검산 (값을 보지 않고 확인).

**Git Bash 에서** (`sha256sum` 은 Git Bash 에만 있다. PowerShell·cmd 에서는 없는 명령이다):

```bash
cd /c/Users/<Windows사용자명>/바이낸스/binance-auto-trader/backend && for K in ENCRYPTION_KEY SECRET_KEY; do V=$(grep "^$K=" .env | head -1 | cut -d= -f2-); printf "%s fp=%s\n" "$K" "$(printf '%s' "$V" | sha256sum | cut -c1-12)"; done
```

**PowerShell 밖에 없다면** (같은 결과가 나오는 것을 2026-09-03 실측 확인):

```powershell
Set-Location "C:\Users\<Windows사용자명>\바이낸스\binance-auto-trader\backend"
$v = ((Get-Content .env) | Where-Object { $_ -like 'ENCRYPTION_KEY=*' } | Select-Object -First 1) -replace '^ENCRYPTION_KEY=',''
$s = [System.IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($v))
"ENCRYPTION_KEY fp=" + (Get-FileHash -InputStream $s -Algorithm SHA256).Hash.ToLower().Substring(0,12)
```

`ENCRYPTION_KEY fp=1728f1f33e3b` 가 나오면 성공이다.

> ⚠️ **지문이 안 맞으면 90%는 줄바꿈 문자 때문이다.** 현재 `.env` 는 **LF** 다 (`file .env` → `UTF-8 text`, CR 0개 — 실측). Windows 메모장으로 편집·저장하면 CRLF 가 되고, 그러면 값 끝에 보이지 않는 `\r` 이 붙어 ① 지문이 달라지고 ② `ENCRYPTION_KEY` 가 **44자가 아니게 되어 Fernet 검증에서 앱이 부팅부터 죽는다** (§3-2). `.env` 는 VS Code / Notepad++ 처럼 **줄바꿈을 LF 로 유지**하는 편집기로만 열 것. Git Bash 로 확인:
> ```bash
> file .env && grep -c $'\r' .env   # "UTF-8 text" 이고 0 이면 정상
> ```
> ⚠️ 경로의 `<Windows사용자명>` 은 새 PC 의 실제 로그인 계정명이다 (Git Bash 에서 `echo $USERNAME` 으로 확인). 폴더 이름 `바이낸스` 는 한글이지만 공백이 없어 따옴표 없이도 동작한다.

---

### 5. `system_settings` — 운영 토글 (VPS 실조회, 총 63행)

값 읽는 규칙 (`app/services/system_settings_service.py:38-46`):
**`true` / `1` / `yes` / `on` (대소문자 무관) → 켜짐. 그 외 전부 꺼짐. 행 자체가 없으면 코드 기본값.**

#### 5-1. 요청받은 14개 키의 현재 상태

| 키 | DB 값 | 해석 | 근거 |
|---|---|---|---|
| `stage_trim_before_next_enabled` | `1` | ✅ **켜짐** — 다음 단계 진입 전 부분 정리 | `app/services/stage_trim.py:66` |
| `stage_keep_notional_usdt` | **행 없음** | 코드 기본값 **10 USDT** 사용 (남길 증거금) | `stage_trim.py` `KEEP_NOTIONAL_DEFAULT = Decimal("10")` |
| `entry_chg24_gate_enabled` | `1` | ✅ **켜짐** — 24h 변동률 진입 게이트 | `app/services/chg24_entry_gate.py:56` |
| `entry_rank_top_n` | **행 없음** | 코드 기본값 **50** (상승 50 + 하락 50 = 100종목) | `chg24_entry_gate.py` `TOP_N_DEFAULT: int = 50` |
| `entry_chg24_gate_mode` | **행 없음** | 코드 기본값 **`rank`** (순위 방식). 다른 값은 `abs`(절대값) | `chg24_entry_gate.py` `MODE_DEFAULT: str = "rank"` |
| `support_score_gate_enabled` | **행 없음** | ❌ **꺼짐** (기본 OFF, 헌법 161) | `app/services/support_score.py:99` + `gate_enabled()` |
| `support_score_min_long` | **행 없음** | 코드 기본값 **6** (이 점수 이상이면 LONG 허용, 승률 70.6% n=80) | `support_score.py` `MIN_LONG_DEFAULT = 6` |
| `support_score_max_short` | **행 없음** | 코드 기본값 **1** (이 점수 이하면 SHORT 허용, 승률 63.9% n=67) | `support_score.py` `MAX_SHORT_DEFAULT = 1` |
| `trend_4h_gate_enabled` | `1` | ✅ **켜짐** — 4H 추세 게이트 | `app/services/trend_4h_gate.py:62` |
| `auto_obv_enabled` | `1` | ✅ **켜짐** — OBV 자동 진입 | `app/api/v1/strategy_suggestions.py:878` |
| `adaptive_tp_enabled` | `1` | ✅ **켜짐** — 변동성 연동 TP1 | `app/services/adaptive_tp.py:77` |
| `sajangnim_ladder_stages_enabled` | `1` | ✅ **켜짐** — 사장님 3단 사다리 | `app/services/sajangnim_capital.py:353` |
| `sajangnim_pyramid_trigger_roi` | `2` | ROI **+2%** 에서 피라미딩 추가 진입 | `app/workers/success_pyramiding_worker.py:47` |
| `stage_wait_for_turn_enabled` | `1` | ✅ **켜짐** — 단계 진입 시 「꺾임」 대기 | `app/services/stage_entry_timing.py:68` |

> 🚨 **「행이 없다」와 「꺼져 있다」는 다르다.** 위 6개는 DB 에 행이 아예 없어서 코드 기본값으로 도는 중이다. 새 환경으로 DB 를 그대로 가져가면 동일하게 유지되지만, **DB 를 새로 만들면 이 기본값들이 그대로 적용된다**는 뜻이기도 하다.

#### 5-2. 전체 목록 — 진입/매매 토글

| 키 | 값 | 해설 |
|---|---|---|
| `confluence_gate_enabled` | `true` | ✅ 합의 게이트 (`app/services/confluence_gate.py:47`) |
| `entry_window_short_enabled` | `true` | ✅ SHORT 진입 시간창 |
| `long_surge_gate_enabled` | `1` | ✅ LONG 급등 게이트 (`app/services/long_surge_gate.py:62`) |
| `support_breakdown_short_enabled` | `0` | ❌ 지지 붕괴 SHORT 꺼짐 |
| `scheduled_entry_enabled` | `1` | ✅ 예약 진입 (`"1" 이어야 동작`, `app/workers/scheduled_entry_worker.py:64`) |
| `unified_entry_enabled` | `0` | ❌ 통합 진입 꺼짐 |
| `unified_15m_1h_pct` | `2` | 통합 진입 1h 기준 %(꺼져 있어 미적용) |
| `unified_15m_3h_pct` | `7` | 〃 3h 기준 % |
| `unified_v223_min_score` | `1` | 〃 최소 점수 |
| `auto_bb_breakdown_enabled` | `0` | ❌ 볼밴 하향 돌파 꺼짐 |
| `auto_bb_break_daily_limit` | `0` | 일일 한도 0 = 사실상 차단 |
| `auto_bb_break_reset_at` | `2026-08-23T07:34:…` | 워커가 쓰는 타임스탬프 (수동 편집 대상 아님) |
| `pending_hc_fast_enabled` | `0` | ❌ |
| `success_pyramiding_enabled` | `0` | ❌ 피라미딩 워커 꺼짐 — ⚠️ `sajangnim_pyramid_trigger_roi=2` 는 설정돼 있지만 워커 자체가 OFF |
| `whitelist_enabled` | `false` | ❌ 심볼 화이트리스트 미적용 (`ALLOWED_SYMBOLS_CSV` 도 비어 있음) |

#### 5-3. 3단 모드 키 (`off` / `shadow` / `on`) — 🚨 값 해석 주의

이 두 개는 bool 이 아니다. **`shadow` 는 「판정은 하되 실제 주문은 내지 않음」** 이다.

| 키 | 값 | 해설 | 근거 |
|---|---|---|---|
| `bb_mid_line_mode` | `on` | ✅ **실주문 나감** | `app/workers/bb_mid_line_worker.py:42` (`off \| shadow \| on`) |
| `surge_ladder_mode` | `shadow` | ⚠️ **로그만, 실주문 없음** | `app/workers/surge_peak_ladder_worker.py:70` |

#### 5-4. 볼밴 분할 / 사장님 사다리 / 재진입

| 키 | 값 | 해설 |
|---|---|---|
| `pump_split_enabled` | `1` | ✅ 볼밴 분할 켜짐 |
| `pump_split_capitals` | `100,200,500` | 1/2/3차 자본 (USDT) |
| `pump_split_steps` | `3,5,7` | 단계별 트리거 %p |
| `pump_split_sl_roi` | `10` | 손절 ROI % |
| `pump_split_max_concurrent` | `10` | 동시 보유 상한 |
| `split_peak_stall_enabled` | `1` | ✅ 정점-주춤 판정 (`app/workers/stage_trigger_worker.py:905`) |
| `sajangnim_capital_ladder` | `10,300,600` | 사장님 3단 사다리 |
| `sajangnim_default_capital` | `50.0` | 기본 자본 |
| `sajangnim_max_stage` | `3` | 최대 단계 |
| `sajangnim_pyramid_capital` | `300` | 피라미딩 1회 추가액 |
| `sajangnim_reentry_daily_limit` | `10` | 재진입 일일 한도 |
| `sajangnim_reentry_concurrent_slots` | `10` | 재진입 전용 동시 슬롯 |
| `sajangnim_top_short_daily_limit` | `50` | 정점 SHORT 일일 한도 |

#### 5-5. OBV 자동 진입

| 키 | 값 | 키 | 값 |
|---|---|---|---|
| `auto_obv_enabled` | `1` ✅ | `auto_obv_min_confidence` | `0.95` |
| `auto_obv_capital_per_stage` | `400` | `auto_obv_daily_limit` | `3` |
| `auto_obv_leverage` | `2` | `auto_obv_stage2_trigger` | `-5.0` |
| `auto_obv_stage3_trigger` | `-5.0` | `auto_obv_tp1` ~ `tp4` | `15.0 / 25.0 / 35.0 / 45.0` |

#### 5-6. 손절 / 증거금

| 키 | 값 | 해설 |
|---|---|---|
| `force_sl_short_enabled` | `true` | ✅ SHORT 강제 손절 |
| `force_sl_short_roi` | `80` | ROI −80% 에서 강제 손절 |
| `force_sl_long_roi` | `80` | LONG 〃 |
| `force_sl_unlock_unreachable_stage` | `true` | ✅ 도달 불가 단계로 손절이 잠기던 교착 해제 |
| `auto_add_margin_usdt` | `300` | 자동 증거금 추가액 |

#### 5-7. 제안(suggestion) 엔진

| 키 | 값 | 해설 |
|---|---|---|
| `suggestion_auto_execute_enabled` | `false` | ❌ **자동 실행 꺼짐** (제안만 하고 주문 안 냄) |
| `suggestion_confidence_threshold` | `0.85` | 자동 실행 최소 신뢰도 |
| `suggestion_daily_auto_limit` | `3` | 자동 실행 일일 한도 |
| `suggestion_auto_dismiss_hours` | `24` | 제안 자동 폐기 시간 |
| `suggestion_current_default_profile` | `safe` | 기본 프로필 |
| `suggestion_default_profiles` | (큰 JSON) | `safe` / `aggressive` / `conservative` 3종 프로필 정의 — UI 에서 편집 |

#### 5-8. 🤖 워커가 자동 생성하는 캐시 (사람이 편집하지 말 것)

| 키 | 정체 | 크기 |
|---|---|---|
| `learning_agent_insights` | 학습 에이전트 결과 JSON, 매시 갱신 (마지막 `2026-09-03 05:52`) | 수 KB |
| `pattern_learning_insights_v187` | 패턴 학습 결과 JSON (표본 2,395건), 매시 갱신 (`2026-09-03 06:52`) | 수십 KB |
| `post_liquidation_analysis_v212` | 청산 후 분석 JSON (`2026-08-21` 이후 갱신 없음) | 작음 |

> 새 환경으로 DB 를 옮길 때 이 3개는 **복사할 필요 없다.** 워커가 다시 채운다.

전체 목록을 새 PC 에서 다시 뜨는 명령 (거대 JSON 3개는 제외):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key,value from system_settings where length(value)<200 order by key\")).fetchall():
    print(f\"{k} = {v}\")
"'
```

---

### 6. `exchange_accounts` / `users` — 개수와 플래그만

VPS 실조회. **키 값은 읽지 않았고 존재 여부만 확인했다.**

| id | user_id | 거래소 | 시장 | 헤지모드 | 테스트넷 | 활성 | 계정별 손실한도 | api_key 있음 | secret 있음 | passphrase | 생성일 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | binance | usds_m_futures | ✅ | ❌ **mainnet** | ✅ **활성** | NULL (전역값 사용) | ✅ | ✅ | 없음 | 2026-04-25 |
| 2 | 2 | binance | usds_m_futures | ✅ | ✅ testnet | ❌ 비활성 | NULL | ✅ (더미 3자) | ✅ (더미) | 없음 | 2026-04-25 |

**→ 실제로 돈이 도는 계정은 `id=1` 하나뿐이다.**

`users` 테이블: 2명, 둘 다 `role=admin`, `is_active=true`, `timezone=Asia/Seoul`.
(id=1 은 `he***@gmail.com` = 사장님. id=2 는 이메일에 `@` 가 없는 값이라 마스킹 처리했다 — ⚠️ 정체 확인 못 함)

- `daily_loss_limit_usdt` 가 둘 다 NULL → 전역 `.env` 의 `DAILY_LOSS_LIMIT_USDT=0` 을 따르고, **0 이므로 일일 손실 한도가 비활성**이다 (`app/models/exchange_account.py:20-23`, `app/core/config.py:33`).

새 PC 에서 같은 조회를 하는 명령:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select id,user_id,is_testnet,is_active,(api_key_enc is not null) as has_key from exchange_accounts order by id\")).fetchall():
    print(dict(r._mapping))
"'
```

> 🚨 **함정**: `docker compose exec db psql` 로 조회하면 **빈 DB** 가 나온다. 실제 DB 는 외부 Neon 인데 로컬 `db` 컨테이너도 같이 떠 있기 때문이다 (`docker-compose.yml:2-16`, 컨테이너 `binance-auto-trader-db` 가 3주째 가동 중). 반드시 위처럼 **api 컨테이너의 앱 세션**으로 접근할 것.

---

### 7. 🚨 새 PC 이전 — 하면 안 되는 것 / 해야 하는 것

#### 7-1. 절대 하면 안 되는 것

| 🚨 | 왜 |
|---|---|
| **`.env` 를 채팅·이메일·텔레그램·깃에 붙여넣기** | `.gitignore:7-10` 이 `backend/.env` 를 막고 있지만, 사람이 손으로 붙여넣는 건 못 막는다 |
| **`ENCRYPTION_KEY` 를 새로 생성해서 기존 DB 에 붙이기** | DB 의 API 키가 즉시 복호화 불가가 된다. §3-3 |
| **새 PC 에서 `docker compose up -d` 를 그냥 실행** | 🚨 **로컬 `.env` 의 DATABASE_URL 이 운영 Neon 을 가리키고 ENCRYPTION_KEY 도 같다** → scheduler / user-stream 이 VPS 와 **동시에** 실계좌로 주문을 낸다. 중복 주문 사고. ⚠️ 지금 이 순간은 그 DATABASE_URL 의 **비밀번호가 만료돼 인증 실패**하는 덕에 우연히 막혀 있다 (§4-1 실측). **최신 DATABASE_URL 을 채워 넣는 순간 이 우연한 방어가 사라진다** |
| **`check_binance_key.py` 를 새 PC 에서 실행 / 출력을 캡처해 공유** | 🚨 초안은 「키 앞 10자」라고만 했는데 **틀렸다. API Key 앞 10자 + API Secret 앞 10자를 둘 다 찍는다** (`scripts/check_binance_key.py:38-39`, 실코드 확인). 게다가 이 스크립트는 **바이낸스에 실제로 서명 요청을 3번 보낸다**(ping / get_balance / get_account) → 화이트리스트에 없는 새 PC 에서 돌리면 **IP ban 위험**. §7-2b |
| **`key-rotation-backup-*.json` 을 방치** | 옛 암호문 전체가 들어있다. ⚠️ **`--dry-run` 만 돌려도 이 파일이 생긴다** (`rotate_encryption_key.py:274`) |
| **`rotate_encryption_key.py` 출력을 캡처해 공유** | 옛/새 `ENCRYPTION_KEY` 의 **앞 8자**를 화면에 찍는다 (`scripts/rotate_encryption_key.py:257-258`, `old_key head=… / new_key head=…`) |
| **`alembic upgrade head` 를 `.env` 확인 없이 실행** | 🚨 운영 Neon DB 에 DDL 이 걸린다. 되돌리는 스크립트가 없다. §7-2 ⑥ |
| **`rotate_encryption_key.py` 를 운영 DB 에 그냥 실행** | 🚨 VPS 컨테이너는 **옛 키를 메모리에 들고 있다** → DB 만 새 키가 되는 순간 실매매가 즉시 멈춘다. §3-3 (B) |
| **`git stash` / `git stash pop` 을 맨손으로 사용** | 🚨 이 저장소는 **worktree 를 공유**한다(`.claude/worktrees/…`). stash 는 저장소 전역이라 다른 worktree 의 작업까지 빨아들이고, `pop` 은 충돌 시 stash 를 남긴 채 반쯤 적용돼 되돌리기 어렵다. 임시 보관이 필요하면 `git stash` 대신 **브랜치를 하나 파서 커밋**할 것 |
| **`git reset --hard` / `git clean -fd` / `git push --force`** | 이 문서 어디에도 필요 없는 명령이다. `--hard` 는 `.env` 는 안 지우지만(`.gitignore` 대상) 미커밋 코드 변경을 **복구 불가**하게 날린다 |
| **VPS 에서 재시작·배포·설정변경** | 실자금이 돌고 있다. 이번 조사는 전부 읽기 전용으로 했다 |
| **VPS 의 `.env` 를 새 PC 에서 `scp` 로 덮어쓰기** | CRLF `.env` 를 VPS 에 올리면 값 끝에 `\r` 이 붙어 `DATABASE_URL`·`ENCRYPTION_KEY` 가 조용히 깨진다. ⚠️ **정정**: 이 저장소는 `core.autocrlf=true` 이지만 `.env` 는 `.gitignore:7` 로 깃 추적 대상이 아니라 **git 이 변환하지 않는다.** 실제로 사무실 `.env` 는 지금 **LF**(CR 0개, 실측)다. CRLF 는 **Windows 메모장 같은 편집기로 저장할 때** 생긴다 — 그쪽을 조심할 것. 확인: `file .env && grep -c $'\r' .env` |
| **비밀 값을 명령줄에 적기** — `NEW_ENCRYPTION_KEY="…" python …`, `psql "postgres://…:비번@…"` 같은 형태 | 그 줄이 `~/.bash_history` 에 **파일로 영구히 남고**, 실행 중에는 같은 서버의 `ps aux` 로 누구나 본다. ssh 로 보내면 **VPS 히스토리에도** 남는다. §3-3 (B) 의 파일 방식을 쓸 것 |
| **비밀 값을 Claude(나) 나 다른 AI 채팅창에 붙여넣기** | 이 문서를 만드는 동안 나는 `.env` 의 **값을 한 번도 읽지 않았다.** 앞으로도 값은 사장님만 다루신다. 진단에 필요한 건 값이 아니라 **지문**(§4)이다 |
| **`.env` 나 USB 사본을 OneDrive / 구글드라이브 같은 동기화 폴더에 두기** | 저장소 경로가 이미 사용자 폴더 밑(`C:\Users\user\…`)이다. 동기화 폴더 안으로 옮기면 `.gitignore` 와 **무관하게** 클라우드로 올라간다 |
| **터미널 출력을 그대로 캡처해 공유** | `.env` 를 실수로 `cat` 한 화면, `docker compose config`(→ `.env` 값을 전부 펼쳐 출력한다), `env` / `printenv` 출력이 전부 해당된다 |
| 🚨 **이 문서(`docs/handoff/2026-09-03/secrets.md`)를 커밋해서 push** | **저장소가 public 이다** (`"visibility": "public"` 실측). `docs/handoff/` 는 이미 추적되는 경로라 커밋하면 바로 공개된다. VPS IP·root SSH·**열린 redis**·해제된 안전장치가 전부 공개 문서가 된다. 문서 맨 위 경고 참고 |

#### 7-2. 새 PC 에서 로컬 스택을 굳이 띄워야 한다면

> ## 🚨🚨 먼저: 이 절의 초안에는 **치명적 오류**가 있었다 (검증에서 발견, 수정 완료)
>
> 초안은 「`.env.local-safe` 사본을 만들어 거기만 고치고 `docker compose up` 하라」고 했다.
> **그렇게 하면 안전해지지 않는다.** `backend/docker-compose.yml` 은 서비스마다
> `env_file: - .env` 로 **파일 이름이 박혀 있다** (`docker-compose.yml:31,45,58,74` — api/scheduler/user-stream/mark-price-stream 네 곳 전부).
> compose 는 `.env.local-safe` 를 **쳐다보지도 않는다.**
> → 사본을 만들고 「안전하게 바꿨다」고 믿은 채 `docker compose up -d` 하면
> **운영 Neon DB + 운영 ENCRYPTION_KEY 로 그대로 뜬다.** 위험 2·4 가 그대로 realize 된다.
>
> 실제로 갈아끼우려면 **`.env` 그 파일 자체를 바꿔야 한다.** 아래 절차를 그대로 따를 것.

**결론부터: 가장 안전한 선택은 「로컬 스택을 안 띄우는 것」이다.**
운영 화면은 VPS 의 `http://159.65.137.250:8000` 을 그대로 쓰면 된다. 새 PC 에서
코드만 편집하고 push 하는 것으로 충분하다. 아래는 **정말로 로컬 기동이 필요할 때만.**

> **전제: 새 PC 에 Docker 가 깔려 있어야 한다.** 이 문서의 `docker compose …` 는 전부
> **Docker Desktop for Windows** (WSL2 백엔드) 를 전제로 한다. 없으면 `bash: docker: command not found` 가 난다.
> 확인:
> ```bash
> docker --version && docker compose version
> ```
> 둘 다 버전이 찍히지 않으면 https://www.docker.com/products/docker-desktop/ 에서 설치하고 **Docker Desktop 을 실행한 상태**로 둔다 (앱이 꺼져 있으면 `error during connect` 가 난다).
> ⚠️ VPS 에 대고 치는 `ssh … docker compose …` 명령들은 **VPS 쪽 도커를 쓰므로 새 PC 에 Docker 가 없어도 된다.** §8 검증 체크리스트는 Docker 없이도 전부 돈다.

**① 운영 `.env` 를 먼저 백업한다 (되돌리기 지점)**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp -n .env .env.PROD-BACKUP && ls -l .env .env.PROD-BACKUP
```

`cp -n` 이라 이미 백업이 있으면 덮어쓰지 않는다. 두 파일이 **같은 크기**로 보여야 한다.

**② 로컬용 사본을 만들고 편집한다**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp .env .env.local-safe
```

`.env.local-safe` 를 편집기로 열어 아래 **네 줄**을 고친다. (초안은 두 줄만 시켰는데
부족하다 — 텔레그램·Sentry 를 그대로 두면 로컬 테스트 알림이 **운영 알림 채널로** 날아가
사장님이 실매매 알림과 구분할 수 없게 된다.)

- `DATABASE_URL=postgresql+psycopg2://postgres:<같은 파일의 POSTGRES_PASSWORD 값>@db:5432/binance_auto_trader`
- `APP_ENV=local`
- `TELEGRAM_BOT_TOKEN=` ← **빈 값으로**
- `SENTRY_DSN=` ← **빈 값으로**

> 🚨 **첫 줄의 비밀번호를 `postgres` 로 쓰면 안 된다** (초안이 그렇게 시켰는데 틀렸다).
> `docker-compose.yml:10` 이 db 컨테이너를 `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}` 로 띄운다 —
> 즉 **`.env` 에 있는 `POSTGRES_PASSWORD` 값**으로 postgres 가 초기화된다. 로컬 `.env` 에는 그 키가 실제로 들어 있다(§1-3 목록 6번).
> 새 PC 는 볼륨이 비어 있으니 그 값으로 처음 만들어지고, DSN 에 `postgres` 를 적으면 `password authentication failed` 가 난다.
> → **같은 `.env.local-safe` 파일 안의 `POSTGRES_PASSWORD=` 줄 값을 그대로 복사해 넣는다.**
> 값은 이 문서에 적지 않는다. 파일 안에서 복사·붙여넣기만 하면 되고, **화면에 출력할 필요도 없다.**
> (URL 에 넣을 때 `@ : / ? #` 같은 문자가 값에 있으면 퍼센트 인코딩이 필요하다. `token_urlsafe` 로 만든 값이면 그런 문자가 없어 그냥 붙이면 된다.)

`ENCRYPTION_KEY` 는 **그대로 둔다.** 형식이 틀리면 api 가 부팅 즉시 죽는다 (`main.py:46`).
로컬 DB 는 비어 있어 복호화할 대상 자체가 없으므로 위험하지 않다.

**③ `.env` 를 로컬용으로 실제 교체한다 — 이 단계를 빼면 ①②가 전부 무의미하다**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && cp .env.local-safe .env
```

**④ 🚨 교체가 진짜 됐는지 검증한다. 이 검증을 통과하기 전에는 어떤 compose/alembic 명령도 치지 말 것.**

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && n=$(grep -c "^DATABASE_URL=" .env); if [ "$n" -ne 1 ]; then echo "🚨 STOP: DATABASE_URL 줄이 $n 개다 (1개여야 한다) — 옛 줄을 지울 것"; elif grep "^DATABASE_URL=" .env | grep -q "neon.tech"; then echo "🚨 STOP: .env 가 아직 운영 Neon 을 가리킨다 — 여기서 멈출 것"; elif grep "^DATABASE_URL=" .env | grep -q "@db:5432/"; then echo "SAFE: .env 가 로컬 DB 를 가리킨다"; else echo "🚨 STOP: DATABASE_URL 이 로컬도 Neon 도 아니다 — 눈으로 확인할 것"; fi
```

`SAFE:` 가 나오지 않으면 **여기서 멈춘다.** `neon.tech` 가 한 글자라도 남아 있으면 안 된다.

> 줄 개수를 세는 이유: `.env` 에 `DATABASE_URL` 이 **두 줄** 남아 있으면(옛 줄을 지우지 않고
> 새 줄을 밑에 추가한 경우) 눈으로는 로컬로 바꾼 것처럼 보이는데, 어느 줄이 이기는지가
> 로더에 따라 달라진다. **한 줄만 남기는 것이 유일하게 확실하다.**

**⑤ 컨테이너를 띄운다 — `api` 만. `scheduler` / `user-stream` / `mark-price-stream` 은 띄우지 않는다**

`docker compose up -d` 를 **인자 없이 치면 9개 서비스가 전부 뜬다.** 반드시 이름을 지정한다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis api
```

**⑥ 스키마 생성 — alembic 은 `.env` 의 `DATABASE_URL` 을 그대로 따라간다**

> 🚨 **`alembic upgrade head` 는 읽기 명령이 아니라 DDL 이다.** ④ 검증을 건너뛰고 이걸 치면
> **운영 Neon DB 에 마이그레이션이 걸린다.** alembic 의 `downgrade` 는 이 프로젝트에서
> 한 번도 실행·검증된 적이 없으므로 **되돌릴 방법이 사실상 없다.**
> 아래는 컨테이너 안에서 접속 대상을 한 번 더 확인한 뒤에만 실행한다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.config import settings; h=settings.database_url.split('@')[-1]; print('TARGET =', h); assert 'neon.tech' not in h, 'STOP: 운영 DB 다'; print('OK: 로컬 DB')"
```

`OK: 로컬 DB` 가 찍힌 다음에만:

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head
```

참고: 2026-09-03 기준 운영 DB 의 alembic 버전 = `0034_surge_ladder`, 저장소 최신 마이그레이션 = `0034_surge_ladder_state.py`. **둘이 일치한다** → 지금 코드에는 운영에 미적용된 마이그레이션이 없다 (VPS 실조회로 확인).

**⑦ 끝나면 운영 `.env` 로 되돌린다 (롤백)**

로컬 실험이 끝나면 반드시 되돌려 놓는다. 안 되돌리면 다음에 이 폴더에서 무심코 친 명령이
**로컬 빈 DB** 를 보고 「데이터가 사라졌다」는 오진으로 이어진다.

```bash
cd "/c/Users/<사용자>/바이낸스/binance-auto-trader/backend" && docker compose down && cp .env.PROD-BACKUP .env && grep -c "neon.tech" .env
```

마지막 숫자가 `1` 이상이면 운영 `.env` 로 복구된 것이다.

> ## 🚨 `docker compose down` 은 **새 PC 안에서만** 친다
>
> 이 명령은 컨테이너를 **정지하고 삭제**한다. 같은 명령을 **VPS 에서 치면 실매매가 통째로 멈춘다**
> — api·scheduler·user-stream 이 다 내려가고, **열려 있는 포지션의 손절·익절이 나가지 않는다.**
> 이 문서에서 `docker compose down` 이 등장하는 곳은 **여기 한 곳뿐**이고, 앞의 `cd "/c/Users/…"`
> 가 반드시 붙어 있어야 한다.
>
> **ssh 창과 로컬 Git Bash 창을 헷갈리는 것이 이 사고의 실제 원인이다.** 치기 전에 한 번 확인:
> ```bash
> hostname   # 새 PC 이름이어야 한다. binance-trader-prod 가 나오면 VPS 다 — 즉시 멈출 것
> ```

> ⚠️ **이 §7-2 절차는 실제로 돌려보지 않았다** (VPS 읽기 전용 원칙 + 로컬 컨테이너 미기동).
> `env_file: - .env` 가 박혀 있다는 사실과 alembic/모듈 경로는 파일로 확인했지만,
> 기동 자체는 미검증이다.

#### 7-2b. 🚨 로컬 스택을 띄울 때의 바이낸스 IP ban 위험

`.env` 를 로컬 DB 로 갈아끼웠어도, **로컬 DB 에 실 API 키를 등록하면 안 된다.**

- 새 PC 의 공인 IP 는 바이낸스 API 키의 신뢰 IP 목록에 **없다** (§10 미확인 항목).
- 등록되지 않은 IP 에서 서명 요청을 보내면 전부 거부되고, 워커가 자동 재시도를 돌리면
  **418 / -1003 IP ban** 으로 번진다. 2026-08-26 에 실제로 발생한 사고다.
- 밴은 **키가 아니라 IP** 에 걸린다. 사무실·집 회선이 VPS 와 같은 NAT 를 타는 상황이면
  운영까지 영향을 받을 수 있다.

→ 로컬은 **테스트넷 키**(`is_testnet=True`)로만 붙이거나, 아예 거래소 계정을 등록하지 않고
UI/스키마만 확인한다.

#### 7-3. SSH 개인키 — 두 가지 방법

**방법 A (간단, 키 재사용)**: 사무실 PC 의 `~/.ssh/id_ed25519` 와 `id_ed25519.pub` 두 파일을 USB 로 새 PC 의 같은 경로에 복사.

```bash
ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub
```

> ⚠️ **Windows 에서는 `chmod` 가 진짜 관문이 아니다 — NTFS 권한(ACL)이 관문이다.** Git Bash 는 `ls -l` 에 `-rw-r--r--` (644) 로 보여주지만 그건 **흉내낸 표시**다. 2026-09-03 사무실 PC 실측: `icacls` 로 본 실제 권한은 `Administrators / SYSTEM / 본인` 세 주체뿐이라 충분히 잠겨 있고, **Git Bash 의 `ssh` 도 PowerShell 의 `ssh.exe` 도 둘 다 정상 접속된다.** 즉 지금 사무실 PC 는 문제가 없다.
>
> 문제는 **USB 를 거쳐 새 PC 로 복사할 때**다. 복사된 파일이 상위 폴더의 느슨한 ACL 을 물려받으면 Windows 기본 `ssh.exe` 가 `UNPROTECTED PRIVATE KEY FILE` 로 **접속을 거부**한다. 옮기자마자 **PowerShell 에서** 아래를 실행해 확실히 잠근다 (Git Bash 의 `chmod` 는 NTFS ACL 을 못 고치는 경우가 있다):
>
> ```powershell
> icacls "$env:USERPROFILE\.ssh\id_ed25519" /inheritance:r /grant:r "$env:USERNAME:(R)"
> icacls "$env:USERPROFILE\.ssh\id_ed25519"
> ```
>
> 두 번째 줄의 출력에 `Users` 나 `Everyone` 이 **없어야** 정상이다. Git Bash 만 쓴다면 아래도 같이 해두면 좋다:
>
> ```bash
> chmod 600 ~/.ssh/id_ed25519 && chmod 644 ~/.ssh/id_ed25519.pub && ls -l ~/.ssh/id_ed25519*
> ```
>
> 🚨 **개인키를 옮긴 USB 는 반드시 정리한다.** 이 파일 하나로 운영 서버 root 에 들어갈 수 있다. 복사가 끝나고 새 PC 접속이 확인되면 USB 의 사본을 지우고 휴지통도 비울 것. 클라우드 드라이브·이메일·채팅에 올리지 말 것.

**방법 B (더 안전, 새 키 발급)**: 새 PC 에서 새 키를 만들고 **공개키만** VPS 에 추가. 이건 VPS 에 쓰기 작업이라 **사장님이 직접** 하셔야 한다 (이번 세션은 VPS 읽기 전용).

> ## 🚨 방법 B 는 「서버에서 잠길 수 있는」 유일한 절차다 — 아래 3가지를 반드시 지킬 것
>
> 1. **기존 SSH 세션을 열어둔 채로 작업한다.** 새 키가 안 먹혀도 그 열린 창으로 되돌릴 수 있다.
>    작업이 끝나고 **새 창에서 새 키로 접속이 되는 걸 확인하기 전까지 그 창을 닫지 말 것.**
> 2. `authorized_keys` 에 넣을 때 **반드시 `>>` (추가)** 를 쓴다. **`>` (덮어쓰기) 를 쓰면 기존
>    `binance-trader-vps` 키가 지워져 사무실 PC 가 즉시 잠긴다.** 현재 등록된 키는 딱 1개라 여유가 없다.
> 3. 그래도 잠겼다면 마지막 수단은 **DigitalOcean 웹 콘솔**(Droplet → Access → Launch Droplet Console) 이다.
>    거기서 로그인하려면 **root 비밀번호**가 필요하다 — 🚨 **지금 그 비밀번호를 알고 계신지 이전 전에 미리 확인**하실 것.
>    모르면 콘솔에서 비밀번호 재설정이 필요하고, 그 사이 VPS 를 못 만진다 (매매는 계속 돌지만 손을 못 댄다).
>
> ⚠️ **방법 A 로 이미 키를 옮겼다면 방법 B 는 할 필요가 없다.** 둘 다 하지 말 것 —
> 아래 `ssh-keygen` 은 같은 경로(`~/.ssh/id_ed25519`)를 쓰므로 **방금 옮긴 키를 덮어쓸 수 있다**
> (덮어쓰기 전에 `Overwrite (y/n)?` 를 묻는다. **여기서 `y` 를 치면 옮겨온 키가 사라진다 — `n` 을 칠 것**).
> 굳이 둘 다 두려면 `-f ~/.ssh/id_ed25519_newpc` 처럼 **다른 파일명**을 쓴다.

새 PC 에서 키 생성:

```bash
ssh-keygen -t ed25519 -C "binance-trader-newpc" -f ~/.ssh/id_ed25519_newpc
```

접속 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'hostname && uptime'
```

`binance-trader-prod` 가 나오면 성공이다 (2026-09-03 실측 호스트명).

> ⚠️ **`-o StrictHostKeyChecking=no` 에 대해** — 이 문서의 모든 ssh 명령에 붙어 있다. 이건
> **서버 신원 확인을 끄는 옵션**이다. 새 PC 는 `known_hosts` 가 비어 있어서 첫 접속의
> 대화형 확인 프롬프트를 넘기려고 쓴 것이지, 안전해서 쓴 게 아니다.
> **첫 접속 한 번만 이 옵션을 쓰고, 그 뒤로는 떼는 것을 권한다.** 한 번 접속하면
> `~/.ssh/known_hosts` 에 서버 지문이 저장되어 다음부터는 옵션 없이 붙는다.
> 옵션을 계속 달고 다니면 **서버가 바뀌어도(= 중간자 공격이어도) 경고 없이 접속**한다 —
> root 로 들어가는 서버라 위험이 크다.

#### 7-4. GitHub

원격은 HTTPS 이고 credential helper 는 `manager` 다.

```bash
git -C /c/Users/<사용자>/바이낸스/binance-auto-trader remote -v
```

→ `https://github.com/herosys1-crypto/binance-auto-trader.git`
새 PC 첫 `git push` 때 Git Credential Manager 가 브라우저 로그인을 띄운다. **사장님이 직접 로그인**하시면 된다. PAT 를 파일에 적어둘 필요 없다.

---

### 8. 이전 후 검증 체크리스트

순서대로 실행. 하나라도 실패하면 다음으로 넘어가지 말 것.

> **전제 (이게 안 돼 있으면 ① 부터 전부 「파일 없음」으로 실패한다)**
> - **Git Bash 에서** 실행한다. `sha256sum`·`awk`·`grep` 은 PowerShell·cmd 에 없다 (PowerShell 대안은 §4 참고).
> - 저장소가 이미 새 PC 에 **clone** 돼 있어야 한다. 아직이라면 먼저:
>   ```bash
>   mkdir -p /c/Users/<Windows사용자명>/바이낸스 && cd /c/Users/<Windows사용자명>/바이낸스 && git clone https://github.com/herosys1-crypto/binance-auto-trader.git
>   ```
> - `backend/.env` 는 **깃에 없다**(`.gitignore:7`). clone 만으로는 생기지 않는다 — §4 의 방법으로 **직접 옮겨 놓은 뒤**에 ① 을 실행한다.
> - 아래 `<Windows사용자명>` 은 새 PC 의 로그인 계정명이다 (`echo $USERNAME`).
> - **clone 전에** 사무실 PC 와 같은 줄바꿈 설정을 맞춘다. 안 맞추면 전 파일이 diff 로 뜨거나
>   `.sh` 가 `bad interpreter: ^M` 으로 안 돈다 (§9-7b).
>   ```bash
>   git config --global core.autocrlf true
>   ```
> - ⚠️ **clone 한 새 PC 에서 `git push` 를 서두르지 말 것.** 운영 VPS 는 `main` 의 `ded22f3` 을
>   그대로 돌리고 있다(2026-09-03 실측). 새 PC 에서 실수로 옛 커밋을 올리면 다음 배포 때
>   운영 코드가 되돌아간다. push 전에 `git log -1` 로 HEAD 를 확인할 것.

**① `.env` 가 제대로 옮겨졌는지 (값을 보지 않고)**

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ {k=$1; v=substr($0, index($0,"=")+1); print k, (length(v)>0 ? "SET" : "EMPTY")}' .env
```

**② `ENCRYPTION_KEY` 지문이 `1728f1f33e3b` 인지**

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && printf '%s' "$(grep '^ENCRYPTION_KEY=' .env | cut -d= -f2-)" | sha256sum | cut -c1-12
```

`1728f1f33e3b` 가 아니면 **줄바꿈(CRLF) 오염을 먼저 의심할 것** — §4 의 마지막 경고 참고.

**②-b `ENCRYPTION_KEY` 길이가 44자인지 (Fernet 형식 즉시 확인)**

지문이 맞아도 이 검사를 한 번 더 한다. 44자가 아니면 **api 가 부팅과 동시에 죽는다** (`main.py:46`).

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && printf 'ENCRYPTION_KEY len=%s (44 여야 정상)\n' "$(grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\n\r' | wc -c)"
```

**②-c `DATABASE_URL` 이 실제로 붙는지 (이걸 안 재면 조용히 실패한다)**

지문·길이가 다 맞아도 **DB 비밀번호가 만료돼 있으면 아무것도 안 돈다.** 2026-09-03 사무실 PC 가 정확히 그 상태였다 (§4-1). 값은 화면에 찍지 않는다.

```bash
cd /c/Users/<사용자>/바이낸스/binance-auto-trader/backend && python -c "
import psycopg2
u=[l.split('=',1)[1].strip() for l in open('.env',encoding='utf-8') if l.startswith('DATABASE_URL=')][0]
try:
    c=psycopg2.connect(u.replace('postgresql+psycopg2://','postgresql://'), connect_timeout=15)
    c.cursor().execute('select 1'); c.close(); print('DB CONNECT_OK')
except Exception as e:
    print('DB CONNECT_FAIL:', 'AUTH_FAIL' if 'authentication' in str(e).lower() else type(e).__name__)
"
```

> ⚠️ **이 명령의 출력 문자열을 한글로 바꾸지 말 것.** Windows 콘솔 기본 인코딩이 `cp949` 라
> `python -c` 안에서 한글이나 `—` 같은 문자를 `print` 하면 실행 자체가
> `UnicodeEncodeError: 'cp949' codec can't encode character` 로 죽는다 (2026-09-03 실측).
> 그래서 위 출력은 전부 ASCII 다. (컨테이너 안에서 도는 명령은 UTF-8 이라 한글이 안전하다.)

판정:
- `DB CONNECT_OK` → 붙었다
- `DB CONNECT_FAIL: AUTH_FAIL` → **비밀번호 만료.** §4-1 대로 최신 `DATABASE_URL` 로 교체해야 한다
- `DB CONNECT_FAIL: OperationalError` → 네트워크·방화벽 문제 (Neon 은 5432/TCP 아웃바운드가 필요하다)
- `psycopg2` 가 없다는 오류(`ModuleNotFoundError`)가 나면: `pip install psycopg2-binary`
- 🚨 `DB CONNECT_OK` 가 나오면 **새 PC 가 운영 DB 에 붙은 것이다.** 여기서 `docker compose up -d` 를 치면 VPS 와 중복으로 실매매가 나간다 (§7-1). 확인만 하고 **컨테이너는 띄우지 말 것.**

**③ VPS SSH 접속**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'hostname'
```

**④ VPS 컨테이너가 전부 살아있는지**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
```

2026-09-03 조사 시점 기준 9개 컨테이너 전부 `Up`: api / scheduler / user-stream / mark-price-stream / db / redis / prometheus / grafana / db-backup.

**⑤ 암호화 키가 실제로 복호화하는지**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.crypto import validate_encryption_key; validate_encryption_key(); print(\"ENCRYPTION_KEY OK\")"'
```

**⑥ GitHub push 권한**

```bash
git -C /c/Users/<사용자>/바이낸스/binance-auto-trader ls-remote origin HEAD
```

**⑦ 🚨 마지막 — 「내가 이전하는 동안 실매매가 멀쩡했는가」**

①~⑥ 은 전부 「새 PC 가 준비됐는가」를 잰다. **운영이 상했는지는 안 잰다.**
이전 작업 전후로 이 한 줄을 돌려 **숫자가 늘고 있는지** 확인한다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"ACTIVE_STRATEGIES =\", db.execute(text(\"select count(*) from strategy_instances where status not in (\x27COMPLETED\x27,\x27STOPPED\x27,\x27CANCELLED\x27)\")).scalar())
print(\"LAST_ORDER_AT     =\", db.execute(text(\"select max(created_at) from orders\")).scalar())
"'
```

- `LAST_ORDER_AT` 이 **몇 시간째 그대로**면 매매가 멈춘 것이다. 조용히 멈추는 건 이 시스템의
  대표적 고장 양상이다 (§3-2). 이전 작업과 무관하게라도 즉시 원인을 찾아야 한다.
- 컨테이너 로그로 복호화 실패가 났는지 확인 (값은 안 찍힌다):
  ```bash
  ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 30m scheduler | grep -i "invalid token\|CryptoError" | tail -20'
  ```
  출력이 **비어 있어야 정상**이다. 뭔가 나오면 `ENCRYPTION_KEY` 불일치다 (§3-3 B 의 사고 양상).

✅ **이 쿼리는 실제로 돌려서 확인했다** (2026-09-03, 읽기 전용). 그때의 기준값:

```
ACTIVE_STRATEGIES = 24
LAST_ORDER_AT     = 2026-09-03 08:59:18+00:00   (UTC — KST 는 +9시간)
```

이전 작업 뒤에 다시 재서 `LAST_ORDER_AT` 이 **이 값보다 나중**이면 매매가 살아 있는 것이다.

---

### 9. 추가로 발견한 것 (이전과 직접 관계는 없지만 알아두실 것)

| # | 발견 | 근거 |
|---|---|---|
| 🚨 1 | **VPS `.env` 권한이 `-rw-r--r--` (644)** — 템플릿은 `chmod 600` 을 지시하고 있다. 루트 단독 서버라 실피해는 없지만 지시와 다르다 | VPS `ls -l .env` / `.env.production.template:7` (「3. chmod 600 .env」 — 초안의 `:4` 는 오기, 재확인함) |
| ⚠️ 2 | **VPS 에 `APP_ENV` 가 없어 `local` 로 운영 중** | `config.py:6` 기본값 |
| ⚠️ 3 | **`SENTRY_ENV=mainnet` 은 죽은 키** — 읽는 코드가 0곳 | `grep -rn "SENTRY_ENV\|sentry_env" backend/app/` 결과 없음 |
| ⚠️ 4 | 안전장치 4개가 사실상 해제 상태: `DAILY_LOSS_LIMIT_USDT=0`, `MIN_LIQUIDATION_DISTANCE_PCT=0`, `MAX_LEVERAGE=125`, `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=100` | VPS `.env` 실조회 |
| 🚨 5 | `ufw` 방화벽 **inactive** 인데 **redis 가 `6380:6379` = 0.0.0.0 바인딩이고 비밀번호가 없다**. compose 에 `requirepass` 가 없고 `REDIS_URL` 에도 비번이 없다 → 인터넷에서 `159.65.137.250:6380` 으로 **인증 없이 접속 가능**한 상태다. Redis 에는 mark price·kill-switch·재진입 대기 상태가 들어있다. 함께 0.0.0.0 인 것: api `8000`, prometheus `9090`. `127.0.0.1` 로 안전하게 묶인 것: db `5433`, grafana `3000` | VPS `ufw status` = inactive / VPS `docker-compose.yml:24,36,89` (2026-09-03 읽기 전용 재확인) |
| 🚨 5b | Grafana admin 비밀번호가 **`docker-compose.yml:98-99` 에 평문으로 깃에 커밋돼 있다** (사람이 정한, 사전에 나오는 약한 비번). **그리고 이 저장소는 public 이다** → 이미 **누구나 볼 수 있는 상태**다. `127.0.0.1:3000` 바인딩이라 인터넷에서 직접 두드릴 수는 없지만, 위험 5 로 서버에 발을 들이면 그대로 쓰인다. 🚨 **값은 이 문서에 옮겨 적지 않는다** — 필요하면 저장소의 해당 줄을 직접 볼 것. **조치: 비번을 바꾸고 `.env` 변수(`GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}`)로 빼서 compose 에서 지울 것** | `backend/docker-compose.yml:98-99` / GitHub API `"visibility": "public"` |
| ⚠️ 6 | `WALLET_LIMIT_PCT` 는 `config.py` 에 정의가 없고 `os.environ` 으로만 읽힌다. `settings_sync_worker` 가 매시간 `.env` 와 대조해 불일치 알림을 보낸다 | `app/services/capital_calculator.py:38`, `app/workers/settings_sync_worker.py:35-49` |
| ✅ 7 | ~~VPS `docker-compose.yml` 은 4011 bytes, 저장소 것은 4147 bytes. **내용이 다르다**~~ → 🚨 **이 주장은 틀렸다. 검증에서 반증됨.** 두 파일은 **내용이 완전히 같다.** 136 바이트 차이는 전부 **줄바꿈(CRLF vs LF)** 이다 — 정확히 136줄 × 1바이트. LF 로 정규화한 SHA-256 이 양쪽 `5fefef90b795…` 로 **일치**한다. VPS `git status`/`git diff` 도 깨끗하고 HEAD 가 `ded22f3` 로 저장소와 같다. **배포 담당이 이걸 쫓아다닐 필요 없다.** | 로컬 `tr -d '\r' < docker-compose.yml \| sha256sum` = VPS `sha256sum docker-compose.yml` = `5fefef90b795…` / 양쪽 `wc -l` = 136 / VPS `git status --porcelain` 무출력 |
| ⚠️ 7b | 위 오진의 **원인이 더 중요하다**: 이 PC 는 `git config core.autocrlf=true` 다. 체크아웃되는 모든 텍스트 파일이 **CRLF** 로 저장된다(compose 파일에 CR 282개 실측). → ① **`ls -l` 바이트 수로 로컬↔VPS 를 비교하면 안 된다**(항상 다르게 보인다). 비교는 `tr -d '\r' \| sha256sum` 으로. ② 새 PC 에도 같은 설정을 넣어야 diff 지옥이 안 생긴다. ③ **`scp` 로 파일을 VPS 에 직접 올리면 CRLF 가 딸려간다** — `.sh` 는 `bad interpreter: ^M`, `.env` 는 값 끝에 `\r`. VPS 로 코드를 옮길 땐 반드시 `git pull` 을 쓸 것 | `git config --get core.autocrlf` = `true` / `od -c \| grep -o '\\r' \| wc -l` = 282 |
| ℹ️ 8 | GitHub Actions 는 `sajangnim_sasang_audit.yml` 하나뿐이고 `secrets.*` 를 **전혀 쓰지 않는다** → CI 쪽 비밀 이전 작업 없음 | `grep -rn "secrets\." .github/workflows/` 결과 없음 |
| ℹ️ 9 | 깃에 추적되는 env 파일은 `backend/.env.example` 과 `backend/.env.production.template` 둘뿐 (둘 다 값 없음) | `git ls-files \| grep .env` |

---

### 10. ⚠️ 확인 못 함

| 항목 | 왜 확인 못 했나 |
|---|---|
| **바이낸스 API 키의 IP 화이트리스트에 어떤 IP 가 등록돼 있는지** | 바이낸스 계정 로그인이 필요하고, 이 세션은 금융 계정에 접속하지 않는다. VPS 공인 IP 는 `159.65.137.250` 하나로 확인됐다. 메모리에는 「2 IP」 기록이 있어 사무실 IP 도 등록돼 있을 가능성이 있다 — **사장님이 직접 바이낸스에서 확인**하실 것 |
| **바이낸스 키의 권한 설정** (Futures ON / 출금 OFF 여부) | 위와 동일 |
| ~~**`DATABASE_URL` 이 로컬과 VPS 에서 정확히 어디가 다른지**~~ | ✅ **해결됨 (2026-09-03 재조사)** — 조각별 지문 비교로 **비밀번호만 다르다**는 것, 그리고 사무실 쪽 비밀번호는 이미 **만료(AUTH_FAIL)** 라는 것까지 실측했다. §4-1 |
| **`users.id=2` 가 누구인지** | 이메일에 `@` 가 없는 값이라 마스킹만 하고 내용을 보지 않았다 |
| **Neon 콘솔 로그인 자격증명** | 조사 범위 밖. 사장님만 접근 가능 |
| **§7-2 로컬 스택 기동 절차가 실제로 동작하는지** | 로컬 컨테이너를 띄우지 않았다 (운영 DB 오접속 위험 회피). `env_file: - .env` 가 박혀 있다는 사실·alembic 대상·모듈 경로는 파일로 확인했지만 **기동 자체는 미검증** |
| ~~**VPS `docker-compose.yml` 과 저장소 버전의 구체적 차이**~~ | ✅ **해결됨 — 차이가 없다.** LF 정규화 SHA-256 이 양쪽 `5fefef90b795…` 로 동일. 「내용이 다르다」던 초안 주장은 **CRLF 오인**이었다. §9-7 |
| **§3-3 (B) 키 회전 절차가 실제로 동작하는지** | 운영 DB 에 쓰는 작업이라 이번 세션(읽기 전용)에서 **`--dry-run` 조차 돌리지 않았다.** 스크립트 코드와 자체 docstring 을 읽고 정리한 것이다. `docker compose exec --env-file` 지원 여부도 미검증 |
| **§8 ⑦ 의 「매매 살아있음」 판정 기준값이 정상 범위인지** | 쿼리는 실행해 확인했다(`ACTIVE_STRATEGIES=24`, `LAST_ORDER_AT=2026-09-03 08:59 UTC`). 다만 **이 숫자가 「정상」인지 아닌지는 판단하지 않았다** — 매매 판단은 사장님 영역 |
| **DigitalOcean 웹 콘솔 root 비밀번호를 사장님이 알고 계신지** | 계정 접근이 필요해 확인 불가. **SSH 가 잠겼을 때의 유일한 탈출구**이므로 §7-3 대로 **이전 전에 미리 확인**하실 것 |
| **새 PC 의 공인 IP** | 아직 그 PC 가 없다. 바이낸스 화이트리스트·Neon IP 제한에 영향이 있으니 세팅 후 확인 |


---

<a id="sec-4"></a>

## 4. 로컬 개발환경 재구축

새 PC(Windows)에서 이 저장소로 개발을 시작하기까지 필요한 모든 것.
아래 내용은 **옛 PC 에서 실제로 명령을 돌려 확인한 것**만 적었다. 확인하지 못한 것은 「⚠️ 확인 못 함」으로 표시했다.

---

### 0. 한 눈에 — 새 PC 에서 필요한 것

| # | 항목 | git clone 으로 따라오나 | 어디서 얻나 |
|---|---|---|---|
| 1 | 저장소 코드 | ✅ 따라옴 | `git clone` |
| 2 | Git / Python / Node / Docker | ❌ | 각 공식 설치본 (§1) |
| 3 | GitHub 인증 | ❌ | 브라우저 로그인 (Git Credential Manager, §2). ⚠️ **저장소가 public 이라 clone 엔 불필요** — 첫 `push` 때만 필요 (§2-3) |
| 4 | Python 패키지 (23개 + 전이) | ❌ | 🚨 **`pip install -r requirements.txt` 를 그냥 쓰지 마라** — 23개 중 핀이 3개뿐이라 옛 PC 와 다른 버전이 깔린다(`redis` 7→8 등). **§4-3 ②번의 고정 설치 명령**을 쓴다 |
| 5 | `backend/.env` (SECRET_KEY / ENCRYPTION_KEY / DB 접속) | ❌ **gitignore** | 옛 PC 에서 손으로 옮김 (§5) — 🚨 **이것 없으면 로컬 앱 안 뜸** / 🚨 **통째로 복사하면 안 된다** (옛 값의 `DATABASE_URL` 이 운영 Neon 을 가리킴, §5-4) |
| 6 | Claude Code 메모리 83개 | ❌ (저장소 밖) | `docs/handoff/memory-backup-2026-09-03/` — RESTORE 문서 참조 |
| 7 | `.claude/agents/` (impl·locator·mech) | ✅ **따라옴** | 클론하면 그대로 있음 (§10) |
| 8 | `.claude/settings.local.json` (권한 허용 목록) | ❌ **전역 gitignore** | 옛 PC 에서 손으로 옮김 (§10). ⚠️ **옛 PC 에 4개가 있고 내용이 다 다르다** (164/345/731/71건) — §10-2 |
| 9 | git worktree 4개 | ❌ | 새 PC 에선 **없는 게 정상**. 새로 만들면 됨 (§9) |
| 10 | 프런트엔드 빌드 산출물 | — | **빌드 없음**. 정적 파일 그대로 (§6) |

---

### 1. 사전 설치물

옛 PC 에서 실제로 돌아가던 버전 (`python --version` / `git --version` / `node --version` / `docker --version` 출력):

| 도구 | 옛 PC 실측 버전 | 새 PC 에서 |
|---|---|---|
| Python | **3.14.2** | 3.12 를 권장 — 이유는 아래 🚨 |
| pip | 26.1.1 | Python 에 딸려옴 |
| git | 2.53.0.windows.2 | 최신으로 무방 |
| node | v24.14.1 | **이 저장소는 node 를 안 쓴다** (§6). 다른 용도로만 |
| npm | 11.11.0 | 위와 같음 |
| Docker Desktop | 29.3.1 (build c2be9cc) | 로컬 DB/Redis 를 띄우려면 필요 |

🚨 **Python 버전이 세 곳에서 서로 다르다 — 이게 사고의 씨앗이다.**

| 어디 | Python | 근거 |
|---|---|---|
| 옛 로컬 PC | 3.14.2 | `python --version` 실측 |
| Docker 이미지 (VPS 운영) | **3.12** | `backend/Dockerfile:1` — `FROM python:3.12-slim` |
| GitHub Actions CI | **3.12** | `.github/workflows/sajangnim_sasang_audit.yml:21` — `python-version: "3.12"` |

로컬만 3.14 였다. 로컬에서 통과한 것이 운영(3.12)에서 통과한다는 보장이 없다.
**새 PC 에서는 3.12 로 맞추는 것을 권한다** — 그러면 로컬·CI·운영이 한 버전이 된다.

Python 설치: https://www.python.org/downloads/windows/ 에서 3.12.x 를 받는다.
설치 시 「Add python.exe to PATH」를 반드시 체크.

---

### 2. 저장소 클론 + GitHub 인증 (gh CLI 없이)

사장님은 `gh` CLI 를 쓰지 않는다 (메모리 `user_profile.md` — 「GitHub 웹 UI 만 사용」).
`gh` 는 **설치할 필요가 없다.** 인증은 Git 이 브라우저를 띄워서 처리한다.

옛 PC 의 git 설정 (`git config --show-origin --get ...` 실측):

| 설정 | 값 | **실제** 출처 (2026-09-03 재실측) |
|---|---|---|
| `remote.origin.url` | `https://github.com/herosys1-crypto/binance-auto-trader.git` | 저장소 로컬 |
| `credential.helper` | **`manager`** (Git Credential Manager) | **system** — `C:/Program Files/Git/etc/gitconfig` (Git 설치 기본값) |
| `core.autocrlf` | **true** | **system** — 같은 파일 (설치 기본값) |
| `user.name` | 이규수 | **전역**(`--global`) |
| `user.email` | herosys1@gmail.com | **전역** |
| `init.defaultBranch` | **`main`** | **전역** ← 손으로 넣은 것. system 기본값은 `master` 다 |
| `core.longpaths` | true | ⚠️ **전역이 아니다.** 아래 참조 |

🚨 **`credential.helper` 와 `core.autocrlf` 는 「전역 설정」이 아니라 Git 설치 기본값(system)이다.**
→ 새 PC 에 **Git 을 정상 설치하기만 하면 자동으로 붙는다. 따로 할 것이 없다.**

🚨 **옛 PC 의 `--global` 설정은 딱 3줄뿐이다** (`git config --global --list` 실측):
`user.name` / `user.email` / `init.defaultbranch=main`. **그러므로 §2-1 과 §2-2 만 하면 재현 끝이다.**

#### 2-1. git 사용자 정보 + 기본 브랜치 (새 PC 최초 1회)

```bash
git config --global user.name "이규수"
```

```bash
git config --global user.email "herosys1@gmail.com"
```

```bash
git config --global init.defaultBranch main
```

세 줄이 다 들어갔는지 확인 — 정확히 이 3줄이 나오면 옛 PC 와 같은 상태다:

```bash
git config --global --list
```

#### 2-2. 긴 경로 허용

```bash
git config --global core.longpaths true
```

⚠️ **정정**: 옛 PC 에서 이 값은 **전역에도, 메인 저장소에도 설정돼 있지 않았다**
(`git config --global --get core.longpaths` → 빈 출력 / exit 1. 실측).
유일하게 값이 있던 곳은 worktree 하나의 `.git/worktrees/<이름>/config.worktree` 였고
그건 Claude Code 가 worktree 를 만들면서 넣은 것이다.

**즉 이것이 없어도 옛 PC 는 정상적으로 clone·작업했다. 「빠뜨리면 클론이 깨진다」는 과장이었다.**
그래도 켜 두기를 권한다 — 이 저장소는 `.claude/worktrees/<긴이름>/backend/app/...` 처럼 경로가 깊어지고,
Windows 기본 260자 제한에 실제로 가까워지기 때문이다. 부작용은 없다.

#### 2-3. 클론

경로를 옛 PC 와 **똑같이** 두는 것을 권한다 (이유는 §3 과 RESTORE 문서 §1).

🚨 **먼저 새 PC 의 Windows 사용자명이 `user` 인지 확인한다.** 아래 명령들은 전부 `/c/Users/user/...` 로
박혀 있어서, 사용자명이 다르면 **엉뚱한 자리에 폴더가 생기고** 이후 모든 명령이 어긋난다:

```bash
echo "$HOME"
```

`/c/Users/user` 가 나오면 그대로 진행한다. **다른 이름이 나오면** 이 문서의 모든
`/c/Users/user/바이낸스/...` 를 그 이름으로 바꿔 읽어야 한다 (그리고 §3-2 를 읽는다).

```bash
mkdir -p "$HOME/바이낸스"
```

```bash
cd "$HOME/바이낸스" && git clone https://github.com/herosys1-crypto/binance-auto-trader.git
```

(`$HOME` 을 쓰면 사용자명이 무엇이든 「내 홈 아래 `바이낸스`」로 정확히 간다.
이후 절들은 읽기 쉽도록 `/c/Users/user/...` 를 그대로 쓴다 — 사용자명이 `user` 가 아니면 그 부분만 바꿔라.)

저장소가 public 이라 **clone 자체는 로그인 없이 조용히 끝난다** (아래 정정 상자).

**로그인이 실제로 필요해지는 시점은 첫 `git push` 다.** 그때 **Git Credential Manager 창이 뜬다**
→ 「Sign in with your browser」 → GitHub 웹으로 로그인 → 끝.
`gh auth login` 도, 토큰을 손으로 만들 필요도 없다. 한 번 로그인하면 Windows 자격 증명 관리자에 저장돼 다음부터 안 묻는다.

> # 🚨 정정 — 이 저장소는 **Private 이 아니라 Public 이다** (2026-09-03 실측)
>
> `GIT_SYNC_GUIDE.md:36` 은 「**Private** 선택 (반드시!)」이라고 적고 있지만 **현재 상태는 그렇지 않다.**
> 인증을 전혀 쓰지 않은 요청으로 확인했다 (GitHub 은 private 저장소를 미인증 요청에 **404** 로 숨긴다):
>
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" https://api.github.com/repos/herosys1-crypto/binance-auto-trader
> ```
>
> 결과 **`200`**, 그리고 응답 본문이 `"private": false`, `"visibility": "public"` 이었다.
>
> **① 새 PC 절차에 미치는 영향 — 좋은 쪽이다.**
> **clone 에는 GitHub 로그인이 필요 없다.** 아래 「Credential Manager 창이 뜬다」는
> **`git push` 를 처음 할 때** 해당된다. clone 이 로그인 없이 되더라도 고장이 아니다.
>
> **② 그러나 이건 별도로 판단이 필요한 사안이다.**
> 실자금이 도는 매매 시스템의 **전체 소스·전략 로직·기획서가 인터넷에 공개**돼 있다는 뜻이다.
> ✅ 비밀 값이 새어 나가지는 않았다 — 확인했다:
> `git log --all -- backend/.env .env` → **커밋 0건**,
> 트리에 있는 `.env` 계열은 값이 없는 `.env.example` · `.env.production.template` 둘뿐,
> 히스토리 전체에 `*.pem` · `*.key` · `id_rsa` 로 추가된 파일 **0건**.
> **즉 지금 당장의 유출 사고는 없다.** 다만 매매 규칙이 공개된 상태이므로
> **비공개로 바꿀지는 사장님이 결정할 사항**이다 (이 문서는 판단하지 않는다).
> 바꾸려면 GitHub → 저장소 → Settings → 맨 아래 Danger Zone → Change visibility.
> ⚠️ 비공개로 바꾸면 **VPS 가 `git pull` 할 때 인증이 필요해진다** — VPS 배포가 멈출 수 있으니
> 바꾸기 전에 VPS 쪽 인증 방식을 먼저 확인해야 한다.

#### 2-4. 클론 확인

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git log --oneline -3
```

2026-09-03 기준 `origin/main` 의 최신 커밋은
`e51d9a8 chore(handoff): 저장소 밖 자산을 저장소 안으로 — 새 PC 이전 대비` 다.
갓 clone 한 저장소라면 맨 윗줄이 이것이어야 한다.

이어서 이 세 줄이 나오는지도 본다 (`e51d9a8` 다음이 `ded22f3` = Fix 327):

```
e51d9a8 chore(handoff): 저장소 밖 자산을 저장소 안으로 — 새 PC 이전 대비
ded22f3 feat(Fix 327): 차트분석 전문가 에이전트팀 — 지지선 7점 판정을 진입에 배선
1d04598 fix(Fix 326): 남긴 10 USDT 를 다음 사이클이 죽이고 있었다
```

한글이 `\353\260\224...` 처럼 깨져 보이면 §3 함정 ② 대로 `git config --global core.quotepath false` 를 하면 된다.
**깨져 보이는 것과 실제 파일이 깨진 것은 다르다** — 표시 문제일 뿐이다.

---

### 3. 경로에 한글(「바이낸스」)이 들어간 것 — 문제인가

**결론: 프로그램 동작에는 문제가 없다. 다만 세 가지 함정이 있다.**

옛 PC 에서 실제로 이 경로로 pytest 1,766건과 FastAPI 앱 구동이 정상 동작했다.
Python·pip·pytest·FastAPI 모두 한글 경로를 문제없이 다뤘다.

| 함정 | 증상 | 대처 |
|---|---|---|
| ① Bash 에서 따옴표 없이 쓰면 깨진다 | `cd C:/Users/user/바이낸스/...` 가 실패 | **항상 따옴표로 감싼다**: `cd "C:/Users/user/바이낸스/..."` |
| ② git 출력에서 escape 로 보인다 | `git worktree list` 가 `"C:/Users/user/\353\260\224..."` 로 표시 | 표시만 그런 것. `git config --global core.quotepath false` 로 한글 그대로 볼 수 있다 |
| ③ 🚨 Claude Code 메모리 폴더 이름이 경로에서 자동 생성된다 | 경로가 바뀌면 **옛 메모리 83개를 못 읽는다** | §3-1 |

#### 3-1. 🚨 경로를 바꾸면 메모리가 끊긴다

Claude Code 메모리는 저장소 밖 `C:/Users/user/.claude/projects/<프로젝트키>/memory` 에 있고,
`<프로젝트키>` 는 **프로젝트 절대경로를 변환해 자동 생성**된다.

옛 PC: `C:\Users\user\바이낸스\binance-auto-trader` → 키 `C--Users-user------binance-auto-trader`

셈이 맞는지 보면 규칙이 보인다 — **`:` 와 `\` 도, 한글 한 글자도 각각 하이픈 하나**로 바뀐다:

| 원본 조각 | `C` | `:` | `\` | `Users` | `\` | `user` | `\` | `바`·`이`·`낸`·`스` | `\` | `binance-auto-trader` |
|---|---|---|---|---|---|---|---|---|---|---|
| 변환 | `C` | `-` | `-` | `Users` | `-` | `user` | `-` | `----` | `-` | `binance-auto-trader` |

→ `user` 뒤의 하이픈이 **6개**인 이유 = 구분자 1 + **「바이낸스」 4글자** 4 + 구분자 1.
(「3글자」가 아니다 — 바·이·낸·스 **4글자**다.)

경로를 `C:\dev\binance-auto-trader` 같은 영문으로 바꾸면 키가 달라져 옛 메모리 폴더를 안 읽는다.

💡 새 PC 에서 **실제 키가 무엇인지 직접 보는 것이 가장 확실하다.** Claude Code 를 그 폴더에서 한 번 띄운 뒤:

```bash
ls "$HOME/.claude/projects/"
```

**권장: 새 PC 도 같은 경로 `C:\Users\user\바이낸스\binance-auto-trader` 를 쓴다.**
(사용자명이 `user` 가 아니면 키가 달라지므로 §3-2)

경로를 꼭 바꾸고 싶으면 — 바꿔도 **개발은 정상 동작한다.** 잃는 것은 메모리 연결뿐이고,
그건 `docs/handoff/RESTORE-2026-09-03.md` §1 「방법 B」대로 새 폴더 이름을 확인해 복사하면 된다.

#### 3-2. ⚠️ 새 PC 의 Windows 사용자명이 `user` 가 아니면

경로가 `C:\Users\<다른이름>\바이낸스\...` 가 되므로 프로젝트 키도 달라진다.
→ 메모리는 RESTORE 문서 「방법 B」로 복원한다. **코드 쪽에는 영향 없다.**

✅ **전수 검색을 실제로 했다** (2026-09-03). 저장소 전체에서 `C:\Users\user` / `C:/Users/user` 를 찾은 결과
**소스·스크립트에는 한 건도 없다.** 걸린 5개 파일은 전부 `docs/handoff/2026-09-03/` 안의 이 핸드오프 문서들뿐이다.

추적 중인 실행 스크립트 4개(`backend/backup-db-for-home.bat`, `backend/home-pc-sync-from-office.bat`,
`backend/restore-from-home-backup.bat`, 루트 `home-pc-sync-from-office.bat`)는 전부
**`cd /d "%~dp0"` (스크립트 자기 위치 기준 상대경로)** 를 쓴다 — 사용자명이 달라도 그대로 돈다.
유일한 예외는 `backend/restore-from-home-backup.bat:7` 인데 그것도 `REM` **주석 한 줄**이라 동작에 영향이 없다
(게다가 `C:\Users\user\binance\...` 라는 옛 폴더명이라 이미 낡은 주석이다).

→ **새 PC 의 Windows 사용자명이 무엇이든 코드는 그대로 돈다.** 바뀌는 것은 메모리 폴더 키뿐이다.

---

### 4. backend 의존성 설치

의존성 파일은 **`backend/requirements.txt` 하나뿐이다.** `pyproject.toml` 은 **없다** (`ls backend/pyproject.toml` → 없음).

#### 4-1. 🚨 왜 버전 핀이 목숨줄인가 — 실제로 났던 사고

`backend/requirements.txt:1-8` 이 주석으로 사고 원인을 직접 적어 두었다:

> fastapi 가 핀 없어 재빌드 시 신버전 드리프트 → `include_router` 가 `app.routes` 에
> `.path` 없는 `_IncludedRouter` (라우트 중첩) 추가 → `prometheus-fastapi-instrumentator`
> 7.1.0 (`<8` 핀) 이 `route.path` 접근 시 **전 요청 500** (대시보드 전체 다운).

즉 **핀이 없던 패키지 하나가 올라가서 mainnet 대시보드가 전부 500** 이 됐다.
그래서 지금 핀이 걸린 것은 딱 3개뿐이다:

| 핀 걸린 것 | 핀 | 이유 |
|---|---|---|
| `fastapi` | `==0.135.3` | requirements.txt:7 — `_IncludedRouter` 없는 검증된 버전 |
| `starlette` | `==0.52.1` | requirements.txt:8 — fastapi 0.135.3 의 검증 조합 |
| `prometheus-fastapi-instrumentator` | `>=7.0.0,<8` | requirements.txt:27 |

**나머지 20개는 전부 핀이 없다.** 그래서 새 PC 에서 그대로 설치하면 옛 PC 와 다른 버전이 깔린다.

#### 4-2. 🚨 실측 — 지금 설치하면 이만큼 달라진다

`pip install --dry-run --ignore-installed -r requirements.txt` 를 **실제로 돌려** 나온 결과와
옛 PC 의 `pip freeze` 를 비교했다:

| 패키지 | 옛 PC (동작 확인됨) | 오늘 새로 깔면 | 차이 |
|---|---|---|---|
| **redis** | **7.4.0** | **8.1.0** | 🚨 **메이저 1단계 점프** |
| **websockets** | **16.0** | **17.1** | 🚨 메이저 1단계 |
| **cryptography** | **46.0.7** | **50.0.1** | 🚨 메이저 4단계 — ENCRYPTION_KEY(Fernet) 를 다루는 패키지 |
| uvicorn | 0.44.0 | 0.52.4 | 마이너 8단계 |
| pydantic | 2.12.5 | 2.13.5 | 마이너 1단계 |
| pydantic-settings | 2.14.0 | 2.15.0 | 마이너 1단계 |
| SQLAlchemy | 2.0.49 | 2.0.52 | 패치 |
| alembic | 1.18.4 | 1.19.1 | 마이너 |
| APScheduler | 3.11.2 | 3.11.3 | 패치 |
| PyJWT | 2.12.1 | 2.13.0 | 마이너 |
| requests | 2.33.1 | 2.34.2 | 마이너 |
| sentry-sdk | 2.58.0 | 2.68.1 | 마이너 10단계 |
| prometheus_client | 0.25.0 | 0.26.0 | 마이너 |
| pytest | 9.0.3 | 9.1.1 | 마이너 |
| python-multipart | 0.0.26 | 0.0.32 | 패치 6단계 |
| websocket-client | 1.9.0 | 1.9.2 | 패치 |
| fastapi / starlette / instrumentator / psycopg2-binary / passlib / httpx / bcrypt / email-validator | 동일 | 동일 | ✅ 핀 or 우연히 일치 |

**`redis` 7 → 8 은 메이저 버전 변경이다.** 이 시스템은 Redis 에 락·kill-switch·mark price 캐시·
health heartbeat 를 전부 걸어 두고 있다(`backend/app/main.py:24-25`, `docker-compose.yml:69-80`).
아무 검증 없이 8.x 로 올린 채 실자금을 돌리는 것은 fastapi 사고와 같은 종류의 위험이다.

**🚨 `websockets` 는 §4-3 ②번 고정 설치 명령에도 핀이 없다 — 그래도 괜찮은 이유:**
바이낸스 스트림 워커 2종은 `websockets` 가 아니라 **`websocket-client`** 를 쓴다
(실측: `app/workers/binance_user_stream_consumer.py:3` 과 `app/workers/mark_price_stream_consumer.py:28`
둘 다 `import websocket`. 저장소 전체에서 `import websockets` 는 **0건**).
그리고 `websocket-client` 는 ②번 명령에 `==1.9.0` 으로 **핀이 걸려 있다.**
`websockets` 는 `uvicorn[standard]` 가 딸려 오는 전이 의존성일 뿐이라 **실거래 경로에 없다.**
→ 위 표의 「websockets 🚨 메이저」는 **우선순위가 낮다.** 진짜로 신경 쓸 것은 `redis` 와 `cryptography` 다.

#### 4-3. 권장 절차 — 옛 PC 버전 그대로 재현

**① 가상환경을 만든다** (옛 PC 는 venv 없이 전역에 깔려 있었고, 전역에 anthropic·openai·pandas 등
저장소와 무관한 패키지가 118개 섞여 있었다 — 새 PC 에선 분리하는 편이 낫다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m venv .venv
```

`.venv/` 는 `.gitignore:55` 에 이미 들어 있어 커밋될 걱정이 없다 (`grep -n '\.venv' .gitignore` 로 확인 가능).

```bash
source "/c/Users/user/바이낸스/binance-auto-trader/backend/.venv/Scripts/activate"
```

⚠️ Windows 라서 `bin/activate` 가 아니라 **`Scripts/activate`** 다. PowerShell 이면 대신 이것:

```powershell
& "C:\Users\user\바이낸스\binance-auto-trader\backend\.venv\Scripts\Activate.ps1"
```

(PowerShell 이 스크립트 실행을 막으면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 를 한 번 실행한다.)

🚨 **가상환경은 터미널마다 다시 켜야 한다.** 새 창을 열 때마다 위 `source` 를 다시 돌린다.
지금 venv 안에 있는지 확인 — `.venv` 경로가 나와야 한다:

```bash
python -c "import sys; print(sys.prefix)"
```

**② 옛 PC 와 같은 버전으로 고정 설치** (아래를 그대로 붙여넣는다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip install fastapi==0.135.3 starlette==0.52.1 uvicorn[standard]==0.44.0 python-multipart==0.0.26 sqlalchemy==2.0.49 alembic==1.18.4 psycopg2-binary==2.9.12 pydantic==2.12.5 pydantic-settings==2.14.0 PyJWT==2.12.1 bcrypt==5.0.0 "passlib[bcrypt]==1.7.4" requests==2.33.1 email-validator==2.3.0 websocket-client==1.9.0 pytest==9.0.3 httpx==0.28.1 cryptography==46.0.7 APScheduler==3.11.2 redis==7.4.0 prometheus-fastapi-instrumentator==7.1.0 prometheus-client==0.25.0 "sentry-sdk[fastapi]==2.58.0"
```

✅ **이 23개 핀이 Python 3.12 에서도 되는지 실제로 확인했다** (2026-09-03).
`pip download --python-version 3.12 --only-binary=:all: --platform win_amd64` 로 위 목록 전부를 받아본 결과
**전이 의존성까지 합쳐 54개 wheel 이 모두 존재**하고 해석에 실패한 것이 하나도 없다
(`cryptography-46.0.7-cp311-abi3-win_amd64.whl`, `psycopg2_binary-2.9.12-cp312-cp312-win_amd64.whl`,
`pydantic_core-2.41.5-cp312-cp312-win_amd64.whl`, `redis-7.4.0-py3-none-any.whl` 등).
→ **3.12 로 새 PC 를 맞춰도 이 명령은 그대로 돈다.** 컴파일러(Visual C++ Build Tools) 도 필요 없다.

**③ (대안) 최신으로 그냥 깔고 싶다면** — 되긴 하지만 위 표의 차이를 감수한다는 뜻이다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip install -r requirements.txt
```

**④ 설치 확인** — 핀 3종이 정확히 맞는지:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && pip freeze | grep -iE "^(fastapi|starlette|prometheus-fastapi-instrumentator|redis|cryptography)=="
```

②번(고정 설치)으로 깔았다면 정확히 이 5줄이 나온다 (옛 PC 에서 이 명령을 실제로 돌려 확인한 출력):

```
cryptography==46.0.7
fastapi==0.135.3
prometheus-fastapi-instrumentator==7.1.0
redis==7.4.0
starlette==0.52.1
```

③번(최신 설치)으로 깔았다면 `redis`·`cryptography` 두 줄이 다르게 나온다 — 그건 §4-2 표의 차이를 감수했다는 뜻이다.

> 💡 이 사고를 영구히 막으려면 `requirements.txt` 를 전부 `==` 로 고정하는 것이 정답이다.
> 다만 그건 **코드 변경**이라 이번 조사 범위 밖이다. 새 PC 에서 정상 동작을 확인한 뒤 사장님이 결정하시면 된다.

#### 4-4. requirements.txt 에 **없는데** 쓰이는 패키지

| 패키지 | 어디서 | 언제 필요 |
|---|---|---|
| `anthropic` | `tools/batch/run.py:59` (`import anthropic`, 없으면 `sys.exit`) | 배치 실행기(Fix 292)를 쓸 때만. 앱 구동·테스트에는 불필요 |

```bash
pip install anthropic
```

`tools/batch/run.py:74` 이 안내하듯 `console.anthropic.com → API Keys` 에서 키를 받아
`ANTHROPIC_API_KEY` 환경변수로 넣는다. (🚨 키 값은 이 문서에 적지 않는다.)

🚨 이 키도 **명령줄에 직접 적지 마라** (`ANTHROPIC_API_KEY=sk-... python ...` 형태). `.bash_history` 와
터미널 스크롤백에 그대로 남는다. Windows 사용자 환경변수(시스템 속성 → 환경 변수)에 등록하는 편이 안전하다.

---

### 5. `backend/.env` — 🚨 clone 으로 절대 안 따라온다

`git check-ignore -v backend/.env` 실측 → `.gitignore:7:backend/.env` 에 걸린다. **커밋된 적 없고 앞으로도 없다.**

옛 PC 에는 `C:/Users/user/바이낸스/binance-auto-trader/backend/.env` 가 **36줄**로 존재했다.
(주의: **worktree 안에는 `.env` 가 없다.** 메인 저장소 폴더에만 있다.)

#### 5-1. 옛 PC `.env` 에 들어 있던 키 이름 (값은 적지 않음)

`grep -oE "^[A-Za-z_0-9]+=" backend/.env` 실측 — 22개:

| 키 | 새 PC 에서 어떻게 얻나 | 🚨 |
|---|---|---|
| `ENCRYPTION_KEY` | **반드시 옛 PC 와 똑같은 값**을 옮긴다 | 🚨 **잃으면 DB 안의 거래소 API 키를 영영 복호화 못 한다** — 구체적으로 `exchange_accounts` 테이블의 `api_key_enc` / `api_secret_enc` 두 컬럼(`backend/app/models/exchange_account.py:13-14`)이 Fernet 으로 암호화돼 있어 **이 키 없이는 복구 수단이 전혀 없다**. 바이낸스에서 키를 새로 발급받아 재등록하는 것 말고는 방법이 없다 (`DEV-WORKFLOW.md:28`) |
| `SECRET_KEY` | 옛 PC 값을 옮긴다 | 다르면 기존 JWT 토큰이 전부 무효 → 재로그인 필요 |
| `DATABASE_URL` | 🚨 **옛 PC 값을 그대로 복사하지 마라.** 로컬 개발용으로 §5-3 표의 `localhost:5433` 값을 **새로 적는다** | 🚨 **실측 확인: 옛 PC 의 이 값은 운영 Neon DB 를 가리키고 있다.** 그대로 옮기면 새 PC 로컬 앱이 **실자금 DB 에 직접 붙는다** (§5-3) |
| `TEST_DATABASE_URL` | 위와 같음 (옛 PC 값은 docker 내부 호스트 `db:5432` 라 호스트에서는 안 통한다) | |
| `REDIS_URL` | 로컬이면 `redis://localhost:6380/0` (§5-3) | |
| `POSTGRES_PASSWORD` | docker-compose 의 db 비번. 로컬 개발은 `postgres` 로 충분 | `docker-compose.yml:10` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 옛 PC 값 (텔레그램 BotFather) | 비워두면 알림만 안 감 |
| `SENTRY_DSN` / `SENTRY_TRACES_SAMPLE_RATE` / `SENTRY_PROFILES_SAMPLE_RATE` | Sentry 프로젝트 설정 화면 | 비워도 동작 |
| `APP_NAME` / `APP_ENV` / `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | `.env.example` 값 그대로 | |
| `BINANCE_FUTURES_BASE_URL` / `BINANCE_FUTURES_TESTNET_BASE_URL` | `.env.example` 값 그대로 | |
| `ENABLE_METRICS` | `true` | |
| `ALLOWED_SYMBOLS_CSV` / `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` / `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` / `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | 운영 정책값 | 없으면 `config.py` 기본값 |

값이 없는 뼈대는 저장소 안에 있다 — **이 두 파일은 커밋돼 있어서 clone 으로 따라온다**:

- `backend/.env.example` (29줄, 값 없음 — `.gitignore:9` 의 `!backend/.env.example` 로 예외 허용)
- `backend/.env.production.template` (119줄, `.gitignore:10` 로 예외 허용) — 운영용 키 **26개**
  (`grep -cE "^[A-Za-z_0-9]+=" backend/.env.production.template` → **26**. 로컬 개발에는 안 쓴다 — 참고용)

#### 5-2. `.env` 만들기

> 🚨 **맨손 `cp .env.example .env` 는 위험하다 — 이미 있는 `.env` 를 아무 말 없이 덮어쓴다.**
> USB 로 옮겨 온 `ENCRYPTION_KEY` 를 이미 `.env` 에 넣어 둔 상태에서 이걸 치면
> **그 키가 그 자리에서 사라진다.** `.env` 는 gitignore 라 git 으로 되살릴 수도 없다.
> 아래처럼 **`-n`(덮어쓰지 않음)** 을 붙여 쓴다.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && cp -n .env.example .env && echo "새로 만들었다" || echo "이미 .env 가 있다 — 덮어쓰지 않았다 (정상)"
```

그다음 `.env` 를 편집기로 열어 옛 PC 값(특히 `ENCRYPTION_KEY`, `SECRET_KEY`)을 채운다.

⚠️ **`.env.example` 은 18개 키뿐이다. 옛 PC `.env` 는 22개다** (양쪽 다 `grep -cE "^[A-Za-z_0-9]+=" ...` 로 실측).
`cp` 만 하면 아래 **4개가 비어 있는 상태**가 된다 — `.env.example` 에 아예 없는 키들이다:

| 빠지는 키 | `app/core/config.py` 기본값 | 비워둬도 되나 |
|---|---|---|
| `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` | `10` (`config.py:38`) | ✅ 된다 |
| `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE` | `None` = 제한 없음 (`config.py:41`) | ✅ 된다 |
| `ALLOWED_SYMBOLS_CSV` | `None` = 모든 심볼 허용 (`config.py:44`) | ✅ 된다 |
| `ALLOW_DUPLICATE_SYMBOL_STRATEGIES` | `False` (`config.py:62`) | ✅ 된다 |

**넷 다 `config.py` 에 기본값이 있어서 없어도 앱은 정상 기동한다.** 다만 §11 체크리스트의
「`.env` 22개 키」는 **옛 PC `.env` 를 그대로 참고해 채웠을 때의 숫자**다.
`cp .env.example .env` 로 시작했다면 **18 이 나오는 것이 정상**이니 놀라지 마라.
운영과 똑같은 정책값을 쓰고 싶으면 옛 PC `.env` 에서 이 4줄만 보고 옮겨 적으면 된다 (비밀 값 아님).

🚨 **`.env` 파일을 통째로 복사하지 마라.** 옛 PC 의 `.env` 는 `DATABASE_URL` 이 **운영 Neon DB** 를 가리키고 있다(실측). 통째로 덮으면 새 PC 로컬 앱이 실자금 DB 에 붙는다. **옮길 값과 옮기면 안 되는 값을 나눠서** 손으로 채운다 — §5-4 표.

🚨 **`ENCRYPTION_KEY` 를 새로 만들면 안 된다.** 새로 만들면 DB 에 암호화 저장된 바이낸스 API 키를 못 읽는다.
옮기는 방법은 §5-4 를 따른다. **채팅·이메일·카톡 전송 금지**(`DEV-WORKFLOW.md:29`).

새 키가 정말 필요한 상황(= 처음부터 다시 세팅)일 때만:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

이 명령은 `backend/app/core/crypto.py:22` 가 오류 메시지로 직접 안내하는 것과 같다.
`app/main.py` 는 기동 시 `validate_encryption_key()` 를 호출해 **잘못된 키면 즉시 죽는다**
(`crypto.py:12-30` — 「첫 거래 시점에 crash 방지」).

#### 5-3. 🚨 로컬 개발용 DATABASE_URL — 값에 따라 실자금 DB 를 건드린다

`.env.example:13` 의 기본값은 `postgresql+psycopg2://postgres:postgres@db:5432/binance_auto_trader` 로,
호스트명이 `db` = **docker 컨테이너 안에서만** 통한다.

| 어디서 앱을 돌리나 | DATABASE_URL 호스트 | REDIS_URL |
|---|---|---|
| docker compose 안 (api 컨테이너) | `db:5432` | `redis://redis:6379/0` |
| Windows 호스트에서 직접 (`uvicorn`) | `localhost:5433` ← 🚨 **5432 아님** | `redis://localhost:6380/0` ← 🚨 **6379 아님** |

포트가 다른 이유: `docker-compose.yml:14` 가 `127.0.0.1:5433:5432`,
`docker-compose.yml:24` 가 `6380:6379` 로 매핑한다 (호스트 포트 충돌 방지).

🚨 **운영 DB(Neon) 주소를 로컬 `.env` 에 넣지 마라.** 로컬에서 워커를 실수로 띄우면
실자금 포지션에 명령이 나갈 수 있다. `DEV-WORKFLOW.md:23` 도 「mainnet 운영 시: 한 시점에 한 PC 에서만 `docker compose up`」을 못 박고 있다.

#### 5-4. 🚨 비밀 값을 새 PC 로 안전하게 옮기는 법

**이 문서에는 비밀 값이 한 개도 적혀 있지 않다. 앞으로도 적지 마라.**
아래는 「어느 값을 / 어떻게」 옮기는지만 정리한 것이다.

**① 무엇을 옮기고 무엇을 옮기지 않나** (옛 PC `.env` 22개 키를 실제로 분류했다 — 값은 보지 않고 호스트/길이만 확인):

| 분류 | 키 | 새 PC 에서 |
|---|---|---|
| 🔴 **반드시 그대로 옮긴다** | `ENCRYPTION_KEY` | 잃으면 복구 불가 (§5-1). 옛 PC 값 그대로 |
| 🟡 옮기면 편하다 | `SECRET_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 안 옮겨도 앱은 뜬다. SECRET_KEY 가 다르면 재로그인, 텔레그램은 알림만 안 감 |
| 🔵 **옮기지 말고 새로 적는다** | `DATABASE_URL` / `TEST_DATABASE_URL` / `REDIS_URL` | 🚨 옛 값은 **운영 Neon / docker 내부 호스트**다. §5-3 표의 `localhost:5433` · `localhost:6380` 으로 **손으로 적는다** |
| ⚪ 그냥 `.env.example` 값 | 나머지 (`APP_*` / `JWT_*` / `BINANCE_*` / `ENABLE_METRICS` / `POSTGRES_PASSWORD` 등) | 복사할 필요 없음 |
| ⚫ 비어 있음 | `SENTRY_DSN` | 옛 PC 에서도 비어 있었다. 그대로 비워둔다 |

**② 옮기는 경로 — 해도 되는 것 / 절대 안 되는 것**

| ✅ 써도 되는 방법 | ❌ 절대 금지 |
|---|---|
| 비밀번호 관리자 (1Password 등) — `DEV-WORKFLOW.md:27` 이 권하는 방식 | 채팅·이메일·카톡·메신저 (`DEV-WORKFLOW.md:29`) |
| USB 로 직접 들고 가서 손으로 입력 | **Claude/ChatGPT 대화창에 붙여넣기** — 대화 기록에 영구히 남는다 |
| 옛 PC 화면을 보고 새 PC 에 타이핑 | OneDrive·Dropbox·Google Drive 등 **클라우드 동기화 폴더**에 `.env` 복사 |
| | GitHub 저장소·Gist·이슈·PR 본문 |
| | `ENCRYPTION_KEY=... 명령` 처럼 **명령줄에 직접 적기** — `.bash_history` 와 터미널 스크롤백에 남는다 |

> 🚨 `C:\Users\user\` 아래가 OneDrive 로 동기화돼 있는 PC 가 흔하다. USB 를 쓸 거면 옮긴 **직후 USB 에서 지우고 휴지통까지 비운다.**

**③ 🚨 옛 PC 를 정리하기 전에 `ENCRYPTION_KEY` 를 백업해라**

지금 이 키는 **옛 PC 의 `backend/.env` 단 한 곳에만** 있다. VPS 에도 있지만 옛 PC 를 밀거나
디스크가 죽으면 사실상 단일 장애점이다. `DEV-WORKFLOW.md:28` 이 「Mainnet 운영자는 백업 필수」라고 못 박고 있다.
**새 PC 세팅을 시작하기 전에** 비밀번호 관리자에 먼저 넣어라.

**④ 값을 보지 않고 옮겨졌는지 확인하는 법**

지문(해시 앞 12자)만 비교하면 값을 화면에 띄우지 않고도 두 PC 가 같은지 알 수 있다.
**옛 PC 와 새 PC 에서 각각 돌려 출력이 같으면 성공이다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | sha256sum | cut -c1-12
```

길이만 빠르게 보고 싶으면 (정상값은 **44**):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | wc -c
```

**⑤ 새 `.env` 가 운영 DB 를 안 가리키는지 마지막 확인** — 앱을 띄우기 전에 반드시:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -c "neon.tech" .env
```

**`0` 이 나와야 한다.** `0` 이 아니면 멈추고 `DATABASE_URL` 을 §5-3 표대로 고친다.

> ⚠️ 위 명령은 **「운영 호스트가 없다」를 확인하는 부정형**이라 약하다. 운영 DB 호스트가 `neon.tech` 가
> 아닌 다른 이름으로 바뀌면 `0` 이 나와도 안전하지 않다.
> **「로컬을 가리킨다」를 확인하는 긍정형**을 같이 돌려라 (§8-3 ①번과 같은 명령):
>
> ```bash
> cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -qE '^DATABASE_URL=postgresql\+psycopg2://[^@]*@(db|localhost|127\.0\.0\.1):' .env && echo "OK - 로컬 DB 다." || echo "!!! 중단 !!! 로컬 DB 가 아니다."
> ```
>
> **두 명령이 모두 통과해야 앱을 켠다.**

---

### 6. 프런트엔드 — 빌드가 없다

**결론: 빌드 단계가 없다. node/npm 이 필요 없다.**

근거:

- 저장소 어디에도 `package.json` 이 없다 (`find . -name package.json -not -path "*/node_modules/*"` → **0건**)
- 화면은 `backend/app/static/` 아래 **정적 HTML + 순수 JS** 다
  - `index.html` 218,684 bytes (대시보드 본체) 외 **8개** 페이지 — `analysis.html` / `bb-breakdown-ranking.html` /
    `bb-middle-ranking.html` / `bb-reversal-ranking.html` / `learning-insights.html` /
    `multi-timeframe-ranking.html` / `pump-ranking.html` / `realtime-monitor.html`
    (`git ls-tree --name-only origin/main backend/app/static/ | grep '\.html$'` → **9개**, index 포함)

    ⚠️ 옛 PC 의 worktree 에서 `ls` 를 하면 `perp-terminal.html` 이 하나 더 보인다. 그건 **아직 커밋 안 된
    작업 중인 파일**이라 새 PC 의 clone 에는 **따라오지 않는다**. 「파일이 하나 없다」고 놀라지 마라.
  - `backend/app/static/js/` 아래 **43개 `.js` 파일** (`strategies-list.js` 94KB, `strategy-suggestions.js` 95KB 등)
- FastAPI 가 직접 서빙한다. 경로 3개가 이렇게 나뉜다 (`main.py` 실측):

  | 위치 | 하는 일 |
  |---|---|
  | `main.py:164` | `app.mount("/static", _NoCacheStaticFiles(...))` — `js`·`css` 등 정적 자산 |
  | `main.py:166` `/admin-ui` | `index.html` 을 읽어 `?v=` 자산 버전을 **내용 해시로 갈아 끼운 뒤** `HTMLResponse` 로 돌려준다 (`:179`) |
  | `main.py:187` `/` | `RedirectResponse(url="/admin-ui")` — **307 리다이렉트**. HTML 을 직접 돌려주지 않는다 (§8-1) |

  ⚠️ `main.py:186` 의 `FileResponse` 는 **정상 경로가 아니라** 버전 재작성이 실패했을 때의
  fail-open 폴백이다 (`except Exception` 안에 있다). 평소에는 실행되지 않는다.

즉 **JS 를 고치면 저장하는 즉시 반영**된다. 트랜스파일·번들링·`npm install` 어느 것도 없다.

관련 함정: `main.py:93` 의 `_NoCacheStaticFiles` 가 캐시 금지 헤더를 붙인다(Fix 199).
과거 `?v=` 쿼리 18개가 낡아 옛 JS 가 뜨던 사고가 있었고, 지금은 **내용 해시 자동화**로 바뀌었다
(`main.py:2` 의 `hashlib` 임포트 + `:159` `_rewrite_asset_versions()` 가 그 구현이다).

⚠️ `--reload` 는 **`.py` 변경만** 감시한다. `index.html`·`js` 를 고쳤을 때는 서버 재시작이 필요 없고
**브라우저 새로고침만** 하면 된다 (위 no-cache 헤더 + 해시 재작성 덕분에 강력 새로고침도 대개 불필요).

---

### 7. 테스트 실행 — 실제로 돌려본 결과

#### 7-1. 어떻게 돌리나

pytest 설정은 `backend/pytest.ini` 에 있고 `pythonpath = .` 이므로 **반드시 `backend/` 에서 돌려야 한다.**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```

🚨 **`PYTHONIOENCODING=utf-8` 을 빼면 한글이 깨진다.** 테스트 이름에 한글이 들어 있다
(예: `test_pump_dump_live_analyzer.py::test_5m은_신호를_내지_않음`).

PowerShell 에서 돌린다면 (⚠️ PowerShell 은 `VAR=값 명령` 형태를 못 쓴다. 아래처럼 `$env:` 로 따로 세팅한다):

```powershell
cd "C:\Users\user\바이낸스\binance-auto-trader\backend"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/ -q
```

💡 `PYTHONIOENCODING` 은 pytest 만의 문제가 아니다. 이 PC 의 콘솔 기본 인코딩이 **cp949** 라
`pip install --report -` 처럼 유니코드를 뱉는 명령도 `UnicodeEncodeError: 'cp949' codec can't encode ...` 로 죽는다
(실제로 겪었다). **한글이 섞인 출력을 내는 명령 앞에는 습관적으로 붙이는 편이 안전하다.**

#### 7-2. 🚨 실측 결과 — 2026-09-03, 옛 PC, Python 3.14.2

```
52 failed, 1714 passed in 618.63s (0:10:18)
```

| 항목 | 값 |
|---|---|
| 통과 | **1,714건** |
| 실패 | **52건** |
| 합계 | 1,766건 |
| 소요 | **618.63초 (10분 18초)** — 새 PC 에서도 10분 안팎으로 보면 된다 (재실행 시 669초가 나오기도 했다. PC 부하에 따라 ±1분은 흔들린다) |
| 테스트 파일 수 | 156개 (`find backend/tests -name "test_*.py" \| wc -l`) |

✅ **독립 재현 확인 (2026-09-03).** 같은 명령을 다시 돌려 **`52 failed, 1714 passed in 669.51s`** 로
숫자가 정확히 일치하는 것을 확인했다. 이 기준선은 신뢰해도 된다.

**DB 도 Redis 도 필요 없다.** `backend/tests/conftest.py:6` 이
`TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"` 로 인메모리 SQLite 를 쓴다.
`integration/` 폴더 테스트도 마찬가지다.

#### 7-2b. 🚨 그런데 「52」는 **`.env` 가 없을 때**의 숫자다

위 52 는 **`ENCRYPTION_KEY` 가 없는 상태**에서 나온 값이다 (측정을 worktree 에서 했는데
`.env` 는 메인 저장소 폴더에만 있다 — §5 참조).

`.env` 를 §5 대로 제대로 넣고 전체를 다시 돌려봤다. **실패가 52 → 44 로 줄었다** (전체 실행 실측):

```
44 failed, 1722 passed, 2 warnings in 695.49s (0:11:35)
```

두 실행의 실패 목록을 `comm` 으로 대조한 결과, **정확히 아래 8건**이 통과로 바뀌었고
**새로 실패한 것은 0건**이었다:

| 통과로 바뀐 테스트 | `.env` 없을 때의 실패 이유 |
|---|---|
| `unit/test_admin_module_split.py::test_router_registered_in_main_app` | `from app.main import app` → `main.py:46` → **`CryptoError: ENCRYPTION_KEY 가 기본값('change_me')`** |
| `unit/test_strategies_module_split.py::test_router_registered_in_main_app` | 위와 같음 |
| `unit/test_codebase_guards.py::test_static_routes_registered_before_param_routes` | 위와 같음 |
| `integration/test_exchange_credentials_update.py` **5건** (`test_valid_keys_rotate_and_encrypt` / `test_flip_testnet_to_mainnet_no_active_strategies` / `test_key_rotation_with_active_strategy_allowed` / `test_audit_notification_sent_on_success` / `test_passphrase_explicit_empty_clears`) | 거래소 API 키를 **Fernet 으로 암호화**하는 경로라 유효한 키가 없으면 못 돈다 |

**→ 그러므로 §11 체크리스트 순서(`.env` 를 먼저 넣고 테스트)를 따르면 기대 숫자는 52 가 아니다.**

| 상태 | 기대 결과 | 근거 |
|---|---|---|
| `.env` 없음 / `ENCRYPTION_KEY` 미설정 | **52 failed, 1714 passed** | 전체 실행 2회 재현 |
| `.env` 정상 (유효한 `ENCRYPTION_KEY`) | **44 failed, 1722 passed** | 전체 실행 실측 |

🚨 **판정 기준: 위 두 숫자 중 하나가 나오면 정상. 그보다 실패가 많으면 환경 문제다.**
반대로 `.env` 를 넣었는데도 **52** 가 나오면 **`ENCRYPTION_KEY` 가 앱에 안 읽히고 있다는 뜻**이다
(오타·따옴표·BOM·`.env` 가 `backend/` 가 아닌 곳에 있음 등). 그때는 §5-2 부터 다시 본다 —
이건 「원래 실패하던 8건」이 아니라 **설정이 안 먹었다는 신호**다.

💡 이 8건은 **환경 검증에 아주 쓸모 있는 신호**다. `.env` 를 넣었는데 `test_exchange_credentials_update` 5건이
여전히 빨간불이면, 앱이 `ENCRYPTION_KEY` 를 못 읽고 있다는 것을 **앱을 띄우기 전에** 알 수 있다.

#### 7-2c. ✅ 「새 PC 의 clone」을 그대로 재현해서 확인했다

위 숫자들은 옛 PC 의 **작업 트리**에서 잰 것이고, 그 트리에는 미커밋 변경이 있었다
(`M router.py` / `M exchange_accounts.py` / `M market.py` = **+166 / −6줄**, 미추적 `terminal.py`·`perp-terminal.html`).
「새 PC 가 clone 하면 받게 될 코드」와는 다르다.

그래서 **`git archive origin/main` 으로 순정 트리를 따로 뽑아**(= clone 과 동일한 내용) 저장소 밖에서 돌렸다:

```
44 failed, 1722 passed, 2 warnings in 662.95s (0:11:02)
```

실패 **목록까지 한 줄도 다르지 않았다** (`comm` 으로 대조 → 양쪽 차집합 **0건**).
순정 트리 자체도 확인했다 — HTML **9개**, 테스트 파일 **156개**, alembic **32개**, `backend/.env` **없음**.

**→ 새 PC 에서 clone 하고 `.env` 를 넣고 돌리면 `44 failed, 1722 passed` 가 나온다. 이것이 최종 기준선이다.**

#### 7-3. 🚨 52건 실패는 「새 PC 라서」가 아니다 — 옛 PC 에서도 이미 실패하던 것

실패 원인을 하나씩 확인했다. **환경 문제가 아니라 코드와 테스트가 어긋난 것**이다:

```
tests/unit/test_strategy_status_constants.py::test_exactly_seven_statuses
  AssertionError: assert 8 == 7
  frozenset({'CLOSED','CLOSED_BY_SL','CLOSED_BY_TP','COMPLETED',
             'KILL_SWITCH_TRIGGERED','REENTRY_READY', ...})
  Extra items in the left set: 'STOPPED_CAPITAL_EXHAUSTED'
```

= 코드에 `STOPPED_CAPITAL_EXHAUSTED` 상태가 추가됐는데 테스트가 「정확히 7개」라고 못 박고 있다.

```
tests/integration/test_sl_pct_per_template.py::test_default_50_pct
  AssertionError: assert evaluate_stop_loss(1) is True
```

= 손절 판정 로직이 바뀌었는데 옛 기대값이 그대로다.

**따라서 새 PC 에서도 같은 건수가 실패하는 것이 「정상」이다.**
기준선은 §7-2b 표 — `.env` 없으면 **52**, `.env` 정상이면 **44**. 그보다 **커지면** 그때가 진짜 환경 문제다.
(아래 52건 목록 중 `test_admin_module_split` · `test_strategies_module_split` · `test_codebase_guards` ·
`test_exchange_credentials_update` 5건 = **총 8건**은 `.env` 만 있으면 사라지므로
「코드/테스트 어긋남」에 해당하지 않는다.)

> 🚨 **「정상」은 「환경 이전 판정 기준」이라는 뜻이지, 「방치해도 된다」는 뜻이 아니다.**
> 실패 목록에 `test_exit_full_close_mismatch_guard`(청산 수량 불일치 가드) ·
> `test_sl_pct_per_template`(손절 비율) · `test_codebase_guards` · `test_static_assets_integrity` 처럼
> **손절·청산·자동 가드**를 지키는 테스트가 섞여 있다.
> 이 프로젝트는 「가드가 조용히 죽어 있던 것」으로 여러 번 손실을 봤다 (Fix 320/321/322 계열).
> 새 PC 이전이 끝나면 **52건을 그대로 두지 말고 따로 처리 대상으로 올려라.**
> 여기서 「52면 통과」로 쓰는 것은 **오직 환경 검증 한 번뿐**이다.
>
> ⚠️ 그리고 이 52 라는 숫자는 **Python 3.14.2 + 옛 PC 전역 패키지** 기준이다.
> §1 권고대로 **3.12 + venv** 로 맞추면 숫자가 달라질 수 있다 (⚠️ 확인 못 함 — 3.12 로는 돌려보지 않았다).
> 52 와 다르다고 곧바로 「환경 고장」으로 단정하지 말고, **실패한 테스트 이름이 위 목록과 같은지**를 먼저 비교하라.

**실패 파일 전체 목록 — 합이 정확히 52 다** (2026-09-03 재실행 결과에서 파일별로 센 것.
옛 표는 「그 밖」에 11개 파일을 뭉뚱그려 합이 37 밖에 안 됐다. 아래가 완전한 목록이다):

| 파일 | 실패 | 비고 |
|---|---|---|
| `tests/unit/test_martingale_stage_entry.py` | **7** | 🚨 **CI 가 돌리는 파일이다** (§7-4) |
| `tests/integration/test_exchange_credentials_update.py` | **5** | ⬅️ `.env` 만 있으면 **5건 전부 통과** (§7-2b) |
| `tests/unit/test_stream_service_partial_close.py` | 4 | |
| `tests/unit/test_v7_short_exit_partial_stage.py` | 4 | |
| `tests/integration/test_sl_pct_per_template.py` | 4 | 🚨 손절 비율 |
| `tests/integration/test_crisis_adhoc_safety_net.py` | 3 | |
| `tests/integration/test_crisis_threshold_per_template.py` | 3 | |
| `tests/integration/test_verify_tp_sl_entry.py` | 3 | |
| `tests/integration/test_admin_stats_breakdown.py` | 2 | |
| `tests/integration/test_strategy_full_capital_reservation.py` | 2 | |
| `tests/unit/test_risk_constants_centralization.py` | 2 | |
| `tests/unit/test_strategy_status_constants.py` | 2 | |
| `tests/integration/test_crisis_trailing_policy_v2.py` | 1 | |
| `tests/integration/test_ensure_isolated_margin.py` | 1 | |
| `tests/integration/test_exit_full_close_mismatch_guard.py` | 1 | 🚨 청산 수량 가드 |
| `tests/integration/test_reconcile_zombie_cleanup.py` | 1 | |
| `tests/integration/test_stopping_stuck_alert.py` | 1 | |
| `tests/integration/test_trigger_next_stage_and_inplace_stages.py` | 1 | |
| `tests/unit/test_pump_dump_live_analyzer.py` | 1 | |
| `tests/unit/test_static_assets_integrity.py` | 1 | |
| `tests/unit/test_admin_module_split.py` | 1 | ⬅️ `.env` 만 있으면 **통과** (§7-2b) |
| `tests/unit/test_strategies_module_split.py` | 1 | ⬅️ `.env` 만 있으면 **통과** |
| `tests/unit/test_codebase_guards.py` | 1 | ⬅️ `.env` 만 있으면 **통과** |
| **합계** | **52** | `.env` 정상이면 **44** (위 ⬅️ 표시 8건이 빠진다) |

#### 7-4. 🚨 CI 도 지금 빨간불일 가능성이 높다

`.github/workflows/sajangnim_sasang_audit.yml:29` 가 돌리는 3개 파일 중
**`tests/unit/test_martingale_stage_entry.py` 가 로컬에서 7건 실패**한다.
CI 는 Python 3.12 + `pip install pytest pydantic sqlalchemy fastapi` (4개만) 로 돌리므로
로컬과 조건이 다르긴 하다.

### ✅ 확인했다 — 「가능성」이 아니라 **사실이다. CI 는 빨간불이다** (2026-09-03)

저장소가 public 이라 GitHub Actions API 를 **인증 없이** 조회할 수 있었다:

```bash
curl -s "https://api.github.com/repos/herosys1-crypto/binance-auto-trader/actions/runs?per_page=5"
```

- 총 실행 **659건**. `main` 최근 5건(`#655`~`#659`, 2026-09-03) **전부 `conclusion: failure`**
- 더 거슬러 올라가 **최근 100건을 조회했는데 `success` 가 0건**이다.
  조회 범위의 가장 오래된 것이 `#557` (2026-08-29) — 즉 **최소 닷새, 100회 연속 실패** 중이다.

최신 실행(`#659`)의 job 별 결과:

| job | 결과 |
|---|---|
| 사장님 사상 단위 테스트 | ❌ **failure** — 실패 스텝 = `사장님 단위 테스트` (§7-4 표의 `:29`) |
| 사장님 E2E 시나리오 테스트 | ✅ success |
| 코드 ↔ spec 동기 검증 | ✅ success |

**→ 로컬에서 7건 실패하는 `test_martingale_stage_entry.py` 가 CI 에서도 그대로 터지고 있다.**
로컬 실패와 CI 실패가 **같은 원인**이라는 뜻이다.

🚨 **새 PC 세팅과의 관계**: 새 PC 에서 push 를 하면 **당연히 빨간불이 뜬다. 새 PC 탓이 아니다.**
「내가 환경을 잘못 만들었나?」 하고 되돌리지 마라. 이미 100회째 그런 상태다.
다만 이건 **원래 있던 문제**이므로, 이전이 끝난 뒤 §7-3 의 처리 대상 목록과 함께 다루어야 한다.

워크플로 파일은 `.github/workflows/sajangnim_sasang_audit.yml` **하나뿐**이고 job 이 3개다 (실측):

| job | 하는 일 |
|---|---|
| `sajangnim_unit_tests` | `test_sajangnim_stage_calculation.py` / `test_current_price_action.py` / `test_martingale_stage_entry.py` (`:29`) |
| `sajangnim_e2e_tests` | `tests/e2e/test_sajangnim_scenarios.py` (`:47`) |
| `sajangnim_spec_audit` | 금지 패턴 `grep` 2종 (`:62`, `:68`) — 파이썬을 안 쓴다 |

트리거는 `main`·`feat/**` 로의 PR 과 **`main` 에 push** 다(`:6-10`).
즉 새 PC 에서 `main` 에 push 하면 **자동으로 돈다** — 로컬 테스트를 건너뛰고 push 하지 마라.

💡 참고: CI 의 `pip install ... fastapi` 는 **핀이 없다**(`:25`, `:43`). §4-1 사고가 났던 그 형태다.
CI 가 갑자기 빨개지면 코드가 아니라 **CI 가 그날 받은 fastapi 버전**이 원인일 수 있다.
(고치는 것은 코드 변경이라 이번 이전 범위 밖 — 사장님 판단 사항으로 남긴다.)

#### 7-5. 빠르게 일부만 돌리기

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/unit -q
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/unit/test_strategy_status_constants.py -q --no-header
```

---

### 8. 로컬에서 앱을 띄울 수 있나

**결론: 띄울 수 있다. 다만 「어디까지 되는가」가 단계별로 다르다.**

#### 8-1. 실측 — DB/Redis 없이도 앱은 import 되고 화면은 나온다

✅ **`uvicorn` 을 실제 포트(127.0.0.1)에 띄우고 `curl` 로 확인했다** (2026-09-03 재검증).
DB 도 Redis 도 **안 띄운 상태**에서 나온 결과다:

| 경로 | 응답 |
|---|---|
| `/` | **307 Temporary Redirect** → `location: /admin-ui` (본문 0 bytes) |
| `/admin-ui` | **200**, 215,268 bytes ← **여기가 진짜 대시보드다** |
| `/static/js/api.js` | **200**, 6,404 bytes |
| `/metrics` | **200**, 9,912 bytes |
| `/health` | **200**, `{"status":"ok"}` (`main.py:201`) |
| `/healthz` | **404** — 이 이름의 경로는 **없다** |

🚨 **`/` 는 200 이 아니라 307 이다.** `main.py:187-189` 의 `root_redirect()` 가 `/admin-ui` 로 넘긴다.
브라우저는 리다이렉트를 자동으로 따라가므로 **`http://localhost:8000` 을 주소창에 치면 정상적으로 화면이 뜬다.**
다만 `curl http://localhost:8000` 처럼 명령줄로 확인하면 **빈 응답 + 307** 만 보여서
「앱이 고장났나?」 하고 오해하기 쉽다. `curl -L` 을 쓰거나 `/admin-ui` 를 직접 치면 된다:

```bash
curl -s -L -o /dev/null -w "%{url_effective} %{http_code} %{size_download}\n" http://127.0.0.1:8000/
```

기대 출력: `http://127.0.0.1:8000/admin-ui 200 215268`

💡 디스크의 `index.html` 은 218,684 bytes 인데 응답은 215,268 bytes 다. 줄어든 3,416 bytes = **줄 수**다.
`core.autocrlf=true` 라 디스크에는 CRLF 로 체크아웃되고, `main.py:179` 의 `read_text()` 가 LF 로 읽어
내보내기 때문이다. **불일치가 아니라 정상**이다.

앱 import 자체도 성공했다 (`routes: 146`).
`app/core/database.py:6` 의 `create_engine(...)` 은 **연결을 지연**하므로 DB 없이도 import 된다.
Redis 도 마찬가지다 — `main.py:28-41` 의 heartbeat 폴링이 `except Exception` 으로 감싸여 있어
Redis 가 없어도 5초마다 debug 로그만 남고 앱은 멀쩡히 돈다 (위 실측에서 확인).

단, `ENCRYPTION_KEY` 가 없거나 `change_me` / `.env.example` 의 `change_me_to_fernet_key` 면
**`app.main` 을 import 하는 순간 죽는다** — `main.py:46` 의 `validate_encryption_key()` 가
`app = FastAPI(...)` **보다 먼저** 실행되기 때문이다 (§5-2).

#### 8-2. 단계 A — DB/Redis 없이 화면만 보기 (제일 안전)

> 🚨 **「제일 안전」은 `.env` 의 `DATABASE_URL` 이 로컬일 때만 참이다.**
> 옛 PC 의 `.env` 를 그대로 옮겼다면 이 `uvicorn` 은 **운영 Neon DB 에 붙는다.**
> 그러면 「DB 가 없어 실패한다」가 아니라 **운영 데이터가 그대로 뜨고**, 대시보드가 주기적으로 폴링하는
> 잔고·포지션 API 가 **DB 에 저장된 운영 API 키로 Binance 를 호출**한다
> (`app/api/v1/analysis.py`, `app/api/v1/strategies/control.py` 가 binance client 를 쓴다 — 실측).
> = VPS 와 **같은 계정 weight 를 나눠 쓰게 되고**, §8-4 의 IP ban(418) 위험이 여기서도 발생한다.
> 게다가 이 화면에는 **주문·청산 버튼이 있다.** 「보기만 하겠다」가 한 번의 오클릭으로 실주문이 된다.
>
> **→ 이 명령 전에 §8-3 ①번 확인 명령을 먼저 돌려라.** 로컬 DB 가 아니면 켜지 마라.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

⚠️ `uvicorn` 이 「명령을 찾을 수 없다」고 하면 venv 를 안 켠 것이다(§4-3 ①). 확실하게 가려면 `python -m` 을 붙인다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

브라우저에서 `http://localhost:8000` → 307 리다이렉트를 따라 `http://localhost:8000/admin-ui` 로 가고 대시보드가 뜬다.
데이터를 부르는 API 는 DB 가 없어 실패한다. **JS/HTML 만 손볼 때 이걸로 충분하다.**

✅ **확인 완료 (2026-09-03).** 실제로 포트에 바인딩해 `curl` 로 위 §8-1 표의 6개 경로를 전부 찍어봤다.
DB(5433)·Redis 를 **띄우지 않은 상태**에서 `Application startup complete.` 까지 정상 도달했고,
Redis 연결 실패로 인한 크래시도 없었다.

기동 성공 시 터미널에 이 4줄이 나온다:

```
INFO:     Started server process [nnnnn]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

🚨 **이 4줄 대신 `CryptoError: ENCRYPTION_KEY ...` 가 나오면** `.env` 의 `ENCRYPTION_KEY` 문제다(§5-2).
앱이 아니라 **설정** 문제이니 코드를 뒤지지 마라.

#### 8-3. 단계 B — 로컬 DB/Redis 를 띄워 API 까지 쓰기

> ## 🚨🚨 이 절을 시작하기 전에 — 이 문서에서 가장 위험한 곳이다
>
> `alembic upgrade head` 는 **`DATABASE_URL` 이 가리키는 DB 의 스키마를 실제로 바꾼다.**
> 근거(실측): `backend/alembic/env.py:28-30` 이 `os.getenv("DATABASE_URL")` 로
> `alembic.ini:4` 의 기본 URL 을 **덮어쓴다.**
>
> §5 를 그대로 따라 옛 PC 의 `.env` 를 통째로 옮겼다면 `DATABASE_URL` 은 **운영 Neon DB** 다.
> 그 상태에서 컨테이너 안(`docker compose exec api alembic ...`)이나 `.env` 를 읽는 경로로 이 명령을 치면
> **실자금이 도는 운영 DB 에 마이그레이션이 나간다.** VPS 가 같은 DB 를 쓰고 있으므로
> 최악의 경우 **운영 중단 + 포지션 관리 불능**이다.
>
> **되돌리기가 사실상 없다.** `alembic downgrade` 는 추가했던 컬럼을 **DROP** 한다 —
> 그 사이 운영이 써 넣은 값은 같이 사라진다. 「실행 전에 막는 것」이 유일한 방어다.

**① 먼저 로컬 DB 를 가리키는지 확인한다** (값은 화면에 찍히지 않는다 — OK/중단만 나온다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -qE '^DATABASE_URL=postgresql\+psycopg2://[^@]*@(db|localhost|127\.0\.0\.1):' .env && echo "OK - 로컬 DB 다. 진행해도 된다." || echo "!!! 중단 !!! 로컬 DB 가 아니다. 5-3 표대로 먼저 바꿔라."
```

**② 로컬 DB/Redis 를 띄운다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis
```

컨테이너가 실제로 떴는지 먼저 본다 (db 는 `healthy` 가 될 때까지 10~20초 걸린다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose ps
```

**③ 마이그레이션.** 🚨 **`docker compose exec api ...` 를 쓰면 안 된다** — 방금 `db redis` 만 띄웠으므로
`api` 컨테이너는 존재하지 않고 `service "api" is not running` 으로 실패한다.
venv 를 켠 **Windows 호스트에서** 직접 돌린다 (`backend/Makefile` 의 `upgrade` 타깃과 같은 명령):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && alembic upgrade head
```

🚨 **그런데 위 명령만으로는 십중팔구 접속 오류가 난다.** `alembic/env.py:28` 은 `DATABASE_URL` **환경변수**만
읽고 **`.env` 파일은 읽지 않는다**(env.py 실측 — `load_dotenv` 호출이 없다). 환경변수가 없으면
`alembic.ini:4` 의 `...@localhost:**5432**/...` 로 떨어지는데, docker-compose 는 호스트에 **5433** 으로
매핑한다(§5-3). 그래서 그 자리에서 직접 넘겨준다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5433/binance_auto_trader" alembic upgrade head
```

(컨테이너 안에서 돌리고 싶다면 `api` 를 함께 띄운 뒤 `docker compose exec api alembic upgrade head` 를 쓴다.
🚨 **단 이 경로는 `.env` 를 그대로 읽는다** — `docker-compose.yml:30-31` 의 `env_file: .env`.
즉 `.env` 의 `DATABASE_URL` 이 아직 운영 Neon 이면 **운영 DB 가 마이그레이션된다.**
위 ①번 확인을 통과하지 않았다면 이 경로를 쓰지 마라. 호스트에서 URL 을 손으로 넘기는 위 방식이 더 안전하다 —
**어느 DB 를 건드리는지가 명령 줄에 눈으로 보이기 때문**이다.)

**되돌리기 — 로컬 DB 를 처음부터 다시 만들고 싶을 때만:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose down -v
```

> 🚨 **`-v` 는 `postgres_data` 볼륨을 삭제한다** (`docker-compose.yml:136`). 로컬 DB 의 **모든 데이터가 사라진다.**
> 로컬 개발용 DB 일 때만 안전하다. **`.env` 가 운영 Neon 을 가리켜도 이 명령은 Neon 을 지우지 않는다**
> (Neon 은 compose 볼륨이 아니다) — 그래도 습관이 무서우니 「`-v` 는 로컬 전용」으로 외워 둘 것.
> 되돌린 뒤에는 ②→③ 을 다시 하면 된다.

`backend/alembic/versions/` 에 **32개** 마이그레이션 파일이 있고 최신은 `0034_surge_ladder_state.py` 다
(`ls backend/alembic/versions/*.py | wc -l` → **32**. 번호는 0001~0034 인데 **0025·0026 이 결번**이라 파일 수와 번호가 안 맞는다. 정상이다).

`.env` 의 `DATABASE_URL` / `REDIS_URL` 을 §5-3 표대로 맞춰야 한다.

#### 8-4. 단계 C — 전체 스택 (compose)

⚠️ **`backend/README.md:13-20` 의 「빠른 시작」은 `docker compose up -d` 가 아니다.** 실제 본문은
`docker compose up -d db redis` → `make upgrade` → `make seed-templates` → `make run` → `make scheduler`
→ 별도 터미널에서 `make user-stream` 이다. 즉 README 도 **DB/Redis 만 compose 로 띄우고 앱은 따로 켜는** 방식이다
(그리고 `make` 는 Windows 에 없다 — §8-5).

`docker-compose.yml` 이 띄우는 서비스는 **9개**다: `db`(postgres:16) / `redis`(redis:7) / `api` /
`scheduler` / `user-stream` / `mark-price-stream` / `prometheus`(9090) / `grafana`(127.0.0.1:3000) / `db-backup`.

> # ⛔ 여기서부터가 위험 구간이다 — 아래 명령을 읽기 전에 이 상자를 먼저 읽어라
>
> **`docker compose up -d` 를 인자 없이 치면 9개가 전부 뜬다.**
> 그중 `scheduler`·`user-stream`·`mark-price-stream` 은 **실제로 주문을 낼 수 있는 워커**다.
>
> `.env` 에 운영 DB 와 운영 API 키가 들어 있으면 **새 PC 에서 켜는 순간 VPS 와 동시에 같은 계정에 신호를 보낸다.**
> `DEV-WORKFLOW.md:22-23` 이 정확히 이 상황을 경고한다.
> 최악의 경우 **같은 심볼에 이중 진입 / 이중 손절 / 서로의 포지션을 청산**한다.
>
> 🚨 **추가 위험 ① — Binance IP ban (418).**
> 워커 3종은 각자 Binance REST/WebSocket 을 계속 두드린다. VPS 와 새 PC 가 **동시에** 같은 계정 키로
> 붙으면 **계정 단위 요청 weight 가 합산**돼 `429` → `418`(IP ban) 로 간다.
> 이 프로젝트는 **과거에 418 로 ban 이 스스로 연장되는 사고**를 겪었다
> (메모리 `project_2026-08-26_ip_ban_spiral.md`). ban 이 걸리면 **VPS 쪽 실거래도 같이 멈춘다** —
> 새 PC 의 실수가 운영을 세운다. 되돌리는 방법은 「기다리는 것」뿐이다.
>
> 🚨 **추가 위험 ② — `restart: unless-stopped`.**
> 9개 서비스 전부에 이 옵션이 붙어 있다(`docker-compose.yml`). 한 번 켜면 **PC 를 재부팅해도 자동으로 다시 뜬다.**
> 「잠깐 켜 봤다」가 며칠 동안 돌아가는 상태가 된다. 반드시 아래 「끄는 법」으로 명시적으로 내려라.
>
> **→ 새 PC 에서 이 명령(`docker compose up -d`, 인자 없음)은 「VPS 를 내렸다」는 확신이 없으면 치지 마라.**

**VPS 가 지금 돌고 있는지 확인하는 법 (읽기 전용 — 아무것도 바꾸지 않는다):**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

`scheduler` / `user-stream` / `mark-price-stream` 이 `Up` 으로 보이면 **VPS 가 실거래 중이다.**
그 상태에서 새 PC 워커를 켜면 §8-4 의 이중 주문 · IP ban 이 그대로 일어난다.

> 🚨 **VPS 를 내리는 것은 이 문서의 범위가 아니다.** 실자금이 도는 운영기다 —
> 내릴지 말지는 **사장님이 포지션 상태를 보고 직접 판단**하실 일이고,
> 이 핸드오프 작업 때문에 내릴 이유는 없다.
> **새 PC 는 「워커를 안 켜는 것」으로 충분히 안전하다** (§8-4 의 `db redis api` 만 켜기).

**안전 규칙 — 새 PC 에서 처음 띄울 때는 `api` 만 켠다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose up -d db redis api
```

**무엇이 떴는지 눈으로 확인한다 — `scheduler`/`user-stream`/`mark-price-stream` 이 목록에 있으면 즉시 내린다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose ps --services --filter status=running
```

**끄는 법 (되돌리기) — 실수로 워커를 켰다면 이것부터 친다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose stop scheduler user-stream mark-price-stream
```

전부 내리려면 (볼륨은 **안** 지운다 — `-v` 를 붙이지 마라):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && docker compose down
```

> ⚠️ 워커를 잠깐이라도 켰다면 **바이낸스 거래 내역과 텔레그램 알림을 반드시 눈으로 확인**해라.
> 주문이 나갔는지는 컨테이너를 끈다고 없어지지 않는다. 이미 나간 주문은 **되돌릴 수 없다** —
> 포지션 정리는 사장님이 화면에서 직접 판단하실 일이다.

#### 8-5. Makefile 로 워커를 개별 실행

`backend/Makefile` 에 타깃이 정리돼 있다 (`make run` / `make test` / `make upgrade` /
`make scheduler` / `make user-stream` / `make mark-price-stream` 등).

⚠️ **Windows 기본 환경에는 `make` 가 없다. Git Bash 에도 없다** (2026-09-03 실측 — `which make` → `no make in ...`,
`where.exe make` → 찾지 못함). **설치할 필요 없다.** Makefile 은 그냥 「명령 모음집」이라 아래 표대로 직접 치면 된다.

`backend/Makefile` 전체 대응표 (venv 켜고 `backend/` 에서 실행):

| `make ...` | 실제 명령 | 위험 |
|---|---|---|
| `make install` | `pip install -r requirements.txt` | — (🚨 핀 드리프트는 §4-2) |
| `make run` | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | ⚠️ `0.0.0.0` = **LAN 에 노출**. 혼자 쓸 땐 `--host 127.0.0.1` 로 바꿔라 |
| `make test` | `PYTHONIOENCODING=utf-8 python -m pytest -q` | 안전 |
| `make lint` | `python -m compileall app` | 안전 |
| `make upgrade` | `alembic upgrade head` | 🚨 §8-3 상자 |
| `make downgrade` | `alembic downgrade -1` | 🚨 **컬럼 DROP** |
| `make migrate` | `alembic revision --autogenerate -m "auto migration"` | 파일만 생성 |
| `make seed-templates` | `psql $DATABASE_URL -f seed_strategy_templates.sql` | ⚠️ Windows 에 `psql` 도 없다 — `docker compose exec -T db psql ...` 를 쓰거나 건너뛴다 |
| `make scheduler` | `python -m app.workers.scheduler_runner` | ⛔ 아래 상자 |
| `make user-stream` | `python -m app.workers.run_user_stream` | ⛔ 아래 상자 |
| `make mark-price-stream` | `python -m app.workers.mark_price_stream_consumer` | ⛔ 아래 상자 |
| `make worker-keepalive` / `-reconcile` / `-tpsl` / `-symbol-sync` | `python -m app.workers.run_workers --worker <keepalive\|reconcile\|tp-sl\|symbol-sync>` | ⛔ 아래 상자 |

(`make telegram-test` / `make pg-test` 도 있지만 각각 토큰·DB 가 필요해 새 PC 첫 세팅에서는 쓸 일이 없다.)

> 🚨 **`make scheduler` / `make user-stream` / `make mark-price-stream` 은 §8-4 의 워커와 똑같이 위험하다.**
> compose 를 거치지 않을 뿐 **같은 프로세스**다 (`Makefile:39-46` — `python -m app.workers.scheduler_runner`,
> `python -m app.workers.run_user_stream`). 「compose 를 안 썼으니 안전하다」가 아니다.
> §8-4 의 ⛔ 상자(이중 주문 · IP ban)가 그대로 적용된다.
>
> 또 `make seed-templates` 는 `psql $DATABASE_URL -f seed_strategy_templates.sql` 로 **DB 에 직접 쓴다**
> (`Makefile:24-25`). 로컬 DB 를 가리키는지 §8-3 ①번으로 확인한 뒤에만 쓸 것.

---

### 9. git worktree 구조 — 새 PC 에서 어떻게 되나

#### 9-1. 옛 PC 의 실제 상태 (`git worktree list` 실측)

| 경로 | 브랜치 | 커밋 |
|---|---|---|
| `C:/Users/user/바이낸스/binance-auto-trader` (**메인**) | `main` | 2586555 ← 🚨 아래 주의 |
| `.claude/worktrees/infallible-euler-6dc297` | `claude/infallible-euler-6dc297` | e51d9a8 (= `origin/main`) |
| `.claude/worktrees/charming-albattani-3f588f` | `feat/external-positions` | f346fee |
| `.claude/worktrees/loving-rhodes-52788c` | `feat/c-full-archive-filter-restore` | a3e5a02 |
| `C:/Users/user/AppData/Local/Temp/claude/.../scratchpad/baseline` | (detached) | 2a17a26 |

🚨 **옛 PC 의 로컬 `main` 브랜치(2586555)는 `origin/main`(e51d9a8) 보다 30커밋 뒤처져 있다**
(`git rev-list --count 2586555..e51d9a8` → **30**. Fix 318~327 이 전부 그 안에 있다).
최신 코드는 worktree 쪽(`claude/infallible-euler-6dc297`)에 있고 그게 이미 `origin/main` 에 push 돼 있다.
→ **새 PC 는 그냥 clone 하면 최신(e51d9a8)을 받으므로 이 뒤처짐은 새 PC 와 무관하다.**
헷갈리지 않도록 적어 둔다. 옛 PC 에서 `git log` 를 보고 「2586555 가 최신인가?」 하고 판단하지 마라.

#### 9-2. 🚨 새 PC 에서 worktree 는 **하나도 따라오지 않는다** — 그리고 그게 정상이다

세 가지가 겹친다:

1. **`.claude/worktrees/` 는 gitignore 다.**
   `git check-ignore -v .claude/worktrees` → `.gitignore:106:.claude/worktrees/` (메인 저장소에서 실측).
   → GitHub 에 올라간 적이 없다.

2. **worktree 메타데이터는 `.git/worktrees/` 안에 있고, `.git` 내부는 push 되지 않는다.**
   옛 PC 의 `C:/Users/user/바이낸스/binance-auto-trader/.git/worktrees/` 에
   `baseline` / `charming-albattani-3f588f` / `infallible-euler-6dc297` / `loving-rhodes-52788c` 4개 폴더가 있다.
   `git clone` 은 이걸 안 가져온다.

3. **worktree 는 절대경로로 서로를 가리킨다 — 새 PC 경로가 다르면 깨진다.**
   worktree 안의 `.git` 은 파일이고 내용이 이것뿐이다 (실측):

   ```
   gitdir: C:/Users/user/바이낸스/binance-auto-trader/.git/worktrees/infallible-euler-6dc297
   ```

   경로가 통째로 박혀 있다. 폴더를 새 PC 로 복사해 붙여넣으면 **이 경로가 안 맞아 git 이 동작하지 않는다.**

**→ 결론: worktree 폴더를 복사해 옮기려 하지 마라. 새 PC 에서는 브랜치만 받고 필요하면 새로 만든다.**

#### 9-3. 새 PC 에서 확인

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree list
```

메인 하나만 나오면 정상이다.

#### 9-4. 브랜치가 필요하면 — worktree 를 새로 만든다

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git fetch origin
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git branch -r
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree add ".claude/worktrees/external-positions" feat/external-positions
```

갓 clone 한 저장소에는 로컬 브랜치가 `main` 하나뿐이지만 이 명령은 **된다** — git 이 `origin/feat/external-positions`
하나만 찾으면 자동으로 추적 브랜치를 만들어 준다. `Preparing worktree (new branch 'feat/external-positions')` 가 나오면 성공이다.

🚨 **단, 옛 PC 의 worktree 3개 중 하나는 이 방법으로 못 만든다.**
`git ls-remote --heads origin <브랜치>` 로 실측한 결과:

| §9-1 의 브랜치 | origin 에 있나 | 새 PC 에서 `worktree add` |
|---|---|---|
| `claude/infallible-euler-6dc297` | ✅ 있음 | 된다 |
| `feat/external-positions` | ✅ 있음 (커밋 `f346fee` 까지 push 완료) | 된다 |
| `feat/c-full-archive-filter-restore` | ❌ **없음 — 옛 PC 로컬 전용** | **`fatal: invalid reference` 로 실패한다** |

✅ **그래도 잃는 것은 없다.** 확인했다:
- 그 브랜치의 커밋 `a3e5a02` 는 **`origin/main` 의 조상**이다 (`git merge-base --is-ancestor a3e5a02 origin/main` → 참).
  즉 **그 브랜치만 가진 커밋은 0개**다 (`git rev-list --count a3e5a02 --not --remotes` → **0**).
  브랜치 포인터가 옛 main 커밋을 가리키고 있었을 뿐이다.
- 유일한 고유 내용인 **미커밋 변경(2,971 bytes)** 은 §9-5 백업의
  `wip-backup-2026-09-03/loving-rhodes_feat-c-full-archive-filter-restore/uncommitted.patch` 에 들어 있다.

→ 그 작업을 이어서 하려면 **브랜치를 새로 파고 패치를 적용**한다.

🚨 **base 를 `origin/main` 으로 잡으면 패치가 안 붙는다.** 실제로 돌려봤다:

```
error: backend/app/api/v1/strategies.py: No such file or directory
error: patch failed: backend/app/workers/scheduler_runner.py:9
error: backend/app/workers/scheduler_runner.py: patch does not apply
```

이유는 그 사이 **`backend/app/api/v1/strategies.py` 가 `strategies/` 디렉터리로 쪼개졌기 때문**이다
(`git cat-file -e a3e5a02:backend/app/api/v1/strategies.py` → 있음 / `origin/main:...` → **없음**).
패치가 뜬 시점(`a3e5a02`)과 지금 main 의 파일 구조가 다르다.

**그래서 base 는 `a3e5a02` 로 잡는다:**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git worktree add -b feat/c-full-archive-filter-restore ".claude/worktrees/archive-filter" a3e5a02
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/archive-filter" && git apply --check "docs/handoff/wip-backup-2026-09-03/loving-rhodes_feat-c-full-archive-filter-restore/uncommitted.patch"
```

⚠️ 패치 경로는 **worktree 안의 상대경로**다. worktree 도 저장소 전체를 체크아웃하므로
`docs/handoff/...` 가 그 안에 그대로 있다. `../../../docs/...` 같은 상위 경로를 쓰면 안 된다 —
그건 **메인 체크아웃의 `docs/`** 를 가리키고, 그 시점 파일 구조가 다르면 엉뚱한 결과가 난다.

`--check` 는 **적용하지 않고 되는지만** 본다. 아무 출력이 없으면 성공 — 그때 `--check` 를 빼고 다시 친다.
붙인 뒤 최신 main 으로 옮기는 것은 그다음 문제다 (`git rebase origin/main` — `strategies.py` 분할 때문에
충돌이 나는 것이 정상이고 손으로 풀어야 한다).

#### 9-4-a. 🚨 worktree 를 쓸 때 절대 맨손으로 치면 안 되는 git 명령

worktree 들은 **하나의 `.git` 을 공유**한다. 한 폴더에서 친 명령이 다른 폴더의 작업을 지운다.
아래는 이 저장소에서 실제로 위험한 것들이다 — **이 문서 어디에도 이 명령들은 없다. 스스로 치지 마라.**

| 명령 | 무슨 일이 나나 | 대신 이렇게 |
|---|---|---|
| `git stash` / `git stash pop` | 🚨 stash 저장소는 **저장소 전체에 하나뿐**이다. worktree A 에서 `stash` 하고 worktree B 에서 `pop` 하면 **엉뚱한 폴더에 풀리고 충돌 나면 그 자리에서 유실**된다. 옛 PC 의 미커밋 작업을 §9-5 백업으로 뽑아 둔 이유가 이것이다 | 커밋하거나 (`git commit -m wip`) 브랜치를 파라. 꼭 필요하면 `git stash list` 로 **번호를 눈으로 확인**하고 `git stash apply stash@{N}` (pop 말고 apply — 실패해도 원본이 남는다) |
| `git reset --hard` | 그 worktree 의 **미커밋 변경 전부 소멸**. 되돌릴 수 없다 | `git stash` 도 답이 아니다. `git diff > backup.patch` 로 먼저 뽑아 둔다 |
| `git checkout -- .` / `git restore .` | 위와 같음 (조용히 지운다) | 같음 |
| `git clean -fd` | untracked 파일 삭제 — **`.env` 는 gitignore 라 `-x` 를 붙이면 같이 날아간다** | 쓰지 마라. 굳이 쓸 거면 `git clean -nd` 로 **먼저 목록만** 본다 |
| `git push --force` / `-f` | 원격 히스토리를 덮어쓴다. VPS 가 `git pull` 로 받는 코드다 | 절대 금지. 되돌리려면 `git revert` 로 **새 커밋**을 쌓는다 |
| `git worktree remove <경로>` | 그 폴더의 미커밋 작업까지 삭제 | 먼저 `cd` 해서 `git status` 로 비었는지 확인. `--force` 는 쓰지 마라 |
| `rm -rf .claude/worktrees/...` | git 이 모르는 채로 지워져 `.git/worktrees/` 에 **유령 항목**이 남는다 | `git worktree remove` 를 쓰고, 이미 지웠으면 `git worktree prune` |

> 💡 **`git worktree add` 는 이미 다른 worktree 가 체크아웃한 브랜치로는 실패한다**
> (`fatal: '<브랜치>' is already checked out at ...`). 이건 **고장이 아니라 보호 장치**다.
> `--force` 로 뚫지 마라 — 같은 브랜치를 두 폴더에서 고치면 서로를 덮어쓴다.

#### 9-5. 미커밋 작업은 별도 백업에 있다

옛 PC 의 worktree 에 있던 **커밋 안 된 작업**은 이미 저장소 안으로 옮겨져 있다.
구조는 **worktree 별 하위 폴더 3개**다 (`ls docs/handoff/wip-backup-2026-09-03/` 실측):

```
docs/handoff/wip-backup-2026-09-03/
├── main/
├── charming-albattani_feat-external-positions/
└── loving-rhodes_feat-c-full-archive-filter-restore/
```

각 폴더 안에 똑같이 6개가 들어 있다:
`uncommitted.patch` / `staged.patch` / `untracked/` / `untracked-list.txt` / `unpushed/` / `unpushed-commits.txt`.
복원 절차는 `docs/handoff/RESTORE-2026-09-03.md` §2 참조.

**백업 6종을 전부 열어 origin/main 과 대조했다** (2026-09-03). 실제로 손댈 것은 많지 않다:

| 폴더 / 항목 | 실측 | 새 PC 에서 할 일 |
|---|---|---|
| `main/` 의 `staged.patch`·`uncommitted.patch` | **0 bytes** (빈 파일) | 없음 |
| `main/untracked/docs/` 문서 2건 | 이미 `origin/main` 에 커밋됨 | **없음** — clone 으로 따라온다 (§9-6) |
| `charming.../unpushed/0001-feat-positions.patch` (`f346fee`) | **이미 `origin/feat/external-positions` 에 있음** (`git ls-remote --heads` 로 확인) | **없음** — worktree 만 새로 만들면 된다 |
| `charming.../untracked/HANDOFF-2026-05-21-SAFETY-NETS.md` | `origin/main` 에 **없음** (백업에만 있는 문서) | 필요하면 그냥 복사. 코드 아님 |
| `loving-rhodes.../uncommitted.patch` **2,971 bytes** | ⬅️ **유일하게 코드 복원이 필요한 것** | §9-4 절차대로 `a3e5a02` 기반 worktree 에 `git apply` |
| `loving-rhodes.../untracked/` 워커 2개 | 🚨 **아래 경고** | **복사하지 마라** |

> ## 🚨 `loving-rhodes` 의 「새 워커 2개」를 복사하면 **최신 코드를 옛 코드로 덮는다**
>
> `RESTORE-2026-09-03.md` §2-1 은 이 두 파일을 「**원격 어디에도 없는 작업**」이라고 적고 있다.
> **사실이 아니다.** 둘 다 이미 `origin/main` 에 있고, **main 쪽이 훨씬 크고 최신**이다 (`git cat-file -s` 실측):
>
> | 파일 | 백업본 | `origin/main` | 차이 |
> |---|---|---|---|
> | `backend/app/workers/auto_long_at_bottom_worker.py` | 12,019 bytes | **93,893 bytes** | diff **2,066줄** |
> | `backend/app/workers/long_bottom_detector_worker.py` | 27,244 bytes | **42,437 bytes** | diff **415줄** |
>
> 백업본은 그 워커들의 **초기 스냅샷**이다. 그대로 `cp` 하면 **8만 줄 가까운 개발분이 사라진다.**
> RESTORE 문서 §2-1 의 「바로 복사하지 마라 / diff 를 먼저 보라」 경고는 옳지만,
> **「원격에 없다」는 전제 자체가 틀렸으므로** 그 절은 그냥 건너뛰어도 된다.
>
> → **결론: 이 두 파일은 아무것도 하지 마라.** clone 한 `origin/main` 것이 정답이다.

→ **정리: 위 백업에서 새 PC 로 손수 복원할 것은 `loving-rhodes` 의 `uncommitted.patch` 하나뿐이다.**

#### 9-5-a. 🚨🚨 백업에 **빠져 있는** 것 — 옛 PC 를 밀기 전에 반드시 처리할 것

`wip-backup-2026-09-03/` 에는 폴더가 **3개**뿐이다: `main` / `charming-albattani` / `loving-rhodes`.
**지금 이 작업을 하고 있는 worktree(`infallible-euler-6dc297`) 폴더가 없다.**
백업이 만들어진 뒤에도 이 worktree 에서 작업이 계속됐기 때문이다.

그런데 그 worktree 에는 **커밋도 push 도 안 된 작업이 215KB 넘게** 있다 (`git status --short` 실측):

| 상태 | 파일 | 크기 |
|---|---|---|
| ?? 미추적 | `backend/app/static/perp-terminal.html` | **144,146 bytes** |
| ?? 미추적 | `backend/app/api/v1/terminal.py` | **71,608 bytes** |
| M 수정 | `backend/app/api/v1/exchange_accounts.py` | +101줄 |
| M 수정 | `backend/app/api/v1/market.py` | +69줄 |
| M 수정 | `backend/app/api/router.py` | +2줄 |

이건 **「perp 터미널」 기능**으로 보이며 **origin 어디에도 없다** (`git ls-tree origin/main` 에 없음).

🚨 **옛 PC 를 밀거나 디스크가 죽으면 이 작업은 그대로 사라진다.**
`git clone` 으로도, `wip-backup` 으로도 **복구할 방법이 없다.**

**→ 새 PC 로 넘어가기 전에 셋 중 하나를 반드시 해라:**

**① 커밋해서 push 한다 (가장 안전, 권장)**

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git add -A && git commit -m "wip(perp-terminal): 새 PC 이전 전 임시 저장" && git push origin HEAD
```

**② 커밋하기 싫으면 패치로 떠서 저장소에 넣는다** (위 백업들과 같은 방식)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked && git diff > docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/uncommitted.patch && git ls-files --others --exclude-standard > docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked-list.txt
```

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" && git ls-files --others --exclude-standard | while read -r f; do mkdir -p "docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked/$(dirname "$f")"; cp "$f" "docs/handoff/wip-backup-2026-09-03/infallible-euler_perp-terminal/untracked/$f"; done
```

(그다음 이 백업 폴더를 커밋해서 push 해야 새 PC 로 따라온다. 안 하면 ①과 똑같이 사라진다.)

**③ 이 작업을 버릴 생각이면 아무것도 안 해도 된다** — 다만 **버린다는 결정을 의식적으로** 하라.
모르고 잃는 것과 알고 버리는 것은 다르다.

#### 9-6. 옛 PC 에 남아 있던 정리 안 된 것

메인 worktree 의 `git status --short` 실측:

```
?? docs/CURRENT_STATE_2026-08-24_END_OF_DAY.md
?? docs/ROLLBACK_GUIDE_2026-08-24.md
```

untracked 문서 2건. ✅ **담겨 있는 것을 실제로 확인했다** (2026-09-03) — 다음 자리에 그대로 있다:

```
docs/handoff/wip-backup-2026-09-03/main/untracked/docs/CURRENT_STATE_2026-08-24_END_OF_DAY.md
docs/handoff/wip-backup-2026-09-03/main/untracked/docs/ROLLBACK_GUIDE_2026-08-24.md
```

즉 clone 만 하면 새 PC 에 따라온다. 옛 PC 에서 따로 챙길 것이 없다.

---

### 10. `.claude/` — 무엇이 따라오고 무엇이 안 따라오나

`git check-ignore -v` 로 하나씩 확인했다.

| 경로 | gitignore? | 근거 | 새 PC 에서 |
|---|---|---|---|
| `.claude/agents/impl.md` | ❌ **아님** | `git ls-files .claude` → 3건 tracked | ✅ **clone 하면 그대로 있다** |
| `.claude/agents/locator.md` | ❌ 아님 | 위와 같음 | ✅ 따라옴 |
| `.claude/agents/mech.md` | ❌ 아님 | 위와 같음 | ✅ 따라옴 |
| `.claude/settings.local.json` | ✅ **ignore** | `"C:\Users\user/.config/git/ignore":3:**/.claude/settings.local.json` | ❌ **안 따라옴** — 손으로 옮겨야 함 |
| `.claude/worktrees/` | ✅ ignore | `.gitignore:106` | ❌ 안 따라옴 (§9) |
| `.claude/settings.json` | (파일 자체가 없음) | `ls` → 없음 | — |
| 저장소 루트 `CLAUDE.md` | (파일 자체가 없음) | `ls CLAUDE.md` → 없음 | — |

#### 10-1. 🚨 `settings.local.json` 을 막는 것은 저장소 `.gitignore` 가 **아니다**

전역 ignore 파일 `C:\Users\user\.config\git\ignore` 의 **3번째 줄**이 막고 있다.
저장소의 `.gitignore` 에는 이 규칙이 **없다.**

→ **새 PC 에 그 전역 ignore 파일이 없으면, `settings.local.json` 이 커밋 대상으로 잡힌다.**
민감 정보는 없지만(아래 참조) 42KB 짜리 로컬 설정이 저장소에 섞이는 것은 바람직하지 않다.

옛 PC 의 그 파일은 **3줄뿐**이고 내용은 전부 확인했다 (시크릿 없음, 그냥 ignore 규칙):

```
**/.claude\settings.local.json
(빈 줄)
**/.claude/settings.local.json
```

(역슬래시판·슬래시판을 둘 다 넣어 둔 것이다. 실제로 매칭되는 건 슬래시판 = 3번째 줄.)

`core.excludesFile` 은 **설정돼 있지 않다** (`git config --show-origin --get core.excludesFile` → 빈 출력).
git 이 `~/.config/git/ignore` 를 기본으로 읽기 때문에 별도 설정이 필요 없다.

새 PC 에서 같은 보호를 켜려면 파일 하나만 만들면 된다:

```bash
mkdir -p "$HOME/.config/git" && printf '%s\n' '**/.claude/settings.local.json' >> "$HOME/.config/git/ignore"
```

(`$HOME` 을 쓴다. Git Bash 에서 `$HOME` 은 `/c/Users/<윈도우사용자명>` 이라 사용자명이 `user` 가 아니어도 맞는다.
`echo $HOME` 으로 먼저 확인해도 좋다. `>>` 이므로 이미 있는 파일에 줄만 덧붙는다 — 두 번 돌리면 같은 줄이 두 번 생기지만 무해하다.)

확인:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git check-ignore -v .claude/settings.local.json
```

이런 한 줄이 나오면 성공이다 (옛 PC 실측 출력):

```
"C:\\Users\\user/.config/git/ignore":3:**/.claude/settings.local.json	.claude/settings.local.json
```

🚨 **아무 것도 안 나오고 조용히 끝나면 = 막히지 않은 것이다** (`git check-ignore` 는 매칭이 없으면 출력 없이 exit 1).
「에러가 안 났으니 됐다」고 착각하지 마라. 출력 줄이 보여야 성공이다.

#### 10-2. `settings.local.json` 안에 무엇이 있나

구조만 확인했다 (값 나열 안 함). 최상위 키는 **`permissions` 하나뿐**이고 그 안은 `allow` 배열 하나다.
API 키·토큰 같은 것은 **없다.**

🚨 **그런데 이 파일은 하나가 아니다. 옛 PC 에 네 개가 있고 내용이 전부 다르다** (2026-09-03 실측):

| 위치 | 크기 | `permissions.allow` 건수 |
|---|---|---|
| **메인 저장소** `binance-auto-trader/.claude/settings.local.json` | 20,766 bytes | **164** |
| worktree `loving-rhodes-52788c/.claude/settings.local.json` | **107,338 bytes** | **731** ← 가장 많다 |
| worktree `infallible-euler-6dc297/.claude/settings.local.json` | 42,065 bytes | 345 |
| worktree `charming-albattani-3f588f/.claude/settings.local.json` | 9,106 bytes | 71 |

**「345건 / 42KB」는 worktree 하나의 숫자였다.** 새 PC 가 clone 후 갖게 될 자리(메인 저장소)에
대응하는 것은 **164건 / 20,766 bytes** 쪽이다.

→ **권장: 가장 많은 `loving-rhodes-52788c` 것(731건)을 새 PC 메인 저장소 자리에 넣어라.**
허용 목록은 많을수록 덜 묻는다. 자동 병합되지 않으므로, 여러 개를 합치고 싶으면 손으로 합쳐야 한다.
(옛 PC 를 아직 안 밀었다면 나중에 다시 가져와도 된다 — 잃어도 「다시 묻는다」일 뿐 복구 불가한 값이 아니다.)

이걸 안 옮기면 새 PC 에서 Claude Code 가 명령마다 허용을 다시 묻는다. 동작은 하지만 매우 번거롭다.

**「같은 자리」란 정확히 어디인가** — **저장소 루트 바로 아래**다. 홈 디렉터리가 아니다:

```
C:\Users\user\바이낸스\binance-auto-trader\.claude\settings.local.json
```

USB 로 옮긴 뒤 그 자리에 놓고 확인한다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && ls -l .claude/settings.local.json && python -c "import json,io; d=json.load(io.open('.claude/settings.local.json',encoding='utf-8')); print('keys:', list(d)); print('allow:', len(d['permissions']['allow']))"
```

기대 출력: `keys: ['permissions']` 와, 어느 파일을 가져왔는지에 따라 `allow:` **164 / 345 / 731 / 71** 중 하나
(아래 표 참조). `keys` 가 `['permissions']` 가 아니면 잘못된 파일을 가져온 것이다.

⚠️ **worktree 를 새로 만들면 그 폴더에도 별도의 `.claude/` 가 생긴다.** worktree 안에서 Claude Code 를
쓸 거라면 그쪽에도 같은 파일을 넣어야 같은 허용 목록이 적용된다 (옛 PC 도 그렇게 돼 있었다).

#### 10-3. `.claude/agents/` 3종 — 클론하면 바로 쓸 수 있다

| 에이전트 | 모델 | 용도 (파일 front matter 에서 발췌) |
|---|---|---|
| `impl` | sonnet | 「매매 로직이 아닌 일반 구현 — UI/화면, API 엔드포인트, 문서, 스크립트, 테스트」. 🚨 「손절·자본·진입 판정 코드는 이 에이전트에 맡기지 마라」 |
| `locator` | haiku | 코드 위치 찾기 전용. 「코드를 고치지 않는다」 |
| `mech` | haiku | 기계적 점검 — 문법/임포트/포맷, 테스트 실행·분류. 「매매 로직 판단에는 쓰지 마라」 |

---

### 11. 새 PC 체크리스트 (순서대로)

| # | 할 일 | 확인 방법 |
|---|---|---|
| **0** | 🚨 **옛 PC 를 밀기 전에** `ENCRYPTION_KEY` 를 비밀번호 관리자에 백업 (§5-4 ③) | 지문 12자 메모 (§5-4 ④) |
| **0-b** | 🚨 **옛 PC 를 밀기 전에** `infallible-euler-6dc297` worktree 의 미커밋 작업(**215KB**, perp 터미널)을 push 하거나 패치로 뜬다 (§9-5-a) | 그 worktree 에서 `git status --short` 가 **비어 있어야** 안전 |
| 1 | Python 3.12 설치 (PATH 체크) | `python --version` |
| 2 | Git 설치 + `user.name`/`user.email`/`init.defaultBranch`/`core.longpaths` 설정 (§2-1, §2-2) | `git config --global --list` 에 3줄 (`credential.helper`·`core.autocrlf` 는 설치만 하면 자동) |
| 3 | Docker Desktop 설치 | `docker --version` |
| 3-b | 새 PC 사용자명 확인 (§2-3) | `echo $HOME` 이 `/c/Users/user` 인가? 아니면 이 문서의 경로를 전부 바꿔 읽어야 한다 |
| 4 | `$HOME/바이낸스/` 폴더 만들고 clone (**로그인 안 뜬다 — public 이다**, §2-3) | `git log --oneline -3` 첫 줄이 `e51d9a8` |
| 5 | 메모리 83개 복원 | RESTORE 문서 §1 — `ls .../memory \| wc -l` 이 83 |
| 6 | `.claude/settings.local.json` 복사 (§10-2) — 옛 PC 4개 중 **731건짜리** 권장 | §10-2 의 `python -c ...` 가 `keys: ['permissions']` 를 출력 |
| 7 | 전역 git ignore 설정 (§10-1) | `git check-ignore -v .claude/settings.local.json` 이 걸림 |
| 8 | venv 만들고 §4-3 ②번 명령으로 고정 설치 | `pip freeze \| grep -i "^fastapi=="` → `fastapi==0.135.3` |
| 9 | 🚨 옛 PC `.env` 의 비밀 값을 **§5-4 ①②** 대로 옮김 (통째 복사 ❌, ENCRYPTION_KEY 필수). 옮긴 뒤 USB 는 지운다 | 아래 9-확인 명령 + §5-4 ④ 지문 일치 |
| 9-b | 🚨 **옮긴 `.env` 의 `DATABASE_URL`·`TEST_DATABASE_URL`·`REDIS_URL` 을 로컬용으로 바꾼다 (§5-3)** | 아래 9b-확인 명령 |
| 10 | 테스트 (10~12분 소요) | 9·9-b 를 마쳤으면 **`44 failed, 1722 passed`** 가 정상. `.env` 없이 돌렸다면 `52 failed, 1714 passed` (§7-2b) |
| 11 | 앱 기동 (api 만) | `http://localhost:8000` 에서 대시보드 HTML |
| 12 | ⛔ 워커(`scheduler`/`user-stream`/`mark-price-stream`)는 **VPS 를 내렸다는 확신이 없으면 켜지 않는다.** 이중 주문 + Binance IP ban(418) 로 **VPS 실거래까지 멈춘다** | §8-4 ⛔ 상자. 켜졌는지 확인 = `docker compose ps --services --filter status=running` |
| 13 | 🚨 **`docker compose up -d` 를 인자 없이 치지 않았는지** 되짚는다 (인자 없으면 워커 3종 포함 9개가 전부 뜨고, `restart: unless-stopped` 라 재부팅해도 되살아난다) | 위 12번과 같은 명령. 워커가 보이면 즉시 `docker compose stop scheduler user-stream mark-price-stream` |

**9-확인** — 키가 22개 다 왔는지 센다. **값은 안 찍고 개수만** 나온다:

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -cE "^[A-Za-z_0-9]+=" .env
```

**9b-확인** — 🚨 이게 이번 이전에서 **가장 위험한 한 줄**이다. `.env` 의 DB/Redis 주소가 어디를 가리키는지
**호스트 이름만** 뽑아 본다 (비번·토큰은 안 찍힌다):

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && grep -E "^(DATABASE_URL|TEST_DATABASE_URL|REDIS_URL)=" .env | sed -E 's#://[^@]*@#://***:***@#'
```

출력에 `neon.tech` 같은 **운영 DB 호스트**가 보이면 **거기서 멈추고** §5-3 대로 `localhost:5433` /
`redis://localhost:6380/0` 으로 바꾼 다음에 10번으로 간다. 운영 주소를 그대로 둔 채 앱을 켜면
**로컬에서 실자금 DB 를 건드린다.**

📌 **9-확인 숫자 읽는 법**: 옛 PC `.env` 를 참고해 채웠으면 **22**, `cp .env.example .env` 로 시작했으면 **18** 이
정상이다(§5-2). 그보다 **적게 나오면** `ENCRYPTION_KEY` 를 포함해 뭔가 빠진 것이니 §5-1 표와 대조한다.

---

### 12. ⚠️ 확인 못 한 것

| 항목 | 왜 |
|---|---|
| ~~GitHub 저장소가 실제로 Private 인지~~ | ✅ **확인 완료 (2026-09-03) — Private 이 아니라 `public` 이었다.** 미인증 `curl` 로 GitHub API 가 **200** + `"private": false` 를 반환. `GIT_SYNC_GUIDE.md:36` 의 「Private 선택」은 옛 설정 안내일 뿐 현재 상태가 아니다. clone 에 로그인이 필요 없다. §2-3 의 정정 상자 참조 |
| ~~GitHub Actions 최근 실행이 초록불인지 빨간불인지~~ | ✅ **확인 완료 (2026-09-03) — 빨간불이다.** 저장소가 public 이라 Actions API 를 미인증 조회했다. `main` **최근 100건 전부 실패**(`success` 0건, 최소 2026-08-29 `#557` 이후 연속). 실패 job 은 `사장님 사상 단위 테스트` 하나이고 나머지 2개는 통과. 로컬 7건 실패와 **같은 원인**이다. §7-4 참조 |
| ~~`pip install` 이 Python **3.12** 에서도 문제없이 되는지~~ | ✅ **확인 완료 (2026-09-03)** — `pip download --python-version 3.12 --only-binary=:all: --platform win_amd64` 로 §4-3 ②번 23개 핀을 전부 받아봤고 전이 의존성 포함 **54개 wheel 이 모두 존재**, 해석 실패 0건. §4-3 참조 |
| ~~`uvicorn` 을 포트에 실제 바인딩해 열어본 결과~~ | ✅ **확인 완료 (2026-09-03)** — `127.0.0.1:8765` 에 바인딩해 `curl` 로 6개 경로 확인. **`/` 는 200 이 아니라 307 → `/admin-ui`** 였다(옛 기록의 200 은 TestClient 가 리다이렉트를 자동으로 따라간 결과). §8-1 참조. 단 **브라우저 GUI 로 눈으로 본 것은 아니다** |
| ~~저장소 소스에 `C:\Users\user` 절대경로 하드코딩이 있는지 전수 조사~~ | ✅ **확인 완료 (2026-09-03)** — 저장소 전체 검색 결과 소스·스크립트에 **0건**. `.bat` 4개는 전부 `%~dp0` 상대경로. §3-2 참조 |
| ~~`make` 를 새 PC 에 어떻게 넣을지~~ | ✅ **해결 (2026-09-03)** — 넣을 필요가 없다. `backend/Makefile` 14개 타깃 전부를 실제 명령으로 풀어 §8-5 에 표로 옮겨 적었다. `make` 미설치를 `which make` / `where.exe make` 로 실측 확인 |
| ~~52건 실패가 origin/main 에서도 동일한지~~ | ✅ **확인 완료 (2026-09-03)** — 옛 설명(`git diff --stat origin/main HEAD` 빈 출력)은 **커밋끼리만** 비교한 것이라 근거가 약했다. 실제 작업 트리엔 미커밋 변경이 있었다(`M router.py`/`M exchange_accounts.py`/`M market.py` = +166/−6줄, 미추적 `terminal.py`·`perp-terminal.html`). 그래서 `git archive origin/main` 으로 **순정 트리를 따로 뽑아 저장소 밖에서 전체 실행** → `44 failed, 1722 passed`, **실패 목록까지 완전히 동일**. §7-2c |
| 52건 실패가 **Python 3.12 + venv** 에서도 똑같이 52건인지 | 실측은 3.14.2 + 전역 패키지에서만 했다. §1 권고대로 3.12 로 맞추면 숫자가 달라질 수 있다 — **숫자보다 실패 테스트 이름을 비교**할 것 (§7-3) |
| §8-3 의 `alembic upgrade head` 를 실제 로컬 DB 에 돌려본 결과 | **일부러 안 돌렸다.** 옛 PC `.env` 가 운영 Neon 을 가리키고 있어, 조사 중 실수로 운영 DB 를 마이그레이션할 위험이 있었다. 명령의 동작은 `alembic/env.py:28-30` 과 `alembic.ini:4` 를 **읽어서** 추론한 것이다 |
| 워커(`scheduler`/`user-stream`/`mark-price-stream`)를 로컬에서 켰을 때 실제로 어떤 주문이 나가는지 | **실자금이라 시험하지 않았다.** §8-4 의 위험 설명은 `docker-compose.yml` 의 command 와 `DEV-WORKFLOW.md:22-23`, 그리고 과거 사고 기록에 근거한 것이다 |
| Binance weight 가 어느 지점에서 `429`/`418` 로 넘어가는지 | 재보지 않았다(재보는 행위 자체가 ban 을 부른다). 과거 418 사고 기록(`project_2026-08-26_ip_ban_spiral.md`)에 근거해 **「동시 접속을 만들지 마라」**로만 적었다 |
| `docker compose down -v` 가 운영 Neon 에 영향이 없다는 것 | compose 볼륨(`postgres_data`)만 지운다는 정의상 그렇다. **실행해서 확인하지는 않았다** — 어차피 이 명령은 로컬에서만 쓸 것 |


---

<a id="sec-5"></a>

## 5. VPS 운영환경과 배포 절차

조사 시각: 2026-09-03 09:00~09:05 UTC (KST 18:00~18:05)
조사 방법: SSH 읽기 전용 조회 + 저장소 파일 정독. **VPS 는 아무것도 변경하지 않았다.**

---

> ## 🚨🚨🚨 먼저 읽을 것 — 확인된 비밀 유출
>
> **운영 중인 `SECRET_KEY`(로그인 토큰 서명키)가 공개 GitHub 저장소에 평문으로 들어 있다.**
> 저장소 공개 여부, 커밋된 값, 그 값이 VPS 현재 값과 동일하다는 것(md5 일치), 그리고
> API 포트 8000 이 인터넷에 열려 있다는 것까지 **2026-09-03 에 전부 실측 확인했다.**
>
> 합치면 **누구든 로그인 토큰을 위조해 실자금 자동매매 API 에 접근할 수 있다.**
> 새 PC 이전보다 **이 조치가 먼저다.** → **10장의 「10-A」 절**(문서 내 `10-A` 로 검색)에
> 확인 근거·조치 순서·재검증 명령이 있다.
>
> ✅ 함께 확인한 것: Binance API 키·`ENCRYPTION_KEY`·텔레그램 토큰은 저장소에 커밋되지 **않았고**,
> 저장소에 있던 옛 Neon DB 비밀번호는 **이미 교체되어 있다.** (상세는 10-A 표)

---

### 0. 한눈에 보는 접속 정보

> 🚨 **새 PC 라면 이 문서를 순서대로 읽지 말고 아래 「9장. SSH 키」를 먼저 하라.**
> 1장부터 나오는 모든 명령이 SSH 접속을 전제한다. 키가 등록되기 전에는 **하나도 돌지 않는다.**
> 권장 순서: **9장(SSH 키) → 11장(첫날 체크리스트) → 1장(위험 3가지) → 나머지.**
>
> 새 PC 사전 준비 (셋 다 없으면 SSH 부터 막힌다):
> - **OpenSSH 클라이언트** — Git for Windows(Git Bash)에 포함. `ssh -V` 로 확인.
> - **`git`** — `git --version` 으로 확인.
> - 이 문서의 명령은 전부 **Git Bash** 기준이다. PowerShell 에서는 작은따옴표 인용이 달라 깨진다.
>
> 검증 (새 PC 에서):
>
> ```bash
> ssh -V && git --version
> ```

| 항목 | 값 | 근거 |
|---|---|---|
| VPS IP | `159.65.137.250` (DigitalOcean) | 과제 지시 + `ssh` 실접속 성공 |
| SSH 계정 | `root` | `ssh root@159.65.137.250` 성공 |
| SSH 인증 키 | `~/.ssh/id_ed25519` (현 PC) | `ssh -v` 출력: `Server accepts key: /c/Users/user/.ssh/id_ed25519` |
| 내 공개키 지문 | `SHA256:cbFAdSNFpCEZRnC/fxKsDmI0+4w2uTSUgls9XWbC4KI` | 동상 |
| VPS 호스트키 지문 | `SHA256:NYbjWuJ7a5pBfXRi9E9ys7yyDqWlaupLiuwH12Q2toM` (ED25519) | `ssh-keyscan \| ssh-keygen -lf -` |
| 앱 경로 | `/root/binance-auto-trader/backend` | `ls -la ~/binance-auto-trader/backend` |
| git remote | `https://github.com/herosys1-crypto/binance-auto-trader.git` | `git remote -v` (VPS) |
| VPS 브랜치 / HEAD | `main` / `ded22f3` | `git rev-parse --abbrev-ref HEAD`, `git log --oneline -3` |
| Docker / Compose | Docker 29.4.3 / Compose v5.1.3 | `docker --version`, `docker compose version` |
| Compose 프로젝트명 | **`backend`** (디렉터리명에서 자동) | `docker compose ls` → `NAME=backend` |
| DB | **외부 Neon** `ep-…(엔드포인트 ID 마스킹).c-2.ap-southeast-1.aws.neon.tech` / `neondb` | api 컨테이너에서 `DATABASE_URL` 파싱 (비번은 출력 안 함) |
| Alembic 리비전 | `0034_surge_ladder` (current == head, 최신) | `alembic current`, `alembic heads` |
| 웹 접속 | `https://159.65.137.250` (self-signed, 브라우저 경고 1회 무시) | `/etc/nginx/sites-enabled/trader` |
| 스펙 | 2 vCPU / 7.8 GiB RAM / 48G 디스크 (25G 사용, 51%) | `nproc`, `free -h`, `df -h /` |
| 가동 시간 | 114일 23시간 | `uptime` |

---

### 1. 🚨 가장 먼저 알아야 할 3가지 (전부 실측 확인)

#### 🚨 (1) `docker-compose.production.yml` 은 VPS 에 **있지만 적용되어 있지 않다**

먼저 **파일 위치를 헷갈리지 마라.** 이 오버라이드 파일은 `backend/` 안이 아니라 **저장소 루트**에 있다.

| 파일 | 위치 (저장소) | 위치 (VPS) |
|---|---|---|
| `docker-compose.yml` (기본) | `backend/docker-compose.yml` | `/root/binance-auto-trader/backend/docker-compose.yml` |
| `docker-compose.production.yml` (오버라이드) | **저장소 루트** | `/root/binance-auto-trader/docker-compose.production.yml` |

`docker-compose.production.yml` 은 「Neon 을 쓰니 로컬 db 를 끄고, 포트를 127.0.0.1 로 묶는다」는
운영용 오버라이드다. **파일은 VPS 에 git 으로 내려와 있다** (git 추적 파일이므로 당연하다).
문제는 **compose 가 이 파일을 읽지 않는다**는 것이다 — compose 는 실행 디렉터리(`backend/`)의
`docker-compose.yml` + `docker-compose.override.yml` 만 자동으로 읽는데, `docker-compose.override.yml` 이
**없다.**

두 디렉터리를 **모두** 확인해야 한다 (`backend/` 만 보면 「파일이 없다」는 오진에 빠진다):

```bash
ssh root@159.65.137.250 'ls -la ~/binance-auto-trader/docker-compose*.yml ~/binance-auto-trader/backend/docker-compose*.yml'
```

실제 출력 (2026-09-03 재확인):

```
-rw-r--r-- 1 root root 2778 May 31 19:03 /root/binance-auto-trader/docker-compose.production.yml
-rw-r--r-- 1 root root 4011 May 31 19:02 /root/binance-auto-trader/backend/docker-compose.yml
```

→ `backend/` 안에는 `docker-compose.yml` **하나뿐**이고 `docker-compose.override.yml` 은 **없다.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ls'
```

```
NAME      STATUS         CONFIG FILES
backend   running(9)     /root/binance-auto-trader/backend/docker-compose.yml
```

`CONFIG FILES` 가 `docker-compose.yml` **하나뿐**이다 = **오버라이드가 실제로 안 먹고 있다.**
이것이 결정적 증거다 (파일 존재 여부가 아니라 **이 줄**을 봐야 한다). 그 결과가 아래 (2)(3)이다.

오버라이드를 적용하는 방법은 파일 머리말(`docker-compose.production.yml:4-10`)에 적혀 있다 —
`-f` 로 두 개를 같이 주거나, `backend/docker-compose.override.yml` 로 복사하는 것.
🚨 **둘 다 재시작을 동반하므로 실자금 영향이 있다. 사장님 판단 사항이며 나는 실행하지 않았다.**

> 근거: `docker-compose.production.yml:21-26` (db/db-backup 을 `profiles: ["disabled"]` 로 끔),
> `docker-compose.production.yml:30-31, 73-74, 82-83` (포트를 `127.0.0.1` 로 묶음),
> `docker-compose.production.yml:100-101` (grafana 비번을 `.env` 주입으로 권고)

#### 🚨 (2) 포트가 인터넷에 열려 있다 — Redis 는 **비밀번호도 없다**

내 PC(외부 인터넷)에서 TCP 연결을 시도한 결과:

| 포트 | 서비스 | 외부 접속 | 위험 |
|---|---|---|---|
| 443 | nginx (HTTPS) | OPEN | 정상 (의도된 것) |
| 80 | nginx → 443 리다이렉트 | OPEN | 정상 |
| 8000 | **api (평문 HTTP)** | **OPEN** | 🚨🚨🚨 HTTPS 강제를 우회해서 API 직접 호출 가능. **게다가 JWT 서명키(`SECRET_KEY`)가 공개 저장소에 유출되어 있어 인증까지 위조 가능 → 10-A. 이 둘이 합쳐지는 것이 현재 최대 위험이다.** |
| 9090 | **prometheus** | **OPEN** | 🚨 인증 없음, 운영 지표 전부 노출 |
| 6380 | **redis** | **OPEN** | 🚨🚨 **`requirepass` 가 비어 있음 = 무인증** |

Redis 무인증 확인 (VPS 내부에서):

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli CONFIG GET requirepass'
```

→ 값이 **빈 문자열**로 돌아온다 (`cat -A` 로 확인: `requirepass$` 다음 줄이 `$` 뿐).

방화벽도 없다:

```bash
ssh root@159.65.137.250 'ufw status'
```

→ `Status: inactive`

🚨 **Redis 에는 IP ban 회로 차단기 상태(`api_backoff:ip:ban_until_ms`), weight 카운터, mark price 캐시,
재진입 대기 사유가 들어 있다.** 외부에서 이 키를 쓰면 자동매매 판정을 조작할 수 있다.
🚨 **이건 이번 이전(migration) 작업과 별개로 사장님이 판단해서 조치할 사안이다. 나는 VPS 를 읽기 전용으로
다뤘으므로 아무것도 바꾸지 않았다.** 조치하려면 오버라이드를 적용하거나(재시작 필요 = 실자금 영향) UFW/DO
클라우드 방화벽으로 6380·9090·8000 을 막는 방법이 있다.

⚠️ 확인 못 함: DigitalOcean **클라우드 방화벽**(VPS 바깥 계층)이 별도로 걸려 있는지는 DO 콘솔을 봐야 안다.
다만 위 TCP 연결이 **실제로 성립**했으므로 최소한 현재는 막혀 있지 않다.

#### 🚨 (3) `db-backup` 은 **빈 데이터베이스를 백업하고 있다** — 백업이 사실상 없다

`db-backup` 은 `POSTGRES_HOST: db` 로 **로컬 postgres 컨테이너**를 백업한다
(`backend/docker-compose.yml:119`). 그런데 앱은 Neon 을 쓰므로 로컬 `db` 는 **비어 있다.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T db psql -U postgres -d binance_auto_trader -c "\dt"'
```

→ `Did not find any relations.` (테이블 0개)

백업 파일 크기가 그 증거다:

```bash
ssh root@159.65.137.250 'ls -la ~/binance-auto-trader/backend/db_backups/daily/'
```

```
-rw-r--r-- 1 root root  505 Aug 27 00:00 binance_auto_trader-20260827.sql.gz
-rw-r--r-- 1 root root  506 Sep  2 00:00 binance_auto_trader-20260902.sql.gz
-rw-r--r-- 4 root root  505 Sep  3 00:00 binance_auto_trader-20260903.sql.gz
```

**505 바이트.** 압축을 풀어 보면 `CREATE SCHEMA public;` 밖에 없다 = **데이터 0건.**
`db_backups` 폴더 전체가 76K 다.

🚨 **결론: 실거래 데이터(전략·주문·학습기록)의 백업은 VPS 에 존재하지 않는다. 오직 Neon 자체 백업/PITR 에만
의존하고 있다.** 이건 `docker-compose.production.yml:25-26` 이 의도한 바(「Neon 이 처리」)와 같지만,
**그 오버라이드가 적용되지 않아 db-backup 컨테이너가 매일 헛돌며 「백업이 돌고 있다」는 착시**를 만든다.
🚨 **새 PC 로 옮기기 전에 Neon 콘솔에서 백업/PITR 보존기간을 반드시 눈으로 확인할 것.**

⚠️ 확인 못 함: Neon 프로젝트의 백업 보존 정책(플랜별 PITR 기간)은 Neon 웹 콘솔에서만 볼 수 있어 확인하지 못했다.

---

### 2. `db` 컨테이너의 모순 — 죽은 것인가?

**답: 프로세스는 살아 있지만, 애플리케이션 관점에서는 죽었다. 쓰이지 않는다.**

| 질문 | 답 | 근거 |
|---|---|---|
| `db` 컨테이너가 떠 있나? | 예. `Up 3 weeks` | `docker compose ps` |
| 앱이 여기 붙나? | **아니오.** `DATABASE_URL` 은 Neon 을 가리킨다 | api 컨테이너에서 `DATABASE_URL` 호스트 파싱 → `...neon.tech` |
| 안에 데이터가 있나? | **없음. 테이블 0개** | `psql -c "\dt"` → `Did not find any relations.` |
| 그럼 왜 떠 있나? | 운영 오버라이드 파일은 VPS 에 **있지만 compose 가 안 읽는다** (위 1-(1)) | `docker compose ls` CONFIG FILES |
| 디스크는? | 볼륨 `backend_postgres_data` 47M (initdb 기본값 수준) | `du -sh /var/lib/docker/volumes/backend_postgres_data` |

🚨 **여기서 나는 반드시 함정을 경고해야 한다.**
`docker compose exec db psql ...` 로 조회하면 **빈 DB** 가 나오고, 그러면
「테이블이 없다 / 데이터가 날아갔다」는 **완전한 오진**에 이른다. 실제로 이 프로젝트는 이런 종류의
오진으로 여러 번 사고가 났다. **DB 조회는 반드시 api 컨테이너의 앱 세션으로 한다.**

❌ **절대 이렇게 조회하지 마라 (빈 DB 가 나온다):**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T db psql -U postgres -d binance_auto_trader -c "select count(*) from strategy_instances"'
```

✅ **반드시 이렇게 조회하라 (Neon 에 붙는다):**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(db.execute(text(\"select count(*) from strategy_instances\")).scalar())
"'
```

- `PYTHONPATH=/app` 를 빼면 `ModuleNotFoundError` 가 난다.
- 쿼리가 하나라도 실패하면 세션이 오염되므로 다음 쿼리 전에 `db.rollback()` 을 부를 것.
- 여러 줄 스크립트는 로컬에 파일로 쓴 뒤 `scp` → `docker compose cp` → 실행이 안전하다.

---

### 3. 9개 서비스 정리표

정의: `backend/docker-compose.yml` (VPS 에서 실제 사용 중) /
**저장소 루트**의 `docker-compose.production.yml` (파일은 VPS 에 있으나 **compose 가 안 읽음** — 1-(1))

| # | 서비스 | 이미지 | 하는 일 | 명령 | 포트 (실제 VPS) | 볼륨 | depends_on | 실제 상태 |
|---|---|---|---|---|---|---|---|---|
| 1 | `db` | `postgres:16` | 🚨 **미사용.** 앱은 Neon 을 씀. 테이블 0개 | 기본 | `127.0.0.1:5433→5432` | `postgres_data` | — | Up 3 weeks (죽은 것과 같음) |
| 2 | `db-backup` | `prodrigestivill/postgres-backup-local:16` | 🚨 **빈 `db` 를 매일 백업** (@daily, 일7/주4/월6 보관) | `/init.sh` | 미노출 (`ps` 표시는 `5432/tcp`, 헬스체크는 내부 8080) | `./db_backups:/backups` | `db` | Up 3 weeks (healthy) — 하지만 무의미 |
| 3 | `api` | `backend-api` (로컬 빌드) | FastAPI 웹서버 + UI. nginx 가 여기로 프록시 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | 🚨 **`0.0.0.0:8000`** | `.:/app` (bind) | `db`, `redis` | Up 9 min, 재시작 0 |
| 4 | `scheduler` | `backend-scheduler` | **자동매매 두뇌.** APScheduler 로 워커 수십 개를 주기 실행 (진입/단계/TP·SL/재진입/피라미딩) | `python -m app.workers.scheduler_runner` | 내부 8000 (미노출) | `.:/app` | `db`, `redis` | Up 9 min, **재시작 4회** |
| 5 | `user-stream` | `backend-user-stream` | Binance User Data Stream(WS) 구독 — 체결/포지션 이벤트 수신 | `python -m app.workers.run_user_stream` | 내부 8000 | `.:/app` | `db`, `redis` | Up 22 hours, 재시작 0 |
| 6 | `mark-price-stream` | `backend-mark-price-stream` | markPrice WS 를 1초 주기로 Redis 캐시 갱신 → 라이브 PNL 정확도 (±0.1 USDT) | `python -m app.workers.mark_price_stream_consumer` | 내부 8000 | `.:/app` | `db`, `redis` | Up 8 days, 재시작 0 |
| 7 | `redis` | `redis:7` | 회로차단기 상태 / weight 카운터 / markPrice 캐시 / 대기사유 | 기본 | 🚨 **`0.0.0.0:6380→6379` 무인증** | 없음 (영속화 X) | — | Up 3 weeks, 재시작 1 |
| 8 | `prometheus` | `prom/prometheus:latest` | api `/metrics` 수집 + 알림 규칙 | 기본 | 🚨 **`0.0.0.0:9090`** | `./deploy/prometheus/*.yml` (2개, ro 아님) | `api` | Up 3 weeks |
| 9 | `grafana` | `grafana/grafana:latest` | 대시보드. admin 계정, 익명 접속 차단 | 기본 | `127.0.0.1:3000` (안전) | `./deploy/grafana/provisioning`, `./deploy/grafana/dashboards` | `prometheus` | Up 3 weeks |

> 근거: `backend/docker-compose.yml:1-136` 전체, VPS `docker compose ps -a` 및
> `docker inspect --format "{{.Name}} started={{.State.StartedAt}} restarts={{.RestartCount}}"`

🚨 **`grafana` 의 admin 비밀번호가 `backend/docker-compose.yml:99` 에 평문으로 커밋되어 있다.**
(값은 여기 옮기지 않는다.) 3000 포트는 127.0.0.1 로만 열려 있어 당장 외부 위험은 아니지만,
`docker-compose.production.yml:100-101` 은 이 값을 `.env` 주입으로 바꾸라고 주석으로 권고한다.

**앱 코드를 실행하는 컨테이너는 4개**(`api`, `scheduler`, `user-stream`, `mark-price-stream`)이며,
전부 `.:/app` **bind mount** 를 쓴다 → **`git pull` 후 재시작만으로 새 코드가 반영된다(재빌드 불필요).**
`backend/Dockerfile:17` 의 `COPY . /app` 은 bind mount 에 덮여서 무의미해진다.

#### 새 PC 에서 각 화면에 접속하는 법

| 화면 | 새 PC 에서 여는 법 |
|---|---|
| **웹 UI (본체)** | 브라우저에서 `https://159.65.137.250` — self-signed 인증서라 경고가 뜬다. 「고급 → 계속 진행」 1회 |
| **Grafana** | `127.0.0.1:3000` 이라 **직접 못 연다. SSH 터널이 필요하다** ↓ |
| **Prometheus** | `http://159.65.137.250:9090` 으로 열리긴 하지만 (1-(2)의 보안 문제) **터널로 여는 편이 낫다** ↓ |

SSH 터널 (새 PC 에서 실행, 이 창은 **켜 둔 채로** 브라우저를 연다):

```bash
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 root@159.65.137.250
```

그 다음 브라우저에서 `http://localhost:3000` (Grafana) / `http://localhost:9090` (Prometheus).
Grafana 로그인 계정은 `admin` 이고 **비밀번호는 `backend/docker-compose.yml:99` 에 평문으로 있다**
(값은 이 문서에 옮기지 않는다 — 파일을 직접 볼 것). 터널은 `Ctrl+C` 로 끊는다.

⚠️ nginx 는 `/etc/nginx/sites-enabled/trader` 에서 80 → 443 리다이렉트 후
`proxy_pass http://127.0.0.1:8000` 으로 api 에 넘긴다 (2026-09-03 실측 확인).
즉 **웹 UI 는 nginx 를 거치고, Grafana/Prometheus 는 nginx 를 안 거친다.**

---

### 4. 현재 VPS 실측 상태 (2026-09-03 09:04 UTC)

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

```
NAME                                    SERVICE             STATUS
binance-auto-trader-api                 api                 Up 9 minutes
binance-auto-trader-db                  db                  Up 3 weeks
binance-auto-trader-db-backup           db-backup           Up 3 weeks (healthy)
binance-auto-trader-grafana             grafana             Up 3 weeks
binance-auto-trader-mark-price-stream   mark-price-stream   Up 8 days
binance-auto-trader-prometheus          prometheus          Up 3 weeks
binance-auto-trader-redis               redis               Up 3 weeks
binance-auto-trader-scheduler           scheduler           Up 9 minutes
binance-auto-trader-user-stream         user-stream         Up 22 hours
```

재시작 횟수 조회:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'docker inspect --format "{{.Name}} started={{.State.StartedAt}} restarts={{.RestartCount}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}" $(docker ps -aq)'
```

| 컨테이너 | 시작 시각 (UTC) | 재시작 | 비고 |
|---|---|---|---|
| api | 2026-09-03 08:51:26 | 0 | 오늘 배포 |
| scheduler | 2026-09-03 08:51:57 | **4** | 마지막 종료코드 0, OOM 아님 → 사장님의 수동 배포 재시작으로 보임 (⚠️ 단정 못 함) |
| user-stream | 2026-09-02 11:13:58 | 0 | |
| mark-price-stream | 2026-08-26 00:27:34 | 0 | |
| redis | 2026-08-12 11:31:18 | 1 | |
| db / db-backup / prometheus / grafana | 2026-08-12 03:00 | 0 | |

헬스 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

→ `{"status":"ok"}`

⚠️ **부하 주의**: `uptime` 이 load average `6.16 / 3.99 / 3.67` 인데 **vCPU 는 2개**다.
15분 평균 3.67 = 코어 대비 약 180% 로 **지속적으로 과부하**다. 메모리는 여유(7.8Gi 중 1.6Gi 사용).
⚠️ 원인은 확인하지 못했다 (스캔 워커 밀집이 유력하나 측정 안 함).

---

### 5. 🚨 서비스명 함정 — `api` / `scheduler` 이지 `backend` 가 **아니다**

메모리의 경고를 **확인했고, 사실이다.** 그리고 헷갈리는 진짜 이유까지 찾았다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose config --services'
```

```
redis
db
scheduler
user-stream
api
db-backup
prometheus
grafana
mark-price-stream
```

**`backend` 라는 서비스는 없다.** 그런데 왜 자꾸 `backend` 를 치게 되는가:

| 무엇 | 이름 | 왜 헷갈리나 |
|---|---|---|
| Compose **프로젝트**명 | `backend` | 디렉터리명이 `backend` 라서 자동으로 붙는다 (`docker compose ls` → `NAME backend`) |
| **이미지**명 | `backend-api`, `backend-scheduler`, `backend-user-stream`, `backend-mark-price-stream` | 프로젝트명 접두사가 붙어서 `docker compose ps` 의 IMAGE 열에 `backend-` 가 보인다 |
| **컨테이너**명 | `binance-auto-trader-api` 등 | `container_name:` 으로 고정 (`backend/docker-compose.yml:4,20,28,...`) |
| **서비스**명 (compose 명령에 쓰는 것) | **`api`, `scheduler`, ...** | ← 이것만이 `docker compose restart <X>` 에 유효 |

❌ **틀린 명령 (에러):**

```bash
docker compose restart backend
```

✅ **맞는 명령:**

```bash
docker compose restart api scheduler
```

또한 **systemd 서비스는 존재하지 않는다.** `systemctl list-units | grep -iE "trader|binance"` 는
아무것도 반환하지 않았다. 즉 `systemctl restart api` 같은 것도 없다. **전부 docker compose 다.**

---

### 6. 배포 절차 (정확한 명령)

전제: 배포는 **수동 SSH** 다. GitHub Actions 에 배포 워크플로가 **없다**
(`.github/workflows/` 에는 `sajangnim_sasang_audit.yml` 하나뿐이고 SSH/deploy 문자열이 없다).
VPS 에 `crontab -l` 도 없고 배포 스크립트(`*.sh`)도 없다.

🚨 **배포는 실자금이 도는 자동매매를 재시작한다. 사장님 판단으로만 실행한다.**

#### 🚨🚨 6-0. 배포 전에 반드시 알아야 할 것 — **손절은 거래소가 아니라 `scheduler` 가 한다**

`backend/app/integrations/binance/futures_trade.py:75, 102` 에 거래소측 손절/익절 주문을 넣는
`place_stop_market_order` / `place_take_profit_market_order` 가 **정의되어 있지만, 호출하는 곳이
`backend/app` 안에 한 곳도 없다.**

```bash
# 실행 결과: 아무것도 안 나온다 = 호출처 0곳
grep -rn "stop_market\|take_profit_market" backend/app --include=*.py | grep -v futures_trade.py
grep -rn "STOP_MARKET" backend/app --include=*.py     # futures_trade.py 한 파일만
```

🚨 **결론: 포지션에 걸린 거래소측 스톱 주문이 없다. 손절·익절·강제청산은 전부 `scheduler` 컨테이너의
워커가 주기적으로 판정해서 시장가로 낸다.**

➡️ **`scheduler` 가 꺼져 있는 동안 모든 포지션은 손절이 전혀 없는 무방비 상태다.**
`restart` 는 수 초지만 `--build` 는 수 분, `down` 은 사장님이 다시 켤 때까지다.

**따라서 배포는 반드시:**
1. 포지션이 적고 변동성이 낮은 시간에 한다.
2. 재시작 후 **6-6 의 확인을 끝까지 한다.** 「명령을 쳤다」로 끝내지 않는다.
3. 🚨 큰 미실현 손실 포지션을 들고 있을 때는 배포를 **미룬다.**

⚠️ 확인 못 함: 과거에 수동으로/거래소 앱으로 걸어 둔 스톱 주문이 남아 있을 가능성은 배제 못 한다.
위 판정은 **이 저장소 코드가 스톱 주문을 걸지 않는다**는 사실까지만이다.

#### 6-1. 표준 배포 (코드만 바뀐 경우) — 가장 흔한 경우

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250
```

🚨 **① 되돌릴 지점을 먼저 적어 둔다 (이걸 안 하면 롤백이 불가능하다).**

```bash
cd ~/binance-auto-trader/backend && echo "ROLLBACK_TO=$(git rev-parse HEAD)  at $(date -u +%FT%TZ)" | tee -a ~/deploy_rollback_points.txt
```

🚨 **② IP ban 중이 아닌지 확인한다.** ban 중에 재시작하면 회로차단기 상태가 초기화되어
2026-08-26 사고(스스로 ban 을 연장)가 재현될 수 있다 (→ 8장, 6-5).

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"
```

→ **빈 값이어야 배포한다.** 숫자가 나오면 그 시각이 지날 때까지 **배포를 미룬다.**

**③ 받아온다.** 🚨 `git pull` 이 아니라 `git pull --ff-only` 를 쓴다.

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main
```

- 🚨 **왜 `--ff-only` 인가**: 그냥 `git pull` 은 VPS 쪽 이력이 갈라져 있으면 **자동 머지**를 시도한다.
  충돌이 나면 VPS 작업 트리에 **충돌 마커가 박힌 반쪽짜리 `.py` 파일**이 남는데,
  bind mount 라서 **그게 곧바로 실행 중인 코드가 된다.** `--ff-only` 는 이 경우 아무것도
  건드리지 않고 즉시 실패한다 = 안전하다.
  (VPS 는 지금까지도 `pull --ff-only` / `pull -q` 로만 갱신돼 왔다 — `git reflog` 로 확인함.)
- ⚠️ `--ff-only` 가 실패하면 **거기서 멈추고 원인을 확인한다.** 🚨 아래는 절대 하지 마라:
  `git stash` / `git stash pop` / `git reset --hard` / `git clean -fd` / `git push -f` — 이유는 6-5.

**④ 재시작한다.**

```bash
cd ~/binance-auto-trader/backend && docker compose restart api scheduler
```

🚨 **③과 ④ 사이를 길게 두지 마라.** bind mount 라서 `git pull` 이 끝나는 **순간** 디스크 코드는
새 코드다. 그런데 프로세스는 아직 옛 코드로 돌고 있고, 이 프로젝트는 **함수 안 `import`** 를 여러 곳에서
쓴다 → 그 함수가 처음 호출되는 순간 **새 모듈이 옛 프로세스에 섞여 들어온다.**
즉 `pull` 직후는 **옛 코드 + 새 코드가 뒤섞인 상태**다. 실자금이 이 상태로 오래 돌면 안 된다.
③④를 한 줄로 붙여서 실행하는 것이 가장 안전하다:

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main && docker compose restart api scheduler
```

**⑤ 되돌리는 법 (배포 후 이상하면).**

```bash
cd ~/binance-auto-trader/backend && tail -3 ~/deploy_rollback_points.txt
```

```bash
cd ~/binance-auto-trader/backend && git checkout <위에서_적어둔_해시> && docker compose restart api scheduler
```

- `git checkout <해시>` 는 detached HEAD 가 된다(정상). 나중에 복귀는 `git checkout main`.
- 🚨 **`git reset --hard` 를 쓰지 마라.** 되돌아가는 효과는 같지만, 손이 미끄러져 대상을 잘못 적으면
  복구 지점이 사라진다. `checkout` 은 이력을 안 지운다.
- 🚨 **마이그레이션을 이미 돌렸다면 코드만 되돌리는 것으로는 부족하다** → 6-3 의 경고를 볼 것.
- 🚨 **되돌린 뒤에도 6-6 의 「배포 후 3분 확인」을 반드시 한다.** 롤백도 재시작이다.

##### 6-1 보충 — 왜 재빌드가 필요 없나 / 무엇을 재시작하나

- `.:/app` bind mount 덕분에 **재빌드가 필요 없다.** `git pull` 이 호스트 파일을 갱신하면
  컨테이너 안 `/app` 이 그대로 바뀐다. 파이썬 프로세스만 재시작하면 반영된다.
- 🚨 **`docker compose restart` 는 `.env` 변경을 반영하지 않는다.** `restart` 는 기존 컨테이너를
  껐다 켜기만 하고 환경변수는 **컨테이너 생성 시점**에 박힌다. `.env` 를 고쳤다면 **재생성**해야 한다:

  ```bash
  cd ~/binance-auto-trader/backend && docker compose up -d --force-recreate api scheduler user-stream mark-price-stream
  ```

  (`.py` 코드만 바뀐 경우엔 `restart` 로 충분하다 — bind mount 라서.)
  🚨 **서비스명 4개를 반드시 붙여라.** `--force-recreate` 만 쓰고 서비스명을 빼면 `redis` 까지
  재생성되어 IP ban 회로차단기가 지워진다 (→ 6-5).
  🚨 재생성은 `restart` 보다 오래 걸린다 = **손절 없는 구간이 그만큼 길다** (→ 6-0).
  🚨 **`.env` 를 고치기 전에 원본을 복사해 둘 것** — git 에 없어서 되돌릴 방법이 그것뿐이다:
  `cp .env .env.bak.$(date +%F-%H%M)` (🚨 이 백업 파일도 비밀 값이 들어 있다. 저장소 밖에 두고,
  `.gitignore` 가 `backend/.env.*` 를 막지만 방심하지 말 것 → 10장).
- 🚨 **`backend/.env` 가 없으면 compose 자체가 안 뜬다.** 9개 서비스 중 앱 4개가
  `env_file: - .env` 를 쓴다 (`backend/docker-compose.yml:30-31` 등). git 에 없는 파일이므로
  저장소만 clone 해서는 절대 실행되지 않는다 → 10장 참조.
- 🚨 **어떤 컨테이너를 재시작해야 하는지는 바뀐 파일에 달렸다:**

| 바뀐 것 | 재시작해야 할 서비스 |
|---|---|
| `app/api/**`, `app/static/**` (UI), `app/schemas/**` | `api` |
| `app/workers/**`, `app/services/**`, `app/agents/**` | `scheduler` (대부분 `api` 도 같이 쓰므로 **둘 다** 권장) |
| `app/integrations/binance/**`, `app/core/**` | **`api scheduler user-stream mark-price-stream` 전부** |
| 잘 모르겠으면 | 아래 6-2 의 전체 재시작 |

#### 6-2. 앱 4개 전부 재시작 (판단이 안 설 때)

```bash
cd ~/binance-auto-trader/backend && docker compose restart api scheduler user-stream mark-price-stream
```

- 🚨 **재시작 전에 6-1 의 ①(롤백 지점 기록)과 ②(IP ban 확인)를 먼저 한다.** 6-2 만 따로 쓰지 마라.
- 🚨 `restart` 는 서비스명을 **명시한 것만** 건드린다. `redis` 를 넣지 마라 (→ 6-5).
- 🚨 재시작 직후 `scheduler` 가 뜨는 데 실패하면 **손절이 계속 없는 상태**다 (→ 6-0).
  반드시 6-6 으로 **네 컨테이너가 다 살아났는지** 확인한다.

#### 6-3. 마이그레이션이 있는 경우 (alembic)

🚨🚨 **먼저 — alembic 은 새 PC 에서 절대 돌리지 마라. 반드시 VPS 의 `api` 컨테이너 안에서만 돌린다.**

`backend/alembic/env.py:27-30` 은 **환경변수 `DATABASE_URL` 이 있을 때만** 그것을 쓰고,
없으면 `backend/alembic.ini:4` 의 기본값(`localhost:5432` 의 로컬 postgres)으로 **조용히** 넘어간다.

| 어디서 돌리나 | 실제로 어디에 붙나 | 결과 |
|---|---|---|
| VPS `api` 컨테이너 (`env_file: .env`) | ✅ Neon (실데이터) | 정상. **이것만 쓴다** |
| 새 PC, `DATABASE_URL` 없이 | 🚨 `localhost:5432` — 엉뚱한/없는 DB | `current` 가 **거짓말**을 한다. 「미적용이 있다」고 착각해 잘못된 판단을 한다 |
| 새 PC, VPS 에서 복사한 `.env` 로 | 🚨🚨 **운영 Neon** | **노트북에서 실데이터 스키마를 바꾼다.** 절대 금지 |

🚨 **에러가 안 난다는 점이 가장 위험하다.** 조용히 다른 DB 를 보고 그럴듯한 답을 낸다.

**언제 도는가**: `backend/alembic/versions/` 에 **새 파일이 추가되었을 때만.**

✅ **가장 확실한 판정법 — `current` 와 `heads` 를 비교한다.** (git 이력에 의존하지 않는다)

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic current && docker compose exec -T -e PYTHONPATH=/app api alembic heads
```

⚠️ alembic 은 `INFO [alembic.runtime.migration] ...` 줄을 **stderr 로** 먼저 뱉는다. 그건 정상이고
**맨 마지막 줄**의 리비전 ID 만 보면 된다. 두 값이 **같으면 돌릴 것이 없다.**

2026-09-03 실행 결과:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
0034_surge_ladder (head)      ← current
0034_surge_ladder (head)      ← heads
```

→ 같다 = **미적용 마이그레이션 없음.**

(참고) `git pull` 로 새 마이그레이션 파일이 왔는지 보고 싶으면:

```bash
cd ~/binance-auto-trader/backend && git diff --name-only "HEAD@{1}" HEAD -- alembic/versions/
```

⚠️ 이건 **reflog 에 의존**한다. 새로 clone 했거나 reflog 가 만료됐으면 `HEAD@{1}` 이 없어서 에러가 난다.
그럴 땐 위의 `current` vs `heads` 비교를 쓸 것. (VPS 는 reflog 635개 보유 = 현재는 동작함)

`current` 와 `heads` 가 **다를 때만** 아래를 실행한다:

```bash
cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head
```

그 다음에 6-1 의 재시작을 한다. **순서는 `git pull` → `alembic upgrade head` → `restart` 다.**

🚨 **이 순서에는 피할 수 없는 위험 구간이 있다.** `git pull` 이 끝난 순간 디스크는 새 코드인데
스키마는 아직 옛날이다 (bind mount + 함수 안 `import` → 6-1 ③ 참조). 즉
**`pull` 과 `upgrade head` 사이에는 「새 코드 + 옛 스키마」로 실거래가 돈다.**
🚨 **그러므로 마이그레이션이 있는 배포는 세 명령을 한 줄로 붙여서 간격을 최소화한다:**

```bash
cd ~/binance-auto-trader/backend && git pull --ff-only origin main && docker compose exec -T -e PYTHONPATH=/app api alembic upgrade head && docker compose restart api scheduler user-stream mark-price-stream
```

(`&&` 라서 앞이 실패하면 뒤가 안 돈다 = 반쯤 배포되는 사고를 막는다.)

🚨 **alembic 은 Neon(실데이터)을 건드린다. 되돌리기(`alembic downgrade -1`)는 데이터 손실 가능성이 있다.**
🚨 alembic 을 돌리기 전에 Neon 콘솔에서 **브랜치/스냅샷을 하나 떠 두는 것이 안전하다** (VPS 백업은 앞서
설명했듯 비어 있어서 도움이 안 된다).

##### 🚨 마이그레이션을 돌린 뒤 롤백하는 법 (6-1 ⑤ 만으로는 부족하다)

`alembic upgrade` 는 **Neon 의 실제 스키마를 바꾼다.** 코드만 옛 커밋으로 되돌리면
**옛 코드 + 새 스키마** 조합이 된다.

| 상황 | 어떻게 하나 |
|---|---|
| 새 마이그레이션이 **컬럼/테이블 추가만** 한 경우 | ✅ **코드만 되돌리면 된다.** 옛 코드는 새 컬럼을 안 볼 뿐이다. `downgrade` 를 돌리지 마라 |
| 새 마이그레이션이 **컬럼/테이블 삭제·이름변경·타입변경**을 한 경우 | 🚨 코드만 되돌리면 옛 코드가 없어진 컬럼을 찾아 **전 API 500** 이 날 수 있다. 이때만 `downgrade` 를 고려하되 **Neon 스냅샷을 먼저 떠 둔 경우에만** |

🚨 **그래서 순서는 「Neon 스냅샷 → `alembic upgrade` 」다.** 스냅샷 없이 `upgrade` 를 돌리면
되돌릴 방법이 사실상 없다. `db_backups/` 는 비어 있어서 도움이 안 된다 (→ 1-(3)).

🚨 **마이그레이션 내용을 먼저 눈으로 읽어라.** 어느 쪽인지 30초면 안다:

```bash
cd ~/binance-auto-trader/backend && grep -nE "drop_column|drop_table|drop_constraint|alter_column" alembic/versions/00XX_*.py
```

→ 아무것도 안 나오면 「추가만」 = 롤백이 쉬운 쪽이다.

**현재 리비전 (2026-09-03 실측)**:

```
current: 0034_surge_ladder (head)
heads:   0034_surge_ladder (head)
```

→ **최신이며 미적용 마이그레이션 없음.** 대응 파일: `backend/alembic/versions/0034_surge_ladder_state.py`

#### 6-4. `requirements.txt` 가 바뀐 경우 (재빌드 필요)

bind mount 는 파이썬 **소스**만 덮는다. 설치된 패키지는 이미지 안에 있으므로 재빌드해야 한다.

```bash
cd ~/binance-auto-trader/backend && docker compose up -d --build api scheduler user-stream mark-price-stream
```

🚨 이 명령은 컨테이너를 **재생성**한다. 빌드 시간(수 분) 동안 자동매매가 멈춘다.
🚨🚨 **그 수 분 동안 모든 포지션에 손절이 없다** (→ 6-0). 이것이 6-4 의 가장 큰 위험이다.
🚨 프로젝트 이력에 **「mainnet deps 핀 필수」**(fastapi 드리프트로 전 API 500 사고) 교훈이 있다.
재빌드는 requirements 가 핀되어 있는지 확인한 뒤에 한다.

**6-4 를 안전하게 하는 순서:**

1. 🚨 **먼저 이미지를 만들어 두고, 그 다음에 갈아 끼운다.** 이러면 정지 시간이 수 분 → 수 초가 된다.

   ```bash
   cd ~/binance-auto-trader/backend && docker compose build api scheduler user-stream mark-price-stream
   ```

   (`build` 만 하는 동안에는 **현재 컨테이너가 계속 돌아간다** = 손절이 살아 있다.)

2. 빌드가 **성공한 것을 확인한 뒤에만** 갈아 끼운다.

   ```bash
   cd ~/binance-auto-trader/backend && docker compose up -d api scheduler user-stream mark-price-stream
   ```

3. 🚨 **되돌리는 법**: 재빌드 롤백은 `git checkout <해시>` 만으로는 안 된다. **패키지가 이미지 안에
   있으므로 이미지도 되돌려야 한다.** 옛 코드로 체크아웃한 뒤 **다시 빌드**해야 한다.

   ```bash
   cd ~/binance-auto-trader/backend && git checkout <ROLLBACK_TO_해시> && docker compose build api scheduler user-stream mark-price-stream && docker compose up -d api scheduler user-stream mark-price-stream
   ```

   ⚠️ 이때도 되돌리는 빌드에 수 분이 걸리므로, **1번처럼 build 를 먼저 끝내고 up 을 나중에** 한다.

🚨 **`up -d` 는 `docker-compose.yml` 이 바뀌었으면 해당 서비스를 재생성한다.** `git pull` 로
compose 파일이 바뀐 뒤 서비스명을 빠뜨리고 `docker compose up -d` (인자 없이) 를 치면
**`redis` 까지 재생성되어 IP ban 회로차단기 상태가 통째로 지워진다** (→ 6-5). 서비스명을 항상 명시할 것.

#### 6-5. 🚨 절대 쓰면 안 되는 명령 (외우지 말고 **배포 전에 이 표를 다시 볼 것**)

**A. docker 계열**

```bash
# ❌❌ 절대 금지 — 볼륨까지 삭제
docker compose down -v
```

```bash
# ❌ 위험 — 전체 정지. 자동매매가 포지션을 든 채로 멈추고, 그동안 손절이 아예 없다 (6-0)
docker compose down
```

```bash
# ❌ 위험 — IP ban 중이면 회로차단기가 통째로 지워진다 (아래 설명)
docker compose restart redis
docker compose up -d               # ← 서비스명 없이 치면 바뀐 서비스를 전부 재생성
redis-cli FLUSHALL
```

```bash
# ❌ 위험 — 안 쓰는 것처럼 보이는 이미지/볼륨을 지운다. 롤백용 옛 이미지가 날아간다
docker system prune -a
docker volume prune
```

🚨 **왜 `redis` 재시작이 위험한가**: `redis` 서비스에는 **볼륨이 없다**
(`backend/docker-compose.yml:18-24` — `db` 와 달리 `volumes:` 절 자체가 없다) = **영속화 0.**
그런데 IP ban 회로차단기는 **프로세스 메모리(1차) + Redis(2차)** 에만 산다
(`client.py:53-59, 224, 237-253`). 즉 **redis 를 재시작하면 「지금 ban 중」이라는 사실이 사라진다.**
그 상태에서 워커들이 정상 속도로 Binance 를 두드리면 **ban 기간 중의 요청이 다시 카운트되어
ban 이 연장된다** — 2026-08-26 사고와 정확히 같은 경로다 (→ 8-1).

**B. git 계열 — 🚨 이 저장소는 worktree 를 공유한다**

```bash
# ❌❌ 절대 금지 — worktree 공유 저장소에서 다른 작업의 변경을 통째로 삼키고 되돌리기 어렵다
git stash
git stash pop
```

```bash
# ❌❌ 절대 금지 — VPS 에 사장님이 만든 추적되지 않는 조사 스크립트 31개가 있다. 전부 지워진다
git clean -fd
git clean -fdx
```

```bash
# ❌ 위험 — 복구 지점이 사라진다. 되돌릴 땐 6-1 ⑤ 의 git checkout <해시> 를 쓸 것
git reset --hard
git reset --hard origin/main
```

```bash
# ❌❌ 절대 금지 — 원격 이력을 덮어쓴다. 다른 PC/worktree 의 작업이 사라진다
git push -f
git push --force
```

🚨 **`git pull` 이 실패했을 때 `stash` 로 밀어내고 싶어지는 순간이 가장 위험하다.**
VPS 는 지금 **추적 파일 수정이 0건, 추적되지 않는 파일이 31개**다 (`git status --porcelain` 실측).
이 상태에서 `--ff-only` 가 실패한다면 그건 「로컬 변경」때문이 아니라 **이력이 갈라진 것**이므로
`stash` 로 해결되지 않는다. **멈추고 원인을 먼저 본다.**

**C. 애플리케이션 계열**

- 🚨 `clear_ip_ban()` — **실제 ban 중에 쓰면 ban 이 연장된다** (`client.py:306-308` 주석).
- 🚨 `alembic downgrade` — Neon 실데이터에서 컬럼/테이블이 삭제될 수 있다 (→ 6-3).

`OPERATIONS.md:328-331` 에 `down -v` 예시가 있는데 이는 **로컬 개발 초기화**용이다.
운영 VPS 에서 쓰면 안 된다.

#### 6-6. 배포가 실제로 됐는지 판정하는 법

🚨 **`docker exec ... grep` 으로 코드를 확인하는 것은 「디스크」를 보는 것이다.**
bind mount 라서 `git pull` 만 해도 파일은 이미 새 코드다 — **재시작하지 않았어도 grep 은 통과한다.**
반드시 **프로세스 시작 시각 vs 파일 수정 시각**으로 판정한다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && echo -n "api   start: " && docker inspect --format "{{.State.StartedAt}}" binance-auto-trader-api && echo -n "sched start: " && docker inspect --format "{{.State.StartedAt}}" binance-auto-trader-scheduler && echo "newest .py:" && find app -name "*.py" -printf "%TY-%Tm-%TdT%TH:%TM %p\n" | sort -r | head -3'
```

2026-09-03 실행 결과 (**정상 배포된 예시**):

```
api   start: 2026-09-03T08:51:26.932467002Z
sched start: 2026-09-03T08:51:57.679240765Z
newest .py:
2026-09-03T08:51 app/services/support_score.py
2026-09-03T08:51 app/services/execution_service.py
2026-09-03T08:25 app/services/tp_sl_orchestrator.py
```

파일 최신 수정(08:51) **≤** 프로세스 시작(08:51:26 / 08:51:57) → **반영됨.**
반대로 파일이 프로세스 시작보다 **나중**이면 → **아직 안 올라간 코드다.**

⚠️ VPS 작업 디렉터리에는 사장님이 조사용으로 만든 추적되지 않는 `.py` 스크립트가 20개 이상 있다
(`git status --porcelain` 실측 = **추적 파일 수정 0건 / 추적되지 않는 파일 31개**).
`git pull` 시 충돌을 일으키진 않지만 `find app -name "*.py"` 결과에는 섞이지 않는다
(전부 `backend/` 직속이라 `app/` 밖). 🚨 **`git clean` 을 쓰면 이 31개가 전부 사라진다** (→ 6-5).

##### 🚨 배포 후 3분 확인 — 「명령을 쳤다」로 끝내지 마라

손절이 `scheduler` 안에 있으므로 (→ 6-0), **재시작이 반쯤 실패한 것을 모르고 지나가는 것**이
이 시스템에서 가장 비싼 실수다. 배포 직후 아래를 순서대로 본다.

**① 네 컨테이너가 다 살아 있고 크래시 루프가 아닌지**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps api scheduler user-stream mark-price-stream'
```

→ 넷 다 `Up ...` 이어야 한다. `Restarting` / `Exited` 가 하나라도 있으면 **실패다.**

⚠️ `docker compose ps` 는 재시작 **횟수**를 보여주지 않는다. 크래시 루프는 아래로 본다
(같은 명령을 30초 간격으로 두 번 쳐서 `restarts` 숫자가 **늘어나면** 루프다):

```bash
ssh root@159.65.137.250 'for c in api scheduler user-stream mark-price-stream; do docker inspect --format "{{.Name}} restarts={{.RestartCount}} status={{.State.Status}}" binance-auto-trader-$c; done'
```

**② 부팅 중 예외로 죽지 않았는지**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 5m api scheduler | grep -E "Traceback|ImportError|ModuleNotFoundError|ProgrammingError|UndefinedColumn|CRITICAL"'
```

→ 🚨 `UndefinedColumn` / `ProgrammingError` 가 보이면 **마이그레이션을 빠뜨린 것이다** → 6-3.
→ 🚨 `ModuleNotFoundError` 가 보이면 **`requirements.txt` 가 바뀐 배포였다** → 6-4.

**③ 두뇌가 실제로 일을 시작했는지** (로그가 조용하면 `restart` 는 됐는데 워커가 안 도는 것이다)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 5m scheduler | grep -E "\[stage-trigger\]" | tail -3'
```

→ `[stage-trigger] 완료: 활성=N 검사=N ...` 가 **새로 찍히고 있어야** 한다.

**④ API 가 살아 있는지**

```bash
ssh root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

**⑤ 배포가 ban 을 유발하지 않았는지** (재시작 직후 캐시가 비어 스캔이 몰릴 수 있다)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

##### 🚨 즉시 롤백해야 하는 신호 (하나라도 해당되면 6-1 ⑤ 를 실행한다)

| 신호 | 뜻 |
|---|---|
| `scheduler` 가 `Restarting` 이거나 `restarts` 가 계속 증가 | 크래시 루프 = **손절이 없는 상태가 계속된다** |
| 로그에 `Traceback` 이 반복 | 워커가 매 주기 죽는다 |
| `[stage-trigger]` 가 5분 넘게 안 찍힘 | 두뇌가 멈췄다 |
| `/health` 가 응답 없음 | api 사망 |
| ban 키에 숫자가 생김 | IP ban 진입 → 🚨 **롤백보다 먼저, 더 이상 재시작하지 마라.** 재시작은 회로차단기를 지운다 (→ 6-5) |

🚨 **판단이 안 서면 롤백이 정답이다.** 옛 코드는 최소한 어제까지 돌던 코드다.

---

### 7. 로그 보는 법 + 자주 쓰는 grep 패턴

#### 기본형

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 10m --tail 50 scheduler'
```

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h api scheduler'
```

| 목적 | 명령 조각 |
|---|---|
| 최근 10분 | `--since 10m` |
| 특정 시각 이후 | `--since 2026-09-03T08:00:00` |
| 실시간 추적 | `-f --tail 50` (🚨 SSH 세션이 안 끊기니 Ctrl+C 로 나올 것) |
| 여러 서비스 동시 | `docker compose logs --since 30m api scheduler user-stream` |
| 에러만 | 아래 grep |

#### 실전 grep 패턴 (전부 위 로그 표본에서 실제 형식 확인)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h scheduler | grep -E "ERROR|CRITICAL|Traceback"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2h scheduler | grep -E "Fix116|IP ban|418|ip_banned_skip"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2h scheduler | grep -E "Fix124|weight budget|weight_throttled"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h scheduler | grep -E "\[stage-trigger\]"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 6h scheduler | grep -E "진입|청산|손절|익절"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 1h api | grep -vE "GET /(health|api/v1/(strategies|exchange-accounts)) HTTP.* 200 OK"'
```

(마지막 것: api 로그는 대시보드 폴링 200 OK 로 도배되므로 **정상 요청을 빼고** 봐야 한다.
실제 표본에서 `/health`, `/api/v1/strategies`, `/api/v1/exchange-accounts`,
`/api/v1/admin/system-health`, `/api/v1/reentry-alerts` 등이 초 단위로 찍힌다.)

정상 동작 표본 (2026-09-03 09:03 UTC scheduler):

```
[app.workers.stage_trigger_worker] [stage-trigger] 완료: 활성=8 검사=8 발동=0 ban_skip=0 오류=0
[app.services.risk_service] [risk] Fix183/184 TP1 옵션 적용 strategy=2005 TP1_override=15.00 ...
[app.workers.auto_add_margin_worker] [auto_add_margin] 금액 방식 = 고정 300 USDT
```

`ban_skip=0` 이면 IP ban 이 아니다. **0 이 아니면 즉시 아래 8장을 볼 것.**

#### Redis 로 직접 상태 조회 (로그보다 빠름)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

→ **빈 값이면 ban 아님.** (2026-09-03 실측: 빈 값 = 정상)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && m=$(date -u +%Y%m%d%H%M) && docker compose exec -T redis redis-cli GET "binance:weight:$m"'
```

2026-09-03 실측 최근 4분: `340`, `538`, `574`, `219`
→ 스캔 예산 `1500`, 실제 한도 `2400` 대비 **약 14~24%. 매우 여유 있음.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && m=$(date -u +%Y%m%d%H%M) && docker compose exec -T redis redis-cli HGETALL "binance:reqcount:$m"'
```

2026-09-03 실측 (1분): `/fapi/v1/klines|200` = 162, `/fapi/v1/ticker/24hr|200` = 3, `/fapi/v2/account|200` = 3

---

### 8. 🚨🚨 IP ban(418) — 새 PC 에서 Binance API 를 직접 때리면 안 되는 이유

#### 8-1. 무슨 일이 있었나 (2026-08-26 사고)

`backend/app/integrations/binance/client.py:637-651` 의 주석이 사고를 그대로 기록하고 있다:

- IP `159.65.137.250` 이 **418 ban** 상태였는데 `peak_break_reversal` 워커가 **2초에 18번** 호출.
- **Binance 는 ban 기간 중의 요청도 카운트해서 ban 을 연장/승격한다.**
- 실측 연장 궤적: `06:08:43 → 06:28:43 → 06:30:44 → 06:34:47` — **스스로 ban 을 계속 밀어냈다.**
- 워커별 가드로는 못 막았다. 워커는 루프 **시작 전에 한 번만** ban 을 확인하고, 루프 도중 ban 이 걸리면
  33개 심볼을 끝까지 두드린다 (`_get_15m_high` 는 418 예외를 **삼키고** `None` 을 반환하며 다음 심볼로 진행).

#### 8-2. 🚨 핵심 — **418 은 「계정」이 아니라 「IP」 ban 이다**

`client.py:53-56`:

> `418 은 「계정」이 아니라 「IP」 ban 이다 → 프로세스/컨테이너 전체가 멈춰야 한다.`

이 한 문장이 새 PC 이전에서 가장 중요한 문장이다.

🚨 **밴은 API 키가 아니라 「나가는 공인 IP」에 걸린다.**
🚨 **그런데 회로 차단기는 Redis(`api_backoff:ip:ban_until_ms`)와 프로세스 메모리에만 산다** —
즉 **VPS 안에서만 공유된다.** 새 PC 는 그 Redis 를 보지 않고(보더라도 IP 가 다르고), 새 PC 의 요청은
**VPS 의 weight 거버너 카운터에도 잡히지 않는다.**

따라서:

| 새 PC 에서 하는 행동 | 결과 |
|---|---|
| VPS 에 SSH 로 붙어서 조회 | ✅ 안전. VPS 의 회로차단기·거버너가 그대로 적용됨 |
| 새 PC 에서 로컬 앱을 띄워 **같은 Neon DB** 를 보게 함 | 🚨🚨 **실계좌로 실제 주문이 나간다.** API 키가 DB 에 암호화되어 있고 `.env` 의 `ENCRYPTION_KEY` 로 복호화된다 |
| 새 PC 에서 Binance REST 를 직접 호출 (스크립트, 백테스트, 스캔) | 🚨 **새 PC 의 IP 가 밴을 먹는다.** 사무실/집이 VPS 와 같은 NAT 를 공유하지 않는 한 VPS 는 무사하지만, 집 IP 가 밴되면 새 PC 에서 아무 조사도 못 한다 |
| 새 PC 가 **VPS 와 같은 공인 IP** 로 나감 (예: VPS 를 프록시/터널로 씀) | 🚨🚨🚨 **VPS 의 실거래가 전면 정지된다.** 절대 금지 |

#### 8-3. 지금 살아 있는 방어 장치 (읽고 확인함)

| Fix | 무엇 | 위치 |
|---|---|---|
| **116** | IP ban 전역 회로 차단기. **네트워크로 나가기 직전** 한 곳에서 차단. 1차=프로세스 메모리, 2차=Redis(컨테이너 4개 공유) | `client.py:53-59, 637-664` |
| **119** | 차단기가 만든 **합성 예외**에 `locally_suppressed=True` 를 달아, 그걸 「거래소가 준 새 rate limit」으로 오인해 ban 을 60초씩 재연장하던 **되먹임**을 끊음 | `client.py:44-49, 664, 688` |
| **117** | 전 심볼 24h 티커 공유 캐시 (weight 40 짜리) TTL 30s | `client.py:61-66` |
| **122** | klines 공유 캐시 — **IP ban 최대 원인 제거**. 봉 길이 비례 TTL(1m=5s … 4h=180s) | `client.py:68-79` |
| **118** | 엔드포인트별 호출 계측을 Redis 에 (`binance:reqcount:{분}`). scheduler 는 `/metrics` 가 없어 Prometheus 로 안 보이므로 이게 유일한 눈 | `client.py:81-86, 177-219` |
| **124** | **weight 거버너** — 「스캔은 버려도 되지만 주문은 절대 막으면 안 된다」. 한도 2400/분, 스캔 예산 **1500/분**. 주문·포지션·계정·마진·레버리지는 **항상 통과** | `client.py:88-118, 666-690` |
| **125** | weight 를 실제 규칙대로 산출 (klines 는 `limit` 에 따라 1/2/5/10, ticker24h 는 symbol 지정 시 1) — 과대평가로 정상 스캔을 막던 것 수정 | `client.py:120-149` |
| **127** | **차단된 요청의 weight 는 되돌린다**(`sign=-1`). 이전엔 차단분까지 누적 → 카운터가 부풀고 → 더 차단하고 → 더 부푸는 악순환. 실측 426회/분(≈450 weight)인데 표본이 **2135** 까지 치솟아 스캔의 18%(274건)를 오차단 | `client.py:668-679, 150-163` |

거버너가 **차단하는 대상**(`_SCAN_ENDPOINTS`, `client.py:110-118`):
`/fapi/v1/klines`, `/fapi/v1/ticker/24hr`, `/fapi/v1/premiumIndex`, `/fapi/v1/ticker/price`, `/fapi/v1/ticker/bookTicker`
→ **주문 관련 엔드포인트는 이 집합에 없다 = 절대 막히지 않는다.** 설계가 옳다.

#### 8-4. 🚨 새 PC 안전 수칙 (반드시 지킬 것)

1. 🚨 **새 PC 에서 `scheduler` / `user-stream` / `mark-price-stream` 을 절대 띄우지 마라.**
   같은 Neon DB 를 보는 두 번째 두뇌가 생기면 **같은 포지션에 중복 주문**이 나간다.
   (VPS 의 동시보유 상한·중복 진입 가드는 **DB 상태 기준**이라 두 프로세스가 동시에 판정하면 둘 다 통과할 수 있다.
   ⚠️ 이 경합 시나리오는 코드로 확인하지 못했다 — 하지만 안전 쪽으로 가정해야 한다.)
2. 🚨 **로컬에서 Binance REST 를 직접 호출하는 스크립트를 돌리지 마라.**
   조회조차도 weight 를 먹고, 그 weight 는 VPS 거버너에 **보이지 않는다.**
3. ✅ **조사·분석은 전부 VPS 안에서 `docker compose exec` 로 하라.** 그러면 회로차단기와 거버너가
   그대로 적용된다.
4. ✅ 데이터만 필요하면 **Neon DB 만 읽어라** (Binance 를 안 거친다). Neon 은 IP 밴과 무관하다.
5. 🚨 **로컬 개발을 꼭 해야 한다면 testnet 을 써라.**
   `BINANCE_FUTURES_TESTNET_BASE_URL=https://testnet.binancefuture.com`
   (`backend/.env.example:18`, `backend/app/core/config.py:17`).
   🚨 단, **mainnet/testnet 은 `.env` 가 아니라 DB `exchange_accounts.is_testnet` 컬럼으로 갈린다.**
   `.env` 만 바꿔서는 testnet 이 되지 않는다. 새 PC 에서는 **testnet 전용 계정 행을 따로 만들어야 한다.**
6. 🚨 **이미 ban 을 먹었다면 `clear_ip_ban()` 을 쓰지 마라.**
   `client.py:306-308` 주석: `운영자 강제 해제 (실 ban 중 사용 금지 — ban 이 연장된다!)`.
   기다리는 것이 유일한 해법이다.
7. 새 PC 가 밴 상태인지 확인하려면 **VPS 가 아니라 새 PC 에서** 아래를 **정확히 한 번만** 실행한다.
   `/fapi/v1/ping` 은 weight **1** 의 가장 가벼운 공개 엔드포인트다.

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -m 10 https://fapi.binance.com/fapi/v1/ping
   ```

   | 응답 | 뜻 | 해야 할 일 |
   |---|---|---|
   | `200` | 이 IP 는 정상 | 없음 |
   | `429` | rate limit 경고 | **즉시 멈추고** 최소 몇 분 대기 |
   | `418` | 🚨 **이 IP 가 ban** | **아무것도 더 치지 마라.** 재시도 자체가 ban 을 연장한다 (8-1 참조) |
   | `000` / 타임아웃 | 네트워크 문제 (ban 아님) | 인터넷 확인 |

   🚨 **연타·루프·`watch` 금지.** 연타가 바로 2026-08-26 사고의 원인이었다.
   418 을 받았다면 다음 확인은 **최소 수십 분 뒤에 한 번**만.

   🚨🚨 **이 한 번조차도, 새 PC 가 VPS 와 같은 공인 IP 로 나가는 상황이면 치지 마라.**
   (VPS 를 프록시·VPN·SSH 터널로 쓰고 있거나, 사무실 회선이 VPS 와 같은 출구를 공유하는 경우.)
   그 경우 이 `curl` 의 weight 가 **VPS 계정 몫으로 잡히고**, VPS 의 거버너에는 안 보인다.
   현재 나가는 IP 는 이렇게 확인한다 (Binance 를 안 거친다 = 안전):

   ```bash
   curl -s -m 10 https://api.ipify.org; echo
   ```

   → 결과가 `159.65.137.250` 이면 🚨 **VPS 와 같은 IP 다. Binance 를 절대 직접 치지 마라.**

---

### 9. SSH 키 — 새 PC 로 옮기는 절차

현 PC 상태:

| 파일 | 확인 |
|---|---|
| `~/.ssh/id_ed25519` (개인키) | 존재. **내용은 읽지도 출력하지도 않았다** |
| `~/.ssh/id_ed25519.pub` (공개키) | 존재 |
| `~/.ssh/config` | **없음** (그래서 매번 `root@159.65.137.250` 을 직접 친다) |
| 인증에 실제로 쓰이는 키 | `id_ed25519` — `ssh -v` 가 `Server accepts key: /c/Users/user/.ssh/id_ed25519` 로 확인 |
| 지문 | `SHA256:cbFAdSNFpCEZRnC/fxKsDmI0+4w2uTSUgls9XWbC4KI` |

⚠️ 현 PC 의 `id_ed25519` 권한이 `-rw-r--r--` (644) 다. Git Bash 라 OpenSSH 가 넘어가 주지만
원칙적으로는 600 이어야 한다.

#### ✅ 권장: 새 PC 에서 **새 키를 만든다** (개인키가 네트워크를 절대 안 탄다)

새 PC 에서:

```bash
ssh-keygen -t ed25519 -C "sajangnim-newpc-2026-09" -f ~/.ssh/id_ed25519
```

```bash
cat ~/.ssh/id_ed25519.pub
```

🚨 위 `.pub` **한 줄**(공개키 — 노출되어도 안전하다)을 복사한 뒤, **현 PC 에서** VPS 에 등록한다:

🚨🚨 **이 작업의 유일한 실패 모드는 「VPS 에서 영구히 잠기는 것」이다.** 잠기면 실자금이 도는
자동매매를 손댈 수 없게 된다. 아래 안전 절차를 그대로 지킬 것.

**① 현 PC 의 SSH 세션을 하나 열어 두고, 작업이 다 끝날 때까지 절대 닫지 마라.**
(뭔가 잘못돼도 이 살아 있는 세션으로 고칠 수 있다. 닫으면 그 기회가 사라진다.)

**② 등록 전에 지금 등록된 키를 세어 둔다.**

```bash
ssh root@159.65.137.250 'wc -l < ~/.ssh/authorized_keys && cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak.$(date +%F)'
```

**③ 등록한다. 🚨 `>>` 인지 눈으로 두 번 확인하라.**

```bash
ssh root@159.65.137.250 'echo "여기에_새PC의_pub_한줄_붙여넣기" >> ~/.ssh/authorized_keys'
```

🚨🚨 **`>` 를 하나만 쓰면(`> ~/.ssh/authorized_keys`) 기존 키가 전부 지워지고 즉시 잠긴다.**
`>>` (두 개) 여야 「추가」다. 이 한 글자가 이 문서에서 가장 위험한 한 글자다.

**④ 줄 수가 정확히 1 늘었는지 확인한다.** (②의 숫자 + 1)

```bash
ssh root@159.65.137.250 'wc -l < ~/.ssh/authorized_keys'
```

**⑤ 새 PC 에서 접속이 되는 것을 확인한 뒤에야** ①의 세션을 닫는다.

🚨 **되돌리는 법**: ②에서 뜬 백업으로 복구한다 (①의 세션이 살아 있을 때만 가능하다).

```bash
ssh root@159.65.137.250 'cp ~/.ssh/authorized_keys.bak.$(date +%F) ~/.ssh/authorized_keys && wc -l < ~/.ssh/authorized_keys'
```

🚨 **그래도 잠겼다면**: DigitalOcean 콘솔의 **Recovery Console(웹 터미널)** 이 유일한 통로다.
SSH 키와 무관하게 붙을 수 있지만 **root 비밀번호가 필요**하다. 🚨 **새 PC 로 옮기기 전에
DO 계정 로그인과 root 비밀번호(또는 비밀번호 재설정 권한)를 확보해 둘 것.**
⚠️ 확인 못 함: 현재 DO 계정에 root 비밀번호가 설정되어 있는지는 DO 콘솔에서만 알 수 있다.

🚨 이 명령들은 **VPS 의 보안 설정을 바꾼다.** 나는 읽기 전용 지시를 받았으므로 실행하지 않았다.
**사장님이 직접 실행하실 것.**

새 PC 에서 **접속하기 전에** 먼저 호스트키 지문을 대조한다:

```bash
ssh-keyscan -t ed25519 159.65.137.250 2>/dev/null | ssh-keygen -lf -
```

기대 출력 (2026-09-03 현 PC 에서 재확인함):

```
256 SHA256:NYbjWuJ7a5pBfXRi9E9ys7yyDqWlaupLiuwH12Q2toM 159.65.137.250 (ED25519)
```

지문이 다르면 **중간자 공격 의심 — 접속하지 말 것.**

지문이 맞으면 접속한다:

```bash
ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname && uptime'
```

첫 접속에서 `Are you sure you want to continue connecting?` 가 뜨면 화면의 지문이 위와 같은지
한 번 더 보고 `yes`.

🚨 **이 문서의 다른 명령들이 쓰는 `-o StrictHostKeyChecking=no` 는 이 확인을 건너뛴다.**
편의를 위한 것이므로 **첫 접속만큼은 반드시 그 옵션 없이** 위 순서대로 하고,
`~/.ssh/known_hosts` 에 등록된 뒤에 나머지 명령을 쓸 것.

#### 대안: 기존 키를 그대로 옮긴다

정말 옮겨야 한다면 — 🚨 **개인키는 절대 채팅·이메일·클라우드 드라이브·GitHub 에 올리지 마라.**
USB 등 물리 매체로만 옮긴다. 옮긴 뒤 새 PC 에서:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
```

```bash
chmod 600 ~/.ssh/id_ed25519 && chmod 644 ~/.ssh/id_ed25519.pub
```

옮긴 뒤 USB 의 원본은 지운다. (Windows 네이티브 OpenSSH 를 쓸 경우 `icacls` 로 상속을 끊어야 할 수 있다.)

#### 선택: `~/.ssh/config` 로 타이핑 줄이기 (새 PC 에서)

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
```

🚨 **`>>` 다.** `>` 로 쓰면 기존 `~/.ssh/config` 의 다른 호스트 설정이 전부 날아간다.
(새 PC 라 지금은 비어 있겠지만, 나중에 다시 실행할 때를 대비해 습관을 들일 것.)

```bash
printf 'Host trader\n    HostName 159.65.137.250\n    User root\n    IdentityFile ~/.ssh/id_ed25519\n    ServerAliveInterval 30\n' >> ~/.ssh/config
```

⚠️ **두 번 실행하면 `Host trader` 블록이 두 개가 된다.** OpenSSH 는 먼저 나온 것을 쓰므로 당장은
동작하지만 헷갈리니, 다시 실행하기 전에 `grep -n "Host trader" ~/.ssh/config` 로 이미 있는지 볼 것.

```bash
chmod 600 ~/.ssh/config
```

그러면 `ssh trader` 만으로 접속된다. (`mkdir -p` 를 빼면 `~/.ssh` 가 없는 새 PC 에서 `>>` 가
`No such file or directory` 로 실패한다.)

⚠️ 이 문서의 나머지 명령은 전부 `root@159.65.137.250` 을 그대로 쓴다. `config` 를 만들었다면
`ssh trader ...` 로 바꿔 읽으면 된다 — **`scp` 도 `scp trader:~/... ` 형태로 동작한다.**

---

### 10. 백업 정리 — 무엇이 어디에 백업되는가

| 대상 | 백업되나 | 어디에 | 실제 상태 |
|---|---|---|---|
| **Neon DB (진짜 실거래 데이터)** | Neon 자체 기능에만 의존 | Neon 클라우드 | ⚠️ **보존 정책 확인 못 함** (Neon 콘솔 필요) |
| 로컬 `db` 컨테이너 | 예, `db-backup` 이 매일 | `~/binance-auto-trader/backend/db_backups/` | 🚨 **내용이 비어 있다 (505 바이트).** 무의미 |
| `.env` (`ENCRYPTION_KEY` 등) | ❌ **백업 없음** | — | 🚨 이게 없으면 DB 의 API 키를 **영원히 복호화 못 한다** |
| 코드 | 예 | GitHub `herosys1-crypto/binance-auto-trader` | ✅ VPS HEAD `ded22f3` == main |
| Redis | ❌ 영속화 없음 (`volumes:` 자체가 없음) | — | 🚨 재시작하면 캐시·**IP ban 회로차단기 상태가 소실**된다. 평시엔 무해하지만 **ban 중에는 위험하다** — ban 을 잊고 다시 두드려 ban 을 연장한다 (→ 6-5) |

`db-backup` 설정 (`backend/docker-compose.yml:114-133`):
`SCHEDULE=@daily`, `BACKUP_KEEP_DAYS=7`, `BACKUP_KEEP_WEEKS=4`, `BACKUP_KEEP_MONTHS=6`,
`POSTGRES_EXTRA_OPTS="-Z6 --schema=public --blobs"`, 대상 `POSTGRES_HOST=db`(← 로컬, **Neon 아님**).

🚨🚨 **새 PC 이전에서 가장 위험한 단일 지점: `backend/.env` 의 `ENCRYPTION_KEY`.**
Binance API 키는 Neon DB 의 `exchange_accounts.api_key_enc` 에 **암호화**되어 저장되고
(`backend/app/api/v1/exchange_accounts.py:103,226` 에서 `encrypt_text`),
`decrypt_text(account.api_key_enc)` 로 복호화된다 (`app/api/v1/analysis.py:50` 등
**`.py` 파일 60개 / 247줄**에서 호출 — 2026-09-03 재실측:
`grep -rl "decrypt_text" backend/app --include=*.py | wc -l` → `60`,
`grep -rn "decrypt_text" backend/app --include=*.py | wc -l` → `247`).
**`ENCRYPTION_KEY` 를 잃으면 DB 를 그대로 갖고 있어도 거래를 못 한다.**
VPS 의 `.env` 는 git 에 없고 백업도 안 된다 — VPS 디스크가 유일한 사본이다.
2026-09-03 실측으로 확인했다: `find ~ -maxdepth 3 -name ".env*"` 결과가
`/root/binance-auto-trader/backend/.env` **한 개뿐**이다(나머지는 `.example` / `.template`).
🚨 **즉 이 파일 하나가 날아가면 계정의 Binance API 키를 되살릴 방법이 없다.**
새 PC 셋업의 **첫 단계**로 이 파일 사본을 안전한 곳에 확보해 두는 것이 좋다(아래 `scp`).

⚠️ 부수적으로, 이 `.env` 의 권한이 `-rw-r--r--`(644)라 **모든 로컬 사용자가 읽을 수 있다.**
현재 VPS 는 `root` 단독 사용이라 당장의 위험은 낮지만 원칙적으로는 `600` 이어야 한다.
(변경은 사장님 판단 — 나는 읽기 전용이라 실행하지 않았다: `chmod 600 ~/binance-auto-trader/backend/.env`)

VPS `.env` 에 들어 있는 **키 이름 목록** (값은 절대 옮기지 않았다):

```
ACCESS_TOKEN_EXPIRE_MINUTES   ALLOWED_SYMBOLS_CSV   ALLOW_DUPLICATE_SYMBOL_STRATEGIES
BINANCE_FUTURES_BASE_URL      BINANCE_FUTURES_TESTNET_BASE_URL
DAILY_LOSS_LIMIT_USDT         DATABASE_URL          ENABLE_METRICS
ENCRYPTION_KEY                HEARTBEAT_INTERVAL_HOURS   JWT_ALGORITHM
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT   MAX_LEVERAGE
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE     MIN_LIQUIDATION_DISTANCE_PCT
POSTGRES_PASSWORD             REDIS_URL             SECRET_KEY
SENTRY_DSN  SENTRY_ENV  SENTRY_PROFILES_SAMPLE_RATE  SENTRY_TRACES_SAMPLE_RATE
TELEGRAM_BOT_TOKEN            TELEGRAM_CHAT_ID      TEST_DATABASE_URL
WALLET_LIMIT_PCT
```

(조회 명령: `grep -oE "^[A-Za-z_][A-Za-z0-9_]*=" .env | tr -d "="` — **값은 출력하지 않는다.**)

#### 🚨🚨🚨 10-A. 확인된 비밀 유출 — 운영 `SECRET_KEY` 가 **공개** GitHub 저장소에 평문으로 있다

**이것이 이 문서 전체에서 가장 급한 항목이다. 새 PC 이전보다 먼저 조치해야 한다.**

2026-09-03 실측으로 **확인**했다(추측 아님):

| # | 확인한 것 | 방법 | 결과 |
|---|---|---|---|
| 1 | 저장소가 **공개**다 | `curl https://api.github.com/repos/herosys1-crypto/binance-auto-trader` | `"private": false`, `"visibility": "public"` |
| 2 | `SECRET_KEY` **값**이 평문으로 커밋되어 있다 | `HANDOFF-2026-04-30-NEXT-SESSION.md:197` 및 `:210` (git 추적 파일) | 값이 그대로 적혀 있음 |
| 3 | 그 값이 **지금 운영에서 쓰는 값과 동일**하다 | VPS `.env` 의 `SECRET_KEY` 와 위 파일의 값을 **md5 로만** 비교 | **md5 일치** (값은 어느 쪽도 출력하지 않았다) |
| 4 | `SECRET_KEY` 는 **JWT 서명키**다 | `backend/app/core/security.py:45,49` — `jwt.encode(payload, settings.secret_key, ...)` / `jwt.decode(...)` | 로그인 토큰을 이 키로 서명·검증 |
| 5 | API 가 **인터넷에 열려 있다** | 내 PC(외부)에서 `curl http://159.65.137.250:8000/health` | `200` (1-(2) 의 8000 OPEN 과 동일) |

🚨 **연결하면**: 누구든 공개 저장소에서 이 키를 읽어 **유효한 로그인 토큰을 직접 위조**할 수 있고,
인터넷에 열린 8000 포트로 **실자금 자동매매 API 에 인증된 상태로 접근**할 수 있다.
(나는 유출을 **확인만** 했고 토큰 위조나 인증 시도는 **하지 않았다.**)

✅ **함께 확인한 것 — 다행인 부분** (같은 방식으로 md5 비교):

| 값 | 상태 |
|---|---|
| Neon DB 비밀번호 | `HANDOFF-2026-04-28-HOME-TO-OFFICE.md:27,138,179` 에 **옛 값이 평문 커밋**되어 있으나, VPS 현재 값과 **md5 불일치 = 이미 교체됨.** 그래도 파일은 지우는 것이 맞다 |
| `TELEGRAM_BOT_TOKEN` | 저장소에는 `<NEW_...>` **자리표시자만** 있다. 실제 값 커밋 없음 |
| `ENCRYPTION_KEY` | 저장소에 실제 값 커밋 **없음** (`.env.example` 은 자리표시자) |
| Binance API 키/시크릿 | 저장소에 커밋 **없음** (Neon DB 에 암호화 저장) |

🚨 **Grafana admin 비밀번호도 `backend/docker-compose.yml:99` (`GF_SECURITY_ADMIN_PASSWORD`) 에
평문 커밋되어 공개 저장소에 있다**(3장 참조). 값은 짧고 흔한 형태라 **사전 공격에 즉시 뚫린다.**
Grafana 는 127.0.0.1 바인딩이라 당장 외부 노출은 아니지만,
**같은 비밀번호를 다른 곳에 재사용했다면 그쪽이 위험하다.**

🚨 **이 문서에는 그 값을 옮겨 적지 않는다.** 확인이 필요하면 저장소 파일에서 직접 볼 것
(`grep -n GF_SECURITY_ADMIN_PASSWORD backend/docker-compose.yml`). 핸드오프 문서는 사장님이
여러 곳에 복사·보관할 가능성이 높으므로 **값이 아니라 「어디에 있는가」만 적는 것이 원칙이다.**

**사장님이 직접 하실 조치 (순서대로).** 🚨 나는 읽기 전용 지시를 받았으므로 **하나도 실행하지 않았다.**

1. **`SECRET_KEY` 를 새로 발급해 VPS `.env` 에 교체한다.** (가장 급함)

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   🚨 **`ENCRYPTION_KEY` 는 절대 함께 바꾸지 마라.** 그것을 바꾸면 DB 의 `api_key_enc` 를
   복호화할 수 없게 된다(10장 본문). **`SECRET_KEY` 와 `ENCRYPTION_KEY` 는 완전히 다른 키다.**
   `SECRET_KEY` 교체의 유일한 부작용은 **기존 로그인 토큰 전부 무효화 = 재로그인**뿐이다.
2. `.env` 를 고쳤으므로 **`restart` 가 아니라 재생성**이어야 반영된다 (6-1 의 함정과 동일):

   ```bash
   cd ~/binance-auto-trader/backend && docker compose up -d --force-recreate api
   ```
3. **8000·9090·6380 포트를 인터넷에서 닫는다** (1-(2) 참조). 키를 바꿔도 포트가 열려 있으면
   다음 유출 때 같은 일이 반복된다.
4. **Grafana admin 비밀번호를 바꾸고**, `docker-compose.yml` 의 평문을 `.env` 주입으로 옮긴다
   (`docker-compose.production.yml` 이 이미 그렇게 권고한다).
5. **공개 저장소에서 비밀이 적힌 핸드오프 파일들을 지운다** — `HANDOFF-2026-04-28-HOME-TO-OFFICE.md`,
   `HANDOFF-2026-04-30-NEXT-SESSION.md`.
   🚨 **파일을 지우는 커밋만으로는 git 이력에 그대로 남는다.** 이력에서 지우려면 저장소를
   **비공개로 전환**하거나 히스토리 재작성이 필요하다. **가장 확실하고 빠른 조치는 「키 교체」(1번)이며,
   이력 정리는 그 다음이다.** 이미 공개된 값은 「유출된 것」으로 간주하고 전부 새로 발급하는 것이 원칙이다.

**나중에 재검증하는 법** (값을 화면에 띄우지 않고 md5 만 비교):

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && sed -n "s/^SECRET_KEY=//p" .env | tr -d "\n\r " | md5sum'
```

교체 후 이 md5 가 `bf9c11c702702c34890def0d6ccbd4b6` (= 공개 저장소에 있는 값의 md5) 와
**달라야** 정상이다. 같으면 아직 안 바뀐 것이다.

🚨 **새 PC 셋업 중에는 위 공개 저장소 핸드오프 파일들의 `.env` 예시를 그대로 복사해 쓰지 마라.**
거기 적힌 Neon 비밀번호는 이미 만료된 값이라 **접속이 안 되고**, `SECRET_KEY` 는 유출된 값이라
**쓰면 안 된다.** `.env` 는 반드시 아래 「어디서 얻는가」 절차대로 VPS 에서 직접 받는다.

**어디서 얻는가**:

| 키 | 출처 |
|---|---|
| `DATABASE_URL` | Neon 콘솔 → 프로젝트 `ep-…(엔드포인트 ID 마스킹)` → Connection string |
| `ENCRYPTION_KEY` | 🚨🚨 **VPS `~/binance-auto-trader/backend/.env` 가 유일한 사본이고 재생성이 불가능하다.** 바꾸면 DB `exchange_accounts.api_key_enc` 의 기존 암호문을 **영원히 못 읽는다** = 거래 불가. **절대 새로 만들지 마라, 그대로 복사해 온다.** |
| `SECRET_KEY` | ⚠️ **재생성 가능하다** — JWT 서명키일 뿐이라 바꿔도 부작용은 **재로그인**뿐이다(`app/core/security.py:45,49`). 🚨 그리고 **현재 값은 공개 저장소에 유출되어 있으므로 반드시 새로 발급해야 한다 → 10-A 참조.** 복사해 오지 마라 |
| `TELEGRAM_BOT_TOKEN` / `CHAT_ID` | Telegram BotFather / 대화방 |
| `SENTRY_DSN` | Sentry 프로젝트 설정 |
| Binance API 키 | 🚨 `.env` 에 **없다.** Neon DB 에 암호화 저장 → 웹 UI 의 거래소 계정 화면에서 관리 |

`.env` 를 새 PC 로 옮기는 방법은 백업이 없으므로 VPS 에서 직접 가져오는 것뿐이다.
🚨 **아래 명령은 비밀 값을 화면에 띄우지 않고 파일로만 받는다. 사장님이 직접 실행하실 것.**

```bash
scp root@159.65.137.250:~/binance-auto-trader/backend/.env ~/Downloads/vps.env.backup
```

🚨 받은 파일은 즉시 안전한 곳(암호화된 USB, 패스워드 매니저의 안전 노트)에 넣고
`~/Downloads` 에서 지운다. 절대 git 에 커밋하지 마라.

🚨🚨 **이 파일을 옮기는 방법에 대한 금지 사항** — 이 저장소는 실제로 이 규칙을 어겨서
운영 `SECRET_KEY` 가 공개 저장소에 남았다(10-A). 같은 실수를 반복하지 마라:

- ❌ **채팅(카카오톡·슬랙·디스코드)·이메일·문자로 보내지 마라.** AI 에이전트에게 붙여넣는 것도 안 된다.
- ❌ **구글 드라이브·원드라이브·드롭박스 등 클라우드에 올리지 마라.**
- ❌ **git 저장소 안(하위 디렉터리 포함)에 두지 마라.** 핸드오프 `.md` 에 값을 적는 것도 금지다.
- ❌ **화면 캡처·화면 공유에 띄우지 마라.**
- ✅ 허용: 위 `scp`(SSH 암호화 채널로 PC→PC 직접), 암호화된 USB, 패스워드 매니저의 안전 노트.

`scp` 가 안전한 이유는 값이 **SSH 로 암호화되어 두 기기 사이에서만** 오가고 제3자 서버를
거치지 않기 때문이다. 위 ❌ 항목들은 전부 제3자 서버에 평문 사본을 남긴다.
✅ `.gitignore:2-10` 이 `.env`, `.env.*`, `backend/.env`, `backend/.env.*` 를 모두 제외하고
`!.env.example` / `!backend/.env.example` / `!backend/.env.production.template` 만 예외로 두는 것을 확인했다.
🚨 단, 위 `scp` 처럼 **저장소 밖 다른 이름**(`vps.env.backup`)으로 받은 파일이 저장소 안에 들어오면
이 규칙에 안 걸린다. 저장소 디렉터리 밖에 두어라.

---

### 11. 새 PC 첫날 체크리스트 (전부 읽기 전용, 안전)

> **선행 조건: 9장의 SSH 키 등록이 끝나 있어야 한다.** 안 되어 있으면 여기 명령은 전부
> `Permission denied (publickey)` 로 실패한다. 그건 고장이 아니라 **키가 아직 없다는 뜻**이다.

```bash
ssh -o ConnectTimeout=15 root@159.65.137.250 'hostname && uptime && df -h /'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && git log --oneline -3 && git rev-parse --abbrev-ref HEAD'
```

```bash
ssh root@159.65.137.250 'curl -s -m 10 http://127.0.0.1:8000/health'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api alembic current'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T redis redis-cli GET "api_backoff:ip:ban_until_ms"'
```

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"strategy_instances:\", db.execute(text(\"select count(*) from strategy_instances\")).scalar())
"'
```

기대값 (2026-09-03 09:20 UTC 실측 — 전 항목 직접 실행해 대조함):

| 확인 | 기대 출력 | 다르면 |
|---|---|---|
| 컨테이너 | **9개 전부 `Up`** | Exit/Restarting 이 있으면 7장 로그부터 |
| 브랜치 / HEAD | `main` / `ded22f3` (또는 그 이후) | 다른 브랜치면 **배포 상태가 아니다** |
| `/health` | `{"status":"ok"}` | api 가 죽었거나 기동 중 |
| alembic | `0034_surge_ladder (head)`, `current == heads` | 다르면 6-3 |
| ban 키 | **빈 값** (아무것도 안 나옴) | 숫자가 나오면 🚨 8장 즉시 |
| `strategy_instances` | 숫자 출력 — **2026-09-03 실측 `1487`** | 0 이나 에러면 🚨 **`db` 컨테이너로 잘못 조회한 것**(2장) |

🚨 마지막 줄이 가장 중요한 자가진단이다. **숫자가 0 이면 데이터가 날아간 게 아니라
빈 로컬 `db` 를 보고 있는 것**이다 (2장의 함정). `1487` 같은 실수(實數)가 나와야 Neon 에 붙은 것이다.

---

### 12. ⚠️ 확인 못 한 것

- **Neon 백업/PITR 보존 기간** — Neon 웹 콘솔에서만 확인 가능. 🚨 VPS 백업이 비어 있으므로 **이것이 유일한 안전망이다. 반드시 확인할 것.**
- **DigitalOcean 클라우드 방화벽** 설정 유무 — DO 콘솔 필요. (다만 6380/9090/8000 은 실제로 외부에서 연결됐다.)
- `scheduler` 의 **재시작 4회의 실제 원인** — 마지막 종료코드가 0, OOM 아님까지만 확인. 과거 3회는 로그가 남아 있지 않아 단정 못 함.
- **load average 3.67(15분) / 2 vCPU 과부하의 원인** — 프로파일링을 하지 않았다.
- **새 PC 로컬 앱과 VPS 가 같은 DB 를 볼 때의 중복 주문 경합** — 코드로 검증하지 않았다. 안전 쪽으로 「금지」로 기술했다.
- **Grafana / Prometheus 대시보드 내용** — 포트만 확인, 화면은 열어보지 않았다.
- `docker-compose.production.yml` 을 **지금 적용하면 무엇이 깨지는지** — 적용은 재시작을 동반하므로(실자금) 시도하지 않았다. 특히 `db` 를 끄면 `db-backup` 의 `depends_on` 이 어떻게 되는지 등은 검증 안 함.
- **8-4 의 `fapi/v1/ping` 응답표** — 명령 형식은 맞지만 **실행하지 않았다.** 이 PC 에서 Binance 를 치는 것 자체가 8장이 금지하는 행동이라 일부러 피했다. 응답 코드의 의미는 Binance 공식 규약(418=IP ban / 429=rate limit)에 따른 것이다.
- **새 PC 에서의 실제 재현** — 이 문서의 명령은 전부 **현 PC + 운영 VPS** 에서 검증했다. 키가 없는 진짜 새 PC 에서 처음부터 돌려본 것은 아니다.
- **DigitalOcean Recovery Console 로 실제 복구가 되는지 / root 비밀번호가 설정돼 있는지** — DO 콘솔 필요. 🚨 9장의 SSH 키 잠금 사고 시 **유일한 탈출구**이므로 새 PC 로 옮기기 전에 반드시 확인할 것.
- **거래소측 스톱 주문이 실제로 하나도 없는지** — 6-0 은 **저장소 코드가 스톱 주문을 걸지 않는다**는 것까지만 확인했다(`place_stop_market_order` 호출처 0곳). 바이낸스 계정에 과거 수동으로 걸어 둔 주문이 남아 있는지는 **조회하지 않았다**(Binance API 호출을 피하기 위해). 🚨 웹 UI 나 바이낸스 앱에서 미체결 주문 목록을 한 번 눈으로 볼 것.
- **롤백(6-1 ⑤ / 6-4 3번)을 실제로 실행해 본 적은 없다** — 명령 자체는 표준 git/docker 동작이지만, 실자금 시스템이라 리허설하지 않았다. 🚨 처음 롤백하는 순간이 실전이 되므로, 배포 전에 반드시 ①(해시 기록)을 해 둘 것.
- **`git pull --ff-only` 가 실패하는 상황** — 현재 VPS 는 추적 파일 수정 0건이라 실패할 이유가 없다. 실패했을 때의 복구는 「멈추고 원인 확인」까지만 기술했고 시나리오별 절차는 만들지 않았다.

---

#### 이 문서에서 **직접 실행해 대조한 것** (2026-09-03 09:15~09:25 UTC 재검증)

`docker compose ls`(CONFIG FILES 1개) / `ls` 양쪽 디렉터리(오버라이드 파일 위치) / `docker compose ps`(9개 Up) /
`docker compose ps --format {{.Ports}}`(8000·9090·6380 이 `0.0.0.0`) / `ufw status`(inactive) /
`git rev-parse` + `git log`(main, ded22f3) / `docker --version`·`docker compose version` /
`alembic current`·`alembic heads`(둘 다 `0034_surge_ladder`) / `curl /health`(ok) /
`find app -name "*.py" -printf`(6-6 판정법) / `redis-cli CONFIG GET requirepass`(빈 값) /
`redis-cli GET api_backoff:ip:ban_until_ms`(빈 값) / `strategy_instances` 카운트(**1487**) /
`ssh-keyscan | ssh-keygen -lf -`(호스트키 지문 일치) / `grep .env` 키 이름 26개(값 미출력) /
`nginx sites-enabled/trader`(80→443, proxy 8000) / 저장소 line 번호 참조 전건
(`docker-compose.yml:99/114-133/119`, `Dockerfile:17`, `.env.example:18`, `config.py:17`,
`client.py:53-56/306-308/637-645`, `.gitignore:2-10`, `exchange_accounts.py:103,226`, `analysis.py:50`).

**위험 검증(적대적 검토)에서 추가로 대조한 것:**
`git status --porcelain`(VPS = 추적 수정 **0건** / 추적되지 않는 파일 **31개**) /
`git reflog`(VPS 는 지금까지 `pull --ff-only` · `pull -q` 로만 갱신) /
`grep -rn "stop_market\|take_profit_market" backend/app`(**호출처 0곳** → 6-0) /
`grep -n "def place_stop_market_order" futures_trade.py`(75, 102행) /
`docker-compose.yml:18-24`(redis 에 `volumes:` 절 없음 = 영속화 0) /
`docker-compose.yml:30-31,44,57,73`(앱 4개가 `env_file: .env`) /
`alembic/env.py:27-30` + `alembic.ini:4`(**DATABASE_URL 없으면 localhost 로 조용히 폴백** → 6-3) /
`.github/workflows/`(파일 1개 = 배포 워크플로 없음, 문서 주장 확인) /
`Dockerfile`(alembic 자동 실행 **없음** = 마이그레이션은 100% 수동).


---

<a id="sec-6"></a>

## 6. 코드 구조 지도 — 어디를 봐야 하나

작성 기준: worktree `.claude/worktrees/infallible-euler-6dc297`, **앱 코드 기준 커밋
`ded22f3`** (= VPS 배포본 — 아래 §9 에 확인 명령 있음).

ℹ️ 그 뒤 이 핸드오프 문서·자산을 저장소에 넣은 `e51d9a8` (chore) 이 얹혀 있어
`git log -1` 은 `e51d9a8` 을 보여준다. **`backend/app` · `backend/alembic` 변경은 0건**
(`git show --stat --name-only e51d9a8`)이므로 아래 줄번호는 전부 그대로 유효하다.

🚨 **`main` 에 push 해도 VPS 는 바뀌지 않는다.** VPS 는 `main` 을 체크아웃한 별도
사본이라, 반영은 VPS 에서 pull + 컨테이너 재시작을 해야 일어난다.
**그 재시작은 사장님만 한다** — 이 문서의 어떤 명령도 배포가 아니다.
줄번호가 안 맞으면 문서가 틀린 게 아니라 **코드가 움직인 것**이니 위 명령으로 먼저 대조한다.

### 🚨 경로 — 새 PC 에서 이 문서의 명령이 안 도는 첫 번째 이유

이 문서를 쓴 환경은 git worktree(`.claude/worktrees/infallible-euler-6dc297`)였지만
**그 경로는 `.gitignore:106` 의 `.claude/worktrees/` 에 걸려 clone 에 따라오지 않는다.**
아래 명령들은 전부 `docs/handoff/RESTORE-2026-09-03.md` **방법 A** 로 clone 한 경로를 쓴다.

```
C:/Users/user/바이낸스/binance-auto-trader          ← 저장소 루트
C:/Users/user/바이낸스/binance-auto-trader/backend  ← 파이썬 앱 루트 (pytest·alembic 은 여기서)
```

다른 경로에 clone 했다면 위 앞부분만 그 경로로 바꿔 읽는다.
Git Bash 기준이고, 경로에 한글이 있으므로 **따옴표를 반드시 붙인다**
(안 붙이면 `No such file or directory`).

clone 이 이 문서와 같은 코드인지 **한 줄로 확인**한다 (2026-09-03 기준
`origin/main` = `e51d9a8`, 그 아래가 코드 커밋 `ded22f3`):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader" && git log --oneline -2 && ls backend/app/services/*.py | wc -l
```

`59` 가 나와야 한다. **더 작게 나오면 checkout 이 옛 상태다** — `git pull` 하고
다시 센다.

> 🚨 `git pull` 전에 `git status` 를 먼저 본다. 커밋 안 된 변경이 남아 있으면
> pull 이 거부되거나 머지가 생긴다. 그때 **`git stash` / `git reset --hard` 로
> 밀어버리지 마라** — 이 저장소는 worktree 를 공유해서 남의 작업까지 사라진다.
> 남길 게 있으면 브랜치를 파서 커밋한다: `git switch -c wip/설명 && git add -A && git commit -m wip`.
> 버려도 되는 게 확실하면 그때만, **무엇을 버리는지 `git status` 로 확인한 뒤** 정리한다.

(옛 PC 의 main 체크아웃이 실제로 `2586555` 에서 멈춰 `services/` 가 53 이었다.
아래 줄번호·개수는 전부 `ded22f3` 이후 기준이라 옛 checkout 에서는 하나도 안 맞는다.)

### 🚨 명령을 돌리기 전에 한 번만 — 의존성 설치

`pytest` 명령은 의존성이 깔려 있어야 돈다. clone 직후에는 `ModuleNotFoundError` 가 난다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pip install -r requirements.txt
```

`fastapi`·`starlette` 는 2026-06-24 전 API 500 사고 때문에 **버전이 핀 고정**돼 있다
(`requirements.txt` 상단 주석). 핀을 풀지 마라.
🚨 **가상환경을 먼저 만들고 설치하라 — 전역 설치는 다른 프로젝트를 깨뜨린다.**
이 PC 에는 다른 파이썬 작업 환경이 같이 산다. 전역 `pip install -r requirements.txt` 는
핀 고정된 `fastapi`·`starlette` 등을 **시스템 전역에 강제**해 그쪽을 망가뜨릴 수 있고,
반대로 나중에 그쪽에서 설치한 패키지가 **이 프로젝트의 핀을 덮어** 2026-06-24 의
「전 API 500」 드리프트 사고를 재현한다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m venv .venv && source .venv/Scripts/activate && python -m pip install -r requirements.txt
```

되돌리기: venv 를 쓰면 `.venv` 폴더만 지우면 원상복구다(전역은 되돌릴 방법이 사실상 없다).
이후 §8·§9 의 `python` 명령은 **이 venv 를 활성화한 셸에서** 돌린다.

---

### 0. 30초 요약 — 새 PC 에서 처음 열 파일 다섯 개

| 순서 | 파일 | 왜 먼저 보나 |
|---|---|---|
| 1 | `backend/app/services/execution_service.py` (2,269줄) | **모든 진입 주문이 여기를 지난다.** `start_stage1`(188) / `trigger_next_stage`(305) |
| 2 | `backend/app/services/tp_sl_orchestrator.py` (828줄) | **모든 익절·손절이 여기서 나간다.** 손절 함수가 **두 개**라 사고가 났다 (§5) |
| 3 | `backend/app/workers/stage_trigger_worker.py` (1,525줄) | 단계 진입 판정. 네 방식의 분기가 여기 있다 |
| 4 | `backend/app/workers/scheduler_runner.py` (764줄) | **워커가 언제 도는지의 유일한 진실** (§6) |
| 5 | `backend/app/core/strategy_status.py` | 상태 집합·모드 마커의 단일 출처 |

🚨 이 저장소에서 반복해서 난 사고는 전부 같은 모양이다 —
**「게이트는 만들었는데 그 함수가 실제로 안 불렸다」**.
그래서 코드를 읽기 전에 §8(실행 테스트)을 먼저 알아두는 편이 낫다.

---

### 1. 저장소 레이아웃

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader" && ls -d */ *.md | head -60
```

| 경로 | 내용 |
|---|---|
| `backend/app/` | **애플리케이션 전부** (Python 281 파일) |
| `backend/alembic/versions/` | DB 마이그레이션 **32개** (`0034_surge_ladder_state.py` 가 최신 — 번호 `0025`/`0026` 은 결번이라 파일 수 ≠ 최신 번호) |
| `backend/tests/` | 테스트 159 파일 (§8) |
| `backend/memory/` | 워커가 읽는 운영 메모리 |
| `docs/` | 기획서·사양서 (`docs/spec/`, `docs/handoff/`) |
| 저장소 루트 `*.md` | 구버전 핸드오프·사양 **42개**(`ls *.md | wc -l`). **오래된 것이 많다** — 최신 진실은 코드와 `docs/` |
| `deploy/`, `docker-compose.production.yml` | 배포 |

---

### 2. `backend/app/` 층별 지도

파일 수는 아래 명령으로 재현된다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && for d in */; do echo "$d $(find "$d" -name '*.py' -not -path '*__pycache__*' | wc -l)"; done
```

| 디렉터리 | .py | 역할 | 대표 파일 (줄수) |
|---|---:|---|---|
| `services/` | 59 | **비즈니스 로직의 중심.** 주문 실행·리스크·게이트·지표 판정 | `execution_service.py` (2269), `risk_service.py` (1266), `tp_sl_orchestrator.py` (828), `stream_service.py` (551) |
| `workers/` | 64 | 주기 실행 작업. **후보 생산자 + 단계 트리거 + 감시자** | `auto_bb_breakdown_worker.py` (2241), `auto_long_at_bottom_worker.py` (1949), `realtime_reentry_worker.py` (1807), `stage_trigger_worker.py` (1525), `scheduler_runner.py` (764) |
| `agents/` | 55 | 「오케스트라」 에이전트 **`*_team` 폴더 17개 + `orchestrator/`** (분석·학습·감사). **매매 주문을 직접 내지 않는다** | `orchestrator/`(5), `strategy_suggestion_team/`(9), `coding_team/`(6), `planning_team/`(6) |
| `api/` | 36 | FastAPI 라우터. `api/router.py` 가 **22개** 라우터를 `/api/v1` 아래 묶는다 | `v1/strategies/{crud,control,lifecycle,calculate,helpers}.py`, `v1/admin/*`, `v1/strategy_suggestions.py` |
| `models/` | 20 | SQLAlchemy ORM | `strategy_instance.py`, `strategy_template.py`, `strategy_stage_plan.py`, `system_setting.py` |
| `core/` | 14 | 설정·DB·Redis·**암호화**·상수 | `config.py`, `database.py`, `crypto.py` 🔐, `redis_client.py`, `redis_lock.py`, `strategy_status.py`, `risk_constants.py` |
| `integrations/` | 9 | 바이낸스 클라이언트 + 주문 어댑터 | `binance/client.py`, `binance/execution/{router,plain_order_adapter,algo_order_adapter}.py` |
| `repositories/` | 7 | DB 접근 래퍼 | `strategy_repository.py`, `position_repository.py`, `order_repository.py` |
| `schemas/` | 7 | Pydantic 요청/응답 | `strategy.py`, `position.py`, `order.py`, `risk.py` |
| `middleware/` | 2 | `idempotency.py` |
| `observability/` | 2 | `metrics.py` (Prometheus) |
| `db/` / `utils/` | 2 / 2 | `db/base.py`, `utils/backoff.py` |
| `static/` | 0 | **프런트엔드** — HTML **9개** + JS 43개, CSS 파일 0 (스타일은 HTML 안에). 빌드 없음, 그대로 서빙 |

`app/main.py` 가 FastAPI 앱 진입점, `app/api/router.py:25` 이 `/api/v1` prefix.

#### 2-1. 🔐 `core/crypto.py` — 새 PC 이전에서 가장 위험한 파일

바이낸스 API 키는 평문으로 저장되지 않는다. `encrypt_text()` 가 Fernet 으로 암호화해
`exchange_accounts.api_key_enc` / `api_secret_enc` 에 넣고, 쓸 때마다
`decrypt_text()` 로 푼다 (**호출처 154곳** — `grep -rn 'decrypt_text(' backend/app | grep -v 'def ' | wc -l`).

🚨 **Fernet 키는 `.env` 의 `ENCRYPTION_KEY` 단 하나다** (`crypto.py:35` `settings.encryption_key`).
**이 값을 잃거나 새 PC 에서 새로 생성하면 DB 의 `api_key_enc` 는 영원히 복호화할 수 없다.**
Fernet 은 대칭키라 백도어도 복구 절차도 없다 — 바이낸스에서 **키를 새로 발급**받는 것
말고는 방법이 없다. `decrypt_text` 는 그때 `CryptoError("Failed to decrypt: invalid token")`
로 죽는다 (`crypto.py:52-54`).

→ 새 PC 로는 `ENCRYPTION_KEY` 를 **글자 하나도 바꾸지 말고 그대로** 옮긴다.
   이전 절차·값 획득처·검증법은 **`docs/handoff/2026-09-03/secrets.md` §3** 에 있다.
   (이 문서는 값을 담지 않는다 — 키 **이름**만 적는다.)

🚨 `validate_encryption_key()` 가 startup 에서 기본값(`change_me`)과 형식 오류를 잡아
**즉시 죽인다** (`crypto.py:12-30`, 호출은 `main.py:46`). 새 PC 에서 api 가 뜨자마자
`CryptoError` 로 죽으면 코드 문제가 아니라 **`.env` 를 안 옮긴 것**이다.

🚨 **층 사이의 방향**: `workers → services → repositories → models`.
워커가 거래소 API 를 직접 부르는 곳도 있으니(후보 스캔) 「주문」만은 반드시
`ExecutionService` 를 지난다고 기억하면 된다.

---

### 3. 🚨 네 가지 진입 방식 — 이 시스템에서 가장 헷갈리는 곳

#### 3-1. 결론 먼저: `trigger_mode` 로는 구분되지 않는다

실서버 DB 실측(아래 §9 명령으로 재현) — **네 방식 대부분이 `PRICE_DOWN_PCT` 다**:

```
strategy_type                     trigger_mode      capital_management_mode   건수
DYNAMIC_SHORT                     PRICE_DOWN_PCT    fixed                     475
auto_bb_break_SAJANGNIM_TOP       PRICE_DOWN_PCT    fixed                     317
DYNAMIC_LONG                      PRICE_DOWN_PCT    fixed                     257
auto_bb_break_SAJANGNIM_BOTTOM    PRICE_DOWN_PCT    fixed                     158
pump_split                        PRICE_DOWN_PCT    split_entry                68
auto_bb_break                     PRICE_DOWN_PCT    fixed                      43
DYNAMIC_SHORT                     OBV_REVERSE       fixed                      40
DYNAMIC_LONG                      OBV_REVERSE       fixed                      40
bb_mid_line                       PRICE_DOWN_PCT    fixed                      39
```
(2026-09-03 VPS 조회, `strategy_instances` 전건 1,487)

코드도 같은 말을 한다 — `app/services/stage_entry_timing.py:24-25`
(모듈 docstring. 파일을 열면 첫 화면에 있다):

> 세 방식 모두 `trigger_mode = PRICE_DOWN_PCT` 라 **trigger_mode 로는 구분되지 않는다.**
> 그래서 `strategy_type` 접두사로 가른다.

#### 3-2. 진짜 구분자 표

| # | 방식 | **실제 구분자 (코드)** | 근거 |
|---|---|---|---|
| ① | **기본 방식** — 사장님이 화면에서 만드는 단계 전략. 정해진 트리거 단가에 **즉시** 진입 | `template.trigger_mode ∈ {PRICE_DOWN_PCT, PRICE_UP_PCT}` **AND** 아래 ②③④ 마커가 전부 아님 | `workers/stage_trigger_worker.py:1128` `_is_price_mode = _tpl_trigger_mode in ("PRICE_DOWN_PCT","PRICE_UP_PCT")` |
| ② | **OBV 자동** — 4중 게이트로 「좋은 자리」를 판정 | `template.trigger_mode == "OBV_REVERSE"` | `workers/stage_trigger_worker.py:464` `_is_obv_mode`, 분기 `:792` |
| ③ | **v219 사다리** — 1단계 자본 10 → 300 → 600 | `template.strategy_type.startswith("auto_bb_break_SAJANGNIM")` **또는** `instance.capital_management_mode == "stage_ladder"` | `services/stage_entry_timing.py:74` `TYPES_DEFAULT="auto_bb_break_SAJANGNIM"` / `services/sajangnim_capital.py:329` `STAGE_LADDER_MODE="stage_ladder"` (판정 함수는 같은 파일 `is_stage_ladder`) |
| ④ | **볼밴 분할** — 100+200+300 **동시 보유**, 물타기가 설계 | `instance.capital_management_mode == "split_entry"` | `core/strategy_status.py:155` `SPLIT_ENTRY_MODE`, `workers/pump_split_entry_worker.py:138` `MODE_MARKER` |

보조 마커 (같은 컬럼을 쓴다 — 마이그레이션 없이 모드를 늘리는 관행, 헌법 127):

| `capital_management_mode` | 뜻 | 실서버 건수 |
|---|---|---:|
| `fixed` | 기본 (①②③ 대부분) | 1,413 |
| `split_entry` | 볼밴 분할 (④) | 68 |
| `auto_deduct` | v131 청산 후 재진입 + 손실 자동 차감 | 5 |
| `scheduled` | 예약 진입 (`workers/scheduled_entry_worker.py:20`) | 1 |
| `stage_ladder` | v219 사다리 마커 (Fix 315/321) | **0** ⚠️ 아래 참조 |

🚨 **`stage_ladder` 는 아직 실서버에 0건이다.** 마커는
`workers/auto_bb_breakdown_worker.py:1931-1933` 에서
`stages_config["stages_count"] > 1` 일 때만 저장되는데,
24시간 내 만들어진 SAJANGNIM 전략 9건이 전부 `capital_management_mode='fixed'` +
`stage_plans` **1개**였다(가장 최근이 `#2045 HYPEUSDT`, 2026-09-02 23:12 UTC —
2026-09-03 재검증에서도 그대로였다). 관련 코드(Fix 315/327)는 조회 시점 기준 12분 전
재시작으로 배포는 되어 있었으므로, **배포 이후 새 전략이 아직 안 생긴 것**으로 보인다.
새 PC 에서 제일 먼저 확인할 것 = 「사다리가 실제로 3단계로 생성되는가」(§9 명령).
👉 §9 마지막 명령을 돌려 **`#2045` 보다 큰 id 가 나오는지** 먼저 본다. 안 나오면
아직 새 전략이 없는 것이고, 나오는데 `plans` 가 1이면 그때가 진짜 버그다.

#### 3-3. 방식별 상세

**① 기본 방식** — `stage_trigger_worker.py:1103-1132` (Fix 232)
> 사장님 verbatim: "기본방식은 가격만 본다"
- 2단계 이상에서 **지표 게이트를 일부러 전부 뺐다.** 가격이 트리거에 닿으면 그냥 들어간다.
- 이전에는 `confirm_peak` 이 또 막아서 「왜 안 들어가는지 알 수 없는」 상태가 됐다(#1873).
- 🚨 그 대가로 **떨어지는 칼에도 지정가에 들어간다** → 손절이 그만큼 중요하다(§5).

**② OBV 자동** — `services/stage_entry_signal.py` (193줄), 호출 `stage_trigger_worker.py:720 / :830`
4중 게이트를 **자동 진입 워커와 같은 함수·같은 순서**로 부른다 (새 판정 로직을 만들지 않는다):

| 순서 | 게이트 | 함수 |
|---|---|---|
| ① | 4H OBV 극단 = 세력 반대면 차단 | `services/obv_gate.check_obv_gate` |
| ② | 양방향 연속 실패 종목 차단 | `services/bidirectional_blocklist.is_bidirectional_blocked` |
| ③ | 국면 차단 (SHORT 전용) | `services/pump_dump_regime.is_regime_blocked_for_short` |
| ④ | **핵심** — 15m 반복 정점/저점 ≥2회 + 지표 꺾임 ≥2/3 | `services/peak_confirmation.confirm_peak` |

- 각 게이트는 **fail-open**(판정 실패 시 통과)이지만, 그 사실을 `detail` 에 남긴다.
- 🚨 여기에 Fix 312 대기 로직을 또 얹으면 **Fix 232 가 없앤 중복 게이트가 부활한다**
  (`stage_entry_timing.py:16-18` 가 명시).

**③ v219 사다리** — `workers/auto_bb_breakdown_worker.py` + `services/sajangnim_capital.py`
- 자본 사다리 `10 / 300 / 600` (실서버 설정 `sajangnim_capital_ladder = "10,300,600"`).
- **단계 간격 기본 1.5%** (`sajangnim_capital.py:SETTING_STAGE_GAP` / `STAGE_GAP_DEFAULT`).
  🚨 **간격은 손절폭보다 작아야 한다** — SHORT 손절 ROI −5% / 레버2 = 가격 2.5%.
  간격이 2.5% 이상이면 손절이 항상 먼저 와서 **2단계에 영원히 도달하지 못한다**
  (실측 850사이클: 간격 2.5% → SHORT 2·3단계 0건 / 1.5% → +2,636).
- 1단계 10 USDT 는 「자리 탐색」이라 **손절할 것이 없다** → `stage_trim` 이 스킵
  (`services/stage_trim.py:MIN_TRIM_RATIO_DEFAULT=2`).

**④ 볼밴 분할** — `workers/pump_split_entry_worker.py` (1,069줄)
- 자본 모델이 ③과 **정반대**: 100+200+300 = 600 을 **동시 보유**해 평단을 만든다.
- 진입 = 15m 기준선 대비 −3 / −5 / −7% 이탈. 2·3차는 `stage_plan.trigger_price` 로 심어
  **기존 `stage_trigger_worker` 가 처리**한다 (새 진입 경로를 만들지 않는다).
- 🚨 **다른 워커가 여기에 계획 밖 진입을 얹으면 평단이 설계와 반대로 밀린다.**
  2026-08-29 피라미딩이 4건에 300씩 얹어 **−252.18 USDT**(Fix 213).
  그래서 `stage_trim` 은 `split_entry` 를 **설정으로도 켤 수 없게 코드에 박아** 제외한다
  (`services/stage_trim.py:75` `ALWAYS_EXCLUDED_MODES`).

---

### 4. 공용 진입 관문 — `execution_service.start_stage1`

`backend/app/services/execution_service.py:188`.
**신규 진입은 전부 여기를 지난다.** 직접 호출은 **7곳**이고, 다음 명령으로 재현된다:

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -rn "start_stage1(" --include=*.py . | grep -v "def start_stage1"
```

| 호출자 | 파일:줄 |
|---|---|
| API(수동·화면) | `api/v1/strategies/control.py:47` |
| 급등 정점 사다리 | `services/surge_ladder_entry.py:311` |
| BB 붕괴 자동 (= **공용 전략 생성 함수** `_create_auto_bb_strategy`) | `workers/auto_bb_breakdown_worker.py:2029` |
| 청산 후 재진입 | `workers/auto_reentry_worker.py:163` |
| 사다리 재시작 | `workers/ladder_restart_worker.py:310` |
| 볼밴 분할 | `workers/pump_split_entry_worker.py:1040` |
| 예약 진입 | `workers/scheduled_entry_worker.py:231` |

🚨 **`unified_15m_entry` 는 이 목록에 없다 — 없는 게 아니라 간접이다.**
`unified_15m_entry_worker.py:173-179` 이 `auto_bb_breakdown_worker` 에서
`_create_auto_bb_strategy` 를 import 해(호출은 `:433`) 그쪽 `start_stage1` 로 들어간다. §6-3 에서 `auto_bb_breakdown` **잡**이
주석 처리돼 있는데도 **모듈은 살아 있다**고 적은 이유가 이것이다.
그래서 `unified_15m_entry` 를 읽을 때는 `auto_bb_breakdown_worker` 를 **한 쌍으로** 봐야 한다.
(다만 `unified_entry_enabled=0` 이라 **지금 실서버에서는 이 경로가 안 돈다** — §6-1 끝의 경고.)

(`services/chg24_entry_gate.py:23-25` 는 「8개 경로」라고 적고 7개만 나열한다 —
`unified_15m` 이 간접이라 세다 말았다. 숫자보다 위 표를 믿을 것.)

#### 4-1. 게이트 순서 (위에서 아래로)

| 순 | 줄 | 게이트 | 설정 키 | 코드 기본 | **실서버 현재값** | fail 방향 |
|---:|---:|---|---|---|---|---|
| 1 | `:192` | 계정 Kill-Switch | (DB `account_kill_switch`) | — | — | 차단 |
| 2 | `:199-227` | **Fix 310/325 당일 변동률·순위** — 상승 50 + 하락 50 = 100개 | `entry_chg24_gate_enabled` / `entry_rank_top_n`(50) / `entry_chg24_gate_mode`(`rank`) | **OFF** | **ON (`1`)** | fail-**open** |
| 3 | `:231-267` | **Fix 327 지지선 7점** — LONG score≥6 / SHORT score≤1, 2~5 는 진입 금지 | `support_score_gate_enabled` | **OFF** (`support_score.py:128`) | **미설정 = OFF** | fail-**open** |
| 4 | `:270` | ISOLATED 마진 보장 | — | 항상 | — | 예외 |
| 5 | `:271` | 레버리지 적용 | — | 항상 | — | 예외 |
| 6 | `:272 → _place_stage_entry_order:1154` | **Fix 303 제외 심볼** (`_assert_symbol_allowed:1908`) | `excluded_symbols` | **ON**(코드 내장 목록) | 미설정 = 내장 11종 | 차단 (fail-**closed**) |
| 7 | `:272` | 실제 주문 발사 (MARKET or LIMIT) | — | — | — | — |
| 8 | `:277-303` | 추가 증거금 자동 투입(옵션) | `stage_plan.additional_margin_usdt` | 없으면 skip | — | 실패해도 진입은 유지 |

Fix 303 의 내장 제외 목록 (`services/symbol_exclusion.py:54-61` `DEFAULT_EXCLUDED`):
`BTCUSDT / BTCUSDC / BTCUSD1`(MIN_NOTIONAL 50), `ETHUSDT / ETHUSDC / LTCUSDT /
LINKUSDT / ETCUSDT / BCHUSDT`(20), `BTCUSDT_261225 / BTCUSDT_260925`(stepSize).
이유 = 「10 USDT 잔량」을 남길 수 없어 **팔 수 없는 dust** 가 된다.
🚨 이 저장소는 dust orphan **하나로 계정 전체가 막힌 전력**이 있다.

🚨🚨 **`excluded_symbols` 를 빈 값으로 저장하면 제외가 전부 풀린다 — 절대 하지 마라.**
`symbol_exclusion.py:79-82` 를 그대로 옮기면:

| `excluded_symbols` 값 | 결과 |
|---|---|
| 행 자체가 없음 / `NULL` | 내장 11종 유지 ✅ |
| 조회 실패(예외) | 내장 11종 유지 ✅ (fail-safe) |
| **빈 문자열 `""`** | `frozenset()` = **제외 0건** 🚨 BTCUSDT 까지 진입 대상이 된다 |
| `"AAAUSDT"` | **AAAUSDT 하나만** 제외 = 내장 11종이 **전부 풀린다** 🚨 |

즉 이 키는 **추가(add)가 아니라 대체(replace)** 다. 심볼을 하나 더 빼고 싶으면
**내장 11종을 전부 다시 나열한 뒤 그 뒤에 붙여야** 한다. 한 종목만 적으면
BTCUSDT 에 10 USDT 잔량을 남기려다 dust orphan → **계정 전체 차단**으로 간다.
되돌리는 법: 그 설정 **행을 지우면** 즉시 내장 11종으로 복귀한다(재배포 불필요).

🚨 **Fix 303 만 주문 함수 세 곳에 걸려 있다** —
`_place_stage_entry_order:1155`, `_place_market_entry:1940`, `_place_limit_entry:2165`.
후보 생산자(워커)마다 거는 방식은 이 저장소에서 **반복해서 실패**했다
(「게이트는 있는데 한 경로가 그 함수를 안 부른다」). 주문 직전에 두면 어떤 워커가
만들어도 새어나갈 수 없다. `tests/test_symbol_exclusion.py` 가 세 곳을 고정한다.

#### 4-2. 🚨 `trigger_next_stage` 에는 왜 걸면 안 되나

`execution_service.py:305`.

> 1단계 진입 때 12% 였다가 2단계 트리거 시점에 8% 로 떨어지면 사다리가
> **그 자리에서 영원히 멈춘다.** 이미 자금이 들어간 전략을 변동률로 끊으면 안 된다.
> — `execution_service.py:203-205`, `chg24_entry_gate.py:29-33`

같은 이유가 Fix 327 에도 적혀 있다 (`execution_service.py:250`:
"여기(1단계)에만 건다. `trigger_next_stage` 에 걸면 사다리가 멈춘다").

한 문장으로: **1단계 = 「안 사면 그만」이라 fail-closed 해도 되고,
2단계 이후 = 「이미 돈이 들어가 있다」라 막으면 탈출로가 사라진다.**

#### 4-3. `trigger_next_stage` 가 대신 갖는 게이트

| 순 | 줄 | 내용 | 설정 키 | 코드 기본 | 실서버 |
|---:|---:|---|---|---|---|
| 1 | `:328` | Kill-Switch (2026-05-04 fix — 예전엔 1단계에만 있었다) | — | 항상 | — |
| 2 | `:355 → _trim_before_stage:1784` | **Fix 312 「좋은 포지션」 대기** (v219 사다리 + SHORT 한정) | `stage_wait_for_turn_enabled` / `stage_wait_for_turn_sides`(SHORT) / `_types`(`auto_bb_break_SAJANGNIM`) / `_klines`(120) | **OFF** | **ON (`1`)** |
| 3 | 같은 곳 | **Fix 304 「10 USDT 만 남기고 청산」** 후 다음 단계 진입 | `stage_trim_before_next_enabled` / `stage_keep_notional_usdt` | **OFF** | **ON (`1`)** |
| 4 | `:357` | 주문 발사 (`_place_stage_entry_order` → Fix 303) | — | — | — |

🚨 `_trim_before_stage` 는 **자동(`trigger_next_stage:355`)과 수동
(`enter_stage_at_market` — 함수 시작은 `:1267`, 호출은 그 안 `:1331`) 양쪽**에서
불린다 (Fix 305).
한쪽만 걸면 그 경로로 물타기가 그대로 일어난다.

🚨 **fail 방향이 반대다**: 여기 Fix 304 는 **fail-CLOSED**
(남길 수량을 확정 못 하면 단계 진입 자체를 안 한다 — 실자금이라
"반쯤 실행된 상태"가 가장 위험). 반면 Fix 312 대기는 **fail-OPEN**
(캔들 조회 한 번 실패로 단계가 영구 정지하면 안 된다 — Fix 305 함정).

---

### 5. 🚨 손절 경로 — 함수가 **두 개**다 (여기서 사고가 났다)

디스패치는 한 곳이다 — `services/tp_sl_orchestrator.py:89-97`:

```
if self.risk_service.evaluate_force_stop_loss(strategy.id):
    self._execute_force_stop_loss(strategy)      # ← 사장님 −5% / −10% 는 여기로 온다
    return
if self.risk_service.evaluate_stop_loss(strategy.id):
    self._execute_stop_loss(strategy)            # ← −80~90% 일반 SL
    return
```

| | `_execute_force_stop_loss` (`:545`) | `_execute_stop_loss` (`:686`) |
|---|---|---|
| **누가 발동시키나** | `risk_service.evaluate_force_stop_loss` (`:367`) | `risk_service.evaluate_stop_loss` |
| **임계값** | 사장님 설정 ROI. 전역 `force_sl_{long,short}_*` + 전략별 `force_sl_roi_override` 우선 (−3 / −5 / −10 …) | 템플릿 `stop_loss_percent_of_capital` 기반 = 실질 **−80~90%** |
| **누가 쓰나** | 🚨 **사장님이 실제로 쓰는 손절** | 사실상 최후 안전망 |
| **단계 게이트** | 없음 (아무 단계에서나) — 단 v130 「다음 단계 남으면 보류」 게이트가 있었고 Fix 317/321/322 로 면제됨 | 같은 면제 규칙 공유 (Fix 321) |
| **재진입** | ❌ `mark_reentry_ready` **호출 안 함** = 사장님 손절 의사 = 그 전략 종료 | ✅ `mark_reentry_ready(strategy.id)` 호출 |
| **부분 손절** | Fix 319/326 (`:596-640`) | Fix 318/326 (`:720-757`) — **지금은 양쪽 다 있다** |
| **호출 주기** | `tp_sl` 잡 = **15초** | 동일 |

#### 5-1. 왜 헷갈리는가 — Fix 318 사고

`tp_sl_orchestrator.py:555-563` 이 직접 적어 놓았다:

> Fix 318 은 `_execute_stop_loss`(−80~90% 일반 SL)에 붙어서 **실제로는 아무 효과가
> 없었다.** #2046 AKEUSDT 가 전량 청산된 것도 이 함수를 탔기 때문이다.
> 사전 검증을 하지 않아 함수를 잘못 골랐다.

혼동의 원인 세 가지:
1. **이름이 거의 같다** — `_execute_stop_loss` vs `_execute_force_stop_loss`.
2. **둘 다 「손절」이고 둘 다 부분 청산 로직을 갖는다.** 코드를 봐서는 어느 쪽이
   사장님 설정과 연결되는지 알 수 없다 — 연결은 `risk_service` 의 **평가 함수 이름**에 있다.
3. **정적 검사가 통과한다.** 「소스에 이 문자열이 있나」는 통과했고 배포까지 됐다.

🚨 **기억할 한 줄: 「사장님이 화면에서 고른 손절 %」= `force_sl_*` = `_execute_force_stop_loss`.**

#### 5-2. 부분 손절의 세 갈래 (양쪽 함수 공통)

`services/stage_trim.compute_trim` 이 반환하는 `action` 으로 갈린다:

| action | 처리 | 왜 |
|---|---|---|
| `TRIM` | **10 USDT 만 남기고** 청산 → **전략을 종료하지 않는다** (`STOPPING` 안 찍음, 미체결 LIMIT 도 안 지움) | 사장님 "전략 인스턴스에 남겨둬야 겠어" |
| `SKIP` | **손절하지 않고 그대로 둔다** (Fix 326) | 이미 잔량 수준. 여기서 전량 청산하면 다음 사이클이 사양을 지운다 |
| `BLOCK` | 전량 청산 (안전측) | 판정 불가일 때 손절을 막으면 손실이 커진다 |

🚨 **같은 `BLOCK` 이 호출처에 따라 정반대로 동작한다 — 헷갈리면 손절이 멈춘다.**
상수는 소문자(`ACTION_BLOCK = "block"`, `stage_trim.py:109`)이고, 호출처가 둘뿐인데
**둘이 다르게 다룬다**:

| 호출처 | `BLOCK` 처리 | 방향 |
|---|---|---|
| `execution_service._trim_before_stage:1884` (단계 진입 전, Fix 304) | **명시적 분기 — 단계 진입을 중단** | fail-**CLOSED** ("안 사면 그만") |
| `tp_sl_orchestrator:605·729` (손절, Fix 318/319/326) | **`ACTION_BLOCK` 분기가 아예 없다.** import 도 `ACTION_SKIP, ACTION_TRIM` 둘뿐 → BLOCK 은 그냥 **아래로 흘러 전량 청산** | fail-**OPEN**(손절은 반드시 나간다) |

- 그래서 `grep ACTION_BLOCK app/services/tp_sl_orchestrator.py` 는 **0건이 정상**이다.
  「문서가 틀렸다」가 아니다.
- 🚨 **여기에 `elif _act == ACTION_BLOCK: return` 같은 분기를 「일관성」이라며 넣지 마라.**
  판정 불가(시세 결손·필터 결손)일 때 손절이 통째로 멎어 **손실 상한이 사라진다.**
  진입 쪽과 손절 쪽의 fail 방향이 다른 것은 **의도**다(§4-3 과 같은 원칙).

🚨 **Fix 326 의 교훈** (`tp_sl_orchestrator.py:576-597`) — 실서버 로그가 잡았다:
```
07:55:00  MARSCOIN #2091 부분 손절 → 184 잔여 (명목 20.04)   ✅
08:00:22  MARSCOIN #2091 「남길 것이 없다」 → 전량 청산       ❌ 5분 뒤
```
> **부분 청산을 만들면 「남긴 것」이 다음 사이클에 어떻게 취급되는지 반드시 따라가라.**
> 한 번의 부분 손절은 성공해도 다음 사이클이 그것을 지우면 구현되지 않은 것과 같다.

#### 5-3. 단계 게이트 면제 — `risk_service._stage_gate_exempt` (`:165`)

「단계가 남으면 손절 보류」(v130 물타기 전제)를 면제하는 판정.
🚨 예전엔 **세 곳에 흩어져** 있었고 면제는 force SL 한 곳에만 있었다(Fix 321).
지금은 한 함수로 모아 세 게이트가 같은 판정을 쓴다.

면제 대상: 청산 후 재진입 / `split_entry` / `stage_ladder` / Fix 304 ON /
**사장님이 그 전략에 손절 ROI 를 명시한 경우**(Fix 322).
실측: 단계 계획이 있는 전략 **1,221건 중 371건(30%)** 이 이 게이트에 걸려
손절이 마지막 단계까지 보류되고 있었다.

---

### 6. 워커 지도 — `scheduler_runner.py` 가 유일한 진실

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n 'id="' workers/scheduler_runner.py
```

🚨 위 grep 은 **id 만** 보여준다. 주기와 락 TTL 은 `add_job(...)` 이 여러 줄로 쪼개져
있어 같은 줄에 없다. **주기까지 한 번에 보려면** 아래를 쓴다 (아래 표를 통째로 재생성한다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n -A6 'scheduler.add_job' workers/scheduler_runner.py | grep -E 'guarded_job\("|IntervalTrigger|CronTrigger|id="'
```

APScheduler `BlockingScheduler(timezone="Asia/Seoul")` (`scheduler_runner.py:74`),
`DistributedSchedulerGuard` 로 리더 1대만 실행 (생성 `:76`, 실제 판정은 모든 job 을
감싸는 `guarded_job` `:117-131`).

#### 6-1. 매매에 직접 관여하는 워커 (중요도 순)

| 주기 | job id | 모듈 | 하는 일 |
|---|---|---|---|
| **15초** | `tp_sl` | `run_workers.run_tp_sl_once` → `TPSLOrchestratorService` | **모든 익절·손절** (§5) |
| **15초** | `stage_trigger` | `stage_trigger_worker` | **단계 진입 판정** — 네 방식 분기 |
| 15초 | `auto_add_margin` | `auto_add_margin_worker` | 자동 증거금 추가 |
| 30초 | `realtime_reentry` | `realtime_reentry_worker` | 실시간 재진입 |
| 30초 | `success_pyramiding` | `success_pyramiding_worker` | 이익 시 추가 진입 (🚨 `split_entry` 제외) |
| 30초 | `auto_long_at_bottom` | `auto_long_at_bottom_worker` | LONG 저점 진입 |
| 30초 | `auto_short_at_top` | `auto_short_at_top_worker` | SHORT 정점 진입 |
| 30초 | `surge_peak_ladder` | `surge_peak_ladder_worker` | 급등 정점 사다리 |
| 30초 | `resistance_reversal` | `resistance_reversal_worker` | 저항 반전 SHORT |
| 30초 | `peak_break_reversal` | `peak_break_reversal_worker` | 정점 붕괴 반전 |
| **30초** | `unified_15m_entry` | `unified_15m_entry_worker` | **v224 통합 진입 소스** (`:505-510` `IntervalTrigger(seconds=30)`, TTL 25s). 🚨 **실서버에서는 지금 아무것도 진입하지 않는다** — 아래 참조 |
| 60초 | `auto_reentry` | `auto_reentry_worker` | 청산 후 재진입 |
| 1분 | `daily_loss_check` | `daily_loss_aggregator` | 일일 손실 한도 |
| 1분 | `liquidation_risk` | `liquidation_risk_worker` | 청산 위험 사전 알림 |
| 3분 | `macd_reversal_15m` | `macd_reversal_15m_worker` | 15m MACD 반전 |
| 5분 (시작 +150초) | `long_bottom_detector` | `long_bottom_detector_worker` | LONG 저점 후보 |
| 5분 | `bb_upper_breakout_short` | `bb_upper_breakout_short_worker` | BB 상단 돌파 SHORT |
| 5분 | `pump_top_detector` | `pump_top_detector_worker` | 급등 정점 감지 |
| 5분 | `pump_dump_early_detector` | `pump_dump_early_detector_worker` | 급등락 조기 감지 |
| 5분 | `ladder_restart` | `ladder_restart_worker` | 사다리 재시작 |
| 5분 | `scheduled_entry` | `scheduled_entry_worker` | 예약 진입 (`mode=scheduled`) |
| 15분 | `pump_split` | `pump_split_entry_worker` | **볼밴 분할 (④)** |
| 15분 | `bb_mid_line` | `bb_mid_line_worker` | BB 중단선 전략 |
| 15분 | `realtime_watchlist` | `realtime_watchlist_worker` | 감시 목록 갱신 |

🚨🚨 **「등록돼 있다」와 「진입한다」는 다르다 — `unified_15m_entry` 가 그 예다.**
2026-09-03 실서버 실측:

```
unified_entry_enabled       0        ← 워커 첫 줄에서 return
auto_bb_break_daily_limit   0        ← 통과해도 두 번째 줄에서 return
```

`unified_15m_entry_worker.py:162-170` 이 이 둘을 차례로 보고 **하나라도 0 이면 즉시
`{"entered": 0}` 로 나간다** (지금은 둘 다 0 이라 첫 줄에서 끝난다).
즉 30초마다 돌기는 하지만 **주문은 한 건도 안 낸다.**
따라서 진입은 §6-3 아래쪽에 **다시 등록된** `pump_top_detector`(5분) /
`auto_short_at_top`(30초) 등 **v224 이전 경로**에서 나온다.
⚠️ 다만 그 워커들의 **자체 ON 스위치까지는 확인하지 못했다** — 같은 방식으로
각자의 설정 키를 §9 명령에 추가해 확인할 것.

🚨 이 저장소가 반복해서 당한 함정이 정확히 이 모양이다 — 「스케줄러에 있으니 돌겠지」.
**워커를 조사할 때는 ① 등록됐나 ② 락에 안 걸리나(§6-4) ③ 자기 ON 스위치가 켜졌나
세 가지를 다 본다.** ③ 은 §9 의 설정 조회 명령으로 확인한다.

#### 6-2. 감시·정합성·학습 워커

| 주기 | job id | 하는 일 |
|---|---|---|
| 1분 | `silent_bug_detector` | 잠재 silent bug 감지 |
| 2분 | `position_reconcile` | 거래소 ↔ DB 정합 회복 (🚨 고아 정리는 `position_amt == 0` **정확히 0** 일 때만) |
| 2분 | `tp_miss_detector` | TP 도달했는데 미실행 감지 |
| 2분 | `reentry_alert` | 재진입 알람 |
| 5분 | `trade_anomaly_monitor` / `stage_calc_audit` / `user_intent_validator` / `edit_mode_validator` / `auto_fix_proposer` / `telegram_retry` / `learning_sync` / `martingale_gate_validator` / `orchestra_health` | 자동 가드·학습 |
| 변수 | `heartbeat` (`:593`) | 주기가 상수가 아니라 변수 `hours=hb_hours` 다 — 값은 파일에서 확인 |
| 3분 | `setting_preservation` | 사장님 설정 영구 유지 |
| 10분 | `pump_bb_watcher` | 급등 + BB중단 알람 |
| 30분 | `listenkey_keepalive` / `endpoint_health_monitor` / `failure_pattern_analyzer` | |
| 1시간 | `self_check` / `spec_audit` / `mainnet_safety` / `settings_sync` / `suggestion_cleanup` / `market_obs_update` / `pattern_learning` / `prediction_outcome` | |
| 4시간 | `market_obs_snapshot` / `learning_team_cycle` | |
| 6시간 | `binance_changelog_monitor` / `chart_pattern_scan` | |
| Cron | `symbol_sync_daily`(03:00) / `suggestion_daily_predict`(06:30) / `suggestion_auto_execute`(07:00) / `daily_briefing`(22:30 UTC=KST 07:30) / `daily_summary`(15:00) / `memory_consolidator`(18:00) / `daily_report`(UTC 00:00=KST 09:00) | |

#### 6-3. ⛔ 등록이 **주석 처리된** 워커 (파일은 남아 있다 — 착각 주의)

| 워커 | 줄 | 왜 껐나 |
|---|---:|---|
| `auto_bb_breakdown` | `:315-320` | v224 통합 → `unified_15m_entry` 로 대체. 🚨 **모듈 자체는 살아 있고 다른 곳에서 import 된다** |
| `pending_hc_fast` | `:376-381` | 같은 통합 |
| `pump_top_detector` (구 5분판) / `auto_short_at_top` (구 30초판) | `:391-404` | 통합 후 **아래쪽 `:663-692` 에서 다시 등록됨** — 같은 id 가 두 번 나오니 grep 만 보고 「꺼졌다」고 판단하지 말 것 |
| `time_reverse_exit` | `:645-652` | 비활성 |

🚨 롤백 방법이 각 주석에 적혀 있다 (`scheduler_runner.py:311`):
**주석 해제 + `unified_entry_enabled=0`**.

🚨 **실서버는 그 롤백이 「반만」 된 상태다** — 설정은 이미 `unified_entry_enabled=0`
인데 **주석은 그대로**다. 그래서 `auto_bb_breakdown`(BB 4H)과 `pending_hc_fast` 는
**어느 쪽으로도 안 돈다**(잡 미등록 + 통합 경로 OFF). 반대로 `pump_top_detector` /
`auto_short_at_top` 은 아래쪽에 다시 등록돼 있어 **그대로 돈다.**
→ 「BB 4H 진입이 왜 없지?」의 답이 여기 있다. 되살리려면 위 주석을 해제한다
(코드 수정 + 재배포이므로 **사장님 승인 없이 하지 말 것**).

🚨 **되살릴 때 순서를 틀리면 실자금으로 이중 진입이 난다.**
`unified_15m_entry` 와 `auto_bb_breakdown` 은 **같은 15m 급등/급락 후보**를 본다.
둘이 동시에 돌면 같은 심볼에 진입이 두 번 나가고, 그건 롤백이 아니라 **물량 2배**다.

| 순서 | 할 일 | 왜 이 순서인가 |
|---:|---|---|
| 1 | DB 설정 `unified_entry_enabled=0` **을 먼저 확인**(이미 0이면 그대로) | 설정은 재배포 없이 즉시 먹는다 |
| 2 | 통합 경로 진입이 실제로 멎었는지 로그로 확인 | 「설정했다」와 「멎었다」는 다르다 |
| 3 | 그 다음에 주석 해제 → 커밋 → **사장님이** pull + 재시작 | 코드는 재시작 전엔 안 먹는다 |

되돌리기(rollback of the rollback): **주석을 다시 넣기 전에** `unified_entry_enabled=1`
로 올리지 말 것 — 순서가 3→1 이 되면 그 사이에 둘 다 도는 창이 생긴다.
반드시 **주석 원복 + 재시작 → 그 다음 `unified_entry_enabled=1`**.

ℹ️ 참고: 주석 안의 `auto_bb_breakdown` 등록은 `IntervalTrigger(hours=1)` 이다
(15분이 아니다 — 되살려도 시간당 1회다).

#### 6-4. 🚨 워커가 조용히 안 도는 두 가지 이유

`scheduler_runner.py:91-131` (Fix 139 — 이유는 주석 `:91-106`, 코드는 `guarded_job:117-131`):
1. 리더가 아님 (`refresh_leader` 실패)
2. **이전 실행이 아직 락을 쥐고 있음** (`acquire_job_lock` 실패)

`guarded_job(job_name, ttl_seconds, fn)` 의 두 번째 인자가 **락 TTL**이다.
🚨 예: `success_pyramiding` 은 TTL 25s / 주기 30s → 한 번이라도 25초를 넘기면
그 뒤로 계속 건너뛸 수 있다. 지금은 **연속 skip 1회째와 20회마다** 경고 로그가 남는다.

---

### 7. 최근 신설 모듈 7개 (2026-09-03 세션)

| 모듈 | 줄 | 하는 일 | 설정 키 | 코드 기본 | 실서버 | 걸리는 곳 |
|---|---:|---|---|---|---|---|
| `services/stage_trim.py` | 412 | **「10 USDT 만 남기고 청산」** 수량 계산. `TRIM/SKIP/BLOCK` 반환 | `stage_trim_before_next_enabled`, `stage_keep_notional_usdt`(10), `stage_min_trim_ratio`(2), `stage_max_cumulative_loss_usdt`, `stage_trim_exclude_modes` | OFF | **ON** | 단계 진입 전(Fix 304) + 손절 양쪽(Fix 318/319) |
| `services/support_score.py` | 403 | **지지선 7점 판정.** LONG≥6 / SHORT≤1, 2~5 관망 | `support_score_gate_enabled`, `support_score_min_long`, `support_score_max_short` (🚨 `support_score_gate_*` 아님) | **OFF** | 미설정 = OFF | `start_stage1:253` |
| `services/chg24_entry_gate.py` | 184 | **당일 상승 50 + 하락 50 = 100개**만 신규 진입 | `entry_chg24_gate_enabled`, `entry_rank_top_n`(50), `entry_chg24_gate_mode`(`rank`/`abs`), `entry_min_abs_chg24`(10) | OFF | **ON** | `start_stage1:208` |
| `services/symbol_exclusion.py` | 121 | **자동매매 제외 심볼** 11종 (MIN_NOTIONAL > 10) | `excluded_symbols` (있으면 내장 목록을 **대체**) | **ON**(내장) | 내장 | 주문 함수 3곳 |
| `services/trend_4h_gate.py` | 220 | **4H MACD hist 「상승 중 AND > 0」** = 확정 흐름이 내 편인가 | `trend_4h_gate_enabled` | **OFF** (`trend_4h_gate.py:69-79`) | 🚨 **ON (`1`)** | `auto_bb_breakdown_worker:1545`, `bb_mid_line_worker:260`, `success_pyramiding_worker:756` |
| `services/sajangnim_capital.py` | 393 | **자본 사다리 10/300/600** + 단계 간격 + `stage_ladder` 마커 | `sajangnim_capital_ladder`(10,300,600), `sajangnim_ladder_stages_enabled`, `sajangnim_stage_gap_pct`(1.5) | 사다리 ON | **ON**, 사다리 `10,300,600` | `auto_bb_breakdown_worker`, `risk_service._stage_gate_exempt` |
| `services/stage_entry_timing.py` | 154 | **「좋은 포지션」 대기** — 트리거 도달 후 꺾임을 기다린다 | `stage_wait_for_turn_enabled` / `_sides`(SHORT) / `_types`(`auto_bb_break_SAJANGNIM`) / `_klines`(120) — 앞은 전부 `stage_wait_for_turn_` 접두사 (`stage_entry_timing.py:68-75`) | OFF | **ON** | `_trim_before_stage:1809` |

🚨 **적용 대상이 각각 다르다 — 전부에 걸린다고 착각하기 쉽다:**
- `chg24_entry_gate` / `support_score` → **신규 1단계만**
- `stage_entry_timing` → **v219 사다리 + SHORT 만** (기본방식·OBV 제외)
- `stage_trim` → **`split_entry` 는 코드로 영구 제외**
- `trend_4h_gate` → 워커 3곳에서 각각 호출 (공용 관문 아님)

🚨 **`trend_4h_gate` 는 통과율이 21%** 다. 켜면 진입이 1/5 로 준다.
그리고 **실서버는 이미 켜져 있다** — 2026-09-03 재조회에서 `trend_4h_gate_enabled='1'`.
「진입 후보는 많은데 실제 진입이 적다」를 조사할 때 **여기를 먼저 보라.**
🚨 `auto_bb_breakdown_worker:1545` 는 **`_create_auto_bb_strategy`(:1404-2167) 안**이다.
즉 잡이 주석 처리된 `auto_bb_breakdown` 뿐 아니라 **`unified_15m_entry` 로 만드는 전략도
이 게이트를 지난다** (§4 의 간접 경로). 「그 워커는 꺼져 있으니 상관없다」가 아니다.

실서버 ON/OFF 를 추측하지 말고 **§9 「게이트 ON/OFF 실제값」 명령으로 매번 다시 확인**한다.
사장님이 화면에서 언제든 바꾸므로 이 표의 「실서버」 열은 **찍은 순간의 값**이다.

🚨 **`support_score` 의 가장 중요한 발견**(`support_score.py:14-31`):
> **반등을 보고 들어가면 진다.** 아래꼬리·RSI 상향전환·거래량 급증은 전부
> 부호가 반대이거나 "이미 반등해서 비싸게 사는" 아티팩트였다.
> 15m MACD hist 「상승 중」은 **역방향 지표**로 채택했다.

---

### 8. 테스트 지도 — 「정적 검사는 증명하지 못한다」

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q
```

#### 8-0. 🚨 전체 실행 결과를 미리 알고 시작하라 — **지금도 52건이 실패한다**

2026-09-03, `ded22f3` 코드 + Windows / Python 3.14.2 에서 실제로 돌린 결과:

```
52 failed, 1714 passed in 696.68s (0:11:36)
```

- **12분쯤 걸린다.** 멈춘 게 아니다. 급하면 §8-1 의 두 파일만 돌린다(1초).
- **52건 실패는 새 PC 환경 탓이 아니다.** 표본으로 확인한
  `tests/unit/test_strategy_status_constants.py` 는
  「`TERMINAL_STATUSES` 는 7개」라고 단언하는데 코드는 이미 8개다
  (`STOPPED_CAPITAL_EXHAUSTED` 추가) — **코드가 앞서고 테스트가 뒤진 것**이다.
- 그래서 **「전부 green」을 목표로 삼지 마라.** 새 PC 에서 처음 한 번 돌려
  위 숫자와 **같은지**만 확인하고, 그 숫자를 기준선으로 삼는다.
  코드를 고친 뒤 실패가 **52건보다 늘면** 그게 내가 낸 것이다.

실패가 몰린 파일 (⚠️ 52건 중 **29건분만 기록**했다 — 실행 출력 끝부분만 남겨서
전수는 아니다. 전수가 필요하면 아래 명령을 `tail` 없이 다시 돌린다):

| 파일 | 실패 |
|---|---:|
| `tests/unit/test_martingale_stage_entry.py` | 7 |
| `tests/unit/test_v7_short_exit_partial_stage.py` | 4 |
| `tests/unit/test_stream_service_partial_close.py` | 4 |
| `tests/integration/test_verify_tp_sl_entry.py` | 3 |
| `tests/unit/test_strategy_status_constants.py` / `test_risk_constants_centralization.py` | 2 / 2 |

기준선을 다시 재려면 (요약만 남긴다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q 2>&1 | tail -3
```

실패 **전수를 파일별로** 보려면 (기준선을 새로 적어 둘 때 이걸 쓴다):

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q 2>&1 | grep '^FAILED' | sed 's/::.*//' | sort | uniq -c | sort -rn
```

| 위치 | 파일 수 | 성격 |
|---|---:|---|
| `tests/` (루트) | 20 (`conftest.py` 포함 = 테스트 19) | **최근 사양 검증** — Fix 303~327 대부분 여기 |
| `tests/unit/` | 80 | 순수 함수·계산·상수 고정 |
| `tests/integration/` | 58 | sqlite in-memory + FastAPI (`tests/conftest.py`) |
| `tests/e2e/` | 1 | `test_sajangnim_scenarios.py` |

`tests/conftest.py` = sqlite `:memory:` 세션 픽스처. **실 DB·실 거래소를 쓰지 않는다.**
`pytest.ini` 가 `pythonpath = .` / `testpaths = tests` 를 정하므로 **반드시 `backend/`
에서** 돌린다 (저장소 루트에서 돌리면 `tests` 를 못 찾는다).

**디렉터리별로 나눠 재면 52건이 어디 있는지 바로 보인다** (2026-09-03 실측):

| 대상 | 결과 | 시간 |
|---|---|---:|
| `tests/` 루트만 (`--ignore=tests/unit --ignore=tests/integration --ignore=tests/e2e`) | **317 passed, 0 failed** ✅ | 15초 |
| `tests/unit` | 1001 passed, **24 failed** | 82초 |
| `tests/integration tests/e2e` | 396 passed, **28 failed** | 502초 |

🚨 **Fix 303~327 사양을 담은 `tests/` 루트는 지금 100% green 이다.**
그러니 진입·손절을 고친 뒤에는 12분짜리 전체 대신 **루트 317건(15초)을 먼저** 돌린다.
여기서 하나라도 빨개지면 **그건 100% 내가 낸 것**이다 — 기준선 핑계가 없다.

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/ --ignore=tests/unit --ignore=tests/integration --ignore=tests/e2e
```

🚨 **`.env` 를 실서버 값으로 채운 채 테스트를 짜지 마라 — 실 DB 를 때릴 수 있다.**
`app/core/database.py` 는 **import 시점에** `settings.database_url`(=`.env` 의
`DATABASE_URL`)로 엔진을 만든다. 지금 있는 테스트는 워커마다
`monkeypatch.setattr("app.workers.X.SessionLocal", ...)` 로 **하나하나 갈아끼워서**
안전한 것이지, 구조적으로 막혀 있는 게 아니다.
- 새 테스트에서 `SessionLocal` 패치를 **빼먹으면 그 워커가 실서버 Neon DB 에 쓴다.**
- 워커 함수(`run_*_once()`)를 REPL·스크립트에서 맨손으로 부르는 것도 같다.
- 안전책: 새 PC 의 로컬 `.env` 는 `DATABASE_URL` 을 **실서버가 아닌 값**으로 두고,
  실서버 조회는 §9 의 VPS 명령으로만 한다.

#### 8-1. 🚨 「실행 테스트」 두 개가 특별한 이유

**`tests/test_stop_loss_execution_path.py`** — 파일 상단이 이유를 직접 적었다:

> 지금까지 내 테스트는 전부 **정적 검사**였다 — "소스에 이 문자열이 있나".
> 그건 **「그 함수가 실제로 불린다」를 증명하지 못한다.**
> (…) 같은 이름의 손절 함수가 둘인데 아래쪽을 고쳤다.
> **정적 검사 13건이 전부 통과**했고 배포까지 됐는데, 사장님 손절은 여전히
> 전량으로 나가 #2046 이 전량 청산됐다.

무엇을 하나:
- `TPSLOrchestratorService` 를 **실제로 실행**하고 거래소로 나가는
  `emergency_close_position(quantity=...)` 를 가로채 **수량을 검사**한다.
- 손절이 어느 함수를 타든 상관없다 — **주문이 부분인지만 본다.**
- 함수를 잘못 고르면 **즉시 실패**한다.
- 잔량을 남겼는데 `STOPPING` 을 찍으면 실패 / 부분인데 미체결 주문을 취소하면 실패.

**`tests/test_stage_flow_execution.py`** — 같은 방식으로 `trigger_next_stage` 를
실행해 **주문의 순서와 수량**을 검사한다. 상단에 사고 3건이 적혀 있다:

| 사고 | 정적 검사 결과 |
|---|---|
| Fix 318 — 엉뚱한 손절 함수에 붙였다 | 13건 **전부 통과** |
| Fix 311 — 1단계 진입을 통째로 막았다 | 57건 **전부 통과** |
| Fix 315 — 마커를 저장 안 해 손절을 다시 잠갔다 | **테스트가 없었다** |

검증 대상 사양:
```
기본 방식 : 트리거 단가 도달 → 10 USDT 남기고 청산 → 그 단가에 다음 단계 진입
OBV 자동  : 같은 흐름 (판정만 stage_entry_signal 이 한다)
1단계 10  : "손절없이 그냥" → 정리 없이 바로 다음 단계
볼밴 분할 : 물타기가 설계 → 정리하지 않는다
```

🚨 **새 PC 에서 진입/손절 코드를 건드리면 이 두 파일을 반드시 돌려라.**

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/test_stop_loss_execution_path.py tests/test_stage_flow_execution.py
```

✅ 이 두 파일은 **`28 passed in ~1s`** 가 나와야 한다 (2026-09-03 실행 확인).
위 전체 실행의 52건 실패와 달리 **여기는 하나도 실패하면 안 된다** — 1건이라도
빨간색이면 진입·손절 실행 경로가 깨진 것이므로 **거기서 멈춘다.**

#### 8-2. 구조를 고정하는(회귀 방지) 테스트

| 파일 | 무엇을 고정하나 |
|---|---|
| `tests/test_symbol_exclusion.py` | Fix 303 이 주문 함수 **세 곳 모두**에 있는지 |
| `tests/unit/test_pyramiding_excludes_bbsplit.py` | `SPLIT_ENTRY_MODE` ↔ `MODE_MARKER` 문자열 동기화 |
| `tests/test_stage_gate_exempt.py` / `tests/test_force_sl_stage_gate.py` | 단계 게이트 면제 규칙 |
| `tests/test_partial_stop_loss.py` / `tests/test_stage_trim.py` | 부분 손절 수량 계산 |
| `tests/unit/test_status_set_centralization.py` / `test_strategy_status_constants.py` | 상태 집합 단일 출처 ⚠️ 후자는 **현재 2건 실패**(위 기준선) |
| `tests/unit/test_codebase_guards.py` / `test_static_assets_integrity.py` | 코드베이스 가드 / `?v=` 해시 ⚠️ **각 1건 실패** |
| `tests/unit/test_last_stage_trigger_single_source.py` | 「같은 칸이 두 저장소」 재발 방지 |
| `tests/test_chg24_entry_gate.py` / `test_support_score.py` / `unit/test_trend_4h_gate.py` | 신설 게이트 |

---

### 9. 새 PC 에서 바로 쓸 확인 명령

#### 9-0. ⛔ 새 PC 에서 **절대 하면 안 되는 것 네 가지**

이 문서의 명령은 전부 「읽기」다. 아래 넷은 읽기처럼 보이지만 **실자금이 나간다.**

| ⛔ 하지 마라 | 무슨 일이 나나 | 대신 |
|---|---|---|
| **로컬에서 스케줄러 실행** (`python -m app.workers.scheduler_runner`, `docker compose up`) | 리더 선출은 Redis `sched:leader` **한 키**로 한다(`distributed_scheduler_guard.py:11`). 로컬 Redis 는 VPS 와 **다른 Redis** 라 로컬 인스턴스가 **즉시 자기 리더**가 되고, `.env` 의 실서버 DB + 실 API 키로 **41개 워커 전부**를 돈다 → VPS 와 **동시에 같은 심볼에 주문**한다 | 실행은 VPS 에서만. 로컬은 §9 의 조회 명령만 |
| **로컬에서 `uvicorn app.main:app`** | 같은 이유. API 만 띄워도 `/api/v1` 의 진입·청산 엔드포인트가 **실서버 DB + 실 계정**에 붙는다 | 화면 확인이 필요하면 VPS 의 실제 화면을 본다 |
| **로컬에서 바이낸스 API 를 직접 호출** (심볼 루프, 캔들 수집, `client.py` 를 REPL 에서 부르기) | ① 가중치 한도는 **IP 단위** → `-1003` / HTTP **418 IP ban**. 이 저장소는 ban 을 **스스로 연장한 전력**이 있다. ② 주문·요청 카운트 일부는 **계정 단위** → 로컬이 태운 몫만큼 **VPS 의 실매매가 굶는다**. 실제로 이 이유로 `tp_sl`·`stage_trigger` 주기를 10s→15s 로 낮췄다(`scheduler_runner.py:533-534`) | 시세·포지션은 §9 의 **VPS DB 조회**로 본다 |
| **`alembic upgrade head` 를 로컬에서** | `.env` 가 실서버 Neon 을 가리키면 **운영 DB 스키마가 바뀐다.** 되돌리기가 가장 어려운 작업이다 | 마이그레이션은 배포 절차의 일부 — 사장님 승인 + VPS 에서만 |

🚨 **위 넷의 공통 방아쇠는 하나 — 실서버 값이 든 `.env`.**
새 PC 로컬 `.env` 는 `DATABASE_URL` / `REDIS_URL` / 바이낸스 키를 **실서버가 아닌 값**으로
두는 것이 유일하게 안전한 상태다. 실서버 값이 필요하면 그때만, VPS 안에서 쓴다.

🚨 **코드를 만질 때 — 이 저장소는 worktree 를 공유한다.**
`git stash` / `git stash pop` 을 맨손으로 쓰지 마라. stash 는 **저장소 전역**이라
다른 worktree·다른 세션이 만든 stash 와 섞이고, `pop` 이 충돌하면 어느 쪽 변경인지
분간이 안 된다. 임시 보관이 필요하면 **브랜치를 하나 파서 커밋**한다
(`git switch -c wip/설명 && git add -A && git commit -m wip`).
같은 이유로 `git reset --hard` / `git clean -fd` / `git push --force` 도
**현재 worktree 밖의 남의 작업을 지운다** — 쓰지 마라.

**로컬 — 코드 구조 확인** (읽기만 한다)

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && for d in */; do echo "$d $(find "$d" -name '*.py' -not -path '*__pycache__*' | wc -l)"; done
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n 'id="' workers/scheduler_runner.py
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend/app" && grep -n "^    def " services/execution_service.py
```

```bash
cd "C:/Users/user/바이낸스/binance-auto-trader/backend" && python -m pytest -q tests/test_stop_loss_execution_path.py tests/test_stage_flow_execution.py
```

**VPS — 읽기 전용 조회** (🚨 재시작·설정변경·DB 쓰기 금지)

🚨 **`system_settings` 는 재시작 없이 즉시 먹는다 = 되돌릴 「배포」가 없다.**
워커들이 매 사이클 DB 에서 값을 다시 읽으므로, 한 줄 UPDATE 가 **다음 15초 안에**
실매매 동작을 바꾼다. 그래서 값을 바꾸는 일은 사장님 몫이고, 부득이 바꿔야 한다면
**바꾸기 전에 옛 값을 반드시 먼저 찍어서 남긴다** (이게 유일한 rollback 기록이다):

```bash
# ① 바꾸기 전 — 현재 값 백업 출력 (읽기)
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value from system_settings where key = :k\"), {\"k\":\"바꿀_키_이름\"}):
    print(\"BEFORE\", r)
"'
```
행이 **하나도 안 나오면** 그 키는 「미설정」이고, 되돌릴 때는 값을 되쓰는 게 아니라
**그 행을 지워야** 원래 상태가 된다 (「미설정」과 「빈 값」은 다르다 —
`excluded_symbols` 가 바로 그 예, §4-1).

⛔ **선행 조건**: 아래 `ssh` 가 `Permission denied (publickey)` 로 막히면 코드 문제가
아니다. 서버는 **비밀번호 로그인이 꺼져 있고** 등록된 공개키가 1개뿐이라, 그 짝인
개인키(`~/.ssh/id_ed25519`)가 새 PC 에 없으면 **어떤 방법으로도 못 들어간다.**
옮기는 절차는 `secrets.md` §7 / `vps-ops.md` 를 볼 것 — **이 문서에는 없다.**
(개인키를 옮기는 건 사장님이 직접 한다. 채팅·메일로 보내지 말 것.)

> 🔐 **아래 명령을 응용하기 전에 — 컨테이너 안에서는 비밀이 평문으로 튀어나온다.**
> 이 recipe 는 api 컨테이너 안에서 **앱 코드를 그대로 실행**한다. 그래서 아래 세 가지는
> 실행하는 순간 터미널 스크롤백·채팅 로그·스크린샷에 **실키가 남는다.**
>
> | ❌ 절대 하지 말 것 | 왜 |
> |---|---|
> | `print(settings)` / `print(settings.model_dump())` | `config.py` 는 `SecretStr` 을 안 쓴다 — 전 필드가 평문 `str` 이라 `ENCRYPTION_KEY`·`DATABASE_URL`·`TELEGRAM_BOT_TOKEN`·`SECRET_KEY` 가 **한 줄에 전부** 찍힌다 (`app/core/config.py:8-26`, 저장소 전체에서 `SecretStr` 사용 **0곳**) |
> | `print(decrypt_text(account.api_key_enc))` | 바이낸스 **실계좌 API 키 평문**. 앱 코드는 `decrypt_text()` 결과를 로그·print 로 내보내는 곳이 **0곳**이다(`grep -rnE '(logger\|print)\..*decrypt_text' app` = 무결과) — 조회하겠다고 그 규칙을 깨지 말 것 |
> | `select * from exchange_accounts` | `api_key_enc` / `api_secret_enc` 암호문이 통째로 나온다. `ENCRYPTION_KEY` 를 가진 사람에게는 평문과 같다 |
> | `env` / `cat .env` / `docker compose config` | 같은 이유 |
>
> ✅ 대신 **존재·길이·성공여부만** 본다 —
> `print(bool(settings.encryption_key), len(settings.encryption_key))`,
> `try: print("DECRYPT_OK", len(decrypt_text(a.api_key_enc)))` / `except Exception as e: print("FAIL", type(e).__name__)`.
> (🚨 `decrypt_text` 는 실패 시 **falsy 를 반환하지 않고 `CryptoError` 를 던진다** —
> `if decrypt_text(...) else` 식으로 쓰면 FAIL 이 찍히는 게 아니라 그냥 죽는다.)
> 값을 대조해야 하면 **지문**으로 — `sha256` 앞 12자만 비교한다 (`secrets.md` §4 가 이 방식을 쓴다).
>
> 🔑 **비밀을 새 PC 로 옮기는 방법은 이 문서에 없다** — `secrets.md` §3/§7 을 볼 것.
> 카카오톡·이메일·채팅·이 대화창에 키를 붙여넣지 마라. `.env` 는 git 에 없고
> (저장소 루트 `.gitignore:1-10` — `.env` / `backend/.env` / `*.pem` / `*.key` 전부 제외.
> 추적되는 건 값 없는 `.env.example` 과 `.env.production.template` 둘뿐이다),
> 있어야 할 곳은 **각 PC 의 디스크뿐**이다.
>
> ⚠️ 아래 명령의 `-o StrictHostKeyChecking=no` 는 **서버 신원 확인을 끄는 옵션**이다.
> 사무실 PC 는 이미 `known_hosts` 에 이 서버가 있어서 무해했지만, **새 PC 는 처음
> 접속이라 「어떤 서버든 그냥 받아들인다」**는 뜻이 된다 — 그 세션으로 mainnet 키를
> 쥔 서버에 root 로 들어간다. 새 PC 에서 **첫 접속 한 번만은 옵션 없이** 붙어
> 지문을 눈으로 확인하고 `yes` 를 치는 편이 안전하다. 한 번 등록되면 그 뒤로는
> 아래 명령을 그대로 써도 된다.

배포 커밋 확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && git log --oneline -3 && docker compose ps'
```

네 방식의 실제 분포:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select t.strategy_type, t.trigger_mode, s.capital_management_mode, count(*) from strategy_instances s left join strategy_templates t on t.id=s.strategy_template_id group by 1,2,3 order by 4 desc limit 25\")):
    print(r)
"'
```

게이트 ON/OFF 실제값:

🚨 **없는 키는 「꺼짐」이 아니라 「미설정 = 코드 기본값」이다.** 이 저장소는
「모름」을 「꺼짐」으로 표시했다가 사고가 난 전력이 있다(fail-OFF). 그래서 아래는
`like` 로 있는 것만 긁지 말고 **볼 키를 먼저 적고 없으면 없다고 찍는다.**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
KEYS = [
 \"unified_entry_enabled\",\"auto_bb_break_daily_limit\",
 \"entry_chg24_gate_enabled\",\"entry_rank_top_n\",\"entry_chg24_gate_mode\",
 \"support_score_gate_enabled\",\"trend_4h_gate_enabled\",\"excluded_symbols\",
 \"stage_trim_before_next_enabled\",\"stage_keep_notional_usdt\",\"stage_min_trim_ratio\",
 \"stage_wait_for_turn_enabled\",\"sajangnim_ladder_stages_enabled\",
 \"sajangnim_capital_ladder\",\"sajangnim_stage_gap_pct\",
]
rows = dict(db.execute(text(\"select key, value from system_settings where key = any(:ks)\"), {\"ks\": KEYS}).all())
for k in KEYS:
    print(k.ljust(34), rows.get(k, \"(미설정 = 코드 기본값)\"))
"'
```

2026-09-03 실측 결과 — 이 표가 「코드 기본」과 다른 곳이 곧 사장님이 손댄 곳이다:

```
unified_entry_enabled              0                      ← 🚨 통합 진입 OFF
auto_bb_break_daily_limit          0                      ← 🚨 일일 한도 0 = 진입 없음
entry_chg24_gate_enabled           1
entry_rank_top_n                   (미설정 = 코드 기본값 50)
entry_chg24_gate_mode              (미설정 = 코드 기본값 rank)
support_score_gate_enabled         (미설정 = OFF)
trend_4h_gate_enabled              1                      ← 🚨 켜져 있다 (통과율 21%)
excluded_symbols                   (미설정 = 내장 11종)
stage_trim_before_next_enabled     1
stage_keep_notional_usdt           (미설정 = 코드 기본값 10)
stage_min_trim_ratio               (미설정 = 코드 기본값 2)
stage_wait_for_turn_enabled        1
sajangnim_ladder_stages_enabled    1
sajangnim_capital_ladder           10,300,600
sajangnim_stage_gap_pct            (미설정 = 코드 기본값 1.5)
```

(옛 버전의 `like` 방식도 남겨 둔다 — **위 목록에 없는 키를 찾을 때만** 쓴다.)

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value from system_settings where key like :a or key like :b or key like :c or key like :d\"), {\"a\":\"%ladder%\",\"b\":\"stage_%\",\"c\":\"%chg24%\",\"d\":\"%gate_enabled%\"}):
    print(r)
"'
```

🚨 **사다리가 진짜 3단계로 생기는지** (§3-2 미확인 항목):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select s.id, s.symbol, s.capital_management_mode, count(p.id) plans, s.created_at from strategy_instances s left join strategy_stage_plans p on p.strategy_instance_id=s.id join strategy_templates t on t.id=s.strategy_template_id where t.strategy_type like :st group by 1,2,3,5 order by s.id desc limit 10\"), {\"st\":\"auto_bb_break_SAJANGNIM%\"}):
    print(r)
"'
```

🚨 **함정**: DB 는 로컬 `db` 컨테이너가 아니라 **외부 Neon** 이다.
`docker compose exec db psql` 로 조회하면 **빈 DB** 가 나와 「테이블이 없다」는
오진에 이른다. 반드시 위처럼 `api` 컨테이너의 앱 세션(`PYTHONPATH=/app`)으로 접근한다.
쿼리가 실패하면 `db.rollback()` 을 해야 다음 쿼리가 돈다.

---

### 10. 🚨 새 PC 가 빠지기 쉬운 함정 모음

| 함정 | 왜 위험한가 | 확인법 |
|---|---|---|
| **`trigger_mode` 로 방식을 판단** | 네 방식 대부분이 `PRICE_DOWN_PCT` 다 (§3-1) | `strategy_type` 접두사 + `capital_management_mode` 를 같이 봐라 |
| **손절 함수를 잘못 고름** | Fix 318 사고. 정적 검사 13건 전부 통과했다 | 사장님 % = `force_sl_*` = `_execute_force_stop_loss` |
| **`trigger_next_stage` 에 진입 게이트 추가** | 이미 자금이 들어간 사다리가 **영원히 멈춘다** | `execution_service.py:203-205, 250` |
| **스케줄러에 있으니 돈다고 판단** | `unified_15m_entry` 는 30초마다 도는데 `unified_entry_enabled=0` / `auto_bb_break_daily_limit=0` 이라 **진입 0건**이다 | §6-1 끝 + §9 설정 조회 |
| **설정 조회 결과에 없는 키를 「꺼짐」으로 해석** | 「모름」을 「꺼짐」으로 보여줘 사고가 난 전력(fail-OFF) | §9 의 **키 목록 명시형** 조회를 쓴다 |
| **`python -m pytest -q` 가 다 통과할 거라 기대** | 지금도 **52건 실패**가 기준선이다. 「내 환경이 깨졌나」로 오진한다 | §8 기준선 표 |
| **worktree 경로 그대로 복사** | `.claude/worktrees/` 는 `.gitignore` 라 새 PC 에 없다 | 문서 상단 「경로」 블록 |
| **`split_entry` 에 정리·피라미딩을 얹음** | 평단이 설계와 반대로 밀린다. 실측 −252.18 USDT | `stage_trim.py:75` `ALWAYS_EXCLUDED_MODES` |
| **단계 간격을 손절폭보다 크게** | 손절이 항상 먼저 와서 2단계에 **영원히 도달 못 함** | `sajangnim_capital.py` 실측표. 기본 1.5% |
| **주석 처리된 워커를 「살아 있다」고 판단** | `pump_top_detector` / `auto_short_at_top` 은 아래에서 다시 등록된다 | `grep -n 'id="' workers/scheduler_runner.py` 로 **중복 id** 확인 |
| **워커 로그가 없으면 죽었다고 판단** | 락 TTL 초과로 조용히 skip 될 수 있다 | 「연속 N회 건너뜀」 경고 로그를 찾아라 |
| **`docker compose exec db psql` 로 DB 조회** | 빈 DB → 「테이블이 없다」 오진 | §9 의 api 컨테이너 방식 |
| **fail 방향을 통일** | Fix 304 는 fail-CLOSED, Fix 312·310·327 은 fail-OPEN. **일부러 다르다** | 각 함수 docstring |
| **10 USDT 미만 잔량을 남김** | reduceOnly 거부 = 영원히 못 파는 dust. **계정 전체가 막힌 전력** | `symbol_exclusion.py` 제외 목록 |
| 🔐 **`ENCRYPTION_KEY` 를 새 PC 에서 새로 생성** | DB 의 `api_key_enc` 를 **영원히** 복호화 못 함. 바이낸스 키 재발급밖에 답이 없다 | §2-1 / `secrets.md` §3 |
| 🔐 **컨테이너에서 `print(settings)`** | `SecretStr` 을 안 써서 전 비밀이 평문 한 줄로 찍힌다 — 스크롤백·채팅 로그에 남는다 | §9 상단 🔐 블록 |
| 🔐 **키를 채팅·메일로 전달** | 이 문서를 포함해 **어떤 문서에도 값을 적지 않는다**. 이름과 획득처만 | `secrets.md` §7 |
| 💸 **로컬에서 스케줄러·`uvicorn` 실행** | 리더 키가 Redis 별로 따로라 로컬이 **즉시 자기 리더**가 된다 → VPS 와 **동시에 실주문** | §9-0 |
| 💸 **로컬에서 바이낸스 API 직접 호출** | IP 단위 418 ban + **계정 단위 주문 한도**를 VPS 실매매와 나눠 쓴다 | §9-0 |
| 💸 **로컬에서 `alembic upgrade head`** | `.env` 가 실서버면 **운영 스키마가 바뀐다.** 되돌리기가 가장 어렵다 | §9-0 |
| 💸 **`excluded_symbols` 에 한 종목만 적음** | 이 키는 add 가 아니라 **replace** — 내장 11종이 **전부 풀린다** → BTCUSDT dust → 계정 차단 | §4-1 표 |
| 💸 **주석 워커 롤백 순서를 뒤집음** | `unified` 와 `auto_bb_breakdown` 이 같은 후보를 봐서 **같은 심볼에 이중 진입** | §6-3 순서표 |
| 💸 **새 테스트에서 `SessionLocal` 패치 누락** | 엔진이 `.env` 의 `DATABASE_URL` 로 import 때 만들어진다 → **실 DB 에 쓴다** | §8 경고 블록 |
| 🧨 **`git stash pop` / `reset --hard` / `push --force` 를 맨손으로** | worktree 를 공유해서 **다른 세션의 작업이 사라진다** | §9-0 |

---

### 11. ⚠️ 확인 못 함

- **`stage_ladder` 모드로 만들어진 전략이 실서버에 아직 0건.** 코드(Fix 315/321)는
  배포돼 있고 `sajangnim_ladder_stages_enabled=1` 이지만, 최근 24h SAJANGNIM 전략 9건은
  전부 `fixed` + `stage_plans` 1개였다. api/scheduler 가 조회 시점 기준 12분 전
  재시작이라 **「배포 이후 새 전략이 아직 없어서」인지 「stages_config 가 여전히
  1단계로 계산되어서」인지 구분하지 못했다.** §9 마지막 명령으로 확인할 것.
  (2026-09-03 재조회에서도 최신이 `#2045`(09-02 23:12 UTC) 그대로였다 = 그 사이
  새 SAJANGNIM 전략이 아예 안 생겼다. `unified_entry_enabled=0` 과 관련이 있을 수
  있으나 **인과는 확인하지 못했다.**)
- **`agents/` 17개 팀(+`orchestrator/`)의 실행 경로.** `scheduler_runner` 에
  `learning_team_cycle`(4h) 등 일부만 보였다. 각 팀이 어떤 워커에서 불리는지는
  전수 추적하지 않았다. (`agents/TEAMS.md` 는 「13개 팀」이라고 적혀 있는데 **낡았다** —
  실제 폴더는 17개다. 그 파일의 숫자를 믿지 말 것.)
- **`static/js` 43개 파일의 화면-코드 대응.** UI 담당 섹션이 별도로 있으므로 여기서는
  `cm-submit.js:217, 261` (진입 방식 전송)만 확인했다.
- **`api/v1` 36개 파일의 엔드포인트 전수 목록.** 라우터 등록(`api/router.py`)만 확인했다.
- **워커 상당수의 내부 로직.** 26,790줄 중 진입·손절·스케줄에 직접 관계된 것만 읽었다.
- **§9-0 「로컬 실행」 위험의 severity 는 코드로 추론한 것이지 실측이 아니다.**
  실제로 띄워 보는 것 자체가 실주문 위험이라 **일부러 시험하지 않았다.**
  근거는 `distributed_scheduler_guard.py:10-26`(리더 키 `sched:leader` 하나) +
  `core/database.py`(엔진을 import 시점에 `.env` 로 생성) 두 가지다.
  Neon 이나 바이낸스 쪽에 IP 허용목록이 걸려 있어 로컬 연결이 그냥 막힐 가능성은
  **확인하지 못했다** — 막힌다는 보장이 없으므로 위험으로 취급한다.
- **바이낸스 한도의 IP 단위 / 계정 단위 경계를 실측하지 않았다.** §9-0 의 근거는
  `scheduler_runner.py:533-534` 주석(「API Ban -1003 여러 번 발생 → interval 10s→15s」)과
  이 저장소의 418 ban 전력이다. 정확한 한도 표는 바이낸스 문서를 볼 것.
- **실패 52건의 전수 목록.** 디렉터리별 집계(루트 0 / unit 24 / integration+e2e 28)까지만
  확인했고, 개별 테스트 이름은 §8-0 의 일부만 적었다. 전수는 §8-0 의 `grep '^FAILED'` 명령으로.


---

<a id="sec-7"></a>

## 7. 현재 운영 상태 — 무엇이 돌고 있나

> 조사 시각: **2026-09-03 18:15 KST** (= 09:15 UTC)
> 조사 방법: VPS 읽기 전용 SSH + api 컨테이너 앱 세션 SQL + 로컬 저장소 코드/커밋 감사
> 이 섹션의 모든 숫자에는 근거(명령 출력 또는 `파일:줄번호`)가 붙어 있다.

---

### 0. 한눈에 보기 (새 PC에서 제일 먼저 알아야 할 것)

| 항목 | 값 | 비고 |
|---|---|---|
| VPS 배포 커밋 | `ded22f3` (Fix 327) | **런타임 코드의 최신 커밋.** 조사 시점엔 로컬 워크트리 HEAD 와 같았으나, 그 뒤 핸드오프 문서 커밋 `e51d9a8` 이 얹혀 지금 워크트리는 `e51d9a8` 이다 — `backend/app/` 실행 경로 차이는 **0건** (§2) |
| GitHub `main` | `e51d9a8` | VPS 보다 1커밋 앞 — **핸드오프 문서만** (런타임 코드 무관) |
| 실행 컨테이너 | api = **`2026-09-03T08:51:26Z`** / scheduler = **`08:51:57Z`** 에 시작 | 배포 반영됨 (아래 §2 검증). 🚨 「Up N minutes」 같은 **상대 시각은 읽는 시점마다 달라지므로 쓰지 말 것** — 절대 시각으로 기록한다 |
| 포지션 보유 전략 | **8건** (전부 `STAGE1_OPEN`, 전부 레버리지 2) | §3 |
| 오늘(KST) 진입 | 자동 32건 / 수동 18건 | §4 |
| 오늘(KST) 실현손익 (진입일 기준) | 자동 **−36.91** / 수동 **+229.30** | §4 — 🚨 수동은 2건이 전부 |
| Kill-Switch | **OFF** (`is_enabled=false`, 2026-08-31 해제됨) | §6 |
| alembic 버전 | `0034_surge_ladder` | §6 |
| 스케줄러 프로세스 시작 | 9.5시간에 **14회** (= 오늘 배포 횟수와 일치, 크래시 루프 아님) | §7 ① — 「40분마다 재시작」이 아니다. 연속 가동 최장 **5h04m** |
| `chart_patterns` 테이블 | **0건** | §7 미해결 ① — 데이터 0 은 사실, 원인 단정은 금지 |

---

### 0.5 🚨🚨 새 PC 첫날 — 실제로 돈이 날아가는 5가지 (이 섹션을 먼저 읽어라)

이 문서의 나머지는 **조회**다. 아래 5개는 **한 줄로 실자금 사고가 나는 것들**이다.
지금 실계정에 **포지션 8건**(§3)이 물려 있고 스케줄러가 **초 단위로 주문을 낸다**.

| # | 절대 하지 마라 | 왜 — 무슨 일이 나는가 |
|---|---|---|
| **1** | 새 PC에서 `docker compose up` / `python -m app.workers.scheduler_runner` | 🚨 **가장 위험.** 실계정 API 키는 `.env` 가 아니라 **DB 에 암호화되어**(`exchange_accounts.api_key_enc` / `api_secret_enc`) 들어 있고, `.env` 의 **`DATABASE_URL`(운영 Neon) + `ENCRYPTION_KEY`** 두 개만 맞으면 **그대로 복호화된다**. 즉 로컬에서 띄우는 순간 **VPS 스케줄러와 같은 계정·같은 DB 에 붙은 두 번째 스케줄러**가 된다 → 같은 전략에 **중복 주문**, 단계 전환·손절이 **두 프로세스에서 동시에** 나간다. 이 저장소는 이미 「부분 손절 12~17초 뒤 전량 청산」 사고(Fix 326)를 겪었다 — 그건 **한 프로세스일 때** 얘기다. |
| **2** | 로컬에서 Binance REST 직접 호출 (조사 스크립트 포함) | 🚨 **IP ban(418)** 전력이 있다 (2026-08-26, 가드가 ban 을 스스로 연장). 새 PC 는 **새 IP** 다. 실계정 키가 VPS IP 화이트리스트에 묶여 있으면 실패하고, 안 묶여 있으면 **레이트리밋을 VPS 와 나눠 쓰다가 운영 계정 전체가 밴된다**. 시세·포지션은 전부 **VPS api 컨테이너를 통해** 보라 (§8). |
| **3** | 로컬에서 `alembic upgrade head` / `alembic downgrade` | 🚨 `alembic/env.py:27-30` 이 **`DATABASE_URL` 환경변수를 그대로 쓴다.** 그 값은 **운영 Neon DB** 다. 로컬에서 실행하면 **운영 DB 스키마가 바뀐다.** 현재 `0034_surge_ladder`. 마이그레이션은 **VPS 에서, 사장님 승인 후에만.** (참고: `pytest` 는 안전하다 — `tests/conftest.py:6` 이 인메모리 SQLite 를 쓴다.) |
| **4** | `git stash` / `git stash pop` | 🚨 이 저장소는 **worktree 를 공유**한다. stash 는 저장소 전역이라 다른 worktree 작업까지 빨아들이고, `pop` 이 충돌하면 **어느 쪽 것이었는지 복구가 어렵다.** 임시 보관이 필요하면 stash 말고 **브랜치를 새로 파서 커밋**하라 (`git switch -c wip/$(date +%m%d-%H%M) && git add -A && git commit -m wip`). |
| **5** | VPS 에서 `git pull` 을 「조회」라고 생각하기 | 🚨 `docker-compose.yml` 이 `.:/app` **바인드 마운트**다 (`backend/docker-compose.yml`, api·scheduler 양쪽). 즉 **`git pull` 하는 순간 컨테이너 안 파일이 바뀐다.** 재시작 전까지 실행 중인 프로세스는 **옛 코드와 새 코드를 섞어 import** 할 수 있다 (파이썬은 함수 안 import 를 그때그때 읽는다 — 이 저장소에 그런 지연 import 가 많다). **`git pull` = 배포의 시작이지 조회가 아니다.** |

#### 🚨 사고가 났을 때 — 지금 당장 멈추는 법 (외워 둘 것)

거래를 즉시 멈추는 **정식 경로는 Kill-Switch API** 다. DB 를 손으로 고치는 것보다 먼저 이것을 쓴다.

```
POST /api/v1/admin/kill-switch/{exchange_account_id}/enable      ← 멈춤
POST /api/v1/admin/kill-switch/{exchange_account_id}/disable     ← 해제
```
(`app/api/v1/admin/operations.py:257`, `:274` — 라우터 prefix 는 `app/api/router.py:26` 의 `/api/v1` + `/admin`. 로그인 토큰 필요, 계정 소유권 검증 있음.)

⚠️ **Kill-Switch 는 만능이 아니다** — 메모리 확정 사항(2026-08-26 「Kill-Switch 3대 공백」):
- KS 를 켜도 **증거금 주입은 계속된다**.
- **해제하는 순간 밀려 있던 알람이 일괄 발사**된다 → 해제 전에 무엇이 대기 중인지 먼저 보라.
- dust orphan 포지션 하나가 **계정 전체를 차단**한 전력이 있다.

더 확실하게 멈추려면 **스케줄러만** 세운다 (api 는 살려 두어야 화면·수동 청산이 된다).
🚨 이것은 **쓰기 작업이고 사장님 승인 사항**이다. 되돌리는 법을 같이 적어 둔다:
```bash
# 멈춤 (승인 후)
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose stop scheduler'
# 되돌리기
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose start scheduler'
```
⚠️ 스케줄러를 세우면 **자동 손절·단계 전환·재진입이 전부 멈춘다.** 포지션 8건이 무방비가 된다는 뜻이다 — 「멈추는 것」도 위험한 선택지다. 세웠으면 **화면에서 수동으로 지켜볼 것.**

---

### 1. Fix 300~327 이력 (한 줄 요약)

로컬 `git log` 기준. 전부 **2026-09-02~09-03 이틀 사이**에 만들어졌다.

아래 명령은 **저장소 루트**(`backend/` 가 아니다)에서 돌린다. `-60` 은 커밋이 더 쌓이면 모자라므로
Fix 299 커밋(`8010e6f`)까지 범위로 지정하는 편이 안전하다.

```bash
cd /path/to/binance-auto-trader          # 새 PC: git clone 한 디렉터리
git log --format='%h|%ad|%s' --date=format:'%Y-%m-%d %H:%M' 8010e6f~1..HEAD \
  | grep -E 'Fix 2?3?[0-9]{2}'
```
> 표 첫 줄의 Fix 299 도 함께 보려면 위처럼 범위를 쓴다. 원래 쓰던
> `git log … -60 | grep -E 'Fix (3[0-2][0-9])'` 은 **Fix 299 를 걸러내고**, 커밋이 60개 넘게
> 쌓이면 오래된 Fix 를 놓친다.

| Fix | 커밋 | 시각(KST) | 한 줄 요약 |
|---|---|---|---|
| 299 | `8010e6f` | 09-03 02:46 | 변동성 연동 TP1 — 급등락 15% / 안정 3~5% |
| **300** | `9b51273` | 09-03 03:18 | 추가(피라미딩) 진입 트리거 ROI 를 하드코딩 → **설정**으로 (사장님 「+2%부터」) |
| **301** | `560e8fb` | 09-03 03:27 | 재진입 「대기 모니터링」을 Redis+API 로 화면에 남긴다 (99% 잔량은 쓸 수 없음이 밝혀져서) |
| **301b** | `b21c59a` | 09-03 03:31 | 재진입 대기 화면 = 「종료 숨김」과 **독립된** 접이식 패널 |
| **302** | `4619735` | 09-03 06:34 | 🚨 손실률 분모가 틀렸다 — `isolatedMargin` → **`isolatedWallet`** (−96.74% 로 뜨던 게 실제 −49.85%) |
| **303** | `b6fc9a2` | 09-03 07:06 | BTC/ETH 계열 11종 자동매매 제외 (MIN_NOTIONAL > 10 이라 「10 USDT 남기기」 불가) |
| **304** | `807fa26` | 09-03 07:15 | 단계 전환 시 「10 USDT 만 남기고 청산」 = 물타기 → 손절 후 재진입. **기본 OFF** |
| **305** | `030ebd9` | 09-03 07:32 | Fix 304 의 차단 요인 5건 (재시도가 잔량까지 던짐 / 전량 폴백이 단계 LIMIT 삭제 / 시세오류 알림폭탄 / 사각지대 영구정지 / 수동 ▶다음단계가 정리 건너뜀) |
| **306** | `33b88df` | 09-03 08:02 | 단계 청산으로 **확정된 손실이 화면·손절 판정에서 사라지던** 것 — 화면 realized 합산 + 누적손실 상한 게이트 + retry/정리 모드 충돌 가드 |
| **307** | — | — | ⚠️ 독립 커밋 없음 (306 또는 308 에 흡수된 것으로 보임 — **확인 못 함**) |
| **308** | `f8a052b` | 09-03 08:23 | 🚨 OBV 자동 30일 0건의 진짜 이유 — **이벤트 이름 불일치** (`FORCE_STOP_LOSS_TRIGGERED` 를 기록하는데 워커는 존재하지 않는 3개 이름을 조회) |
| **309** | `8c91bba` | 09-03 08:32 | OBV 알람을 `market_observations` 에 관찰 기록으로 남긴다 (Redis TTL 24h 라 사후 검증 불가였음) |
| **310** | `eb27d39` | 09-03 08:38 | 당일 **\|24h\| ≥ 10%** 심볼만 신규 진입 (`start_stage1` 한 곳에만, 단계 진입엔 미적용, 수동 `_quick_` 제외) |
| **311** | `defa0d7` | 09-03 09:01 | 1단계(10 USDT)는 정리하지 않는다 — 청산분이 잔량의 2배 미만이면 스킵 |
| **312** | `defa0d7` | 09-03 09:01 | 다음 단계는 「좋은 포지션」을 기다린다 (Fix 276 꺾임 판정, **SHORT 만** 기본 적용) |
| **313** | `d42b23c` | 09-03 09:16 | 🚨 Fix 304 부분손절이 **전역 스위치 1개**라 볼밴 분할(`split_entry`, 일부러 물타기하는 설계)을 파괴 → `split_entry` 코드 레벨 제외 |
| **314** | `d42b23c` | 09-03 09:16 | 🚨 「설정만 수정」이 `trigger_mode` 미복사로 **OBV 전략을 기본전략으로 영구 강등** |
| **315/317** | `aec3208` | 09-03 09:52 | 🚨 다단계 전략에서 **손절이 마지막 단계까지 보류**되던 v130 교착 |
| **316** | `65fbc8c` | 09-03 09:48 | 내가 만든 Fix 311 이 사장님 사양을 통째로 막고 있었다 (SKIP/BLOCK 분리 도입) |
| **318** | `8e0fc72` | 09-03 09:56 | 손절도 「10 USDT 남기는 부분 손절」이어야 하는데 전량 청산으로 나가고 있었다 |
| **319** | `7fcd332` | 09-03 10:03 | 🚨 Fix 318 이 **엉뚱한 함수**에 붙어 있었다 — 사장님 손절은 `_execute_force_stop_loss` 로 간다 |
| **320** | `77edfc9` | 09-03 10:34 | 손절 실행 경로 **통합(실행) 테스트** 신설 — 정적 검사 13건이 못 잡던 사고를 즉시 잡음을 증명 |
| **321** | `ddb8fb6` | 09-03 10:45 | 🚨 내가 Fix 315 로 손절을 다시 잠갔다 (`stage_ladder` 마커 대입 0곳) — **검증이 잡았고 실피해 0**. 게이트 면제를 3곳 전부에 적용 |
| **322** | `fcd8462` | 09-03 10:51 | 기본 방식: **손절 ROI 가 명시된 전략은 단계 게이트를 면제** (스위치 하나에 손절이 매달려 있던 것) |
| **323** | `fcd8462` | 09-03 10:51 | OBV 자동이 2단계에 영원히 도달 못하던 것 (Fix 177 의 우회가 정상 단계진입을 통째로 스킵) |
| **324** | `61e19a8` | 09-03 15:55 | 사장님 수치로 확정 — 「10 usdt」는 **증거금**(명목 = 10×레버), 1단계는 **정리하지 않는다**(SKIP) |
| **325** | `0459e8f` | 09-03 16:50 | 진입 대상을 절대값 → **「상승 50 + 하락 50 = 100개」 순위**로 (`entry_chg24_gate_mode` 기본 `rank`) |
| **326** | `1d04598` | 09-03 17:25 | 🚨 남긴 10 USDT 를 **다음 사이클이 전량 청산**하고 있었다 (`ACTION_SKIP` 을 전량으로 처리) |
| **327** | `ded22f3` | 09-03 17:51 | 차트분석 에이전트팀 — 지지선 **7점 판정**을 진입에 배선. **기본 OFF** (`support_score_gate_enabled`) |

🚨 **Fix 315→321, 318→319→321, 311→316→324, 304→305→326 은 「내가 만든 것을 내가 되돌린」 연쇄다.** 새 PC에서 이 영역(부분 손절 / 단계 게이트)을 건드릴 때는 반드시 `tests/test_stage_flow_execution.py`, `tests/test_sajangnim_ladder_numbers.py`, 손절 실행 테스트(Fix 320)를 먼저 돌려라.

---

### 2. 배포 상태 — VPS vs 로컬

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format="%H %ad %s" --date=iso'
```

출력:
```
ded22f3ed23018313410287f387c5002613a6f79 2026-09-03 17:51:09 +0900 feat(Fix 327): 차트분석 전문가 에이전트팀 — 지지선 7점 판정을 진입에 배선
```

| 위치 | 커밋 | 상태 |
|---|---|---|
| VPS `~/binance-auto-trader` (branch `main`) | `ded22f3` | Fix 327 까지 배포 완료 |
| 로컬 워크트리 `claude/infallible-euler-6dc297` | `e51d9a8` | 조사 시점엔 `ded22f3` 로 VPS 와 일치했고, 그 뒤 **핸드오프 문서 커밋 1개**(`e51d9a8`)가 얹혔다. `backend/app/` 실행 경로 차이 **0건** — 재검증 시 `git log -1` 이 `e51d9a8` 로 나와도 정상이다 |
| GitHub `refs/heads/main` | `e51d9a8` | VPS 보다 **1커밋 앞** |
| 로컬 `main` 브랜치 (워크트리 밖) | `2586555` (Fix 292c) | 🚨 **25커밋 뒤처짐** — 새 PC에서 clone 하면 이 문제는 사라진다 |

**VPS 가 1커밋 뒤처진 것은 무해하다** — `e51d9a8` 은 `chore(handoff): 저장소 밖 자산을 저장소 안으로` 이고 diff 102개 파일 전부 `docs/handoff/...` 및 `wip-backup-*` 백업 사본이다. `backend/app/` 실행 경로 변경 **0건**.

직접 확인하는 법 (저장소 루트에서):
```bash
git diff --stat ded22f3 e51d9a8 | tail -1          # → 102 files changed, 13150 insertions(+)
git diff --name-only ded22f3 e51d9a8 | sed -E 's#/.*##' | sort | uniq -c   # → 102 docs  (docs/ 뿐)
git diff --stat ded22f3 e51d9a8 -- backend/app | wc -l                     # → 0  ★ 실행 경로 무변경
```
마지막 줄이 **`0`** 이면 「VPS 가 1커밋 뒤처져도 무해하다」가 증명된 것이다.

#### 🚨 「배포됐나」 판정은 파일 mtime 이 아니라 **프로세스 시작 시각과 대조**해야 한다 (메모리 확정 교훈)

🚨 `docker inspect -f "{{.State.StartedAt}}" A B` 는 **시각만 두 줄** 뱉어서 어느 컨테이너 것인지 알 수 없다.
반드시 `{{.Name}}` 을 같이 넣어라. `date -u` 도 함께 찍어야 「이 시각이 몇 분 전인지」를 스스로 계산할 수 있다.

```bash
ssh root@159.65.137.250 'docker inspect -f "{{.Name}} {{.State.StartedAt}}" binance-auto-trader-api binance-auto-trader-scheduler; date -u; stat -c "%y %n" ~/binance-auto-trader/backend/app/services/execution_service.py'
```

실제 출력 (2026-09-03 재검증, **가공하지 않은 원문**):
```
/binance-auto-trader-api 2026-09-03T08:51:26.932467002Z
/binance-auto-trader-scheduler 2026-09-03T08:51:57.679240765Z
Thu Sep  3 09:38:43 UTC 2026
2026-09-03 08:51:24.932421513 +0000 /root/binance-auto-trader/backend/app/services/execution_service.py
```
파일 수정(08:51:24) → api 시작(08:51:26) → scheduler 시작(08:51:57) 순서이므로 **현재 실행 중인 코드가 `ded22f3` 이다.**
(반대로 파일 mtime 이 시작 시각보다 **뒤**면 = 파일만 바뀌고 재시작이 안 된 것 = **미배포**다.)
컨테이너 안에서도 확인:

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T api grep -c support_score_gate_enabled /app/app/services/execution_service.py'
```
→ `1` (Fix 327 마커 존재)

#### 컨테이너 현황

🚨 `docker compose` 는 `docker-compose.yml` 이 있는 **`~/binance-auto-trader/backend`** 에서만 돈다.
`cd` 를 빼면 `no configuration file provided` 로 실패한다 — 이 문서의 모든 compose 명령에 `cd` 가 붙어 있는 이유다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
```

아래 「상태」는 **조사 시점(09:15 UTC) 스냅샷**이다. 지금 돌리면 숫자가 다르게 나오는 것이 정상이다
— 판정은 상대 시각이 아니라 위의 `StartedAt` 절대 시각으로 하라.

| 컨테이너 | 상태 (조사 시점) |
|---|---|
| `binance-auto-trader-api` | Up 9 minutes (= `08:51:26Z` 시작) |
| `binance-auto-trader-scheduler` | Up 9 minutes (= `08:51:57Z` 시작) |
| `binance-auto-trader-user-stream` | Up 22 hours |
| `binance-auto-trader-mark-price-stream` | Up 8 days |
| `binance-auto-trader-db` | Up 3 weeks — 🚨 **비어 있는 껍데기. 실 DB 는 외부 Neon** |
| `binance-auto-trader-redis` / `prometheus` / `grafana` / `db-backup` | Up 3 weeks |

#### ⚠️ VPS 작업트리에 커밋 안 된 파일 31개

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader && git status --short'
```
31개 전부 `??`(untracked)이고 전부 `backend/*.py` 형태의 **1회용 조사 스크립트**(`analyze_stopped.py`, `flip_v4.py`, `loss24.py` 등)다. 추적 파일 변경은 **0건**이다. 다만 새 PC에서 clone 해도 이 파일들은 오지 않으니 **VPS 에만 있는 일회용 자산**임을 알아둘 것.

> 🚨 **「추적 파일 변경 0건이니 `git pull` 이 안전하다」는 결론으로 넘어가지 마라.** 두 가지가 더 걸린다.
> 1. **untracked 도 pull 을 막는다.** 앞으로 저장소에 `backend/loss24.py` 같은 **같은 이름의 파일이 추가되면** git 이 `error: untracked working tree files would be overwritten by merge` 로 **중단**한다. 그때 `-f`·`checkout .`·`clean -fd` 로 밀어붙이지 마라 — 조사 스크립트가 사라진다. 막히면 **그 파일만 `mv` 로 옮기고** 다시 pull 하라.
> 2. **`git pull` 자체가 배포다** (§0.5 #5, 바인드 마운트). 당겼으면 **반드시 재시작까지 이어져야** 코드가 일관된 상태가 된다 — 「당겨만 놓고 나중에」가 가장 위험하다.
>
> **되돌리는 법 (배포 롤백)** — 🚨 사장님 승인 후에만:
> ```bash
> # 1) 현재 커밋을 먼저 적어 둔다 (이게 없으면 되돌릴 곳을 잃는다)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format=%H'
> # 2) 되돌리기 = 옛 커밋으로 checkout (reset --hard 를 쓰지 마라 — untracked 31개와
> #    추적 파일 상태를 한꺼번에 날릴 위험이 있고, 실수 시 복구 지점이 사라진다)
> ssh root@159.65.137.250 'cd ~/binance-auto-trader && git checkout <되돌릴커밋>'
> # 3) 코드가 바뀌었으므로 재시작해야 반영된다 (재시작은 사장님)
> ```
> ⚠️ 롤백에 **alembic 되돌리기가 포함되면 얘기가 완전히 다르다.** 스키마를 내리면 데이터가 사라질 수 있다. 현재 `0034_surge_ladder`. **downgrade 는 이 문서의 권한 밖이다 — 사장님과 상의.**

---

### 3. 살아있는 전략 (포지션 보유) — **8건**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"\"\"
select si.id, si.symbol, si.side, si.status, st.name, si.current_stage,
       si.current_position_qty, round(si.unrealized_pnl::numeric,2), round(si.realized_pnl::numeric,2),
       si.leverage, si.force_sl_roi_override
from strategy_instances si left join strategy_templates st on st.id=si.strategy_template_id
where si.status not in (\x27STOPPED\x27,\x27COMPLETED\x27,\x27CANCELLED\x27,\x27FAILED\x27,\x27REENTRY_READY\x27)
order by si.id desc\"\"\")).fetchall(): print(r)
"'
```

> ✅ 위 명령은 **그대로 복사해 붙여넣으면 돈다** (2026-09-03 재실행 확인).
> `\x27` 는 작은따옴표(`'`)의 Python 이스케이프다 — 바깥 `'…'` 안에 `'` 를 못 넣기 때문에 쓴 우회이니 **고치지 마라**.
>
> 🚨 아래 표는 **살아 있는 데이터의 스냅샷**이다. 지금 돌리면 id·심볼은 같아도 **미실현 손익은 반드시 다르게 나온다**
> (재검증 시 실제로 `−0.82 → +1.22` 로 바뀌었다). 「숫자가 다르다」로 고장을 의심하지 마라.
> 구조(8건 / 전부 `STAGE1_OPEN` / 전부 레버 2)가 바뀌었는지만 보면 된다.
>
> 🚨 `force_sl_roi_override` 컬럼의 **원값은 양수**다 (`10.00` / `5.00` / `3.64`).
> 아래 표의 `−10%` 는 「ROI 가 −10% 이하면 발동」이라는 **의미로 부호를 붙인 것**이다 — DB 값과 부호가 다르다고 놀라지 마라.

| id | symbol | side | status | 단계 | 템플릿 (=전략 종류) | qty | 미실현 | 실현 | 레버 | 강제손절 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2096 | ARCUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` = 볼밴 중단선 | −2,765 | **−0.82** | −0.01 | 2 | −10% |
| 2093 | BRUSDT | LONG | STAGE1_OPEN | 1 | `_quick_…` = **수동** | 4,312 | **+57.33** | −0.08 | 2 | −3.64% |
| 2090 | MAGMAUSDT | LONG | STAGE1_OPEN | 1 | `_quick_…_inplace_…` = **수동** | 2,473 | **+19.80** | −0.20 | 2 | −5% |
| 2088 | CRDOUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` | −1.19 | −0.12 | −0.03 | 2 | −10% |
| 2034 | PYTHUSDT | SHORT | STAGE1_OPEN | 1 | `BB_MIDLINE_…` | −3,483 | +0.39 | −0.10 | 2 | −10% |
| 2009 | MSTRUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.16 | −0.25 | −0.01 | 2 | −5% |
| 2005 | BMNRUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.86 | −0.19 | −0.01 | 2 | −5% |
| 1988 | TQQQUSDT | SHORT | STAGE1_OPEN | 1 | `AUTO_BB_…` | −0.28 | −0.18 | −0.01 | 2 | −5% |

**합계: 미실현 +75.96 / 실현 −0.45.** 이익의 거의 전부(+77.13)가 **수동 LONG 2건**이다.

전략 종류 판별 (템플릿 접두사 → 생산 워커):

| 접두사 | 생산자 | 근거 |
|---|---|---|
| `BB_MIDLINE_` | 볼밴 중단선 4종 (Fix 278 로 분리된 별도 전략) | `app/workers/bb_mid_line_worker.py:68` `TEMPLATE_PREFIX = "BB_MIDLINE"` |
| `AUTO_BB_` | `_create_auto_bb_strategy` (공용 진입 생성자) | `app/workers/auto_bb_breakdown_worker.py:1861` |
| `auto_bb_break_SAJANGNIM_TOP/BOTTOM` | v219 사다리 | `app/services/stage_entry_timing.py:23` — **현재 활성 0건** |
| `_quick_` / `DYNAMIC_*` | **사장님 수동** | `app/services/chg24_entry_gate.py` (게이트가 일부러 통과시킴) |

🚨 **8건 전부 `current_stage = 1`.** 사장님 3단 사다리(10/300/600)가 **2단계로 올라간 살아있는 전략이 지금 0건**이다. Fix 311/312/316/323/324/326 이 전부 이 문제를 겨냥한 수정이고, 그 효과는 **아직 실전에서 확인되지 않았다**.

#### 전체 상태 분포

| status | 건수 |
|---|---|
| STOPPED | 1,173 |
| COMPLETED | 290 |
| REENTRY_READY | 16 |
| STAGE1_OPEN | **8** |

⚠️ `REENTRY_READY` 16건은 **`created_at` 기준 2026-07-14 ~ 08-28 에 멈춘 좀비**다.
16건 중 **14건이 `_quick_`(수동)**, 2건이 `AUTO_BB_`(#1116 BLESSUSDT / #1272 MELANIAUSDT). 9월 들어 갱신 0건 = 최소 6일 방치. → §7 미해결 ⑦.

전량을 직접 뽑는 명령:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"\"\"
select si.id, si.symbol, si.side, left(coalesce(st.name,\x27\x27),22), si.created_at::date
from strategy_instances si left join strategy_templates st on st.id=si.strategy_template_id
where si.status=\x27REENTRY_READY\x27 order by si.created_at\"\"\")).fetchall(): print(r)
"'
```

---

### 4. 오늘(KST 2026-09-03) 진입 — **진입일 기준** 집계

> 🚨 이 저장소의 확정 교훈: **청산일이 아니라 진입일**로 갈라야 한다.
> `created_at` 은 `timestamptz` 로 UTC 에 정확히 저장돼 있다 (pg TimeZone=GMT). KST 경계는 아래처럼 잡는다.

로컬에 `ops_today.py` 를 만들어 VPS 로 보낸 뒤 컨테이너 안에서 실행한다.
(아래 3 블록을 **위에서부터 차례로** 실행하면 끝난다. §8-3 에도 같은 3단계가 나온다.)

**① 로컬(새 PC)에서 파일 생성** — Git Bash 에서. 만들어지는 위치는 **현재 디렉터리**이니
`cd ~` 등으로 위치를 정해 두고 실행하라:

```bash
cat > ops_today.py <<'PYEOF'
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
SQL = """
select case when st.name like '%quick%' then '수동' else '자동' end as kind,
       case when si.started_at is null then '미진입' else '진입' end as entered,
       count(*) as n,
       round(sum(coalesce(si.realized_pnl,0))::numeric,2) as realized,
       round(sum(coalesce(si.unrealized_pnl,0))::numeric,2) as unrealized
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.created_at >= (date_trunc('day', (now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul')
group by 1,2 order by 1,2
"""
for r in db.execute(text(SQL)).fetchall():
    print(" | ".join(str(v) for v in r))
PYEOF
```

**② VPS 로 보낸다:**
```bash
scp -o StrictHostKeyChecking=no ops_today.py root@159.65.137.250:/root/ops_today.py
```

**③ 컨테이너에 넣고 실행한다** (🚨 `PYTHONPATH=/app` 을 빼면 `ModuleNotFoundError`):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose cp /root/ops_today.py api:/tmp/t.py && docker compose exec -T -e PYTHONPATH=/app api python /tmp/t.py'
```

> 🚨 **이 쿼리는 「2026-09-03」이 아니라 「오늘」을 본다.** `now()` 를 쓰기 때문에, 다른 날 실행하면
> 그날 KST 자정 이후 데이터가 나온다 — 아래 결과표와 숫자가 다른 게 정상이다.
> 특정 날짜를 보려면 `where` 절을 다음으로 바꾼다:
> ```sql
> where si.created_at >= (date '2026-09-03' at time zone 'Asia/Seoul')
>   and si.created_at <  (date '2026-09-04' at time zone 'Asia/Seoul')
> ```
>
> ⚠️ **수동/자동 분류는 `st.name like '%quick%'` 뿐이다.** §3 표에는 수동에 `DYNAMIC_*` 도 적혀 있지만
> 이 SQL 은 `DYNAMIC_*` 을 **자동으로 센다**. 오늘은 `DYNAMIC_*` 템플릿이 0건이라 결과가 같지만,
> 다른 날 재실행할 때는 `like '%quick%' or st.name like 'DYNAMIC%'` 로 바꿔야 §3 과 기준이 맞는다.

핵심 SQL (KST 경계 잡는 부분이 요점이다):

```sql
select case when st.name like '%quick%' then '수동' else '자동' end as kind,
       case when si.started_at is null then '미진입' else '진입' end as entered,
       count(*), round(sum(coalesce(si.realized_pnl,0))::numeric,2)
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.created_at >= (date_trunc('day', (now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul')
group by 1,2;
```

#### 결과

| 구분 | 생성 | 실제 진입 | 미진입 | 실현손익 | 미실현 |
|---|---|---|---|---|---|
| **수동** (`_quick_`) | 18 | 18 | 0 | **+229.30** | +77.13 |
| **자동** | 32 | 14 | **18** | **−36.91** | −0.55 |
| ─ `BB_MIDLINE_*` | 29 | — | — | −29.12 | −0.55 |
| ─ `AUTO_BB_*` | 3 | — | — | −7.79 | 0.00 |

> ✅ 재검증(같은 날 09:38 UTC): 건수 18/14/18 과 실현손익 `+229.30` / `−36.91` 이 **글자 그대로 재현**됐다.
> 다만 미실현은 `+77.13 → +63.88` 로 달라졌다 — **미실현은 시세라서 매번 다르다.** 재현 여부는 **실현손익과 건수**로만 판단하라.

#### 🚨 수동 +229.30 은 「자동보다 잘했다」는 뜻이 아니다

18건 중 **2건이 전부**다:

| id | symbol | side | 실현 |
|---|---|---|---|
| 2032 | AKEUSDT | SHORT | **+280.14** |
| 2094 | BULLAUSDT | LONG | **+138.72** |
| **나머지 16건 합계** | | | **−189.56** |

그리고 메모리에 기록된 **반복 패턴이 오늘도 그대로 재현됐다**:
- `AKEUSDT` 수동 진입이 **하루에 7건** (2032/2035/2036/2038/2039/2040/2041/2046) — 큰 이익(+280.14) 직후 같은 종목 반복.
- 그 7건의 합계는 **+240.02** 이지만, 첫 건(+280.14)을 빼면 **−40.12**.
- 16:43~16:53 **10분 사이에 수동 7건 연속 진입** (2089~2095) → 합계 **+53.36**, 그중 BULLA(+138.72) 빼면 **−85.36**.
- 🚨 메모리 확정: `_quick_` 수동 경로에는 **중복 진입 가드가 없다**.

#### 🚨 자동 32건 중 18건이 「생성만 되고 진입 못함」

전부 `BB_MIDLINE_*` 이고 `started_at IS NULL`, `realized_pnl = 0.00` 이다 (11:07 에 11건, 13:22 에 4건, 13:37 에 3건 등 배치로 생성). 이 워커가 후보를 만들고 **진입 관문에서 걸러진 뒤 STOPPED 로 정리되는 흐름**으로 보이나, 어느 게이트가 걸렀는지는 **⚠️ 확인 못 함** (로그에 전략 id 로 추적 가능한 차단 사유가 남아 있지 않다).

#### 참고 — 일일 리스크 테이블(청산일·UTC 기준)은 숫자가 다르다

```
account_daily_risk_limits: 2026-09-03 → realized −39.92 (status ACTIVE)
```
위 진입일 기준 합계(+192.39)와 다른 것이 **정상**이다. 하나는 청산일·UTC, 하나는 진입일·KST 다. **두 숫자를 섞어 쓰지 말 것.**

---

### 5. 최근 로그의 반복 패턴 상위 (스케줄러, 2026-09-02 23:32 ~ 09-03 09:06 UTC = 약 9.5시간)

> ⚠️ **아래 첫 명령은 「조회」가 아니라 운영 서버에 파일을 쓰는 명령이다.**
> `> /root/sch.log` 는 **매번 약 52 MB** 를 VPS 디스크에 쓰고, 같은 이름이므로 **기존 파일을 말없이 덮어쓴다**.
> 현재 여유는 `48G 중 24G` (실측 `df -h /` → `51% used`)라 한 번은 문제없지만, **습관적으로 매일 돌리면 쌓인다.**
> 파일을 남길 필요가 없으면 **쓰지 말고 파이프로 바로 흘려라** — 이게 진짜 읽기 전용이다:
> ```bash
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --tail 200000 scheduler 2>&1 | grep -E " WARNING " | head -50'
> ```
> 굳이 파일로 받아야 하면 **이름에 날짜를 넣어 덮어쓰기를 피하고**, 다 쓴 뒤 **경로를 눈으로 확인하고** 지운다:
> ```bash
> # 🚨 rm 이다. 경로에 오타가 나면 다른 것이 지워진다. 반드시 ls 로 먼저 확인할 것.
> ssh root@159.65.137.250 'ls -la /root/sch-2026-09-04.log'      # ← 먼저 이걸로 확인
> ssh root@159.65.137.250 'rm -i /root/sch-2026-09-04.log'       # ← 그 다음에만
> ```
> `rm -rf`, 와일드카드(`rm /root/*.log`), `rm` + 변수 조합은 **쓰지 마라.** 실자금이 도는 서버다.

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --tail 200000 scheduler > /root/sch.log; wc -l /root/sch.log'
```
```bash
ssh root@159.65.137.250 'grep -E " WARNING " /root/sch.log | sed -E "s/^.*WARNING //; s/[A-Z0-9]+USDT//g; s/[0-9]+(\.[0-9]+)?/N/g" | cut -c1-95 | sort | uniq -c | sort -rn | head -18'
```

로그 레벨 분포를 세는 명령 (근거):
```bash
ssh root@159.65.137.250 'for L in INFO WARNING ERROR; do printf "%-8s %s\n" "$L" "$(grep -c " $L " /root/sch.log)"; done'
```
→ **INFO 156,904 / WARNING 42,780 / ERROR 6** (합 199,690 ≈ 200,000줄. 재검증에서 **글자 그대로 재현**됐다.)

> 🚨 **「9.5시간」은 `--tail 200000` 이 마침 그만큼을 덮은 결과이지, 고정된 창이 아니다.**
> 로그가 더 빨리 쌓이는 날에는 같은 20만 줄이 **더 짧은 시간**만 덮는다. 시간으로 자르고 싶으면
> `--tail 200000` 대신 `--since 24h` 를 써라 (§8-6).

> 🚨 **아래 「건수」는 정확한 총계가 아니라 위 `sed`+`cut -c1-95` 파이프라인이 만든 버킷 크기다.**
> 심볼 치환 `s/[A-Z0-9]+USDT//g` 가 **소문자·한자 심볼(`龙虾USDT` 등)을 못 지우고**, 남은 길이 차이 때문에
> 같은 메시지가 여러 버킷으로 갈린다. 실제로 1위 메시지의 **진짜 총계는 27,257건**인데 표에는 26,906 으로 잡혔다
> (재실행하면 26,690 처럼 또 달라진다 — `cut -c` 는 로케일에 따라 바이트/문자 기준이 갈린다).
>
> **정확한 건수가 필요하면 메시지 원문을 직접 세라** (로케일·자르기와 무관):
> ```bash
> ssh root@159.65.137.250 'grep -c "소소한 반등 = LONG 아님" /root/sch.log'          # → 27257
> ssh root@159.65.137.250 'grep -c "auto_long_at_bottom_worker" /root/sch.log'      # → 43285
> ```
> 순위표는 **「무엇이 로그를 지배하는가」를 보려는 용도**다. 건수를 근거로 인용하지 마라.

| # | 건수(버킷) | 워커 | 패턴 = 무엇을 막고 있나 |
|---|---|---|---|
| 1 | **26,906** (실제 27,257) | `auto_long_at_bottom_worker` | `🚫 <SYM> 소소한 반등 = LONG 아님 — OBV 회복 부족` |
| 2 | 4,569 | `auto_long_at_bottom_worker` | `SKIP: 지표 꺾임 N/N (아직 …)` |
| 3 | 3,869 | `auto_short_at_top_worker` | `SKIP: 지표 꺾임 N/N` |
| 4 | 2,098 | `realtime_reentry_worker` | `LONG 재진입 차단: 지표 꺾임` |
| 5 | 1,126 | `realtime_reentry_worker` | `완료: scanned=N candidates=N reentered=N` (요약 로그가 WARNING) |
| 6 | 1,111 | `resistance_reversal_worker` | `DONE: {scanned, approached, reversed, entered}` (요약) |
| 7 | 1,043 | `peak_break_reversal_worker` | `DONE: {scanned, processed, entered, errors}` (요약) |
| 8 | **432** | `apscheduler` | 🚨 `Run time of job … was missed by 0:00:01` = **misfire** |
| 9 | 149 | `macd_reversal_15m_worker` | `완료: scanned/detected/skipped` (요약) |
| 10 | **147** | `auto_bb_breakdown_worker` | `🚫 <SYM> SHORT 진입 차단 — 합의 판정 AVOID` (Fix 247 합의 게이트) |

**읽는 법:**
- 1~4위(총 **37,442건**)는 **진입 게이트가 정상적으로 후보를 거르는 소리**다. 고장이 아니다. 다만 `auto_long_at_bottom_worker` 혼자 로그의 **43,285줄(전체의 22%)** 을 쓴다 — 로그 노이즈로 다른 신호를 덮는다.
- 5~7·9위는 **정상 완료 요약인데 WARNING 레벨**로 찍힌다. 🚨 **「WARNING 42,780건」을 보고 놀라지 마라. 진짜 문제는 6건의 ERROR 와 432건의 misfire 다.**
- 10위 = Fix 247 합의 게이트가 9.5시간에 **147건 차단** = 살아서 일하고 있다.
- chg24 진입 게이트 로그는 **`[Fix310]` 76건 / `[Fix325]` 0건**이다 (아래로 재현 가능. 초안의 「125건」은 어떤 grep 으로 센 것인지 근거가 없어 **삭제했다**):
  ```bash
  ssh root@159.65.137.250 'grep -c "Fix310" /root/sch.log; grep -c "Fix325" /root/sch.log'   # → 76 / 0
  ```
  🚨 **`Fix325` 가 0 이라고 「Fix 325 가 안 돈다」로 읽지 마라.** ① Fix 325 는 **17:51 KST 배포분**이라 이 로그 창(≈09:06 UTC 까지)에 **15분밖에 안 들어 있고**, ② `chg24_entry_gate.py:158,174` 의 `[Fix325]` 로그는 **fail-open(조회·산출 실패) 때만** 찍힌다. **0 = 실패 0건**이라는 뜻이다. 정상 차단은 `[Fix310] <SYM> 진입 차단: 24h ±N%` 로 남는다.

#### misfire 분포 (🚨 §7 미해결 ① 의 직접 증거)

```bash
ssh root@159.65.137.250 'grep -oE "trigger: interval\[[0-9:]+\][^)]*\)\" was missed" /root/sch.log | grep -oE "interval\[[0-9:]+\]" | sort | uniq -c | sort -rn'
```
```
174 interval[0:00:30]    146 interval[0:05:00]     33 interval[0:03:00]
 21 interval[0:00:15]     20 interval[0:01:00]     16 interval[0:15:00]
 12 interval[0:30:00]      7 interval[0:02:00]      3 interval[1:00:00]
```
🚨 **`interval[6:00:00]` 이 목록에 아예 없다.** 6시간 잡은 misfire 조차 안 난다 — **한 번도 실행 시각에 도달하지 못했기 때문**이다 (§7 ①).

#### ERROR 6건 = 전부 같은 것 (🚨 새로 발견)

```bash
ssh root@159.65.137.250 'grep -m1 -A14 " ERROR \[apscheduler" /root/sch.log'
```
```
File "/app/app/workers/mainnet_safety_worker.py", line 139, in _check_exchange_accounts
    "name": a.name,
AttributeError: 'ExchangeAccount' object has no attribute 'name'
```
**1시간 주기 잡이 매번 100% 실패**한다 — UTC `02:52 / 03:52 / 04:52 / 05:52 / 06:52 / 07:56` = **6회/9.5h**.
「정각」이 아니라 **`52분`**(= 스케줄러 시작 시각에서 1시간씩 더해진 자리)이므로, 로그에서 찾을 때 정각을 뒤지지 마라.
단서는 ERROR 한 줄에 찍히는 **`trigger: interval[1:00:00]`** 이다. → §7 미해결 ⑤.

---

### 6. 현재 설정 스냅샷 (`system_settings` 63행 전량)

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key, left(value,60) from system_settings order by key\")).fetchall(): print(k, \"=\", v)
"'
```

#### 🚨 실자금에 직접 영향을 주는 스위치 (지금 켜져 있는 것)

| 키 | 값 | 의미 |
|---|---|---|
| `stage_trim_before_next_enabled` | **1 (ON)** | 🚨 단계 전환 시 「10 USDT 만 남기고 청산」 = Fix 304/324/326 이 실제로 돈다 |
| `stage_wait_for_turn_enabled` | **1 (ON)** | Fix 312 — 다음 단계는 꺾임을 기다린다 (SHORT 만) |
| `sajangnim_ladder_stages_enabled` | **1 (ON)** | 🚨 Fix 315. **Fix 321 때 긴급히 0 으로 껐다가 오늘 16:22 KST 에 다시 1 로 켰다** |
| `entry_chg24_gate_enabled` | **1 (ON)** | Fix 310/325 진입 대상 제한 |
| `adaptive_tp_enabled` | **1 (ON)** | 🚨 켜져 있는데 **v219 경로에만 배선돼 있다** → §7 ④ |
| `auto_obv_enabled` | 1 (ON) | OBV 자동 (일 3건 / 건당 400 USDT = 최대 노출 1,200) |
| `confluence_gate_enabled` | true | Fix 247 합의 게이트 (9.5h에 147건 차단) |
| `force_sl_unlock_unreachable_stage` | true | Fix 235 |
| `pump_split_enabled` / `pump_split_capitals` | 1 / `100,200,500` | 볼밴 분할 (일부러 물타기하는 설계 — Fix 313 이 부분손절에서 제외) |
| `sajangnim_capital_ladder` | `10,300,600` | 사장님 3단 사다리 |
| `sajangnim_pyramid_trigger_roi` | **2** | Fix 300 — 사장님 「+2%부터」 |
| `bb_mid_line_mode` | on | 볼밴 중단선 = **현재 활성 전략 4/8건의 출처** |
| `trend_4h_gate_enabled` / `long_surge_gate_enabled` | 1 / 1 | |
| `scheduled_entry_enabled` | 1 | |
| `split_peak_stall_enabled` | 1 | Fix 260 정점-주춤 |
| `force_sl_short_enabled` = `true`<br>`force_sl_long_roi` = **80**<br>`force_sl_short_roi` = **80** | 🚨 | **§7 ③ 을 읽기 전에 이 세 줄을 먼저 보라 — 초안에는 빠져 있었다.** 이건 **전역 백스톱**이고 값이 **ROI −80%** 다(양수로 저장, `ROI <= -80%` 에서 발동).<br>우선순위는 `app/services/risk_service.py:381-390` 이 명시한다 — *「전역 설정(모든 전략 기본) + 전략별 override 우선 (NULL = 전역 상속)」*, `resolve_force_sl(override_…, global_…)`.<br>→ 지금 살아 있는 8건은 **전부 `force_sl_roi_override`(3.64 / 5 / 10)를 갖고 있어 이 80 은 적용되지 않는다.** 즉 §7 ③ 의 「전 경로 −5%」와 **모순이 아니다.**<br>키 정의: `app/core/risk_constants.py:71,73` |
| `sajangnim_max_stage` = `3` / `sajangnim_default_capital` = `50.0` | | 사다리 최대 단계 / 기본 자본 |
| `sajangnim_reentry_daily_limit` = `10` / `sajangnim_reentry_concurrent_slots` = `10` | | Fix 262/263 (재진입 전용 한도·슬롯) |

#### 꺼져 있는 것 / 없는 것

| 키 | 상태 | 의미 |
|---|---|---|
| `support_score_gate_enabled` | **행 자체 없음 = OFF** | 🚨 **Fix 327(오늘 마지막 커밋)이 배포는 됐지만 켜지지 않았다.** 지지선 7점 판정이 진입에 전혀 영향을 주지 않는다 |
| `entry_chg24_gate_mode` | 행 없음 → 코드 기본 **`"rank"`** | `app/services/chg24_entry_gate.py:62` `MODE_DEFAULT = "rank"` → Fix 325 순위 방식이 기본으로 동작 |
| `entry_rank_top_n` / `entry_min_abs_chg24` | 행 없음 → 코드 기본 (50 / 10.0) | |
| `stage_keep_notional_usdt` / `stage_min_trim_ratio` / `stage_max_cumulative_loss_usdt` / `stage_trim_exclude_modes` | 행 없음 → 코드 기본 | 🚨 `stage_max_cumulative_loss_usdt` 미설정 = **누적 손실 무제한** (Fix 306 의 의도된 기본값) |
| `excluded_symbols` | 행 없음 → 코드 기본 목록 적용 | Fix 303 BTC/ETH 11종 제외가 코드 기본으로 작동 |
| `auto_bb_breakdown_enabled` | **0 (OFF)** | v224 통합으로 스케줄러에서도 주석 처리됨 (`scheduler_runner.py:307-318`) |
| `unified_entry_enabled` | **0 (OFF)** | 🚨 v224 「유일한 진입」으로 만들어 놓고 꺼져 있다 |
| `success_pyramiding_enabled` | 0 (OFF) | Fix 213 사고 이후 |
| `support_breakdown_short_enabled` | 0 (OFF) | |
| `surge_ladder_mode` | `shadow` | 실 진입 안 함 |
| `whitelist_enabled` | false | |
| `auto_obv_min_confidence` | 0.95 | 🚨 **가짜 게이트** — 한 번도 비교되지 않는다 (Fix 308 커밋에 명시) |

#### 안전장치 상태

```
account_kill_switches: is_enabled = FALSE
  reason_code   = ZOMBIE:ORPHAN_EXCHANGE_POSITION
  reason_message= 거래소 FLOCKUSDT SHORT 포지션 (amt=-550) 에 매칭 strategy 없음
  triggered_at  = 2026-08-31 01:43:26 UTC
  cleared_at    = 2026-08-31 01:45:26 UTC   ← 2분 만에 해제됨
```
→ **Kill-Switch 는 현재 OFF (정상 거래 중)**. 마지막 발동은 3일 전 좀비 포지션 때문이었다.

```
alembic_version = 0034_surge_ladder
account_daily_risk_limits (2026-09-03, UTC) = realized −39.92 / status ACTIVE
```

✅ **좋은 소식 — 지금은 밀린 마이그레이션이 없다.** 저장소의 최신 리비전 파일이 `alembic/versions/0034_surge_ladder_state.py` 이고 (총 32개), 운영 DB 의 `alembic_version` 도 **`0034_surge_ladder`** 다. **DB 와 코드가 같은 지점에 있다.**
```bash
ls backend/alembic/versions/ | sort | tail -3     # → 0032 / 0033 / 0034_surge_ladder_state.py
```
🚨 **그래서 지금 `alembic upgrade` 를 실행할 이유가 없다.** 새 PC에서 「일단 upgrade 한번 돌려보자」는 **하지 마라** — 로컬에서 돌리면 `DATABASE_URL` 때문에 **운영 DB 를 건드린다**(§0.5 #3).
⚠️ 반대로 **앞으로 `0035` 이후가 추가되면 그때는 배포 순서가 중요해진다** — 코드만 배포하고 마이그레이션을 빠뜨리면 **컬럼 없음 오류로 워커가 죽는다**(이 저장소는 「전 API 500」 사고 전력이 있다). 새 리비전이 생겼을 때의 배포 절차·순서는 **이 문서 범위 밖이다 — `vps-ops.md` 의 배포 절차를 따르고, 실행은 사장님이 한다.**

학습 파이프라인은 살아 있다: `market_observations` 최근 7일 **2,803건**, `trade_learning_records` 최근 7일 **385건**.

---

### 7. 미해결 과제 목록

#### ① 🚨 `chart_patterns` **0건** — 데이터 0 은 **확정(사실)**, 「6시간 잡이 굶어서」는 **유력 가설**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal; from sqlalchemy import text
print(SessionLocal().execute(text(\"select count(*) from chart_patterns\")).scalar())"'
```
→ **`0`**

세 가지가 겹쳐서 확정된다:

1. **잡 등록에 `misfire_grace_time` 이 없다** → APScheduler 기본값 **1초**.
   ```bash
   cd /path/to/binance-auto-trader     # 🚨 저장소 루트. backend/ 안에서 돌리면 경로가 없어 "No such file" 이 난다
   git grep -n "misfire_grace_time" -- backend/app/
   ```
   → 출력 **0줄** (2026-09-03 재검증). `git grep` 이라 `__pycache__` 가 섞이지 않는다. `backend/app/workers/scheduler_runner.py:513-524` 를 보면 `chart_pattern_scan` 은 `IntervalTrigger(hours=6)` + `coalesce=True` 뿐이다.
2. **스케줄러 프로세스가 9.5시간에 14번 새로 시작했다.**
   ```bash
   ssh root@159.65.137.250 'grep -c "Scheduler started" /root/sch.log'
   ```
   → **`14`**. `IntervalTrigger(hours=6)` 는 start_date 가 없으면 **첫 실행이 프로세스 시작 6시간 뒤**로 잡히므로, 프로세스가 6시간을 못 버티면 그 주기 동안은 실행되지 않는다.

   🚨 **여기서 「평균 40분마다 재시작하는 크래시 루프」라고 읽으면 오진이다 — 재검증했다.** 실제 시각 분포:
   ```
   23:32 23:39 00:02 00:17 00:49 00:53 00:57 01:04 01:46 01:52
                    ← 5시간 04분 무중단 →
   06:56 07:57 08:25 08:52   (08:52 UTC = 17:51 KST = Fix 327 배포 시각과 정확히 일치)
   ```
   - **균등하지 않다.** 앞부분에 몰려 있고 **01:52 → 06:56 은 5h04m 연속 가동**이다.
   - 이 시각들은 **오늘 배포한 커밋 시각(Fix 300~327, 하루 20여 개)과 겹친다.** 즉 **배포 때문에 재시작한 것**이지 스스로 죽는 것이 아니다.
   - 도커 관점 확인: `docker inspect` → `RestartCount=4`, `OOMKilled=false`, `ExitCode=0`, 컨테이너 `Created=2026-08-22` (12일 전). **도커가 자동 복구한 흔적은 12일에 4번뿐**이다. 호스트도 `up 114 days`, 메모리 여유 6.2 GB.
   - ⇒ **「영원히 실행되지 않는다」는 과한 표현이다.** 정확히는 **「배포가 잦은 날에는 6시간을 못 채워 건너뛴다」**. 배포 없는 날이 하루 있으면 이론상 실행된다.
3. **로그에 흔적이 0건이다.**
   ```bash
   ssh root@159.65.137.250 'grep -ci "chart_pattern" /root/sch.log; grep -ci "changelog" /root/sch.log'
   ```
   → **`0`** / **`0`** (다른 6시간 잡인 `binance_changelog_monitor`(`scheduler_runner.py:580`)도 마찬가지로 0건).
   misfire 분포에도 `interval[6:00:00]` 이 **없다** — 실행 시각에 도달조차 못 했다는 뜻이다.

**결론(신뢰도 구분):**
- ✅ **사실** — `chart_patterns` 는 **0행**이다. 테이블은 스키마(17컬럼: `pattern_type`, `confidence`, `outcome_price_24h/48h/7d`, `outcome_max_favorable_pct` …)만 존재한다.
- ✅ **사실** — 최근 9.5시간 로그에 `chart_pattern` / `changelog` 흔적이 **0건**이고 `interval[6:00:00]` misfire 도 **0건**이다.
- 🔶 **가설(강함)** — 2026-08-16 에 만든 차트분석 팀(`ChartPatternLearningTeamLead`)이 **한 번도 성공적으로 돈 적이 없다.** 로그 보존 범위가 9.5시간뿐이라 **「지금까지 한 번도」는 관측 범위를 넘는 주장**이다. 이 저장소는 이런 확대 해석으로 여러 번 오진했다.

⚠️ **다만 「6시간 잡이 굶는다」가 `chart_patterns=0` 의 **유일한** 원인이라고 단정하지 마라.** 위 3근거가 보여주는 것은 「9.5시간 로그 안에서 실행 흔적이 없다」까지다. 아직 배제하지 못한 가설:
- 잡이 과거에 돌았지만 **`run_full_scan` 이 아무 행도 쓰지 않았다**(내부 조기 return / 예외를 `guarded_job` 이 삼킴).
- 6시간 잡 자체가 **`chart_patterns` 에 쓰는 경로가 아니다**.
확인 방법은 **재시작 없이** 가능하다 — 6시간 잡의 다음 실행 예정 시각을 직접 물어보면 된다. (읽기 전용)
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -iE "chart_pattern|ChartPattern|changelog" | head -20'
```

🚨 **이 문제를 「고치려고」 스케줄러 코드를 건드리는 것이 이 항목의 진짜 위험이다.**
`scheduler_runner.py` 는 **모든 자동매매 잡이 등록되는 파일**이다. 여기에 `misfire_grace_time` / `start_date` 를 넣는 수정은 배포 = **스케줄러 재시작**을 부르고, 재시작하면 **포지션 8건을 지키는 손절·단계 전환 잡이 잠깐 멈춘다.**
- `chart_patterns` 는 **학습용 데이터**다. 비어 있어도 **실매매는 지금 정상 작동한다**(§5 의 게이트 로그가 증거). **급하지 않다.**
- 고치더라도 **포지션이 0건인 시간**에, **사장님 승인 후**, `tests/` 를 돌린 뒤에 하라.
- 되돌리는 법: 이 변경은 `scheduler_runner.py` 한 파일이므로 `git revert <커밋>` → 재배포 → 재시작이면 원복된다.

#### ② 🚨 신설 스위치를 켤 UI·API 가 없다 — **확정 (사실)**

🚨 **`grep -r` 로 세면 새 PC 와 숫자가 달라진다. 반드시 `git grep` 을 써라.** 이유 두 가지:
> 1. `grep -r` 은 **`__pycache__/*.pyc`(컴파일된 바이트코드)까지 센다.** 예를 들어 `adaptive_tp_enabled` 는
>    `.py` 2개인데 `grep -r` 로는 **4** 로 나온다. **새로 clone 한 PC 에는 `.pyc` 가 없으므로 절반으로 떨어진다.**
> 2. `grep -r` 은 **커밋 안 된 작업 중 파일**까지 센다. 실제로 이 워크트리에는 조사 시점 이후 만들어진
>    커밋 전 파일(`app/api/v1/terminal.py`)이 있어서 `grep -r` 이 `api=2` 를 뱉는다 — **VPS 에 배포된 코드에는 없다.**
>
> `git grep` 은 **추적 중인 파일만** 보므로 새 PC 의 clone 과 결과가 항상 같다.

**저장소 루트**에서 실행한다 (`backend/` 아니다):

```bash
cd /path/to/binance-auto-trader
for k in support_score_gate_enabled entry_chg24_gate_enabled entry_rank_top_n \
  stage_trim_before_next_enabled stage_wait_for_turn_enabled sajangnim_ladder_stages_enabled \
  adaptive_tp_enabled stage_max_cumulative_loss_usdt excluded_symbols; do
  printf "%-38s api=%s ui=%s code=%s\n" "$k" \
    "$(git grep -l "$k" -- backend/app/api/ | wc -l)" \
    "$(git grep -l "$k" -- backend/app/static/ | wc -l)" \
    "$(git grep -l "$k" -- backend/app/services backend/app/workers | wc -l)"; done
```

실제 출력 (2026-09-03 재검증, `.pyc` 없는 **참값**):
```
support_score_gate_enabled             api=0 ui=0 code=2
entry_chg24_gate_enabled               api=0 ui=0 code=1
entry_rank_top_n                       api=0 ui=0 code=1
stage_trim_before_next_enabled         api=0 ui=0 code=3
stage_wait_for_turn_enabled            api=0 ui=0 code=1
sajangnim_ladder_stages_enabled        api=0 ui=0 code=1
adaptive_tp_enabled                    api=0 ui=0 code=2
stage_max_cumulative_loss_usdt         api=0 ui=0 code=1
excluded_symbols                       api=0 ui=0 code=1
```

<details><summary>참고 — 조사 때 쓴 원래 명령 (`.pyc` 포함이라 code 값이 부풀려져 있다)</summary>

```bash
cd backend && for k in support_score_gate_enabled entry_chg24_gate_enabled entry_rank_top_n \
  stage_trim_before_next_enabled stage_wait_for_turn_enabled sajangnim_ladder_stages_enabled \
  adaptive_tp_enabled stage_max_cumulative_loss_usdt excluded_symbols; do
  printf "%-38s api=%s ui=%s code=%s\n" "$k" \
    "$(grep -rl "$k" app/api/ 2>/dev/null | wc -l)" \
    "$(grep -rl "$k" app/static/ 2>/dev/null | wc -l)" \
    "$(grep -rl "$k" app/services app/workers 2>/dev/null | wc -l)"; done
```

그때의 출력 (조사 시점, `.pyc` 가 섞여 code 가 1씩 큼):
```
support_score_gate_enabled             api=0 ui=0 code=3
entry_chg24_gate_enabled               api=0 ui=0 code=2
entry_rank_top_n                       api=0 ui=0 code=2
stage_trim_before_next_enabled         api=0 ui=0 code=4
stage_wait_for_turn_enabled            api=0 ui=0 code=2
sajangnim_ladder_stages_enabled        api=0 ui=0 code=2
adaptive_tp_enabled                    api=0 ui=0 code=4
stage_max_cumulative_loss_usdt         api=0 ui=0 code=2
excluded_symbols                       api=0 ui=0 code=2
```
</details>

**9개 전부 `api=0 ui=0`.** 이 스위치들을 켜고 끄는 방법은 **`system_settings` 직접 쓰기**뿐이다.

> ⚠️ **`git grep` 대신 옛 `grep -rl` 을 쓰면 5개 키가 `api=2` 로 보인다** — 위 `git grep` 판을 쓰면 나지 않는 현상이다:
> ```
> support_score_gate_enabled  api=2   entry_chg24_gate_enabled  api=2   entry_rank_top_n  api=2
> stage_trim_before_next_enabled api=2   excluded_symbols  api=2
> ```
> **결론은 바뀌지 않는다.** 그 2건의 정체를 실제로 열어 보면:
> 1. `app/api/v1/terminal.py:954-955` — **docstring 안에 키 이름이 나열된 것뿐**이다. 그 엔드포인트(`GET /api/v1/terminal/symbol-status`)는 **명시적으로 읽기 전용**이고 docstring 자체가 *"진입 게이트 설정은 전부 `SystemSetting` 에만 있고 어떤 라우터·JS 로도 노출된 적이 없다"* 라고 적고 있다.
>    🚨 그리고 이 파일은 조사 시점 기준 **아직 커밋되지 않은 작업 중 파일**이라 **VPS 에도, 새 PC 의 clone 에도 존재하지 않는다** (`git grep` 이 0 을 내는 이유). 즉 **운영 코드에는 이 5건조차 없다.**
> 2. `app/api/v1/__pycache__/terminal.cpython-314.pyc` — **컴파일 캐시(바이너리)**. 소스가 아니다.
>
> 🚨 **이게 교훈이다: `grep -rl` 의 숫자만 보고 「API 가 있다」고 믿지 마라.** `__pycache__` 와 주석/문서열이 섞여 든다. 재현하려면 이렇게 좁혀라:
> ```bash
> cd backend && grep -rn "$k" app/api/ --include=*.py | grep -v __pycache__
> ```
> **「쓰는 엔드포인트가 있는가」는 라우트 데코레이터로 확인해야 한다** (`@router.post` / `@router.patch` 와 같은 줄에 그 키가 다뤄지는지).

🚨 **이것이 실무에서 왜 위험한가:** 오늘 Fix 321 때 `sajangnim_ladder_stages_enabled` 를 긴급히 0 으로 내렸다가 다시 1 로 올렸다. 즉 **이 스위치들의 사고 대응 경로가 「DB 에 손으로 upsert」 하나뿐**이다.

✅ **그렇다고 「멈출 방법이 아예 없다」는 뜻은 아니다 — 이 오해가 더 위험하다.**
급할 때는 **스위치를 하나씩 끄는 것보다 §0.5 의 두 경로가 먼저**다:
1. **Kill-Switch API** — `POST /api/v1/admin/kill-switch/{exchange_account_id}/enable` (`app/api/v1/admin/operations.py:257`). 토큰만 있으면 **DB 접속 없이** 계정 단위로 멈춘다. (한계는 §0.5 참조 — 증거금 주입은 계속되고, 해제 시 알람이 몰려 나간다.)
2. **`docker compose stop scheduler`** — 사장님 승인 후. 자동 손절까지 멈추므로 **멈춘 뒤 화면으로 지켜봐야 한다.**

> 🚨 **그렇다고 새 PC 의 로컬 `backend/.env` 에 운영 `DATABASE_URL` 을 채우지 마라.**
> 위 문장을 「그러니 새 PC에서 DB 에 직접 붙을 수 있게 해두자」로 읽으면 **정확히 반대의 사고**가 난다.
> `secrets.md` §0-2 실측: 사무실 PC 의 `.env` 는 이미 운영 Neon 을 가리키고 있고(비밀번호만 만료), `ENCRYPTION_KEY` 지문이 VPS 와 **완전히 같다.**
> → 로컬 `.env` 의 `DATABASE_URL` 만 최신값으로 채우는 순간 **mainnet API 키가 그대로 복호화되어, VPS 와 똑같은 실계좌로 매매하는 엔진이 하나 더 뜬다.**
> **위험 스위치를 끄는 정상 경로는 VPS 안에서다** — `ssh` → `docker compose exec -T -e PYTHONPATH=/app api python …` (§8 과 같은 형태, **쓰기는 사장님 승인 후**).
> 즉 새 PC가 확보해야 하는 것은 **DB 접속 문자열이 아니라 SSH 접속**이다 (§8 상단 🔑).

⚠️ 실제 값 변경은 쓰기이므로 이 조사에서는 하지 않았다. 필요할 때의 형태만 기록해 둔다 — **실행 전 반드시 사장님 승인**:
```
system_settings (key TEXT PK, value TEXT) 에 upsert 하는 방식.
현재 63행. 없는 키는 코드 기본값이 쓰인다.
```

🚨 **스위치를 바꾸기 전에 반드시 지킬 3가지 (안 지키면 되돌릴 수 없다):**

1. **바꾸기 전 값을 먼저 적어라.** 「행이 없었다」와 「값이 0이었다」는 **다르다**. 행이 없으면 코드 기본값이 쓰이고, `0` 을 넣으면 명시적 OFF 다. 이 저장소는 **「모름」을 「꺼짐」으로 표시한 fail-OFF 사고**(2026-08-28)와 **`0` 을 넣었더니 20 으로 둔갑한 사고**(Fix 107~110)를 둘 다 겪었다.
   ```bash
   # 되돌릴 지점 확보 — 읽기 전용
   ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
   from app.core.database import SessionLocal
   from sqlalchemy import text
   db = SessionLocal()
   r = db.execute(text(\"select key, value from system_settings where key = :k\"), {\"k\": \"바꿀키\"}).fetchall()
   print(r if r else \"행 없음 (= 코드 기본값 사용 중)\")
   "'
   ```
   출력을 **그대로 메모**해 둔다. 「행 없음」이었다면 되돌리기는 **값을 0 으로 넣는 것이 아니라 그 행을 지우는 것**이다.
2. **한 번에 하나만 바꿔라.** 오늘 하루에 Fix 315→321, 318→319, 304→326 연쇄 사고가 났다. 두 개를 동시에 바꾸면 **어느 쪽이 원인인지 영원히 모른다.**
3. **바꾼 뒤 「반영됐는지」를 로그로 확인하라.** 확인한 범위에서는 `system_settings` 를 **호출할 때마다 DB 에서 읽는다** (`app/services/system_settings_service.py` 에 캐시·`lru_cache` 없음, `chg24_entry_gate.py:100~117` 도 매 호출 조회). 즉 **다음 잡 주기에 자연히 반영되고, 스위치 하나 바꾸자고 컨테이너를 재시작할 이유가 없다.**
   ⚠️ 단 **전 설정 키를 다 확인한 것은 아니다.** 모듈 로드 시각에 상수로 읽는 키가 섞여 있을 수 있다 — 바꾼 뒤 **로그에 실제로 새 값이 나타나는지**를 보고 판단하라. 「재시작해야 반영되나?」를 추측으로 결론내지 말 것.

#### ③ 🚨 LONG 손절이 전 경로 −5% 인데 사장님 지시 문서는 −10% — **코드 사실은 확정, 「고쳐야 한다」는 결론은 아니다**

**저장소 루트**에서 (`backend/` 아니다):
```bash
cd /path/to/binance-auto-trader
git grep -n "force_sl_roi_override *=" -- backend/app/ | grep -v "=="
```
→ 18줄. 그중 아래 6개 경로가 **신규 전략에 −5% 를 박는 자리**다
(나머지는 `= None`(해제) · 화면 API · surge_ladder · `pump_split`(설정값 사용) · 주석).

| 경로 | 파일:줄 | 값 |
|---|---|---|
| 기본 방식 (화면 생성) | `app/services/strategy_service.py:578` | `force_sl_roi_override=D("5")` |
| auto_bb 공용 생성자 | `app/workers/auto_bb_breakdown_worker.py:1353`, `:1981` | `Decimal("5")` |
| LONG 저점 워커 | `app/workers/auto_long_at_bottom_worker.py:164` | `LONG_FORCE_SL_ROI = Decimal("5")` (`:1519`, `:1829` 에서 사용) |
| SHORT 고점 워커 | `app/workers/auto_short_at_top_worker.py:291` | `Decimal("5")` |
| 반전 워커 2종 | `peak_break_reversal_worker.py:455`, `resistance_reversal_worker.py:351` | `Decimal("5")` |

**LONG/SHORT 구분이 코드 어디에도 없다. 전부 −5%.**

정책 근거 (사장님 지시):
- `docs/spec/SAJANGNIM_3STEP_LADDER_2026-09-02.md:71` — `반대로 간다 → SHORT −5% / LONG −10% 손절`
- 같은 문서 `:88` — `손절은 −10%(SHORT 보다 넓게) — 변동이 크기 때문이다`
- 같은 문서 `:123` — `**4** | **LONG 손절이 −5%** | auto_bb 가 LONG 도 Decimal("5") | 사장님은 **−10%**. LONG 은 변동이 커서 −5% 면 노이즈에 잘린다.`
- 같은 문서 `:137` — `**③ LONG 손절을 −10% 로** — 사장님 명시 지시이고, LONG 승률 20%의 원인일 수 있다.`

🚨🚨 **여기서 「그럼 −10% 로 바꾸면 되겠네」로 가면 실제로 손실이 커진다. 반드시 아래를 먼저 읽어라.**

**「아직 안 한 것」이 아니다 — 한 번 했다가 실측으로 되돌린 것이다.**
`app/workers/auto_long_at_bottom_worker.py:141-164` 에 그 경위가 통째로 주석으로 남아 있다 (커밋 `b7d6694`, **Fix 253, 2026-09-01**):

| 시각 | 무슨 일 |
|---|---|
| 2026-08-24 | Fix 49 — 사장님 verbatim 「단계별 진입후 −5% 손실이면 청산하고 대기」 |
| 2026-08-25 | Fix 87 — **LONG 만 10% 로 상향.** 근거 = 「레버 2× + 15m 알트 노이즈 = 자연 노이즈 손절」 |
| **2026-09-01** | **Fix 253 — 실측이 그 근거를 반증해서 10% → 5% 로 복귀** |

Fix 253 이 제시한 실측(주석에 그대로 있다):
- LONG 이 **이틀 연속 승자 0명** (08-31 12건 0% / 09-01 11건 0%).
- 손절은 설정대로 정확히 작동했다(초과 중앙값 0.2%p). ⇒ **느슨한 손절이 승률을 올린 게 아니라 잃는 크기만 2배로 키웠다.**
- 「노이즈에 잘린다」도 사실이 아니었다 — 당시 **이익 중이던 LONG 13건의 최저 ROI 가 −0.1 ~ −4.3%**, 즉 **−5% 를 건드린 승자가 한 건도 없었다.**
- 추정 효과: 09-01 LONG **−143 → 약 −72**.

**즉 §7 ③ 의 「사장님 지시 −10%」와 코드의 −5% 는 「미이행」이 아니라 「정면 충돌」이다:**
- 사장님 지시 문서 `SAJANGNIM_3STEP_LADDER_2026-09-02.md` 는 **09-02**,
- 이를 되돌린 코드 결정 Fix 253 은 **09-01** — **지시가 하루 더 최신**이다.
- 그러나 그 지시의 근거(「LONG 은 −5% 면 노이즈에 잘린다」)는 **Fix 253 이 숫자로 반증한 바로 그 문장**이다.

🚨 **그러므로 새 PC에서 할 일은 「−10% 로 고치기」가 아니라 「사장님께 이 충돌을 그대로 보여드리기」다.**
숫자 없이 −10% 로 바꾸면 **패자 손실이 다시 2배**가 된다 — 이 시스템은 이미 그 경로를 한 번 갔다 왔다.
바꾸기로 결정된다면 **바꾸기 전에** 주석이 지정한 재측정을 먼저 하라:

> ⚠️ (`auto_long_at_bottom_worker.py:162-163` 원문) *되돌리려면 이 값만 10 으로 바꾸면 된다. 바꿀 때는 위 실측을 다시 재고 **「이익 중인 LONG 이 −5% 아래로 간 적이 있는가」**를 확인할 것.*

⚠️ 또한 이 값은 **한 곳이 아니다** — 위 표의 **6개 파일**을 모두 바꿔야 일관된다. 하나만 바꾸면 **경로마다 손절이 다른** 상태가 되고, 그게 이 저장소가 반복해서 당한 사고 유형이다. 되돌리는 법은 `git revert` 로 한 커밋에 묶어 두는 것 — **6곳을 한 커밋에** 담아라.

(예외적으로 `pump_split_sl_roi = 10` 은 볼밴 분할 전용으로 설정에 존재한다.)

#### ④ 🚨 적응 TP 가 v219 경로에만 배선 — **확정 (사실), 게다가 스위치는 켜져 있다**

**저장소 루트**에서 (`git grep` 이라 `__pycache__` 가 안 섞인다):
```bash
cd /path/to/binance-auto-trader
git grep -n "from app.services.adaptive_tp\|adaptive_tp import" -- backend/app/
```
실제 출력 — **단 한 줄** (2026-09-03 재검증):
```
backend/app/workers/auto_bb_breakdown_worker.py:1827:        from app.services.adaptive_tp import (
```

- `app/services/adaptive_tp.py` 는 존재하고 `adaptive_tp_enabled` / `pick_tp1` / `tp_ladder_from_tp1` 을 export 한다 (`__all__` = `:74-77`, 기본값 `SURGE_CHG_DEFAULT=15.0` / `TP_SURGE_DEFAULT=15.0` / `TP_CALM_DEFAULT=3.0` = `:85-87`).
- **호출처가 `auto_bb_breakdown_worker` 하나뿐**이다. `strategy_service`(기본 방식 생성 경로)와 `stage_entry_signal`(OBV 자동 판정 경로)에는 **import 조차 없다.**
- 🚨 그런데 `system_settings.adaptive_tp_enabled = **1**` 이다.
  → **사장님은 「급등락 15% / 안정 3~5%」 가 전체에 적용된 줄 알고 계실 가능성이 높다.** 기본 방식과 OBV 자동은 여전히 `TP1_PCT_DEFAULT`(15) 고정을 쓴다 (`strategy_service.py:576` `tp1_pct_override=TP1_PCT_DEFAULT,  # v147: 15% (사장님 지시)`).

Fix 299 커밋 메시지의 실측 근거: 구간별 기대값에서 TP15 가 최선인 건 `|24h| 15~30%` 하나뿐(+0.51)이고 나머지 구간은 −0.94 ~ **−4.30** 이었다. 즉 **배선이 빠진 두 경로가 실측상 가장 손해 보는 구간을 그대로 쓰고 있다.**

#### ⑤ 🚨 (신규 발견) `mainnet_safety_worker` 가 매시간 100% 크래시

```bash
ssh root@159.65.137.250 'grep -c " ERROR \[apscheduler" /root/sch.log'   # → 6
```
```
File "/app/app/workers/mainnet_safety_worker.py", line 139, in _check_exchange_accounts
    "name": a.name,
AttributeError: 'ExchangeAccount' object has no attribute 'name'
```

🚨 위 `grep -c " ERROR \[apscheduler"` 는 §5 에서 만든 **`/root/sch.log` 가 있어야** 돈다.
그 파일을 만들지 않았다면 로그를 바로 흘려 보면 된다 (파일을 쓰지 않는 편이 안전하다):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -c " ERROR \[apscheduler"'
```

코드 확인 — **저장소 루트**에서 (2026-09-03 재검증, 두 명령 모두 그대로 돈다):
```bash
cd /path/to/binance-auto-trader
sed -n '130,142p' backend/app/workers/mainnet_safety_worker.py
sed -n '1,30p'   backend/app/models/exchange_account.py
```
`sed` 출력의 139번째 줄이 문제의 `"name": a.name,` 이다.
`ExchangeAccount` 모델의 컬럼은 `id / user_id / exchange_name / market_type / api_key_enc / api_secret_enc / passphrase_enc / hedge_mode_enabled / is_testnet / is_active / daily_loss_limit_usdt / created_at / updated_at` — **`name` 이 없다.** (`app/models/exchange_account.py:9-26`)

**영향: 「mainnet 인지 testnet 인지」를 매시간 확인하는 안전 점검이 9.5시간 동안 6번 전부 실패했다.** 실자금 계정에서 이 점검이 죽어 있는 것은 가볍지 않다. 고치는 것 자체는 `a.name` → `a.exchange_name` 한 줄로 보이지만, **이 조사에서는 코드를 수정하지 않았다.**

> 🚨 **「한 줄이니까 새 PC 첫날에 후딱 고치자」가 이 항목의 함정이다.**
> - 이 저장소는 **오늘 하루에만** 「한 줄 수정」이 엉뚱한 함수에 붙어 사고가 난 사례를 겪었다 (Fix 318 → 319: 손절 수정이 **다른 함수**에 붙어 있었다).
> - 게다가 **코드 수정 = 배포 = 컨테이너 재시작**이다. 재시작하면 **포지션 8건을 지키는 손절·단계 전환 잡이 그 사이 멈춘다.** 「안전 점검을 고치려다 실제 안전장치를 잠깐 끄는」 거래가 된다.
> - ✅ **먼저 확인할 것**: 이 크래시는 **`_check_exchange_accounts` 한 함수**만 죽이는가, 아니면 **`mainnet_safety_worker` 전체**가 죽는가? 후자면 다른 안전 점검도 같이 죽어 있다는 뜻이라 우선순위가 완전히 달라진다. 스택트레이스 전체를 먼저 읽어라 (읽기 전용):
>   ```bash
>   ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -B5 -A25 "has no attribute .name." | head -60'
>   ```
> - 고칠 때: **한 커밋 · 한 파일**, `git revert` 로 되돌릴 수 있게. **포지션이 적은 시간**에, **사장님 승인 후**.
> - ⚠️ **이 워커가 「testnet 인 줄 알았는데 mainnet」을 잡는 장치라면, 고친 직후 처음 도는 순간 경보가 무더기로 나올 수 있다.** 고친 뒤 첫 1시간은 알림을 지켜볼 것.

> 🚨 **위 컬럼 목록에 나오는 `api_key_enc` / `api_secret_enc` / `passphrase_enc` 를 읽을 때 반드시 알아야 할 것**
> 이 컬럼들은 **평문이 아니라 Fernet 대칭키로 암호화된 값**이고, 그 키는 `.env` 의 **`ENCRYPTION_KEY` 단 하나**다
> (`backend/app/core/crypto.py:33-45` — `Fernet(settings.encryption_key)`).
> **`ENCRYPTION_KEY` 를 잃거나 새 PC에서 새로 생성하면 `api_key_enc` 는 수학적으로 복구 불가능**하다.
> 백도어도 복구 절차도 없고, **바이낸스에서 API 키를 새로 발급받는 것 말고는 방법이 없다.**
> → 새 PC 이전 절차·회전 절차·검증 방법은 **`secrets.md` §3 「`ENCRYPTION_KEY` — 이전에서 가장 위험한 지점」** 을 반드시 먼저 읽을 것.
> (이 문서에는 비밀 **값**이 한 개도 들어 있지 않다. 키 **이름**과 「어디서 얻는가」만 적혀 있다.)

#### ⑥ 🚨 (신규 발견) Fix 327 이 배포됐는데 꺼져 있다

`support_score_gate_enabled` 가 `system_settings` 에 **행 자체가 없다** = 기본 OFF (커밋 메시지 명시: `기본 OFF(support_score_gate_enabled). fail-open.`).
→ 오늘 마지막 커밋인 지지선 7점 판정(승률 LONG 70.6% / SHORT 63.9% 실측)이 **진입에 전혀 관여하지 않고 있다.** 켜려면 §7 ② 때문에 **DB 직접 쓰기밖에 없다.**

> ⚠️ **다만 「배포됐는데 꺼져 있다 = 실수다」로 읽지 마라.** 커밋 메시지가 **`기본 OFF(support_score_gate_enabled). fail-open.`** 이라고 **의도적으로** 적고 있다. 이 저장소의 관행은 **새 게이트를 OFF 로 배포하고 관찰 후 켜는 것**이다(Fix 247 합의 게이트도 같은 방식이었고, 사장님이 직접 켰다).
> 🚨 **켤 때의 위험**: 이 게이트는 **진입을 막는 쪽**으로 작동한다. 켜는 순간 **자동 진입이 급감하거나 0이 될 수 있다** — 「자동매매가 멈췄다」로 보이지만 실제로는 게이트가 일하는 것이다. 그 구분이 안 되면 또 한 번 오진한다.
> ✅ 켜기 전에 **차단 로그가 남는지** 먼저 확인하고(§5 의 Fix 247 게이트처럼 「N건 차단」이 보여야 한다), 켠 뒤 **진입 건수 변화를 §4 방식으로 비교**하라. 되돌리기는 **값을 `0` 으로** 또는 **그 행을 지우는 것**(원래 행이 없었다 — §7 ② 의 1번 참조).

#### ⑦ ⚠️ (신규 발견) `REENTRY_READY` 16건이 최대 50일 방치

재검증 실제 출력 (`created_at` 오름차순, 일부):
```
(465,  'ALLOUSDT',   'LONG',  '_quick_20260714203844',  2026-07-14)   ← 가장 오래됨
(1116, 'BLESSUSDT',  'LONG',  'AUTO_BB_BLESSUSDT_LONG', 2026-08-22)
(1272, 'MELANIAUSDT','LONG',  'AUTO_BB_MELANIAUSDT_LO', 2026-08-24)
(1662, '龙虾USDT',    'SHORT', '_quick_20260828233727',  2026-08-28)   ← 가장 최근
```
16건 중 **14건이 `_quick_`(수동), 2건이 `AUTO_BB_`**(#1116 / #1272)다.
가장 오래된 것이 **2026-07-14**(= 조사일 기준 51일), 가장 최근이 **08-28**. 9월 들어 하나도 갱신되지 않았다.
(전량을 뽑는 명령은 §3 「전체 상태 분포」 끝에 있다.)
> ⚠️ 앞선 초안에 `13건 / 07-15` 로 적혀 있었으나 **재실행 결과 `14건 / 07-14` 가 맞다.** 위 숫자를 쓰라.
⚠️ **이게 「재진입 워커가 이것들을 후보로 안 본다」는 뜻인지, 「정상적으로 대기 중」인지는 확인 못 함.** 메모리 확정 사항(재진입 워커는 `TERMINAL_STATUSES` 에서만 후보를 고른다 / Fix 296 이 화이트리스트에서 `_quick_` 를 어떻게 다루는지)과 대조해 볼 것.

#### ⑧ ⚠️ (신규 발견) 사다리가 2단계로 올라간 실전 사례가 아직 0건

현재 활성 8건 **전부 `current_stage = 1`**. Fix 304~326 이 전부 「단계 전환 시 부분 손절 → 다음 단계」를 겨냥했는데, **그 흐름이 끝까지 성공한 것을 실서버에서 아직 못 봤다.** 오늘 Fix 326 은 실서버 로그에서 「부분 손절 → 12~17초 뒤 전량 청산」 사고 3건(#2091 / #2095 / #2089)을 잡아서 고친 것이고, 그 수정의 효과 확인은 **다음 단계 전환이 일어나야** 가능하다.
→ 🚨 **새 PC에서 제일 먼저 볼 것: `current_stage >= 2` 인 전략이 생기는지.**

```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
q = \"select current_stage, count(*) from strategy_instances where status like :p group by 1 order by 1\"
print(db.execute(text(q), {\"p\": \"STAGE%\"}).fetchall())
"'
```

#### ⑨ ⚠️ `unified_entry_enabled = 0` — 「유일한 진입」으로 만든 통합 경로가 꺼져 있다

`backend/app/workers/scheduler_runner.py:501-511` 에 `unified_15m_entry` 가 **30초 주기**로 등록돼 있고 주석은 `SystemSetting "unified_entry_enabled" = 1 시만 실 진입!` 인데 설정값은 **0**. 같은 v224 통합으로 `auto_bb_breakdown` 잡은 **주석 처리**됐다 (`scheduler_runner.py:307-318`).
⚠️ 이것이 의도된 상태(다른 워커들이 실제 진입을 담당)인지, 방치된 것인지는 **확인 못 함.** 실제로 진입을 만드는 건 `bb_mid_line_worker`(BB_MIDLINE)와 `auto_short_at_top_worker` / `auto_long_at_bottom_worker`(AUTO_BB) 다.

> 🚨🚨 **「꺼져 있으니 켜 보자」가 이 항목의 사고다. `unified_entry_enabled = 1` 은 절대 가볍게 켜지 마라.**
> - 이 스위치는 **진입 소스를 하나 더 여는 것**이다. v224 설계에서는 `unified_15m_entry` 가 **다른 워커들을 대체**하기로 되어 있었지만, **대체될 워커들은 지금 살아서 실제로 진입을 만들고 있다**(오늘 자동 32건 전부 `BB_MIDLINE_*` / `AUTO_BB_*` — §4).
> - 즉 지금 켜면 **대체가 아니라 추가**가 된다 → 같은 시장에 **두 진입 엔진**이 동시에 후보를 만든다. 동시 보유 상한·일일 한도가 순식간에 소진되고, 같은 심볼에 겹쳐 들어갈 수 있다.
> - 게다가 **30초 주기**로 등록돼 있다(`scheduler_runner.py:502-510`). 잘못 켜면 **되돌리기 전에 이미 여러 건이 들어가 있다.**
> - ✅ 켜야 한다면: **먼저 `bb_mid_line_worker` / `auto_*_worker` 를 끄는 계획**을 세우고, **사장님 승인**을 받고, **포지션이 적은 시간**에, **켠 직후 1시간을 지켜볼 수 있을 때** 켜라. 되돌리는 법(= 값을 다시 `0` 으로)을 **켜기 전에 손에 쥐고** 시작하라.

#### ⑩ ⚠️ Fix 307 커밋을 못 찾았다

Fix 306(`33b88df`)과 Fix 308(`f8a052b`) 사이에 Fix 307 이 없다.

재검증 — **커밋 본문과 코드·문서 전체를 뒤져도 흔적이 0건**이다:
```bash
cd /path/to/binance-auto-trader
git log --format='%h %s%n%b' 8010e6f~1..HEAD | grep -n "Fix 307"   # → 0줄
git grep -n "Fix 307\|Fix307" -- backend/ docs/                    # → 0줄
```
⇒ **「어딘가에 흡수됐다」기보다 번호를 건너뛴 쪽에 가깝다.** 다만 「왜 건너뛰었는지」는 여전히 **확인 못 함**이고,
**실행 코드에 미치는 영향은 없다**(어떤 파일도 Fix 307 을 참조하지 않는다). 이 항목은 안심하고 넘어가도 된다.

---

### 8. 새 PC 첫날 점검 순서 (복사해서 그대로 실행)

> 🔑 **전제 — 이 절의 모든 명령은 VPS SSH 접속이 되어야 돈다.** 새 PC에는 아직 접속 수단이 없다.
> 현재 사무실 PC 는 `~/.ssh/id_ed25519` (개인키) / `id_ed25519.pub` (공개키) 로 `root@159.65.137.250` 에 붙는다.
>
> 🚨 **권장: 개인키를 옮기지 마라. 새 PC에서 새로 만들어라.** 개인키는 옮기는 순간 「어딘가에 복사본이 하나 더 생기는」 자산이고, 옮기는 경로(메일·메신저·클라우드 드라이브·채팅)가 전부 사고 지점이다.
> ```bash
> # 새 PC 에서 (개인키는 이 PC 밖으로 절대 안 나간다)
> ssh-keygen -t ed25519 -C "새PC" -f ~/.ssh/id_ed25519
> cat ~/.ssh/id_ed25519.pub          # ← .pub (공개키) 는 공개해도 안전하다
> ```
> 그 다음 **사장님이 기존 접속되는 PC 에서** VPS `~/.ssh/authorized_keys` 에 위 `.pub` 한 줄을 추가한다(= VPS 쓰기이므로 **사장님이 직접**).
> 이렇게 하면 옛 PC 를 잃어버렸을 때 그 줄만 지우면 되고, 개인키가 전송된 적이 아예 없다.
>
> ⚠️ 개인키(`id_ed25519`)를 꼭 옮겨야 한다면 **채팅·이메일·이슈·스크린샷은 금지.** 물리 매체나 비밀번호 관리자로 옮기고, 새 PC에서 권한을 `chmod 600 ~/.ssh/id_ed25519` 로 조인다. 자세한 원칙은 `secrets.md`.
> (이 문서에는 개인키 내용도, 어떤 비밀 **값**도 들어 있지 않다.)

> ⚠️ **`-o StrictHostKeyChecking=no` 를 습관으로 만들지 마라.** 이 옵션은 **처음 보는 서버 키를 묻지 않고 그대로 받아들인다** — 새 PC 첫 접속에서 편하려고 쓰는 것이지, **안전해서 쓰는 것이 아니다.**
> 이 저장소가 다루는 것은 **실계좌를 조작할 수 있는 서버**다. 첫 접속 때 **한 번만** 지문을 눈으로 확인하고 등록해 두면, 그 뒤로는 이 옵션 없이 쓰는 것이 맞다.
> ```bash
> # 처음 한 번: 지문을 확인하고 등록 (사장님이 알고 있는 값과 대조)
> ssh-keyscan -t ed25519 159.65.137.250 | ssh-keygen -lf -
> ssh root@159.65.137.250 'echo ok'      # ← 이후로는 옵션 없이
> ```
> 이 절의 명령들에 붙은 `-o StrictHostKeyChecking=no` 는 **첫 1회용**으로 읽어라.

> ✅ **아래 1)~6) 은 전부 읽기 전용이다** — 주문을 내지 않고, 설정을 바꾸지 않고, DB 에 쓰지 않는다.
> 단 **3) 만 예외적으로 파일을 쓴다**(로컬 heredoc + `scp` + `docker compose cp`). 그 주의사항은 3) 안에 적어 두었다.

**0) 저장소를 새 PC에 가져온다** — §1 · §2 · §7 ②③ 의 `git log` / `git grep` 명령은 **로컬 clone 이 있어야** 돈다.
```bash
cd ~                                   # 원하는 상위 폴더
git clone https://github.com/herosys1-crypto/binance-auto-trader.git
cd binance-auto-trader
git log -1 --format='%h %s'            # → e51d9a8 chore(handoff): …  (= GitHub main)
```
🚨 **clone 만 한다. `pip install` 도 `docker compose up` 도 하지 마라** — §0.5 #1 참조.
이 절의 모든 조회는 **VPS 컨테이너 안**에서 돌고, 로컬은 **코드를 읽기 위해서만** 필요하다.
이후 문서에 나오는 `cd /path/to/binance-auto-trader` 는 여기서 clone 한 경로를 말한다.

> ⚠️ **VPS(`ded22f3`)와 GitHub main(`e51d9a8`)은 1커밋 다르다.** clone 하면 `e51d9a8` 이 받아진다.
> 차이는 `docs/` 뿐이고 `backend/app/` 은 동일하므로(§2), **코드를 읽는 목적에는 문제가 없다.**
> VPS 와 글자 그대로 같은 상태를 보고 싶으면 `git checkout ded22f3` 한다(읽기 전용 detached HEAD).

**1) 배포 대조**
```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log -1 --format="%H %s"'
```
보는 법: 출력이 `ded22f3…` 이면 조사 시점과 같다. **다른 SHA 가 나오면 그 뒤로 배포가 있었다는 뜻**이니
§1 의 Fix 표와 `git log ded22f3..<새 SHA>` 를 대조해 무엇이 추가됐는지 먼저 파악하라.

**2) 컨테이너 살아있나 + 언제 시작했나**

`docker compose ps` 는 **「Up 9 minutes」 같은 상대 시각만** 준다. 배포 판정에는 쓸 수 없으므로
절대 시각(`StartedAt`)과 서버 현재 시각(`date -u`)을 **같이** 찍는다:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose ps --format "table {{.Name}}\t{{.Status}}"'
ssh root@159.65.137.250 'docker inspect -f "{{.Name}} {{.State.StartedAt}}" binance-auto-trader-api binance-auto-trader-scheduler; date -u'
```
보는 법: **`api` / `scheduler` 두 개가 Up 이어야 한다.** `db` 가 Up 인 것은 의미 없다(빈 껍데기, §9).
`StartedAt` 이 `~/binance-auto-trader/backend/app/**` 파일 mtime 보다 **뒤**면 배포 반영됨 (§2).

**3) 지금 돈이 들어가 있는 전략** — 여러 줄 SQL 은 로컬에 파일로 쓴 뒤 보내는 편이 안전하다.

> ⚠️ **이 단계만 파일을 3곳에 쓴다. 셋 다 「덮어쓰기」다:**
> 1. **로컬 cwd** — `cat > ops_active.py` 는 **같은 이름 파일이 있으면 묻지 않고 덮어쓴다.** 🚨 **저장소 안에서 실행하지 마라** — 커밋에 섞여 들어가고, 나중에 VPS `git pull` 을 막는다(§2 참조). 저장소 **밖의 임시 폴더**에서 하라:
>    ```bash
>    mkdir -p ~/ops-scratch && cd ~/ops-scratch    # ← 여기서 heredoc 실행
>    ```
> 2. **VPS `/root/ops_active.py`** — 같은 이름이면 덮어쓴다. 조사용이라 무해하지만, 이미 `/root` 에 `q1.py`~`q8.py`, `vq.py`, `sch.log` 가 쌓여 있다(§8 하단 참조).
> 3. **컨테이너 안 `/tmp/a.py`** — 🚨 이름이 너무 짧고 흔하다. **두 사람이 동시에 조사하면 서로의 스크립트를 덮어쓴다.** 자기 이름을 붙여라(예: `/tmp/ops_active_0904.py`).
>
> ✅ **파일을 안 쓰고 끝내는 방법도 있다** — 한 줄짜리 조회라면 §3 처럼 `python -c "…"` 로 바로 보내면 된다. 여러 줄이 필요할 때만 위 방식을 쓴다.
> ✅ 이 스크립트들은 **`select` 만** 한다. 새 PC에서 붙여 넣기 전에 **`insert`/`update`/`delete` 가 섞이지 않았는지 눈으로 확인**하라 — 여기서 실행되는 것은 **운영 Neon DB** 다.

먼저 로컬에 `ops_active.py` 를 만든다:
```bash
cat > ops_active.py <<'PYEOF'
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
rows = db.execute(text("""
select si.id, si.symbol, si.side, si.status, st.name, si.current_stage,
       si.current_position_qty, round(si.unrealized_pnl::numeric,2),
       round(si.realized_pnl::numeric,2), si.leverage, si.force_sl_roi_override
from strategy_instances si
left join strategy_templates st on st.id = si.strategy_template_id
where si.status not in ('STOPPED','COMPLETED','CANCELLED','FAILED','REENTRY_READY')
order by si.id desc
""")).fetchall()
for r in rows:
    print(" | ".join("" if v is None else str(v) for v in r))
print("total:", len(rows))
PYEOF
```
보내서 실행한다 (🚨 `PYTHONPATH=/app` 을 빼면 `ModuleNotFoundError`):
```bash
scp -o StrictHostKeyChecking=no ops_active.py root@159.65.137.250:/root/ops_active.py
```
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose cp /root/ops_active.py api:/tmp/a.py && docker compose exec -T -e PYTHONPATH=/app api python /tmp/a.py'
```

> 참고: 이 조사에서 만든 스크래치 파일이 VPS 에 남아 있다 — `/root/q1.py` ~ `/root/q8.py`, **`/root/vq.py`**, `/root/sch.log`(200,000줄, **52.5 MB** = 실측 `52,505,186` 바이트), 컨테이너 안 `/tmp/q*.py`. 지워도 무방하지만 **읽기 전용 원칙** 때문에 이 조사에서는 지우지 않았다.
> 🚨 **지울 때 `rm /root/*.py` 같은 와일드카드를 쓰지 마라.** `/root` 는 사장님이 다른 용도로 쓰는 파일이 섞일 수 있는 곳이다. **`ls` 로 눈으로 확인 → 파일명을 하나씩 지정 → `rm -i`** (§5 의 삭제 절차와 동일). 디스크는 여유가 있다(48G 중 24G) — **급하지 않으니 서두르지 마라.**
> 🔒 **비밀 관점 확인 완료**: `/root/sch.log` 에 자격증명 흔적이 있는지 실제로 훑었다 — `listenKey` **0건**, 50자 이상 연속 토큰 문자열 **0건**. 즉 이 로그를 지우지 않고 둬도 키가 새는 상황은 아니다. 다만 `/root` 는 root 만 읽으므로 **그대로 두되 밖으로 복사하지는 말 것**(로그를 통째로 옮기면 심볼·수량·손익 같은 거래 정보가 같이 나간다).

**4) 오늘 진입 (KST, 진입일 기준, 수동/자동 분리)** — §4 의 SQL 을 쓸 것.

**5) 위험 스위치 현재 값**
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for k,v in db.execute(text(\"select key,value from system_settings order by key\")).fetchall(): print(k,\"=\",v)
"'
```
> ⚠️ 이 명령은 `system_settings` 값을 **자르지 않고 전부** 화면에 뿌린다.
> 2026-09-03 실조회 기준 이 테이블에 비밀 값은 **없다** — 비밀(바이낸스 API 키 · `ENCRYPTION_KEY` · 텔레그램 봇 토큰 · DB 접속문자열)은 전부 `.env` 와 `exchange_accounts` 의 암호화 컬럼에 있고, `system_settings` 63행은 숫자·on/off 토글뿐이다
> (`telegram_bot_token` / `telegram_chat_id` 는 `app/core/config.py:21-22` = **환경변수**이지 `system_settings` 가 아니다).
> 다만 이후 누가 키를 추가했을 수 있으니 **출력을 채팅·스크린샷·이슈에 붙이기 전에 한 번 훑어볼 것.** 훑기 싫으면 §6 처럼 `left(value,60)` 로 잘라서 본다.
>
> 🚨 **실용 경고: 이 명령을 그대로 돌리면 화면이 폭발한다.** 63행 중 **4행이 초장문 JSON** 이다 (실측 길이):
> `pattern_learning_insights_v187` **19,699자** / `learning_agent_insights` **3,688자** / `suggestion_default_profiles` **1,626자** / `post_liquidation_analysis_v212` **330자**.
> 이 넷이 **스크롤을 밀어내서 정작 보려던 위험 스위치가 화면 밖으로 사라진다.** 위험 스위치만 보려면 §6 처럼 자르거나, 길이만 먼저 보라 (값 노출 없음):
> ```bash
> ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
> from app.core.database import SessionLocal
> from sqlalchemy import text
> db = SessionLocal()
> for k,v in db.execute(text(\"select key, left(value,40) from system_settings where length(value) <= 60 order by key\")).fetchall(): print(k,\"=\",v)
> "'
> ```

**6) 지난 밤 사이 ERROR 만 뽑기**

`--tail 200000` 은 52 MB 를 통째로 훑어 느리다. **시간으로 자르는 편이 낫다** (아래는 약 45초):
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -E " (ERROR|CRITICAL) " | tail -40'
```

🚨 **위 명령만으로는 「무엇이 깨졌는지」를 알 수 없다.** apscheduler 의 ERROR 한 줄은
`Job "…_wrapped (trigger: interval[1:00:00] …)" raised an exception` 이라 **워커 이름이 안 나온다.**
원인은 바로 뒤에 붙는 traceback 에 있으므로 `-A 14` 로 뒤 14줄을 같이 봐야 한다:
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --no-color --since 24h scheduler 2>&1 | grep -A 14 -E " (ERROR|CRITICAL) " | tail -60'
```
지금 나오는 6건은 전부 §7 ⑤ 의 `mainnet_safety_worker` 다 (`interval[1:00:00]` = 1시간 주기가 단서).

**7) 🚨 오늘 제일 중요한 관찰 — 2단계로 올라간 전략이 생겼나** (§7 ⑧)
```bash
ssh root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
q = \"select current_stage, count(*) from strategy_instances where status like :p group by 1 order by 1\"
print(db.execute(text(q), {\"p\": \"STAGE%\"}).fetchall())
"'
```
- `[(1, N)]` **만** 나오면 = Fix 304~326 의 효과가 **아직 확인 안 됨** (조사 시점 상태).
- `[(1, N), (2, M)]` 처럼 **2 가 등장하면** = 단계 전환이 처음으로 성공한 것 → §7 ⑧ 을 닫을 수 있다.

---

### 9. 🚨 새 PC에서 하면 안 되는 것

| 하지 마라 | 이유 |
|---|---|
| 🚨 새 PC 에서 `docker compose up` / `python -m app.workers.scheduler_runner` 로 앱을 띄우기 | 🚨 **이 표에서 가장 비싼 실수.** `.env` 가 운영 Neon + 실계정 키를 가리키므로 **VPS 스케줄러와 같은 계정에 붙은 두 번째 엔진**이 된다 → 중복 주문 / 손절·단계 전환 이중 실행. 상세는 §0.5 #1 |
| 🚨 로컬에서 `alembic upgrade head` (또는 `downgrade`) | 🚨 `alembic/env.py:27-30` 이 `DATABASE_URL` 을 그대로 쓴다 = **운영 DB 스키마가 바뀐다**. 현재 `0034_surge_ladder`. 마이그레이션은 VPS 에서 사장님 승인 후 (§0.5 #3) |
| 🚨 로컬에서 Binance REST 직접 호출 (조사 스크립트 포함) | 🚨 **IP ban(418) 전력**(2026-08-26). 새 PC = 새 IP. 시세·포지션은 **VPS api 컨테이너를 통해서만** 본다 (§0.5 #2) |
| 🚨 `git stash` / `git stash pop` | 🚨 **worktree 공유 저장소**다. stash 는 저장소 전역이라 다른 worktree 작업까지 삼키고, `pop` 충돌 시 복구가 어렵다. **브랜치 파서 커밋**으로 대체 (§0.5 #4) |
| 🚨 VPS 에서 `git pull` 을 「조회」로 취급 | 🚨 `.:/app` **바인드 마운트**라 pull 즉시 컨테이너 안 파일이 바뀐다. 재시작 전까지 **옛 코드 + 새 코드 혼합 import** 위험. **pull = 배포의 시작** (§0.5 #5, §2) |
| 🚨 `reset --hard` / `checkout .` / `clean -fd` / `rm -rf` 로 막힌 상황 밀어붙이기 | 🚨 VPS 작업트리에 **untracked 조사 스크립트 31개**가 있고 전부 날아간다. `rm` 은 **와일드카드 없이, `ls` 로 경로 확인 후, `-i` 로** (§5) |
| 🚨 `--force` push / 브랜치 강제 덮어쓰기 | 🚨 `main` 이 곧 **배포 대상**이다. 강제 푸시는 다른 PC·VPS 가 이미 가진 커밋을 **되돌릴 수 없게** 만든다. 충돌은 merge 로 풀 것 |
| `docker compose exec db psql …` 로 조회 | 🚨 로컬 `db` 컨테이너는 **빈 껍데기**. 실 DB 는 외부 **Neon**. 「테이블이 없다」는 오진으로 이어진다 |
| `PYTHONPATH=/app` 없이 `docker compose exec api python` | `ModuleNotFoundError` |
| 쿼리 실패 후 그대로 다음 쿼리 | 세션이 막힌다. `db.rollback()` 을 반드시 넣을 것 |
| 파일 mtime 만 보고 「배포됐다」 판정 | 🚨 `docker exec grep` 은 **디스크**를 본다. **프로세스 시작 시각 vs 파일 수정 시각**으로 판정할 것 (§2) |
| `stage_trim_before_next_enabled` / `sajangnim_ladder_stages_enabled` 를 임의로 토글 | 🚨 지금 ON 이고 실자금 8건이 물려 있다. 오늘만 이 계열로 Fix 315→321, 318→319, 304→326 연쇄 사고가 났다 |
| 청산일 기준으로 일일 실적 판정 | 🚨 확정 교훈. **진입일**로 갈라야 한다 (§4) |
| 코드 감사에 `grep -r` 로 **개수 세기** | 🚨 `__pycache__/*.pyc` 와 **커밋 안 된 작업 중 파일**까지 세어 **새 PC 의 clone 과 숫자가 달라진다.** 이 문서의 §7 ② code 값도 그래서 1씩 부풀어 있었다. 개수를 근거로 쓸 거면 **`git grep`**(추적 파일만) 을 써라 (§7 ②) |
| 로그 파이프라인(`sed`+`cut`)의 버킷 크기를 **정확한 건수**로 인용 | 🚨 심볼 치환이 소문자·한자 심볼을 못 지워 같은 메시지가 여러 버킷으로 갈린다. §5 1위는 26,906 으로 보이지만 **실제 27,257** 이고 재실행하면 또 달라진다. 정확한 수는 **메시지 원문을 `grep -c`** (§5) |
| 미실현 손익이 문서와 다르다고 고장 의심 | ⚠️ 미실현은 **시세**다. 재현 판정은 **건수와 실현손익**으로만 하라 (§3 · §4) |
| WARNING 42,780건을 보고 놀라기 | 대부분 정상 게이트 로그와 요약 로그다. 진짜는 **ERROR 6건 + misfire 432건** (§5) |
| VPS 에서 재시작·설정변경·DB 쓰기 | 실자금이 돌고 있다. 배포·재시작은 사장님 |
| 🚨 「한 줄이니까」로 코드 수정 → 바로 배포 | 🚨 **코드 수정 = 배포 = 재시작**이고, 재시작 동안 **포지션 8건을 지키는 손절 잡이 멈춘다.** 오늘만 Fix 318→319(수정이 엉뚱한 함수에 붙음), 315→321(손절을 다시 잠금) 이 났다. `tests/test_stage_flow_execution.py` 등을 **먼저** 돌려라 (§1 하단) |
| 🚨 §7 ③ 을 읽고 LONG 손절을 −10% 로 바꾸기 | 🚨 **그건 이미 했다가 실측으로 되돌린 값**이다 (Fix 253, 2026-09-01). 바꾸면 패자 손실이 다시 2배가 된다. 지시 문서와 실측이 **충돌**하는 사안이니 **사장님께 충돌 자체를 보고**하라 (§7 ③) |
| 🚨 되돌리는 법을 정해두지 않은 채 무언가 바꾸기 | 🚨 설정이면 **바꾸기 전 값**(특히 「행 없음」 vs 「0」), 코드면 **revert 할 커밋**을 먼저 확보. 이게 없으면 사고가 났을 때 **원래 상태를 아무도 모른다** (§7 ②) |
| 🚨 새 PC 에서 `ENCRYPTION_KEY` 를 **새로 생성** (`Fernet.generate_key()` / `deploy/generate-secrets.sh` 통째 붙여넣기) | 🚨 **DB 의 `api_key_enc` / `api_secret_enc` 가 즉시 영구 복호화 불가**가 된다. Fernet 대칭키라 복구 수단이 **없다** — 바이낸스에서 키 재발급뿐. 기존 DB 를 계속 쓸 거면 **글자 하나도 바꾸지 말고 그대로 옮긴다.** 절차는 `secrets.md` §3 |
| 🚨 API 키·시크릿·`ENCRYPTION_KEY`·DB 접속문자열·SSH 개인키를 **채팅·이메일·메신저·스크린샷·이슈**로 전달 | 🚨 그 순간 비밀이 서버 로그·백업·대화 기록에 영구 저장된다. 되돌릴 방법이 없다. **비밀은 사장님이 직접 새 PC 앞에서 손으로 입력**하거나 비밀번호 관리자로 옮긴다. AI 에게 값을 붙여넣어 달라고 하지 말 것 |
| 🚨 명령줄에 비밀 값을 그대로 적기 (`-e KEY="실제값"`, `export KEY=...`) | 셸 히스토리 · `ps` 출력 · docker inspect 에 남는다. 파일(`umask 077`)로 넘기고 끝나면 `history -c`. `secrets.md` §3-3 참조 |
| 🚨 `.env` 를 `cat` 해서 그 출력을 어딘가에 붙여넣기 | 이 저장소의 조사 원칙: **값은 읽지 않는다.** 존재·길이·지문(해시 앞자리)만 비교한다 (`secrets.md` §4 가 값 노출 없이 비교하는 방법) |


---

<a id="sec-8"></a>

## 8. 이번 세션에서 한 일과 다음 할 일

> 작성: 2026-09-03 (세션 인수인계 담당)
> 대상 커밋: `ded22f3` (main, VPS 배포 완료 — 아래 §1 에서 실측 확인)
> ℹ️ 그 뒤에 문서 전용 커밋 `e51d9a8`(`chore(handoff)`)이 하나 더 있다. **backend 파일 0개**(실측: `git show --name-only e51d9a8 | grep -c '^backend/'` → 0)라 **배포 대상 코드는 여전히 `ded22f3` 이다.** §7 에서 `git log` 를 돌리면 맨 위에 `e51d9a8` 이 보이는데 정상이다.
> 🔒 이 문서에는 **비밀 값이 없다**(2026-09-03 비밀 누출 검토 완료 — 키 **이름**과 「어디서 얻는가」만 기록). 비밀은 `secrets.md` 로, 값은 어디에도 적지 않는다.
> 이 섹션만 읽고도 새 세션이 이어받을 수 있게 썼다. **추측한 곳은 「⚠️ 확인 못 함」으로 표시**했다.

---

### 0. 30초 요약

| 항목 | 상태 |
|---|---|
| 이번 세션 커밋 | **Fix 325 / 326 / 327** (`0459e8f` → `1d04598` → `ded22f3`) |
| VPS 배포 | ✅ **완료** — 파일 mtime `2026-09-03 08:51 UTC`, api 컨테이너 기동 `08:51:26 UTC`, scheduler `08:51:57 UTC` |
| Fix 325 (순위 100개 진입 대상) | 🚨 **이미 살아서 돌고 있다** — 스위치를 안 눌러도 기본값이 `rank` 다 |
| Fix 326 (잔량 유지 손절) | 🚨 **이미 살아 있다** (`stage_trim_before_next_enabled='1'`). **다만 배포 후 손절 이벤트 0건 = 아직 실검증 안 됨** |
| Fix 327 (지지선 7점 게이트) | ⏸ **OFF** (`support_score_gate_enabled` 행 자체가 없음). 켜야 동작한다 |
| 신규 문서 | `docs/spec/*_2026-09-03.{md,json}` 5건 (차트분석 에이전트팀 4명 실측) |
| 🚨 제일 먼저 할 일 | **Fix 326 실검증** (§6 P1) — 실자금이 도는 손절 경로를 바꿔놓고 아직 한 번도 안 돌았다 |
| 🧭 읽는 순서 | 새 PC 면 **`local-env.md` → `secrets.md` → 이 문서 §7 → §6**. §7 의 3개 명령이 다 돌아야 §6 이 의미가 있다 |
| 🚨 **새 PC 로 가기 전에 반드시** | 이 worktree 에 **커밋 안 된 3,666줄**(`terminal.py` / `perp-terminal.html` / `router.py` 수정)이 있다. GitHub·VPS·백업 폴더 **어디에도 없다** → 클론하면 **영구 소실**. 살리는 명령은 §6-3 끝 |

---

### 1. 배포·운영 상태 (전부 실측, 읽기 전용 조회)

#### 1-1. 배포 판정 근거

메모리 교훈대로 **「프로세스 시작 시각 vs 파일 수정 시각」**으로 판정했다 (`docker exec grep` 은 디스크일 뿐이라 배포 판정이 안 된다).

| 확인 | 값 |
|---|---|
| VPS `git log -1` | `ded22f3 feat(Fix 327) …` (branch `main`) |
| `backend/app/services/support_score.py` mtime | `2026-09-03 08:51` (UTC) |
| api 컨테이너 `StartedAt` | `2026-09-03T08:51:26Z` |
| scheduler 컨테이너 `StartedAt` | `2026-09-03T08:51:57Z` |
| 조회 시각 | `2026-09-03 09:03 UTC` (= 18:03 KST) |

→ 컨테이너 기동이 파일 갱신보다 **뒤**이므로 세 Fix 모두 **배포됨**.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log --oneline -3 && ls -la backend/app/services/support_score.py && docker inspect binance-auto-trader-api --format "{{.State.StartedAt}}" && docker inspect binance-auto-trader-scheduler --format "{{.State.StartedAt}}" && date -u'
```

#### 1-2. 관련 설정 실측값 (2026-09-03 09:03 UTC, `system_settings` 63행)

| 키 | 값 | 의미 |
|---|---|---|
| `entry_chg24_gate_enabled` | `1` (2026-09-02 23:39) | 진입 대상 게이트 **ON** |
| `entry_chg24_gate_mode` | **행 없음** | → 기본 `rank` = 🚨 **Fix 325 순위 방식이 지금 돌고 있다** |
| `entry_rank_top_n` | 행 없음 | → 기본 `50` (상승 50 + 하락 50) |
| `entry_min_abs_chg24` | 행 없음 | (구 절대값 기준, 지금 미사용) |
| `stage_trim_before_next_enabled` | `1` (2026-09-02 22:33) | 🚨 **Fix 326 경로 활성** |
| `stage_keep_notional_usdt` | 행 없음 | → 기본 `10` USDT (증거금 기준) |
| `adaptive_tp_enabled` | `1` (2026-09-02 17:47) | 적응 TP ON — **단, 배선된 경로는 하나뿐** (§6 P5) |
| `confluence_gate_enabled` | `true` (2026-08-31) | 합의 게이트 ON |
| `support_score_gate_enabled` | **행 없음** | ⏸ Fix 327 **OFF** |
| `support_score_min_long` / `_max_short` | 행 없음 | → 기본 6 / 1 |

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value, updated_at from system_settings order by key\")).fetchall():
    print(r[0], \"=\", r[1], \"|\", str(r[2])[:19])
"'
```

> 🚨 **DB 는 로컬 `db` 컨테이너가 아니라 외부 Neon 이다.** `docker compose exec db psql` 로 조회하면 **빈 DB** 가 나와 「테이블이 없다」는 오진에 이른다. 반드시 위처럼 **api 컨테이너의 `SessionLocal`** 을 경유할 것. (옛 롤백 가이드에 적힌 `docker compose exec db psql …` 명령들은 **이 이유로 지금은 틀렸다** — 그 문서를 그대로 따라 하면 안 된다. 정확한 위치와 줄번호는 §9-6 에 정리했다.)

#### 1-3. 배포 후 25분 로그 (실측)

| 확인 | 결과 |
|---|---|
| scheduler 로그 줄 수 (최근 25분) | **8,716줄** (로그 자체는 정상적으로 흐름) |
| `Fix310` / `Fix318` / `Fix319` / `Fix325` / `Fix326` / `Fix327` 태그 | **전부 0회** (scheduler 25분 창, 그리고 scheduler+api 30분 창 — 두 번 따로 확인) |
| `chart_patterns` 행 수 | **0** (§6 P4 의 원인은 그대로) |
| 전략 상태 분포 | STOPPED 1173 / COMPLETED 290 / REENTRY_READY 16 / STAGE1_OPEN 8 |

→ 배포 후 **신규 1단계 진입도, 손절 이벤트도 아직 한 건도 없다.** 그래서 Fix 325/326/327 은 전부 **로그로 확인된 바가 없다** (⚠️ 코드는 배포됐고 테스트는 통과했으나 실서버 실행 증거는 아직 0).

> ✅ **재확인 (2026-09-03 09:38 UTC = 배포 후 47분, 위험 검토 담당이 독립 실행)**: 같은 명령을 `scheduler api` 두 컨테이너 60분 창으로 다시 돌렸다 — `Fix310|318|319|325|326|327` **여전히 전부 0회**. `system_settings` 도 63행 그대로, 위 §1-2 의 10개 키 값이 **한 글자도 다르지 않았다**. 즉 §1-2·§1-3 은 **두 사람이 따로 재서 일치한 값**이다.
> 🚨 **다만 「0회」를 「고장」으로 읽지 말 것.** 지금 STAGE1_OPEN 이 8건뿐이라 손절·진입 이벤트 자체가 드물다. 태그가 0인 것은 **아직 그 코드에 도달할 사건이 없었다**는 뜻이고, 「배포가 안 됐다」는 뜻이 **아니다**(배포 판정은 §1-1 의 mtime vs StartedAt 으로 이미 끝났다).
> ✅ **세 번째 재확인 (2026-09-03 09:36~09:50 UTC, 재현성 검증 담당)**: §1-1·§1-2·§1-3 의 명령을 **그대로 복사해 실행**했고 표의 값이 전부 일치했다 (`ded22f3` / mtime `Sep 3 08:51` / api `08:51:26Z` / scheduler `08:51:57Z` / `system_settings` 63행 / 10개 키 동일 / `chart_patterns` 0 / 상태분포 `1173·290·16·8` / Fix 태그 0회). **이 세 명령은 새 PC 에서 그대로 붙여 넣어도 돈다.**
> ✅ 추가 실측: 배포(`08:51 UTC`) 이후 `strategy_instances` 에 **`created_at` 기준 신규 0건**(09:45 UTC 확인) — 「신규 1단계 진입이 없었다」가 로그뿐 아니라 DB 로도 확인됐다. 재실행 명령은 §6-1 끝에 있다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 60m --tail 40000 --no-log-prefix scheduler 2>/dev/null | grep -oE "Fix3(10|18|19|25|26|27)" | sort | uniq -c'
```

---

### 2. 2026-09-03 신규 문서 5건 — 요약과 핵심 숫자

전부 **차트분석 전문가 에이전트팀 4명**이 실측으로 만든 것이다. 숫자를 지우지 말 것.

| 문서 | 무엇인가 | 표본 | 코드 반영 |
|---|---|---|---|
| `SUPPORT_BOUNCE_VS_BREAKDOWN_2026-09-03.md/.json` | **지지선 7점 판정식** (BOUNCE vs BREAKDOWN) | 접촉 264건 / 30심볼 / 15m 75시간 | ✅ `app/services/support_score.py` (Fix 327) |
| `CHART_REGIME_ANALYSIS_2026-09-03.md` | **차트 5국면 분류** (급등·급락·보합·지지반등·추가하락) 수치화 | 5,916봉 / 30심볼 / 15m·1h·4h 300봉 | ❌ 코드 미반영 (의도적 — 아래 참조) |
| `REGIME_THRESHOLDS_2026-09-03.json` | 위 문서의 **기계용 임계값** 2,460줄 | 동일 | ❌ 아직 읽는 코드 없음 |
| `REGIME_REAL_TRADE_VALIDATION_2026-09-03.md` | **실거래 DB 로 이론 검증** | 손익 확정 **1,419건** / 315심볼 / 2026-07-05~09-03 | ❌ (다음 할 일의 근거로 쓰임) |
| `REGIME_WIRING_AUDIT_2026-09-03.md` | **어디에 꽂아야 하는가** 배선 감사 (코드 0줄 수정) | 파일:줄번호 전수 | ✅ Fix 327 이 이 감사대로 배선됨 |

#### 2-1. `SUPPORT_BOUNCE_VS_BREAKDOWN` — 핵심 숫자

- 지지선 정의 **9개를 전부 재서** `swing_low`(좌우 3봉 피벗 저점) 채택 — OOS 평균 |d| **+0.517** 1위, 안정 지표 23개.
- **기각**: 볼밴 하단 OOS **−0.125** (안정 지표 6개뿐) / fib 0.5 **−0.724** / fib 0.618 **−0.656** → 그룹을 바꾸면 판정이 **정반대**. 「밴드 하단 = 지지」로 코딩하면 안 된다.
- 7점 판정식 결과 (기준선 **55.0%**, n=264):

  | 구간 | n | 승률 | A그룹 | B그룹 |
  |---|---:|---:|---:|---:|
  | score ≥ 7 → LONG 강 | 47 | **76.9%** | 78.3 | 75.0 |
  | score ≥ 6 → LONG | 80 | **70.6%** | 75.0 | 64.3 |
  | 2~5 → 관망 | — | — | — | — |
  | score ≤ 1 → SHORT | 67 | **63.9%** | 72.2 | 60.5 |
  | score = 0 → SHORT 강 | 22 | **71.4%** | 80.0 | 63.6 |

- TP/SL 근거(가격 %, 8시간 지평): LONG(≥6) → **SL −3% / TP1 +3% / TP2 +5%** (TP+3% 도달 70.0%, TP+5% 53.8%, SL−3% 터치 36.2%). SHORT(≤1) → SL +3% / TP1 −3% / TP2 −5% (−3% 도달 74.6%).
- 🚨 **재진입 반증**: 직전 접촉이 손절이어도 다음 접촉 승률 **49.1%**(n=55) — 기준선 55.0% **아래**. 「손절했으니 확률이 오른다」는 성립하지 않는다. → **재진입 전용 규칙을 만들지 않는다. 같은 score 로 판정한다. 자본을 배수로 키우지 않는다.**
- 🚨 **미래참조 경고**: 순진하게 재면 「직전손절 36.8% / 직전반등 69.7%」라는 극적인 값이 나오는데, 연결된 234건 중 **102건(43.6%)** 이 이번 접촉 시점에 아직 결착이 안 난 상태였다. **그 숫자로 코딩하면 안 된다.**

#### 2-2. `CHART_REGIME_ANALYSIS` — 핵심 숫자

- 국면 정의(순서대로 첫 번째로 맞는 것): RANGE(밴드폭 자기순위 ≤0.25 & 6봉 변화 ≤0) → SURGE(`ret12 ≥ +4.07%`) → CRASH(`ret12 ≤ −3.13%`) → BOUNCE(`px_pos48 ≤ 0.25 & ret48 < 0 & ret4 ≥ +1.17%`) → BREAKDOWN(`px_pos48 ≤ 0.25 & ret48 < 0 & ret4 ≤ −0.92%`) → RANGE(잔여). **모든 경계는 실측 분위수**다.
- 국면별 표본: SURGE 815(13.8%) / CRASH 786(13.3%) / RANGE 4,076(68.9%) / **BOUNCE 40(0.7%)** / BREAKDOWN 199(3.4%).
- 국면 확정 후 2시간 실측: SURGE +0.73%/승률 57.3% ✅재현 / CRASH −0.46%/46.2% ❌**두 그룹 부호 뒤집힘** / RANGE +0.30%/52.5% ✅ / **BOUNCE −1.94%/31.6%** ✅재현 / **BREAKDOWN +0.53%/57.4%** ✅재현.
- 🚨 **절대 임계값은 종목 스케일이 바뀌면 무력해진다** — AKEUSDT 밴드폭 절대 13.21%(넓음)인데 자기 50봉 순위는 **0.02**(최대 수축). v1 판정식은 이 보합을 **CRASH 85%** 로 오판했다. → **모든 국면 지표는 자기 이력 백분위로 정규화**할 것. 이 함정에 이번 분석에서 **세 번**(밴드폭·ATR·RSI/CCI) 걸렸다.
- 🚨 **ATR 정규화는 과교정**(v2 폐기): 급락이 ATR 을 부풀려 −23.7% 하락이 −1.5 배수밖에 안 돼 CRASH 문턱에 못 미쳤다. → **현재 변동성으로 그 변동성을 만든 움직임을 정규화하면 안 된다.**
- 🚨 **지표 수준 교차검증을 통과해도 결과 수준에서 뒤집힐 수 있다**: SURGE vs CRASH 방향 판정기를 표본외로 돌리니 A→B **+0.74%p** / B→A **−0.43%p** 로 부호 반전. **효과크기만 보고 채택하면 안 된다.**
- 문서 스스로 **「BOUNCE 는 표본 40건뿐, 지금 수치로 로직을 만들면 안 된다」** 고 못 박았고, **BREAKDOWN 정밀도 15.6%** = 독립 진입 신호로 쓰면 안 된다고 적었다. → 그래서 이 문서의 국면은 **코드에 들어가지 않았다.**

#### 2-3. `REGIME_REAL_TRADE_VALIDATION` — 핵심 숫자 (실거래 1,419건)

| 확정된 것 (앞/뒤 절반 모두 방향 일치) | 숫자 |
|---|---|
| 수동이 손실의 **94.3%** | 수동 791건 −13,401.7 / 자동 628건 −803.7 |
| **BOTTOM(저점LONG) 하나가 자동을 적자로 만든다** | BOTTOM 156건 **−1,049.0** PF 0.28. 빼면 자동 472건 **+245.4** PF 1.07 (전반 +0.16 / 후반 +0.88) |
| SHORT 는 **24h +10~+30%** 에서만 이긴다 | 106건 +5.44/건 PF 1.70. 경계는 +5% 아니라 **+10%** ([+5,+20) 은 차이 없음) |
| LONG 은 **어느 국면에서도** 이기지 않는다 | 잰 네 칸 전부 음수 |
| `macd_4h_direction=up` **LONG** | 43건 **승률 2.3%** PF 0.00 (앞뒤 4.5% / 0.0%) |
| `PATTERN_B_AFTER_CORRECTION` | 45건 승률 11.1% 건당 −11.25 **PF 0.04** — 43/45가 24h ±10% = **평탄 구간을 「조정」으로 오인** |
| 손절 후 **6시간 이내 재진입 금지** | 93건 −4.25 (전반 −3.16 / 후반 −8.21) |
| `MACD_15M_REVERSAL_SHORT` 는 안정 양수 | 188건 +1.09 (전 +1.22 / 후 +1.00) |
| 피라미딩은 계속 손실 | SUCCESS_PYRAMID 26건 **−559.5** (최악 SKRUSDT SHORT −724.80) |
| 🚨 `max_profit_pct` 결손 = **패배** | 결손 285건 중 **94.4% 가 손실**. → 자동 628건 중 **최소 269건(42.8%)이 한 번도 +로 못 갔다** = **익절 구조가 아니라 진입 자리 문제** |
| 🚨 자동에 「청산 후 재진입」이 켜진 적 없음 | 확정 자동 628건 **전부 False**. 51건 True 는 **전부 수동** |

#### 2-4. `REGIME_WIRING_AUDIT` — 핵심

- **`chart_patterns` 0건의 확정 원인**: 신뢰도 컷도 예외 삼킴도 아니고 **잡 본문이 한 번도 실행된 적이 없다.**
  - `scheduler_runner.py:74` `BlockingScheduler(timezone="Asia/Seoul")` 에 `job_defaults` 가 없다 → `misfire_grace_time` = APScheduler **기본 1초**. 부팅 직후 첫 실행이 `missed by 0:00:01.95` 로 **폐기**된다.
  - 다음 기회는 「부팅 + 6시간」인데 스케줄러가 **72시간에 57회 재시작**한다 → 6시간 잡은 **구조적으로 굶는다**. 실측: `interval[6:00:00]` Running **0** / missed 18, 반면 `interval[1:00:00]` Running **424**.
  - 같은 이유로 굶는 잡: `binance_changelog_monitor` (`scheduler_runner.py:580`).
- 🚨 **되살려도 진입에는 안 쓰인다** — `ChartPattern` 을 읽는 코드는 **쓰기 2곳 + 화면 2곳뿐**, 진입 판정 **0곳**. 스케줄만 고치면 **Fix 247 과 똑같은 모양**(계산·저장만 하고 진입은 안 봄)이 된다.
- **신규 1단계 진입의 단일 관문 = `app/services/execution_service.py:188 start_stage1`.** 직접 호출 7곳 + 공용 깔때기(`_create_auto_bb_strategy`) 경유 7곳 = **전부** 여기를 지난다.
- 🚨 **`trigger_next_stage`(`execution_service.py:305`, 2026-09-03 실측 — `grep -n "def trigger_next_stage" app/services/execution_service.py`)에는 절대 걸지 않는다.** 자본이 들어간 사다리가 그 자리에서 영원히 멈춘다 (Fix 203 / Fix 235 전력).
- 🚨 **국면 판정이 이미 둘 있다**: `app/services/pump_dump_regime.py`(진입 8곳에서 호출) 와 `app/api/v1/bb_middle_scan.py:170 _detect_regime`(사장님 v169 4구간 — API 라우터 안에 숨어 있는데 `auto_bb_breakdown_worker.py:133-142` 가 import 해서 **실제로 진입에 닿는다**). **세 번째를 만들지 말 것** — `_detect_regime` 을 `app/services/market_regime.py` 로 끌어올려 확장하는 것이 권고안이다.

---

### 3. 🚨 두 문서가 모순처럼 보이는 이유 — 새 세션이 반드시 읽을 것

**표면상 정반대로 보이는 두 결론**

| 문서 | 결론 |
|---|---|
| `CHART_REGIME_ANALYSIS` §5, §8 | **BOUNCE(지지반등) 승률 31.6% / 평균 −1.94% → LONG 진입 금지.** BREAKDOWN(추가하락) 57.4% / +0.53% → SHORT 진입 금지 |
| `SUPPORT_BOUNCE_VS_BREAKDOWN` §6 | **score ≥ 6 → LONG 승률 70.6%.** score ≤ 1 → SHORT 승률 63.9% |

**모순이 아니다. 두 문서는 「지지선 근처의 서로 다른 시점」을 재고 있다.**

#### 3-1. 결정적 차이 — 라벨 정의를 실제로 읽으면 드러난다

| | CHART_REGIME 의 BOUNCE | SUPPORT 의 「접촉」 |
|---|---|---|
| 정의 | `px_pos48 ≤ 0.25` **AND** `ret48 < 0` **AND** **`ret4 ≥ +1.17%`** | `low[i] ≤ S×(1+tol)` **AND** `close[i−1] > S×(1+tol)` **AND** 24봉 고점 대비 `≤ −1.0%` |
| `ret4` / 접촉의 뜻 | 직전 **4봉(1시간) 수익률이 상위 25%(p75)** = **이미 1시간 동안 크게 올랐다** | **지금 막 위에서 내려와 지지선을 찍었다** = 아직 안 올랐다 |
| 시점 | 반등을 **눈으로 확인한 뒤** | 반등이 **일어나기 전** |
| 미래 창 | 15m × 8봉 = **2시간** | 15m × 32봉 = **8시간**, ±3% 선도달 |
| 표본 | **n=38~40 (전체의 0.7%)** | **n=264** |

> **즉 CHART_REGIME 의 「BOUNCE」는 「지지반등이 일어날 자리」가 아니라 「이미 반등이 1시간치 일어난 자리」다.** 그 자리에서 사면 비싸게 사는 것이고, 그래서 승률 31.6% 다.
> `SUPPORT` 의 score ≥ 6 은 **닿는 순간**의 자리다. 여기서는 70.6% 다.

#### 3-2. 같은 이야기를 SUPPORT 문서가 지표로 못 박아 놨다

`SUPPORT` 의 7규칙 중 **3번은 일부러 역방향**이다:

```
m15_macdh_not_rising3 :  NOT ( MACD_hist[i] > MACD_hist[i-3] )    ← 15분봉
```

- 효과크기 d(3분위) **−0.380** / d(트레이드) −0.364 — **15분 MACD hist 가 3봉 상승 중이면 그 접촉은 더 잘 깨진다.**
- 이게 「이미 올라서 비싸게 사는」 아티팩트인지 **재검증**했다: 지지선 대비 종가 위치를 층으로 고정해도 **−0.401 / −0.490**, 지지선 지정가를 가정해도 **−0.298** 로 **살아남는다**.
- 반면 같은 계열로 의심됐던 것들은 통제하면 **사라졌다**: RSI 상향전환은 지정가 가정에서 **+0.080 으로 부호가 뒤집혔다**(= 순수 아티팩트, 버림), 아래꼬리 비율도 대부분 소멸(버림).

**해석(문서 §4-1 원문 취지)**: 지지선에 닿는 순간까지 하락 모멘텀이 살아 있으면 그건 빠른 투매고 V자 반등이 나온다. 반대로 hist 가 이미 3봉째 올라오는데도 여전히 지지선을 찍고 있으면 **반등 시도가 이미 한 번 실패했다는 뜻**이라 다음 이탈이 온다.

#### 3-3. BREAKDOWN 쪽도 같은 구조다

- CHART_REGIME 의 BREAKDOWN 정의는 `ret4 ≤ −0.92%` = **이미 1시간 내려간 뒤** → 「이미 다 빠졌다」 → 이후 +0.53%. 게다가 **인식 정밀도 15.6%** (그렇게 부른 것 6~7건 중 1건만 진짜, 나머지는 대부분 CRASH).
- SUPPORT 의 score ≤ 1 은 **접촉 순간에 1H 방향축이 죽어 있는** 상태 → 이후 −3% 도달 74.6%.

#### 3-4. 그래서 코드에는 무엇이 들어갔는가

| 것 | 코드 반영 | 이유 |
|---|---|---|
| SUPPORT 7점 판정식 | ✅ `support_score.py` + `start_stage1` 배선 | n=264, 두 그룹 모두 기준선 초과, 6개 다른 지지선 정의로 이식해도 재현 |
| CHART_REGIME 의 BOUNCE/BREAKDOWN 국면 | ❌ **의도적으로 넣지 않음** | 문서 스스로 「BOUNCE n=40, 교차검증 통과 지표 0개, 지금 수치로 로직을 만들면 안 된다」 / 「BREAKDOWN 정밀도 15.6%, 독립 진입 신호로 쓰지 말 것」이라고 결론 |

> **한 줄로**: 두 문서 모두 같은 결론을 말한다 — **「반등한 걸 보고 들어가면 진다. 지지선에 미리 걸어놔야 이긴다.」** 이는 사장님 사상(「4H 조정 구간에 미리미리 분할, 바닥 확인 X」)과도 정확히 같다.
> 🚨 **새 세션 주의**: CHART_REGIME 의 「BOUNCE 승률 31.6%」를 근거로 `support_score` 게이트를 끄거나 뒤집으면 **오독이다.** 두 숫자는 서로 다른 시점을 재고 있다.

---

### 4. Fix 325 / 326 / 327 — 무엇이 문제였고, 어떻게 고쳤고, 어떻게 되돌리나

| Fix | 커밋 | 무엇이 문제였나 | 어떻게 고쳤나 | 되돌리는 법 | 현재 상태 |
|---|---|---|---|---|---|
| **325** | `0459e8f` | 진입 대상이 절대값 `\|24h\| ≥ 10%` 라 조용한 날 대상이 급감 (실측: 거래대금 5M 이상 **252심볼 중 26개 = 10.3%**) | 사장님 지시대로 **상승 50위 + 하락 50위 = 100개 순위**로 전환 | `entry_chg24_gate_mode='abs'` (DB) → 옛 절대값 / 게이트 자체를 끄려면 `entry_chg24_gate_enabled='0'` / 코드 되돌리려면 `git revert 0459e8f` | 🚨 **동작 중** (mode 행 없음 = 기본 rank) |
| **326** | `1d04598` | 부분 손절로 10 USDT 를 남겨도 **다음 사이클이 전량 청산해 지워버렸다** | `compute_trim` 이 `ACTION_SKIP` 을 주면 **손절하지 않고 그대로 둔다** (두 손절 경로 모두) | `stage_trim_before_next_enabled='0'` (DB) → 부분손절 자체가 꺼져 옛 동작(전량) / `git revert 1d04598` | 🚨 **동작 중**, 단 실검증 0건 |
| **327** | `ded22f3` | 사장님 「분석해서 저장해서 **진입에 모두 사용**해줘」 — 계산만 하고 진입에 안 쓰이는 자리를 또 만들지 않기 위해 | 지지선 7점 판정(`support_score.py`)을 **`start_stage1` 단일 관문**에 배선. **기본 OFF / fail-open / 수동 제외 / 접촉 아니면 미적용** | 켜지 않으면 아무 일도 안 일어남. 껐다 켜기는 `support_score_gate_enabled` 행 삭제 또는 `'0'` / `git revert ded22f3` | ⏸ **OFF** |

##### 🚨 「되돌리는 법」을 실제로 쓰기 전에 — 위험 검토 담당의 경고

1. 🚨 **`git revert` 는 로컬만 바꾼다. 그것만으로는 운영이 되돌아가지 않는다.**
   순서는 `git revert <커밋>` → `git push origin HEAD:main` → **VPS 에서 `git pull`** → **컨테이너 재시작**. 마지막 재시작은 **사장님 몫**이다(실자금이 돌고 있다). 커밋만 되돌리고 「되돌렸다」고 보고하면 오보다 — 이 저장소는 그 사고(「fix 브랜치만 push 하고 main 은 옛 코드」)를 이미 겪었다.
2. ✅ **먼저 DB 설정으로 되돌려라 — 즉시 적용되고 재시작이 필요 없다.**
   Fix 325·326·327 세 개 다 **설정 한 줄로 옛 동작으로 돌아간다**(위 표의 왼쪽 방법). 코드 revert 는 설정으로 안 될 때만 쓴다. 배포·재시작이 끼면 그 자체가 새로운 위험이다.
3. 🚨 **`git revert 1d04598`(Fix 326) 은 「고친 것을 다시 고장내는」 revert 다.**
   되돌리는 순간 §4-2 의 실서버 사고(부분 손절 → **12~300초 뒤 전량 청산**)가 그대로 돌아온다. Fix 326 을 끄고 싶으면 revert 가 아니라 **`stage_trim_before_next_enabled='0'`** 으로 **부분 손절 자체를 끄는 것**이 맞다(그러면 원래대로 전량 손절이라 잔량이 남지 않는다).
4. 🚨 **`git reset --hard` / `git checkout .` / `git clean -fd` / `git push --force` 로 되돌리지 마라.**
   이 저장소는 worktree 를 공유하고 **커밋 안 된 작업이 실재한다**(§6-3 의 `terminal.py` 등 3,666줄). 위 명령들은 **묻지 않고 즉시 지우며 되돌릴 수 없다.** `git revert`(=새 커밋을 쌓는 방식)만 쓴다.
5. 🚨 **`git stash` / `git stash pop` 도 맨손으로 쓰지 마라.** 이 저장소엔 이미 오래된 stash 3개가 쌓여 있다(실측 `git stash list` → `stash@{0}` 는 **2026-08-24** 백업). 아무 생각 없이 `pop` 하면 **8월 24일 코드가 9월 3일 코드 위에 얹힌다.**
6. ✅ **되돌린 뒤에는 반드시 「되돌아갔는가」를 재서 확인한다** — §1-1 의 mtime vs `StartedAt` 명령. 「revert 했다」는 배포 증거가 아니다.

#### 4-1. Fix 325 상세

- 변경 파일 (`git show 0459e8f --numstat` 실측): `backend/app/services/chg24_entry_gate.py` **+86/−23**, `backend/tests/test_chg24_entry_gate.py` **+90/−12** (테스트 **23건** 통과 — §7 ② 로 재확인 가능)
- 신설 설정: `entry_rank_top_n`(기본 50, 허용 1~500 — `chg24_entry_gate.py:98 top_n()`), `entry_chg24_gate_mode`(`"rank"`(기본) | `"abs"` — `:113 gate_mode()`)
- 🚨 **「clamp」가 아니라 「기본값 복귀」다** (2026-09-03 코드 재확인). 범위 밖(예: `entry_rank_top_n=900`)이나 숫자가 아닌 값을 넣으면 **500 으로 깎이는 게 아니라 기본 50 으로 되돌아간다.** 로그에 `[Fix325] entry_rank_top_n=900 범위밖(1~500) → 기본 50` 이 한 줄 남는 것이 유일한 신호다. `entry_chg24_gate_mode` 도 `rank`/`abs` 가 아니면 조용히 `rank` 가 된다. **값을 넣은 뒤 반드시 로그로 실제 적용값을 확인할 것.**
- 판정 위치: `chg24_entry_gate.py:124 passes()` → `execution_service.py:207-228` 에서 호출 (start_stage1 안)
- 유지된 안전장치: **수동 `_quick_` 제외**, **fail-open**(시세/순위 조회 실패 시 통과), **`start_stage1` 에만 적용**(사다리를 끊지 않는다)
- 🚨 **순위 풀에 하드코딩 하한이 있다**: `app/services/market_movers.py:48 MIN_QUOTE_VOLUME = 5_000_000.0` — 설정으로 빠져 있지 않다. 「감으로 정한 값」이라고 주석에 적혀 있다(`market_movers.py:36-47`). 대상이 이상하면 여기부터 볼 것.
- 🚨 테스트에서 배운 함정(커밋 메시지): `top_movers` 는 심볼 풀이 `top_n*2` 보다 작으면 **상승/하락 목록이 겹친다**. 순위 테스트는 반대편을 두껍게 깔아야 한다.

#### 4-2. Fix 326 상세 — 실서버 사고 로그가 근거

커밋 메시지에 남은 2026-09-03 실서버 로그:

| 시각 | 사건 |
|---|---|
| 07:55:00 | MARSCOIN #2091 부분 손절 → 184 잔여(명목 20.04) ✅ |
| 08:00:22 | MARSCOIN #2091 「남길 것이 없다」 → **전량 청산** ❌ (5분 뒤) |
| 08:01:52 | HEMI #2095 부분 손절 → 1173 잔여(명목 20.01) ✅ |
| 08:02:09 | HEMI #2095 「남길 만큼 크지 않다」 → **전량 청산** ❌ (17초 뒤) |
| 07:44:03 / 07:44:15 | UAI #2089 부분 손절 → 52 잔여 ✅ → **전량 청산** ❌ (12초 뒤) |

- 원인: 남긴 잔량은 여전히 손절 ROI 아래라 **다음 사이클에 또 손절 대상**이 된다. 그때 `compute_trim` 이 돌려주는 `ACTION_SKIP`(=이미 잔량 수준)을 **전량 청산으로 처리**하고 있었다.
- 정정된 판단: *"손절을 건너뛰면 손실이 무한정 커진다"* 는 **틀렸다** — 잔량 증거금이 10 USDT 면 **최대 손실도 10 USDT** 다.
- 변경 위치 (2곳 모두 고침):
  - `backend/app/services/tp_sl_orchestrator.py:545 _execute_force_stop_loss` → `:615 elif _act == ACTION_SKIP: … return`
  - `backend/app/services/tp_sl_orchestrator.py:686 _execute_stop_loss` → `:739 elif _act == ACTION_SKIP: … return`
- 동작표: `ACTION_TRIM` → 부분 손절(변경 없음) / `ACTION_SKIP` → **손절 안 함, 잔량 유지** / `ACTION_BLOCK` → 전량 청산(판정 불가, 안전측) — 세 갈래 모두 코드에서 확인함(TRIM/SKIP/전량 = `tp_sl_orchestrator.py:609 / :615 / :625`, 그리고 `:733 / :739 / :748`).

##### 🚨 위험 검토 — Fix 326 을 만지기 전에 반드시 읽을 것 (2026-09-03 실측)

**(가) 코드 주석이 지금 코드와 정반대다 — 속지 마라.**
`app/services/stage_trim.py:320-321` 에 이렇게 적혀 있다:

```
⚠️ 손절 경로는 SKIP 을 받으면 스스로 전량으로 떨어진다(손절은 반드시
   나가야 한다). 단계 진입 경로만 「그냥 진입」이 된다.
```

🚨 **이 주석은 Fix 326 이전 이야기이고, 지금은 틀렸다.** Fix 326 이 바로 그 「전량으로 떨어진다」를 없앴다 — 지금 손절 경로는 SKIP 을 받으면 **`return` 해서 아무것도 하지 않는다**(`tp_sl_orchestrator.py:615`, `:739`). 이 저장소가 반복해서 당한 함정(「주석은 정답을 적어 놨는데 코드가 안 함」)의 **부호만 뒤집힌 형태**다. 코드를 만질 사람은 **주석 말고 `tp_sl_orchestrator.py:615/739` 를 직접 볼 것.** (📌 다음 세션 작은 할 일: 이 주석 3줄을 현재 동작에 맞게 고치기. 이번 검토는 **문서만** 고쳤고 코드는 손대지 않았다.)

**(나) 🚨 `stage_keep_notional_usdt` 를 키우면 손절이 사실상 전면 중단된다.**

| 실측 | 값 |
|---|---|
| 허용 범위 | `0 < v ≤ 10000` (`stage_trim.py:176`) — **상한이 10,000 이다** |
| 목표 잔량(명목) | `keep_notional × 레버리지` (`stage_trim.py:294`) |
| 보유 명목 ≤ 목표 잔량이면 | `ACTION_SKIP` (`stage_trim.py:322-326`) → **Fix 326 이후 손절 자체를 건너뛴다** |

→ 예: `stage_keep_notional_usdt = 1000`, 레버 10 이면 목표 잔량 명목 **10,000 USDT**. 사실상 **모든 포지션이 SKIP** 이 되어 **손절이 하나도 나가지 않는다.** 기본값 10 에서는 최대 노출이 증거금 10 USDT 라 안전하지만, **이 값을 키우는 것은 「손절 끄기」와 같다.**
- 🚨 §6-3(P3)에서 이 키에 UI 를 붙일 때 **입력 상한을 코드 상한(10000)에 맞추지 말 것.** 화면에서는 **10~50 정도로 좁게 clamp** 하고, 그보다 큰 값은 경고와 함께 거부하는 편이 안전하다.
- 🚨 되돌리기: 값을 지우거나(행 삭제) `10` 으로 되돌리면 즉시 원복된다(재시작 불필요 — 매 호출마다 DB 를 읽는다).

**(다) 「최대 손실 10 USDT」는 격리(ISOLATED) 전제다.** 이 시스템은 모든 진입에서 `ensure_isolated_margin()` 을 부르지만(`execution_service.py:270`), 누군가 바이낸스 앱에서 그 심볼을 CROSS 로 바꿔 놓으면 그 전제가 깨진다. 「손절을 건너뛰어도 안전하다」는 판단의 **바닥이 격리 마진**이라는 점을 기억할 것.
- 🚨 기대를 뒤집은 테스트: `test_1단계_소액은_손절하지_않는다` — 원래 「전량 손절되어야 한다」였는데 사장님 사양과 **반대**였다(「첫진입이 10이라 손절없이 그냥 좋은 포지션에 2단계 300으로 진입」).
- 테스트: `tests/test_stop_loss_execution_path.py`(실서버 사고 2건 재현 포함) — 커밋 당시 16건, **2026-09-03 현재 17건**(Fix 327 이후 1건 추가). §7 ② 명령이 `62 passed` 를 내면 정상.
- 🔁 **교훈**: 부분 청산을 만들면 「남긴 것」이 **다음 사이클에 어떻게 취급되는지 반드시 따라가라.** 한 번의 부분 손절이 성공해도 다음 사이클이 지우면 사양은 구현되지 않은 것과 같다.

#### 4-3. Fix 327 상세 — 배선 위치와 5중 안전장치

```
backend/app/services/execution_service.py:188  start_stage1()
  ├ :207-228   Fix 310/325  chg24 게이트 (본보기)
  ├ :230-268   Fix 327      지지선 7점 게이트   ← 이번에 추가
  └ :270       ensure_isolated_margin()  ← 실주문 부수효과는 여기부터
```

| 안전장치 | 구현 위치 |
|---|---|
| ① 기본 OFF (`support_score_gate_enabled`) | `support_score.py:128 gate_enabled` |
| ② fail-open (조회/판정 실패는 통과) | `support_score.py:365, 401` + `execution_service.py:257-259` |
| ③ **지지선 접촉이 아니면 막지 않음** (판정식 표본 밖) | `support_score.py:397-398` |
| ④ 1H 데이터 없으면 판정 보류 | `support_score.py:289-290` |
| ⑤ 진행 중인 봉 잘라내기 | `support_score.py:371-372` (`kl[:-1]`) |
| 🚨 `trigger_next_stage` 에는 안 검 | 사다리 정지 방지 (Fix 203/235 전력) |

- 신설 파일: `backend/app/services/support_score.py` (403줄), 테스트 `backend/tests/test_support_score.py` **22건** (진입 경로 통합 154건, 전체 통과)
- 사전 검증(실 캔들 30심볼): 상승 +12~+49% → 6~7점 LONG / 하락 −8~−31% → 0~4점 SHORT·관망. **AKEUSDT(사장님 차트) = 1점 SHORT** — 급등 후 급락·보합을 정확히 잡았다.
- ⚠️ **확인 못 함**: 이 게이트는 실서버에서 **한 번도 실행된 적이 없다**(§1-3). 「한 번도 실행 안 된 분기는 런타임이 못 잡는다」(Fix 298 교훈).

---

### 5. `app/services/support_score.py` 7점 판정식 — 그대로 재현 가능한 표

#### 5-1. 1단계 — 지지선 찾기 `find_swing_low(lows)` (`support_score.py:220`)

| 상수 | 값 | 코드 |
|---|---|---|
| `LOOKBACK_BARS` | 96 | `:106` |
| `PIVOT_HALF_WIDTH` | 3 | `:107` |
| `EXCLUDE_RECENT` | 4 | `:108` |

```
가장 최근 i 부터 거꾸로 내려가며:
  left  = lows[i-3 : i]
  right = lows[i+1 : i+4]
  all(lows[i] < x for x in left) and all(lows[i] < x for x in right)  →  S = lows[i]
탐색 범위: max(3, n-96) ≤ i < n-4     (최근 4봉은 오른쪽 3봉이 없어 피벗 확정 불가)
없으면 (None, None) → 판정하지 않고 통과(fail-open)
```

#### 5-2. 2단계 — 접촉 판정 `is_touching(...)` (`support_score.py:244`)

| # | 조건 | 코드 | 불만족 시 사유 |
|---|---|---|---|
| 0 | `len(closes) >= 25` | `:256` | "데이터 부족" |
| — | `tol = max(0.002, 0.25 × ATR14/close)` | `:260` | (ATR 없으면 0.002) |
| 1 | `lows[-1] <= S × (1 + tol)` | `:263` | "지지선까지 안 내려옴" |
| 2 | `closes[-2] > S × (1 + tol)` | `:265` | "직전 봉이 이미 지지선 아래 (접촉이 아니라 이탈)" |
| 3 | `(close / max(highs[-24:]) − 1) × 100 <= −1.0` | `:270` | "…(고점권)" |

→ 셋 다 만족해야 **접촉**. 접촉이 아니면 score 는 계산해서 **로그에만 남기고 막지 않는다** (`:397-398`).

#### 5-3. 3단계 — 7점 채점 `compute_score(kl_15m, kl_1h)` (`support_score.py:279`)

전제: `len(kl_15m) >= 100` (`:287`), `len(kl_1h) >= 40` (`:289`). 아니면 **`None` = 판정 보류**.

| # | 규칙 id | TF | 정확한 판정식 | 코드 | 해당시 승률 | 미해당시 | Δ%p | d(A) / d(B) |
|---:|---|---|---|---|---:|---:|---:|---|
| 1 | `h1_macdh_pos` | 1h | `MACD_hist(12,26,9)[-1] > 0` | `:300` | 65.5% | 43.9% | **+21.6** | +0.688 / +0.211 |
| 2 | `h1_above_ema20` | 1h | `close[-1] > EMA20[-1]` | `:301` | 65.4% | 45.7% | **+19.7** | +0.514 / +0.223 |
| 3 | `h1_rsi12_ge_50` | 1h | `Wilder RSI(12) >= 50` | `:302-303` | 64.7% | 46.6% | **+18.1** | +0.445 / +0.185 |
| 4 | `m15_macdh_not_rising3` | 15m | 🚨 **`NOT ( hist[-1] > hist[-4] )`** (역방향) | `:310-312` | 61.5% | 42.9% | **+18.7** | −0.437 / −0.285 |
| 5 | `m15_rsi24_ge_45` | 15m | `Wilder RSI(24) >= 45` | `:313-314` | 62.7% | 46.1% | **+16.6** | +0.412 / +0.224 |
| 6 | `m15_drop96_ge_m15` | 15m | `(close[-1] / max(high[-96:]) − 1) × 100 >= −15.0` | `:315-317` | 61.6% | 41.9% | **+19.8** | +0.188 / +0.337 |
| 7 | `m15_above_ema50` | 15m | `close[-1] > EMA50[-1]` | `:318` | 67.7% | 50.0% | **+17.7** | +0.302 / +0.294 |

- **등가중 합** = `score` (0~7). 가중치를 붙여도 개선되지 않아 **등가중 채택**(단순 = 과적합 방어).
- 지표 구현: EMA `k=2/(n+1)`, 시드 = 첫 값(`:161-168`) / MACD hist = EMA12−EMA26 의 EMA9 뺀 값, **40봉 미만이면 None**(`:171-178`) / RSI = **Wilder**(`:181-198`) / ATR14 = 단순평균(`:201-213`).
- 🚨 4번 규칙은 **부호가 직관과 반대**다. 「이미 오르고 있으면 점수를 주지 않는다」. 이게 이 판정식의 핵심이다(§3-2).

#### 5-4. 4단계 — 결론 `decide(score, side)` (`support_score.py:327`)

| 방향 | 조건 | 기본값 | 설정 키 | 실측 |
|---|---|---|---|---|
| LONG | `score >= min_long` | **6** (`MIN_LONG_DEFAULT`, `:103`) | `support_score_min_long` (허용 0~7) | 승률 70.6% (n=80) |
| SHORT | `score <= max_short` | **1** (`MAX_SHORT_DEFAULT`, `:104`) | `support_score_max_short` (허용 0~7) | 승률 63.9% (n=67) |

🚨 **여기도 clamp 가 아니라 「기본값 복귀」다** (`support_score.py:134 _int_setting`, 2026-09-03 재확인). `support_score_min_long=9` 를 넣으면 7 로 깎이는 게 아니라 **기본 6 으로 되돌아간다** — 즉 **게이트가 느슨해지는 게 아니라 원래대로 돌아간다.** 로그 `[Fix327] support_score_min_long=9 범위밖(0~7) → 기본 6` 이 유일한 신호다. 값을 넣은 뒤 반드시 로그로 실제 적용값을 확인할 것.
| 그 외 방향 문자열 | — | 판정 안 함(통과) | — | `:341` |

전체 스위치: `support_score_gate_enabled` (`:99`) — `"1"/"true"/"on"/"yes"` 만 ON.

#### 5-5. 공용 진입점 `evaluate(db, bc, symbol, side)` (`support_score.py:348`) 흐름

```
gate_enabled 아니면 → (True, "", d)                       # 아무것도 안 함
get_klines(15m limit=200) / get_klines(1h limit=120)      # 실패 → fail-open 통과
kl15c = kl15[:-1] / kl1hc = kl1h[:-1]                     # 진행 중 봉 제거
find_swing_low → 없으면 fail-open 통과
is_touching → touching / why_t
compute_score → None 이면 fail-open 통과
decide(score, side, min_long, max_short)
  ├ 접촉 아님 → (True, "지지선 접촉 아님 … [n/7점]")       # 기록만
  └ 접촉      → (ok, why)                                  # 여기서만 실제로 막는다
예외 → fail-open 통과
```

---

### 6. 다음 할 일 — 우선순위와 시작 지점

> 🚨 **순서 주의 — 이 절의 명령을 돌리기 전에 §7 을 먼저 끝내라.** 아래는 전부 **VPS SSH** 또는 **로컬 클론**이 이미 준비돼 있다고 전제한다. 새 PC 라면 `local-env.md`(클론·파이썬) → `secrets.md`(SSH 키·`.env`) → **§7 ①②③** → 그다음이 이 절이다. §7 이 문서 뒤쪽에 있는 것은 참고용이라서가 아니라 **분량 때문**이다.

우선순위 근거: **① 이미 실자금에 영향을 주는 것 → ② 켜지 않으면 아무 효과도 없는 것 → ③ 사장님이 조작할 수 없는 것 → ④ 데이터가 안 쌓이는 것 → ⑤ 실측 근거가 확실한 개선 → ⑥ 실측이 반대인 것(재측정 먼저)**

| 순위 | 할 일 | 왜 지금 | 시작 파일 : 함수 | 위험 |
|---:|---|---|---|---|
| **P1** | **Fix 326 실검증** (손절 이벤트 시 잔량이 유지되는가) | 실자금 손절 경로를 바꿔놓고 **배포 후 이벤트 0건 = 증거 0** | `tp_sl_orchestrator.py:545 _execute_force_stop_loss` / `:686 _execute_stop_loss` — 로그 태그 `[Fix326]` | 🚨 잘못되면 손절이 **안 나간다** |
| **P2** | **Fix 327 게이트 실전 검증** (현재 OFF) | 코드는 배포됐으나 **한 번도 실행된 적 없음**. 「한 번도 실행 안 된 분기는 런타임이 못 잡는다」 | `support_score.py:348 evaluate` / 설정 `support_score_gate_enabled` | 🚨 켜면 **즉시 차단**한다 — 관찰 모드가 없다(아래 참조) |
| **P3** | **신설 스위치 UI/API** | 신설 키 **10개 전부 「쓰기(변경) 경로 0곳」** = 사장님이 켜거나 끌 방법이 DB 직접 쓰기뿐 (⚠️ 「grep 0건」은 §6-3 에서 **정정됨** — 7개는 읽기 전용 API 에 이미 있으나 **그 API 자체가 미커밋·미배포**) | `app/api/v1/strategy_suggestions.py:541 set_sajangnim_settings` 의 `fields` dict + `app/static/js/strategy-suggestions.js:1023 / :1095` | 저장 검증 실패가 **다른 필드까지 소실**시킨 전력(Fix 181) |
| **P4** | **6시간 잡 굶음 수정** (`chart_patterns` 0건) | 실측 재확인 — 오늘도 `chart_patterns = 0` | `app/workers/scheduler_runner.py:74` (`job_defaults` 신설) + `:520 chart_pattern_scan` + `:580 binance_changelog_monitor` | 🚨 되살려도 **진입엔 안 쓰인다** + 한 사이클 **API 200회**(IP ban 418 전력) |
| **P5** | **적응 TP 를 기본·OBV 경로에도** | `adaptive_tp` 호출처가 **`auto_bb_breakdown_worker` 한 곳뿐** (grep 결과). 주력인 볼밴 분할 68건은 못 받는다 | `app/workers/auto_bb_breakdown_worker.py:1826-1857`(본보기) → `pump_split_entry_worker.py:1040` / `surge_ladder_entry.py:311` / `scheduled_entry_worker.py:231` | TP 를 낮추면 큰 파도를 **조기 익절**하고 되돌릴 수 없다 |
| **P6** | **LONG 손절 −5% → −10%** | 🚨 **실측이 정반대다**(아래 6-6). 재측정 먼저 | `app/workers/auto_long_at_bottom_worker.py:164 LONG_FORCE_SL_ROI` (+ `auto_bb_breakdown_worker.py:1353, :1981`, `strategy_service.py:578`) | 🚨 Fix 253 을 되돌리는 변경 |
| (추가 후보) | **BOTTOM(저점LONG) 끄기 또는 조건 좁히기** | 156건 **−1,049.0** PF 0.28. 빼면 자동이 **흑자**(+245.4, 앞뒤 절반 모두 양수) | `app/workers/auto_long_at_bottom_worker.py` (워커 스위치) / `PATTERN_B_MIN_CHG` **`:139`** (`:140` 은 `PATTERN_B_MAX_CHG`) | **사장님 결정 사안** — 사상 변경이므로 임의로 끄지 말 것 |

#### 6-1. P1 — Fix 326 실검증 절차

「부분 손절 직후 몇 분 안에 전량 청산이 뒤따르지 않는가」를 본다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 24h --tail 200000 --no-log-prefix scheduler api 2>/dev/null | grep -E "\[Fix31[89]\]|\[Fix326\]" | tail -60'
```

🚨🚨 **이 명령을 돌리기 전에 반드시 읽을 것 — 그냥 보면 「Fix 326 이 고장났다」고 오독하게 된다.**

- **로그 타임스탬프는 UTC 다** (컨테이너 TZ. `date -u` 와 같은 시계다. KST = +9h).
- **배포 시각은 `2026-09-03 08:51 UTC`**(= 17:51 KST, §1-1). 그보다 **앞선 줄은 전부 옛 바이너리**가 찍은 것이다.
- 2026-09-03 09:40 UTC 에 실제로 돌려 보니 `--since 24h` 창 안에 **`전량 손절 (skip)` 이 3건 나온다**(07:44:15 UAI #2089 / 08:00:22 MARSCOIN #2091 / 08:02:09 HEMI #2095). **이건 Fix 326 이 고친 바로 그 버그의 원본 증거**이고, 셋 다 배포 **이전**이다. 실패로 세지 말 것.
- 따라서 **판정은 `08:51 UTC` 이후 줄로만** 한다. 배포 이후만 보려면 `--since` 를 배포 시각 기준으로 좁힌다:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2026-09-03T08:52:00Z --tail 200000 --no-log-prefix scheduler api 2>/dev/null | grep -E "\[Fix31[89]\]|\[Fix326\]" | tail -60'
```

판정 기준 (**배포 시각 이후 줄만**):

| 로그 | 뜻 | 기대 |
|---|---|---|
| `[Fix319] … **부분 손절**: N 청산 / M 잔여` (강제손절 경로) / `[Fix318] … 부분 손절: …` (일반 손절 경로) | 부분 손절 성공 | 발생해도 됨 |
| `[Fix326] … 잔량 유지 — 손절하지 않음 (skip)` | **Fix 326 이 작동한 증거** | ✅ 이게 나와야 한다 |
| 같은 `#id` 에 대해 부분 손절 **직후** `전량 손절 (skip)` | Fix 326 미작동 | ❌ **배포 이후 줄에** 나오면 안 된다 |

> 태그 대응(`tp_sl_orchestrator.py` 실측): `_execute_force_stop_loss`(:545) → **`[Fix319]`**, `_execute_stop_loss`(:686) → **`[Fix318]`**. 번호가 함수 순서와 반대라 헷갈리기 쉽다.
> `[Fix326]` 은 `logger.info` 다. 컨테이너 로그 레벨은 `app/core/logging.py` 에서 **INFO** 로 고정돼 있으니 레벨 때문에 안 보일 일은 없다.
> **아무 줄도 안 나오면 「고장」이 아니라 「아직 손절 이벤트가 없음」이다.** 그때는 아래 DB 확인으로 최근 상태 변화 자체가 있었는지부터 본다.

> 🚨🚨 **최악의 시나리오와 즉시 되돌리는 법 (위험 검토 2026-09-03 추가)**
>
> P1 의 위험은 「손절이 **안** 나간다」이다. 아래가 보이면 **판단을 미루지 말고 즉시 되돌린다.**
>
> **위험 신호**: `[Fix326] … 잔량 유지 — 손절하지 않음` 이 **같은 `#id` 에 계속 반복**되는데 그 포지션의 손실이 **커지고 있다** (= 남은 잔량이 「10 USDT 급 소액」이 아니라는 뜻).
>
> **즉시 되돌리기 — 재시작 불필요, 다음 사이클부터 옛 동작(전량 손절)으로 돌아간다**:
>
> ```bash
> # 🚨 운영 DB 쓰기. 부분 손절 기능 자체를 끈다 = 손절이 다시 전량으로 나간다.
> ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
> from app.core.database import SessionLocal
> from app.models.system_setting import SystemSetting
> db = SessionLocal()
> row = db.get(SystemSetting, \"stage_trim_before_next_enabled\")
> if row:
>     row.value = \"0\"
>     db.commit()
> print(\"stage_trim_before_next_enabled =\", (row.value if row else \"(행 없음 = OFF)\"))
> "'
> ```
>
> - ✅ **왜 이게 옳은 되돌리기인가**: `trim_enabled` 가 False 면 `compute_trim` 자체를 부르지 않아 `ACTION_SKIP` 이 나올 수 없고, 손절은 **전량**으로 나간다(`tp_sl_orchestrator.py:603`, `:727` 의 `if trim_enabled(...)` 가 통째로 건너뛰어진다). **`git revert` 도 재배포도 필요 없다.**
> - 🚨 **`git revert 1d04598` 로 되돌리지 마라** — §4 의 경고대로 그건 §4-2 의 실서버 사고(부분 손절 12~300초 뒤 전량 청산)를 **되살린다.**
> - ⚠️ **다시 켜기**: 같은 명령에서 `"0"` → `"1"`. 켜기 전에 왜 껐는지 로그를 남길 것.

같은 전략이 살아남았는지 DB 로도 확인:

> 🚨 **이 문서의 이전 판에 있던 `now() - interval %(w)s` 는 돌지 않는다.** 2026-09-03 실행 결과 `psycopg2.errors.SyntaxError: syntax error at or near "s"`. Postgres 에서 `interval` 뒤에는 **리터럴만** 올 수 있어 바인딩 파라미터를 그대로 붙일 수 없다. 아래처럼 **`cast(:w as interval)`** 로 써야 한다. (그리고 SQLAlchemy `text()` 의 바인딩 표기는 `%(w)s` 가 아니라 **`:w`** 다.)
> 🚨 쿼리가 한 번 실패하면 그 세션은 죽는다 — **다음 쿼리 전에 `db.rollback()`** 을 부를 것.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
sql = text(\"select id, symbol, side, status, current_stage, updated_at from strategy_instances where updated_at > now() - cast(:w as interval) order by updated_at desc limit 30\")
for r in db.execute(sql, {\"w\": \"24 hours\"}).fetchall():
    print(r)
"'
```

> ⚠️ `updated_at` 은 **가격 갱신에도 찍힌다** — 2026-09-03 09:42 UTC 실행에서 `STAGE1_OPEN` 8건이 전부 **동일한 초**로 나왔다(일괄 갱신). 「배포 후 새 진입이 있었는가」를 보려면 `updated_at` 이 아니라 **`created_at`** 을 봐야 한다:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
sql = text(\"select id, symbol, side, status, created_at from strategy_instances where created_at > cast(:t as timestamptz) order by created_at desc limit 20\")
rows = db.execute(sql, {\"t\": \"2026-09-03T08:51:00Z\"}).fetchall()
print(\"배포 이후 생성 건수:\", len(rows))
for r in rows: print(r)
"'
```

2026-09-03 09:45 UTC 실측 = **0건**. 즉 배포 후 55분간 신규 1단계 진입이 없었다는 §1-3 의 진술은 그 시점까지 유효하다. **`:t` 값을 새 배포 시각으로 바꿔서 다시 재라.**

#### 6-2. P2 — Fix 327 게이트 켜기 / 끄기

🚨 **이 명령은 운영 DB 쓰기다. 실자금 진입 판정이 즉시 바뀐다. 사장님이 판단해 실행할 것.**
🚨 **관찰 모드(막았을 것만 로그)가 구현돼 있지 않다.** 현재 구현은 켜는 즉시 `raise ValueError` 로 **실제 차단**한다 (`execution_service.py:260-265`). Fix 247 이 쓴 「먼저 로그만 남기고 사장님이 켠다」 방식을 원하면 **먼저 그 모드를 만들어야 한다.**

> 확인함(2026-09-03 재검증): 게이트가 OFF 면 `evaluate` 가 **첫 줄에서 그냥 통과**하고 점수 계산조차 하지 않는다(§5-5, `support_score.py:128`). 그래서 **켜기 전에는 「몇 점이 나왔을지」를 알 방법이 로그에도 없다.** 이게 관찰 모드가 필요한 이유다.
> 🚨 반면 `GET /api/v1/terminal/symbol-status` 는 **`support_gate_enabled`(on/off)만** 돌려주고 **점수는 돌려주지 않는다**(`terminal.py:1029-1035`). 「터미널 화면에서 미리 볼 수 있다」고 **오해하지 말 것** — 미리 보이는 것은 24h 순위 게이트의 통과 여부뿐이다(§6-3). 🚨 게다가 그 라우터는 **운영 VPS 에 배포조차 돼 있지 않다**(실측: VPS `router.py` 에 `terminal` 0건 → **404**). §6-3 의 「커밋 안 됨」 경고를 볼 것.
> 💡 위험을 낮추는 순서: **관찰 모드를 먼저 만든다 → 하루 로그를 본다 → 켠다.** 지금 바로 켜면 첫 차단이 실자금 진입을 막는 순간에 처음 실행된다.

켜기:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
db = SessionLocal()
row = db.get(SystemSetting, \"support_score_gate_enabled\")
if row: row.value = \"1\"
else: db.add(SystemSetting(key=\"support_score_gate_enabled\", value=\"1\", description=\"Fix 327 지지선 7점 게이트\"))
db.commit()
print(\"support_score_gate_enabled =\", db.get(SystemSetting, \"support_score_gate_enabled\").value)
"'
```

끄기 (되돌리기):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
db = SessionLocal()
row = db.get(SystemSetting, \"support_score_gate_enabled\")
if row: row.value = \"0\"; db.commit()
print(\"support_score_gate_enabled =\", (row.value if row else \"(행 없음 = OFF)\"))
"'
```

켠 뒤 관찰 (차단·통과 사유가 전부 로그로 나온다):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 3h --tail 100000 --no-log-prefix scheduler api 2>/dev/null | grep "\[Fix327\]" | tail -60'
```

> 참고: 재시작 없이 적용된다 — `gate_enabled` 가 매 호출마다 DB 를 읽는다(`support_score.py:128-131`).
> 임계값만 완화하고 싶으면 같은 방식으로 `support_score_min_long`(0~7) / `support_score_max_short`(0~7) 를 넣는다.

##### 🚨 켜기 전에 — 위험 검토 담당이 추가한 3가지 (2026-09-03 실측)

1. 🚨 **차단이 로그에 「❌ 실 진입 실패」로 보인다. 고장으로 오진하지 말 것.**
   게이트는 `start_stage1` 안에서 `raise ValueError("[Fix327] … 진입 차단: …")` 를 던지고, 호출자들은 그것을 **일반 예외로 받아** 「실 진입 실패」로 찍고 **좀비 정리 경로**로 넘어간다 (`auto_bb_breakdown_worker.py:2036-2042` / `surge_ladder_entry.py:312-313`).
   → 켠 뒤에는 **① 전략 인스턴스가 만들어졌다가 곧바로 STOPPED 로 남는 건수가 늘고 ② 「실 진입 실패」 경고가 늘어난다.** 이건 **정상이고 설계대로**다. 진짜 고장과 구별하려면 **같은 줄에 `[Fix327]` 이 있는지**를 보면 된다.
   ✅ 확인함: 호출자 8곳이 전부 `try/except` 로 감싸고 있어 **게이트가 워커를 죽이지는 않는다**(다른 심볼 처리는 계속된다).
2. ✅ **켜기 전에 현재 값을 먼저 적어 둬라** — 되돌릴 기준점이다. 위 §1-2 조회 명령을 한 번 돌려 출력을 남긴 뒤 켠다. (지금은 **행 자체가 없음** = OFF 가 기준점이다.)
3. 🚨 **켠 뒤 30분 안에 「진입이 통째로 멈추지 않았는지」를 확인하라.**
   이 게이트는 지지선 **접촉일 때만** 막지만, 접촉 시 score 2~5 구간은 **LONG·SHORT 양쪽 다 막힌다**(LONG 은 ≥6, SHORT 는 ≤1). 진입이 0 이 되면 즉시 위 「끄기」로 되돌린다 — **끄기는 재시작 없이 다음 호출부터 적용된다.**

```bash
# 켠 뒤 관찰: 차단 건수 vs 통과 건수 (숫자만 빠르게)
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 3h --no-log-prefix scheduler api 2>/dev/null | grep -c "\[Fix327\].*진입 차단"'
```

#### 6-3. P3 — 신설 스위치 UI/API

**실측 (2026-09-03 재검증에서 정정됨)**: 아래 10개 키는 **쓰기(설정 변경) 경로가 0곳**이다 — 사장님이 켜거나 끌 방법이 **DB 직접 쓰기뿐**이라는 결론은 그대로다.

🚨 **다만 「grep 결과 전부 0」은 틀렸다.** 재검증하니 7개 키가 **읽기 전용으로는 이미 API 에 노출돼 있다** — 🚨 **단, 아래 「커밋 안 됨」 경고를 먼저 읽을 것**:

- `app/api/v1/terminal.py:942 GET /api/v1/terminal/symbol-status?symbol=<심볼>` (`router = APIRouter(prefix="/terminal")`, `app/api/router.py:49` 에서 등록)
- 돌려주는 것: `chg24_gate.{enabled,mode,top_n,min_abs,passes,reason}` (`:1000-1027`) / **`support_gate_enabled`** (`:1029-1035`) / `trim.{enabled,keep_notional_usdt}` (`:1037-1044`) / `reentry` (Fix 301)
- 즉 `entry_chg24_gate_enabled` · `entry_chg24_gate_mode` · `entry_rank_top_n` · `entry_min_abs_chg24` · `support_score_gate_enabled` · `stage_trim_before_next_enabled` · `stage_keep_notional_usdt` **7개는 SSH 없이도 상태를 볼 수 있다.**
- 이 라우터는 「모름」을 `passes=null` 로 주고 `false` 로 뭉개지 않는다(2026-08-28 fail-OFF 사고 반영). 화면을 만들 때 이 규약을 깨지 말 것.

여전히 **읽기조차 없는 것**: `support_score_min_long` / `support_score_max_short` / `adaptive_tp_enabled` / `confluence_gate_enabled` / `force_sl_unlock_unreachable_stage`.

> 🔁 **교훈**: 「grep 0건」이라고 적을 때는 **어떤 디렉터리에서 무슨 패턴으로** 쟀는지 같이 적어라. 위 5개 키는 `terminal.py:954-955` 주석에 문자열로 실재해서, 새 세션이 grep 하면 곧바로 문서와 어긋난다.

##### 🚨🚨 위 터미널 API 는 **커밋되지 않았다 — 운영에도 GitHub 에도 없다** (2026-09-03 위험 검토 실측)

이 한 줄을 놓치면 새 PC 에서 **3,666줄이 통째로 사라진다.**

| 확인 | 명령 | 결과 |
|---|---|---|
| 저장소에 추적되는가 | `git ls-files backend/app/api/v1/terminal.py` | **출력 없음 = 추적 안 됨** |
| 작업트리 상태 | `git status --porcelain` | `?? backend/app/api/v1/terminal.py` (1,185줄) / `?? backend/app/static/perp-terminal.html` (2,481줄) / ` M backend/app/api/router.py` (터미널 라우터 등록 2줄) |
| **운영 VPS 에 있는가** | `ssh … 'grep -c "terminal" backend/app/api/router.py'` | **`0`** — VPS `router.py` 에 terminal 라우터가 **등록돼 있지 않다** |
| VPS 파일 | `ssh … 'ls backend/app/api/v1/terminal.py'` | **`No such file or directory`** |
| 백업(`docs/handoff/wip-backup-2026-09-03/`)에 들어 있는가 | `find … -name terminal.py` | **없음.** 백업은 `main` / `charming-albattani` / `loving-rhodes` **3개 worktree 만** 담았고 **이 worktree(`infallible-euler-6dc297`)는 빠져 있다** |

**그래서 실제로는 이렇다:**

1. 🚨 **운영 서버에서 `GET /api/v1/terminal/symbol-status` 는 404 다.** 「SSH 없이도 상태를 볼 수 있다」는 **지금 사장님에게 해당되지 않는다.** 배포하려면 먼저 커밋·푸시하고 VPS 에 배포해야 한다.
2. 🚨 **새 PC 에서 GitHub 을 클론하면 이 세 파일 변경은 따라오지 않는다.** `terminal.py` + `perp-terminal.html` + `router.py` 수정이 **영구 소실**된다.
3. ✅ **살리는 방법 (사무실 PC 에서 먼저 할 것 — 새 PC 로 가기 전)**: 아래 중 하나.

```bash
# (A) 권장 — 커밋해서 GitHub 으로 보낸다. 문서·화면 파일이라 배포와 무관하게 안전하다.
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" \
  && git add backend/app/api/v1/terminal.py backend/app/static/perp-terminal.html backend/app/api/router.py \
  && git status --short           # ← 무엇이 담겼는지 눈으로 확인하고 나서 커밋
```

```bash
# (B) 커밋하고 싶지 않으면 최소한 백업 폴더에 복사해 둔다 (파괴적 명령 없음).
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" \
  && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/api/v1 \
  && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/static \
  && cp backend/app/api/v1/terminal.py       docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/api/v1/ \
  && cp backend/app/static/perp-terminal.html docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/static/ \
  && git diff backend/app/api/router.py > docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/router.patch
```

> 🚨 **절대 하지 말 것**: `git stash`, `git reset --hard`, `git checkout .`, `git clean -fd`.
> 이 저장소는 worktree 를 공유하고, 위 세 파일은 **추적조차 안 되는 상태**라 그 명령 하나로 **경고 없이 즉시 소멸**한다. 되돌릴 방법이 없다 (`claude-state.md:338-339` 와 같은 경고).
>
> 🚨 **배포까지 하려면**: 커밋·푸시한 뒤 **VPS 에서 `git pull` + 컨테이너 재시작**이 필요하다. 재시작은 **사장님 몫**이다(실자금이 돌고 있다). 커밋만 해서는 운영 404 가 그대로다.

| 키 | 관련 Fix | 기본값 |
|---|---|---|
| `support_score_gate_enabled` / `support_score_min_long` / `support_score_max_short` | 327 | OFF / 6 / 1 |
| `entry_chg24_gate_enabled` / `entry_chg24_gate_mode` / `entry_rank_top_n` | 310, 325 | ON(DB) / rank / 50 |
| `adaptive_tp_enabled` | 299 | OFF (DB 엔 1) |
| `stage_trim_before_next_enabled` | 304~326 | OFF (DB 엔 1) |
| `confluence_gate_enabled` | 247 | OFF (DB 엔 true) |
| `force_sl_unlock_unreachable_stage` | 235 | OFF |

착수 지점: `app/api/v1/strategy_suggestions.py:541 @router.put("/sajangnim-settings")` 안의 `fields` dict(`:552~579`)에 `(payload_key, sanitizer)` 를 추가하고, `app/api/v1/strategy_suggestions.py:251 @router.get("/sajangnim-settings")` 에 읽기를 추가한 뒤, `app/static/js/strategy-suggestions.js:1023`(읽기) / `:1095`(저장)에 입력칸을 붙인다.

🚨 주의 5가지:
1. **`?v=` 캐시 버스터** — 정적 파일을 고치면 반드시 갱신(과거 18개가 낡아 화면만 옛 코드였던 전력).
2. **검증 실패 시 `HTTPException(400)`** 으로 던질 것. `return {"error": …}` 는 HTTP 200 이라 프론트가 「저장 완료」를 띄우고 **그 요청의 다른 필드까지 소실**된다(Fix 181, `:637-644` 주석).
3. **HTML 기본값이 DB 를 덮는 사고 전력**(Fix 188~194) — 화면 기본값과 코드 기본값을 반드시 일치시킬 것.
4. 🚨 **화면에 붙이는 순간 이 키들은 「한 번의 오타로 실자금 동작이 바뀌는 스위치」가 된다.** 특히 `stage_keep_notional_usdt` 는 **코드 상한이 10,000** 이라 큰 값을 넣으면 **손절이 사실상 전면 중단**된다(§4-2 (나)). **화면에서는 10~50 으로 좁게 clamp** 하고, 그 밖의 값은 저장을 거부할 것.
5. 🚨 **끄는 방법을 켜는 방법과 같은 화면에 같이 놓을 것.** 이 저장소는 「0 을 넣으면 20 으로 둔갑해 끄기가 작동 안 하던」 사고(Fix 107~110)를 겪었다. 저장 후 **DB 에서 다시 읽어 화면에 되비추는지** 반드시 확인하라 — 「저장했다」는 「저장됐다」가 아니다.

#### 6-4. P4 — 6시간 잡 굶음

원인 두 겹 (§2-4). 고칠 자리:

| 무엇 | 어디 | 어떻게 |
|---|---|---|
| misfire 1초 | `app/workers/scheduler_runner.py:74` | `BlockingScheduler(timezone="Asia/Seoul", job_defaults={"misfire_grace_time": 300, "coalesce": True})` — ⚠️ **잡 전체에 영향**. 2026-09-03 실측으로 `scheduler.add_job` 이 **62회**(무조건 등록 60 + 조건부 2)다: `grep -c "^    scheduler\.add_job" app/workers/scheduler_runner.py`. 먼저 어떤 잡이 미스파이어를 재실행하면 위험한지 확인할 것 |
| 6시간 주기 자체 | `:520 chart_pattern_scan`, `:580 binance_changelog_monitor` | 주기를 **≤4시간**으로 낮추거나 `CronTrigger` 로 고정 시각화. **72시간에 57회 재시작**하는 환경에선 6시간 잡이 구조적으로 굶는다 |
| 재시작 원인 | ⚠️ **확인 못 함** | 배포인지 크래시 루프인지 미확인. `[scheduler] another node is leader; exiting` 이 15초에 5회 연속 찍힌 구간이 있어 **리더 경합 루프** 가능성 (감사 부록 B-3) |
| 부수 결함 | `pattern_collector.py:28`(수집 `>=60`) vs `pattern_detector.py:33-34`(탐지 `<100` 이면 **조용히** 빈 리스트) | 60~99봉 심볼은 수집만 되고 탐지가 통째로 스킵된다. 로그 없음 |
| 🚨 **진입에 안 쓰임** | `ChartPattern` 읽기 = 쓰기 2곳 + 화면 2곳, **진입 0곳** | 스케줄만 고치면 **Fix 247 과 같은 자리**가 된다. 반드시 같이 고칠 것 |

> 🚨🚨 **위험 검토 — 위 표 첫 줄(`job_defaults` 전역 설정)을 그대로 하지 마라.**
>
> `BlockingScheduler(..., job_defaults={"misfire_grace_time": 300})` 는 **등록된 62개 잡 전부**의 동작을 한 번에 바꾼다. 이 스케줄러는 **72시간에 57회 재시작**하는 환경이고, 재시작 직후에는 **1분·2분 주기 진입/손절/청산 잡들이 전부 「놓친 실행」 상태**다. 지금은 그것들이 `misfire_grace_time=1초` 때문에 **조용히 폐기**되고 있는데, 300초로 늘리면 **부팅하자마자 수십 개 잡이 한꺼번에 발사된다.**
> - → **바이낸스 API 버스트 → 418 IP ban**(Fix 117/122 와 정확히 같은 모양). ban 이 나면 **손절도 못 나간다.**
> - → 진입 워커가 한 번에 몰려 돌면 **의도치 않은 동시 진입**이 날 수 있다.
> - `coalesce: True` 는 「밀린 여러 번을 한 번으로」 합쳐줄 뿐, **여러 잡이 동시에 뜨는 것**은 막지 못한다.
>
> ✅ **안전한 방법 — 전역이 아니라 그 두 잡에만 건다** (`add_job` 은 잡별 `misfire_grace_time` 을 받는다):
>
> ```python
> # scheduler_runner.py — chart_pattern_scan / binance_changelog_monitor 각각의 add_job 에만 추가
> misfire_grace_time=3600,   # 이 잡만. 전역 job_defaults 는 건드리지 않는다.
> ```
>
> 이러면 **다른 60개 잡의 부팅 시 동작이 한 글자도 바뀌지 않는다.** 전역 변경은 되돌리기도 어렵다(무엇이 달라졌는지 로그로 분리되지 않는다).
> 🚨 **되돌리는 법**: 이건 **코드 변경**이라 DB 토글로 못 되돌린다 → `git revert` + push + VPS `git pull` + **재시작(사장님)**. 그래서 P4 는 **P1·P2 를 끝낸 뒤**에 손대는 것이 맞다.

수동으로 한 번 돌려볼 수 있는 경로(⚠️ **DB 쓰기 + 바이낸스 API 약 200회** — IP ban 전력 Fix 117/122):

🚨 **주의 — `curl -X POST http://159.65.137.250/api/v1/chart-patterns/scan-now` 는 그냥은 안 된다.**
이 엔드포인트는 `user_id: int = Depends(get_current_user_id)` 가 붙어 있어(`app/api/v1/chart_patterns.py:124-128`) **JWT 없이는 401** 이다. 2026-09-03 실측:

```
$ curl -s http://159.65.137.250/api/v1/chart-patterns/summary
{"detail":"Not authenticated"}          # HTTP 401
```

토큰을 받아오려면 사장님 로그인 계정이 필요하다(`POST /api/v1/auth/token`, form-encoded). **비밀번호를 이 문서나 채팅에 적지 말 것.**
토큰 없이 같은 일을 하려면 **스케줄러가 부르는 함수를 컨테이너 안에서 직접 부른다** — `scheduler_runner.py:515-518` 과 동일한 코드다:

```bash
# 🚨 실행 전 사장님 승인 필요 — 바이낸스 API 약 200회 연속 호출 + chart_patterns DB 쓰기
# 🚨 IP ban(418) 전력이 있다(Fix 117/122). 한 번만, 관찰하면서 돌릴 것.
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.agents.chart_pattern_learning_team.team_lead import ChartPatternLearningTeamLead
with SessionLocal() as db:
    print(ChartPatternLearningTeamLead().run_full_scan(db, decrypt_text, top_n=100))
"'
```

🚨 **위험 검토 담당의 보충 (2026-09-03 실측) — 위 스캔을 돌리기 전에**

| 항목 | 실측 | 뜻 |
|---|---|---|
| 실제 호출 수 | `get_24hr_ticker()` **1회** + `get_klines(4h, limit=200)` **최대 100회** = **≈101 요청** (`pattern_collector.py:20-33` 수집 / `:34` 심볼 목록) | 「200회」는 **요청 수가 아니라 가중치**에 가깝다. 4h/limit200 은 요청당 가중치 2 → **총 ≈205** |
| 지연 없음 | `team_lead.py:68` `for sym in symbols:` — **sleep 이 하나도 없다** | 101 요청이 **연달아** 나간다. IP ban(418) 이 바로 이 모양에서 났다(Fix 117/122) |
| 🚨 **부담을 줄이려면** | `top_n=100` 을 **`top_n=10` 으로 먼저** 돌려 본다 | 같은 코드 경로를 **1/10 비용**으로 검증할 수 있다. 잘 돌면 그때 100 으로 올린다 |
| 🚨 **되돌리는 법** | **없다 — `chart_patterns` 에 행이 쌓이고 지우는 명령은 이 문서에 싣지 않는다** | 운영 DB 를 **DELETE 하는 명령을 문서에 두지 않는 것이 의도**다. 이 스캔은 **읽기 전용이 아니다**. 그래서 「사장님 승인」이 필요하다 |
| ✅ 안전한 점 | 이 잡은 **주문을 만들지 않는다**(패턴 탐지·저장·결과 갱신뿐) | 자금이 나가지는 않는다. 위험은 **IP ban 과 DB 쓰기**뿐이다 |

> 🚨 **IP ban 이 나면 자동매매 전체가 멈춘다.** 이 시스템은 **하나의 계정·하나의 IP** 로 진입·손절·청산을 전부 처리한다. 418 을 맞으면 **손절도 못 나간다.** 「패턴 데이터를 채우려다 손절을 못 하는」 교환은 절대 하지 말 것 — 그래서 P4 는 **P1·P2 다음**이다.
> ✅ **돌리기 좋은 때**: 포지션이 적을 때(지금은 `STAGE1_OPEN` 8건). 포지션이 많은 날에는 돌리지 마라.

돌린 뒤 결과 확인(읽기 전용):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"chart_patterns:\", db.execute(text(\"select count(*) from chart_patterns\")).scalar())
"'
```

현재 상태 재확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 72h --tail 400000 --no-log-prefix scheduler 2>/dev/null | grep -c "interval\[6:00:00\].*Running job"'
```

🚨 **`--since 72h` 라고 써도 72시간이 나오지 않는다.** 2026-09-03 09:50 UTC 실측: 이 명령이 실제로 훑는 로그의 **가장 오래된 줄이 `2026-09-02 14:45 UTC`** = 약 **19시간분**뿐이다(컨테이너 재생성 시 로그가 함께 사라진다). 먼저 이걸 확인하고 해석할 것:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 72h --tail 400000 --no-log-prefix scheduler 2>/dev/null | head -1 | cut -c1-30'
```

- **재현되는 것**: `interval[6:00:00]` **Running job = 0**. 2026-09-03 09:50 UTC 재실측에서도 **0** 이었다 = 핵심 주장은 살아 있다.
- **재현되지 않는 것**: 감사 당시의 「missed 18」·「72시간에 57회 재시작」. 같은 시각 재측정은 **missed 3** 이었다 — 로그 창이 19시간으로 줄었기 때문이다. **숫자가 다르다고 감사가 틀린 게 아니다.** 개수를 다시 인용하려면 위 `head -1` 로 **실제 창 길이를 먼저 재고** 함께 적을 것.

#### 6-5. P5 — 적응 TP 를 다른 경로에도

**실측 (grep)**: `adaptive_tp` 를 import 하는 곳은 `app/workers/auto_bb_breakdown_worker.py:1827` **한 곳뿐**이다. 즉 `adaptive_tp_enabled='1'` 인데도 아래 경로는 여전히 고정 TP 를 쓴다.

| 경로 | 1단계 발주 위치 | 적응 TP |
|---|---|---|
| v219 사다리 (`_create_auto_bb_strategy`) | `auto_bb_breakdown_worker.py:2029` | ✅ 적용됨 (`:1826-1857`) |
| **볼밴 분할** (`pump_split`, 주력 68건) | `pump_split_entry_worker.py:1040` | ❌ |
| 급등 사다리 | `surge_ladder_entry.py:311` | ❌ |
| 예약 진입 | `scheduled_entry_worker.py:231` | ❌ |
| 청산 후 재진입 / 사다리 재시작 | `auto_reentry_worker.py:163` / `ladder_restart_worker.py:310` | ❌ |
| 화면 수동 시작 | `api/v1/strategies/control.py:47` | ❌ (수동은 제외가 맞을 수 있음 — 사장님 판단) |

근거 숫자(`adaptive_tp.py` 헤더): 구간별 기대값에서 **TP15 가 최선인 구간은 `|24h| 15~30%` 하나뿐**(+0.51)이고 나머지는 **−0.94 ~ −4.30**. 설계 R=3.00 인데 실효 R=1.01 이 된 원인이다.
⚠️ 이 측정은 **손절 ROI −10% 를 가정**했다. 현재 자동 LONG 실운영은 **−5%**(P6 참조)이므로 **손절을 바꾸면 이 표를 다시 재야 한다.**

#### 6-6. P6 — 🚨 「LONG 손절 −5% → −10%」는 실측과 반대다

| 근거 | 내용 |
|---|---|
| `auto_long_at_bottom_worker.py:141-164` (Fix 253, 2026-09-01) | **10% → 5% 로 조인 것**이 최근 변경이다. 「LONG 이 이틀 연속 승자 0명(08-31 12건 0% / 09-01 11건 0%)」, 「이익 중인 LONG 13건의 최저 ROI 가 −0.1~−4.3% = **−5% 를 건드린 승자가 한 건도 없다**」, 「느슨한 손절이 승률을 올린 게 아니라 **잃는 크기만 2배로 키웠다**」 |
| `REGIME_REAL_TRADE_VALIDATION` §2-3 | BOTTOM(저점LONG)의 **최대손실 중앙값 −5.02%** vs TOP(정점SHORT) −1.48%. 손절을 늘리면 이 꼬리가 그대로 커진다 |
| 반대쪽 근거 | `adaptive_tp` 기대값 표가 **SL −10% 가정**이므로, TP 를 3%로 낮추면서 SL 은 −5% 로 두면 표의 전제와 어긋난다 |

> **권고**: 값을 바꾸기 전에 **재측정**한다 — 「현재 이익 중인 LONG 이 −5% 아래로 간 적이 있는가」(Fix 253 주석이 지정한 그 질문). 바꾸기로 하면 **한 줄만** 고치면 된다: `auto_long_at_bottom_worker.py:164 LONG_FORCE_SL_ROI = Decimal("5")` → `Decimal("10")`.
> 🚨 다만 같은 −5% 가 **네 군데에 흩어져 있다**: `auto_long_at_bottom_worker.py:164`(LONG 전용 상수) / `auto_bb_breakdown_worker.py:1353`·`:1981`(하드코딩 `Decimal("5")`) / `strategy_service.py:578`(모든 신규 인스턴스 기본값). **한 곳만 고치면 방향에 따라 손절이 달라진다.** 설정으로 빼는 편이 낫다.
> 🚨 그리고 `spec_audit_worker.py:109-119` 가 「Fix 49 SL −5%」를 **누락 검사**하고 있다. 값을 바꾸면 이 감사 워커도 같이 봐야 한다.

---

### 7. 새 세션이 처음 30분에 할 일 (순서대로)

> 🚨 **새 PC 라면 아래 명령은 그대로는 하나도 안 돈다. 먼저 `secrets.md` 와 `local-env.md` 를 끝내고 올 것.**
> - **경로**: 아래 경로는 `local-env.md` §2 가 지정한 **메인 클론 위치**(`/c/Users/user/바이낸스/binance-auto-trader`)다. 다른 곳에 클론했으면 그 경로로 바꿔 읽을 것. 🚨 옛 PC 는 워크트리(`.claude/worktrees/infallible-euler-6dc297`)에서 작업했지만 **워크트리는 `git clone` 에 딸려오지 않는다**(`local-env.md` §9) — 새 PC 에서는 그냥 `main` 을 보면 된다. 이 세션 작업은 **전부 `origin/main`(= `e51d9a8`)에 있다**(실측 확인).
>   🚨 **정정(위험 검토 2026-09-03)**: 「이 세션 작업은 전부 `main` 에 있다」는 **틀렸다.** Fix 325/326/327 은 `main` 에 있지만, 이 worktree 에는 **커밋조차 안 된 `terminal.py`(1,185줄) / `perp-terminal.html`(2,481줄) / `router.py` 수정**이 남아 있고 **GitHub 에도 VPS 에도 백업 폴더에도 없다.** 클론하면 **사라진다.** → **새 PC 로 가기 전에 §6-3 끝의 (A) 또는 (B) 를 먼저 하라.**
> - **SSH**: `ssh root@159.65.137.250` 은 **개인키가 있어야만** 된다. 서버는 비밀번호 로그인이 꺼져 있어(`passwordauthentication no`) 키가 없으면 **우회로가 없다** (`secrets.md` §위험 3).
> - **pytest**: 2026-09-03 실측 — 아래 ②의 **3개 파일은 `backend/.env` 없이도 통과한다**(`.env` 가 아예 없는 워크트리에서 `62 passed`). `.env` 는 앱을 **띄울** 때 필요하다.
> - 🚨 **`pytest tests/` 전체는 건강 검진용으로 쓰지 말 것 — 지금도 초록이 아니다.** 같은 날 실측에서 `tests/integration/test_admin_stats_breakdown.py::TestStatsBreakdown::test_strategies_view_includes_all` 등이 **이번 세션과 무관하게** 실패한다(전체 1,766건 수집). 전체를 돌리면 없는 사고를 쫓게 된다. 아래 ②의 3개 파일만 볼 것.
>
> 🚨 **`ENCRYPTION_KEY` 경고 (이전에서 가장 위험한 지점 — `secrets.md` §3)**
> `.env` 의 `ENCRYPTION_KEY` 는 DB 의 바이낸스 API 키를 푸는 **Fernet 대칭키**다. 이걸 잃거나 **새로 생성해서 기존 DB 에 붙이면** `exchange_accounts.api_key_enc` / `api_secret_enc` 는 **수학적으로 복구 불가능**해진다. 백도어도, 복구 절차도, 「관리자 재설정」도 없다 — 바이낸스에서 **키를 새로 발급**받는 것 말고는 방법이 없다 (`backend/app/core/crypto.py`).
> - 따라서 새 PC 로 옮길 때는 **글자 하나도 바꾸지 말고 그대로 옮긴다.**
> - `deploy/generate-secrets.sh` 를 그냥 돌리면 **`ENCRYPTION_KEY` 도 새로 만든다.** 기존 DB 를 계속 쓸 거면 그 출력을 통째로 붙여 넣지 말 것.
> - 🚨 **옮기는 방법**: 카카오톡·이메일·채팅·이 대화창에 **비밀 값을 붙여 넣지 마라.** 비밀번호 관리자나 USB 같은 오프라인 경로를 쓰고, 옮긴 뒤 `history -c` 로 셸 히스토리를 정리한다. 값은 이 저장소의 **어떤 문서에도 적지 않는다** (이 문서 포함 — 여기엔 키 **이름**만 있다).
> - 🚨 `local-env.md`/`secrets.md` §7-2 경고: 로컬 `.env` 의 `DATABASE_URL` 을 최신값으로 채우는 순간, 새 PC 가 **운영 Neon DB 에 붙어 실계좌로 매매하는 엔진이 하나 더** 뜬다. 개발용으로 쓸 거면 DB 를 분리할 것.

> 🚨🚨 **처음 30분에 절대 하면 안 되는 것 3가지** (위험 검토 2026-09-03 추가)
>
> | 하지 말 것 | 왜 |
> |---|---|
> | **로컬(내 PC)에서 스케줄러·워커·`docker compose up` 을 띄우기** | `.env` 에 운영 `DATABASE_URL` 을 채운 상태로 띄우면 **운영 Neon DB 에 붙은 매매 엔진이 하나 더** 생긴다. 스케줄러는 Redis 리더 선출을 쓰는데(`scheduler_runner.py:75-77` `DistributedSchedulerGuard.try_become_leader()`) **로컬 Redis 는 별개**라 로컬도 자기가 리더인 줄 알고 **실계좌에 주문을 낸다.** 새 PC 에서는 **읽기 명령과 pytest 까지만** 한다 |
> | **로컬에서 바이낸스 API 를 직접 호출하기** (분석 스크립트, `get_klines` 반복, `python -c "…BinanceClient…"`) | 🚨 **IP ban(418)** 전력이 있다(Fix 117/122). ban 은 **IP 단위**라 집·사무실 IP 가 막히는 것과 별개로, 같은 **API 키에 대한 rate limit** 을 소모해 **VPS 의 손절·청산까지 굶길 수 있다.** 시세·캔들이 필요하면 **VPS 에서 조회**하거나(위 §들의 `docker compose exec` 방식) **DB 에 저장된 값**을 읽어라 |
> | **`git stash` / `git stash pop` / `git reset --hard` / `git checkout .` / `git clean -fd` / `git push --force`** | 이 저장소는 **worktree 를 공유**하고 **커밋 안 된 작업이 실재한다**. 특히 `git stash list` 에 **2026-08-24 백업 stash 가 아직 남아 있다** — 무심코 `pop` 하면 **8월 24일 코드가 9월 3일 코드 위에 얹힌다.** 상태를 맞추고 싶으면 `git status` 로 **보기만** 하고, 지우는 대신 **커밋하거나 복사**하라 |

**① 코드가 맞는 자리에 있는가** (`local-env.md` §2 대로 클론했다면 경로가 아래와 같다)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git fetch origin && git status -sb | head -1 && echo "--- 내 체크아웃 ---" && git log --oneline -1 && echo "--- origin/main ---" && git log --oneline -6 origin/main
```

기대(2026-09-03 실측): `origin/main` 목록의 맨 위가 `e51d9a8 chore(handoff) …` → `ded22f3` → `1d04598` → `0459e8f` → `61e19a8` → `fcd8462`.
`e51d9a8` 은 **문서만** 바꾼 커밋이다(`backend/` 변경 0건). 그래서 VPS 가 `ded22f3` 인 것은 **뒤처진 게 아니라 정상**이다.

첫 줄이 `## main...origin/main` 이면 최신이고, **`## main...origin/main [behind 30]` 처럼 `behind` 가 붙으면 뒤처진 것**이다(2026-09-03 옛 PC 메인 클론 실측값이 정확히 `[behind 30]` 이었다).

🚨🚨 **「--- 내 체크아웃 ---」이 `e51d9a8` 이 아니면 여기서 멈추고 먼저 당겨라.** `git fetch` 는 원격만 갱신할 뿐 **작업 트리를 바꾸지 않는다.** 2026-09-03 실측: 옛 PC 의 메인 클론은 로컬 `main` 이 **`2586555`(8월 말)** 에 멈춰 있었고, 그 상태에서 아래 ②를 돌리면 **`test_support_score.py` 등 3개 파일이 아예 없어서** `ERROR: file or directory not found` 가 난다. 「테스트가 깨졌다」가 아니라 **「코드를 안 당겼다」**이다.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git checkout main && git pull --ff-only origin main && git log --oneline -1
```

(`--ff-only` 를 쓰는 이유: 로컬에 커밋이 남아 있으면 조용히 머지하지 말고 **실패해서 알려야** 한다. 실패하면 로컬 커밋이 있다는 뜻이니 지우지 말고 §6-3 의 「살리는 방법」을 먼저 볼 것.)

**② 회귀 테스트가 도는가** — 이 3개가 Fix 325/326/327 의 테스트다 (**①에서 체크아웃이 `e51d9a8` 인 것을 확인한 뒤에** 돌릴 것)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/test_support_score.py tests/test_chg24_entry_gate.py tests/test_stop_loss_execution_path.py -q
```

기대: **`62 passed`** (support_score 22 + chg24_entry_gate 23 + stop_loss_execution_path 17). 2026-09-03 옛 PC 실측.
`PYTHONIOENCODING=utf-8` 을 빼지 말 것 — 이 저장소의 테스트 이름이 한글(`test_1단계_소액은_손절하지_않는다`)이라 Windows 기본 코드페이지에서 깨질 수 있다.

> ✅ **안심해도 되는 점 (위험 검토 실측)**: 이 3개 테스트는 **네트워크도 운영 DB 도 건드리지 않는다.**
> 실측 `grep -n "SessionLocal\|create_engine\|DATABASE_URL\|BinanceClient\|requests\|httpx" <세 파일>` → **출력 0줄**. 공용 `tests/conftest.py` 의 DB 픽스처조차 **`sqlite+pysqlite:///:memory:`** 이고(끝나면 `drop_all`), 이 세 파일은 그 픽스처도 쓰지 않는다(전부 가짜 객체).
> → 즉 **pytest 는 실계좌·운영 DB·바이낸스 API 에 아무 영향을 주지 않는다.** 새 PC 에서 제일 먼저 돌려도 되는, 유일하게 완전히 안전한 명령이다.

**③ VPS 가 어느 커밋으로 돌고 있는가**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log --oneline -1 && docker inspect binance-auto-trader-api --format "{{.State.StartedAt}}" && docker inspect binance-auto-trader-scheduler --format "{{.State.StartedAt}}" && date -u'
```

그다음 §6-1(P1 Fix 326 실검증)의 로그 명령을 돌린다.

---

### 8. 🚨 이 저장소에서 반복해서 사고가 난 자리 (이번 세션 문서들이 다시 확인한 것)

| 함정 | 이번 세션의 증거 |
|---|---|
| **「저장했다」는 「쓴다」가 아니다** | `chart_patterns` 를 진입에서 읽는 코드 **0곳**. Fix 247(`strategy_confluence`)과 같은 모양 |
| 🚨 **고친 뒤 옛 주석이 남으면 다음 사람을 정확히 반대로 속인다** | `stage_trim.py:320-321` 은 아직 「손절 경로는 SKIP 을 받으면 전량으로 떨어진다」라고 적혀 있는데, **Fix 326 이 바로 그것을 없앴다**(§4-2). 이 저장소는 「주석은 정답인데 코드가 안 함」을 겪었고, 이번엔 **부호만 반대**다 |
| 🚨 **커밋 안 된 것은 「있는 것」이 아니다** | `terminal.py`+`perp-terminal.html`+`router.py` **3,666줄**이 GitHub·VPS·백업 어디에도 없다. 그래서 그 API 는 **운영에서 404** 다(§6-3) |
| 🚨 **전역 기본값 한 줄이 62개 잡을 동시에 바꾼다** | P4 의 `job_defaults` 제안 — 부팅 시 밀린 잡이 한꺼번에 발사되어 **418 IP ban** 으로 갈 수 있다. 잡별로 걸어라(§6-4) |
| **부분 청산은 「남긴 것」의 다음 사이클까지 따라가야 한다** | Fix 326 — 부분 손절 12~300초 뒤에 전량 청산이 지웠다 |
| **한 번도 실행 안 된 분기는 런타임이 못 잡는다** | Fix 327 게이트는 지금까지 실행 0회 |
| **6시간 주기 잡은 이 환경에서 굶는다** | 72시간 `interval[6:00:00]` Running **0** / missed 18 |
| **절대 임계값은 종목 스케일이 바뀌면 무력해진다** | AKEUSDT: 밴드폭 절대 13.21%(넓음) vs 자기순위 0.02(최대 수축) |
| **효과크기가 교차검증을 통과해도 결과 수준에서 뒤집힐 수 있다** | SURGE/CRASH 방향 판정기 A→B +0.74%p / B→A −0.43%p |
| **같은 지표라도 용도가 다르면 결과가 다르다** | 4H MACD 상승: 종목 선정엔 d=2.08 최강급인데 **LONG 진입 타이밍으로 쓰면 43건 승률 2.3%** |
| **결손률 40% 넘는 컬럼은 결손 자체가 정보일 수 있다** | `max_profit_pct` 결손 285건 중 **94.4%가 손실** |
| **미래참조는 「이미 알 수 있었는가」로 검사한다** | 재진입 분석 234건 중 **102건(43.6%)** 이 아직 결착 전이었다 |
| **DB 는 Neon 이다** | `docker compose exec db psql` 은 **빈 DB** — 반드시 api 컨테이너 `SessionLocal` 경유 |

---

### 9. ⚠️ 이번 인수인계에서 확인하지 못한 것

1. **Fix 325 / 326 / 327 의 실서버 실행 증거** — 배포 후 25분 로그에 해당 태그 **0회**. 코드·테스트는 통과했으나 실운영 확인은 아직 없다.
2. **스케줄러가 재시작을 반복하는 원인** — 배포인지 크래시 루프인지 구분 못 함(감사 부록 B-3 과 동일).
3. **`StrategySuggestion.strategy_config["regime"]` 이 진입을 막거나 방향을 바꾸는지** — `auto_bb_breakdown_worker.py:232` 가 읽는 것은 확인됐으나 소비처는 미추적(감사 부록 B-1 그대로).

   ⬇️ **아래 3-1 ~ 3-4 는 2026-09-03 위험 검토 담당이 추가한 「확인 못 함」이다.**

   - **3-1. `perp-terminal.html`(2,481줄)이 실제로 주문을 낼 수 있는지** — 짝인 `terminal.py` 는 **`@router.get` 6개뿐**(POST 0개)이라 그 라우터만으로는 주문이 안 나간다. 그러나 HTML 이 **다른 기존 주문 API 를 부르는지는 읽지 않았다.** 새 PC 에서 이 화면을 열기 전에 확인할 것.
   - **3-2. 스케줄러 부팅 시 실제로 몇 개 잡이 미스파이어로 폐기되는지** — 「misfire_grace_time 을 늘리면 한꺼번에 발사된다」는 **APScheduler 동작에서 나온 추론**이다. 실제 폐기 건수를 부팅 로그로 세지는 않았다. P4 를 하기 전에 `grep "missed by"` 로 **먼저 세어 볼 것.**
   - **3-3. 스캔 1회의 진짜 rate-limit 비용** — 요청 수 ≈101 은 코드로 셌지만, **바이낸스가 매기는 실제 가중치와 현재 남은 한도**는 재지 않았다. 「200회」라는 기존 표현은 **요청 수로는 과대**, 가중치로는 대략 맞다.
   - **3-4. `stage_keep_notional_usdt` 를 크게 넣었을 때의 실제 동작** — 코드 경로(`stage_trim.py:176 → :294 → :322-326` → `tp_sl_orchestrator.py:615/739`)로만 추적했다. **운영에서 시험하지 않았다(해서도 안 된다 — 손절이 멈춘다).**
4. **`chart_pattern_scan` 을 `/scan-now` 로 부르면 몇 건이 탐지되는지** — DB 쓰기 + API 약 200회라 호출하지 않았다.
   🚨 **정정**: 이 문서의 이전 판이 적어 둔 `curl -X POST …/chart-patterns/scan-now` 는 **애초에 돌지 않는 명령이었다**(JWT 필요 → 실측 **401 `{"detail":"Not authenticated"}`**). 토큰 없이 같은 일을 하는 컨테이너 내부 명령으로 §6-4 를 바꿔 놓았다. **여전히 사장님 승인 후에만 실행할 것.**
5. **`REGIME_THRESHOLDS_2026-09-03.json` (2,460줄) 전문** — 구조와 주요 임계값만 확인했다. `indicator_recognition.rules.BOUNCE` 와 `.RANGE` 는 **빈 dict** 이고(= 인식 규칙 없음), `gate = 0.25`, `threshold_quantile = 0.5` 인 것까지 확인했다.
   ✅ **2026-09-03 재현성 검증에서 위 네 가지를 전부 재확인**했다(2,460줄 / `rules.BOUNCE`·`rules.RANGE` 둘 다 `{}` / `gate` 0.25 / `threshold_quantile` 0.5). 덤으로 §2-2 의 국면 표본수(SURGE 815 · CRASH 786 · RANGE 4,076 · BOUNCE 40 · BREAKDOWN 199)와 2시간 결과(SURGE +0.73%/57.3% `reproducible:true`, CRASH −0.46%/46.2% `reproducible:false`, RANGE +0.30%)도 이 JSON 과 **정확히 일치**했다. 아래 명령으로 언제든 다시 잴 수 있다:

   ```bash
   cd "/c/Users/user/바이낸스/binance-auto-trader" && PYTHONIOENCODING=utf-8 python -c "
import json; d=json.load(open('docs/spec/REGIME_THRESHOLDS_2026-09-03.json', encoding='utf-8'))
ir=d['indicator_recognition']
print('gate', ir['gate'], '| quantile', ir['threshold_quantile'])
print('빈 규칙:', [k for k,v in ir['rules'].items() if not v])
print('표본수:', d['regime_sample_counts'])
"
   ```

   🚨 **`encoding='utf-8'` 을 빼면 Windows 에서 파일이 아예 안 열린다.** 최상위 키 4개가 한글이라 실측으로 `UnicodeDecodeError: 'cp949' codec can't decode byte 0xec in position 7` 이 난다. `PYTHONIOENCODING=utf-8` 도 같이 붙여야 출력의 한글이 안 깨진다. **이 저장소의 한글 JSON·문서를 파이썬으로 열 때는 매번 둘 다 붙일 것.**
6. **옛 롤백 가이드의 나머지 명령이 지금도 유효한지** — 나머지는 미검증. 단 아래 두 가지는 **재검증에서 정정**했다.

   🚨 **경로가 틀렸다**: `docs/ROLLBACK_GUIDE_2026-08-24.md` 는 **저장소에 없다**(`git ls-files` 미추적 = 클론해도 안 딸려온다). 실제 위치는 백업본 한 곳뿐이다:

   ```
   docs/handoff/wip-backup-2026-09-03/main/untracked/docs/ROLLBACK_GUIDE_2026-08-24.md   (328줄)
   ```

   🚨 **줄번호도 불완전했다**. 그 파일에서 로컬 `db` 컨테이너를 때리는 줄 **전체**는 다음과 같다 (실측 `grep -n psql`):

   | 줄 | 명령 | 왜 틀렸나 |
   |---:|---|---|
   | 163 | `exec -T db psql … < backup_2026-08-24.sql` | **옛 목록에서 빠져 있었다** |
   | 181 | `exec db psql … COPY system_settings TO STDOUT` | |
   | 184 | `exec db pg_dump -t system_settings` | psql 은 아니지만 **같은 로컬 db 오인** |
   | 190 | `exec -T db psql … TRUNCATE + COPY FROM STDIN` | 🚨 복원인 줄 알고 돌리면 **빈 로컬 DB 를 지운다** |
   | 193 | `exec -T db psql … < system_settings_2026-08-24.sql` | |
   | 239 | `exec db psql -U postgres -d binance_auto_trader` | **옛 목록에서 빠져 있었다** |

   (78행은 psql 명령이 아니라 그 흐름 안의 `UPDATE system_settings …` SQL 이다.)
   → **이 가이드로 롤백하려면 위 6줄을 전부 §1-2 의 api 컨테이너 `SessionLocal` 방식으로 바꿔야 한다.** 그대로 돌리면 **운영 Neon 이 아니라 빈 로컬 DB** 를 상대로 백업·복원한 뒤 「했다」고 착각하게 된다 — 이 저장소가 반복해서 겪은 「조용한 실패」와 같은 모양이다.


---

## ⚠️ 알려진 공백

> 조사관 8명과 검증관 24명이 **고치지 못하고 남긴 문제 156건**이다. 숨기지 않고 그대로 옮긴다.
> 대부분은 **① 실자금이라 실행할 수 없었다 ② VPS 읽기 전용 원칙 ③ 코드 수정 금지 ④ 사장님 권한이 필요하다** 중 하나 때문이다.
> 각 항목 끝의 `[섹션]` 은 어느 조사관이 보고했는지다.

### 🔴 A. 지금 열려 있는 보안 구멍 — 사장님만 조치할 수 있다

| # | 사안 | 실측 근거 | 왜 못 고쳤나 |
|---|---|---|---|
| **A-1** | 🚨🚨🚨 **`SECRET_KEY` 가 공개 저장소에 평문으로 있고, 그 값이 VPS 현재 값과 md5 일치**. `SECRET_KEY` 는 `app/core/security.py:45,49` 의 `jwt.encode/decode` 서명키이고 포트 8000 이 인터넷에 열려 있다 → **누구든 로그인 토큰을 위조해 실자금 API 에 접근 가능** | `HANDOFF-2026-04-30-NEXT-SESSION.md:197,210` / `curl http://159.65.137.250:8000/health` → 200 / 저장소 `"private": false` | 실제 키 교체는 **VPS 쓰기**라 사장님만 가능. 유출을 **확인만** 했고 토큰 위조·인증 시도는 하지 않았다 `[vps-ops]` |
| **A-2** | 🚨 **Neon DB 비밀번호가 공개 저장소에 평문으로 있다.** 커밋 `e51d9a8` 로 이미 `origin/main` push 됨. 인증 없이 raw 로 HTTP 200 / 57,771 바이트를 받았고 그 안에 `npg_` 2건(385·386줄) + `postgresql://` 접속문자열 1건(389줄, 126자) | `docs/handoff/memory-backup-2026-09-03/project_overview.md` | 파일을 지워도 **git 이력에 남는다.** 교체만이 해결이며 Neon Console + VPS `.env` + 재시작 순서가 필요 `[claude-state]` |
| **A-3** | 🚨 **유출의 원천이 남아 있다** — 메모리 **원본**(`~/.claude/projects/.../memory/project_overview.md`)에도 같은 3줄이 그대로다. 저장소 안 사본만 마스킹하면 **다음 백업 때 재생성된다** | 위와 동일 | 저장소 밖 파일이라 이번 범위에서 손대지 않았다 `[claude-state]` |
| **A-4** | 🚨 **Redis 가 `6380:6379` = 0.0.0.0 바인딩인데 비밀번호가 없고 `ufw` 는 inactive** → `159.65.137.250:6380` 이 **인증 없이 열려 있다.** 외부에서 `api_backoff:ip:ban_until_ms` 를 써서 **회로차단기를 조작**하거나 mark price 캐시를 오염시킬 수 있다 | VPS 읽기 전용 실측: `sshd -T` / `ufw status` / `docker-compose.yml:24` | **Docker 는 ufw 를 우회하므로 ufw 를 켜도 이 포트는 안 막힌다** — compose 를 `127.0.0.1:6380:6379` 로 고쳐야 한다. 재시작을 동반해 실자금 영향 `[secrets][vps-ops]` |
| **A-5** | **Prometheus(9090)·api 평문(8000) 도 0.0.0.0 외부 노출.** 문서화는 정확하나 조치는 재시작을 동반 | 외부에서 실제 연결 확인 | 이전 작업과 별개로 **가장 시급한 미조치 위험** `[vps-ops]` |
| **A-6** | **Grafana admin 비밀번호가 `backend/docker-compose.yml:99` 에 평문 커밋**돼 공개 저장소에 있다 = **이미 유출 상태**. 3000 은 127.0.0.1 바인딩이라 직접 노출은 아니지만 **같은 비번을 다른 곳에 재사용했다면 그쪽이 위험**하다 | 실측 | 코드 수정 금지 + 교체가 재시작 동반 `[secrets][vps-ops]` |
| **A-7** | ⚠️ **VPS `backend/.env` 권한이 `-rw-r--r--`(644)** — 모든 로컬 사용자가 읽을 수 있다. 600 이어야 한다 | 실측 | VPS 쓰기라 명령만 문서에 남김 `[vps-ops]` |
| **A-8** | **SSH 개인키에 passphrase 가 없고 권한도 `-rw-r--r--`** 다 | `ssh-keygen -y -f ... -P ""` → `NO_PASSPHRASE` | 키 교체는 접속 정책 변경이라 하지 않았다 `[claude-state]` |
| **A-9** | 🚨 **이 문서·메모리·`reference_vps.md` 어디에도 없는 두 번째 서버 `152.42.232.195`(사용자 `trader`)** 가 허용목록에서 발견됐다. `docker compose restart` 와 `.env.production` 복사 항목이 있어 운영 계열로 보인다 | `settings.local.json` | 접속해 확인하지 않았다(VPS 읽기전용 + 정체불명 호스트). **새 PC 작업 전 사장님 확인 필요** `[claude-state]` |
| **A-10** | **이미 공개된 handoff 102개 파일 중 8개에 VPS root SSH 엔드포인트가 박혀 있다.** 되돌릴 수 없다 — 히스토리를 지워도 **이미 복제됐다고 가정**해야 한다 | 실측 | 비밀 값은 안 샜지만 **실자금 서버의 공격 대상이 특정된 상태** `[doctrine]` |
| **A-11** | **VPS 의 SSH 하드닝 상태**(비밀번호 로그인 금지 / root 직접 로그인 금지 / fail2ban / 방화벽 IP 제한) 미확인 | — | VPS 읽기 전용 원칙으로 `sshd_config` 조회까지 하지 않았다. public 저장소에 엔드포인트가 노출된 상태라 **사장님이 직접 확인**해야 한다 `[doctrine]` |
| **A-12** | **git 이력 전체(과거 커밋)에 대한 비밀 스캔은 하지 않았다.** 현재 워킹트리 파일만 검사했다 | — | 지금은 지워진 비밀이 과거 커밋에 더 남아 있을 수 있다 `[vps-ops]` |
| **A-13** | 🚨 **저장소가 public 인데 `docs/handoff/` 는 이미 깃에 추적되는 경로다**(커밋된 파일 102개). 이 핸드오프를 커밋하면 **VPS IP·root SSH·열린 redis·해제된 안전장치가 전부 공개된다** | 실측 | 커밋 금지 / private 전환은 사장님만 `[secrets][doctrine]` |
| **A-14** | **`ENCRYPTION_KEY` 평문 2개가 `settings.local.json` 허용목록에 있었다.** 이 파일이 과거에 외부로 나간 적이 있는지 확인 못 함(트랜스크립트 1.1GB 미조사) | `[claude-state]` §4.4 | 교체하면 DB 의 `api_key_enc` 를 전부 못 읽게 되어 거래소 계정 재등록이 필요 → 사장님 판단 사항 `[claude-state]` |

### 🟠 B. 이전 절차 자체의 미검증·미완 (여기서 막힐 수 있다)

- **B-1** 🚨 **`infallible-euler-6dc297` worktree 의 미커밋 3,666줄(215KB)이 아직 안 살려졌다.** `wip-backup-2026-09-03/` 에 이 worktree 폴더가 **없다**(main·charming·loving 3개뿐). 옛 PC 를 밀면 복구 불가. 실제 push/패치 뜨기는 **사장님이 해야 하는 미완 작업**이다 — worktree 상태를 바꾸는 일이라 조사관이 하지 않았다 `[local-env][recent-work]`
- **B-2** 🚨 **`docs/handoff/2026-09-03/` 폴더가 여전히 untracked 다.** 사무실 PC 를 다시 켜지 않으면 **핸드오프 문서 전체가 새 PC 로 넘어가지 않는다** — 문서 수정으로 못 막는 실물 블로커. 게다가 커밋하는 순간 public 게시가 되므로 **A-13 결정을 먼저 해야 하는 순서 의존**이 있다 `[doctrine]`
- **B-3** **`52 failed / 44 failed` 기준선을 Python 3.12 + venv 에서 재측정하지 못했다.** 실측은 전부 3.14.2 + 옛 PC 전역 패키지. 그런데 문서는 새 PC 에 3.12 를 권한다 = **사장님이 문서를 그대로 따르면 비교 기준이 실측되지 않은 환경에서 검증하게 된다.** 경고(「숫자 대신 실패 테스트 이름을 비교하라」)는 넣었으나 **3.12 기준선 숫자 자체는 공백** `[local-env][architecture]`
- **B-4** **`alembic upgrade head` 를 실제로 실행해 검증하지 못했다.** 옛 PC `.env` 가 운영 Neon 을 가리켜 실수로 운영 DB 를 마이그레이션할 위험이 있어 **의도적으로 돌리지 않았다.** venv 의 `alembic` PATH, docker db healthy 대기, 첫 마이그레이션 소요 시간은 **문서상 추론** `[local-env]`
- **B-5** **로컬 스택 기동 절차(`docker compose up -d db redis api` → `alembic upgrade head`)는 실행 미검증.** `env_file: - .env` 고정·alembic 대상·모듈 경로는 파일로 확인했지만 컨테이너를 띄우지 않았다 `[secrets]`
- **B-6** **새 PC 의 로컬 포트 5433/6380 이 이미 다른 프로그램에 쓰이고 있을 때의 대처가 문서에 없다.** 충돌하면 `docker compose up -d db redis` 가 실패하는데, 이때 `docker-compose.yml` 의 포트 매핑을 고치면 다른 절의 명령과 어긋나게 된다 `[local-env]`
- **B-7** **`pip install cryptography` / `psycopg2-binary` 가 깨끗한 새 파이썬에서 성공하는지 미검증.** 옛 PC 에는 둘 다 이미 깔려 있었다 `[secrets]`
- **B-8** **`.env` 전송 경로가 노출됐다고 의심될 때 바이낸스 API 키를 회전(재발급)하는 절차가 없다.** 거래소 계정 조작이라 조사관이 쓰지 않았다 `[local-env]`
- **B-9** **`ENCRYPTION_KEY` 를 「이미 잃어버린」 경우의 복구 절차가 없다.** 「영영 복호화 못 한다」까지만 있고 그 다음(거래소 계정 행 삭제 → 바이낸스 키 재발급·재등록)이 없다. `backend/scripts/rotate_encryption_key.py` 는 **247행 `old_key = settings.encryption_key` 로 옛 키를 요구**하므로 분실 시 대안이 아니다 — 이 사실도 문서에 없다 `[local-env]`
- **B-10** **옛 PC 와 VPS 의 `ENCRYPTION_KEY` 가 실제로 같은 값인지 확인 못 했다**(VPS 읽기 전용 + 비밀값 미조회). 「VPS 에도 있으니 옛 PC 를 밀어도 안전하다」고 판단해도 되는지 문서가 확정해 주지 못한다 — **사장님이 양쪽에서 지문 12자를 직접 대조**해야 한다 `[local-env]`
- **B-11** **§4 의 지문 값(예: `ENCRYPTION_KEY fp=1728f1f33e3b`)을 독립적으로 재확인하지 못했다.** `.env` 값을 읽어 해싱하는 명령이 권한 분류기에 차단됐다(값을 출력하지 않는 명령이었는데도). **검증 체크리스트가 이 숫자에 전적으로 의존**하므로 사장님이 직접 한 번 돌려 대조하는 것이 안전 `[secrets]`
- **B-12** **최신 `DATABASE_URL` 을 문서가 제공할 수 없다.** 사무실 PC 값은 비밀번호가 만료돼 인증 실패(실측). **이 문서만으로는 새 PC 에서 DB 에 붙는 단계까지 갈 수 없다** `[secrets]`
- **B-13** **옛 비밀번호를 아직 어딘가(다른 스크립트·백업·CI)에서 쓰고 있지 않은지 확인 못 했다** `[secrets]`
- **B-14** **`docs/handoff/memory-backup-2026-09-03/` 를 저장소에서 내릴지 미결.** 비밀번호 교체가 끝난 뒤에 결정해야 한다 — 지금 지우면 메모리 복구 경로가 끊기고 이력의 비밀은 그대로 남아 안전해지지도 않는다 `[claude-state]`
- **B-15** **git 히스토리 정리(force-push / history rewrite) 여부 미결.** 파괴적 작업이라 사장님 판단. 마스킹 커밋만으로는 `e51d9a8` 히스토리에 값이 남는다 `[claude-state]`
- **B-16** **새 PC 의 Windows 사용자명을 모른다.** `user` 가 아니면 경로 계산을 다시 해야 하는데, 그 경우의 실제 동작(옛 슬러그와 다른 폴더 생성)은 재현할 수 없었다 `[claude-state]`
- **B-17** **새 PC 의 Claude Code 버전이 같은 슬러그 규칙을 쓰는지 확인 불가.** 현재 PC 는 v2.1.258. 대비책이 [15단계 ①](#step-15) 의 「Fix 298 질문」 종단 검증이다 `[claude-state]`
- **B-18** **`settings.local.json` 위험 항목 제거 정규식의 개별 항목 타당성은 검증 못 함.** 개수(1,116 → kept 919 / removed 197)만 확인했고, 제외된 197개 중 **과잉 제외(false positive)** 가 있는지는 하나씩 보지 않았다 `[claude-state]`
- **B-19** **`settings.local.json` 4개(합 1,116항목)에 VPS IP 외 다른 민감값이 있는지 전수 검사하지 않았다.** USB 로 옮기기 전에 한 번 훑는 것이 좋다 `[claude-state]`
- **B-20** **`%TEMP%\claude\...\scratchpad\baseline` detached worktree(`2a17a26`)에 고유 작업이 있는지 조사하지 않았다** `[claude-state]`
- **B-21** **`loving-rhodes` 미커밋본과 `origin/main` 본의 줄 단위 우열은 비교하지 않았다.** 「더 최신 커밋이 있다」는 근거만으로 폐기 판단이 서 있다 `[claude-state]`
- **B-22** 🚨 **`RESTORE-2026-09-03.md` §2-1 에 사실이 아닌 주장이 남아 있다.** 「`long_bottom_detector_worker.py` / `auto_long_at_bottom_worker.py` 는 원격 어디에도 없다」고 적혀 있으나 **둘 다 이미 `origin/main` 에 있고 main 쪽이 훨씬 최신**이다 (`auto_long_at_bottom_worker.py` 백업본 12,019 bytes vs main **93,893 bytes**, diff 2,066줄 / `long_bottom_detector_worker.py` 27,244 vs 42,437, diff 415줄). **그 절을 따라 복사하면 8만 줄 가까운 개발분을 옛 스냅샷으로 덮는다.** 담당 파일이 아니라 못 고쳤다 `[local-env]`
- **B-23** **`GIT_SYNC_GUIDE.md:36` 의 「Private 선택 (반드시!)」이 현재 상태와 다르다** — 저장소는 public 이다. 정정 상자는 넣었지만 그 파일 자체는 못 고쳤다 `[local-env]`
- **B-24** **저장소를 새 PC 로 clone 하는 절차가 `vps-ops.md` 에는 없다.** VPS 작업은 clone 없이 SSH 만으로 전부 가능하므로 치명적이진 않다 `[vps-ops]`
- **B-25** **`architecture.md` 는 의도적으로 비밀 이전 절차를 담지 않고 `secrets.md` 로 넘긴다.** 두 파일이 분리되어 전달되면 **그 포인터가 끊긴다** — 핸드오프는 `docs/handoff/2026-09-03/` **폴더 통째로** 넘겨야 한다 `[architecture]`
- **B-26** **`ops-state.md` 단독으로는 배포를 완결할 수 없다.** pull → alembic → restart 순서와 「손절 없는 구간」 관리는 `vps-ops.md` §6 에 있다 — **두 문서에 걸친 의존**이 남아 있다 `[ops-state]`
- **B-27** **새 PC 에서 `.env` 가 실수로 커밋되지 않는지 확인하는 절차가 비대칭이다.** `settings.local.json` 에는 `git check-ignore` 확인 명령이 있는데 `.env` 에는 없었다(이 통합 문서 [11단계](#-이전-시나리오-순서대로)에서 보강했다) `[local-env]`
- **B-28** **진짜 새 PC(키 없는 상태)에서의 처음부터 재현은 불가능했다.** 모든 명령을 현 PC + 운영 VPS 에서만 검증했다. 특히 **`authorized_keys` 등록은 VPS 쓰기라 실행하지 않았고, 그 한 줄이 실패하면 새 PC 는 어떤 VPS 명령도 못 돌린다** `[vps-ops]`
- **B-29** **DigitalOcean Recovery Console 로 실제 복구가 되는지 / root 비밀번호가 설정돼 있는지 확인 못 함**(DO 콘솔 필요). SSH 잠금 사고의 **유일한 탈출구**인데 이것이 없으면 대비책이 문서상으로만 존재하게 된다. **이전 작업 전 최우선 확인 항목** `[vps-ops][secrets]`
- **B-30** **새 PC 의 공인 IP 를 알 수 없어**(아직 그 PC 가 없다) 바이낸스 화이트리스트·Neon IP 제한에 무엇을 추가해야 하는지 구체적으로 적지 못했다 `[secrets]`
- **B-31** **바이낸스 API 키의 IP 화이트리스트 / 권한(Futures ON, 출금 OFF) 확인 불가**(금융 계정 미접속 원칙). **새 PC 에서 무엇이 되고 안 되는지가 여기에 달려 있는데 문서로는 메울 수 없다** — 메모리에는 「2 IP」 기록이 있어 사무실 IP 도 등록돼 있을 가능성이 있다 `[secrets]`
- **B-32** **`ENCRYPTION_KEY` 회전 절차(`--dry-run` 포함)를 한 번도 돌리지 않았다.** 특히 `docker compose exec --env-file` 지원 여부가 compose 버전을 타는데 확인 못 했다 — **그 명령이 실패하면 사장님이 키를 명령줄에 적게 되어 셸 히스토리에 남는다** `[secrets]`
- **B-33** **VPS `.env` 에 실제로 어떤 키가 몇 개 있는지 확인 못 함.** 키 목록은 저장소 `backend/.env.example` 18개를 근거로 한 것이라 **운영에만 있는 추가 키가 빠져 있을 수 있다** `[claude-state]`
- **B-34** **현재 DB 의 `api_key_enc` 가 지금 VPS 의 `ENCRYPTION_KEY` 로 실제 복호화되는지 확인 못 함.** 운영이 정상 매매 중이라는 정황으로 추정만 했다(확인법: 화면에서 거래소 계정 조회가 되는지 — `lifecycle.py:324` 오류 문구가 안 뜨면 정상) `[claude-state]`
- **B-35** **`users.id=2` 의 정체 미확인**(이메일에 `@` 가 없는 값이라 열어보지 않았다). 새 환경에서 이 계정을 살릴지 지울지 판단할 근거가 없다 `[secrets]`
- **B-36** **옛 PC 의 `C:\Users\user\` 트리가 OneDrive 등으로 동기화되고 있는지 확인 못 했다.** 동기화 중이라면 `backend/.env` 가 이미 클라우드에 올라가 있을 수 있다 `[local-env]`
- **B-37** **롤백 가이드의 psql 계열 6줄 외 나머지 명령이 지금도 유효한지 미검증.** 그 파일이 untracked 백업본으로만 존재하므로, 롤백이 필요해지면 **가이드 전체를 Neon 기준으로 다시 쓰는 작업이 선행**돼야 한다 `[recent-work]`
- **B-38** **VPS 쪽 alembic 되돌리기(downgrade) 경로가 어디에도 없다.** upgrade 후 문제가 생겼을 때 되돌리는 절차가 빠져 있다 `[doctrine]`
- **B-39** **롤백 절차를 실제로 실행해 보지 않았다**(실자금이라 리허설 불가). 명령 자체는 표준 git/docker 동작이지만 **첫 롤백이 곧 실전**이 된다. 특히 `git checkout <해시>` 후 detached HEAD 에서 다시 `git pull` 을 치면 **실패한다**는 것까지는 문서에 없다 `[vps-ops]`
- **B-40** **`git pull --ff-only` 실패 시의 시나리오별 복구 절차가 없다.** 「멈추고 원인 확인」까지만. 현재 VPS 는 추적 수정 0건이라 실패할 이유가 없지만, **사장님이 VPS 에서 직접 파일을 고친 뒤라면 상황이 달라진다** `[vps-ops]`
- **B-41** **`docker-compose.production.yml` 을 지금 적용하면 무엇이 깨지는지 미검증**(적용이 재시작을 동반). 특히 `db` 를 `profiles:disabled` 로 끌 때 `db-backup`·`api`·`scheduler` 의 `depends_on` 이 어떻게 되는지 `[vps-ops]`
- **B-42** **VPS `docker-compose.yml`(4011 bytes)과 저장소 버전(4147 bytes)의 내용을 실제로 diff 하지 않았다.** 포트 바인딩만 대조했다(둘 다 8000/9090/6380 = 0.0.0.0, 5433/3000 = 127.0.0.1 로 일치). 다른 검증관은 CRLF 로 인한 차이라고 정리했으나 독립 확인은 없다 `[secrets]`
- **B-43** **`fapi/v1/ping` 응답표(418/429 의미)는 명령 형식만 맞고 실행하지 않았다.** 이 PC 에서 Binance 를 치는 것 자체가 금지 행동이라 일부러 피했다 `[vps-ops]`
- **B-44** **Binance weight 가 어느 지점에서 `429`/`418` 로 넘어가는지 재보지 않았다**(재보는 행위 자체가 ban 을 부른다) `[local-env]`
- **B-45** **워커를 로컬에서 켰을 때 실제로 어떤 주문이 나가는지 시험하지 않았다**(실자금). 위험 설명은 `docker-compose.yml` 의 command 와 `DEV-WORKFLOW.md:22-23`, 과거 사고 기록에 근거한 것이다 `[local-env]`
- **B-46** **새 PC 로컬에서 실서버 Neon DB / 바이낸스에 실제로 연결이 되는지**(IP 허용목록으로 그냥 막히는지) 확인하지 못했다. **막힌다는 보장이 없으므로 위험으로 취급**했다 `[architecture]`
- **B-47** **로컬 스케줄러/uvicorn 을 이미 실행해 버린 뒤의 복구 런북이 없다.** 필요한 것: 즉시 프로세스 종료 → VPS·거래소 포지션 대조(reconcile 결과) → 로컬이 만든 고아 주문/포지션 식별 `[architecture]`
- **B-48** **`docker compose down -v` 가 운영 Neon 에 영향이 없다는 것은 정의상 그렇다는 것이지 실행해 확인하지 않았다** `[local-env]`
- **B-49** **이 문서의 명령은 「옛 PC 와 같은 경로에 clone」을 전제한다.** 다른 경로를 택하면 9개 명령의 경로를 손으로 다 바꿔야 한다 — 자동화하지 못했다 `[architecture]`
- **B-50** **새 PC 의 SSH 개인키 이전 절차를 `doctrine.md` 에서 검증하지 못했다.** `vps-ops.md` / `secrets.md` 로 넘겼지만 그 두 문서가 실제로 담고 있는지는 담당 밖이라 확인하지 못했다 `[doctrine]`
- **B-51** **새 PC 의 Python/pytest 환경 구축 절차를 `doctrine.md` 에서 검증하지 못했다.** 「테스트 실패」와 「환경 없음(`ModuleNotFoundError`)」을 혼동하지 말라는 경고는 넣었다 `[doctrine]`

### 🟡 C. 운영 미해결 — 이전과는 별개지만 새 PC 운영자가 매일 마주친다

- **C-1** 🚨 **자동 32건 중 18건이 생성만 되고 진입 못함 — 어느 게이트가 걸렀는지 미상.** 전략 id 로 차단 사유를 추적할 로그가 코드에 없어 **새 PC 에서도 조사할 수단이 없다.** 해결하려면 코드 수정이 필요 `[ops-state]`
- **C-2** **`REENTRY_READY` 16건이 「워커가 후보로 안 보는 좀비」인지 「정상 대기」인지 미확정.** 메모리에 「재진입 워커는 `TERMINAL_STATUSES` 에서만 후보를 고른다」가 확정 사항으로 있어 **좀비일 가능성이 높다** `[ops-state]`
- **C-3** **`unified_entry_enabled=0` 이 의도된 정지인지 사고인지 모른다.** `auto_bb_break_daily_limit=0` 도 마찬가지. **사장님만 답할 수 있다** — 실자금 설정이라 건드리지 않았다. **새 PC 에서 제일 먼저 확인할 항목** `[ops-state][architecture]`
- **C-4** **현재 실제로 진입을 만드는 워커들**(`pump_top_detector` / `auto_short_at_top` / `auto_long_at_bottom` 등)**의 자체 ON 스위치를 확인하지 못했다.** `unified_15m` 이 꺼져 있다는 것만 확인했다 = **「지금 무엇이 실제로 진입하는가」는 여전히 미확정** `[architecture]`
- **C-5** **`stage_ladder` 0건의 원인 미해결.** 「배포 이후 새 전략이 없어서」인지 「`stages_config` 가 여전히 1단계라서」인지 구분 못 함. **사다리 3단계가 안 만들어지는 것일 수도 있어 실매매 사양 결함 가능성**이 남아 있다 `[architecture]`
- **C-6** **`chart_patterns` = 0 의 원인 미상.** 「스케줄러가 40분마다 재시작하는 크래시 루프」 진단은 **반증됐다**(실제 분포는 배포 시각에 몰려 있고 01:52→06:56 은 5h04m 무중단, docker `RestartCount`=4/12일, `OOMKilled`=false, `ExitCode`=0). 그렇다면 원인이 무엇인지는 **여전히 모른다.** 로그 보존이 9.5시간뿐이라 확인할 방법이 없었다. 배제 못 한 대안 2개: `run_full_scan` 이 아무 행도 안 씀 / 6시간 잡이 `chart_patterns` 를 쓰는 경로가 아님 `[ops-state][recent-work]`
- **C-7** **scheduler 재시작 4회 원인 / load average 3.66~3.67 (2 vCPU 대비 180%) 과부하 원인 — 둘 다 미규명.** 이 상태에서 `docker compose up -d --build` 를 돌리면 **빌드가 예상보다 훨씬 오래 걸릴 수 있고 그만큼 손절 공백이 길어진다.** 「수 분」이라는 문서 표기는 실측이 아니다 `[vps-ops][recent-work]`
- **C-8** 🚨 **`mainnet_safety_worker` 크래시가 「그 함수만」 죽이는지 「워커 전체」를 죽이는지 확정 못 했다.** 후자면 **다른 안전 점검도 같이 죽어 있다**는 뜻이라 우선순위가 완전히 달라진다 `[ops-state]`
- **C-9** 🚨 **LONG 손절 기준이 지시와 코드가 정면 충돌한 채 남아 있다.** 지시 문서(09-02, −10%)와 코드 결정(Fix 253, 09-01, 실측으로 10%→5% 복귀)이 충돌하고, **지시가 하루 더 최신인데 그 지시의 근거를 실측이 반증한 구조**다. **사장님 결정 사항** `[ops-state]`
- **C-10** **거래소에 과거 수동으로 걸어 둔 미체결 스톱 주문이 실제로 있는지 확인하지 못했다.** 「손절이 없다」는 **코드가 스톱 주문을 걸지 않는다**는 것까지만 증명한다 — **사장님이 웹 UI/앱의 미체결 주문 목록을 눈으로 봐야 최종 확정**된다 `[vps-ops]`
- **C-11** **테스트 실패 52건이 누구도 triage 하지 않은 채 기준선으로 굳었다.** 실자금 시스템에서 **red baseline 자체가 위험**이다. 표본으로 본 `tests/unit/test_strategy_status_constants.py` 는 「테스트가 뒤진 것」이 맞지만 나머지 51건은 미확인. 특히 **`tests/integration/test_verify_tp_sl_entry.py`(3건, 진입 검증)** 와 **`tests/unit/test_stream_service_partial_close.py`(4건, 부분 청산)** 는 부분손절 사양과 같은 영역이라 우선 확인 필요. 52건 중 **29건분만** 파일별로 기록됐다(나머지 23건은 미확인) `[architecture][local-env]`
- **C-12** **CI 워크플로가 fastapi 를 핀 없이 설치한다**(`sajangnim_sasang_audit.yml:25, :43`). mainnet 500 사고와 같은 형태라 **CI 가 어느 날 코드 변경 없이 빨개질 수 있다** `[local-env]`
- **C-13** 🚨 **코드 주석이 현재 동작과 정반대인데 고치지 못했다**: `backend/app/services/stage_trim.py:320-321` 이 「손절 경로는 SKIP 을 받으면 스스로 전량으로 떨어진다」라고 적혀 있는데 **Fix 326 이 바로 그것을 없앴다**(`tp_sl_orchestrator.py:615`, `:739` 에서 `return`). **다음 세션이 이 주석 3줄을 고쳐야 한다** `[recent-work]`
- **C-14** **Fix 327 의 「관찰 모드(막았을 것만 로그)」가 없다. 켜는 순간 실제 차단이 시작된다** `[recent-work]`
- **C-15** **Fix 325/326/327 의 실서버 실행 증거가 여전히 0.** 배포(08:51 UTC) 후 54분 시점까지 신규 전략 `created_at` 0건 · Fix 태그 0회. **문서 결함이 아니라 아직 사건이 안 일어난 것** `[recent-work]`
- **C-16** **Fix 325·326·327 이 Claude Code 메모리에 없다**(메모리 최대 Fix 번호 = 324). **헌법 69(요구는 즉시 메모리 저장)에 어긋나며, 새 세션이 메모리만 읽으면 최신 3개 변경을 모른다.** 대체 경로 = 커밋 메시지 / `docs/spec/CHART_REGIME_ANALYSIS_2026-09-03.md` `[doctrine]`
- **C-17** **헌법 19~172 번의 정본 목록이 어디에도 없다** `[doctrine]`
- **C-18** **사상 vs 코드 대조표의 「⚠️ 확인 못 함」 4건이 남았다**: ③ 볼밴 하단 이탈에 분할 SHORT / ④ 우선순위 OBV>4H>15m 의 실제 강제력 / ⑥ 4H vs 15m 하드게이트 / ⑥ 4H 조정 구간 LONG 미리분할 국면. **한 줄 grep 으로 갈리지 않고 호출 체인 전체를 따라가야 해서** 추측으로 채우지 않았다. **사상과 코드가 정반대일 수 있는 항목이라 실매매 영향이 있다** `[doctrine]`
- **C-19** **「전체자산 1~2% 분할」 스위치를 켜면 얼마가 되는지 실측 못 함.** 「24건 × 910 ≈ 21,840 USDT」는 단순 산수이고, 어느 전략에 적용되는지·레버리지 배수가 몇인지는 확인 못 했다. **이 스위치를 켜기 전에 실측 필요** `[doctrine]`
- **C-20** **「10 usdt = 증거금」의 Fix 324 소수점 재현 계산을 다시 돌려보지 못했다**(사장님 원 수치가 문서에 없어 재현 입력을 만들 수 없었다) `[doctrine]`
- **C-21** **`stage_keep_notional_usdt`(10)가 심볼별 MIN_NOTIONAL 보다 작아지는 경우에 잔량이 dust 가 되는지 끝까지 추적하지 못했다.** `stage_trim` 이 거래소 필터 결손 시 BLOCK 하는 것까지만 확인 `[architecture]`
- **C-22** **`stage_keep_notional_usdt` 를 크게 넣었을 때의 동작은 코드 경로 추적으로만 확인했다.** 운영에서 시험하지 않았고, **해서도 안 된다(손절이 멈춘다)** `[recent-work]`
- **C-23** **`perp-terminal.html`(2,481줄)이 기존 주문 API 를 호출해 실주문을 낼 수 있는지 읽지 않았다.** 짝인 `terminal.py` 는 `@router.get` 6개뿐(POST 0개)이라 **그 라우터만으로는 주문이 안 나가는 것까지만** 확인 `[recent-work]`
- **C-24** **APScheduler `job_defaults` 위험은 동작에서 나온 추론이다.** 부팅 시 실제로 몇 개 잡이 미스파이어로 폐기되는지 로그로 세지 않았다(먼저 `grep "missed by"` 로 세어 볼 것) `[recent-work]`
- **C-25** **위험 스위치를 끌 승인된 비상 명령의 정확한 SQL 이 문서에 없다.** `system_settings (key TEXT PK, value TEXT) 에 upsert` 라는 서술만 있고 실행문이 없다 — **사고 대응 경로가 하나뿐인데 그 하나가 문서화돼 있지 않다.** 쓰기 작업 문서화라 조사 범위를 넘고 사장님 승인이 필요 `[ops-state]`
- **C-26** **VPS 에 남은 스크래치 파일**(`/root/q1~q8.py`, `/root/vq.py`, `/root/sch.log` **52.5 MB**, 컨테이너 안 `/tmp/q*.py`)**을 지우지 않았다**(읽기 전용 원칙). 디스크는 48G 중 24G 여유라 급하지 않지만 정리는 사장님 몫 `[ops-state]`
- **C-27** **Neon 백업/PITR 보존 기간 미확인**(Neon 웹 콘솔에서만 확인 가능). **VPS 백업이 505바이트 빈 파일이라 이것이 유일한 안전망**이다 — 사장님이 콘솔에서 직접 볼 것 `[vps-ops]`
- **C-28** **DigitalOcean 클라우드 방화벽 유무 미확인**(DO 콘솔 필요). 다만 **6380/9090/8000 이 외부에서 실제 연결되므로 현재는 막혀 있지 않음이 확정** `[vps-ops]`
- **C-29** **`system_settings` 63행에 비밀이 없다는 판정은 `left(value,60)` 덤프 + 코드 감사에 근거한다.** 63행 전량을 무절단으로 덤프해 훑지는 않았다(값 열람 최소화). **잔여 위험은 「미래에 누가 비밀성 키를 추가하는 경우」** `[ops-state]`
- **C-30** **기준값(`ACTIVE_STRATEGIES=24` 등)이 「정상 범위」인지는 판단하지 않았다.** 매매 판단은 사장님 영역 `[secrets]`

### ⚪ D. 문서 자체의 남은 흠 (읽을 때 혼동할 수 있는 것)

- **D-1** **`ops-state.md` 내부가 서로 모순된다.** §0 요약표는 「크래시 루프 아님, 연속 가동 최장 5h04m」로 정정됐는데 **§7① 본문은 「평균 약 40분마다 재시작」 옛 주장 그대로**다(415줄 부근). 동시 편집 충돌을 피하려 손대지 않았다 `[ops-state]`
- **D-2** **§7② 의 grep 출력 `api=0 ui=0` 이 현재 워크트리에서는 재현되지 않는다.** 실행하면 5개가 `api=2` 로 나온다 — 원인은 ① 미커밋 `terminal.py` 의 독스트링 언급(읽기 전용 조회 엔드포인트라 토글 API 가 아니다) ② `__pycache__/*.pyc` 바이너리 매치. **새 PC 는 fresh clone 이라 `api=0` 이 재현되고 결론(「토글 수단이 DB 직접 쓰기뿐」)은 여전히 참**이지만, 이 워크트리에서 검산하는 사람은 혼란을 겪는다 `[ops-state]`
- **D-3** **컨테이너 표의 `Up 22 hours` 같은 상대 시각이 남아 있다**(api/scheduler 두 개만 절대 시각을 실측했다). 스냅샷임을 명시해 뒀다 `[ops-state]`
- **D-4** **`§1 의 실측값은 2026-09-03 09:03 UTC 기준이라 이미 낡았다.** 새 세션은 재측정 명령으로 다시 재야 하는데 **「이 수치의 유효기간」이 명시돼 있지 않다** `[recent-work]`
- **D-5** **「scheduler 25분 로그 8,716줄」·「72시간에 57회 재시작」·「interval[6:00:00] Running 0 / missed 18」·「`chart_patterns` 0행」·「전략 상태 분포 STOPPED 1173」 등은 이 세션에서 SSH 를 돌리지 않아 재확인 못 했다.** 문서가 보고한 값 그대로 남겨 뒀다 `[recent-work]`
- **D-6** **인용 통계(n=264, 승률 70.6%/63.9%, 실거래 1,419건, PF, 효과크기 d 등)는 원문 대조·재계산을 하지 않았다.** 코드 배선과 줄번호만 검증했다 `[recent-work]`
- **D-7** **「진입 경로 통합 154건」·「전체 138건 통과」의 출처 집합을 특정하지 못했다**(현재 전체 수집은 1,766건) `[recent-work]`
- **D-8** **`tp_sl_orchestrator.py:596-640` / `:720-757` 같은 범위형 줄번호는 시작점만 대조하고 끝점까지 정확히 재지 않았다** `[architecture]`
- **D-9** **과거 백테스트 수치(「850사이클: 간격 2.5% → 2·3단계 0건 / 1.5% → +2,636」, `−252.18 USDT` 등)는 재현하지 못했다** `[architecture]`
- **D-10** **`doctrine.md` 본문 929~935줄이 아직 `<SLUG>` 자리표시자를 쓴다**(§1-2 의 `$SLUGDIR` 자동탐지와 불일치). 안전 문제는 아니고 표기 일관성 문제 `[doctrine]`
- **D-11** **Neon 엔드포인트 호스트명 표기가 문서 간 불일치**했다 — `secrets.md` 는 마스킹, `vps-ops.md` 는 평문. **이 통합 문서에서는 마스킹으로 통일했다.** 자격증명이 아니고(비번 없이 접속 불가) Neon 프로젝트 식별에 필요하지만, 저장소를 비공개로 전환한다면 함께 정리하면 된다 `[architecture][vps-ops][local-env]`
- **D-12** 🚨 **비밀 값 재유입 위험.** `vps-ops.md` 는 여러 검증관이 동시 편집했고 **실제로 그 과정에서 Grafana admin 비밀번호 실제 값이 본문에 들어왔다가 제거됐다.** 최종 머지 직전마다 스캔이 필요하다:
  ```bash
  grep -nEi "postgres:postgres@|npg_|BEGIN .*PRIVATE KEY|AKIA[0-9A-Z]{16}" docs/handoff/2026-09-03/*.md HANDOFF-2026-09-03-NEW-PC-MIGRATION.md
  ```
  (이 통합 문서에도 위 스캔을 돌렸다. `postgres:postgres@` 는 `.env.example` 의 **로컬 docker 기본값**이라 운영 비밀이 아니다.) `[vps-ops]`
- **D-13** **`secrets.md` 는 성격상 위험이 가장 높은 파일이다**(회전 절차에서 옛/새 키 앞 8자를 출력하는 스크립트를 다룬다). **별도 검토관의 전수 검사가 권장된다** — `ops-state` 검토관은 자기 파일 한 개만 검사했다 `[ops-state]`
- **D-14** **`.env` 파일 자체는 규칙대로 열지 않았다.** 「사무실 PC `.env` 에 실제로 어떤 값이 들어 있는가」는 확인 대상이 아니었다(키 이름 목록은 `config.py` / `.env.example` 로만 확인) `[architecture]`
- **D-15** **VPS 가 실제로 `ded22f3` 를 돌고 있는지는 일부 검증에서 SSH 를 쓰지 않아 확인 못 했다.** [14단계](#-이전-시나리오-순서대로) 첫 명령으로 새 PC 에서 직접 대조해야 한다 `[architecture]`
- **D-16** **`system_settings` 쓰기 경로 전수 감사는 하지 않았다.** `strategy_suggestions.py:541` 의 fields dict 에 없다는 것과 `terminal.py` 가 읽기 전용이라는 것까지만 확인 `[recent-work]`
- **D-17** **§6 게이트 ON/OFF 명령·chart_pattern 수동 스캔 명령은 문법·경로만 코드와 대조했고 실행하지 않았다**(운영 DB 쓰기 / 바이낸스 API 200회 + DB 쓰기) `[recent-work]`
- **D-18** **「scheduler 로그 8,716줄」 같은 시간 의존 값은 재현 불가.** 새 세션이 다른 숫자를 봐도 정상이지만 그 단서가 문서에 없다 `[recent-work]`

---

## 🆘 막혔을 때

| 증상 | 원인 | 해결 |
|---|---|---|
| **DB 조회가 「테이블이 없다」/ 0건** | 🚨 **가장 흔한 오진.** DB 는 로컬 `db` 컨테이너가 **아니라 외부 Neon** 이다. `docker compose exec db psql` 로 보면 **빈 DB** 가 나온다 | 반드시 **api 컨테이너의 앱 세션**으로: `docker compose exec -T -e PYTHONPATH=/app api python -c "from app.core.database import SessionLocal ..."`. `strategy_instances` 가 **1487** 같은 실수(實數)면 Neon 에 붙은 것이다 |
| **`ModuleNotFoundError: app`** (VPS 컨테이너 안) | `PYTHONPATH=/app` 을 빼먹었다 | `docker compose exec -T **-e PYTHONPATH=/app** api python -c ...` |
| **첫 쿼리 실패 후 다음 쿼리도 전부 실패** | 세션이 aborted 상태 | `db.rollback()` 을 넣은 뒤 다음 쿼리를 돌린다 |
| **`docker compose restart backend` 가 「없는 서비스」** | 🚨 **서비스명이 `backend` 가 아니다.** `api` / `scheduler` 다 (`backend` 는 compose **프로젝트 이름**) | `docker compose restart api` / `docker compose restart scheduler` |
| **`docker-compose.production.yml` 이 안 보인다** | 그 파일은 `backend/` 안이 아니라 **저장소 루트**에 있다 | `ls -la ~/binance-auto-trader/docker-compose*.yml ~/binance-auto-trader/backend/docker-compose*.yml` 로 **양쪽 다** 본다. 참고로 compose 는 이 오버라이드를 **읽지 않는다**(`docker-compose.override.yml` 이 없다) |
| **명령이 경로에서 깨진다 / 「No such file」** | 경로에 **한글 「바이낸스」** 가 있다 | Bash 에서 **반드시 따옴표**: `cd "C:/Users/user/바이낸스/binance-auto-trader"`. Windows 긴 경로 대비로 `git config --global core.longpaths true` 도 켠다 |
| **파이썬 출력이 `UnicodeEncodeError`** | Windows 콘솔 기본 코드페이지 | `PYTHONIOENCODING=utf-8` 을 앞에 붙여 실행 |
| **메모리 파일은 있는데 Claude 가 「모른다」고 답한다** | 🚨 **슬러그(메모리 디렉터리 이름) 불일치.** 이름이 한 글자만 틀려도 **조용히** 안 읽힌다 | `cd <저장소> && python -c "import re,os; print(re.sub(r'[^A-Za-z0-9]','-',os.getcwd()))"` 로 계산 → `ls "$HOME/.claude/projects/"` 의 실제 폴더명과 **눈으로 대조**. 종단 검증은 [15단계 ①](#step-15) 의 「Fix 298 질문」 |
| **메모리 개수가 83 이 아니다** | 복사 원본이 잘못됐거나 슬러그가 틀렸다 | `ls .../memory \| wc -l` 이 83. 원본 두 곳: clone 안 `docs/handoff/memory-backup-2026-09-03/` 또는 USB `/e/handoff-memory` |
| **`git ls-files docs/handoff/memory-backup-2026-09-03 \| wc -l` 이 `0`** | 🚨 **`git ls-files` 는 지금 체크아웃된 커밋만 본다.** 옛 PC 의 main 워크트리는 `origin/main` 보다 **30커밋 뒤처져 있다** | `git fetch origin && git ls-tree -r --name-only origin/main -- docs/handoff/memory-backup-2026-09-03 \| wc -l` → **83** |
| **`git check-ignore` 가 아무것도 출력 안 함** | 🚨 **조용한 실패다.** 「출력이 없으니 괜찮다」고 읽지 마라 | `echo "exit=$?"` 를 같이 본다. `exit=1` 이면 전역 gitignore 가 안 만들어진 것 → [9단계 ①](#-이전-시나리오-순서대로) |
| **worktree 명령이 「절대경로가 깨졌다」고 함** | worktree 는 옛 PC 의 **절대경로**를 기억한다. 새 PC 에서 경로가 다르면 링크가 끊긴다 | 새 PC 에서는 worktree 를 그대로 옮기지 말고 **필요한 브랜치를 새로 `git worktree add`** 한다. 옛 PC 의 미커밋 작업은 [1단계](#-이전-시나리오-순서대로)에서 미리 커밋/백업해 둔다 |
| **`git push` 가 `rejected`** | `origin/main` 이 움직였다 | 🚨 **`--force` 금지**(실자금 코드가 사라진다). `git fetch origin && git merge --no-edit origin/main` 후 재푸시 |
| **`ssh ... Permission denied (publickey)`** | 고장이 아니라 **키가 아직 없다** | [5단계](#-이전-시나리오-순서대로). 잠겼다면 유일한 탈출구는 **DigitalOcean 웹 Recovery Console** (root 비밀번호를 미리 알아 둘 것) |
| **`authorized_keys` 에 키를 넣었더니 옛 PC 도 접속이 끊겼다** | 🚨 `>>` 가 아니라 `>` 를 썼다 | Recovery Console 로 들어가 복구. **예방: 새 키 접속 성공을 확인하기 전에 옛 키를 지우지 마라** |
| **pytest 가 대량 `ModuleNotFoundError`** | 「테스트 실패」가 아니라 **「환경 없음」** | [10단계](#-이전-시나리오-순서대로) 의존성 설치부터. `fastapi` 는 반드시 **핀 고정**(`fastapi==0.135.3`) |
| **테스트 실패 개수가 문서와 다르다** | 기준선은 Python **3.14.2 + 전역 패키지**에서 잰 것이다 | **숫자 대신 실패 테스트 이름 목록**을 비교한다 |
| **CI 가 빨간불** | 새 PC 탓이 아니다. `main` 은 최소 2026-08-29 `#557` 이후 연속 실패이고 원인은 `test_martingale_stage_entry.py` | 첫 push **전에** Actions 탭을 직접 본다. 🚨 마틴게일 = 실자금 증액 로직이라 우선 확인 필요 |
| **`docker compose up -d` 를 인자 없이 쳤다** | 🚨 워커 3종 포함 **9개가 전부 뜬다.** `restart: unless-stopped` 라 재부팅해도 되살아난다 | 즉시 `docker compose stop scheduler user-stream mark-price-stream`. 확인: `docker compose ps --services --filter status=running` |
| **로컬에서 앱을 띄웠는데 실주문이 나갔다** | `.env` 의 `DATABASE_URL`(운영 Neon) + `ENCRYPTION_KEY` 만 맞으면 **DB 의 실계정 키가 복호화된다** | 즉시 `docker compose down` → **바이낸스 화면에서 그 시간대 주문·포지션을 눈으로 확인** → DB 를 손으로 고치지 말고 사장님께 보고. 정식 정지 = **Kill-Switch API** (`POST /api/v1/admin/kill-switch/{id}/enable`) |
| **Binance 가 `418` / `429`** | IP ban. 이 프로젝트는 **ban 무한 연장 사고 전력**이 있다(가드가 루프 앞에 있어 스스로 연장) | 로컬에서 Binance REST 를 직접 때리지 마라. 조회는 **VPS api 컨테이너를 통해서**. 복구는 메모리 `project_2026-08-26_ip_ban_spiral.md` |
| **VPS 에서 `git pull` 했더니 동작이 이상하다** | 🚨 `docker-compose.yml` 이 `.:/app` **바인드 마운트**다 = **`git pull` 은 조회가 아니라 배포의 시작**이다. 재시작 전까지 **옛 코드와 새 코드를 섞어 import** 할 수 있다 | 재시작까지 한 세트로 진행한다. 마이그레이션이 섞였으면 **재시작 전에** `alembic upgrade head`. 순서는 섹션 5 §6 |
| **`.env` 를 바꿨는데 반영이 안 된다** | `restart` 로는 `env_file` 이 다시 읽히지 않는다 | 섹션 5 §6 (475줄 부근) 참조 |
| **`git stash` 를 쓰고 싶다** | 🚨 이 저장소는 **worktree 를 공유**한다. stash 는 저장소 전역이라 다른 worktree 작업까지 빨아들이고, 충돌 시 복구가 어렵다 | stash 말고 **브랜치를 파서 커밋**: `git switch -c wip/$(date +%m%d-%H%M) && git add -A && git commit -m wip` |
| **로컬에서 `alembic upgrade head` 를 치려 한다** | 🚨 `alembic/env.py:27-30` 이 **`DATABASE_URL` 환경변수를 그대로 쓴다** = 운영 Neon 스키마가 바뀐다 | 마이그레이션은 **VPS 에서, 사장님 승인 후에만.** 현재 `0034_surge_ladder`. (`pytest` 는 안전 — `tests/conftest.py:6` 이 인메모리 SQLite) |
| **`make` 가 없다** | Windows 에 안 깔려 있다(실측) | 설치할 필요 없다. `backend/Makefile` 14개 타깃을 실제 명령으로 푼 표가 섹션 4 §8-5 에 있다 |
| **`http://localhost:8000/` 이 200 이 아니라 307** | 정상이다 | `/` 는 **307 → `/admin-ui`** 로 리다이렉트한다 |
| **로컬 포트 5433 / 6380 이 이미 쓰이고 있다** | 다른 프로그램과 충돌 | ⚠️ **이 경우의 정식 대처가 문서에 없다**(B-6). 포트 매핑을 고치면 다른 절의 명령과 어긋난다 — 고치기 전에 어긋나는 명령을 함께 정리할 것 |

---

> **이 문서를 만든 방식**: 조사관 8명이 실측(VPS 읽기 전용 SSH · 로컬 명령 · GitHub 미인증 API)으로 섹션을 쓰고,
> 검증관 24명이 각 주장을 재실행해 반증·정정한 뒤 하나로 합쳤다.
> **확인하지 못한 것은 「확인 못 함」으로 남겼다** — 이 프로젝트는 추측으로 여러 번 사고가 났다.
