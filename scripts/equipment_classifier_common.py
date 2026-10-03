#!/usr/bin/env python3
"""Shared code for the top-6 tractor-brand classifier (train / evaluate / infer).

A single source of truth for the preprocessing, the model factory and the
metric computation so training, evaluation and Django inference can never
silently diverge. Nothing in this module performs network access; pretrained
weights are consumed only when explicitly loaded during training.
"""
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, transforms
from torchvision.models import mobilenet_v3_large, resnet18

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
IMAGE_SIZE = 224

ARCH_NAME = "mobilenet_v3_large"
VERSION = "v1"
MODEL_FAMILY = "mobilenetv3_top6"


def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def eval_transform():
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])


def train_transform():
    return transforms.Compose([
        transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.6, 1.0), ratio=(0.75, 1.333)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomRotation(degrees=10),
        transforms.ColorJitter(brightness=0.25, contrast=0.25, saturation=0.25, hue=0.05),
        transforms.RandomAffine(degrees=0, translate=(0.05, 0.05)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])


def build_model(arch_name: str, num_classes: int, pretrained: bool = False):
    """Build MobileNetV3-Large (or ResNet18) with a fresh classifier head."""
    if arch_name == "mobilenet_v3_large":
        weights = "IMAGENET1K_V2" if pretrained else None
        model = mobilenet_v3_large(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
    elif arch_name == "resnet18":
        weights = "IMAGENET1K_V1" if pretrained else None
        model = resnet18(weights=weights)
        in_features = model.fc.in_features
        model.fc = torch.nn.Linear(in_features, num_classes)
    else:
        raise ValueError(f"unsupported architecture: {arch_name}")
    return model


def class_weights_from_counts(counts):
    """Inverse-frequency weights: w_c = total / (n_classes * count_c).

    Single, documented imbalance method (weighted CrossEntropyLoss).
    """
    total = sum(counts.values())
    n = len(counts)
    weights = torch.tensor([total / (max(n * counts[c], 1)) for c in sorted(counts)],
                           dtype=torch.float32)
    return weights / weights.sum()


class LabeledDataset(Dataset):
    """Thin wrapper that exposes class order alongside the ImageFolder samples."""

    def __init__(self, folder: Path, transform):
        self.folder = datasets.ImageFolder(str(folder), transform=transform)
        self.classes = self.folder.classes
        self.class_to_idx = self.folder.class_to_idx

    def __len__(self):
        return len(self.folder)

    def __getitem__(self, idx):
        return self.folder[idx]

    @property
    def counts(self):
        return {c: self.folder.targets.count(i) for c, i in self.class_to_idx.items()}


def load_labeled(folder: Path, transform, batch_size: int, shuffle: bool, device):
    ds = LabeledDataset(folder, transform)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=shuffle,
                        num_workers=0, pin_memory=device.type == "cuda")
    return ds, loader


@torch.no_grad()
def predict_logits(model, loader, device):
    model.eval()
    logits, labels = [], []
    for x, y in loader:
        out = model(x.to(device))
        logits.append(out.cpu())
        labels.append(y.cpu())
    return torch.cat(logits), torch.cat(labels)


def topk_accuracy(logits, labels, k=3):
    topk = torch.topk(logits, k=k, dim=1).indices
    hit = topk.eq(labels.unsqueeze(1)).any(dim=1)
    return float(hit.float().mean().item())


def macro_f1_from_logits(logits, labels, num_classes):
    """Macro F1 averaged over classes (mirrors sklearn macro_f1) without sklearn."""
    preds = logits.argmax(dim=1).cpu().numpy()
    labels_np = labels.cpu().numpy()
    f1s = []
    for c in range(num_classes):
        tp = int(((preds == c) & (labels_np == c)).sum())
        fp = int(((preds == c) & (labels_np != c)).sum())
        fn = int(((preds != c) & (labels_np == c)).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0)
    return float(np.mean(f1s))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")