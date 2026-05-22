"""
Real (non-mock) validation of HiveAgent.receive_feedback using actual torch
tensors, a real linear model, and a real optimizer.
"""
import sys
import pytest

sys.path.insert(0, "/home/user/Hive")

torch = pytest.importorskip("torch")
import torch.nn as nn
import torch.optim as optim


from HiveAgent import HiveAgent


def _make_linear_agent(in_dim=8, out_dim=4):
    """Agent backed by a single linear layer."""
    model = nn.Linear(in_dim, out_dim)
    feature_fn = lambda x: model(x)
    output_fn = lambda f: f                    # identity — features are the output
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    agent = HiveAgent(
        name="test",
        model=model,
        feature_fn=feature_fn,
        output_fn=output_fn,
        optimizer=optimizer,
    )
    return agent, model


class TestHiveAgentFeedbackReal:

    def test_history_is_empty_on_init(self):
        agent, _ = _make_linear_agent()
        assert agent.history == []

    def test_feedback_appends_to_history(self):
        agent, _ = _make_linear_agent()
        images = torch.randn(2, 8)
        agent.process(images)
        refined = torch.randn(2, 4)
        agent.receive_feedback(refined)
        assert len(agent.history) == 1
        assert isinstance(agent.history[0], torch.Tensor)

    def test_weights_change_after_feedback(self):
        """The gradient step must actually move the model parameters."""
        agent, model = _make_linear_agent()

        images = torch.randn(2, 8)
        agent.process(images)

        # Snapshot weights before feedback
        before = {n: p.data.clone() for n, p in model.named_parameters()}

        # Provide a refined target that differs from what the model currently produces
        with torch.no_grad():
            current = model(images)
        refined = current + 1.0          # non-trivial gradient target

        agent.receive_feedback(refined)

        # At least one parameter must have changed
        changed = any(
            not torch.equal(p.data, before[n])
            for n, p in model.named_parameters()
        )
        assert changed, "receive_feedback should update model weights but parameters are unchanged"

    def test_weights_move_toward_target(self):
        """MSE loss means the output should be closer to the refined target after the step."""
        agent, model = _make_linear_agent()

        images = torch.randn(1, 8)
        agent.process(images)

        with torch.no_grad():
            before_output = model(images)

        refined = torch.zeros(1, 4)          # fixed target
        dist_before = (before_output - refined).pow(2).sum().item()

        agent.receive_feedback(refined)

        with torch.no_grad():
            after_output = model(images)
        dist_after = (after_output - refined).pow(2).sum().item()

        assert dist_after < dist_before, (
            f"Output should be closer to target after feedback step "
            f"(before={dist_before:.4f}, after={dist_after:.4f})"
        )

    def test_no_weight_change_without_prior_process(self):
        """Feedback before any process() call must not attempt a gradient step."""
        agent, model = _make_linear_agent()
        before = {n: p.data.clone() for n, p in model.named_parameters()}

        agent.receive_feedback(torch.randn(2, 4))   # no process() beforehand

        unchanged = all(
            torch.equal(p.data, before[n])
            for n, p in model.named_parameters()
        )
        assert unchanged, "No gradient step should fire before process() is ever called"

    def test_no_weight_change_without_optimizer(self):
        """Agent without an optimizer must not crash and must not modify weights."""
        model = nn.Linear(8, 4)
        agent = HiveAgent(
            name="test",
            model=model,
            feature_fn=lambda x: model(x),
            output_fn=lambda f: f,
            optimizer=None,
        )
        before = {n: p.data.clone() for n, p in model.named_parameters()}

        images = torch.randn(2, 8)
        agent.process(images)
        agent.receive_feedback(torch.randn(2, 4))

        unchanged = all(
            torch.equal(p.data, before[n])
            for n, p in model.named_parameters()
        )
        assert unchanged

    def test_multiple_feedback_rounds_keep_improving(self):
        """Repeated feedback rounds should keep reducing distance to target."""
        agent, model = _make_linear_agent()
        images = torch.randn(1, 8)
        refined = torch.zeros(1, 4)

        agent.process(images)

        prev_dist = float("inf")
        for _ in range(5):
            agent.receive_feedback(refined)
            with torch.no_grad():
                out = model(images)
            dist = (out - refined).pow(2).sum().item()
            assert dist < prev_dist, "Each feedback round should reduce distance to target"
            prev_dist = dist
