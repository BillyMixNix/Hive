# === VisionAgent.py ===

import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image

class VisionAgent(nn.Module):
    def __init__(self, name="vision_agent", device="cpu"):
        super().__init__()
        self.name = name  # <-- this fixes the 'name' issue
        self.device = device
        base = models.resnet18(weights=models.ResNet18_Weights.DEFAULT).to(device)
        base.eval()
        # Strip the classification head; keep convolutional trunk + avgpool
        self.feature_extractor = nn.Sequential(*(list(base.children())[:-1]))  # outputs [B, 512, 1, 1]
        self.feature_dim = base.fc.in_features

        self.preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                std=[0.229, 0.224, 0.225]),
        ])

        self.feedback_bank = []
    def process(self, input_data):
        """
        input_data: a PIL Image or preprocessed tensor
        Returns: latent vector [1, feature_dim]
        """
        if isinstance(input_data, torch.Tensor):
            x = input_data.to(self.device)
        else:
            x = self.preprocess(input_data).unsqueeze(0).to(self.device)

        with torch.no_grad():
            feats = self.feature_extractor(x)  # [B, 512, 1, 1]
            feats = feats.flatten(1)          # [B, 512]
        return feats

    def forward(self, image: Image.Image):
        """
        image: A PIL image
        Returns: [1, feature_dim] tensor from penultimate layer
        """
        x = self.preprocess(image).unsqueeze(0).to(self.device)
        with torch.no_grad():
            feats = self.feature_extractor(x)  # [1, 512, 1, 1]
            feats = feats.flatten(1)           # [1, 512]
        return feats  # shape: [1, feature_dim]

    def receive_signal(self, messages):
        for vec, tag in messages:
            if vec.shape[-1] == self.feature_dim:
                self.feedback_bank.append((vec.detach(), tag))

        if self.feedback_bank:
            print(f"[VisionAgent] Integrated {len(self.feedback_bank)} feedback signals.")

    def summarize_feedback(self):
        if not self.feedback_bank:
            return None
        vectors = torch.stack([v for v, _ in self.feedback_bank])
        return torch.mean(vectors, dim=0, keepdim=True)  # [1, feature_dim]
