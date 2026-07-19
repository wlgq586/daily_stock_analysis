# 项目部署指南

## 前置条件

```bash
# CentOS
yum install -y git
# Docker（参考官网）https://docs.docker.com/engine/install/centos/
yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
```

## 1. 拉代码

```bash
mkdir -p /home/stock/code && cd /home/stock/code
git clone https://github.com/xxx/daily_stock_analysis.git
cd daily_stock_analysis
```

## 2. 配置 .env

```bash
cp .env.example .env
vim .env
```

必填项：

| 配置项 | 说明 |
|--------|------|
| `OPENAI_API_KEY` 或 `LLM_CHANNELS` | LLM 模型配置 |
| `FEISHU_WEBHOOK_URL` | 飞书通知（分析完成后推送） |
| `FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `FEISHU_STREAM_ENABLED=true` | 飞书机器人交互（@机器人发指令） |
| `TAVILY_API_KEYS` | 新闻搜索（免费注册 tavily.com） |

注意事项：
- **Web UI 里保存的设置不会自动写回 .env**，容器启动只读 .env，所以配置首选直接 `vim .env`
- 不需要引号，格式：`KEY=value`
- 含 `#` 或空格的值需要引号：`KEY="val#ue"`

## 3. 创建持久化目录

```bash
mkdir -p /home/stock/{data,logs,reports}
```

## 4. 数据迁移（可选）

如果从旧服务器迁移数据库：

```bash
# 先在旧服务器上停掉 Docker，确保 SQLite WAL 已写入主文件
docker compose -f ./docker/docker-compose.yml down

# 传输三个文件（.db + .db-wal + .db-shm）
scp /home/stock/data/stock_analysis.db* root@新服务器:/home/stock/data/

# 新服务器上修正文件权限（容器内运行用户 UID 通常是 1000）
chown -R 1000:1000 /home/stock/{data,logs,reports}
```

> ⚠️ SQLite 使用 WAL 模式，只传 .db 不传 .db-wal/.db-shm 会导致数据丢失。

## 5. 构建并启动

```bash
cd /home/stock/code/daily_stock_analysis
docker compose -f ./docker/docker-compose.yml up -d --build
```

> `docker compose` 是空格，不是连字符（Docker Compose v2）。

两个容器启动后：

```bash
docker ps
# stock-server  → Web 服务（端口 8000）
# stock-analyzer → 定时分析 + K线更新
```

## 6. 验证

```bash
# 检查 Web 页面
curl -I http://localhost:8000

# 检查通知配置
docker compose -f ./docker/docker-compose.yml exec -u dsa analyzer python main.py --check-notify

# 检查飞书 Stream
docker compose -f ./docker/docker-compose.yml logs server --tail=20 | grep -i feishu

# 手动触发一次分析
docker compose -f ./docker/docker-compose.yml exec -u dsa analyzer python main.py --stocks 600519
```

## 7. 开放防火墙

```bash
firewall-cmd --add-port=8000/tcp --permanent
firewall-cmd --reload
```

云服务器还需要在安全组放行 TCP 8000。

---

## 常用命令

```bash
# 重启所有服务
docker compose -f ./docker/docker-compose.yml down
docker compose -f ./docker/docker-compose.yml up -d

# 仅重启（不重新构建）
docker compose -f ./docker/docker-compose.yml restart

# 重新构建并重启（代码有更新时）
docker compose -f ./docker/docker-compose.yml up -d --build

# 查看日志
docker compose -f ./docker/docker-compose.yml logs -f --tail=50

# 查看指定服务日志
docker compose -f ./docker/docker-compose.yml logs analyzer --tail=50
docker compose -f ./docker/docker-compose.yml logs server --tail=50

# 进入容器
docker compose -f ./docker/docker-compose.yml exec -u dsa analyzer bash

# 查看容器状态
docker ps

# 停止所有
docker compose -f ./docker/docker-compose.yml down
```

---

## 注意事项

1. **命令格式**：始终用 `docker compose`（空格），不是 `docker-compose`（连字符）。
2. **配置优先级**：`.env` > Web UI 设置。改了 Web UI 里的设置不等于改了 .env，容器重启后以 .env 为准。
3. **SQLite 迁移**：必须同时传输 `.db`、`.db-wal`、`.db-shm` 三个文件，且运行中的程序要先停掉。
4. **文件权限**：容器内运行用户 UID 为 1000（dsa），挂载的持久化目录权限必须匹配，否则写入会报 `PermissionError`。
5. **飞书机器人**：Stream 模式运行在 `server` 容器（非 `analyzer`），飞书开放平台需要开权限 + 订阅事件 + 发布版本才能生效。
6. **K线数据**：analyzer 容器每天自动更新全量 A 股 K 线，24 小时一次。
7. **首次构建慢**：Docker 内已配置国内镜像源（npm/pip/apt），首次构建约 5-15 分钟。
