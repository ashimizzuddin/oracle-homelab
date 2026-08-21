import os

from PIL import Image

from ai_job_filter.processing.image_hash import compute_dhash, compute_sha256, hamming_distance


def create_test_image(path, color, size=(100, 100)):
    img = Image.new("RGB", size, color=color)
    img.save(path)


def test_dhash_and_hamming(tmp_path):
    img1_path = os.path.join(tmp_path, "img1.png")
    img2_path = os.path.join(tmp_path, "img2.png")

    # Create two identical images
    create_test_image(img1_path, "red")
    create_test_image(img2_path, "red")

    hash1 = compute_dhash(img1_path)
    hash2 = compute_dhash(img2_path)

    assert hash1 == hash2
    assert hamming_distance(hash1, hash2) == 0


def test_sha256_image(tmp_path):
    img1_path = os.path.join(tmp_path, "img1.png")
    create_test_image(img1_path, "blue")
    sha_hash = compute_sha256(img1_path)
    assert len(sha_hash) == 64
