bot.py# ================== EXTRACTOR BOT - FULL bot.py ==================

import os
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from pyrogram import Client, filters
from pyrogram.types import Message
from gtts import gTTS
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

# ================== CONFIG ==================
API_ID = 123456                # <-- PUT YOUR API ID
API_HASH = "YOUR_API_HASH"     # <-- PUT YOUR API HASH
BOT_TOKEN = "YOUR_BOT_TOKEN"   # <-- PUT YOUR BOT TOKEN

CHANNEL_ID = "@YourChannelUsername"
ADMINS = [111111111]

HACKER_IMAGE = "hacker.jpg"
WORK_DIR = Path("work_dir")
WORK_DIR.mkdir(exist_ok=True)

SLIDE_DURATION = 3
BASE_RES = (1280, 720)
FFMPEG = "ffmpeg"
MAX_WORKERS = 4
# ============================================

app = Client("extractor_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def safe_name(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in "-_ ").strip().replace(" ", "_")[:120]

def parse_input_file(path: str) -> List[Dict]:
    items = []
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        url = None
        if "http" in line:
            parts = line.rsplit(" ", 1)
            if parts and parts[-1].startswith("http"):
                url = parts[-1].strip()
                line = parts[0].strip()

        if "|" in line:
            p = [x.strip() for x in line.split("|")]
            if len(p) >= 3:
                vid, title, batch = p[0], p[1], p[2]
            elif len(p) == 2:
                vid, title, batch = p[0], p[1], "Unknown Batch"
            else:
                vid, title, batch = "", p[0], "Unknown Batch"
        else:
            tokens = line.split()
            if tokens and tokens[0].isdigit():
                vid = tokens[0]
                title = " ".join(tokens[1:])
                batch = "Unknown Batch"
            else:
                vid, title, batch = "", line, "Unknown Batch"

        items.append({"id": vid, "title": title, "batch": batch, "url": url})

    return items


def tts_save(title: str, out_mp3: Path):
    try:
        tts = gTTS(text=title, lang="hi")
        tts.save(str(out_mp3))
    except:
        subprocess.run([
            FFMPEG, "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t", "1",
            str(out_mp3)
        ])


def create_slide_with_ffmpeg(title: str, batch: str, slide_path: Path):
    tmp_img = WORK_DIR / "tmp_bg.jpg"
    shutil.copyfile(HACKER_IMAGE, tmp_img)

    safe = safe_name(title)[:50]
    audio_file = WORK_DIR / f"{safe}.mp3"

    tts_save(title, Path(audio_file))

    fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    title_esc = title.replace("'", "\\'")
    batch_esc = batch.replace("'", "\\'")

    draw_title = (
        f"drawtext=fontfile={fontfile}:text='{title_esc}':"
        f"fontcolor=white:fontsize=48:x=(w-text_w)/2:y=60:"
        f"box=1:boxcolor=black@0.55:boxborderw=10"
    )

    draw_batch = (
        f"drawtext=fontfile={fontfile}:text='Batch: {batch_esc}':"
        f"fontcolor=white:fontsize=28:x=(w-text_w)/2:y=h-90:"
        f"box=1:boxcolor=black@0.45:boxborderw=8"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-i", str(tmp_img),
        "-i", str(audio_file),
        "-vf", f"scale={BASE_RES[0]}:{BASE_RES[1]},{draw_title},{draw_batch}",
        "-t", str(SLIDE_DURATION),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "96k",
        str(slide_path)
    ]

    subprocess.run(cmd)
    os.remove(audio_file)
    return str(slide_path)


def ffmpeg_concat(slides: List[str], out_file: Path):
    concat_text = WORK_DIR / "concat.txt"
    with open(concat_text, "w") as f:
        for s in slides:
            f.write(f"file '{s}'\n")

    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_text),
        "-c", "copy",
        str(out_file)
    ])

    return str(out_file)


def generate_multires(final_video: Path, prefix: str):
    out = {}
    resolutions = {
        "144p": (256, 144),
        "240p": (426, 240),
        "360p": (640, 360),
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080)
    }

    for label, (w, h) in resolutions.items():
        out_file = WORK_DIR / f"{prefix}_{label}.mp4"
        subprocess.run([
            FFMPEG, "-y",
            "-i", str(final_video),
            "-vf", f"scale={w}:{h}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "24",
            "-c:a", "aac", "-b:a", "96k",
            str(out_file)
        ])
        out[label] = str(out_file)

    return out


def make_pdf(items: List[Dict], pdf_path: Path):
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(A4))
    width, height = landscape(A4)

    y = height - 2*cm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, y, "Video Extract Summary")
    y -= 2*cm

    for it in items:
        c.setFont("Helvetica", 10)
        line = f"{it['id']}   |   {it['title']}   |   {it['batch']}   |   {it.get('url','')}"
        c.drawString(2*cm, y, line)
        y -= 0.8*cm

        if y < 2*cm:
            c.showPage()
            y = height - 2*cm

    c.save()
    return str(pdf_path)


async def process_batches(message: Message, items: List[Dict]):
    batches = {}

    for x in items:
        batches.setdefault(x["batch"], []).append(x)

    await message.reply_text("Processing... This will take some time.")

    for batch, group in batches.items():
        safe_b = safe_name(batch)
        bdir = WORK_DIR / safe_b
        bdir.mkdir(exist_ok=True)

        slides = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = []
            for i, item in enumerate(group):
                out_slide = bdir / f"slide_{i+1}.mp4"
                futures.append(ex.submit(create_slide_with_ffmpeg, item["title"], item["batch"], out_slide))

            for fut in as_completed(futures):
                slides.append(fut.result())

        final_video = bdir / f"{safe_b}_final_base.mp4"
        ffmpeg_concat(slides, final_video)

        outputs = generate_multires(final_video, safe_b)

        pdf_path = bdir / f"{safe_b}_summary.pdf"
        make_pdf(group, pdf_path)

        # auto post to channel
        await app.send_document(CHANNEL_ID, pdf_path, caption=f"Batch: {batch}")
        for label, fpath in outputs.items():
            await app.send_document(CHANNEL_ID, fpath, caption=f"{batch} — {label}")

        await message.reply_text(f"Batch {batch} done!")


@app.on_message(filters.document | filters.command(["run", "process"]))
async def main_handler(client, message: Message):
    uid = message.from_user.id
    if uid not in ADMINS:
        return await message.reply_text("Not allowed.")

    if message.document:
        src = await message.download(file_name=str(WORK_DIR / "input.txt"))
    else:
        src = "/mnt/data/SSC Pratham Batch-01.txt"

    items = parse_input_file(src)
    await process_batches(message, items)


if __name__ == "__main__":
    print("Extractor Bot Started")
    app.run()

# ================== END ==================
