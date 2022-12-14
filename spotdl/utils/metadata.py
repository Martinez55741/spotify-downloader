"""
Module for embedding metadata into audio files using Mutagen.

```python
embed_metadata(
    output_file=Path("test.mp3"),
    song=song_object,
    file_format="mp3",
)
```
"""

import base64

from pathlib import Path
from typing import Any, Dict, Optional

import requests

from mutagen._file import File
from mutagen.mp4 import MP4Cover
from mutagen.flac import Picture
from mutagen.id3._frames import APIC, WOAS, USLT, COMM
from mutagen.id3 import ID3

from spotdl.types import Song


class MetadataError(Exception):
    """
    Base class for all exceptions related to metadata and id3 embedding.
    """


# Apple has specific tags - see mutagen docs -
# http://mutagen.readthedocs.io/en/latest/api/mp4.html
M4A_TAG_PRESET = {
    "album": "\xa9alb",
    "artist": "\xa9ART",
    "date": "\xa9day",
    "title": "\xa9nam",
    "year": "\xa9day",
    "originaldate": "purd",
    "comment": "\xa9cmt",
    "group": "\xa9grp",
    "writer": "\xa9wrt",
    "genre": "\xa9gen",
    "tracknumber": "trkn",
    "albumartist": "aART",
    "discnumber": "disk",
    "cpil": "cpil",
    "albumart": "covr",
    "encodedby": "\xa9too",
    "copyright": "cprt",
    "tempo": "tmpo",
    "lyrics": "\xa9lyr",
    "explicit": "rtng",
    "woas": "----:spotdl:WOAS",
}

MP3_TAG_PRESET = {
    "album": "TALB",
    "artist": "TPE1",
    "date": "TDRC",
    "title": "TIT2",
    "year": "TDRC",
    "originaldate": "TDOR",
    "comment": "COMM::XXX",
    "group": "TIT1",
    "writer": "TEXT",
    "genre": "TCON",
    "tracknumber": "TRCK",
    "albumartist": "TPE2",
    "discnumber": "TPOS",
    "cpil": "TCMP",
    "albumart": "APIC",
    "encodedby": "TENC",
    "copyright": "TCOP",
    "tempo": "TBPM",
    "lyrics": "USLT::XXX",
    "woas": "WOAS",
    "explicit": "NULL",
}

TAG_PRESET = {key: key for key in M4A_TAG_PRESET}

TAG_TO_SONG = {
    "title": "name",
    "artist": "artists",
    "album": "album_name",
    "albumartist": "album_artist",
    "genre": "genres",
    "discnumber": "disc_number",
    "year": "year",
    "date": "date",
    "tracknumber": "track_number",
    "encodedby": "publisher",
    "woas": "url",
    "copyright": "copyright_text",
    "lyrics": "lyrics",
}

M4A_TO_SONG = {
    value: TAG_TO_SONG.get(key)
    for key, value in M4A_TAG_PRESET.items()
    if TAG_TO_SONG.get(key)
}
MP3_TO_SONG = {
    value: TAG_TO_SONG.get(key)
    for key, value in MP3_TAG_PRESET.items()
    if TAG_TO_SONG.get(key)
}


def embed_metadata(output_file: Path, song: Song):
    """
    Set ID3 tags for generic files (FLAC, OPUS, OGG)

    ### Arguments
    - output_file: Path to the output file.
    - song: Song object.
    """

    # Get the file extension for the output file
    encoding = output_file.suffix[1:]

    # Get the tag preset for the file extension
    tag_preset = TAG_PRESET if encoding != "m4a" else M4A_TAG_PRESET

    try:
        audio_file = File(str(output_file.resolve()), easy=(encoding == "mp3"))

        if audio_file is None:
            raise MetadataError(
                f"Unrecognized file format for {output_file} from {song.url}"
            )
    except Exception as exc:
        raise MetadataError("Unable to load file.") from exc

    # Embed basic metadata
    audio_file[tag_preset["artist"]] = song.artists
    audio_file[tag_preset["albumartist"]] = song.artist
    audio_file[tag_preset["title"]] = song.name
    audio_file[tag_preset["date"]] = song.date
    audio_file[tag_preset["originaldate"]] = song.date
    audio_file[tag_preset["encodedby"]] = song.publisher

    # Embed metadata that isn't always present
    album_name = song.album_name
    if album_name:
        audio_file[tag_preset["album"]] = album_name

    if len(song.genres) > 0:
        audio_file[tag_preset["genre"]] = song.genres

    if song.copyright_text:
        audio_file[tag_preset["copyright"]] = song.copyright_text

    if song.lyrics and encoding != "mp3":
        audio_file[tag_preset["lyrics"]] = song.lyrics

    if song.download_url and encoding != "mp3":
        audio_file[tag_preset["comment"]] = song.download_url

    # Embed some metadata in format specific ways
    if encoding in ["flac", "ogg", "opus"]:
        # Zero fill the disc and track numbers
        zfilled_disc_number = str(song.disc_number).zfill(len(str(song.disc_count)))
        zfilled_track_number = str(song.track_number).zfill(len(str(song.tracks_count)))

        audio_file[tag_preset["discnumber"]] = zfilled_disc_number
        audio_file[tag_preset["tracknumber"]] = zfilled_track_number
        audio_file[tag_preset["woas"]] = song.url
    elif encoding == "m4a":
        audio_file[tag_preset["discnumber"]] = [(song.disc_number, song.disc_count)]
        audio_file[tag_preset["tracknumber"]] = [(song.track_number, song.tracks_count)]
        audio_file[tag_preset["explicit"]] = (4 if song.explicit is True else 2,)
        audio_file[tag_preset["woas"]] = song.url.encode("utf-8")
    elif encoding == "mp3":
        audio_file["tracknumber"] = f"{str(song.track_number)}/{str(song.tracks_count)}"
        audio_file["discnumber"] = f"{str(song.disc_number)}/{str(song.disc_count)}"

    # Mp3 specific encoding
    if encoding == "mp3":
        audio_file.save()

        audio_file = ID3(str(output_file.resolve()))

        audio_file.add(WOAS(encoding=3, url=song.url))

        if song.lyrics:
            audio_file.add(USLT(encoding=3, text=song.lyrics))

        if song.download_url:
            audio_file.add(COMM(encoding=3, text=song.download_url))

    # Embed album art
    # audio_file = embed_cover(audio_file, song, encoding)

    audio_file.save()


def embed_cover(audio_file, song: Song, encoding: str):
    """
    Embed the album art in the audio file.

    ### Arguments
    - audio_file: Audio file object.
    - song: Song object.
    """

    if not song.cover_url:
        return audio_file

    # Try to download the cover art
    try:
        cover_data = requests.get(song.cover_url, timeout=10).content
    except Exception:
        return audio_file

    # Create the image object for the file type
    if encoding in ["flac", "ogg", "opus"]:
        picture = Picture()
        picture.type = 3
        picture.desc = "Cover"
        picture.mime = "image/jpeg"
        picture.data = cover_data

        if encoding in ["ogg", "opus"]:
            image_data = picture.write()
            encoded_data = base64.b64encode(image_data)
            vcomment_value = encoded_data.decode("ascii")
            audio_file["metadata_block_picture"] = [vcomment_value]
        elif encoding == "flac":
            audio_file.add_picture(picture)
    elif encoding == "m4a":
        audio_file[M4A_TAG_PRESET["albumart"]] = [
            MP4Cover(
                cover_data,
                imageformat=MP4Cover.FORMAT_JPEG,
            )
        ]
    elif encoding == "mp3":
        audio_file["APIC"] = APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover",
            data=cover_data,
        )

    return audio_file


def get_file_metadata(path: Path) -> Optional[Dict[str, Any]]:
    """
    Get song metadata.

    ### Arguments
    - path: Path to the song.

    ### Returns
    - Tuple containing the song name and a dict with other metadata.

    ### Raises
    - OSError: If the file is not found.
    - MetadataError: If the file is not a valid audio file.
    """

    if path.exists() is False:
        raise OSError(f"File not found: {path}")

    audio_file = File(str(path.resolve()))

    if audio_file is None or audio_file == {}:
        return None

    song_meta: Dict[str, Any] = {}
    for key in TAG_PRESET:
        if path.suffix == ".m4a":
            val = audio_file.get(M4A_TAG_PRESET[key])
        elif path.suffix == ".mp3":
            val = audio_file.get(MP3_TAG_PRESET[key])
        else:
            val = audio_file.get(key)

        # If the tag is empty, skip it
        if val is None:
            # If the tag is empty but it's key is in the
            # song object, set it to None
            empty_key = TAG_TO_SONG.get(key)
            if empty_key:
                song_meta[empty_key] = None

            continue

        # MP3 specific decoding
        if path.suffix == ".mp3":
            if key == "woas":
                song_meta["url"] = val.url
            elif key == "year":
                song_meta["year"] = int(str(val.text[0])[:4])
            elif key == "date":
                song_meta["date"] = str(val.text[0])
            elif key == "tracknumber":
                count = val.text[0].split("/")
                if len(count) == 2:
                    song_meta["track_number"] = int(count[0])
                    song_meta["tracks_count"] = int(count[1])
                else:
                    song_meta["track_number"] = val.text[0]
            elif key == "discnumber":
                count = val.text[0].split("/")
                if len(count) == 2:
                    song_meta["disc_number"] = int(count[0])
                    song_meta["disc_count"] = int(count[1])
                else:
                    song_meta["disc_number"] = val.text[0]
            else:
                meta_key = TAG_TO_SONG.get(key)
                if meta_key:
                    song_meta[meta_key] = (
                        val.text[0] if len(val.text) == 1 else val.text
                    )

        # M4A specific decoding
        elif path.suffix == ".m4a":
            if key == "woas":
                song_meta["url"] = val[0].decode("utf-8")
            elif key == "explicit":
                song_meta["explicit"] = val == [4] if val else None
            elif key == "year":
                song_meta["year"] = int(str(val[0])[:4])
            elif key == "discnumber":
                song_meta["disc_number"] = val[0][0]
                song_meta["disc_count"] = val[0][1]
            elif key == "tracknumber":
                song_meta["track_number"] = val[0][0]
                song_meta["tracks_count"] = val[0][1]
            else:
                meta_key = TAG_TO_SONG.get(key)
                if meta_key:
                    song_meta[meta_key] = val[0] if len(val) == 1 else val

        # FLAC, OGG, OPUS specific decoding
        else:
            if key == "originaldate":
                song_meta["year"] = int(str(val[0])[:4])
            elif key == "tracknumber":
                song_meta["track_number"] = int(val[0])
            elif key == "discnumber":
                song_meta["disc_count"] = int(val[0])
            else:
                meta_key = TAG_TO_SONG.get(key)
                if meta_key:
                    song_meta[meta_key] = val[0] if len(val) == 1 else val

    # Add main artist to the song meta object
    song_meta["artist"] = song_meta["artists"][0]

    return song_meta
