import hashlib

from PIL import Image


def compute_dhash(image_path: str, hash_size: int = 8) -> str:
    """
    Compute a perceptual dHash for an image using Pillow.
    Returns a 16-character hex string.
    """
    try:
        with Image.open(image_path) as img:
            # Resize to (hash_size + 1) x hash_size and convert to grayscale
            img = img.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS).convert("L")
            pixels = img.tobytes()

            bits = []
            for row in range(hash_size):
                for col in range(hash_size):
                    idx = row * (hash_size + 1) + col
                    # Compare pixel with the one immediately to its right
                    bits.append(1 if pixels[idx] < pixels[idx + 1] else 0)

            hash_int = sum(b << i for i, b in enumerate(bits))
            return f"{hash_int:016x}"
    except Exception:
        return ""


def hamming_distance(hash1: str, hash2: str) -> int:
    """Count differing bits between two hex hash strings."""
    if not hash1 or not hash2:
        return 64  # Max distance if invalid
    h1, h2 = int(hash1, 16), int(hash2, 16)
    return bin(h1 ^ h2).count("1")


def compute_sha256(image_path: str) -> str:
    """Compute exact binary SHA-256 for an image."""
    sha256_hash = hashlib.sha256()
    with open(image_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
