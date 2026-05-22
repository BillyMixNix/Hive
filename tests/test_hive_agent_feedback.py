"""
Unit tests for HiveAgent.receive_feedback implementation.
Uses lightweight mocks so torch is not required.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, call


def _build_torch_mock():
    """Build a minimal torch mock sufficient for HiveAgent to import and run."""
    torch = types.ModuleType("torch")
    nn = types.ModuleType("torch.nn")
    torch.nn = nn

    class Module:
        def train(self):
            pass

    nn.Module = Module
    sys.modules["torch"] = torch
    sys.modules["torch.nn"] = nn
    return torch


# Patch torch before importing HiveAgent
_torch = _build_torch_mock()
sys.path.insert(0, "/home/user/Hive")


class FakeTensor:
    """Minimal tensor stand-in."""
    def __init__(self, val=1.0, device="cpu"):
        self.val = val
        self.device = device

    def detach(self):
        return self

    def cpu(self):
        return self

    def to(self, device):
        return self


class TestHiveAgentFeedback(unittest.TestCase):

    def _make_agent(self, with_optimizer=True):
        from HiveAgent import HiveAgent

        model = MagicMock()
        model.train = MagicMock()
        feature_fn = MagicMock(return_value=FakeTensor())
        output_fn = MagicMock(return_value=FakeTensor())
        optimizer = MagicMock() if with_optimizer else None

        agent = HiveAgent(
            name="test",
            model=model,
            feature_fn=feature_fn,
            output_fn=output_fn,
            optimizer=optimizer,
        )
        return agent, model, feature_fn, optimizer

    # ------------------------------------------------------------------
    # Bug fix: self.history initialised
    # ------------------------------------------------------------------
    def test_history_initialised_on_construction(self):
        agent, *_ = self._make_agent()
        self.assertIsInstance(agent.history, list)
        self.assertEqual(len(agent.history), 0)

    def test_last_input_initialised_to_none(self):
        agent, *_ = self._make_agent()
        self.assertIsNone(agent._last_input)

    # ------------------------------------------------------------------
    # process() caches the input
    # ------------------------------------------------------------------
    def test_process_caches_last_input(self):
        agent, *_ = self._make_agent()
        fake_images = FakeTensor()
        agent.process(fake_images)
        self.assertIs(agent._last_input, fake_images)

    def test_process_overwrites_cache_on_second_call(self):
        agent, *_ = self._make_agent()
        img1, img2 = FakeTensor(), FakeTensor()
        agent.process(img1)
        agent.process(img2)
        self.assertIs(agent._last_input, img2)

    # ------------------------------------------------------------------
    # receive_feedback: history always updated
    # ------------------------------------------------------------------
    def test_receive_feedback_appends_to_history(self):
        agent, *_ = self._make_agent()
        refined = FakeTensor()
        agent.receive_feedback(refined)
        self.assertEqual(len(agent.history), 1)

    def test_receive_feedback_appends_multiple(self):
        agent, *_ = self._make_agent()
        for _ in range(3):
            agent.receive_feedback(FakeTensor())
        self.assertEqual(len(agent.history), 3)

    # ------------------------------------------------------------------
    # receive_feedback: gradient step skipped when no prior input
    # ------------------------------------------------------------------
    def test_no_gradient_step_without_prior_process(self):
        agent, _, _, optimizer = self._make_agent(with_optimizer=True)
        agent.receive_feedback(FakeTensor())
        optimizer.zero_grad.assert_not_called()
        optimizer.step.assert_not_called()

    def test_no_gradient_step_without_optimizer(self):
        agent, _, feature_fn, _ = self._make_agent(with_optimizer=False)
        agent.process(FakeTensor())
        agent.receive_feedback(FakeTensor())
        # feature_fn called once by process(); a second call would mean
        # the gradient path ran — it should not have.
        self.assertEqual(feature_fn.call_count, 1)

    # ------------------------------------------------------------------
    # receive_feedback: gradient step fires when conditions are met
    # ------------------------------------------------------------------
    def _setup_F_mock(self):
        """Inject a torch.nn.functional mock with mse_loss that returns a trainable fake."""
        loss_tensor = MagicMock()
        loss_tensor.backward = MagicMock()

        F_mod = types.ModuleType("torch.nn.functional")
        F_mod.mse_loss = MagicMock(return_value=loss_tensor)
        sys.modules["torch.nn.functional"] = F_mod
        _torch.nn.functional = F_mod
        return F_mod, loss_tensor

    def test_gradient_step_runs_after_process(self):
        F_mod, loss_tensor = self._setup_F_mock()
        agent, model, feature_fn, optimizer = self._make_agent(with_optimizer=True)

        images = FakeTensor()
        agent.process(images)
        refined = FakeTensor()
        agent.receive_feedback(refined)

        # feature_fn called once by process, once by receive_feedback
        self.assertEqual(feature_fn.call_count, 2)
        F_mod.mse_loss.assert_called_once()
        loss_tensor.backward.assert_called_once()
        optimizer.zero_grad.assert_called_once()
        optimizer.step.assert_called_once()

    def test_gradient_step_uses_cached_input(self):
        self._setup_F_mock()
        agent, _, feature_fn, optimizer = self._make_agent(with_optimizer=True)

        images = FakeTensor()
        agent.process(images)
        agent.receive_feedback(FakeTensor())

        # Both calls to feature_fn should use the same cached images object
        calls = feature_fn.call_args_list
        self.assertIs(calls[0][0][0], images)  # process call
        self.assertIs(calls[1][0][0], images)  # feedback call


if __name__ == "__main__":
    unittest.main()
