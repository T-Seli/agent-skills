"""Small local selector/loader. Native app discovery and messaging remain adapter-owned."""
import hashlib
import json
import os
import re
from pathlib import Path
from .task_contract import checkpoint, validate_packet

SKILL_ID = re.compile(r"^(meta|company|project)\.[a-z][a-z0-9-]*$")
ROLES = {"dot", "worker"}
TIERS = {"small", "medium", "large"}


def _inside(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("relative source path required")
    parts = Path(relative).parts
    if ".." in parts or "." in parts:
        raise ValueError("path traversal forbidden")
    path = root.resolve()
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("source symlink forbidden")
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"source outside catalog or missing: {relative}")
    return path


def _json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def _native_header(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("native skill frontmatter required")
    stop = lines.index("---", 1)
    fields = {}
    for line in lines[1:stop]:
        if line.startswith((" ", "\t")):
            raise ValueError("nested frontmatter needs explicit adapter review")
        key, sep, value = line.partition(":")
        if not sep or key in fields:
            raise ValueError("invalid or duplicate frontmatter field")
        fields[key] = value.strip()
    name = fields.get("name", "")
    desc = fields.get("description", "").strip("'\"").replace("''", "'")
    if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64 or
            name != path.parent.name or not 0 < len(desc) <= 1024):
        raise ValueError("native skill name or description invalid")
    if set(fields) & {"allowed-tools", "context", "agent", "hooks"}:
        raise ValueError("authority-affecting skill frontmatter disabled in v0")
    if re.search(r"!\x60[^\x60]+\x60", text):
        raise ValueError("dynamic command expansion disabled in v0")
    return name


def _package_hashes(root, body):
    skill = _inside(root, body)
    if skill.name != "SKILL.md":
        return {}
    files = []
    for directory, dirs, names in os.walk(skill.parent, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("skill package directory symlink forbidden")
        for name in names:
            file = Path(directory) / name
            if file.is_symlink() or not file.is_file():
                raise ValueError("skill package must contain regular files")
            files.append(file)
    files.sort()
    if len(files) > 64 or sum(p.stat().st_size for p in files) > 2_000_000:
        raise ValueError("skill package exceeds v0 bound")
    result = {}
    for file in files:
        relative = file.relative_to(root).as_posix()
        data = _inside(root, relative).read_bytes()
        result[relative] = hashlib.sha256(data).hexdigest()
    return result


def _entry(root, item):
    keys = {"id", "layer", "summary", "phrases", "roles", "body", "requires"}
    if (not isinstance(item, dict) or set(item) != keys or
            not isinstance(item["id"], str) or not SKILL_ID.fullmatch(item["id"])):
        raise ValueError("invalid skill entry")
    if item["id"].split(".", 1)[0] != item["layer"]:
        raise ValueError("skill id and layer disagree")
    if not isinstance(item["summary"], str) or not item["summary"].strip():
        raise ValueError("skill summary required")
    if not isinstance(item["phrases"], list) or not item["phrases"] or not all(
            isinstance(x, str) and x.strip() for x in item["phrases"]):
        raise ValueError("selection phrases required")
    if (not isinstance(item["roles"], list) or not item["roles"] or
            not all(isinstance(x, str) and x in ROLES for x in item["roles"])):
        raise ValueError("invalid roles")
    if not isinstance(item["requires"], list) or not all(isinstance(x, str) for x in item["requires"]):
        raise ValueError("invalid dependencies")
    if len(item["requires"]) > 16 or len(set(item["requires"])) != len(item["requires"]):
        raise ValueError("dependency closure is duplicate or too large")
    for source in [item["body"], *item["requires"]]:
        if not source.endswith(".md"):
            raise ValueError("skill bodies and dependencies must be Markdown")
        if _inside(root, source).stat().st_size > 512_000:
            raise ValueError("source exceeds v0 size bound")
    if item["body"].endswith("/SKILL.md"):
        name = _native_header(_inside(root, item["body"]))
        if name != item["id"].split(".", 1)[1]:
            raise ValueError("native skill name disagrees with catalog")
        _package_hashes(root, item["body"])
    return item


class Catalog:
    def __init__(self, root, *, project=None, project_root=None, profile=None, profile_root=None):
        self.root = Path(root).resolve()
        self.project_root = Path(project_root).resolve() if project_root else self.root
        self.profile_root = Path(profile_root).resolve() if profile_root else self.root
        source = _json(_inside(self.root, "agent_skills/catalog.json"))
        if (set(source) != {"version", "skills"} or source.get("version") != 1 or
                not isinstance(source.get("skills"), list)):
            raise ValueError("unsupported catalog")
        entries = [{**_entry(self.root, x), "_origin": "core"} for x in source["skills"]]
        if project:
            binding = _json(_inside(self.project_root, project))
            if (set(binding) != {"version", "id", "facts", "skills"} or
                    binding.get("version") != 1 or not isinstance(binding.get("skills"), list)):
                raise ValueError("invalid project binding")
            _inside(self.project_root, binding.get("facts"))
            entries += [{**_entry(self.project_root, x), "_origin": "project"}
                        for x in binding["skills"]]
        ids = [x["id"] for x in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate skill id")
        self.entries = {x["id"]: x for x in entries}
        self.profile = _json(_inside(self.profile_root, profile)) if profile else None
        if self.profile and (not {"version", "id", "scope", "model_tiers"} <= set(self.profile) or
                             set(self.profile) - {"version", "id", "scope", "model_tiers", "note"} or
                             self.profile.get("version") != 1 or
                             self.profile.get("scope") not in ("personal", "team") or
                             set(self.profile.get("model_tiers", {})) != TIERS or
                             not all(isinstance(x, str) and x for x in self.profile["model_tiers"].values())):
            raise ValueError("invalid profile")

    def index(self, role=None):
        if role is not None and role not in ROLES:
            raise ValueError("unknown role")
        return [{"id": x["id"], "layer": x["layer"], "summary": x["summary"],
                 "proposed_export_name": x["id"].replace(".", "-")}
                for x in sorted(self.entries.values(), key=lambda item: item["id"])
                if role is None or role in x["roles"]]

    def select(self, task, *, role, explicit=None, complexity="medium"):
        if role not in ROLES or complexity not in TIERS or not isinstance(task, str) or not task.strip():
            raise ValueError("task, role and complexity required")
        if explicit:
            item = self.entries.get(explicit)
            if not item or role not in item["roles"]:
                raise ValueError("explicit skill unavailable for role")
            score = "explicit"
        else:
            normalized = " ".join(re.findall(r"[a-z0-9]+", task.lower()))
            scored = []
            for item in self.entries.values():
                if role not in item["roles"]:
                    continue
                hits = [len(p.split()) for p in item["phrases"]
                        if " " + " ".join(re.findall(r"[a-z0-9]+", p.lower())) + " " in
                        " " + normalized + " "]
                if hits:
                    scored.append((max(hits), item))
            if not scored:
                return {"decision": "no-match", "role": role}
            best = max(s for s, _ in scored)
            winners = [x for s, x in scored if s == best]
            if len(winners) != 1:
                return {"decision": "ambiguous", "candidates": sorted(x["id"] for x in winners)}
            item, score = winners[0], best
        tier = self.profile["model_tiers"][complexity] if self.profile else None
        return {"decision": "selected", "skill_id": item["id"], "layer": item["layer"],
                "summary": item["summary"], "score": score, "model_tier_hint": tier,
                "profile_scope": self.profile["scope"] if self.profile else None}

    def load(self, skill_id, *, role):
        item = self.entries.get(skill_id)
        if not item or role not in item["roles"]:
            raise ValueError("skill unavailable for role")
        origin = item["_origin"]
        source_root = self.project_root if origin == "project" else self.root
        paths = list(dict.fromkeys([item["body"], *item["requires"]]))
        sources = []
        for relative in paths:
            data = _inside(source_root, relative).read_bytes()
            sources.append({"origin": origin, "path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                            "content": data.decode("utf-8")})
        package = {origin + ":" + path: sha for path, sha in
                   _package_hashes(source_root, item["body"]).items()}
        return {"skill_id": skill_id, "role": role, "sources": sources,
                "package_hashes": package}

    def compose(self, skill_ids, *, role):
        """Load a small, explicit set; common dependencies appear only once."""
        if (not isinstance(skill_ids, (list, tuple)) or not skill_ids or
                len(skill_ids) > 3 or len(set(skill_ids)) != len(skill_ids)):
            raise ValueError("one to three explicit skills required")
        bundles = [self.load(skill_id, role=role) for skill_id in skill_ids]
        sources = list({(s["origin"], s["path"]): s for b in bundles for s in b["sources"]}.values())
        package_hashes = {}
        for bundle in bundles:
            for path, digest in bundle["package_hashes"].items():
                if path in package_hashes and package_hashes[path] != digest:
                    raise ValueError("conflicting package resource")
                package_hashes[path] = digest
        return {"skill_ids": list(skill_ids), "role": role, "sources": sources,
                "package_hashes": dict(sorted(package_hashes.items()))}

    def fresh(self, bundle):
        try:
            current = self.load(bundle["skill_id"], role=bundle["role"])
            return [(x["origin"], x["path"], x["sha256"]) for x in bundle["sources"]] == [
                (x["origin"], x["path"], x["sha256"]) for x in current["sources"]] and (
                bundle["package_hashes"] == current["package_hashes"])
        except (KeyError, TypeError, ValueError):
            return False


def _evidence(catalog, reference):
    """Validate a local reference without putting a machine path in a handoff."""
    if not isinstance(reference, str) or not reference:
        raise ValueError("evidence reference required")
    if reference.startswith("project:"):
        return _inside(catalog.project_root, reference[len("project:"):])
    if ":" in reference:
        raise ValueError("unsupported evidence origin")
    return _inside(catalog.root, reference)


def make_handoff(catalog, bundle, *, work_item, target_role, next_step, evidence_refs=(),
                 task_packet=None, uncertain_side_effects=()):
    """Metadata only. A handoff is never a send or a human approval."""
    if target_role not in ROLES or not catalog.fresh(bundle):
        raise ValueError("target role or source freshness invalid")
    if not work_item or not next_step or any("\n" in x for x in (work_item, next_step)):
        raise ValueError("concise work item and next step required")
    for path in evidence_refs:
        _evidence(catalog, path)
    result = {"work_item": work_item, "from_role": bundle["role"], "to_role": target_role,
            "skill_id": bundle["skill_id"], "source_hashes": {
                x["origin"] + ":" + x["path"]: x["sha256"] for x in bundle["sources"]},
            "package_hashes": bundle["package_hashes"],
            "evidence_refs": list(evidence_refs), "next_step": next_step,
            "human_decision": "not supplied by this handoff", "delivery": "not sent",
            "contract_level": "brief-only"}
    if task_packet is not None:
        validate_packet(task_packet)
        if (task_packet["task_id"] != work_item or
                task_packet["source_hashes"] != result["source_hashes"] or
                task_packet["package_hashes"] != result["package_hashes"]):
            raise ValueError("task packet does not bind this work item and skill bundle")
        result["contract_level"] = "revisioned"
        result["task_packet"] = task_packet
        result["checkpoint"] = checkpoint(task_packet, next_safe_action=next_step,
                                          uncertain_side_effects=list(uncertain_side_effects),
                                          sources_fresh=True)
    return result


def propose_change(catalog, bundle, *, observation, expected, evidence_refs, fixture):
    """A proposal, not a write to the skill or authorization to adopt it."""
    if (not catalog.fresh(bundle) or not all(isinstance(x, str) and x.strip()
                                            for x in (observation, expected, fixture)) or
            not isinstance(evidence_refs, (list, tuple)) or not evidence_refs):
        raise ValueError("fresh source and evidence required")
    if len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError("duplicate evidence reference")
    references = [*evidence_refs, fixture]
    reference_hashes = {ref: hashlib.sha256(_evidence(catalog, ref).read_bytes()).hexdigest()
                        for ref in references}
    payload = {"skill_id": bundle["skill_id"], "role": bundle["role"],
               "observation": observation, "expected": expected,
               "evidence_refs": list(evidence_refs), "fixture": fixture,
               "source_hashes": {x["origin"] + ":" + x["path"]: x["sha256"]
                                 for x in bundle["sources"]},
               "package_hashes": bundle["package_hashes"],
               "reference_hashes": reference_hashes, "state": "proposed"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "proposal_sha256": hashlib.sha256(canonical).hexdigest()}


def review_change(catalog, proposal, *, evaluation_passed):
    """Only marks readiness for human review; never applies or approves a change."""
    if not isinstance(proposal, dict) or set(proposal) != {
            "skill_id", "role", "observation", "expected", "evidence_refs", "fixture",
            "source_hashes", "package_hashes", "reference_hashes", "state", "proposal_sha256"}:
        return {"decision": "blocked", "reason": "invalid proposal"}
    try:
        canonical = json.dumps({key: value for key, value in proposal.items()
                                if key != "proposal_sha256"}, sort_keys=True,
                               separators=(",", ":")).encode()
    except (TypeError, ValueError):
        return {"decision": "blocked", "reason": "invalid proposal"}
    if (proposal["state"] != "proposed" or
            hashlib.sha256(canonical).hexdigest() != proposal["proposal_sha256"]):
        return {"decision": "blocked", "reason": "proposal changed after pinning"}
    item = catalog.entries.get(proposal.get("skill_id"))
    if not item:
        return {"decision": "blocked", "reason": "unknown skill"}
    try:
        bundle = catalog.load(proposal["skill_id"], role=proposal["role"])
        source_hashes = {x["origin"] + ":" + x["path"]: x["sha256"] for x in bundle["sources"]}
    except (KeyError, TypeError, ValueError):
        return {"decision": "blocked", "reason": "source bundle unavailable"}
    if (source_hashes != proposal["source_hashes"] or
            bundle["package_hashes"] != proposal["package_hashes"]):
        return {"decision": "blocked", "reason": "source bundle changed"}
    try:
        references = [*proposal["evidence_refs"], proposal["fixture"]]
        reference_hashes = {ref: hashlib.sha256(_evidence(catalog, ref).read_bytes()).hexdigest()
                            for ref in references}
    except (TypeError, ValueError):
        return {"decision": "blocked", "reason": "review reference unavailable"}
    if reference_hashes != proposal["reference_hashes"]:
        return {"decision": "blocked", "reason": "review reference changed"}
    if evaluation_passed is not True:
        return {"decision": "blocked", "reason": "regression evaluation failed"}
    return {"decision": "human-review-needed", "skill_id": item["id"],
            "proposal_sha256": proposal["proposal_sha256"],
            "rollback_source_hashes": source_hashes,
            "rollback_package_hashes": bundle["package_hashes"]}


def evaluate_selection(catalog, fixture):
    """Run deterministic selection fixtures; this does not measure live agent quality."""
    data = _json(_evidence(catalog, fixture))
    if data.get("version") != 1 or not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("invalid selection fixture")
    results = []
    for case in data["cases"]:
        actual = catalog.select(case["task"], role=case["role"])
        results.append({"name": case["name"], "passed": actual.get("skill_id") == case["expected"]})
    return {"passed": sum(x["passed"] for x in results), "total": len(results), "cases": results}
