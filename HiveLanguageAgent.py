# === HiveLanguageAgent.py ===

import torch
import torch.nn as nn
from transformers import DistilBertTokenizer, DistilBertModel

class LanguageAgent(nn.Module):
    def __init__(self, name="language_agent", device="cpu"):
        super().__init__()
        self.name = name
        self.device = device
        self.tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
        self.model = DistilBertModel.from_pretrained("distilbert-base-uncased").to(device)
        self.model.eval()
        self.feedback_bank = []

    def process(self, text: str):
        if not isinstance(text, str):
            raise ValueError("LanguageAgent expected string input.")
        
        inputs = self.tokenizer([text], return_tensors="pt", padding=True, truncation=True).to(self.device)
        with torch.no_grad():
            vec = self.model(**inputs).last_hidden_state[:, 0]  # CLS token
        return vec  # shape: [1, 768]

    def receive_signal(self, messages):
        for vec, tag in messages:
            if vec.shape[-1] == 768:
                self.feedback_bank.append((vec.detach(), tag))

        if self.feedback_bank:
            print(f"[LanguageAgent] Integrated {len(self.feedback_bank)} feedback signals.")

    def summarize_feedback(self):
        if not self.feedback_bank:
            return None
        vectors = torch.stack([v for v, _ in self.feedback_bank])
        return torch.mean(vectors, dim=0, keepdim=True)
