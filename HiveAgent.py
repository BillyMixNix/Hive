import copy
import torch
import torch.nn as nn
import random

class HiveAgent(nn.Module):
    def __init__(self, name, model, feature_fn, output_fn, optimizer=None, loss_fn=None):
        super().__init__()
        self.name = name
        self.model = model
        self.feature_fn = feature_fn
        self.output_fn = output_fn
        self.optimizer = optimizer
        self.loss_fn = loss_fn

    def process(self, images):
        self.model.train()
        features = self.feature_fn(images)
        outputs = self.output_fn(features)
        return features, outputs

    def receive_feedback(self, refined_features):
        # TODO: integrate feedback into future weights or memory
        self.history.append(refined_features.detach().cpu())
    
    def extract_features(self, x):
        if self.name == "vision":
            x = self.model.conv1(x)
            x = self.model.bn1(x)
            x = self.model.relu(x)
            x = self.model.maxpool(x)
            x = self.model.layer1(x)
            x = self.model.layer2(x)
            x = self.model.layer3(x)
            x = self.model.layer4(x)
            x = self.model.avgpool(x)
            return torch.flatten(x, 1)
        elif self.name == "transformer":
            return self.model.forward_features(x)[:, 0]
    
    def forward(self, x):
        return self.output_fn(self.feature_fn(x))

    def mutate(self, mutation_rate=0.01):
        """Return a mutated copy of the agent."""
        mutated = copy.deepcopy(self)
        with torch.no_grad():
            for param in mutated.model.parameters():
                noise = torch.randn_like(param) * mutation_rate
                param.add_(noise)
        return mutated
    def respond(self, prompt):
        from transformers import DistilBertTokenizer
        tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")

        inputs = tokenizer([prompt], return_tensors="pt", padding=True, truncation=True)
        input_ids = inputs["input_ids"].to(self.model.device)
        attention_mask = inputs["attention_mask"].to(self.model.device)

        with torch.no_grad():
            output = self.output_fn(self.feature_fn((input_ids, attention_mask)))

        return f"<latent_vector_mean: {output.mean().item():.4f}>"

