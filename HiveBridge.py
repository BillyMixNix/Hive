import torch
import torch.nn as nn
import torch.nn.functional as F
import logging
import json
from pathlib import Path

class HiveBridge(nn.Module):
    def __init__(self, agent_dims, shared_dim=128):
        super().__init__()
        self.shared_dim = shared_dim
        self.debug_log_path = Path("logs/bridge_debug.jsonl")
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.debug_log_path.write_text("")  # Clear previous run

        # Each agent gets its own projection MLP
        self.projections = nn.ModuleDict({
            name: nn.Sequential(
                nn.Linear(dim, shared_dim),
                nn.LayerNorm(shared_dim),
                nn.ReLU(),
                nn.Dropout(0.1)
            )
            for name, dim in agent_dims.items()
        })

        # Final fusion MLP
        self.fuse_layer = nn.Sequential(
            nn.Linear(shared_dim, 256),
            nn.ReLU(),
            nn.Linear(256, shared_dim)
        )
        self.latest_attn_weights = {}
        

    def forward(self, features_dict):
        # Project all features to shared latent space
        shared = {
            name: self.projections[name](vec)
            for name, vec in features_dict.items()
        }
        return shared

    def fuse(self, shared_dict):
        keys = list(shared_dict.keys())
        values = torch.stack([shared_dict[k] for k in keys], dim=1)  # [batch, agents, shared_dim]

        # Attention weights based on mean activation (simple heuristic)
        attn_scores = torch.mean(values, dim=2, keepdim=True)  # [batch, agents, 1]
        attn_weights = torch.softmax(attn_scores, dim=1)       # [batch, agents, 1]

        # Log attention values per agent (batch-wise average)
        self.latest_attn_weights = {
            name: attn_weights[:, i, 0].detach().cpu().numpy().tolist()
            for i, name in enumerate(keys)
        }

        # Weighted sum for fusion
        fused = torch.sum(values * attn_weights, dim=1)  # [batch, shared_dim]
        fused_output = self.fuse_layer(fused)

        # === LOGGING ===
        try:
            log_data = {
                "attention": {k: round(sum(v) / len(v), 4) for k, v in self.latest_attn_weights.items()},
                "fused_mean": round(fused_output.mean().item(), 4),
                "shared_vectors": {
                    k: [round(float(x), 4) for x in v[0][:10]]  # Sample 10 dims of 1st vector
                    for k, v in shared_dict.items()
                }
            }
            with self.debug_log_path.open("a") as f:
                f.write(json.dumps(log_data) + "\n")

            logging.info(f"[Bridge] {log_data}")
        except Exception as e:
            logging.warning(f"Failed to log bridge debug info: {e}")

        return fused_output
