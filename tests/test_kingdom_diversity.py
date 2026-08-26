from kingdom.core import BranchSpec
from kingdom.diversity import diversity_report, filter_novel_branches


def test_near_duplicate_generated_branches_are_filtered():
    branches = (
        BranchSpec("a", "skeptic", "What evidence would falsify the claim?", "assume measurements are required"),
        BranchSpec("b", "critic", "What evidence would falsify the claim now?", "assume measurements are required"),
        BranchSpec("c", "implementation", "What can we build immediately?", "assume current hardware only"),
    )

    filtered = filter_novel_branches(branches)

    assert [branch.branch_id for branch in filtered] == ["a", "c"]


def test_forced_worlds_are_never_removed_by_lexical_filter():
    branches = (
        BranchSpec("true", "world:premise_true", "Test the core premise.", "assume the premise is correct"),
        BranchSpec("false", "world:premise_false", "Test the core premise.", "assume the premise is incorrect"),
    )

    filtered = filter_novel_branches(branches, question_threshold=0.0, assumption_threshold=0.0)

    assert filtered == branches


def test_diversity_report_separates_raw_from_effective_branch_count():
    branches = (
        BranchSpec("a", "skeptic", "What evidence would falsify the claim?", "assume measurements are required"),
        BranchSpec("b", "critic", "What evidence would falsify the claim now?", "assume measurements are required"),
        BranchSpec("world", "world:premise_false", "What if the claim is wrong?", "assume the claim is false"),
    )

    report = diversity_report(branches)

    assert report.branch_count == 3
    assert report.effective_branch_count == 2
    assert report.efficiency == 2 / 3
    assert len(report.correlated_pairs) == 1
