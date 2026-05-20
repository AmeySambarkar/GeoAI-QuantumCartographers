"""
Temporal change detection.
Supports: index differencing, z-score anomaly detection, and cosine-similarity
change magnitude (mirrors the AlphaEarth Foundations embedding approach).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ChangeMap:
    raw_diff: np.ndarray          # analysis - baseline
    z_score: np.ndarray           # standardised change
    magnitude: np.ndarray         # absolute change magnitude
    gain_fraction: float          # fraction with z > +1.96 (95% CI gain)
    loss_fraction: float          # fraction with z < -1.96 (95% CI loss)
    stable_fraction: float
    mean_change: float
    change_intensity: float       # RMS of z-scores


def compute_index_change(baseline: np.ndarray, analysis: np.ndarray) -> ChangeMap:
    """
    Pixel-wise change between two index maps.
    Z-score normalised to separate signal from noise.
    """
    diff = analysis - baseline
    mean_b, std_b = float(np.nanmean(baseline)), float(np.nanstd(baseline))
    z = (diff - np.nanmean(diff)) / (np.nanstd(diff) + 1e-8)

    valid = ~(np.isnan(z))
    gain = float(np.mean(z[valid] > 1.96)) if valid.any() else 0.0
    loss = float(np.mean(z[valid] < -1.96)) if valid.any() else 0.0
    stable = 1.0 - gain - loss
    intensity = float(np.sqrt(np.nanmean(z**2)))

    return ChangeMap(
        raw_diff=diff,
        z_score=z,
        magnitude=np.abs(diff),
        gain_fraction=round(gain, 4),
        loss_fraction=round(loss, 4),
        stable_fraction=round(max(0.0, stable), 4),
        mean_change=round(float(np.nanmean(diff)), 4),
        change_intensity=round(intensity, 4),
    )


def cosine_change_from_embeddings(base_emb: np.ndarray, anal_emb: np.ndarray) -> np.ndarray:
    """
    Per-pixel cosine dissimilarity between two embedding stacks.
    base_emb, anal_emb: shape [D, H, W]  (D = embedding dims, e.g. 64)
    Returns [H, W] array of 1 - cosine_similarity in [0, 2].
    Mirrors the AlphaEarth Foundations / Google Satellite Embedding V1 approach.
    """
    # Normalise along embedding dimension
    norm_b = np.linalg.norm(base_emb, axis=0, keepdims=True) + 1e-8
    norm_a = np.linalg.norm(anal_emb, axis=0, keepdims=True) + 1e-8
    cos_sim = np.sum((base_emb / norm_b) * (anal_emb / norm_a), axis=0)
    return np.clip(1.0 - cos_sim, 0.0, 2.0)


def detect_water_change(baseline_ndwi: np.ndarray, analysis_ndwi: np.ndarray, threshold: float = 0.0) -> dict:
    """
    Classify pixels into: new_water | lost_water | persistent_water | dry.
    Returns fraction counts.
    """
    b_water = baseline_ndwi > threshold
    a_water = analysis_ndwi > threshold

    new_water = float(np.nanmean(~b_water & a_water))
    lost_water = float(np.nanmean(b_water & ~a_water))
    persistent = float(np.nanmean(b_water & a_water))
    dry = float(np.nanmean(~b_water & ~a_water))

    return {
        "new_water_fraction": round(new_water, 4),
        "lost_water_fraction": round(lost_water, 4),
        "persistent_water_fraction": round(persistent, 4),
        "dry_fraction": round(dry, 4),
    }


def prithvi_style_reconstruction_error(bands: np.ndarray, mask_ratio: float = 0.5) -> float:
    """
    Simplified anomaly score inspired by Prithvi-EO-2.0's masked autoencoder.
    Masks random patches, reconstructs via mean of visible patches, computes MSE.
    Acts as a proxy for 'how anomalous is this scene vs a uniform baseline'.
    """
    rng = np.random.default_rng(seed=42)
    H, W = bands.shape[-2], bands.shape[-1]
    patch_size = 16
    ph, pw = H // patch_size, W // patch_size

    total_mse = 0.0
    n_patches = 0
    for i in range(ph):
        for j in range(pw):
            if rng.random() < mask_ratio:
                patch = bands[:, i*patch_size:(i+1)*patch_size, j*patch_size:(j+1)*patch_size]
                mean_val = np.nanmean(bands)
                total_mse += float(np.nanmean((patch - mean_val)**2))
                n_patches += 1

    return round(total_mse / max(n_patches, 1), 6)
