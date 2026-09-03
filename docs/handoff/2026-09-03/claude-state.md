## Claude Code 로컬 상태 — 저장소 밖 자산

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
