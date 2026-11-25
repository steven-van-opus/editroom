#!/usr/bin/env python3
"""Validate and render a review cut from timestamped source ranges."""

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Cut:
    start_ms: int
    end_ms: int
    label: str

    @property
    def duration_ms(self):
        return self.end_ms - self.start_ms


def seconds(milliseconds):
    return f"{milliseconds // 1000}.{milliseconds % 1000:03d}"


def probe_source(source):
    reply = subprocess.run(
        [
            "ffprobe", "-v", "error", "-of", "json",
            "-show_entries", "stream=codec_type,duration:format=duration", str(source),
        ],
        check=True, capture_output=True, text=True,
    )
    media = json.loads(reply.stdout)
    streams = media.get("streams", [])
    video = next((stream for stream in streams if stream["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("source must contain a video stream")

    for duration in (video.get("duration"), media.get("format", {}).get("duration")):
        try:
            duration_ms = int(Decimal(duration) * 1000)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            continue
        if duration_ms > 0:
            has_audio = any(stream["codec_type"] == "audio" for stream in streams)
            return duration_ms, has_audio

    raise ValueError("source has no reported video duration")


def load_cuts(path, duration_ms):
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document.get("cuts") if isinstance(document, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("the cut list needs a nonempty cuts array")

    cuts = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"cut {number} must be an object")
        start_ms, end_ms = item.get("start_ms"), item.get("end_ms")
        if type(start_ms) is not int or type(end_ms) is not int:
            raise ValueError(f"cut {number} requires integer start_ms and end_ms")
        if not 0 <= start_ms < end_ms <= duration_ms:
            raise ValueError(
                f"cut {number} must satisfy 0 <= start_ms < end_ms <= {duration_ms}"
            )

        label = item.get("label", f"Cut {number}")
        if not isinstance(label, str) or not label.strip() or not label.isprintable():
            raise ValueError(f"cut {number} needs a printable label")
        cuts.append(Cut(start_ms, end_ms, label))
    return cuts


def render_command(source, cuts, output, has_audio):
    filters = []
    inputs = []
    for index, cut in enumerate(cuts):
        window = f"start={seconds(cut.start_ms)}:end={seconds(cut.end_ms)}"
        filters.append(
            f"[0:v:0]trim={window},setpts=PTS-STARTPTS,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30[v{index}]"
        )
        inputs.append(f"[v{index}]")
        if has_audio:
            filters.append(
                f"[0:a:0]aresample=async=1:first_pts=0,apad,atrim={window},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            inputs.append(f"[a{index}]")

    outputs = "[video][audio]" if has_audio else "[video]"
    filters.append(
        "".join(inputs) + f"concat=n={len(cuts)}:v=1:a={int(has_audio)}" + outputs
    )

    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-n", "-i", str(source),
        "-filter_complex", ";".join(filters),
        "-map", "[video]", "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        command.extend(["-map", "[audio]", "-c:a", "aac", "-b:a", "160k"])
    command.extend(["-movflags", "+faststart", str(output)])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="one local video file")
    parser.add_argument("cut_list", type=Path, help="approved JSON cut list")
    parser.add_argument("output", type=Path, help="new MP4 file to write")
    parser.add_argument("--preview", action="store_true", help="print the plan without rendering")
    options = parser.parse_args()

    try:
        source = options.source.resolve(strict=True)
        output = options.output.resolve()
        if not source.is_file():
            raise ValueError("source must be a local file")
        if output.suffix.lower() != ".mp4" or output.exists():
            raise ValueError("output must be a new .mp4 path")
        if not output.parent.is_dir():
            raise ValueError("output directory does not exist")

        duration_ms, has_audio = probe_source(source)
        cuts = load_cuts(options.cut_list, duration_ms)
        command = render_command(source, cuts, output, has_audio)
        next_at = 0
        for cut in cuts:
            print(
                f"{seconds(next_at)}s  {seconds(cut.start_ms)}s to "
                f"{seconds(cut.end_ms)}s  {cut.label}",
                flush=True,
            )
            next_at += cut.duration_ms
        print(f"Planned duration: {seconds(next_at)}s", flush=True)

        if options.preview:
            print(shlex.join(command))
        else:
            subprocess.run(command, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"cut list: {error}\n")


if __name__ == "__main__":
    main()
