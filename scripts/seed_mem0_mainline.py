"""将 project_mainline_seed.md 中的种子记忆写入 Mem0。"""

import os
import re
import sys
import time

from mem0 import MemoryClient

SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "hermes", "memory", "project_mainline_seed.md",
)


def parse_seed_file(path: str) -> list[dict]:
    """解析种子文件，提取每条记忆。"""
    with open(path) as f:
        content = f.read()

    # Split by "## N. " sections
    sections = re.split(r'\n(?=## \d+\. )', content)
    entries = []

    for section in sections:
        # Extract memory_type from heading "## N. memory_type"
        m = re.match(r'## \d+\. (\w+)', section)
        if not m:
            continue
        mem_type = m.group(1)

        # Extract importance: **重要性**: high
        imp_match = re.search(r'\*\*重要性\*\*:\s*(\w+)', section)
        importance = imp_match.group(1) if imp_match else "medium"

        # Extract tags: **标签**: a, b, c
        tag_match = re.search(r'\*\*标签\*\*:\s*(.+)', section)
        tags = [t.strip() for t in tag_match.group(1).split(",")] if tag_match else []

        # Extract content: everything between tags line and the end (or next ---)
        # Remove the heading line and metadata lines
        lines = section.strip().split("\n")
        content_lines = []
        in_meta = True
        for line in lines:
            # Skip heading
            if re.match(r'^## \d+\.', line):
                continue
            # Skip blank lines before meta
            if in_meta and not line.strip():
                continue
            # Meta line
            if re.match(r'\*\*重要性\*\*:', line) or re.match(r'\*\*标签\*\*:', line):
                continue
            # After meta, blank line triggers content start
            if in_meta and not line.strip():
                in_meta = False
                continue
            if not in_meta:
                content_lines.append(line)
            else:
                # Direct content (no blank after meta)
                in_meta = False
                content_lines.append(line)

        text = "\n".join(content_lines).strip()
        # Remove trailing ---
        text = re.sub(r'\n---\s*$', '', text)

        if text:
            entries.append({
                "memory_type": mem_type,
                "importance": importance,
                "tags": tags,
                "content": text,
            })

    return entries


def main():
    if not os.environ.get("MEM0_API_KEY"):
        print("ERROR: MEM0_API_KEY not set")
        sys.exit(1)

    entries = parse_seed_file(SEED_PATH)
    if not entries:
        print("ERROR: No entries found in seed file")
        sys.exit(1)

    print(f"Parsed {len(entries)} entries from {SEED_PATH}")
    client = MemoryClient()

    for i, entry in enumerate(entries):
        try:
            result = client.add(
                messages=[{"role": "user", "content": entry["content"]}],
                app_id="finance_analysis_system",
                metadata={
                    "scope": "project_mainline",
                    "project_id": "finance_analysis_system",
                    "memory_type": entry["memory_type"],
                    "importance": entry["importance"],
                    "tags": entry["tags"],
                    "source": "seed_import",
                },
            )
            status = result.get("status", "OK")
            print(f"  [{i + 1}/{len(entries)}] {entry['memory_type']}: {status}")
        except Exception as e:
            print(f"  [{i + 1}/{len(entries)}] {entry['memory_type']}: ERROR - {e}")
        time.sleep(0.5)

    print(f"\nDone! {len(entries)} seed memories written to Mem0.")


if __name__ == "__main__":
    main()
