"""RoMaV2-based document matching and warping module.

This module provides functionality to match scanned document images against
template images using the RoMaV2 deep learning model for dense feature matching.

Uses dense warp fields directly from RoMaV2 instead of fitting homographies,
which handles non-planar deformations (curved pages, wrinkles, etc.).

Works on both CPU and GPU - automatically detects available hardware.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from romav2.device import device as _roma_device

from . import telemetry

logger = logging.getLogger(__name__)

roma_device = str(_roma_device)
logger.info(f"RoMaV2 using device: {roma_device}")

if TYPE_CHECKING:
    from romav2 import RoMaV2 as RoMaV2Type


def _should_compile_romav2() -> bool:
    """Use torch.compile where it is helpful, but do not require it on CPU."""
    compile_override = os.getenv("ROMAV2_COMPILE")
    if compile_override is not None:
        return compile_override.lower() in {"1", "true", "yes", "on"}
    return roma_device != "cpu"


@dataclass
class MatchResult:
    """Result of matching a scan image against a template.

    Uses dense warp fields from RoMaV2 instead of homography matrices.
    The warp fields are in normalized coordinates [-1, 1] for use with grid_sample.

    warp_AB: For each pixel in A (template), where to sample from B (scan).
             Used with grid_sample(scan, warp_AB) to warp scan to template space.
    """

    warp_AB: np.ndarray  # Dense warp field: template -> scan sampling (H x W x 2)
    overlap_AB: np.ndarray  # Confidence/overlap map (H x W x 1)
    confidence: float  # Mean confidence score


class DocumentMatcher:
    """Matches scanned documents against templates using RoMaV2.

    This class handles:
    - Model initialization and warmup
    - Dense feature matching between scan and template
    - Direct warping using dense correspondence fields

    Uses the 'precise' setting for high-quality matching:
    - 800x800 low-resolution + 1280x1280 high-resolution
    - Bidirectional matching

    Works on both CPU and GPU - automatically uses GPU if available.
    """

    _instance: DocumentMatcher | None = None
    _model: RoMaV2Type | None = None

    def __init__(self) -> None:
        """Initialize the document matcher."""
        self._initialized = False
        self._model_H: int = 0
        self._model_W: int = 0

    @classmethod
    def get_instance(cls) -> DocumentMatcher:
        """Get the singleton instance of DocumentMatcher."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_device(cls) -> str:
        """Get the device being used (cuda, mps, or cpu)."""
        return roma_device

    def initialize(self) -> bool:
        """Initialize the RoMaV2 model.

        Uses 'precise' setting for high-quality matching:
        - 800x800 LR + 1280x1280 HR with bidirectional matching

        Returns:
            True if initialization successful, False otherwise.
        """
        if self._initialized:
            return True

        compile_model = _should_compile_romav2()
        init_span, init_tok = telemetry.start_current_span(
            "gpu.romav2.initialize",
            **{"gpu.device": roma_device, "torch.compile": compile_model},
        )
        try:
            import torch
            from romav2 import RoMaV2

            logger.info(f"Initializing RoMaV2 model on {roma_device} (compile={compile_model})...")

            # Set matmul precision to highest (required by RoMaV2)
            torch.set_float32_matmul_precision("highest")

            # Keep torch.compile on for accelerator-backed inference, but avoid
            # requiring a runtime compiler in the CPU Docker image.
            self._model = RoMaV2(RoMaV2.Cfg(compile=compile_model))
            self._model.apply_setting("precise")
            self._model.eval()

            # Get model resolution
            H_hr, W_hr = self._model.H_hr, self._model.W_hr
            H_lr, W_lr = self._model.H_lr, self._model.W_lr
            self._model_H = H_hr if H_hr is not None else H_lr
            self._model_W = W_hr if W_hr is not None else W_lr

            self._initialized = True
            telemetry.end_current_span(init_span, init_tok)
            logger.info(f"RoMaV2 model initialized successfully (resolution: {self._model_H}x{self._model_W})")
            return True
        except Exception as e:
            telemetry.end_current_span(init_span, init_tok, error=str(e))
            logger.error(f"Failed to initialize RoMaV2: {e}")
            return False

    def warmup(self, image_a_path: str, image_b_path: str) -> bool:
        """Warm up the model by running inference on sample images.

        This reduces cold start latency by ensuring:
        - Model weights are loaded into GPU memory
        - CUDA kernels are compiled (if using GPU)
        - Any lazy initialization is completed

        Args:
            image_a_path: Path to first warmup image (template)
            image_b_path: Path to second warmup image (scan)

        Returns:
            True if warmup successful, False otherwise.
        """
        if not self._initialized:
            if not self.initialize():
                return False

        if self._model is None:
            return False

        try:
            logger.info("Warming up RoMaV2 model...")

            # Run inference to warm up - template as A, scan as B
            _ = self._model.match(image_a_path, image_b_path)

            logger.info("RoMaV2 warmup completed successfully")
            return True
        except Exception as e:
            logger.error(f"RoMaV2 warmup failed: {e}")
            return False

    def match(
        self,
        scan_image: np.ndarray,
        template_image: np.ndarray,
    ) -> MatchResult | None:
        """Match a scanned image against a template image.

        Uses dense warp fields directly from RoMaV2 instead of fitting homographies.
        This handles non-planar deformations like curved pages and wrinkles.

        Important: Template is image A, scan is image B.
        warp_BA maps from scan coordinates to template coordinates.

        Args:
            scan_image: Scanned document image (RGB, HxWxC)
            template_image: Template image (RGB, HxWxC)

        Returns:
            MatchResult containing dense warp field and confidence, or None if matching fails.
        """
        model = self._model
        if not self._initialized or model is None:
            if not self.initialize():
                logger.error("Model not initialized")
                return None
            model = self._model

        if model is None:
            logger.error("Model not initialized")
            return None

        try:
            with telemetry.span("gpu.romav2.match", **{"gpu.device": roma_device}) as match_span:
                # Run dense matching: template (A) -> scan (B)
                # warp_AB: for each pixel in A (template), where to sample from B (scan)
                preds = model.match(template_image, scan_image)

                # Extract warp field and overlap (confidence)
                # warp_AB: for each template pixel, where to sample from scan
                # Shape: (H_model, W_model, 2) in normalized coords [-1, 1]
                # .cpu() blocks on the GPU op, so the span covers real
                # inference time, not just async kernel-launch time.
                warp_AB = preds["warp_AB"][0].cpu().numpy()
                overlap_AB = preds["overlap_AB"][0].cpu().numpy()

                # Compute mean confidence
                confidence = float(overlap_AB.mean())
                match_span.set_attribute("match.confidence", confidence)

            return MatchResult(
                warp_AB=warp_AB,
                overlap_AB=overlap_AB,
                confidence=confidence,
            )
        except Exception as e:
            logger.error(f"Matching failed: {e}")
            return None

    def warp_scan_to_template(
        self,
        scan_image: np.ndarray,
        template_image: np.ndarray,
        match_result: MatchResult | None = None,
    ) -> tuple[np.ndarray, MatchResult] | None:
        """Warp scan image to match template dimensions using dense warp field.

        Uses grid_sample with the dense warp field from RoMaV2 to handle
        non-planar deformations.

        Args:
            scan_image: Scanned document image (RGB, HxWxC)
            template_image: Template image (RGB, HxWxC)
            match_result: Optional pre-computed match result

        Returns:
            Tuple of (warped_image, match_result) or None if warping fails.
        """
        if match_result is None:
            match_result = self.match(scan_image, template_image)

        if match_result is None:
            return None

        warp_span, warp_tok = telemetry.start_current_span(
            "gpu.romav2.warp", **{"gpu.device": roma_device}
        )
        try:
            import torch
            import torch.nn.functional as F

            H_template, W_template = template_image.shape[:2]

            # Convert scan image to tensor: (H, W, C) -> (1, C, H, W)
            scan_tensor = torch.tensor(scan_image, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0) / 255.0
            scan_tensor = scan_tensor.to(roma_device)

            # Get warp field: warp_AB tells us where to sample from scan for each template pixel
            # Shape: (H_model, W_model, 2) in normalized coords [-1, 1]
            warp_AB = torch.tensor(match_result.warp_AB, dtype=torch.float32)
            warp_AB = warp_AB.to(roma_device)

            # Resize warp field to template size
            # Shape: (H_model, W_model, 2) -> (1, 2, H_model, W_model) for interpolate
            warp_AB_resized = warp_AB.permute(2, 0, 1).unsqueeze(0)
            warp_AB_resized = F.interpolate(
                warp_AB_resized,
                size=(H_template, W_template),
                mode="bilinear",
                align_corners=False,
            )
            # Back to (1, H, W, 2) for grid_sample
            warp_AB_resized = warp_AB_resized.squeeze(0).permute(1, 2, 0).unsqueeze(0)

            # Apply warp using grid_sample
            # warp_AB contains normalized coords [-1, 1] that map to the full scan image
            # grid_sample will correctly map these to the scan_tensor dimensions
            warped = F.grid_sample(
                scan_tensor,
                warp_AB_resized,
                mode="bilinear",
                padding_mode="border",
                align_corners=False,
            )

            # Convert back to numpy: (1, C, H, W) -> (H, W, C)
            warped_np = (warped.squeeze(0).permute(1, 2, 0).cpu().numpy() * 255).clip(0, 255).astype(np.uint8)

            telemetry.end_current_span(warp_span, warp_tok)
            return warped_np, match_result
        except Exception as e:
            telemetry.end_current_span(warp_span, warp_tok, error=str(e))
            logger.error(f"Warping failed: {e}")
            return None


def four_point_transform(
    image: np.ndarray,
    pts: np.ndarray,
    output_size: tuple[int, int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply a 4-point perspective transform.

    This is used when 4 corner points are already known (e.g., from QR code detection).

    Args:
        image: Input image (HxWxC or HxW)
        pts: 4 corner points in order: TL, TR, BR, BL (4x2 array)
        output_size: Optional (width, height) tuple. If None, computed from pts.

    Returns:
        Tuple of (warped_image, transform_matrix)
    """
    pts = np.array(pts, dtype=np.float32)

    if output_size is None:
        # Compute output dimensions from corner distances
        width_top = float(np.linalg.norm(pts[1] - pts[0]))
        width_bottom = float(np.linalg.norm(pts[2] - pts[3]))
        width = int(max(width_top, width_bottom))

        height_left = float(np.linalg.norm(pts[3] - pts[0]))
        height_right = float(np.linalg.norm(pts[2] - pts[1]))
        height = int(max(height_left, height_right))
    else:
        width, height = output_size

    # Define destination points
    dst = np.array(
        [
            [0, 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0, height - 1],
        ],
        dtype=np.float32,
    )

    # Compute transform
    M = cv2.getPerspectiveTransform(pts, dst)

    # Apply transform
    warped = cv2.warpPerspective(
        image,
        M,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255) if len(image.shape) == 3 else 255,
    )

    return warped, M


def get_matcher() -> DocumentMatcher:
    """Get the global DocumentMatcher instance."""
    return DocumentMatcher.get_instance()


def warmup_matcher(image_a_path: str, image_b_path: str) -> bool:
    """Warm up the global matcher instance.

    Args:
        image_a_path: Path to first warmup image (template)
        image_b_path: Path to second warmup image (scan)

    Returns:
        True if warmup successful, False otherwise.
    """
    matcher = get_matcher()
    return matcher.warmup(image_a_path, image_b_path)
