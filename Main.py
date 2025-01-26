import os
import json
import googleapiclient.discovery
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from pydub import AudioSegment
from google.cloud import speech
import io
import subprocess
import tempfile
import logging
import time
import imageio_ffmpeg
import arxiv
import requests
from pdfminer.high_level import extract_text  # Or use PyMuPDF as per your preference
import re

# Load environment variables from .env file
load_dotenv()

# Fetch API keys from environment variables
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not YOUTUBE_API_KEY:
    raise ValueError("No YouTube API key provided. Please set the YOUTUBE_API_KEY environment variable in .env file.")
if not GOOGLE_APPLICATION_CREDENTIALS:
    raise ValueError("No Google Application Credentials provided. Please set the GOOGLE_APPLICATION_CREDENTIALS environment variable in .env file.")

# Define the system message
SYSTEM_MESSAGE = "Marv is a factual chatbot that gives look-maxxing advice. Marv is a realist who gives the harsh truth but is never pessimistic."

# Configure logging
logging.basicConfig(
    filename='transcript_extraction.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Get the path to the FFmpeg executable provided by imageio_ffmpeg
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# Check if FFmpeg executable exists
if not os.path.isfile(FFMPEG_PATH):
    logging.critical(f"FFmpeg executable not found at {FFMPEG_PATH}")
    raise FileNotFoundError(f"FFmpeg executable not found at {FFMPEG_PATH}")
else:
    logging.info(f"FFmpeg is available at: {FFMPEG_PATH}")
    print(f"FFmpeg is available at: {FFMPEG_PATH}")

# Set pydub's FFmpeg path
AudioSegment.converter = FFMPEG_PATH

# Also set the environment variable for FFmpeg
os.environ["FFMPEG_BINARY"] = FFMPEG_PATH

# Verify FFmpeg is working
try:
    subprocess.run([FFMPEG_PATH, '-version'], check=True, capture_output=True, text=True)
    print("FFmpeg is working correctly.")
except subprocess.CalledProcessError:
    print("FFmpeg executable is not working.")
    raise

def get_channel_id(channel_url):
    # (Existing implementation)
    parsed_url = urlparse(channel_url)
    path_segments = parsed_url.path.strip('/').split('/')

    if len(path_segments) == 0:
        raise ValueError("Invalid YouTube channel URL.")

    if path_segments[0] == 'channel':
        # URL format: https://www.youtube.com/channel/CHANNEL_ID
        return path_segments[1]
    elif path_segments[0] == 'user':
        # URL format: https://www.youtube.com/user/USERNAME
        return get_channel_id_from_username(path_segments[1])
    elif path_segments[0] == 'c':
        # URL format: https://www.youtube.com/c/CUSTOM_NAME
        return get_channel_id_from_custom_url(path_segments[1])
    else:
        raise ValueError("Unsupported YouTube channel URL format.")

def get_channel_id_from_username(username):
    # (Existing implementation)
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.channels().list(
        part="id",
        forUsername=username
    )
    response = request.execute()
    items = response.get('items', [])
    if not items:
        raise ValueError(f"No channel found for username: {username}")
    return items[0]['id']

def get_channel_id_from_custom_url(custom_name):
    # (Existing implementation)
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        part="snippet",
        q=custom_name,
        type="channel",
        maxResults=1
    )
    response = request.execute()
    items = response.get('items', [])
    if not items:
        raise ValueError(f"No channel found for custom name: {custom_name}")
    return items[0]['snippet']['channelId']

def get_uploads_playlist_id(channel_id):
    # (Existing implementation)
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    )
    response = request.execute()
    items = response.get('items', [])
    if not items:
        raise ValueError(f"No channel found with ID: {channel_id}")
    uploads_playlist_id = items[0]['contentDetails']['relatedPlaylists']['uploads']
    return uploads_playlist_id

def get_all_videos_from_playlist(playlist_id):
    # (Existing implementation)
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    video_ids = []
    video_titles = []
    next_page_token = None

    while True:
        request = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()

        for item in response['items']:
            video_id = item['contentDetails']['videoId']
            title = item['snippet']['title']
            video_ids.append(video_id)
            video_titles.append(title)

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return video_ids, video_titles

def download_audio(video_id):
    # (Existing implementation with added logging for the command)
    download_dir = "downloaded_audios"
    os.makedirs(download_dir, exist_ok=True)  # Create the directory if it doesn't exist
    audio_file = os.path.join(download_dir, f"{video_id}.wav")  # Save each audio file with its video ID

    command = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", "wav",
        "--ffmpeg-location", FFMPEG_PATH,  # Specify FFmpeg path
        "-o", audio_file,  # Output file path
        f"https://www.youtube.com/watch?v={video_id}"
    ]

    logging.info(f"Executing command: {' '.join(command)}")

    try:
        subprocess.run(command, check=True)
        logging.info(f"Successfully downloaded audio for video ID: {video_id}")
        return audio_file
    except subprocess.CalledProcessError as e:
        logging.error(f"Error downloading audio for video ID {video_id}: {e}")
        return None
    except FileNotFoundError as e:
        logging.error(f"Command not found: {e}")
        return None

def transcribe_audio(audio_path):
    # (Existing implementation)
    client = speech.SpeechClient()

    with io.open(audio_path, "rb") as audio_file:
        content = audio_file.read()

    audio = speech.RecognitionAudio(content=content)

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        # Adjust sample_rate_hertz based on the audio file
        sample_rate_hertz=16000,
        language_code="en-US",
    )

    try:
        response = client.recognize(config=config, audio=audio)
    except Exception as e:
        logging.error(f"Error during transcription: {e}")
        return "Failed to transcribe transcript."

    # Concatenate the transcript of all results
    transcript = ""
    for result in response.results:
        transcript += result.alternatives[0].transcript + " "

    return transcript.strip()

def fetch_transcript(video_id):
    # (Updated to include deletion after transcription)
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = "\n".join([entry['text'] for entry in transcript_list])
        logging.info(f"Successfully fetched transcript for video ID: {video_id}")
        return transcript
    except (TranscriptsDisabled, NoTranscriptFound):
        logging.warning(f"Transcripts are disabled or not available for video ID: {video_id}. Attempting automated transcription.")
        audio_path = download_audio(video_id)
        if audio_path:
            transcript = transcribe_audio(audio_path)
            delete_audio_file(audio_path)  # Delete after transcription
            return transcript
        else:
            return "Failed to download audio for transcription."
    except Exception as e:
        logging.error(f"An unexpected error occurred for video ID {video_id}: {e}")
        return f"An error occurred: {str(e)}"

def save_transcripts_to_jsonl(video_titles, transcripts, filename="fine_tuning_data.jsonl"):
    # (Existing implementation)
    with open(filename, 'a', encoding='utf-8') as file:
        for title, transcript in zip(video_titles, transcripts):
            # Construct the messages list
            messages = [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": f"Video Title: {title}"},
                {"role": "assistant", "content": transcript}
            ]
            # Create the JSON object
            json_object = {"messages": messages}
            # Write the JSON object as a single line
            file.write(json.dumps(json_object, ensure_ascii=False) + "\n")
    print(f"Fine-tuning data has been saved to {filename}")
    logging.info(f"Fine-tuning data has been saved to {filename}")

def read_channel_links(file_path="channellink.txt"):
    # (Existing implementation)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")

    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Remove any leading/trailing whitespace and ignore empty lines
    channel_urls = []
    playlist_urls = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("playlist:"):
            playlist_url = line[len("playlist:"):].strip()
            playlist_urls.append(playlist_url)
        else:
            channel_urls.append(line)

    if not channel_urls and not playlist_urls:
        raise ValueError(f"The file '{file_path}' does not contain any valid URLs.")

    return channel_urls, playlist_urls

def delete_audio_file(audio_path):
    # (Existing implementation)
    try:
        os.remove(audio_path)
        logging.info(f"Deleted audio file: {audio_path}")
    except OSError as e:
        logging.warning(f"Failed to delete audio file {audio_path}: {e}")

# ---------- Research Papers Integration ----------

def search_arxiv(query, max_results=10):
    """
    Searches arXiv for papers matching the query.
    """
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )
    papers = []
    for result in search.results():
        paper = {
            'id': result.get_short_id(),
            'title': result.title,
            'authors': [author.name for author in result.authors],
            'abstract': result.summary,
            'pdf_url': result.pdf_url
        }
        papers.append(paper)
    return papers

def download_pdf(pdf_url, save_path):
    """
    Downloads the PDF from the given URL.
    """
    try:
        response = requests.get(pdf_url)
        response.raise_for_status()  # Check for HTTP errors
        with open(save_path, 'wb') as f:
            f.write(response.content)
        logging.info(f"Downloaded PDF from {pdf_url} to {save_path}")
        return save_path
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download PDF from {pdf_url}: {e}")
        return None

def extract_text_from_pdf(pdf_path):
    """
    Extracts text from the PDF using pdfminer.six.
    """
    try:
        text = extract_text(pdf_path)
        logging.info(f"Extracted text from {pdf_path}")
        return text
    except Exception as e:
        logging.error(f"Failed to extract text from {pdf_path}: {e}")
        return None

def clean_text(text):
    """
    Cleans the extracted text.
    """
    text = re.sub(r'\n+', '\n', text)  # Replace multiple newlines with single newline
    text = re.sub(r'\s+', ' ', text)   # Replace multiple spaces with single space
    text = text.strip()
    return text

def segment_text(text, max_length=2000):
    """
    Segments text into chunks of max_length characters.
    """
    segments = []
    while len(text) > max_length:
        # Find the last newline within max_length
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        segments.append(text[:split_pos].strip())
        text = text[split_pos:].strip()
    if text:
        segments.append(text)
    return segments

def create_jsonl_entry(system_message, user_content, assistant_content):
    """
    Creates a JSONL entry.
    """
    entry = {
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content}
        ]
    }
    return json.dumps(entry, ensure_ascii=False)

def append_to_jsonl(filename, entries):
    """
    Appends a list of JSON strings to the JSONL file.
    """
    with open(filename, 'a', encoding='utf-8') as file:
        for entry in entries:
            file.write(entry + '\n')
    logging.info(f"Appended {len(entries)} entries to {filename}")

# ---------- Main Execution ----------

def process_research_papers(query, max_results=5, jsonl_filename="fine_tuning_data.jsonl"):
    """
    Searches, downloads, extracts, processes, and appends research papers to JSONL.
    """
    papers = search_arxiv(query, max_results)
    jsonl_entries = []

    for paper in papers:
        print(f"Processing research paper: {paper['title']}")
        pdf_path = os.path.join("research_papers_pdfs", f"{paper['id']}.pdf")
        os.makedirs("research_papers_pdfs", exist_ok=True)

        downloaded_pdf = download_pdf(paper['pdf_url'], pdf_path)
        if not downloaded_pdf:
            continue

        extracted_text = extract_text_from_pdf(downloaded_pdf)
        if not extracted_text:
            continue

        cleaned_text = clean_text(extracted_text)
        segments = segment_text(cleaned_text)

        for segment in segments:
            user_content = f"Research Paper Title: {paper['title']}"
            assistant_content = segment
            jsonl_entry = create_jsonl_entry(SYSTEM_MESSAGE, user_content, assistant_content)
            jsonl_entries.append(jsonl_entry)

        # Optionally, delete the PDF after extraction to save space
        try:
            os.remove(downloaded_pdf)
            logging.info(f"Deleted PDF file: {downloaded_pdf}")
        except OSError as e:
            logging.warning(f"Failed to delete PDF file {downloaded_pdf}: {e}")

    append_to_jsonl(jsonl_filename, jsonl_entries)
    print(f"Appended {len(jsonl_entries)} research paper entries to {jsonl_filename}")

if __name__ == "__main__":
    try:
        print("Reading channel and playlist URLs from 'channellink.txt'...")
        channel_urls, playlist_urls = read_channel_links("channellink.txt")
        print(f"Total channels to process: {len(channel_urls)}")
        print(f"Total additional playlists to process: {len(playlist_urls)}\n")

        all_video_ids = []
        all_video_titles = []

        # Process channel URLs
        for channel_url in channel_urls:
            print(f"Processing channel: {channel_url}")
            channel_id = get_channel_id(channel_url)
            uploads_playlist_id = get_uploads_playlist_id(channel_id)
            video_ids, video_titles = get_all_videos_from_playlist(uploads_playlist_id)
            all_video_ids.extend(video_ids)
            all_video_titles.extend(video_titles)
            print(f"Total videos collected so far: {len(all_video_ids)}\n")

        # Process additional playlist URLs (e.g., Shorts)
        for playlist_url in playlist_urls:
            print(f"Processing additional playlist: {playlist_url}")
            parsed_url = urlparse(playlist_url)
            query_params = parse_qs(parsed_url.query)
            playlist_id = query_params.get('list', [None])[0]
            if not playlist_id:
                print(f"Invalid playlist URL format: {playlist_url}")
                logging.warning(f"Invalid playlist URL format: {playlist_url}")
                continue
            video_ids, video_titles = get_all_videos_from_playlist(playlist_id)
            all_video_ids.extend(video_ids)
            all_video_titles.extend(video_titles)
            print(f"Total videos collected so far: {len(all_video_ids)}\n")

        print("Fetching transcripts for all videos...\n")
        transcripts = []
        for idx, (video_id, title) in enumerate(zip(all_video_ids, all_video_titles), start=1):
            try:
                print(f"Fetching transcript for Video {idx}/{len(all_video_ids)}: {title}")
                transcript = fetch_transcript(video_id)
                transcripts.append(transcript)
            except Exception as e:
                print(f"Failed to process video {video_id}: {str(e)}")
                logging.error(f"Failed to process video {video_id}: {e}")
                transcripts.append("Failed to process transcript.")
            # Optional: Introduce a short delay to respect API rate limits
            time.sleep(0.5)  # Pause for 0.5 seconds between requests

        print("\nSaving all transcripts to JSONL file...")
        save_transcripts_to_jsonl(all_video_titles, transcripts)

        # ---------- Process Research Papers ----------
        # Define your research paper query here
        research_query = "machine learning"  # Example query
        max_research_papers = 5  # Adjust as needed

        print("\nProcessing research papers...")
        process_research_papers(research_query, max_research_papers)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        logging.error(f"Script terminated due to an error: {str(e)}")
