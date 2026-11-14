"""手套箱 Agent：组织指令和工具，调用模型，并将本地 CAD 执行结果反馈给模型。

Skill 描述执行策略；模型提出动作；本脚本校验并调度动作。
CATIA 建模、检查点恢复和几何测量由 pipeline 负责。
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "glovebox_pipeline", ROOT / "cases/glovebox/pipeline.py"
)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def load_env():
    """读取本地连接配置；已有环境变量优先于文件中的值。"""
    path = ROOT / ".env.local"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, separator, value = line.partition("=")
                if separator:
                    os.environ.setdefault(
                        key.strip(), value.strip().strip(chr(34)).strip(chr(39))
                    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止将带认证信息的模型请求转发到重定向地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API redirects disabled")


def main():
    # 准备输入：工程检查条件由调用端给定，不交给模型自行修改。
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--radius-min", required=True, type=float)
    parser.add_argument("--radius-max", required=True, type=float)
    parser.add_argument("--minimum-volume", required=True, type=float)
    parser.add_argument("--check-source", required=True)
    parser.add_argument("--allow-cloud", action="store_true")
    args = parser.parse_args()
    if (
        not all(
            math.isfinite(v) and v > 0
            for v in (args.radius_min, args.radius_max, args.minimum_volume)
        )
        or args.radius_min > args.radius_max
    ):
        parser.error("Invalid engineering bounds")

    # 准备模型连接：默认只允许本机服务，公网须显式启用且使用 HTTPS。
    load_env()
    endpoint = os.environ.get("QWEN_BASE_URL", "").rstrip("/")
    model = os.environ.get("QWEN_MODEL", "")
    key = os.environ.get("QWEN_API_KEY", "")
    parsed = urlparse(endpoint)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if not endpoint or not model:
        parser.error("Set QWEN_BASE_URL and QWEN_MODEL in ignored .env.local")
    if (
        parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.scheme not in ("http", "https")
    ):
        parser.error("Invalid API endpoint")
    if not local and (not args.allow_cloud or parsed.scheme != "https"):
        parser.error("Public endpoints require HTTPS and --allow-cloud")

    # 1. 组织 Prompt：Skill 给出流程，policy 给出约束，user 给出本次需求。
    # messages 持续累积模型动作和工具反馈，是本次任务的对话记忆。
    skill = (ROOT / ".agents/skills/glovebox-design/SKILL.md").read_text(
        encoding="utf-8"
    )
    skill_hash = hashlib.sha256(skill.encode("utf-8")).hexdigest()
    policy = {
        "radius_min_mm": args.radius_min,
        "radius_max_mm": args.radius_max,
        "minimum_volume_mm3": args.minimum_volume,
        "check_source": args.check_source,
    }
    messages = [
        {
            "role": "system",
            "content": skill + "\nFixed caller constraints: "
            + json.dumps(policy, ensure_ascii=False),
        },
        {"role": "user", "content": args.prompt},
    ]

    # 2. 定义 Tool：向模型公开动作名称与参数结构，不公开 Python 实现。
    # 模型只能提出半径候选；检查阈值和恢复目录由调度器控制。
    tool = {
        "type": "function",
        "function": {
            "name": "run_glovebox",
            "description": "Build historical circular pad; restore checkpoint for each candidate and return measured results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "radius_candidates_mm": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 1,
                        "maxItems": 4,
                    }
                },
                "required": ["radius_candidates_mm"],
                "additionalProperties": False,
            },
        },
    }

    opener = urllib.request.build_opener(NoRedirect)
    # latest 保存真实 CAD 运行状态，与 messages 中的模型表述分开。
    latest = None
    # 六轮限制模型交互次数；CAD 尝试次数另由 pipeline 的配置限制。
    for turn in range(6):
        # 3. 调用模型：每轮提交全部对话，让模型选择回答或请求工具。
        payload = {
            "model": model,
            "messages": messages,
            "tools": [tool],
            "tool_choice": "auto",
        }
        req = urllib.request.Request(
            endpoint + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
        )
        with opener.open(req, timeout=90) as response:
            message = json.load(response)["choices"][0]["message"]

        # 4. 处理模型返回：先保存 assistant 消息，再判断是否有工具动作。
        # 工具结果必须跟在对应动作之后，才能组成下一轮完整的对话。
        calls = message.get("tool_calls", [])
        messages.append({
            k: message[k]
            for k in ("role", "content", "tool_calls")
            if k in message
        })
        if not calls:
            # 直接回答可能是咨询、澄清或总结，不代表 CAD 已成功。
            if latest:
                pipeline.write_json(
                    Path(latest["run_dir"]) / "agent-transcript.json",
                    {
                        "model": model, "skill_sha256": skill_hash,
                        "messages": messages, "policy": policy,
                    },
                )
            print(json.dumps(
                {
                    "assistant": message.get("content"),
                    "cad_status": latest["status"] if latest else "not_executed",
                    "run_dir": latest["run_dir"] if latest else None,
                },
                ensure_ascii=False,
            ))
            return 2 if latest and latest["status"] == "no_solution" else 0

        # 5. 执行工具：模型输出是待校验的动作请求，不能直接执行任意函数。
        for call in calls:
            if call["function"]["name"] != "run_glovebox":
                raise ValueError("Unknown tool")
            arguments = json.loads(call["function"]["arguments"])
            if set(arguments) != {"radius_candidates_mm"}:
                raise ValueError("Unexpected tool arguments")

            # 用调用端条件组装真实请求，避免模型降低检查标准。
            request = {
                **arguments,
                "minimum_volume_mm3": args.minimum_volume,
                "check_source": args.check_source,
            }
            plan = json.loads(pipeline.PLAN.read_text(encoding="utf-8"))
            pipeline.validate_request(request, plan)
            if any(
                not args.radius_min <= r <= args.radius_max
                for r in arguments["radius_candidates_mm"]
            ):
                raise ValueError("Model proposed radius outside caller bounds")
            if latest is not None and latest["status"] != "no_solution":
                raise ValueError("Completed CAD run cannot be repeated")

            # 首次创建运行；候选失败后复用原运行，由 pipeline 恢复检查点。
            # 输入、网络或 CAD 异常会向外抛出，不自动当作可换参失败处理。
            latest = pipeline.run(
                request, resume_run=latest["run_dir"] if latest else None
            )

            # 6. 反馈工具结果：仅发测量摘要，不发 CAD 文件或历史几何数据。
            summary = {
                "remaining_attempts": plan["max_attempts"] - len(latest["attempts"]),
                "status": latest["status"],
                "ds_status": latest["ds_status"],
                "attempts": [
                    {
                        "radius_mm": a["radius_mm"],
                        "measurement": a["after_reopen"],
                        "passed": a["passed"],
                        "reason": a["reason"],
                    }
                    for a in latest["attempts"]
                ],
            }
            # tool_call_id 将实际结果与模型请求对应，下一轮据此改参或结束。
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(summary),
            })
            pipeline.write_json(
                Path(latest["run_dir"]) / "agent-transcript.json",
                {
                    "model": model, "skill_sha256": skill_hash,
                    "messages": messages, "policy": policy,
                },
            )
    raise RuntimeError("Model turn budget exhausted")


if __name__ == "__main__":
    raise SystemExit(main())
