"""只读检查方向盘参考件的工作副本，输出特征树和参数供操作映射使用。"""
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


def collection(items):
    for index in range(1, items.Count + 1):
        yield items.Item(index)


def hybrid_tree(bodies):
    return [{"name": body.Name,
             "features": [obj.Name for obj in collection(body.HybridShapes)],
             "children": hybrid_tree(body.HybridBodies)}
            for body in collection(bodies)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if source.suffix.lower() != ".catpart":
        parser.error("source must be a CATPart")
    root = Path(__file__).resolve().parents[1] / "runs" / datetime.now().strftime("steering-inspection-%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True)
    copy = root / source.name
    shutil.copy2(source, copy)
    report = {"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "copy": str(copy), "status": "connecting"}
    # 保存版本标记只作兼容性线索，不据此推断最低读取版本。
    report["embedded_release_markers"] = sorted({value.decode("ascii") for value in
        re.findall(rb"V5R\d+SP\d+HF\d+", source.read_bytes())})
    output = root / "inspection.json"

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(report["status"], str(output), flush=True)

    save()
    import win32com.client
    app = win32com.client.GetActiveObject("CATIA.Application")
    report.update(client=app.FullName, status="opening")
    save()
    doc = None
    try:
        doc = app.Documents.Open(str(copy))
        part = doc.Part
        report["bodies"] = [{"name": body.Name,
                             "features": [obj.Name for obj in collection(body.Shapes)],
                             "sketches": [obj.Name for obj in collection(body.Sketches)]}
                            for body in collection(part.Bodies)]
        report["hybrid_bodies"] = hybrid_tree(part.HybridBodies)
        report["parameters"] = []
        for param in collection(part.Parameters):
            entry = {"name": param.Name}
            try:
                entry["value"] = param.ValueAsString()
            except Exception as exc:
                entry["unreadable"] = str(exc)
            report["parameters"].append(entry)
        report["status"] = "inspected"
        save()
    except Exception as exc:
        report.update(status="error", error=str(exc))
        save()
        raise
    finally:
        if doc is not None:
            doc.Close()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == report["sha256"]


if __name__ == "__main__":
    main()
