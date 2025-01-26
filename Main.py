import os
import googleapiclient.discovery
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs

# Replace with your actual API key
API_KEY = "AIzaSyAjz0cKEoMxaTbu0Lq4-JYOcpMkeiiFwgM"

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
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
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
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
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
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
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
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
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

def fetch_transcript(video_id):
    """
    Fetches the transcript for a given video ID.
    Returns the transcript as a string or a message if unavailable.
    """
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = "\n".join([entry['text'] for entry in transcript_list])
        return transcript
    except TranscriptsDisabled:
        return "Transcripts are disabled for this video."
    except NoTranscriptFound:
        return "No transcript available for this video."
    except Exception as e:
        return f"An error occurred: {str(e)}"

def save_transcripts_to_txt(video_titles, transcripts, filename="channel_transcripts.txt"):
    """
    Saves the transcripts to a text file with video titles as headers.
    """
    with open(filename, 'w', encoding='utf-8') as file:
        for title, transcript in zip(video_titles, transcripts):
            file.write(f"=== {title} ===\n")
            file.write(transcript + "\n\n")
    print(f"Transcripts have been saved to {filename}")

def read_channel_url(file_path="channellink.txt"):
    """
    Reads the YouTube channel URL from a text file.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")

    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Remove any leading/trailing whitespace and ignore empty lines
    urls = [line.strip() for line in lines if line.strip()]

    if not urls:
        raise ValueError(f"The file '{file_path}' is empty.")

    # For this script, we'll consider only the first URL
    return urls[0]

if __name__ == "__main__":
    try:
        print("Reading channel URL from 'channellink.txt'...")
        channel_url = read_channel_url("channellink.txt")
        print(f"Channel URL: {channel_url}\n")

        print("Extracting channel ID from URL...")
        channel_id = get_channel_id(channel_url)
        print(f"Channel ID: {channel_id}\n")

        print("Retrieving uploads playlist ID...")
        uploads_playlist_id = get_uploads_playlist_id(channel_id)
        print(f"Uploads Playlist ID: {uploads_playlist_id}\n")

        print("Fetching all videos from the uploads playlist...")
        video_ids, video_titles = get_all_videos_from_playlist(uploads_playlist_id)
        print(f"Total videos found: {len(video_ids)}\n")

        transcripts = []
        for idx, (video_id, title) in enumerate(zip(video_ids, video_titles), start=1):
            print(f"Fetching transcript for Video {idx}/{len(video_ids)}: {title}")
            transcript = fetch_transcript(video_id)
            transcripts.append(transcript)

        print("\nSaving transcripts to text file...")
        save_transcripts_to_txt(video_titles, transcripts)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
