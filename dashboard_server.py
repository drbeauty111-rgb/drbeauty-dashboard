#!/usr/bin/env python3
"""
醫美時尚團隊進度儀表板 - 後端伺服器
啟動方式：python dashboard_server.py
打開瀏覽器到 http://localhost:8080
"""

import http.server
import json
import os
import re
import webbrowser
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# 設定
PORT = 8080
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Team進度.md")
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Markdown 解析與寫回 ─────────────────────────────────────────

def parse_markdown_table(filepath):
    """解析 Markdown 表格，回傳 (metadata, tasks_list)"""
    metadata = {"title": "", "updated": ""}
    tasks = []
    headers = []
    in_table = False
    header_line = None

    if not os.path.exists(filepath):
        return metadata, tasks

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 標題
        if stripped.startswith("# ") and not in_table:
            metadata["title"] = stripped[2:].strip()
        elif stripped.startswith("更新:") or stripped.startswith("更新："):
            metadata["updated"] = stripped.split(":", 1)[-1].strip() if ":" in stripped else stripped.split("：", 1)[-1].strip()

        # 偵測表格開始
        if stripped.startswith("|") and "---" not in stripped and not in_table:
            if "ID" in stripped or "專案名稱" in stripped:
                in_table = True
                header_line = _extract_cells(stripped)
                continue

        # 分隔行跳過
        if in_table and "---" in stripped:
            continue

        # 表格資料行
        if in_table and stripped.startswith("|"):
            cells = _extract_cells(stripped)
            if len(cells) >= 8 and cells[0].strip().isdigit():
                task = {
                    "id": int(cells[0].strip()),
                    "name": cells[1].strip(),
                    "owner": cells[2].strip(),
                    "status": cells[3].strip(),
                    "priority": cells[4].strip(),
                    "deadline": cells[5].strip(),
                    "type": cells[6].strip(),
                    "issue": cells[7].strip(),
                    "note": cells[8].strip() if len(cells) > 8 else "",
                    "_line_index": i  # 記錄行號，方便寫回
                }
                tasks.append(task)
        elif in_table and not stripped.startswith("|"):
            break

    return metadata, tasks


def _extract_cells(line):
    """從 Markdown 表格行中提取儲存格內容"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells = []
    current = ""
    for ch in line:
        if ch == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        cells.append(current.strip())
    return cells


def tasks_to_markdown(metadata, tasks):
    """將 tasks 寫回 Markdown 格式的字串"""
    # 排序：先按狀態（待辦->進行中->已完成->暫停），再按優先級（高->中->低）
    status_order = {"待辦": 0, "進行中": 1, "已完成": 2, "暫停": 3}
    priority_order = {"高": 0, "中": 1, "低": 2}
    sorted_tasks = sorted(tasks, key=lambda t: (
        status_order.get(t["status"], 99),
        priority_order.get(t["priority"], 99),
        t["id"]
    ))

    lines = []
    title = metadata.get("title", "醫美時尚團隊進度儀表板")
    updated = metadata.get("updated", datetime.now().strftime("%Y-%m-%d"))

    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"更新: {updated}")
    lines.append("")
    lines.append("## 任務列表")
    lines.append("")
    lines.append("| ID | 專案名稱 | 負責人 | 狀態 | 優先級 | 截止日 | 專案類型 | 關聯期數 | 備註 |")
    lines.append("|--- |--- |--- |--- |--- |--- |--- |--- |--- |")

    for t in sorted_tasks:
        lines.append(
            f"| {t['id']} | {t['name']} | {t['owner']} | {t['status']} | {t['priority']} | {t['deadline']} | {t['type']} | {t['issue']} | {t['note']} |"
        )

    lines.append("")
    return "\n".join(lines) + "\n"


# 把方法綁到函數上方便呼叫
parse_markdown_table._extract_cells = _extract_cells


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """自訂 HTTP 請求處理器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/tasks":
            metadata, tasks = parse_markdown_table(DATA_FILE)
            self._send_json({"success": True, "metadata": metadata, "tasks": tasks})
        elif path == "/api/tasks/stats":
            metadata, tasks = parse_markdown_table(DATA_FILE)
            stats = self._compute_stats(tasks)
            self._send_json({"success": True, "stats": stats})
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tasks":
            body = self._read_body()
            metadata, tasks = parse_markdown_table(DATA_FILE)

            # 生成新 ID
            new_id = max((t["id"] for t in tasks), default=0) + 1

            task = {
                "id": new_id,
                "name": body.get("name", "新任務"),
                "owner": body.get("owner", "主編"),
                "status": body.get("status", "待辦"),
                "priority": body.get("priority", "中"),
                "deadline": body.get("deadline", ""),
                "type": body.get("type", "月刊"),
                "issue": body.get("issue", ""),
                "note": body.get("note", "")
            }
            tasks.append(task)

            # 更新時間戳
            metadata["updated"] = datetime.now().strftime("%Y-%m-%d")

            markdown_content = tasks_to_markdown(metadata, tasks)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            self._send_json({"success": True, "task": task}, 201)

            # 同時匯出靜態 data.json 給 GitHub Pages
            self._export_data_json(metadata, tasks)

    def _export_data_json(self, metadata, tasks):
        """匯出 data.json 供 GitHub Pages 靜態載入"""
        import json as json_mod
        data = {
            "success": True,
            "metadata": metadata,
            "tasks": [{k: v for k, v in t.items() if k != '_line_index'} for t in tasks]
        }
        data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json_mod.dump(data, f, ensure_ascii=False, indent=2)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/tasks/"):
            task_id = int(parsed.path.split("/")[-1])
            body = self._read_body()
            metadata, tasks = parse_markdown_table(DATA_FILE)

            found = False
            for t in tasks:
                if t["id"] == task_id:
                    if "name" in body:
                        t["name"] = body["name"]
                    if "owner" in body:
                        t["owner"] = body["owner"]
                    if "status" in body:
                        t["status"] = body["status"]
                    if "priority" in body:
                        t["priority"] = body["priority"]
                    if "deadline" in body:
                        t["deadline"] = body["deadline"]
                    if "type" in body:
                        t["type"] = body["type"]
                    if "issue" in body:
                        t["issue"] = body["issue"]
                    if "note" in body:
                        t["note"] = body["note"]
                    found = True
                    break

            if found:
                metadata["updated"] = datetime.now().strftime("%Y-%m-%d")
                markdown_content = tasks_to_markdown(metadata, tasks)
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                self._send_json({"success": True, "task": next(t for t in tasks if t["id"] == task_id)})
                self._export_data_json(metadata, tasks)
            else:
                self._send_json({"success": False, "error": "找不到該任務"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/tasks/"):
            task_id = int(parsed.path.split("/")[-1])
            metadata, tasks = parse_markdown_table(DATA_FILE)

            original_len = len(tasks)
            tasks = [t for t in tasks if t["id"] != task_id]

            if len(tasks) < original_len:
                metadata["updated"] = datetime.now().strftime("%Y-%m-%d")
                markdown_content = tasks_to_markdown(metadata, tasks)
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                self._send_json({"success": True, "deleted_id": task_id})
                self._export_data_json(metadata, tasks)
            else:
                self._send_json({"success": False, "error": "找不到該任務"}, 404)

    def _compute_stats(self, tasks):
        """計算統計數據"""
        total = len(tasks)
        by_status = {}
        by_owner = {}
        by_type = {}
        for t in tasks:
            s = t["status"]
            o = t["owner"]
            tp = t["type"]
            by_status[s] = by_status.get(s, 0) + 1
            by_owner[o] = by_owner.get(o, 0) + 1
            by_type[tp] = by_type.get(tp, 0) + 1

        # 每人完成率
        completion_rate = {}
        for o in set(t["owner"] for t in tasks):
            owned = [t for t in tasks if t["owner"] == o]
            done = sum(1 for t in owned if t["status"] == "已完成")
            completion_rate[o] = {
                "total": len(owned),
                "completed": done,
                "rate": round(done / len(owned) * 100) if owned else 0
            }

        return {
            "total": total,
            "by_status": by_status,
            "by_owner": by_owner,
            "by_type": by_type,
            "completion_rate": completion_rate
        }

    def log_message(self, format, *args):
        """自訂 log 輸出"""
        msg = format % args
        print(f"  [伺服器] {msg}")


def main():
    # 啟動時先匯出 data.json
    metadata, tasks = parse_markdown_table(DATA_FILE)
    handler = DashboardHandler.__new__(DashboardHandler)
    handler._export_data_json(metadata, tasks)

    server = http.server.HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print("")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   醫美時尚團隊進度儀表板 v1.0            ║")
    print("  ╠══════════════════════════════════════════╣")
    print(f"  ║   http://localhost:{PORT}                 ║")
    print(f"  ║   資料檔: {os.path.basename(DATA_FILE)}          ║")
    print("  ╠══════════════════════════════════════════╣")
    print("  ║   Ctrl+C 停止伺服器                     ║")
    print("  ╚══════════════════════════════════════════╝")
    print("")

    # 嘗試自動開啟瀏覽器
    try:
        webbrowser.open(f"http://localhost:{PORT}")
        print("  瀏覽器已自動開啟...")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  伺服器已停止。")


if __name__ == "__main__":
    main()
