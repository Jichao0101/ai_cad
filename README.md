# ai_cad

方向盘骨架与发泡的参数化建模原型；当前以手套箱把手底座子流程验证自动执行和改参恢复，方向盘正式 SOR 待定。

- [历史案例与迁移说明](cases/glovebox/README.md)：原始脚本职责、调用关系与冻结约束。
- [独立交付包说明](delivery/glovebox/README.md)：预定义 Pipeline、命令契约和运行环境。
- [模型执行 Skill](delivery/glovebox/skill/glovebox-design/SKILL.md)：需求映射、检查判读与恢复决策。

运行 `python -X utf8 tools/verify_automatic_cli.py` 可验证真实 CATIA 自动构建、自动回退、非法请求和独立交付 ZIP；需要已安装依赖及可访问的 CATIA V5。开发 Qwen 驱动为 `dev/qwen_acceptance.py`，不属于交付包，正式部署保留纯本地要求。

本轮证据位于 `runs/automatic-acceptance-20261114-133635-952301` 与 `runs/qwen-automatic-20261114-133751-963595`。前者包含已实测的 `glovebox-delivery.zip`。本例通过不代表完整手套箱、3DE R2022x 或正式 DS 已验证。
