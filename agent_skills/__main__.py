"""Offline daily interface: index, select, load, evaluate and prepare handoff."""
import argparse
import json
from pathlib import Path

from .core import Catalog, evaluate_selection, make_handoff, propose_change, review_change
from .task_contract import packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--project", help="relative project binding JSON")
    parser.add_argument("--project-root", type=Path, help="root of the separate project repository")
    parser.add_argument("--profile", help="relative profile JSON")
    parser.add_argument("--profile-root", type=Path, help="root of private or team profile files")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    select = sub.add_parser("select")
    select.add_argument("task")
    select.add_argument("--role", choices=("dot", "worker"), required=True)
    select.add_argument("--complexity", choices=("small", "medium", "large"), default="medium")
    select.add_argument("--skill", help="explicit skill id")
    load = sub.add_parser("load")
    load.add_argument("skill_id")
    load.add_argument("--role", choices=("dot", "worker"), required=True)
    compose = sub.add_parser("compose")
    compose.add_argument("skill_ids", nargs="+")
    compose.add_argument("--role", choices=("dot", "worker"), required=True)
    handoff = sub.add_parser("handoff")
    handoff.add_argument("skill_id")
    handoff.add_argument("--role", choices=("dot", "worker"), required=True)
    handoff.add_argument("--to", choices=("dot", "worker"), required=True)
    handoff.add_argument("--work-item", required=True)
    handoff.add_argument("--next-step", required=True)
    handoff.add_argument("--evidence", action="append", default=[])
    handoff.add_argument("--packet-file", type=Path, help="revisioned task packet JSON")
    make_packet = sub.add_parser("packet")
    make_packet.add_argument("skill_id")
    make_packet.add_argument("--role", choices=("dot", "worker"), required=True)
    make_packet.add_argument("--spec", type=Path, required=True, help="local task specification JSON")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--fixture", default="agent_skills/evaluations/selection.json")
    propose = sub.add_parser("propose")
    propose.add_argument("skill_id")
    propose.add_argument("--role", choices=("dot", "worker"), required=True)
    propose.add_argument("--observation", required=True)
    propose.add_argument("--expected", required=True)
    propose.add_argument("--fixture", required=True)
    propose.add_argument("--evidence", action="append", required=True)
    review = sub.add_parser("review-proposal")
    review.add_argument("proposal_file", type=Path)
    args = parser.parse_args()
    catalog = Catalog(args.root, project=args.project, project_root=args.project_root,
                      profile=args.profile, profile_root=args.profile_root)
    if args.command == "catalog":
        result = catalog.index()
    elif args.command == "select":
        result = catalog.select(args.task, role=args.role, explicit=args.skill, complexity=args.complexity)
    elif args.command == "load":
        result = catalog.load(args.skill_id, role=args.role)
    elif args.command == "compose":
        result = catalog.compose(args.skill_ids, role=args.role)
    elif args.command == "handoff":
        result = make_handoff(catalog, catalog.load(args.skill_id, role=args.role),
                              work_item=args.work_item, target_role=args.to,
                              next_step=args.next_step, evidence_refs=args.evidence,
                              task_packet=json.loads(args.packet_file.read_text()) if args.packet_file else None)
    elif args.command == "packet":
        bundle = catalog.load(args.skill_id, role=args.role)
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            raise ValueError("task specification must be an object")
        result = packet(**spec, source_hashes={x["origin"] + ":" + x["path"]: x["sha256"]
                                               for x in bundle["sources"]},
                        package_hashes=bundle["package_hashes"])
    elif args.command == "evaluate":
        result = evaluate_selection(catalog, args.fixture)
    elif args.command == "propose":
        result = propose_change(catalog, catalog.load(args.skill_id, role=args.role),
                                observation=args.observation, expected=args.expected,
                                evidence_refs=args.evidence, fixture=args.fixture)
    else:
        proposal = json.loads(args.proposal_file.read_text(encoding="utf-8"))
        preflight = review_change(catalog, proposal, evaluation_passed=True)
        if preflight["decision"] == "blocked":
            result = {"evaluation": None, "review": preflight}
        else:
            evaluation = evaluate_selection(catalog, proposal["fixture"])
            result = {"evaluation": evaluation,
                      "review": review_change(catalog, proposal,
                                              evaluation_passed=evaluation["passed"] == evaluation["total"])}
    print(json.dumps(result, indent=2))
    if args.command == "evaluate" and result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
