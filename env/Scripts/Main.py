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
from semanticscholar import SemanticScholar
from Bio import Entrez

# ------------------ Setup and Configuration ------------------

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

# Remove trailing backslash if present
FFMPEG_PATH = FFMPEG_PATH.rstrip('\\')

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

# ------------------ YouTube Transcript Extraction Functions ------------------

def get_channel_id(channel_url):
    """
    Extracts the channel ID from a YouTube channel URL.
    Supports URLs in different formats.
    """
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
    """
    Retrieves the channel ID using the YouTube username.
    """
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
    """
    Retrieves the channel ID using the custom URL name.
    """
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
    """
    Retrieves the uploads playlist ID for the given channel ID.
    """
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
    """
    Fetches all video IDs and titles from the specified playlist.
    """
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
    """
    Downloads the audio of a YouTube video and returns the file path.
    Saves audio to a persistent directory.
    Note: Downloading YouTube videos may violate YouTube's Terms of Service.
    Ensure you have the rights and permissions to download and process the video.
    """
    YTDLP_PATH = r"C:\Users\Jarrod\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\local-packages\Python311\Scripts\yt-dlp.exe"

    if not os.path.isfile(YTDLP_PATH):
        logging.error(f"yt-dlp executable not found at {YTDLP_PATH}")
        return None

    download_dir = "downloaded_audios"
    os.makedirs(download_dir, exist_ok=True)  # Create the directory if it doesn't exist
    audio_file = os.path.join(download_dir, f"{video_id}.wav")  # Save each audio file with its video ID

    command = [
        YTDLP_PATH,  # Use absolute path
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
    """
    Transcribes the audio file using Google Cloud Speech-to-Text API.
    """
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
    """
    Attempts to fetch the transcript using YouTubeTranscriptApi.
    If unavailable, downloads the audio and transcribes it using Speech-to-Text.
    Returns the transcript as a string.
    """
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
    """
    Saves the transcripts to a JSONL file with 'messages' field.
    Each JSON object contains a list of messages with roles.
    """
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
    """
    Reads multiple YouTube channel and playlist URLs from a text file.
    Returns two lists: channel_urls and playlist_urls.
    Playlist URLs should be prefixed with 'playlist:' in the file.
    """
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
    """
    Deletes the specified audio file to save disk space.
    """
    try:
        os.remove(audio_path)
        logging.info(f"Deleted audio file: {audio_path}")
    except OSError as e:
        logging.warning(f"Failed to delete audio file {audio_path}: {e}")

# ------------------ Research Papers Integration Functions ------------------

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

def search_semantic_scholar(query, max_results=10):
    """
    Searches Semantic Scholar for papers matching the query.
    """
    scholar = SemanticScholar()
    search_results = scholar.search_paper(query, limit=max_results)
    papers = []
    for result in search_results:
        paper = {
            'id': result.paper_id,
            'title': result.title,
            'authors': [author.name for author in result.authors],
            'abstract': result.abstract,
            'pdf_url': result.pdf_url  # May be None
        }
        papers.append(paper)
    return papers

def search_pubmed(query, max_results=10):
    """
    Searches PubMed for papers matching the query.
    """
    Entrez.email = "your_email@example.com"  # Replace with your email
    handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
    record = Entrez.read(handle)
    id_list = record['IdList']
    handle.close()
    
    papers = []
    if id_list:
        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="text")
        abstracts = handle.read().split('\n\n')
        handle.close()
        
        for i, pmid in enumerate(id_list):
            paper = {
                'id': pmid,
                'title': f"PubMed Paper {pmid}",  # For detailed titles, use additional parsing or APIs
                'authors': [],  # Parsing authors can be complex
                'abstract': abstracts[i] if i < len(abstracts) else "",
                'pdf_url': None  # PubMed does not provide direct PDF URLs
            }
            papers.append(paper)
    return papers

def download_pdf(pdf_url, save_path):
    """
    Downloads the PDF from the given URL if available.
    """
    if not pdf_url:
        logging.warning(f"No PDF URL provided for {save_path}. Skipping download.")
        return None
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

def process_research_papers(queries, max_results_per_query=5, jsonl_filename="fine_tuning_data.jsonl"):
    """
    Searches, downloads, extracts, processes, and appends research papers from arXiv, Semantic Scholar, and PubMed to JSONL.
    """
    jsonl_entries = []
    
    for query in queries:
        print(f"Searching arXiv for query: {query}")
        arxiv_papers = search_arxiv(query, max_results=max_results_per_query)
        print(f"Found {len(arxiv_papers)} papers on arXiv.")
        
        print(f"Searching Semantic Scholar for query: {query}")
        semantic_papers = search_semantic_scholar(query, max_results=max_results_per_query)
        print(f"Found {len(semantic_papers)} papers on Semantic Scholar.")
        
        print(f"Searching PubMed for query: {query}")
        pubmed_papers = search_pubmed(query, max_results=max_results_per_query)
        print(f"Found {len(pubmed_papers)} papers on PubMed.")
        
        # Combine all papers
        all_papers = arxiv_papers + semantic_papers + pubmed_papers
        
        for paper in all_papers:
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

    if jsonl_entries:
        append_to_jsonl(jsonl_filename, jsonl_entries)
        print(f"Appended {len(jsonl_entries)} research paper entries to {jsonl_filename}")
    else:
        print("No research paper entries to append.")

def read_research_queries(file_path="researchQuery.txt"):
    """
    Reads research paper queries from a text file.
    Each line in the file is considered a separate query.
    """
    if not os.path.exists(file_path):
        logging.error(f"The file '{file_path}' does not exist.")
        return []

    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Remove any leading/trailing whitespace and ignore empty lines
    queries = [line.strip() for line in lines if line.strip()]
    
    if not queries:
        logging.warning(f"The file '{file_path}' does not contain any valid queries.")
    
    return queries

# ------------------ Research Papers Integration Functions ------------------

# (Already included above)

# ------------------ Main Execution Flow ------------------

if __name__ == "__main__":
    try:
        # Read channel and playlist URLs
        channel_urls, playlist_urls = read_channel_links("channellink.txt")
        
        # Check if channel_urls and playlist_urls are empty
        if channel_urls or playlist_urls:
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
        else:
            print("No channel or playlist URLs found in 'channellinks.txt'. Skipping YouTube transcript extraction.")
            logging.info("No channel or playlist URLs found in 'channellinks.txt'. Skipping YouTube transcript extraction.")

        # ---------- Process Research Papers ----------
        # Read queries from researchQuery.txt
        research_queries = read_research_queries("researchQuery.txt")
        if research_queries:
            print("\nProcessing research papers based on queries from 'researchQuery.txt'...")
            process_research_papers(research_queries)
        else:
            print("No research paper queries found to process.")
            logging.info("No research paper queries found to process.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        logging.error(f"Script terminated due to an error: {str(e)}")
