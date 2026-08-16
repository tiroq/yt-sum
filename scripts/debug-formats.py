#!/usr/bin/env python3
"""Debug script to check available formats for a YouTube video."""

import sys
import yt_dlp

if len(sys.argv) < 2:
    print("Usage: python debug-formats.py <VIDEO_ID>")
    sys.exit(1)

video_id = sys.argv[1]
url = f"https://www.youtube.com/watch?v={video_id}"

print(f"Checking formats for: {url}")
print()

options = {
    "quiet": False,
    "no_warnings": False,
}

try:
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        print(f"Title: {info.get('title')}")
        print(f"Duration: {info.get('duration')} seconds")
        print()
        print("Available formats:")
        print()
        for fmt in info.get("formats", []):
            format_id = fmt.get("format_id")
            ext = fmt.get("ext")
            acodec = fmt.get("acodec")
            vcodec = fmt.get("vcodec")
            abr = fmt.get("abr")
            vbr = fmt.get("vbr")
            width = fmt.get("width")
            height = fmt.get("height")
            
            has_audio = acodec and acodec != "none"
            has_video = vcodec and vcodec != "none"
            
            print(f"[{format_id}] {ext} | V:{has_video} A:{has_audio} | ", end="")
            if has_video:
                print(f"{width}x{height}", end=" ")
            if has_audio:
                print(f"{abr}", end="")
            print()
        
        print()
        print("Testing format selections:")
        test_formats = [
            "bestaudio/best",
            "bestaudio",
            "worstaudio",
            "best",
            "bestvideo+bestaudio/best",
        ]
        
        for fmt_spec in test_formats:
            try:
                selected = ydl.format_selector(fmt_spec, info.get("formats", []))
                if selected:
                    print(f"✓ '{fmt_spec}' -> format {selected[0].get('format_id')}")
                else:
                    print(f"✗ '{fmt_spec}' -> no match")
            except Exception as e:
                print(f"✗ '{fmt_spec}' -> {e}")

except yt_dlp.utils.DownloadError as e:
    print(f"Error: {e}")
    sys.exit(1)
