#!/usr/bin/env python3
"""
Guitar Score to Text Pipeline
Convert PDF/image music scores to text format for AI analysis.

Pipeline:
    1. PDF → PNG images (PyMuPDF)
    2. PNG → MusicXML (oemer - Optical Music Recognition)
    3. MusicXML → Guitar-specific text analysis (music21)

Usage:
    python score_to_text.py "score.pdf"
    python score_to_text.py "score.pdf" --pages 1,3,5
    python score_to_text.py "score.pdf" --dpi 200
    python score_to_text.py "score.png"
    python score_to_text.py "score.pdf" --remote user@host
    python score_to_text.py "score.pdf" --local
"""

import argparse
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(cmd, check=True, timeout=600):
    """Run a subprocess with UTF-8 encoding (Windows-safe)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, env=env,
    )
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, stdout, stderr)
    return result.returncode, stdout, stderr


# ---------------------------------------------------------------------------
# Step 1 – PDF / image to PNG
# ---------------------------------------------------------------------------

def pdf_to_images(pdf_path, dpi=150, pages=None):
    """Convert PDF pages to PNG images.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for rasterisation (default 150).
        pages: 1-indexed list of page numbers, or None for all pages.

    Returns:
        List of (page_number, image_path) tuples.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    if pages is None:
        page_indices = list(range(total_pages))
    else:
        page_indices = [p - 1 for p in pages]

    images = []
    for idx in page_indices:
        if idx >= total_pages:
            print(f"  [WARN] Page {idx + 1} does not exist (total: {total_pages})")
            continue
        page = doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        img_path = os.path.join(tempfile.gettempdir(), f"score_page_{idx + 1}.png")
        pix.save(img_path)
        images.append((idx + 1, img_path))
        print(f"  Page {idx + 1}/{total_pages}: {pix.width}x{pix.height} px")

    doc.close()
    return images


# ---------------------------------------------------------------------------
# Step 2 – Optical Music Recognition (oemer)
# ---------------------------------------------------------------------------

def run_omr_remote(image_paths, remote_host, remote_dir="/tmp/omr_work",
                   oemer_bin="oemer", ld_library_path=""):
    """Run oemer on a remote machine via SSH/SCP.

    Args:
        image_paths: List of (page_number, local_image_path).
        remote_host: SSH host (e.g. ``user@192.168.0.58`` or an SSH config alias).
        remote_dir: Working directory on the remote machine.
        oemer_bin: Path to the oemer binary on the remote machine.
        ld_library_path: Extra ``LD_LIBRARY_PATH`` to prepend on the remote side
            (needed when cuDNN / CUDA libs are in a non-standard location).

    Returns:
        List of (page_number, local_musicxml_path) tuples.
    """
    musicxml_files = []
    _run(["ssh", remote_host, f"mkdir -p {remote_dir}/output"])

    env_prefix = ""
    if ld_library_path:
        env_prefix = f"export LD_LIBRARY_PATH={ld_library_path}:$LD_LIBRARY_PATH && "

    for page_num, img_path in image_paths:
        img_name = os.path.basename(img_path)
        remote_img = f"{remote_dir}/{img_name}"
        remote_out = f"{remote_dir}/output"

        print(f"  Page {page_num}: uploading image ...")
        _run(["scp", img_path, f"{remote_host}:{remote_img}"])

        print(f"  Page {page_num}: running OMR (this may take 30-60 s with GPU) ...")
        retcode, stdout, stderr = _run(
            ["ssh", remote_host,
             f"{env_prefix}{oemer_bin} {remote_img} -o {remote_out}"],
            check=False, timeout=600,
        )

        if retcode != 0:
            print(f"  [WARN] Page {page_num}: OMR failed")
            for line in stderr.split("\n"):
                if line.strip() and "CUDA" not in line and "onnxruntime" not in line:
                    print(f"    {line}")
            continue

        remote_mxml = f"{remote_out}/{img_name.replace('.png', '.musicxml')}"
        local_mxml = img_path.replace(".png", ".musicxml")
        _run(["scp", f"{remote_host}:{remote_mxml}", local_mxml])
        musicxml_files.append((page_num, local_mxml))
        print(f"  Page {page_num}: done")

    return musicxml_files


def run_omr_local(image_paths):
    """Run oemer locally (CPU – slower).

    Args:
        image_paths: List of (page_number, local_image_path).

    Returns:
        List of (page_number, local_musicxml_path) tuples.
    """
    musicxml_files = []

    for page_num, img_path in image_paths:
        out_dir = os.path.join(tempfile.gettempdir(), "omr_output")
        os.makedirs(out_dir, exist_ok=True)

        print(f"  Page {page_num}: running OMR on CPU (may take 3-5 min) ...")
        result = subprocess.run(
            ["oemer", img_path, "-o", out_dir],
            capture_output=True, text=True, timeout=1800,
        )

        if result.returncode != 0:
            print(f"  [WARN] Page {page_num}: OMR failed")
            continue

        mxml_name = os.path.basename(img_path).replace(".png", ".musicxml")
        local_mxml = os.path.join(out_dir, mxml_name)

        if os.path.exists(local_mxml):
            musicxml_files.append((page_num, local_mxml))
            print(f"  Page {page_num}: done")
        else:
            print(f"  [WARN] Page {page_num}: MusicXML not generated")

    return musicxml_files


# ---------------------------------------------------------------------------
# Step 3 – MusicXML → guitar-specific text
# ---------------------------------------------------------------------------

NOTE_NAME_JP = {
    "C": "ド", "D": "レ", "E": "ミ", "F": "ファ",
    "G": "ソ", "A": "ラ", "B": "シ",
}

DURATION_JP = {
    "whole": "全", "half": "2分", "quarter": "4分",
    "eighth": "8分", "16th": "16分", "32nd": "32分", "64th": "64分",
}

# Standard guitar tuning (MIDI numbers): E2 A2 D3 G3 B3 E4
GUITAR_OPEN_STRINGS = [40, 45, 50, 55, 59, 64]


def _note_name_jp(note):
    """Convert a music21 Note to a Japanese note name."""
    base = NOTE_NAME_JP.get(note.step, note.step)
    if note.pitch.accidental:
        alter = note.pitch.accidental.alter
        if alter == 1:
            base += "♯"
        elif alter == -1:
            base += "♭"
        elif alter == 2:
            base += "♯♯"
        elif alter == -2:
            base += "♭♭"
    return base


def _duration_name(duration):
    """Convert a music21 Duration to a Japanese duration name."""
    name = DURATION_JP.get(duration.type, duration.type)
    if duration.dots > 0:
        name = "付点" * duration.dots + name
    return name


def _estimate_guitar_string(note):
    """Estimate which guitar string a note would be played on (standard tuning)."""
    midi = note.pitch.midi
    for string_num, open_midi in enumerate(GUITAR_OPEN_STRINGS, 1):
        if open_midi <= midi <= open_midi + 12:
            return string_num
    return None


def _suggest_position(notes_data):
    """Suggest left-hand positions based on note register."""
    hints = set()
    for _offset, note_str in notes_data:
        if "5" in note_str:
            hints.add("高音部: 1-3ポジション推奨")
        elif "4" in note_str:
            hints.add("中音部: 5-7ポジション推奨")
        elif "3" in note_str:
            hints.add("低音部: 開放弦-5ポジション")
    return sorted(hints)


def _chord_form(root_jp, acc, quality):
    """Suggest common open-position guitar chord forms."""
    root_map = {"ド": "C", "レ": "D", "ミ": "E", "ファ": "F",
                "ソ": "G", "ラ": "A", "シ": "B"}
    root = root_map.get(root_jp, root_jp) + acc

    if quality == "major":
        forms = {"C": "開放C", "G": "開放G", "D": "開放D",
                 "A": "開放A", "E": "開放E", "F": "Fバレー"}
        return forms.get(root, f"{root}コード")
    elif quality == "minor":
        forms = {"A": "開放Am", "E": "開放Em", "D": "開放Dm"}
        return forms.get(root, f"{root}mコード")
    return None


def parse_musicxml_to_text(musicxml_files, output_path):
    """Parse MusicXML files and write a guitar-oriented text analysis.

    Args:
        musicxml_files: List of (page_number, musicxml_path).
        output_path: Destination text file path.
    """
    import music21 as m21

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("クラシックギター楽譜テキスト変換結果\n")
        f.write("Guitar Score → Text Analysis\n")
        f.write("=" * 70 + "\n\n")

        for page_num, mxml_path in musicxml_files:
            f.write(f"\n{'─' * 70}\n")
            f.write(f"■ ページ {page_num}  /  Page {page_num}\n")
            f.write(f"{'─' * 70}\n\n")

            try:
                score = m21.converter.parse(mxml_path)
            except Exception as e:
                f.write(f"  Parse error: {e}\n\n")
                continue

            # Key & time signatures
            key_sigs = score.flatten().getElementsByClass(m21.key.KeySignature)
            time_sigs = score.flatten().getElementsByClass(m21.meter.TimeSignature)

            if key_sigs:
                ks = key_sigs[0]
                s = ks.sharps
                if s > 0:
                    f.write(f"調号 / Key sig: シャープ{s}個 ({s} sharps)\n")
                elif s < 0:
                    f.write(f"調号 / Key sig: フラット{abs(s)}個 ({abs(s)} flats)\n")
                else:
                    f.write("調号 / Key sig: なし (none)\n")

            if time_sigs:
                f.write(f"拍子 / Time sig: {time_sigs[0].ratioString}\n")

            f.write("ギター音域 / Guitar range: E2 (6th) – E5 (1st open)\n\n")

            # Process first part as guitar
            part = score.parts[0] if score.parts else score
            measures = part.getElementsByClass(m21.stream.Measure)
            prev_m = -1

            for measure in measures:
                m_num = measure.number
                m_label = f"{m_num}b" if m_num == prev_m else str(m_num)
                prev_m = m_num

                f.write(f"【小節 {m_label}】\n")

                # Key-signature changes
                for kc in measure.getElementsByClass(m21.key.KeySignature):
                    s = kc.sharps
                    if s > 0:
                        f.write(f"  ※調号変化: シャープ{s}個\n")
                    elif s < 0:
                        f.write(f"  ※調号変化: フラット{abs(s)}個\n")

                melody, bass, chords = [], [], []

                for elem in measure.flatten().notesAndRests:
                    off = elem.offset
                    if off > 100:  # oemer bug workaround
                        continue

                    if isinstance(elem, m21.note.Rest):
                        melody.append((off, f"休符 ({_duration_name(elem.duration)})"))

                    elif isinstance(elem, m21.note.Note):
                        name = _note_name_jp(elem)
                        dur = _duration_name(elem.duration)
                        s = _estimate_guitar_string(elem)
                        ns = f"{name}{elem.octave} ({dur})"
                        if s:
                            ns += f" [{s}弦]"
                        stem = getattr(elem, "stemDirection", "")
                        (bass if stem == "down" else melody).append((off, ns))

                    elif isinstance(elem, m21.chord.Chord):
                        parts = []
                        for n in elem.notes:
                            sn = _estimate_guitar_string(n)
                            p = f"{_note_name_jp(n)}{n.octave}"
                            if sn:
                                p += f"[{sn}弦]"
                            parts.append(p)
                        dur = _duration_name(elem.duration)
                        chords.append((off, f"[{'+'.join(parts)}] ({dur})"))

                if melody:
                    f.write("  メロディ（高音部）:\n")
                    for off, ns in sorted(melody, key=lambda x: x[0]):
                        f.write(f"    拍{off + 1:.1f}: {ns}\n")
                if chords:
                    f.write("  和音:\n")
                    for off, cs in sorted(chords, key=lambda x: x[0]):
                        f.write(f"    拍{off + 1:.1f}: {cs}\n")
                if bass:
                    f.write("  低音（伴奏）:\n")
                    for off, ns in sorted(bass, key=lambda x: x[0]):
                        f.write(f"    拍{off + 1:.1f}: {ns}\n")

                if melody or chords:
                    hints = _suggest_position(melody + chords)
                    if hints:
                        f.write("  演奏ポジション:\n")
                        for h in hints[:3]:
                            f.write(f"    {h}\n")
                f.write("\n")

            # Harmonic progression
            f.write("=" * 70 + "\n")
            f.write("和声進行（ギター用） / Harmonic Progression\n")
            f.write("=" * 70 + "\n")
            try:
                chordified = score.chordify()
                for measure in chordified.getElementsByClass(m21.stream.Measure):
                    items = []
                    for elem in measure.flatten().getElementsByClass(m21.chord.Chord):
                        if elem.offset > 100:
                            continue
                        try:
                            root = elem.root()
                            quality = elem.quality
                            rjp = NOTE_NAME_JP.get(root.step, root.step)
                            acc = ""
                            if root.accidental:
                                acc = "♯" if root.accidental.alter == 1 else "♭" if root.accidental.alter == -1 else ""
                            q = {"major": "", "minor": "m", "diminished": "dim",
                                 "augmented": "aug", "other": ""}.get(quality, quality)
                            cn = f"{rjp}{acc}{q}"
                            form = _chord_form(rjp, acc, quality)
                            if form:
                                cn += f" ({form})"
                            items.append(cn)
                        except Exception:
                            items.append("[" + ",".join(p.nameWithOctave for p in elem.pitches) + "]")
                    if items:
                        f.write(f"  小節{measure.number}: {' → '.join(items)}\n")
            except Exception as e:
                f.write(f"  Harmonic analysis error: {e}\n")
            f.write("\n")

    print(f"\nOutput saved: {output_path}")


# ---------------------------------------------------------------------------
# Connection check
# ---------------------------------------------------------------------------

def _check_ssh(host):
    """Return True if SSH connection to *host* succeeds."""
    try:
        rc, _, _ = _run(
            ["ssh", "-o", "ConnectTimeout=3", host, "echo ok"],
            check=False, timeout=10,
        )
        return rc == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert a music score (PDF/image) to guitar-oriented text "
                    "that can be fed to an AI for harmonic analysis."
    )
    parser.add_argument("input", help="Input file (PDF, PNG, JPEG, etc.)")
    parser.add_argument("-o", "--output",
                        help="Output text file (default: <input>_analysis.txt)")
    parser.add_argument("--pages",
                        help="Page numbers to process (comma-separated, e.g. 1,3,5)")
    parser.add_argument("--dpi", type=int, default=150,
                        help="DPI for PDF rasterisation (default: 150)")
    parser.add_argument("--local", action="store_true",
                        help="Run OMR locally on CPU (slow, no SSH needed)")
    parser.add_argument("--remote",
                        help="SSH host for remote OMR (e.g. user@192.168.0.58)")
    parser.add_argument("--remote-dir", default="/tmp/omr_work",
                        help="Working directory on the remote host (default: /tmp/omr_work)")
    parser.add_argument("--oemer-bin", default="oemer",
                        help="Path to the oemer binary on the remote host")
    parser.add_argument("--ld-library-path", default="",
                        help="Extra LD_LIBRARY_PATH on the remote host (for cuDNN)")

    args = parser.parse_args()

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    output_path = args.output or os.path.splitext(input_path)[0] + "_analysis.txt"

    pages = None
    if args.pages:
        pages = [int(p) for p in args.pages.split(",")]

    print("=" * 50)
    print("Guitar Score -> Text Pipeline")
    print("=" * 50)

    # -- Step 1 ---------------------------------------------------------------
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".pdf":
        print(f"\n[Step 1] PDF -> images (DPI={args.dpi})")
        images = pdf_to_images(input_path, dpi=args.dpi, pages=pages)
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff"):
        print("\n[Step 1] Reading image file")
        images = [(1, input_path)]
        print(f"  {input_path}")
    else:
        print(f"Error: unsupported file format: {ext}")
        sys.exit(1)

    if not images:
        print("Error: no images to process")
        sys.exit(1)

    # -- Step 2 ---------------------------------------------------------------
    print("\n[Step 2] Optical Music Recognition (oemer)")

    if args.local:
        print("  Mode: local CPU (slow)")
        musicxml_files = run_omr_local(images)
    elif args.remote:
        print(f"  Mode: remote GPU ({args.remote})")
        musicxml_files = run_omr_remote(
            images, args.remote, args.remote_dir,
            args.oemer_bin, args.ld_library_path,
        )
    else:
        # Auto-detect: try oemer locally
        print("  Mode: local CPU (use --remote <host> for GPU acceleration)")
        musicxml_files = run_omr_local(images)

    if not musicxml_files:
        print("Error: no MusicXML files were generated")
        sys.exit(1)

    # -- Step 3 ---------------------------------------------------------------
    print("\n[Step 3] MusicXML -> guitar text analysis")
    parse_musicxml_to_text(musicxml_files, output_path)

    print(f"\nDone! Output: {output_path}")
    print("You can now feed this file to an AI (e.g. Claude) for harmonic analysis.")


if __name__ == "__main__":
    main()
