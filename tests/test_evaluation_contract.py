import unittest

from agent_skills.evaluation_contract import paired_review, selection_counts, validate_case


CASE = {"id": "review-1", "scenario": "regression", "task": "review a change",
        "selection_mode": "implicit", "required_skills": ["company.test-review"],
        "allowed_skills": ["company.test-review"], "forbidden_skills": ["company.deploy"],
        "outcome_checks": ["review-record"], "hard_invariants": ["no-deploy"]}
ZERO = "0" * 64
ONE = "1" * 64
TRIAL = {"case_id": "review-1", "variant": "candidate", "runtime": "fixture-only",
         "model": "none", "config_sha256": ZERO, "bundle_sha256": ONE,
         "evaluator_sha256": ZERO, "selected_skills": ["company.test-review"],
         "loaded_skills": [], "artifact_evidence": ["local:review.json"],
         "check_results": {"review-record": "pass"},
         "invariant_results": {"no-deploy": "pass"}, "cost": 0,
         "environment_failures": []}


class EvaluationContractTests(unittest.TestCase):
    def test_implicit_selection_counts_false_positives_and_undefined_rates(self):
        bad = {**TRIAL, "selected_skills": ["company.deploy"]}
        self.assertEqual(selection_counts([CASE], [bad]),
                         {"tp": 0, "fp": 1, "fn": 1, "precision": 0, "recall": 0})
        explicit = {**CASE, "selection_mode": "explicit"}
        self.assertEqual(selection_counts([explicit], [TRIAL]),
                         {"tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None})

    def test_mismatched_evaluator_and_failing_safety_block_comparison(self):
        baseline = {**TRIAL, "variant": "incumbent", "bundle_sha256": ZERO}
        self.assertEqual(paired_review(CASE, TRIAL, baseline)["decision"], "human-review-needed")
        self.assertEqual(paired_review(CASE, TRIAL, {**baseline, "evaluator_sha256": ONE})["decision"],
                         "incomparable")
        self.assertEqual(paired_review(CASE, {**TRIAL, "invariant_results": {"no-deploy": "fail"}}, baseline)["decision"],
                         "blocked")

    def test_malformed_case_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_case({**CASE, "required_skills": ["company.deploy"]})
        with self.assertRaises(ValueError):
            validate_case({**CASE, "allowed_skills": [{}]})


if __name__ == "__main__":
    unittest.main()
