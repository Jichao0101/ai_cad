---
name: glovebox-design
description: 按交付 Skill 自动建立手套箱圆形凸台，在检查失败时提交参数变化，由执行器计算恢复位置并重跑。
---

# 加载交付 Skill

先读取本仓库 delivery/glovebox/skill/glovebox-design/SKILL.md，按其中步骤执行。独立 CLI 位于 delivery/glovebox/cad_cli.py，交付说明位于 delivery/glovebox/README.md。

本入口仅负责发现和定位，实际操作与恢复规则只在交付 Skill 中维护。不要调用旧 run_glovebox 接口。
