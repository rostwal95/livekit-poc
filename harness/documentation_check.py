"""Validate the documented ecosystem corpus without certifying product behavior."""

import argparse
import fnmatch
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
# Every document opens with one Field/Value card holding exactly these rows, in order.
CARD_FIELDS = ("Status", "Purpose", "Audience", "Scope", "Owns", "Related")
LEGACY_METADATA = ("Status:", "Last reviewed:")
MANIFEST_KEYS = {
    "schemaVersion",
    "include",
    "requiredDocuments",
    "statuses",
    "roles",
    "forbiddenTerms",
    "forbiddenPatterns",
}


class DocumentationError(ValueError):
    """Invalid documentation policy or a path outside the repository."""


def safe_path(root, value):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or Path(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise DocumentationError("invalid repository-relative policy path")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise DocumentationError("policy path escapes repository")
    return path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DocumentationError("duplicate documentation policy field")
        result[key] = value
    return result


def string_list(value, label, allow_empty=False):
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise DocumentationError(f"invalid {label} policy")


def load_manifest(root, relative="harness/documentation.json"):
    try:
        policy = json.loads(
            safe_path(root, relative).read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    except (OSError, json.JSONDecodeError) as error:
        raise DocumentationError("documentation policy is missing or invalid JSON") from error
    if not isinstance(policy, dict) or set(policy) != MANIFEST_KEYS:
        raise DocumentationError("unexpected documentation policy fields")
    if type(policy["schemaVersion"]) is not int or policy["schemaVersion"] != 1:
        raise DocumentationError("unsupported documentation policy version")
    for key in ("include", "requiredDocuments", "statuses"):
        string_list(policy[key], key)
    string_list(policy["forbiddenTerms"], "forbiddenTerms", allow_empty=True)
    for value in policy["include"] + policy["requiredDocuments"]:
        safe_path(root, value)
    if not isinstance(policy["roles"], list) or not isinstance(policy["forbiddenPatterns"], list):
        raise DocumentationError("invalid documentation role or pattern policy")
    names = set()
    for role in policy["roles"]:
        if (
            not isinstance(role, dict)
            or not {"name", "patterns", "requiredHeadings"} <= set(role)
            or set(role)
            - {
                "name",
                "patterns",
                "requiredHeadings",
                "orderedHeadings",
                "requiredTables",
                "requiredDiagrams",
            }
            or not isinstance(role["name"], str)
            or not role["name"]
            or role["name"] in names
        ):
            raise DocumentationError("invalid or duplicate documentation role")
        names.add(role["name"])
        string_list(role["patterns"], "role patterns")
        string_list(role["requiredHeadings"], "required headings", allow_empty=True)
        headings = {heading.casefold() for heading in role["requiredHeadings"]}
        if len(headings) != len(role["requiredHeadings"]):
            raise DocumentationError("duplicate required heading")
        if "orderedHeadings" in role and type(role["orderedHeadings"]) is not bool:
            raise DocumentationError("invalid heading order policy")
        string_list(role.get("requiredTables", []), "required tables", allow_empty=True)
        tables = [heading.casefold() for heading in role.get("requiredTables", [])]
        if len(tables) != len(set(tables)) or any(heading not in headings for heading in tables):
            raise DocumentationError("table policy refers to an unknown required heading")
        diagrams = role.get("requiredDiagrams", {})
        if not isinstance(diagrams, dict):
            raise DocumentationError("invalid required diagrams policy")
        if len({heading.casefold() for heading in diagrams}) != len(diagrams):
            raise DocumentationError("duplicate diagram section policy")
        supported = {"flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram-v2"}
        for heading, directives in diagrams.items():
            if not isinstance(heading, str) or heading.casefold() not in headings:
                raise DocumentationError("diagram policy refers to an unknown required heading")
            string_list(directives, "diagram directives")
            if not set(directives) <= supported:
                raise DocumentationError("unsupported diagram directive policy")
        for pattern in role["patterns"]:
            safe_path(root, pattern)
    identifiers = set()
    for pattern in policy["forbiddenPatterns"]:
        if (
            not isinstance(pattern, dict)
            or set(pattern) != {"id", "pattern"}
            or not isinstance(pattern["id"], str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", pattern["id"])
            or pattern["id"] in identifiers
            or not isinstance(pattern["pattern"], str)
        ):
            raise DocumentationError("invalid or duplicate documentation pattern")
        identifiers.add(pattern["id"])
        try:
            re.compile(pattern["pattern"])
        except re.error as error:
            raise DocumentationError("invalid documentation pattern expression") from error
    return policy


def scan_markdown(text):
    """Retain visible prose and closed fences, excluding HTML-comment examples."""
    result = []
    opened = None
    in_comment = False
    blocks = []
    body = []
    for number, line in enumerate(text.splitlines(), 1):
        if opened is None:
            visible = ""
            remaining = line
            while remaining:
                if in_comment:
                    end = remaining.find("-->")
                    if end < 0:
                        break
                    remaining = remaining[end + 3 :]
                    in_comment = False
                else:
                    start = remaining.find("<!--")
                    if start < 0:
                        visible += remaining
                        break
                    visible += remaining[:start]
                    remaining = remaining[start + 4 :]
                    in_comment = True
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", visible)
            if marker:
                opened = (marker.group(1)[0], len(marker.group(1)), number, marker.group(2).strip())
                body = []
                result.append((number, ""))
            else:
                result.append((number, visible))
        else:
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
            if (
                marker
                and marker.group(1)[0] == opened[0]
                and len(marker.group(1)) >= opened[1]
                and not marker.group(2).strip()
            ):
                blocks.append((opened[2], number, opened[3], body))
                opened = None
            else:
                body.append(line)
            result.append((number, ""))
    return result, opened[2] if opened else None, blocks


def prose_lines(text):
    """Return lines outside comments/fences and an unmatched fence line, if any."""
    lines, unmatched, _ = scan_markdown(text)
    return lines, unmatched


def issue(relative, code, message, line=None):
    return {
        "module": "shared",
        "group": "docs",
        "path": relative,
        "line": line,
        "code": code,
        "message": message,
    }


def table_cells(line):
    """Split one pipe-table row, honouring escaped pipes; indented code is not a table."""
    if "|" not in line or line.startswith(("    ", "\t")):
        return []
    parts = []
    current = ""
    escaped = False
    value = line.strip()
    for char in value:
        if char == "|" and not escaped:
            parts.append(current.strip())
            current = ""
        else:
            current += char
        escaped = not escaped if char == "\\" else False
    parts.append(current.strip())
    if value.startswith("|"):
        parts = parts[1:]
    if value.endswith("|") and parts and not parts[-1]:
        parts.pop()
    return parts


def has_data_table(lines):
    """Require a pipe header, delimiter and populated row outside fenced examples."""
    for index in range(len(lines) - 2):
        header, separator, data = (table_cells(lines[index + offset][1]) for offset in range(3))
        if (
            len(header) >= 2
            and all(header)
            and len(header) == len(separator) == len(data)
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
            and any(data)
        ):
            return True
    return False


def check_role_content(relative, role, heading_items, lines, blocks):
    """Check opted-in role structure; diagram rendering/meaning needs separate review."""
    problems = []
    required = [heading.casefold() for heading in role["requiredHeadings"]]
    positions = []
    for heading in required:
        matches = [number for number, name in heading_items if name == heading]
        if len(matches) > 1:
            problems.append(
                issue(relative, "duplicate_heading", "required section is repeated", matches[1])
            )
        if matches:
            positions.append(matches[0])
    if role.get("orderedHeadings") and positions != sorted(positions):
        problems.append(issue(relative, "heading_order", "required sections are out of order"))
    sections = {}
    for index, (start, name) in enumerate(heading_items):
        end = heading_items[index + 1][0] if index + 1 < len(heading_items) else len(lines) + 1
        content = [(number, line) for number, line in lines if start < number < end]
        owned_blocks = [block for block in blocks if start < block[0] and block[1] < end]
        sections.setdefault(name, (start, content, owned_blocks))
        if (
            role.get("orderedHeadings")
            and name in required
            and not any(line.strip() for _, line in content)
            and not owned_blocks
        ):
            problems.append(issue(relative, "empty_section", "required section is empty", start))
    for heading in role.get("requiredTables", []):
        section = sections.get(heading.casefold())
        if section and not has_data_table(section[1]):
            problems.append(
                issue(
                    relative, "required_table", f"populated table required: {heading}", section[0]
                )
            )
    for heading, directives in role.get("requiredDiagrams", {}).items():
        section = sections.get(heading.casefold())
        if section is None:
            continue
        found = False
        for _, _, language, body in section[2]:
            content = [
                line.strip() for line in body if line.strip() and not line.lstrip().startswith("%%")
            ]
            if language.casefold() == "mermaid" and content:
                directive = re.match(r"^([A-Za-z][\w-]*)(?=\s|;|$)", content[0])
                inline_body = content[0].partition(";")[2].strip()
                has_body = len(content) > 1 or bool(
                    inline_body and not inline_body.startswith("%%")
                )
                if directive and directive.group(1) in directives and has_body:
                    found = True
        if not found:
            problems.append(
                issue(
                    relative,
                    "required_diagram",
                    f"closed nonempty Mermaid diagram required: {heading}",
                    section[0],
                )
            )
    return problems


def link_targets(lines):
    for number, line in lines:
        for match in re.finditer(r"\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\n]+)\)", line):
            yield number, match.group(1).strip()
        definition = re.match(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>\n]+>|\S+)", line)
        if definition:
            yield number, definition.group(1)
        # Embedded HTML (logos, badges, video) links files too; inline code is an example.
        markup = re.sub(r"`[^`]*`", "", line)
        for tag in re.finditer(r"<[A-Za-z][^>]*>", markup):
            for attribute in re.finditer(
                r"\b(src|href|poster|srcset)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", tag.group(0)
            ):
                value = attribute.group(2) if attribute.group(2) is not None else attribute.group(3)
                candidates = value.split(",") if attribute.group(1) == "srcset" else [value]
                for candidate in candidates:
                    target = candidate.strip().split(" ")[0] if candidate.strip() else ""
                    if target:
                        yield number, target


def check_document_card(relative, lines, statuses):
    """Require the Field/Value card between the H1 and the first section."""
    title = next((number for number, line in lines if re.match(r"^\s{0,3}#\s+\S", line)), None)
    first_section = next(
        (number for number, line in lines if re.match(r"^\s{0,3}##\s+\S", line)), None
    )
    rows = []
    for number, line in lines:
        if first_section is not None and number >= first_section:
            break
        if title is None or number <= title:
            continue
        if line.strip().startswith("|"):
            rows.append(table_cells(line))
        elif rows:
            break
    missing = issue(
        relative,
        "document_card",
        "document requires a Field/Value card with Status, Purpose, Audience, Scope, Owns and"
        " Related between its title and first section",
    )
    if len(rows) != len(CARD_FIELDS) + 2 or rows[0] != ["Field", "Value"]:
        return [missing]
    if len(rows[1]) != 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        return [missing]
    data = rows[2:]
    if any(len(row) != 2 for row in data) or tuple(row[0] for row in data) != CARD_FIELDS:
        return [missing]
    if any(not row[1] for row in data):
        return [issue(relative, "document_card", "document card values must not be empty")]
    if data[0][1] not in statuses:
        return [
            issue(relative, "status_metadata", "document card requires one supported Status value")
        ]
    return []


def local_link_problem(root, source, destination):
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1]
    else:
        # Optional Markdown title follows a destination; paths with spaces can use <...>.
        destination = re.sub(r"\s+(?:\"[^\"]*\"|'[^']*')$", "", destination)
    parsed = urlsplit(destination)
    if parsed.scheme.casefold() in {"http", "https", "mailto", "tel"} or (
        not parsed.scheme and parsed.netloc
    ):
        return None
    if parsed.scheme:
        return "unsafe_link", "link uses an unsupported local or executable URI scheme"
    value = unquote(parsed.path)
    if not value:
        return None
    if "\0" in value or "\\" in value or Path(value).is_absolute():
        return "unsafe_link", "local link contains an invalid path"
    target = (source.parent / value).resolve()
    if not target.is_relative_to(root.resolve()):
        return "unsafe_link", "local link escapes repository"
    if not target.exists():
        return "broken_link", "local link target is missing"
    return None


def check_file(root, relative, policy):
    path = safe_path(root, relative)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [issue(relative, "unreadable_document", "document cannot be read as UTF-8")]
    lines, unmatched, blocks = scan_markdown(text)
    problems = []
    h1 = [(number, line) for number, line in lines if re.match(r"^\s{0,3}#\s+\S", line)]
    if len(h1) != 1:
        problems.append(issue(relative, "document_title", "document must contain exactly one H1"))
    if unmatched:
        problems.append(
            issue(relative, "unbalanced_fence", "fenced code block is not closed", unmatched)
        )
    problems.extend(check_document_card(relative, lines, policy["statuses"]))
    for number, line in lines:
        if line.lstrip().startswith(LEGACY_METADATA):
            problems.append(
                issue(
                    relative,
                    "legacy_metadata",
                    "status belongs in the document card and documents carry no review dates",
                    number,
                )
            )
    heading_items = [
        (number, match.group(1).strip().casefold())
        for number, line in lines
        if (match := re.match(r"^\s{0,3}##\s+(.+?)(?:\s+#+)?\s*$", line))
    ]
    headings = {name for _, name in heading_items}
    for role in policy["roles"]:
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in role["patterns"]):
            for heading in role["requiredHeadings"]:
                if heading.casefold() not in headings:
                    problems.append(
                        issue(relative, "required_heading", f"required section missing: {heading}")
                    )
            problems.extend(check_role_content(relative, role, heading_items, lines, blocks))
    for number, target in link_targets(lines):
        problem = local_link_problem(root, path, target)
        if problem:
            problems.append(issue(relative, *problem, line=number))
    for term in policy["forbiddenTerms"]:
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            problems.append(
                issue(
                    relative,
                    "prohibited_reference",
                    "document contains a prohibited reference",
                    text.count("\n", 0, match.start()) + 1,
                )
            )
    for rule in policy["forbiddenPatterns"]:
        match = re.search(rule["pattern"], text)
        if match:
            problems.append(
                issue(
                    relative,
                    rule["id"],
                    "document contains a prohibited source reference",
                    text.count("\n", 0, match.start()) + 1,
                )
            )
    return problems


def audit_documents(root=ROOT, manifest="harness/documentation.json"):
    root = root.resolve()
    try:
        policy = load_manifest(root, manifest)
        paths = set(policy["requiredDocuments"])
        for pattern in policy["include"]:
            for path in root.glob(pattern):
                if path.is_file() or path.is_symlink():
                    relative = path.relative_to(root).as_posix()
                    safe_path(root, relative)
                    paths.add(relative)
        problems = []
        for relative in sorted(paths):
            path = safe_path(root, relative)
            if not path.is_file():
                problems.append(issue(relative, "missing_document", "required document missing"))
            else:
                problems.extend(check_file(root, relative, policy))
        return {
            "schemaVersion": 1,
            "status": "failed" if problems else "documentation_checks_passed",
            "documentsChecked": len(paths),
            "violations": problems,
        }
    except (DocumentationError, OSError, ValueError, TypeError) as error:
        return {
            "schemaVersion": 1,
            "status": "invalid",
            "documentsChecked": 0,
            "violations": [issue(manifest, "documentation_policy", str(error))],
        }


def check_documentation(root=ROOT):
    return audit_documents(root)["violations"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="harness/documentation.json")
    args = parser.parse_args(argv)
    report = audit_documents(ROOT, args.manifest)
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "invalid" else 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
