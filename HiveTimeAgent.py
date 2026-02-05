import torch
import torch.nn as nn
from datetime import datetime

class TimeAgent(nn.Module):
    def __init__(self, name="time_agent", time_dim=8):
        super().__init__()
        self.name = name
        self.tick = 0 
        self.time_dim = time_dim
        self.time_encoder = nn.Sequential(
            nn.Linear(6, 32),  # year, month, day, hour, minute, second
            nn.ReLU(),
            nn.Linear(32, time_dim)
        )

    def encode_current_time(self):
        now = datetime.utcnow()
        raw = torch.tensor([
            now.year % 100,  # keep short
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second
        ], dtype=torch.float32).unsqueeze(0)  # [1, 6]
        return self.time_encoder(raw)  # [1, time_dim]

    def forward(self, _):
        return self.encode_current_time()

    def get_output_dim(self):
        return self.time_dim
    
    def process(self, _=None):
        """
        Increment the time step and return a simple representation of time.
        """
        self.tick += 1
        return torch.tensor([[self.tick]], dtype=torch.float32)