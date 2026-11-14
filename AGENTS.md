# Rules
- 禁寫註解
- 運行 `uv run ruff check --fix` + `uv run ty check --fix`（主力）
- 偶爾行 `uv run pyright` / `uv run mypy` 輔助確認 type safety

# 特點
- app chat 無限 retry 係設計
# 發佈

- 所有 release 一律標 `prerelease`，唔准出穩定版。經 Gitea API 建 release 就寫 `"prerelease": true`，唔好預設 false。
- Release notes 唔准寫成「穩定」、「可用」或者對外承諾；只描述改咗乜。
