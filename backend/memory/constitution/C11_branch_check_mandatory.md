# C11. branch 확인 = 필수!

## 원칙
모든 fix + push = **branch 확인 필수!**
사장님 = main branch 사용!
= 모든 fix = **main으로 병합!**

## 사장님 사고
"뭐 이거 하나 변경하는데 이렇게 안되는건지"
= 사장님 = 배포 명령 = 안 됨!
= 원인 = fix branch에만 push했음!
= 사장님 = main branch만!

## 원칙 (v132 신!)
1. fix → fix branch에 commit!
2. **push 전 = main으로 병합!**
3. **push origin main!**
4. 사장님 = `git pull` (기본 main!) = 즉시 반영!

## Git 흐름
```
fix branch:
  git commit -m "..."
  ↓
main branch:
  git checkout main
  git merge fix_branch
  git push origin main
  ↓
사장님 VPS:
  git pull   # main 기본!
  docker restart
```

## 관련 사고
- v132 사고 (레버리지 5x stuck!)
- 사장님 = 1시간 답답!
- 원인 = branch 확인 안 함!

## 앞으로 방지
- 매 push 전 = branch 확인!
- 자동 script = branch validator!

## 관련
- SB026_leverage_5x_stuck
