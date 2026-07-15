"""08 清理:完整归档并校验后,清空 01_input 分段和 03_preview。"""
import argparse
import json
import os
import shutil
import subprocess
import time

from common import (
    ARCHIVE_DIR,
    JPEG_EXTS,
    OUTPUT_DIR,
    PREVIEW_DIR,
    ROOT,
    iter_segments,
    list_images,
    log,
    seg_name,
    seg_result,
)


def _copy_and_verify(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    if not os.path.isfile(dst) or os.path.getsize(src) != os.path.getsize(dst):
        raise RuntimeError(f"归档校验失败: {src}")


def _git_commit():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _output_files(output_dir):
    files = []
    if os.path.isdir(output_dir):
        for base, _, names in os.walk(output_dir):
            for name in sorted(names):
                files.append(os.path.join(base, name))
    return files


def _build_plan(segments, preview_dir):
    plan = []
    for seg in segments:
        name = seg_name(seg)
        images = list_images(seg_result(seg), exts=JPEG_EXTS)
        config = os.path.join(seg, "config.json")
        preview = os.path.join(preview_dir, name + ".mp4")
        if not images:
            raise RuntimeError(f"[{name}] result/ 中没有 JPEG,为防止误删已停止清理")
        if not os.path.isfile(config):
            raise RuntimeError(f"[{name}] 缺少 config.json,为防止误删已停止清理")
        if not os.path.isfile(preview):
            raise RuntimeError(f"[{name}] 缺少预览视频 {name}.mp4,为防止误删已停止清理")
        plan.append({
            "name": name,
            "segment": seg,
            "images": images,
            "config": config,
            "preview": preview,
        })
    return plan


def _print_plan(plan, output_files):
    log("将归档并删除以下本地任务:")
    for item in plan:
        log(f"  {item['name']}: {len(item['images'])} 帧 + config.json + 预览 MP4")
    log(f"04_output: {len(output_files)} 个文件将归档,原文件保留")
    log("归档成功后将删除 01_input 下上述分段,并清空 03_preview。")


def run_cleanup(
    segments=None,
    archive_dir=ARCHIVE_DIR,
    preview_dir=PREVIEW_DIR,
    output_dir=OUTPUT_DIR,
    timestamp=None,
    dry_run=False,
    confirmed=False,
):
    segments = list(iter_segments() if segments is None else segments)
    if not segments:
        log("01_input/ 中没有可清理的分段。")
        return None

    plan = _build_plan(segments, preview_dir)
    output_files = _output_files(output_dir)
    _print_plan(plan, output_files)

    if dry_run:
        log("DRY RUN:未复制或删除任何文件。")
        return None

    if not confirmed:
        answer = input("输入 DELETE 确认删除原始素材和当前任务:").strip()
        if answer != "DELETE":
            log("已取消,未复制或删除任何文件。")
            return None

    ts = timestamp or time.strftime("%Y-%m-%d_%H%M%S")
    archive_root = os.path.join(archive_dir, ts)
    if os.path.exists(archive_root):
        raise RuntimeError(f"归档目录已存在,请稍后重试: {archive_root}")

    manifest = {
        "schema_version": 1,
        "archived_at": ts,
        "git_commit": _git_commit(),
        "segments": [],
        "output_files": [],
    }

    # 第一阶段:复制并逐项校验。此阶段失败时不删除本地素材。
    for item in plan:
        name = item["name"]
        segment_archive = os.path.join(archive_root, name)
        for src in item["images"]:
            _copy_and_verify(src, os.path.join(segment_archive, os.path.basename(src)))
        _copy_and_verify(item["config"], os.path.join(segment_archive, "config.json"))
        _copy_and_verify(item["preview"], os.path.join(archive_root, name + ".mp4"))

        archived_images = list_images(segment_archive, exts=JPEG_EXTS)
        if len(archived_images) != len(item["images"]):
            raise RuntimeError(f"[{name}] JPEG 归档数量校验失败")
        manifest["segments"].append({
            "name": name,
            "frame_count": len(item["images"]),
            "config": f"{name}/config.json",
            "preview": f"{name}.mp4",
        })
        log(f"[{name}] 已归档并校验: {len(item['images'])} 帧 + config + MP4")

    for src in output_files:
        relative = os.path.relpath(src, output_dir)
        _copy_and_verify(src, os.path.join(archive_root, "output", relative))
        manifest["output_files"].append(relative.replace(os.sep, "/"))

    os.makedirs(archive_root, exist_ok=True)
    manifest_path = os.path.join(archive_root, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)

    # 第二阶段:全部归档完成后才删除本地任务。
    for item in plan:
        shutil.rmtree(item["segment"])
        log(f"[{item['name']}] 已删除 01_input 分段目录")

    if os.path.isdir(preview_dir):
        for name in os.listdir(preview_dir):
            path = os.path.join(preview_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        log("03_preview/ 已清空")

    log(f"清理完成:归档位于 {archive_root}")
    return archive_root


def main():
    parser = argparse.ArgumentParser(description="归档成果并清理当前延时摄影任务")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划,不复制或删除")
    parser.add_argument("--yes", action="store_true", help="跳过 DELETE 确认,用于自动化")
    args = parser.parse_args()
    run_cleanup(dry_run=args.dry_run, confirmed=args.yes)


if __name__ == "__main__":
    main()
