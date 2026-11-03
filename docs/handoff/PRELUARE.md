# Preluare

Se execută când proprietarul scrie „preia” (sau `/preia`). Continui munca unui agent anterior.

1. **Citește** `AGENTS.md` și `PROGRESS.md`; din `docs/PLAN.md` doar regulile comune și secțiunea etapei tale.
   Respectă „Economie de usage” din `AGENTS.md`.
2. **Verifică agentul.** Dacă etapa următoare e marcată pentru alt agent în „Cine face ce” (de ex. o etapă Claude Code
   și tu ești Antigravity), spune-i proprietarului ce agent să deschidă și oprește-te.
3. **Vezi starea reală:** `git fetch --all --prune`, `git status`, `git log --oneline -10`, `scripts/check_fast.sh`.
4. **Treci pe branch-ul corect** (din „Pasul următor exact” sau din tabel); dacă există doar pe GitHub: `git checkout <branch>`, `git pull`.
5. **Reconciliază.** Dacă `PROGRESS.md` nu se potrivește cu git, crede git-ul: corectează `PROGRESS.md`, commit
   `preluare: reconciliere PROGRESS.md`, push.
6. **Repară testele roșii** înainte de orice altceva.
7. **Continuă** doar cu sub-pasul din „Pasul următor exact”, după protocolul din `AGENTS.md` (commit + push + `PROGRESS.md`).
   La final îi spui proprietarului să deschidă o conversație nouă și să scrie „preia”.
