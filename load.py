import os
import subprocess
import shutil
import requests

import pandas as pd
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

import configparser

config_parser = configparser.ConfigParser()
config_parser.read("config.ini")
config = config_parser['DEFAULT']

UNFORMATTED_URL = "http://csr.bu.edu/ftp/asl/asllvd/asl-data2/quicktime/{session}/scene{scene}-camera1.mov"
VIDEO_DOWNLOAD_DIR = "./data/raw/gloss2pose/signs/"
FRAME_RATE = 30

def get_mongo_client():
    """Create and return a MongoDB client connection."""
    host = config.get('mongo_host', 'localhost')
    port = int(config.get('mongo_port', '27017'))
    return MongoClient(host, port)


def setup_collection(collection_name, db_name=None):
    """Setup MongoDB collection with unique compound index on Gloss and SignID."""
    if db_name is None:
        db_name = config.get('mongo_db_name', 'asl_avatar')
    
    client = get_mongo_client()
    db = client[db_name]
    collection = db[collection_name]
    try:
        collection.create_index([("Gloss", 1), ("SignID", 1)], unique=True)
        print(f"Collection '{collection_name}' in database '{db_name}' is ready with unique index.")
    except Exception as e:
        # Index might already exist
        print(f"Collection '{collection_name}' setup: {e}")
    
    return collection

def find_ffmpeg():
    """Find ffmpeg executable path"""
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

FFMPEG_PATH = find_ffmpeg()
mongo_collection = setup_collection(config["table_name"])

class VideoSegmentMetadata(object):
    def __init__(self, segment_id, start_frame, end_frame, gloss):
        self.segment_id = segment_id
        self.start_frame = start_frame
        self.end_frame = end_frame
        self.gloss = gloss

class VideoMetadata(object):

    def __init__(self, video_id, url, session, scene, segments_metadata):
        self.video_id = video_id
        self.url = url
        self.session = session
        self.scene = scene
        self.segments_metadata = segments_metadata

def get_video_metadata(csv_filepath, num_partitions = 1 , partition = 0 ):
    metadata = pd.read_csv(csv_filepath)
    print(metadata)
    metadata = metadata[metadata["session_scene_id"] % num_partitions == partition]
    # Remove corrupt segments
    metadata = metadata[metadata["is_corrupt"] == 0]
    # Keep only Liz videos
    metadata = metadata[metadata["Consultant"] == "Liz"]
    collapsed_metadata = metadata[["session_scene_id", "Session", "Scene"]].drop_duplicates().sort_values(
        by=["session_scene_id"])
    collapsed_metadata.index = collapsed_metadata["session_scene_id"]
    metadata["id-start-end-gloss"] = metadata["id"].apply(str) + "$" + \
                                     metadata["Start"].apply(str) + "$" + \
                                     metadata["End"].apply(str) + "$" + \
                                     metadata["Gloss Variant"]
    frames_info = metadata.groupby(["session_scene_id"])["id-start-end-gloss"].apply(list)
    collapsed_metadata = pd.concat([collapsed_metadata, frames_info], axis=1)
    return [
        VideoMetadata(
            value[0],
            UNFORMATTED_URL.format(
                session=value[1],
                scene=value[2]
            ),
            value[1],
            value[2],
            sorted([
                VideoSegmentMetadata(
                    segment_id=int(segment.split("$")[0]),
                    start_frame=int(segment.split("$")[1]),
                    end_frame=int(segment.split("$")[2]),
                    gloss=segment.split("$")[3]
                ) for segment in value[3]
            ], key=lambda x: x.start_frame)
        ) for value in collapsed_metadata.values
    ]

def process_video(video: VideoMetadata):
    print("Downloading {} with video_id {}".format(video.url, video.video_id))
    video_filepath = download_large_file(
        video.url,
        VIDEO_DOWNLOAD_DIR,
        "{}-{}.{}".format(
            video.session,
            video.scene,
            video.url.split(".")[-1]
        )
    )
    for segment in video.segments_metadata:
        print("Processing video segment {}".format(
            segment.segment_id
        ))
        temp_segment_filepath = clip_video(
            video_filepath,
            os.path.join(
                VIDEO_DOWNLOAD_DIR,
                "temp-segment-{}.mov".format(segment.segment_id)
            ),
            segment.start_frame,
            segment.end_frame,
        )

        segment_filepath = resample_video(
            temp_segment_filepath,
            os.path.join(
                VIDEO_DOWNLOAD_DIR,
                "sign-{}.mp4".format(segment.segment_id)
            ),
            FRAME_RATE
        )

        gloss = segment.gloss.upper()
        for g in gloss.split('/'):
            g = g.replace('+', '')
            g = g.replace('#', '')
            # response = table.put_item(
            #     Item={
            #         'Gloss': g,
            #         'SignID': segment.segment_id
            #     }
            # )
            print({
                    'Gloss': g,
                    'SignID': segment.segment_id
                })
            try:
                mongo_collection.insert_one({
                    'Gloss': g,
                    'SignID': segment.segment_id
                    })
            except DuplicateKeyError:
                # Document already exists (due to unique index), skip silently
                pass
            except Exception as e:
                print(f"Error inserting gloss '{g}' with SignID {segment.segment_id}: {e}")

        # Clean up
        # os.remove(temp_segment_filepath)
        # if os.path.exists(segment_filepath):
        #     os.remove(segment_filepath)

    # Update checkpoint after processing entire video
    # checkpoint = s3.Object(S3_BUCKET, checkpoint_filepath)
    # checkpoint.put(Body=r'{}'.format(video.video_id))
    # os.remove(video_filepath)

def clip_video(from_video_filepath, to_video_filepath, start_frame, end_frame):
    """
    create video clip starting at @start_frame and ending at @end_frame inclusive
    """

    unformatted_cmd = "\"{ffmpeg_path}\" -i \"{from_path}\" -vf trim=start_frame={start_frame}:end_frame={end_frame} -y -an \"{to_path}\""

    cmd = unformatted_cmd.format(
        ffmpeg_path=FFMPEG_PATH,
        from_path=from_video_filepath,
        to_path=to_video_filepath,
        start_frame=start_frame,
        end_frame=end_frame + 1,
    )

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error clipping video: {result.stderr}")
        raise RuntimeError(f"ffmpeg failed with return code {result.returncode}")

    return to_video_filepath


def resample_video(from_video_filepath, to_video_filepath, frame_rate):
    """
    resamples video with @frame_rate and outputs new video
    """

    unformatted_cmd = "\"{ffmpeg_path}\" -i \"{from_path}\" -filter:v fps={frame_rate} -q:v 0 -vcodec h264 -y \"{to_path}\""

    cmd = unformatted_cmd.format(
        ffmpeg_path=FFMPEG_PATH,
        from_path=from_video_filepath,
        to_path=to_video_filepath,
        frame_rate=frame_rate,
    )

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error resampling video: {result.stderr}")
        raise RuntimeError(f"ffmpeg failed with return code {result.returncode}")

    return to_video_filepath


def download_large_file(url, download_dir, filename):
    os.makedirs(download_dir, exist_ok=True)
    local_filename = os.path.join(download_dir, filename)
    with requests.get(url, stream=True) as response:
        with open(local_filename, 'wb') as file_obj:
            shutil.copyfileobj(response.raw, file_obj)

    return local_filename


if __name__ == "__main__":
    #local_prep_metadata()
    videos = get_video_metadata(r"data\raw\gloss2pose\video_metadata.csv")
    videoscene = [("ASL_2008_03_28",48)]
    for video in videos:
        if video.session=="ASL_2008_03_28" and video.scene == 48:
            process_video(video)