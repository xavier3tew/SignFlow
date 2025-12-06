import multiprocessing
import os
import re
import subprocess
from threading import Thread
import uuid
import pathlib
import configparser
from pymongo import MongoClient

# Load configuration
config_parser = configparser.ConfigParser()
config_parser.read("config.ini")
config = config_parser['DEFAULT']

# MongoDB configuration
MONGO_HOST = config.get('mongo_host', 'localhost')
MONGO_PORT = int(config.get('mongo_port', '27017'))
MONGO_DB_NAME = config.get('mongo_db_name', 'asl_avatar')
MONGO_COLLECTION_NAME = config.get('table_name', 'gloss_sign_mapping')

# Get project root directory
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Local video directories (absolute paths)
SIGN_VIDEO_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "gloss2pose", "signs")
POSE_VIDEO_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "gloss2pose", "pose")
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")


def get_mongo_client():
    """Create and return a MongoDB client connection."""
    return MongoClient(MONGO_HOST, MONGO_PORT)


def get_mongo_collection():
    """Get MongoDB collection."""
    client = get_mongo_client()
    db = client[MONGO_DB_NAME]
    return db[MONGO_COLLECTION_NAME]


def lambda_handler(event, context):
    """This function takes gloss sentence as input and split them by spaces to individual gloss
    and query MongoDB to get the items matching gloss and returns file paths to concatenated videos
    
    Parameters
    ----------
    event: dict, required
        Input event with "Gloss" key containing the gloss sentence

    context: object, required
        Context (not used, kept for compatibility)

    Returns
    ------
        dict: Object containing file paths to pose and/or sign videos
    """
    # Get the Gloss from event
    return gloss_to_video(event.get("Gloss"))


def gloss_to_video(gloss_sentence, pose_only=False, pre_sign=True):
    """Convert gloss sentence to video by querying MongoDB and concatenating local videos.
    
    Parameters
    ----------
    gloss_sentence: str
        Space-separated gloss sentence (e.g., "IX-1P NAME IX-1P SURESH")
    pose_only: bool, optional
        If True, only return pose videos. Default False.
    pre_sign: bool, optional
        If True, return file paths. If False, return file paths. Default True.
        
    Returns
    ------
    dict: Dictionary with 'PoseURL' and optionally 'SignURL' keys containing file paths
    """
    uniq_key = str(uuid.uuid4())
    sign_ids = []
    
    collection = get_mongo_collection()

    for gloss in gloss_sentence.split(" "):
        gloss = re.sub('[,!?.]', '', gloss.strip())
        if not gloss:
            continue
            
        # Query MongoDB for matching gloss
        result = collection.find_one({"Gloss": gloss})
        
        # If not found, try finger spelling (character by character)
        if result is None:
            for c in gloss:
                char_result = collection.find_one({"Gloss": c})
                if char_result:
                    sign_ids.append(char_result['SignID'])
        else:
            sign_ids.append(result['SignID'])
    
    if not sign_ids:
        print(f"Warning: No SignIDs found for gloss sentence: {gloss_sentence}")
        return {'PoseURL': None, 'SignURL': None} if not pose_only else {'PoseURL': None}
    
    # Process videos in parallel threads
    manager = multiprocessing.Manager()
    return_dict = manager.dict()
    
    p1 = Thread(target=process_videos, args=(return_dict, "sign", sign_ids, uniq_key, pre_sign))
    p1.start()

    
    p1.join()
    return {'SignURL': return_dict.get("sign")}


    # return {'PoseURL': process_vides("pose", sign_ids,uniq_key),
    #         'SignURL': process_vides("sign", sign_ids,uniq_key)}


def find_ffmpeg():
    """Find ffmpeg executable path."""
    # Try common Windows installation paths
    common_paths = [
        r"D:\ffmpeg-2025-12-04-git-d6458f6a8b-full_build\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    
    # Check if ffmpeg is in PATH
    try:
        result = subprocess.run(["where.exe", "ffmpeg"], capture_output=True, text=True, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0]
    except:
        pass
    
    # Check common paths
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    # Last resort: try just "ffmpeg" (might work if PATH is set correctly)
    return "ffmpeg"


def process_videos(return_dict, video_type, sign_ids, uniq_key, pre_sign):
    """Process videos by copying local files and concatenating them.
    
    Parameters
    ----------
    return_dict: dict
        Shared dictionary to store results
    video_type: str
        Either "sign" or "pose"
    sign_ids: list
        List of SignIDs to process
    uniq_key: str
        Unique key for this processing session
    pre_sign: bool
        If True, return file paths (kept for compatibility)
    """
    # Create temp folder for this session
    temp_folder = os.path.join(TEMP_DIR, uniq_key)
    video_folder = os.path.join(temp_folder, video_type)
    pathlib.Path(video_folder).mkdir(parents=True, exist_ok=True)
    
    # Determine source directory based on video type
    if video_type == "sign":
        source_dir = SIGN_VIDEO_DIR
    else:
        source_dir = POSE_VIDEO_DIR
    
    # Create list file for ffmpeg concat
    list_file = os.path.join(temp_folder, f"{video_type}.txt")
    video_files_found = []
    
    with open(list_file, 'w', encoding='utf-8') as writer:
        for sign_id in sign_ids:
            # Look for video file in local directory
            source_file = os.path.join(source_dir, f"{video_type}-{sign_id}.mp4")
            
            if os.path.exists(source_file):
                # Use absolute path for ffmpeg concat
                abs_path = os.path.abspath(source_file).replace('\\', '/')
                writer.write(f"file '{abs_path}'\n")
                video_files_found.append(source_file)
            else:
                print(f"Warning: Video file not found: {source_file}")
    
    if not video_files_found:
        print(f"Error: No video files found for {video_type} videos")
        return_dict[video_type] = None
        return None
    
    # Concatenate videos using ffmpeg
    output_file = os.path.join(temp_folder, f"{video_type}.mp4")
    ffmpeg_path = find_ffmpeg()
    
    # Use absolute paths for ffmpeg
    abs_list_file = os.path.abspath(list_file).replace('\\', '/')
    abs_output_file = os.path.abspath(output_file).replace('\\', '/')
    
    # Build ffmpeg command
    cmd = f'"{ffmpeg_path}" -f concat -safe 0 -i "{abs_list_file}" -c copy "{abs_output_file}"'
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    
    if result.returncode != 0:
        print(f"Error concatenating {video_type} videos: {result.stderr.decode()}")
        return_dict[video_type] = None
        return None
    
    # Return the file path
    return_dict[video_type] = abs_output_file
    return abs_output_file
#

if __name__ == "__main__":
    print(lambda_handler({"Gloss": "NS-ASIA_2 PAY-ATTENTION GO"}, {}))
