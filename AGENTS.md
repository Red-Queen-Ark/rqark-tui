# AGENTS.md

## Contributing
> Issue、commit、PR、release、版本號一律跟 `CONTRIBUTING.md`。

# Rules
- 禁寫註解
- 禁止 squash merge 同 `git revert`；PR 一律用 merge commit，改錯用新 commit
- 運行 `uv run ruff check --fix` + `uv run ty check --fix`（主力）
- 偶爾行 `uv run pyright` / `uv run mypy` 輔助確認 type safety
- PEP 758：`except A, B:` 同 `except* A, B:` 係合法語法，不得判定為 Python 2、語法錯誤，或自動補括號；`except (A, B) as e:` 括號仍然必要

# Remote 同 mirror
- GitHub 係 mirror，會自動同步 commit 同 tag；release 要手動開

# 特點
- app chat 無限 retry 係設計