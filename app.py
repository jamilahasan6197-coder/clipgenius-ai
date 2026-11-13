
import streamlit as st
import os
import subprocess
import tempfile
import zipfile
import re
from pathlib import Path
from faster_whisper import WhisperModel

st.set_page_config(
    page_title="ClipGenius AI",
    page_icon="🎬",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: #101018;
    color: white;
}
h1 {
    color: #a78bfa;
}
.stButton button {
    background: #7545e8;
    color: white;
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)

st.title("🎬 ClipGenius AI")
st.caption("Your private AI-powered video clipping studio")

st.divider()

st.subheader("📁 Upload your video")

uploaded = st.file_uploader(
    "Choose an MP4, MOV or MKV video",
    type=["mp4", "mov", "mkv"]
)

clip_count = st.slider(
    "Number of clips",
    min_value=1,
    max_value=10,
    value=5
)

clip_length = st.slider(
    "Clip duration (seconds)",
    min_value=20,
    max_value=60,
    value=35
)

@st.cache_resource
def load_whisper():
    return WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

def get_duration(path):
    result = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])
    return float(result.decode().strip())

def transcribe(model, path):
    segments, info = model.transcribe(
        str(path),
        beam_size=3,
        vad_filter=True
    )

    data = []
    for seg in segments:
        data.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text.strip()
        })

    return data

KEYWORDS = [
    "wow", "no way", "oh my god", "crazy",
    "insane", "bro", "wait", "amazing",
    "unbelievable", "let's go", "seriously",
    "hilarious", "finally", "impossible"
]

def score_window(transcript, start, end):
    words = 0
    keyword_score = 0
    punctuation_score = 0

    for item in transcript:
        if item["end"] > start and item["start"] < end:
            text = item["text"].lower()
            words += len(text.split())

            punctuation_score += (
                text.count("!") + text.count("?")
            )

            for keyword in KEYWORDS:
                if keyword in text:
                    keyword_score += 1

    duration = max(end - start, 1)

    speech_density = words / duration

    return (
        keyword_score * 3
        + punctuation_score * 0.5
        + min(speech_density, 3) * 4
    )

def find_highlights(transcript, duration, count, length):
    candidates = []
    step = 10

    for start in range(
        0,
        max(1, int(duration - length) + 1),
        step
    ):
        end = min(start + length, duration)

        score = score_window(transcript, start, end)

        candidates.append({
            "start": float(start),
            "end": float(end),
            "score": score
        })

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    selected = []

    for item in candidates:
        overlap = any(
            item["start"] < old["end"] + 5
            and item["end"] > old["start"] - 5
            for old in selected
        )

        if not overlap:
            selected.append(item)

        if len(selected) >= count:
            break

    return sorted(selected, key=lambda x: x["start"])

def srt_time(seconds):
    ms = int(round(seconds * 1000))
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    secs = (ms % 60000) // 1000
    millis = ms % 1000

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{millis:03}"
    )

def make_subtitles(transcript, start, end, filename):
    entries = []
    index = 1

    for item in transcript:
        if item["end"] <= start or item["start"] >= end:
            continue

        local_start = max(0, item["start"] - start)
        local_end = min(end - start, item["end"] - start)

        if local_end <= local_start:
            continue

        text = item["text"].replace("-->", "->")

        entries.append(
            f"{index}\n"
            f"{srt_time(local_start)} --> "
            f"{srt_time(local_end)}\n"
            f"{text}\n"
        )
        index += 1

    Path(filename).write_text(
        "\n".join(entries),
        encoding="utf-8"
    )

def create_clip(video, output, subtitle, start, end):
    duration = end - start

    # Vertical center crop and burned-in subtitles
    filters = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles={subtitle}:"
        "force_style='FontName=Arial,FontSize=18,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=2,Alignment=2,MarginV=100'"
    )

    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start),
        "-i", str(video),
        "-t", str(duration),
        "-vf", filters,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output)
    ]

    subprocess.run(command, check=True)

if uploaded:
    st.video(uploaded)

    if st.button("✨ GENERATE MY CLIPS", type="primary"):

        workdir = tempfile.mkdtemp(
            prefix="clipgenius_"
        )

        video_path = os.path.join(
            workdir, "input_video.mp4"
        )

        with open(video_path, "wb") as f:
            f.write(uploaded.getbuffer())

        try:
            with st.spinner("Checking video..."):
                duration = get_duration(video_path)

            if duration < clip_length:
                st.error(
                    "Video is shorter than your selected clip duration."
                )
                st.stop()

            with st.spinner("Loading Whisper AI..."):
                model = load_whisper()

            with st.spinner("AI is listening to your video..."):
                transcript = transcribe(model, video_path)

            if not transcript:
                st.error("No speech detected.")
                st.stop()

            with st.spinner("Finding interesting moments..."):
                highlights = find_highlights(
                    transcript,
                    duration,
                    clip_count,
                    clip_length
                )

            if not highlights:
                st.error("No suitable highlights found.")
                st.stop()

            output_files = []

            progress = st.progress(0)

            for i, item in enumerate(highlights, 1):
                clip_name = f"ClipGenius_{i}.mp4"

                output_path = os.path.join(
                    workdir, clip_name
                )

                subtitle_path = os.path.join(
                    workdir, f"clip_{i}.srt"
                )

                make_subtitles(
                    transcript,
                    item["start"],
                    item["end"],
                    subtitle_path
                )

                with st.spinner(
                    f"Creating clip {i}/{len(highlights)}..."
                ):
                    create_clip(
                        video_path,
                        output_path,
                        subtitle_path,
                        item["start"],
                        item["end"]
                    )

                output_files.append(output_path)
                progress.progress(
                    i / len(highlights)
                )

            zip_path = os.path.join(
                workdir, "ClipGenius_AI_Clips.zip"
            )

            with zipfile.ZipFile(
                zip_path, "w",
                zipfile.ZIP_DEFLATED
            ) as archive:
                for file in output_files:
                    archive.write(
                        file,
                        arcname=os.path.basename(file)
                    )

            st.success("Your clips are ready!")

            for i, file in enumerate(output_files, 1):
                st.subheader(f"🎬 Clip {i}")
                st.video(file)

                with open(file, "rb") as f:
                    st.download_button(
                        f"Download Clip {i}",
                        data=f.read(),
                        file_name=os.path.basename(file),
                        mime="video/mp4",
                        key=f"download_{i}"
                    )

            with open(zip_path, "rb") as f:
                st.download_button(
                    "📦 Download ALL Clips",
                    data=f.read(),
                    file_name="ClipGenius_AI_Clips.zip",
                    mime="application/zip"
                )

        except Exception as error:
            st.error(f"Something went wrong: {error}")

        finally:
            # Files remain available during the Streamlit session.
            # Temporary files are cleaned up when the session ends.
            pass

else:
    st.info("Upload a video to start creating clips.")

st.divider()
st.caption("ClipGenius AI v1.0 | Private development project")
      
