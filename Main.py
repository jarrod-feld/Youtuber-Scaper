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
SYSTEM_MESSAGE = "Marv is a factual chatbot that give looks maxxing advice. Marv is a realist who gives the harsh truth but is never pesimistic."

# Configure logging
logging.basicConfig(
    filename='transcript_extraction.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

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
    Note: Downloading YouTube videos may violate YouTube's Terms of Service.
    Ensure you have the rights and permissions to download and process the video.
    """
    with tempfile.TemporaryDirectory() as tmpdirname:
        audio_file = os.path.join(tmpdirname, "audio.wav")
        try:
            subprocess.run([
                "yt-dlp",
                "-f", "bestaudio",
                "--extract-audio",
                "--audio-format", "wav",
                "-o", audio_file,
                f"https://www.youtube.com/watch?v={video_id}"
            ], check=True)
            return audio_file
        except subprocess.CalledProcessError as e:
            logging.error(f"Error downloading audio for video ID {video_id}: {e}")
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
    with open(filename, 'w', encoding='utf-8') as file:
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
            print(f"Fetching transcript for Video {idx}/{len(all_video_ids)}: {title}")
            transcript = fetch_transcript(video_id)
            transcripts.append(transcript)
            # Optional: Introduce a short delay to respect API rate limits
            time.sleep(0.5)  # Pause for 0.5 seconds between requests

        print("\nSaving all transcripts to JSONL file...")
        save_transcripts_to_jsonl(all_video_titles, transcripts)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        logging.error(f"Script terminated due to an error: {str(e)}")
