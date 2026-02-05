# === MemoryAgent.py ===

import torch
import torch.nn as nn
import torch.nn.functional as F

class MemoryAgent:
    def __init__(self, device, name="memory_agent", vector_dim=768, memory_size=500):
        self.device = device
        self.name = name
        self.vector_dim = vector_dim
        self.memory_size = memory_size
        self.memory = []  # list of (vector, tag)

    def store(self, vector, tag="untagged"):
        vector = vector.detach().cpu()
        if vector.shape[-1] != self.vector_dim:
            print(f"[MemoryAgent] Skipped vector with incorrect dim {vector.shape[-1]}")
            return

        self.memory.append((vector, tag))
        if len(self.memory) > self.memory_size:
            self.memory.pop(0)  # FIFO eviction

    def retrieve(self, query_vector, top_k=3, tag_filter=None):
        query_vector = query_vector.detach().cpu()
        if not self.memory:
            return []

        scores = []
        for mem_vec, tag in self.memory:
            if tag_filter and tag != tag_filter:
                continue
            sim = F.cosine_similarity(query_vector, mem_vec, dim=0)
            scores.append((sim.item(), mem_vec, tag))

        top = sorted(scores, key=lambda x: x[0], reverse=True)[:top_k]
        return [(vec, tag) for _, vec, tag in top]

    def receive_signal(self, messages):
        count = 0
        for vec, tag in messages:
            if vec.shape[-1] == self.vector_dim:
                self.store(vec, tag)
                count += 1
        if count:
            print(f"[MemoryAgent] Stored {count} new feedback vectors.")

    def process(self, _=None):
        if not self.memory_bank:
            return torch.zeros(1, 768, device=self.device)
        vectors = torch.stack([v for v, _ in self.memory_bank])
        return torch.mean(vectors, dim=0, keepdim=True)  # [1, D]

    def summarize_feedback(self):
        if not self.memory:
            return None
        vectors = torch.stack([v for v, _ in self.memory])
        return torch.mean(vectors, dim=0, keepdim=True)  # [1, vector_dim]
