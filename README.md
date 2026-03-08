# 🎸 Guitar Score to Text

**楽譜PDF → テキスト変換パイプライン / PDF Music Score → Text Pipeline**

Convert classical guitar scores (PDF or image) into structured text that can be analyzed by AI (e.g. Claude, ChatGPT) for harmonic analysis, memorization aids, and practice guidance.

クラシックギターの楽譜PDFを、AIが理解できるテキスト形式に自動変換します。和声分析・暗譜・練習ガイドの作成に活用できます。

---

## Features / 機能

- **PDF → Image → MusicXML → Text** fully automated pipeline
- **Guitar-specific output**: string estimation, position hints, chord forms
- **Japanese & English** output format
- **GPU acceleration** via remote SSH (oemer + CUDA)
- **AI-ready**: output text can be directly fed to Claude/ChatGPT for analysis

## Pipeline / パイプライン

```
PDF Score ──→ PNG Images ──→ MusicXML ──→ Guitar Text Analysis
            (PyMuPDF)       (oemer OMR)   (music21)
```

## Quick Start / クイックスタート

### 1. Install / インストール

```bash
pip install -r requirements.txt
```

> **Note:** [oemer](https://github.com/BreezeWhite/oemer) requires `onnxruntime`. For GPU acceleration, install `onnxruntime-gpu` instead of `onnxruntime`.

### 2. Basic Usage / 基本的な使い方

```bash
# Convert entire PDF (all pages)
python score_to_text.py "my_score.pdf"

# Convert specific pages only
python score_to_text.py "my_score.pdf" --pages 1,3,5

# Convert a single image
python score_to_text.py "score_page.png"

# Adjust DPI for better/worse quality
python score_to_text.py "my_score.pdf" --dpi 200
```

### 3. Output / 出力

The script generates a text file (default: `<input>_analysis.txt`) containing:

```
======================================================================
クラシックギター楽譜テキスト変換結果
Guitar Score → Text Analysis
======================================================================

【小節 1】
  メロディ（高音部）:
    拍1.0: ド4 (4分) [3弦]
    拍2.0: ミ4 (4分) [2弦]
    拍3.0: ソ4 (4分) [4弦]
  低音（伴奏）:
    拍1.0: ド3 (全) [1弦]
  演奏ポジション:
    中音部: 5-7ポジション推奨

======================================================================
和声進行（ギター用） / Harmonic Progression
======================================================================
  小節1: ド (開放C)
  小節2: ソ (開放G)
  小節3: ラm (開放Am)
```

### 4. Feed to AI / AIに読ませる

Copy the output text and paste it into Claude, ChatGPT, or any AI assistant with a prompt like:

> この楽譜テキストの和声分析をしてください。各小節の和声進行、転調、カデンツを説明してください。暗譜のためのポイントも教えてください。

---

## GPU Acceleration / GPU高速化

OMR processing is **~7x faster with GPU** (~40 sec/page vs ~5 min/page on CPU).

### Option A: Remote GPU via SSH

If you have a GPU machine accessible via SSH:

```bash
python score_to_text.py "my_score.pdf" \
    --remote user@gpu-machine \
    --oemer-bin /path/to/oemer \
    --ld-library-path /path/to/cuda/libs
```

### Option B: Local GPU

Install GPU-enabled onnxruntime:

```bash
pip install onnxruntime-gpu
```

### GPU Environment Setup (conda)

If you encounter cuDNN errors, create a dedicated conda environment:

```bash
conda create -n oemer python=3.11 -y
conda activate oemer
pip install oemer onnxruntime-gpu==1.20.1
pip install nvidia-cudnn-cu12==9.1.0.70 nvidia-cuda-runtime-cu12==12.4.127 nvidia-cublas-cu12==12.4.5.8
```

Set `LD_LIBRARY_PATH` before running:

```bash
export LD_LIBRARY_PATH=$(python -c "import nvidia.cudnn; print(nvidia.cudnn.__path__[0])")/lib:$(python -c "import nvidia.cuda_runtime; print(nvidia.cuda_runtime.__path__[0])")/lib:$(python -c "import nvidia.cublas; print(nvidia.cublas.__path__[0])")/lib:$LD_LIBRARY_PATH
```

---

## CLI Options / コマンドラインオプション

| Option | Description |
|--------|-------------|
| `input` | Input file (PDF, PNG, JPEG, etc.) |
| `-o`, `--output` | Output text file path |
| `--pages` | Pages to process (comma-separated, e.g. `1,3,5`) |
| `--dpi` | DPI for PDF rasterisation (default: 150) |
| `--local` | Force local CPU processing |
| `--remote HOST` | SSH host for remote GPU processing |
| `--remote-dir` | Working dir on remote host (default: `/tmp/omr_work`) |
| `--oemer-bin` | Path to oemer binary on remote host |
| `--ld-library-path` | Extra `LD_LIBRARY_PATH` on remote host |

---

## Requirements / 必要環境

- Python 3.9+
- [PyMuPDF](https://pymupdf.readthedocs.io/) – PDF to image conversion
- [oemer](https://github.com/BreezeWhite/oemer) – Optical Music Recognition
- [music21](https://web.mit.edu/music21/) – MusicXML parsing and analysis

### Optional (for GPU)

- NVIDIA GPU with CUDA 12.x
- `onnxruntime-gpu`
- cuDNN 9.x

---

## Limitations / 制限事項

- OMR accuracy depends on score quality (clean, high-contrast scans work best)
- Complex polyphonic passages may not be recognized perfectly
- Guitar string/position estimation is approximate
- Some pages may fail if oemer cannot parse the layout (retry with different DPI)

---

## Disclaimer / 免責事項

### Copyright Notice / 著作権について

This tool is intended for use with **your own original scores** or **public domain / copyright-free scores**. Users are solely responsible for ensuring that their use of this tool complies with applicable copyright laws.

本ツールは、**ご自身のオリジナル楽譜**または**パブリックドメイン（著作権フリー）の楽譜**での使用を想定しています。著作権法の遵守はユーザーの責任となります。

- Do **not** redistribute converted text of copyrighted scores.
- 著作権のある楽譜の変換テキストを再配布**しないでください**。
- The converted text is a derivative work of the original score.
- 変換テキストは元の楽譜の二次的著作物に該当します。
- Personal study and research use is generally permitted under fair use / private use exceptions.
- 個人の学習・研究目的での利用は、一般的に私的使用の範囲内です。

### No Warranty / 無保証

This software is provided "as is" without warranty of any kind. The authors are not responsible for any errors in the OMR output or the resulting analysis.

本ソフトウェアは「現状のまま」提供され、いかなる保証もありません。OMR出力や解析結果の誤りについて、作者は責任を負いません。

---

## License / ライセンス

MIT License – see [LICENSE](LICENSE)

> **Note:** This project depends on [PyMuPDF](https://pymupdf.readthedocs.io/) which is licensed under AGPL-3.0. PyMuPDF is not bundled with this project; users install it separately via `pip`.

---

## Acknowledgments / 謝辞

- [oemer](https://github.com/BreezeWhite/oemer) by BreezeWhite – Optical Music Recognition engine
- [music21](https://web.mit.edu/music21/) by MIT – Music analysis toolkit
- [PyMuPDF](https://pymupdf.readthedocs.io/) – PDF processing library
