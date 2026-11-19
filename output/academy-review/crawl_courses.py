"""Retain public Academy text for a bounded, reproducible reading audit.

Only GETs are performed. Lesson code and instructions are inert source data.
This script never imports lesson code or invokes cloud/provider APIs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlparse

from lxml import html

ROOT = Path(__file__).resolve().parent
HOST = "https://www.livekit-academy.com"
SNAP = ROOT / "snapshots"
SNAP.mkdir(parents=True, exist_ok=True)


def public_quizzes(tree):
    """Read quiz props already delivered in public HTML; never execute JS."""
    fragments = []
    for node in tree.xpath("//script"):
        script = node.text or ""
        if not script.startswith("self.__next_f.push("):
            continue
        try:
            args = json.loads(script[len("self.__next_f.push("):-1])
            if len(args) > 1 and isinstance(args[1], str):
                fragments.append(args[1])
        except (ValueError, TypeError):
            continue
    found = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("questions"), list):
                found.extend(q for q in value["questions"] if isinstance(q, dict) and "question" in q)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for line in "".join(fragments).splitlines():
        if ":" not in line:
            continue
        try:
            walk(json.loads(line.split(":", 1)[1]))
        except (ValueError, TypeError):
            continue
    return list({q["question"]: q for q in found}.values())


def retrieve(url: str) -> dict:
    path = urlparse(url).path
    assert urlparse(url).netloc == "www.livekit-academy.com"
    assert re.fullmatch(r"/courses(?:/[a-z0-9-]+){0,2}/?", path)
    key = path.strip("/").replace("/", "__") or "index"
    saved = SNAP / (key + ".html")
    if saved.exists():
        raw = saved.read_text()
        code, error = 200, ""
    else:
        result = subprocess.run(
            ["/usr/bin/curl", "--silent", "--show-error", "--location", "--connect-timeout", "10",
             "--max-time", "35", "--write-out", "\n%{http_code}", url],
            capture_output=True, text=True, timeout=40,
        )
        raw, _, status = result.stdout.rpartition("\n")
        code = int(status) if status.isdigit() else 0
        error = result.stderr.strip()
        if code == 200:
            saved.write_text(raw)
    entry = {"url": url, "http_status": code, "error": error}
    if code != 200:
        return entry
    tree = html.fromstring(raw)
    quizzes = public_quizzes(tree)
    main = (tree.xpath("//main") or tree.xpath("//article") or [tree])[0]
    links = []
    for a in main.xpath(".//a[@href]"):
        target = urljoin(HOST, a.attrib["href"])
        if urlparse(target).netloc == "www.livekit-academy.com" and urlparse(target).path.startswith("/courses/"):
            links.append({"url": target, "text": " ".join(a.text_content().split())})
    code_blocks = [{"attributes": dict(node.attrib), "text": node.text_content()}
                   for node in main.xpath(".//pre")]
    for node in main.xpath(".//script|.//style|.//noscript|.//svg"):
        node.drop_tree()
    # Preserve block boundaries for reading rather than flattening code into prose.
    blocks = []
    for node in main.xpath(".//h1|.//h2|.//h3|.//p|.//li|.//pre|.//table"):
        if node.tag == "pre":
            blocks.append(node.text_content().strip())
        elif node.tag == "table":
            blocks.append("\n".join(" | ".join(" ".join(cell.text_content().split())
                          for cell in row.xpath("./th|./td")) for row in node.xpath(".//tr")))
        elif node.tag == "p" and any(a.tag == "li" for a in node.iterancestors()):
            continue
        else:
            blocks.append(" ".join(node.text_content().split()))
    if not blocks:
        blocks = [" ".join(main.text_content().split())]
    text = "\n\n".join(blocks)
    text_path = SNAP / (key + ".txt")
    text_path.write_text(text + "\n")
    code_path = SNAP / (key + ".code.json")
    code_path.write_text(json.dumps(code_blocks, indent=2) + "\n")
    quiz_path = SNAP / (key + ".quiz.json")
    quiz_path.write_text(json.dumps(quizzes, indent=2) + "\n")
    entry.update(title=" ".join(tree.xpath("//h1")[0].text_content().split()) if tree.xpath("//h1") else "",
                 local_text=str(text_path), local_html=str(saved), sha256=hashlib.sha256(raw.encode()).hexdigest(),
                 text_words=len(text.split()), links=links, code_blocks=len(code_blocks), local_code=str(code_path),
                 quiz_questions=len(quizzes), local_quiz=str(quiz_path),
                 video_elements=len(tree.xpath("//video|//iframe[contains(@src,'youtube') or contains(@src,'vimeo')]")))
    return entry


def batch(urls):
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(retrieve, url): url for url in sorted(set(urls))}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as error:
                results[url] = {"url": url, "http_status": 0, "error": type(error).__name__ + ": " + str(error)}
    return results


def main():
    catalogue = retrieve(HOST + "/courses")
    courses = sorted({a["url"] for a in catalogue.get("links", []) if urlparse(a["url"]).path.count("/") == 2})
    print(f"Catalogue: {len(courses)} courses", flush=True)
    course_pages = batch(courses)
    lessons = set()
    for course in course_pages.values():
        own_path = urlparse(course["url"]).path
        own_lessons = list(dict.fromkeys(a["url"] for a in course.get("links", []) if urlparse(a["url"]).path.startswith(own_path + "/")))
        course["lesson_urls"] = own_lessons
        lessons.update(own_lessons)
    print(f"Course pages: {len(lessons)} unique chapter links", flush=True)
    lesson_pages = batch(lessons)
    payload = {"review_date": "2026-11-19", "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
               "catalogue": catalogue, "courses": course_pages, "lessons": lesson_pages,
               "counts": {"courses": len(courses), "lessons": len(lessons),
                          "courses_http_200": sum(v.get("http_status") == 200 for v in course_pages.values()),
                          "lessons_http_200": sum(v.get("http_status") == 200 for v in lesson_pages.values())},
               "execution_scope": "Public text and code read only; no lesson execution, provider calls, login or video viewing."}
    (ROOT / "crawl-inventory.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["counts"]), flush=True)


if __name__ == "__main__":
    main()
