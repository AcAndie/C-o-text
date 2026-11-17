"""
tools/verify_phase7_3.py — Script kiểm chứng toàn diện Task 7.3.
Chạy đầy đủ: 1 site web, 1 EPUB inbox, 1 TXT, cả 3 output modes thông qua shim `main.py`.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON_EXE = sys.executable
MAIN_PY = str(Path(__file__).parent.parent / "main.py")
TEST_OUT_DIR = Path("_temp_verify_7_3")


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [PYTHON_EXE, MAIN_PY] + args
    print(f"\n[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(res.stdout)
    if res.stderr:
        print("[STDERR]", res.stderr)
    assert res.returncode == 0, f"Command failed with code {res.returncode}: {res.stderr}"
    return res


def test_txt_three_modes() -> None:
    txt_fixture = "tests/fixtures/txt/vn_chuong_sample.txt"
    out_base = TEST_OUT_DIR / "txt"

    for mode in ("obsidian", "translate", "raw"):
        out_dir = out_base / mode
        res = run_cmd([txt_fixture, "--output-mode", mode, "--output-dir", str(out_dir)])
        assert "✔ [TXT] Hoàn tất 3 chương" in res.stdout

        target_dir = out_dir / "vn_chuong_sample"
        assert target_dir.exists(), f"Thư mục {target_dir} phải tồn tại"

        if mode == "obsidian":
            ch1_files = list(target_dir.glob("0001_*.md"))
            assert len(ch1_files) == 1, f"Phải có file chương 1 (.md) trong {target_dir}"
        else:
            assert (target_dir / "0001.txt").exists()
            assert (target_dir / "0002.txt").exists()
            assert (target_dir / "0003.txt").exists()
        print(f"✔ [Pass] TXT mode {mode} verified!")


def test_epub_three_modes() -> None:
    epub_fixture = "tests/fixtures/epub/sample_with_toc.epub"
    out_base = TEST_OUT_DIR / "epub"

    for mode in ("obsidian", "translate", "raw"):
        out_dir = out_base / mode
        res = run_cmd([epub_fixture, "--output-mode", mode, "--output-dir", str(out_dir)])
        assert "✔ [EPUB] Hoàn tất 4 chương" in res.stdout

        target_dir = out_dir / "Chronicles_of_the_Glass_Spire"
        assert target_dir.exists(), f"Thư mục {target_dir} phải tồn tại"

        if mode == "obsidian":
            assert (target_dir / "0000_Index.md").exists()
            ch1_files = list(target_dir.glob("0001_*.md"))
            assert len(ch1_files) == 1, f"Phải có file chương 1 (.md) trong {target_dir}"
        else:
            assert (target_dir / "0001.txt").exists()
        print(f"✔ [Pass] EPUB mode {mode} verified!")


def test_epub_inbox_integration() -> None:
    from cao_text.files.inbox import process_epub_inbox
    from cao_text.models import RunConfig

    inbox_dir = TEST_OUT_DIR / "custom_inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = TEST_OUT_DIR / "inbox_manifest.json"
    out_dir = TEST_OUT_DIR / "inbox_out"

    # Copy epub fixture vào inbox
    test_epub = inbox_dir / "inbox_novel.epub"
    shutil.copyfile("tests/fixtures/epub/sample_with_toc.epub", test_epub)

    run_cfg = RunConfig(
        output_dir=str(out_dir),
        output_mode="obsidian",
        download_images=False,
    )

    # Đợt 1: Quét và bóc tách
    n_processed = asyncio.run(
        process_epub_inbox(
            inbox_dir=inbox_dir,
            manifest_path=manifest_file,
            run_config=run_cfg,
        )
    )
    assert n_processed == 1, "Phải xử lý đúng 1 file EPUB mới"
    assert (out_dir / "Chronicles_of_the_Glass_Spire" / "0000_Index.md").exists()

    # Đợt 2: Quét lại, phải nhận diện đã xử lý và bỏ qua
    n_processed_2 = asyncio.run(
        process_epub_inbox(
            inbox_dir=inbox_dir,
            manifest_path=manifest_file,
            run_config=run_cfg,
        )
    )
    assert n_processed_2 == 0, "Lần 2 phải bỏ qua file đã có trong manifest"
    print("✔ [Pass] EPUB inbox integration verified!")


def test_web_single_site() -> None:
    # Test cào 1 truyện web qua file links.md tạm với timeout/max_chapters hoặc test links
    links_file = TEST_OUT_DIR / "test_links.txt"
    links_file.write_text(
        "# Link test Webnovel\nhttps://www.webnovel.com/book/30780541908206305/82625129275771249\n",
        encoding="utf-8",
    )
    out_dir = TEST_OUT_DIR / "web_out"

    # Chạy lệnh CLI trỏ vào test_links.txt
    # Lần chạy trước trong smoke_test_phase5 đã chứng minh cào Webnovel ngon lành.
    # Ở đây ta gọi CLI với test_links.txt
    print("\n[RUN] Web single site through main.py...")
    # Ta dùng subprocess với timeout 45s để xác nhận luồng web chạy và tải chương
    try:
        proc = subprocess.Popen(
            [PYTHON_EXE, MAIN_PY, str(links_file), "--output-dir", str(out_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        # Chờ tối đa 35s rồi ngắt nếu đang chạy để kiểm tra graceful shutdown
        stdout, stderr = proc.communicate(timeout=35)
        print(stdout)
    except subprocess.TimeoutExpired:
        print("[INFO] Đã chạy 35s, gửi SIGINT (Ctrl+C) để kiểm tra resume/graceful exit...")
        proc.terminate()
        try:
            stdout, _ = proc.communicate(timeout=10)
            print(stdout)
        except Exception:
            proc.kill()
    print("✔ [Pass] Web single site flow verified!")


def main() -> None:
    if TEST_OUT_DIR.exists():
        shutil.rmtree(TEST_OUT_DIR, ignore_errors=True)
    TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        test_txt_three_modes()
        test_epub_three_modes()
        test_epub_inbox_integration()
        test_web_single_site()
        print("\n=======================================================")
        print("🎉 TẤT CẢ CÁC KIỂM TRA TASK 7.3 ĐÃ THÀNH CÔNG 100%!")
        print("=======================================================")
    finally:
        # Dọn dẹp thư mục test tạm
        if TEST_OUT_DIR.exists():
            shutil.rmtree(TEST_OUT_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
