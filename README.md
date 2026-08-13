# 绿植招采线索运营台（spiderman_with_kimi_webbridge）

固定源站增量抓取招投标/政府采购公告 → 清洗 → MySQL → 本地只读台账，持续产出绿植租摆/绿化养护类商机线索。

## 快速开始

```bash
# 1. 准备环境
pip install -r requirements.txt
cp .env.example .env        # 填入 MYSQL_* 真实凭证

# 2. 初始化库表
python scripts/init_db.py
python scripts/migrate_ops.py
python scripts/jobs/seed_keywords.py

# 3. 连通自检
python scripts/verify_db_cn.py

# 4. 单站试跑
python scripts/jobs/run_one_source.py ggzy --keywords 绿植租摆 --pages 1

# 5. 全量增量
python scripts/jobs/run_incremental.py --pages 1

# 6. 本地台账（只读 API + UI）
python scripts/jobs/serve_ledger.py
# 浏览器打开 http://127.0.0.1:8765/
```

## 测试

```bash
python scripts/run_tests.py
# 真实外网抓取用例默认跳过；需要时：
#   Windows: $env:SPIDER_LIVE_TESTS="1"; python scripts/run_tests.py
#   Linux/macOS: SPIDER_LIVE_TESTS=1 python scripts/run_tests.py
```

## 文档

产品范围、架构、反爬、数据模型、阶段验收等**唯一过程文档源**在 `.cursor/docs/`（入口 `.cursor/docs/README.md`）。产品侧只看阶段勾选与 `testing/验收清单.md`。

机器可读配置在 `config/*.json`；冲突时以 `.cursor/docs/` 的产品决策为准并回写配置。

## 凭证

数据库/账号凭证只存 `.env`（已 gitignore），**禁止提交、禁止写入代码**。
