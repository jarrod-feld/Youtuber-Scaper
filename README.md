# YouTube Transcript and Research Paper Extractor
## Overview

The **YouTube Transcript and Research Paper Extractor** is a Python-based tool designed to:

1. **Extract Transcripts from YouTube Videos:**
   - Fetch transcripts using the YouTube Transcript API.
   - If transcripts are unavailable, automatically download audio using `yt-dlp` and transcribe it using Google Cloud's Speech-to-Text API.

2. **Aggregate Research Papers on Facial Ratings:**
   - Search and retrieve papers from multiple sources:
     - **arXiv**
     - **Semantic Scholar**
     - **PubMed**
   - Download available PDFs, extract text, and compile the data into a structured JSONL file suitable for fine-tuning machine learning models.

The tool is particularly useful for researchers, data scientists, and developers focusing on facial ratings, expression analysis, and related fields.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Preparing Input Files](#preparing-input-files)
  - [Running the Script](#running-the-script)
- [Outputs](#outputs)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Features

- **YouTube Transcript Extraction:**
  - Supports multiple YouTube channels and playlists.
  - Automatic fallback to audio transcription if transcripts are disabled or unavailable.

- **Research Paper Aggregation:**
  - Searches across arXiv, Semantic Scholar, and PubMed for relevant papers.
  - Downloads available PDFs and extracts textual content.
  - Segments and cleans extracted text for optimal data usability.

- **Flexible Configuration:**
  - Easily configurable via environment variables.
  - Handles empty input files gracefully, allowing selective processing.

- **Comprehensive Logging:**
  - Detailed logs for monitoring progress and troubleshooting.

---

## Prerequisites

Before setting up the tool, ensure you have the following:

1. **Python 3.8 or Higher:** [Download Python](https://www.python.org/downloads/)
2. **Pip:** Python's package installer (comes bundled with Python).
3. **Git:** For cloning the repository. [Download Git](https://git-scm.com/downloads)
4. **API Keys and Credentials:**
   - **YouTube Data API Key:** [Obtain Here](https://developers.google.com/youtube/v3/getting-started)
   - **Google Cloud Speech-to-Text Credentials:** [Set Up Here](https://cloud.google.com/speech-to-text/docs/quickstart-client-libraries)
   - **Semantic Scholar API Key:** [Check Documentation](https://www.semanticscholar.org/product/api) *(If required)*
   - **PubMed API Access (Entrez):** [Set Up Here](https://www.ncbi.nlm.nih.gov/books/NBK25497/)

5. **FFmpeg:** Required for audio processing.
   - **Download FFmpeg:** [Official Website](https://ffmpeg.org/download.html)
   - **Installation Guide:** [FFmpeg Installation](https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/)

---

## Installation

Follow these steps to set up the tool on your local machine:

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/youtube-research-extractor.git
cd youtube-research-extractor
