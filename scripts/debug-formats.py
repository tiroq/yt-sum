#!/usr/bin/env python3
"""Debug script to check available formats and test audio download for a YouTube video."""

import sys
import tempfile
import time
from pathlib import Path

import yt_dlp

if len(sys.argv) < 2:
    print("Usage: python debug-formats.py <VIDEO_ID> [--download]")
    print()
    print("Examples:")
    print("  python debug-formats.py tSpj7muShX0")
    print("  python debug-formats.py tSpj7muShX0 --download")
    sys.exit(1)

video_id = sys.argv[1]
should_download = "--download" in sys.argv
url = f"https://www.youtube.com/watch?v={video_id}"

print(f"Checking formats for: {url}")
print()

options = {
    "quiet": False,
    "no_warnings": False,
    "socket_timeout": 60,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
}

try:
    with yt_dlp.YoutubeDL(options) as ydl:
        print("Extracting video information...")
        info = ydl.extract_info(url, download=False)
        print(f"✓ Title: {info.get('title')}")
        print(f"✓ Duration: {info.get('duration')} seconds")
        print(f"✓ Channel: {info.get('channel')}")
        print()
        
        formats = info.get("formats", [])
        print(f"Available {len(formats)} formats:")
        print()
        
        audio_formats = []
        video_formats = []
        combined_formats = []
        
        for fmt in formats:
            format_id = fmt.get("format_id")
            ext = fmt.get("ext")
            acodec = fmt.get("acodec", "none")
            vcodec = fmt.get("vcodec", "none")
            abr = fmt.get("abr")
            width = fmt.get("width")
            height = fmt.get("height")
            
            has_audio = acodec and acodec != "none"
            has_video = vcodec and vcodec != "none"
            
            fmt_type = ""
            if has_audio and has_video:
                fmt_type = "A+V"
                combined_formats.append(fmt)
            elif has_audio:
                fmt_type = "AUDIO"
                audio_formats.append(fmt)
            elif has_video:
                fmt_type = "VIDEO"
                video_formats.append(fmt)
            
            print(f"[{format_id:>3}] {fmt_type:6} {ext:5} ", end="")
            if has_video:
                print(f"{width}x{height:4}", end=" ")
            if has_audio:
                print(f"({acodec} {abr})", end="")
            print()
        
        print()
        print(f"Summary: {len(audio_formats)} audio-only, {len(video_formats)} video-only, {len(combined_formats)} combined")
        print()
        
        print("Testing format selector specifications:")
        test_formats = [
            "bestaudio/best",
            "bestaudio",
            "best[vcodec^=avc1][acodec^=mp4a]",
            "best",
            "bestvideo+bestaudio/best",
            "worstaudio",
        ]
        
        for fmt_spec in test_formats:
            # For now, just report if audio formats are available
            audio_found = any(f.get("acodec") and f.get("acodec") != "none" for f in formats)
            if audio_found or fmt_spec == "best":
                print(f"✓ '{fmt_spec:30}' likely matches (has audio formats available)")
            else:
                print(f"✗ '{fmt_spec:30}' likely won't match (no audio formats)")
        
        if should_download:
            print()
            print("Attempting to download audio...")
            with tempfile.TemporaryDirectory() as tmpdir:
                work_dir = Path(tmpdir)
                download_options = {
                    "format": "bestaudio/best",
                    "outtmpl": str(work_dir / "source.%(ext)s"),
                    "quiet": False,
                    "no_warnings": False,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "wav",
                            "preferredquality": "192",
                        }
                    ],
                    "socket_timeout": 60,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }
                }
                
                try:
                    with yt_dlp.YoutubeDL(download_options) as ydl:
                        print(f"Starting download with format: bestaudio/best")
                        ydl.download([url])
                    
                    wav_files = list(work_dir.glob("source.wav"))
                    if wav_files:
                        wav_file = wav_files[0]
                        file_size = wav_file.stat().st_size
                        print(f"✓ Successfully downloaded and converted to WAV: {file_size} bytes")
                    else:
                        print("✗ No WAV file produced")
                        print(f"Files in {work_dir}:")
                        for f in work_dir.iterdir():
                            print(f"  - {f.name}")
                
                except yt_dlp.utils.DownloadError as e:
                    print(f"✗ Download failed: {e}")
                except Exception as e:
                    print(f"✗ Unexpected error: {e}")
                    import traceback
                    traceback.print_exc()

except yt_dlp.utils.DownloadError as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
