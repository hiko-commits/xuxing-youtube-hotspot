# Render 部署指南

## 前置条件
- GitHub 账号
- Render 账号（https://render.com，可用 GitHub 登录）

---

## Step 1: 创建 GitHub 仓库并推送代码

1. 在 GitHub 创建新仓库（如 `youtube-trending-platform`，Private 即可）
2. 在项目根目录执行：
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<你的用户名>/youtube-trending-platform.git
git push -u origin main
```

> 注意：data/ 目录下的 JSON 文件需要一起推送，这是云端初始化数据的来源。

---

## Step 2: 创建 GitHub Personal Access Token

1. 打开 https://github.com/settings/tokens
2. 点击 **Generate new token (classic)**
3. Note 填 `render-deploy`
4. Expiration 选 **No expiration**（或 1 年）
5. 勾选 **repo**（完整仓库权限）
6. 点击 **Generate token**
7. **立即复制 token**（页面关闭后不可再查看）

---

## Step 3: 在 Render 创建 Web Service

1. 打开 https://dashboard.render.com
2. 点击 **New +** → **Web Service**
3. 连接你的 GitHub 账号，选择 `youtube-trending-platform` 仓库
4. 填写配置：
   - **Name**: `youtube-trending`（或任意名）
   - **Runtime**: `Python 3`
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r ../requirements.txt`
   - **Start Command**: `python app.py`
   - **Instance Type**: `Free`
5. 添加环境变量（点 **Advanced** → **Add Environment Variable**）：

   | Key | Value |
   |-----|-------|
   | `YOUTUBE_API_KEY` | `AIzaSyD7NY23Pvw3AlBydd47O5EHnvfDqvsViVg` |
   | `GITHUB_TOKEN` | （粘贴 Step 2 的 token） |
   | `GITHUB_REPO` | `<你的用户名>/youtube-trending-platform` |
   | `GITHUB_DATA_BRANCH` | `main` |
   | `HOST` | `0.0.0.0` |
   | `FLASK_DEBUG` | `0` |

6. 点击 **Create Web Service**
7. 等待构建完成（约 2-3 分钟），状态变为 **Live** 即可访问
8. 访问地址格式：`https://<你的服务名>.onrender.com/starroad`

---

## Step 4: 在 Render 创建 Cron Job（每日自动刷新）

1. 在 Render Dashboard 点击 **New +** → **Cron Job**
2. 填写配置：
   - **Name**: `daily-refresh`
   - **Runtime**: `Python 3`
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r ../requirements.txt`
   - **Command**: `python daily_refresh.py`
   - **Schedule**: `20 2 * * *`（UTC 02:20 = 北京时间 10:20）
   - **Instance Type**: `Free`
3. 添加同样的环境变量（同 Step 3）
4. 点击 **Create Cron Job**

---

## 工作原理

- **数据持久化**：每次保存数据时，自动同步到 GitHub 仓库的 `data/` 目录。应用重启时自动从 GitHub 拉取最新数据。
- **每日刷新**：Cron Job 每天北京时间 10:20 自动运行，刷新视频和创作者数据，结果同步到 GitHub。
- **休眠机制**：Render 免费版 15 分钟无访问会休眠，下次访问自动唤醒（约 30 秒）。Cron Job 触发时会自动唤醒。
- **本地开发**：不配置 `GITHUB_TOKEN` 环境变量时，代码行为和以前完全一致，只使用本地文件。

---

## 常见问题

**Q: 数据会丢失吗？**
A: 不会。数据保存在 GitHub 仓库中，即使 Render 重启或重新部署，启动时会自动从 GitHub 拉取最新数据。

**Q: 休眠后访问很慢？**
A: 首次唤醒约需 30 秒。可以升级到 Starter 套餐（$7/月）取消休眠限制。

**Q: 如何更新代码？**
A: push 到 GitHub main 分支，Render 会自动重新部署。数据文件不受影响（从 GitHub 同步恢复）。

**Q: 本地还能用吗？**
A: 可以。本地不设环境变量就是纯本地模式，和以前完全一样。
