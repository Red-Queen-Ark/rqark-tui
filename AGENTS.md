# Rules
- 禁寫註解
- 禁止 squash merge 同 `git revert`；PR 一律用 merge commit，改錯用新 commit
- 運行 `uv run ruff check --fix` + `uv run ty check --fix`（主力）
- 偶爾行 `uv run pyright` / `uv run mypy` 輔助確認 type safety

# 特點
- app chat 無限 retry 係設計