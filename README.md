# pyNDB

> 基于 Flask 的 Web 数据库管理工具，支持 MySQL / PostgreSQL，提供直连与 SSH 隧道两种连接模式。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-green)
![MySQL](https://img.shields.io/badge/MySQL-5.7%2B-orange)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-10%2B-336791)

---

## 功能概览

| 功能模块 | 说明 |
|----------|------|
| **连接管理** | 支持保存多个数据库连接，组织管理（新增 / 编辑 / 删除 / 分组） |
| **直连模式** | 数据库端口开放时直接通过 TCP 连接 MySQL 或 PostgreSQL |
| **SSH 隧道** | 仅开放 22 端口时，通过 SSH 隧道转发至目标数据库（密码 / 私钥认证） |
| **测试连接** | 保存前可测试连通性，返回数据库版本与延迟 |
| **SQL 执行器** | 多行 SQL 编辑，支持 SELECT / INSERT / UPDATE / DELETE / CREATE 等 |
| **危险操作确认** | DELETE 无 WHERE、DROP TABLE 等操作需二次确认 |
| **元数据查看** | 查看表结构、字段信息、索引与外键 |
| **可视化建表** | 表单填写字段 → DDL 预览 → 执行建表 |
| **数据导出** | 查询结果导出为 CSV 或 JSON |
| **查询历史** | 自动记录所有执行的 SQL，可按连接过滤 |
| **密码加密** | 连接密码、SSH 密钥使用 Fernet (AES) 加密存储 |
| **请求日志** | 文件和终端双输出，记录每次请求方法与路径 |

---

## 快速启动

```bash
# 1. 克隆/进入项目目录
cd D:\work\pyNDB

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python run.py
```

打开浏览器访问 `http://127.0.0.1:7007`。

> 端口通过环境变量 `PORT` 配置（默认 7007）。

---

## 使用指南

### 连接数据库

1. 点击左侧 **+ 新建** → 弹出连接表单
2. 填写连接信息：
   - **连接名称**：自定义标识
   - **数据库类型**：MySQL / PostgreSQL
   - **连接模式**：直连 / SSH 隧道
   - **主机 / 端口 / 用户名 / 密码 / 数据库名**
3. 点击 **测试连接** 校验连通性
4. 点击 **保存** → 连接出现在左侧列表

### 直连模式

```
数据库端口开放（MySQL 3306 / PostgreSQL 5432）
├─ host          → 服务器地址
├─ port          → 监听端口
├─ username      → 数据库用户
├─ password      → 密码
└─ database      → 默认数据库
```

### SSH 隧道模式

```
仅开放 22 端口时
├─ SSH 主机      → 跳板机地址
├─ SSH 端口      → 默认 22
├─ SSH 用户名    → 登录用户
├─ 认证方式      → 密码 / 私钥
│   ├─ 密码      → SSH 密码
│   └─ 私钥      → -----BEGIN RSA PRIVATE KEY-----
├─ 目标数据库地址 → 内网数据库 IP
├─ 目标数据库端口 → 3306 / 5432
└─ 数据库认证    → 用户名 + 密码
```

### 执行 SQL

1. 从左侧选择连接 → 右键或双击打开
2. 在上方编辑器中输入 SQL
3. 点击 **执行** (或 `Ctrl+Enter`) 运行
4. 结果在下方表格展示

危险 SQL（如 `DELETE FROM` 不带 `WHERE`）会弹出二次确认。

### 查看表结构

点击表名打开标签 → 点击 **表结构** 即可查看字段、索引、外键。

### 新建表

1. 选中连接 → 点击 **建表**
2. 填写表名与字段信息（字段名、类型、主键、自增等）
3. 点击 **预览 DDL** 查看生成的建表语句
4. 确认无误后点击 **创建表**

---

## API 接口

所有接口前缀 `/api/v1`。

### 连接管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/connections` | 获取所有连接 |
| GET | `/connections/{id}` | 获取单个连接详情 |
| POST | `/connections` | 新建连接 |
| PUT | `/connections/{id}` | 更新连接 |
| DELETE | `/connections/{id}` | 删除连接 |
| POST | `/connections/test` | 测试新连接 |
| POST | `/connections/{id}/test` | 测试保存的连接 |
| POST | `/connections/{id}/connect` | 建立连接 |
| POST | `/connections/{id}/disconnect` | 断开连接 |
| GET | `/connections/groups` | 获取连接分组 |

### SQL 执行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/query/execute` | 执行 SQL |
| POST | `/query/force-execute` | 强制执行（危险确认后） |
| GET | `/query/history` | 查询历史 |

### 元数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/metadata/databases` | 获取数据库列表 |
| GET | `/metadata/tables` | 获取表列表 |
| GET | `/metadata/views` | 获取视图列表 |
| GET | `/metadata/table/describe` | 获取表结构 |

### 表操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/table/preview-ddl` | 预览 DDL |
| POST | `/table/create` | 创建表 |
| GET | `/table/data` | 获取表数据 |

### 导出

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/export/csv` | 导出 CSV |
| POST | `/export/json` | 导出 JSON |

---

## 项目结构

```
pyNDB/
├── app.py                   # Flask 应用入口，注册蓝图与中间件
├── run.py                   # 启动脚本
├── requirements.txt         # 项目依赖
├── README.md                # 本文件
│
├── api/
│   ├── routes.py            # API 路由（连接管理、SQL 执行、元数据、导出）
│   └── __init__.py
│
├── models/
│   ├── database.py          # 数据模型（连接配置 CRUD、查询历史记录）
│   └── __init__.py
│
├── utils/
│   ├── db_manager.py        # 数据库连接管理器（直连 / SSH 隧道执行 SQL）
│   ├── security.py          # Fernet (AES) 加密工具
│   ├── log_config.py        # 统一日志配置（控制台 + 文件双输出）
│   ├── launcher.py          # 启动器（单实例检测、托盘图标、自动开浏览器）
│   ├── runtime.py           # 路径工具（源码 / PyInstaller 打包兼容）
│   └── __init__.py
│
├── templates/
│   └── index.html           # 单页 Web 前端（暗色主题）
│
├── static/                  # 前端静态文件（可选）
├── data/
│   ├── pyndb.db             # SQLite 元数据库（连接配置、查询历史）
│   └── .fernet_key          # AES 加密密钥
│
├── logs/
│   └── pyndb.log            # 运行日志（自动滚动）
│
├── dist/                    # PyInstaller 打包输出
│   └── PyNDB.exe
│
└── build/                   # 打包中间文件
```

---

## 安全说明

- **密码加密**：数据库密码、SSH 密码、SSH 私钥均使用 **Fernet (AES)** 加密后存入 SQLite
- **密钥管理**：加密密钥存储在 `data/.fernet_key`，可通过环境变量 `FERNET_KEY` 自定义持久化密钥
- **日志脱敏**：日志中不会输出明文密码或完整连接字符串
- **危险 SQL 防护**：DELETE 无 WHERE、DROP TABLE 等操作需二次确认
- **只读保护**：可配合数据库只读账户限制 DML / DDL 操作

---

## 打包部署

项目支持使用 PyInstaller 打包为单文件 exe：

```bash
pip install pyinstaller
pyinstaller PyNDB.spec
```

打包后在 `dist/PyNDB.exe`，双击运行：
- 自动检测端口是否已被占用（单实例）
- 自动打开浏览器
- 系统托盘图标（右键可打开界面 / 退出）
- 日志文件位于 exe 同目录下的 `logs/pyndb.log`

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `7007` | 监听端口 |
| `FERNET_KEY` | 自动生成 | AES 加密密钥（如需持久化请设置） |
| `PYNDDB_NO_BROWSER` | 0 | 设为 `1` 不自动打开浏览器 |
| `PYNDDB_NO_TRAY` | 0 | 设为 `1` 不使用托盘图标（打包模式） |
| `PYNDDB_TRAY` | 0 | 设为 `1` 源码模式下强制启用托盘图标 |

---

## 技术栈

- **后端**：Python 3.10+ / Flask 3.x / PyMySQL / psycopg2-binary
- **SSH 隧道**：Paramiko + sshtunnel
- **加密**：cryptography (Fernet)
- **前端**：原生 HTML/CSS/JS（暗色主题）
- **存储**：SQLite（连接配置、查询历史）
- **打包**：PyInstaller（支持托盘图标）

---

## 开发

```bash
# 开发模式启动
cd D:\work\pyNDB
python run.py

# 日志输出
# 控制台: 直接查看终端
# 文件:    logs/pyndb.log
```

---

## 数据库兼容性

| 数据库 | 驱动 | 最低版本 | 直连 | SSH 隧道 |
|--------|------|----------|------|----------|
| MySQL | PyMySQL | 5.7+ | ✅ | ✅ |
| MariaDB | PyMySQL | 10.2+ | ✅ | ✅ |
| PostgreSQL | psycopg2 | 10+ | ✅ | ✅ |

---

## 许可

MIT License