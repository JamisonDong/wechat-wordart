#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# 一键创建 GitHub Repo 并推送 wechat-wordart 项目
# 前置条件：已安装并登录 gh CLI（brew install gh && gh auth login）
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_NAME="wechat-wordart"
DESCRIPTION="微信聊天记录 → 分词统计 → SVG 词画 → 墨水屏展示"

echo "🚀 创建 GitHub 仓库 $REPO_NAME ..."
gh repo create "$REPO_NAME" \
  --public \
  --description "$DESCRIPTION" \
  --source=. \
  --remote=origin \
  --push

echo ""
echo "✅ 推送完成！"
echo "   仓库地址：https://github.com/$(gh api user --jq .login)/$REPO_NAME"
