#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI


DEFAULT_MODEL = "gpt-image-1.5"
MAX_N_PER_REQUEST = 10


@dataclass
class PromptItem:
    prompt: str
    filename: str | None = None


@dataclass
class RunConfig:
    model: str
    size: str
    quality: str
    output_format: str
    background: str | None
    per_prompt: int
    sleep: float
    retries: int
    resume: bool
    extension: str
    output_dir: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch generate images with the OpenAI Images API."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to .txt, .csv, or .jsonl input file.",
    )
    parser.add_argument(
        "--out",
        default="outputs",
        help="Output directory. Default: outputs",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Image model to use. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--size",
        default="1024x1024",
        choices=["1024x1024", "1024x1536", "1536x1024"],
        help="Output image size.",
    )
    parser.add_argument(
        "--quality",
        default="medium",
        choices=["low", "medium", "high"],
        help="Output image quality.",
    )
    parser.add_argument(
        "--format",
        default="png",
        choices=["png", "jpeg", "webp"],
        help="Output image format.",
    )
    parser.add_argument(
        "--background",
        default=None,
        choices=["transparent", "opaque"],
        help="Optional background mode.",
    )
    parser.add_argument(
        "--per-prompt",
        type=int,
        default=1,
        help="How many images to generate for each prompt. Max 10 per request chunk.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to wait between API requests. Default: 1.0",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="How many prompts to process in parallel. Default: 1",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="How many times to retry a failed request. Default: 3",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip prompts whose target image files already exist.",
    )
    return parser.parse_args()


def slugify(value: str, limit: int = 60) -> str:
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[^A-Za-z0-9._-]", "", value)
    value = value.strip("._-")
    return (value or "image")[:limit]


def load_items(path: Path) -> list[PromptItem]:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if ".txt" in suffixes:
        return load_txt(path)
    if ".csv" in suffixes:
        return load_csv(path)
    if ".jsonl" in suffixes:
        return load_jsonl(path)
    raise ValueError("Only .txt, .csv, and .jsonl input files are supported.")


def load_txt(path: Path) -> list[PromptItem]:
    items: list[PromptItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        prompt = line.strip()
        if not prompt or prompt.startswith("#"):
            continue
        items.append(PromptItem(prompt=prompt))
    return items


def load_csv(path: Path) -> list[PromptItem]:
    items: list[PromptItem] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "prompt" not in reader.fieldnames:
            raise ValueError("CSV must include a 'prompt' column.")
        for row in reader:
            prompt = (row.get("prompt") or "").strip()
            if not prompt:
                continue
            filename = (row.get("filename") or "").strip() or None
            items.append(PromptItem(prompt=prompt, filename=filename))
    return items


def load_jsonl(path: Path) -> list[PromptItem]:
    items: list[PromptItem] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL parse error on line {line_number}: {exc}") from exc
            prompt = str(obj.get("prompt", "")).strip()
            if not prompt:
                continue
            filename = str(obj.get("filename", "")).strip() or None
            items.append(PromptItem(prompt=prompt, filename=filename))
    return items


def chunk_count(total: int, chunk_size: int) -> list[int]:
    chunks: list[int] = []
    remaining = total
    while remaining > 0:
        current = min(chunk_size, remaining)
        chunks.append(current)
        remaining -= current
    return chunks


def save_image(output_path: Path, image_base64: str) -> None:
    output_path.write_bytes(base64.b64decode(image_base64))


def build_base_name(item: PromptItem, index: int) -> str:
    if item.filename:
        return Path(item.filename).stem
    return f"{index:03d}_{slugify(item.prompt)}"


def expected_output_paths(
    output_dir: Path,
    base_name: str,
    per_prompt: int,
    extension: str,
) -> list[Path]:
    return [output_dir / f"{base_name}_{i}.{extension}" for i in range(1, per_prompt + 1)]


def append_manifest_row(lock: Lock, manifest_path: Path, row: dict) -> None:
    with lock:
        with manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_request_args(item: PromptItem, config: RunConfig, n: int) -> dict:
    request_args = {
        "model": config.model,
        "prompt": item.prompt,
        "n": n,
        "size": config.size,
        "quality": config.quality,
        "output_format": config.output_format,
    }
    if config.background:
        request_args["background"] = config.background
    return request_args


def generate_batch(
    client: OpenAI,
    item: PromptItem,
    config: RunConfig,
    n: int,
) -> object:
    last_error: Exception | None = None
    for attempt in range(1, config.retries + 2):
        try:
            return client.images.generate(**build_request_args(item, config, n))
        except Exception as exc:
            last_error = exc
            if attempt > config.retries:
                break
            wait_seconds = max(config.sleep, 0.5) * attempt
            print(f"  retry {attempt}/{config.retries} after error: {exc}", flush=True)
            time.sleep(wait_seconds)
    raise RuntimeError(f"Image generation failed after retries: {last_error}") from last_error


def process_item(
    item_index: int,
    total_items: int,
    item: PromptItem,
    config: RunConfig,
    manifest_path: Path,
    manifest_lock: Lock,
    client: OpenAI,
) -> tuple[bool, str]:
    base_name = build_base_name(item, item_index)
    target_paths = expected_output_paths(
        config.output_dir,
        base_name,
        config.per_prompt,
        config.extension,
    )

    if config.resume and target_paths and all(path.exists() for path in target_paths):
        print(f"[{item_index}/{total_items}] Skipped existing: {item.prompt}", flush=True)
        append_manifest_row(
            manifest_lock,
            manifest_path,
            {
                "index": item_index,
                "prompt": item.prompt,
                "base_name": base_name,
                "status": "skipped",
                "files": [str(path) for path in target_paths],
            },
        )
        return True, "skipped"

    print(f"[{item_index}/{total_items}] Generating for: {item.prompt}", flush=True)
    requests = chunk_count(config.per_prompt, MAX_N_PER_REQUEST)
    image_counter = 0
    saved_files: list[str] = []
    total_tokens: int | None = None

    try:
        for batch_index, n in enumerate(requests, start=1):
            response = generate_batch(client, item, config, n)

            for image in response.data or []:
                image_counter += 1
                output_path = config.output_dir / f"{base_name}_{image_counter}.{config.extension}"
                if not image.b64_json:
                    raise RuntimeError("API returned no image data.")
                save_image(output_path, image.b64_json)
                saved_files.append(str(output_path))
                print(f"  saved: {output_path}", flush=True)

            usage = getattr(response, "usage", None)
            if usage and getattr(usage, "total_tokens", None) is not None:
                total_tokens = (total_tokens or 0) + usage.total_tokens

            if batch_index < len(requests) and config.sleep > 0:
                time.sleep(config.sleep)

        append_manifest_row(
            manifest_lock,
            manifest_path,
            {
                "index": item_index,
                "prompt": item.prompt,
                "base_name": base_name,
                "status": "success",
                "files": saved_files,
                "total_tokens": total_tokens,
            },
        )
        return True, "success"
    except Exception as exc:
        append_manifest_row(
            manifest_lock,
            manifest_path,
            {
                "index": item_index,
                "prompt": item.prompt,
                "base_name": base_name,
                "status": "failed",
                "files": saved_files,
                "error": str(exc),
            },
        )
        return False, str(exc)


def main() -> int:
    args = parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Missing OPENAI_API_KEY environment variable.", file=sys.stderr)
        return 1

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        items = load_items(input_path)
    except Exception as exc:
        print(f"Failed to load input file: {exc}", file=sys.stderr)
        return 1

    if not items:
        print("No prompts found in input file.", file=sys.stderr)
        return 1

    if args.per_prompt < 1:
        print("--per-prompt must be at least 1.", file=sys.stderr)
        return 1
    if args.workers < 1:
        print("--workers must be at least 1.", file=sys.stderr)
        return 1
    if args.retries < 0:
        print("--retries cannot be negative.", file=sys.stderr)
        return 1

    config = RunConfig(
        model=args.model,
        size=args.size,
        quality=args.quality,
        output_format=args.format,
        background=args.background,
        per_prompt=args.per_prompt,
        sleep=args.sleep,
        retries=args.retries,
        resume=args.resume,
        extension="jpg" if args.format == "jpeg" else args.format,
        output_dir=output_dir,
    )

    manifest_path = output_dir / "manifest.jsonl"
    manifest_lock = Lock()
    success_count = 0
    failed_count = 0
    skipped_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for item_index, item in enumerate(items, start=1):
            client = OpenAI(api_key=api_key)
            futures.append(
                executor.submit(
                    process_item,
                    item_index,
                    len(items),
                    item,
                    config,
                    manifest_path,
                    manifest_lock,
                    client,
                )
            )

        for future in as_completed(futures):
            ok, detail = future.result()
            if ok and detail == "skipped":
                skipped_count += 1
            elif ok:
                success_count += 1
            else:
                failed_count += 1
                print(f"  failed: {detail}", file=sys.stderr, flush=True)

    print(
        f"Finished. success={success_count} skipped={skipped_count} failed={failed_count} "
        f"output={output_dir} manifest={manifest_path}"
    )
    return 0 if failed_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
