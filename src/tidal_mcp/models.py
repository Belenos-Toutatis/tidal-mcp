"""
Pydantic models for TIDAL MCP Server structured output schemas.

These models provide type-safe, well-documented structures for all tool responses.
Following MCP best practices: minimal transformation, clear descriptions.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Core Entity Models
# =============================================================================

class Track(BaseModel):
    """Structured representation of a TIDAL track."""

    id: str = Field(description="Unique TIDAL track ID")
    title: str = Field(description="Track title")
    artist: str = Field(description="Primary artist name")
    album: str = Field(description="Album name")
    duration_seconds: int = Field(description="Track duration in seconds")
    url: str = Field(description="TIDAL web URL for the track")


class Album(BaseModel):
    """Structured representation of a TIDAL album."""

    id: str = Field(description="Unique TIDAL album ID")
    title: str = Field(description="Album title")
    artist: str = Field(description="Primary artist name")
    release_date: Optional[str] = Field(None, description="Release date (YYYY-MM-DD)")
    num_tracks: int = Field(description="Number of tracks in album")
    duration_seconds: int = Field(description="Total album duration in seconds")
    url: str = Field(description="TIDAL web URL for the album")


class Artist(BaseModel):
    """Structured representation of a TIDAL artist."""

    id: str = Field(description="Unique TIDAL artist ID")
    name: str = Field(description="Artist name")
    url: str = Field(description="TIDAL web URL for the artist")


class Playlist(BaseModel):
    """Structured representation of a TIDAL playlist."""

    id: str = Field(description="Unique playlist ID (UUID)")
    name: str = Field(description="Playlist name")
    description: str = Field(description="Playlist description")
    track_count: int = Field(description="Number of tracks in playlist")
    creator: Optional[str] = Field(None, description="Playlist creator name")
    creator_id: Optional[str] = Field(
        None, description="TIDAL user ID of the creator (use with get_user_profile)"
    )
    url: str = Field(description="TIDAL web URL for the playlist")


# =============================================================================
# List Response Models
# =============================================================================

class TrackList(BaseModel):
    """List of tracks with metadata."""

    status: str = Field(description="Operation status (success/error)")
    query: Optional[str] = Field(None, description="Search query used (for search results)")
    count: int = Field(description="Number of tracks returned")
    tracks: List[Track] = Field(description="List of track objects")


class AlbumList(BaseModel):
    """List of albums with metadata."""

    status: str = Field(description="Operation status (success/error)")
    query: Optional[str] = Field(None, description="Search query used (for search results)")
    count: int = Field(description="Number of albums returned")
    albums: List[Album] = Field(description="List of album objects")


class ArtistList(BaseModel):
    """List of artists with metadata."""

    status: str = Field(description="Operation status (success/error)")
    query: Optional[str] = Field(None, description="Search query used (for search results)")
    count: int = Field(description="Number of artists returned")
    artists: List[Artist] = Field(description="List of artist objects")


class PlaylistList(BaseModel):
    """List of playlists with metadata."""

    status: str = Field(description="Operation status (success/error)")
    query: Optional[str] = Field(None, description="Search query used (for search results)")
    count: int = Field(description="Number of playlists returned")
    playlists: List[Playlist] = Field(description="List of playlist objects")


class PlaylistTracks(BaseModel):
    """Tracks from a specific playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_name: str = Field(description="Name of the playlist")
    playlist_id: str = Field(description="ID of the playlist")
    count: int = Field(description="Number of tracks returned")
    tracks: List[Track] = Field(description="List of track objects")


class AlbumTracks(BaseModel):
    """Tracks from a specific album."""

    status: str = Field(description="Operation status (success/error)")
    album_title: str = Field(description="Title of the album")
    album_id: str = Field(description="ID of the album")
    artist: str = Field(description="Album artist name")
    count: int = Field(description="Number of tracks returned")
    tracks: List[Track] = Field(description="List of track objects")


# =============================================================================
# Operation Result Models
# =============================================================================

class AuthResult(BaseModel):
    """Result of authentication attempt."""

    status: str = Field(description="Operation status (success/error)")
    message: str = Field(description="Status message")
    authenticated: bool = Field(description="Whether authentication was successful")


class CreatePlaylistResult(BaseModel):
    """Result of creating a new playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist: Optional[Playlist] = Field(None, description="Created playlist details")
    message: str = Field(description="Status message")


class AddTracksResult(BaseModel):
    """Result of adding tracks to a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    tracks_added: int = Field(description="Number of tracks successfully added")
    playlist_url: str = Field(description="TIDAL web URL for the playlist")
    message: str = Field(description="Status message")


class RemoveTracksResult(BaseModel):
    """Result of removing tracks from a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    tracks_removed: int = Field(description="Number of tracks successfully removed")
    message: str = Field(description="Status message")


class UpdatePlaylistResult(BaseModel):
    """Result of updating a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist: Optional[Playlist] = Field(None, description="Updated playlist details")
    message: str = Field(description="Status message")


class DeletePlaylistResult(BaseModel):
    """Result of deleting a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the deleted playlist")
    message: str = Field(description="Status message")


class AddToFavoritesResult(BaseModel):
    """Result of adding an item to favorites."""

    status: str = Field(description="Operation status (success/error)")
    item_id: str = Field(description="ID of the item added to favorites")
    item_type: str = Field(description="Type of item (track/album/artist)")
    message: str = Field(description="Status message")


class RemoveFromFavoritesResult(BaseModel):
    """Result of removing an item from favorites."""

    status: str = Field(description="Operation status (success/error)")
    item_id: str = Field(description="ID of the item removed from favorites")
    item_type: str = Field(description="Type of item (track/album/artist)")
    message: str = Field(description="Status message")


class ArtistDetails(BaseModel):
    """Detailed artist information including biography."""

    status: str = Field(description="Operation status (success/error)")
    artist: Artist = Field(description="Artist basic information")
    bio: Optional[str] = Field(None, description="Artist biography text")


class AlbumDetails(BaseModel):
    """Detailed album information."""

    status: str = Field(description="Operation status (success/error)")
    album: Album = Field(description="Album information")


class RadioTracks(BaseModel):
    """Radio/recommendation tracks based on a seed track or artist."""

    status: str = Field(description="Operation status (success/error)")
    seed_id: str = Field(description="ID of the seed track or artist")
    seed_type: str = Field(description="Type of seed (track/artist)")
    seed_name: str = Field(description="Name of the seed track or artist")
    count: int = Field(description="Number of tracks returned")
    tracks: List[Track] = Field(description="List of recommended tracks")


# =============================================================================
# Editorial / Discovery Models
# =============================================================================

class GenreInfo(BaseModel):
    """A TIDAL genre category."""

    name: str = Field(description="Genre display name")
    path: str = Field(description="Genre path identifier (use this in genre tools)")
    has_tracks: bool = Field(description="Genre has tracks available")
    has_albums: bool = Field(description="Genre has albums available")
    has_playlists: bool = Field(description="Genre has playlists available")
    has_artists: bool = Field(description="Genre has artists available")


class GenreList(BaseModel):
    """List of available genres."""

    status: str = Field(description="Operation status (success/error)")
    count: int = Field(description="Number of genres returned")
    genres: List[GenreInfo] = Field(description="List of genre objects")


class MixInfo(BaseModel):
    """A TIDAL personalized mix."""

    id: str = Field(description="Unique mix ID")
    title: str = Field(description="Mix title (e.g. 'My Daily Discovery')")
    sub_title: str = Field(description="Mix subtitle or description")


class MixList(BaseModel):
    """List of personalized mixes."""

    status: str = Field(description="Operation status (success/error)")
    count: int = Field(description="Number of mixes returned")
    mixes: List[MixInfo] = Field(description="List of mix objects")


class MixTracks(BaseModel):
    """Tracks from a specific TIDAL mix."""

    status: str = Field(description="Operation status (success/error)")
    mix_id: str = Field(description="ID of the mix")
    mix_title: str = Field(description="Title of the mix")
    count: int = Field(description="Number of tracks returned")
    tracks: List[Track] = Field(description="List of tracks in the mix")


class TrackLyrics(BaseModel):
    """Lyrics for a TIDAL track."""

    status: str = Field(description="Operation status (success/error)")
    track_id: str = Field(description="ID of the track")
    text: str = Field(description="Plain text lyrics")
    subtitles: Optional[str] = Field(None, description="Timestamped lyrics in LRC format")
    right_to_left: bool = Field(description="True if lyrics language reads right-to-left")


# =============================================================================
# Folder Models
# =============================================================================

class FolderInfo(BaseModel):
    """A TIDAL playlist folder."""

    id: str = Field(description="Unique folder ID")
    name: str = Field(description="Folder name")
    total_items: int = Field(description="Number of playlists in this folder")


class FolderList(BaseModel):
    """List of playlist folders."""

    status: str = Field(description="Operation status (success/error)")
    count: int = Field(description="Number of folders returned")
    folders: List[FolderInfo] = Field(description="List of folder objects")


class CreateFolderResult(BaseModel):
    """Result of creating a folder."""

    status: str = Field(description="Operation status (success/error)")
    folder: FolderInfo = Field(description="Created folder details")
    message: str = Field(description="Status message")


class MovedToFolderResult(BaseModel):
    """Result of moving a playlist into a folder."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the moved playlist")
    folder_id: str = Field(description="ID of the destination folder")
    folder_name: str = Field(description="Name of the destination folder")
    message: str = Field(description="Status message")


class ShufflePlaylistResult(BaseModel):
    """Result of shuffling a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the shuffled playlist")
    track_count: int = Field(description="Number of tracks shuffled")
    message: str = Field(description="Status message")


class RenameFolderResult(BaseModel):
    """Result of renaming a folder."""

    status: str = Field(description="Operation status (success/error)")
    folder_id: str = Field(description="ID of the renamed folder")
    new_name: str = Field(description="New name of the folder")
    message: str = Field(description="Status message")


class DeleteFolderResult(BaseModel):
    """Result of deleting a folder."""

    status: str = Field(description="Operation status (success/error)")
    folder_id: str = Field(description="ID of the deleted folder")
    message: str = Field(description="Status message")


# =============================================================================
# Catalog Detail Models
# =============================================================================

class AudioQuality(BaseModel):
    """Audio quality tiers TIDAL offers for a track or album."""

    max_quality: Optional[str] = Field(
        None, description="Highest tier available (HIGH, LOSSLESS, HI_RES_LOSSLESS)"
    )
    media_tags: List[str] = Field(
        description="Raw TIDAL quality tags (LOSSLESS, HIRES_LOSSLESS, DOLBY_ATMOS...)"
    )
    audio_modes: List[str] = Field(description="Audio modes (STEREO, DOLBY_ATMOS...)")
    lossless: bool = Field(description="True if a lossless FLAC version exists")
    hi_res: bool = Field(description="True if a Hi-Res (24-bit) version exists")
    dolby_atmos: bool = Field(description="True if a Dolby Atmos version exists")
    summary: str = Field(description="Human-readable description of the best quality")


class TrackDetails(BaseModel):
    """Detailed track information."""

    status: str = Field(description="Operation status (success/error)")
    track: Track = Field(description="Track basic information")
    version: Optional[str] = Field(None, description="Version label (e.g. 'Remastered 2011')")
    isrc: Optional[str] = Field(None, description="International Standard Recording Code")
    explicit: bool = Field(description="True if the track is marked explicit")
    popularity: Optional[int] = Field(None, description="TIDAL popularity score (0-100)")
    track_number: Optional[int] = Field(None, description="Position on its album")
    volume_number: Optional[int] = Field(None, description="Disc number on its album")
    release_date: Optional[str] = Field(None, description="Album release date (YYYY-MM-DD)")
    copyright: Optional[str] = Field(None, description="Copyright notice")
    available: bool = Field(description="True if the track can currently be streamed")
    quality: AudioQuality = Field(description="Available audio quality tiers")


class AudioQualityResult(BaseModel):
    """Audio quality of a track or album."""

    status: str = Field(description="Operation status (success/error)")
    item_type: str = Field(description="Type of item (track/album)")
    item_id: str = Field(description="ID of the item")
    title: str = Field(description="Track or album title")
    artist: str = Field(description="Primary artist name")
    quality: AudioQuality = Field(description="Available audio quality tiers")


class AlbumReview(BaseModel):
    """Editorial review of an album."""

    status: str = Field(description="Operation status (success/error)")
    album_id: str = Field(description="ID of the album")
    album_title: str = Field(description="Title of the album")
    artist: str = Field(description="Album artist name")
    text: str = Field(description="Review text")


class ImageUrls(BaseModel):
    """Image URLs for a TIDAL item, by size."""

    status: str = Field(description="Operation status (success/error)")
    item_type: str = Field(description="Type of item (album/artist/playlist/mix/user)")
    item_id: str = Field(description="ID of the item")
    name: str = Field(description="Name of the item")
    urls: Dict[str, str] = Field(description="Image URL keyed by size (e.g. '640x640')")


# =============================================================================
# User Models
# =============================================================================

class UserProfile(BaseModel):
    """Public profile of a TIDAL user."""

    status: str = Field(description="Operation status (success/error)")
    id: str = Field(description="TIDAL user ID")
    name: str = Field(description="Display name")
    handle: Optional[str] = Field(None, description="Profile handle, if set")
    followers: int = Field(description="Number of followers")
    follows: int = Field(description="Number of profiles followed")
    profile_type: Optional[str] = Field(None, description="Profile type (USER_PROFILE...)")
    picture_url: Optional[str] = Field(None, description="Profile picture URL (600x600)")


class FavoriteCounts(BaseModel):
    """Number of items in each favorites collection."""

    status: str = Field(description="Operation status (success/error)")
    tracks: int = Field(description="Number of favorite tracks")
    albums: int = Field(description="Number of favorite albums")
    artists: int = Field(description="Number of followed artists")
    playlists: int = Field(description="Number of favorite playlists (TIDAL counts folders too)")


# =============================================================================
# Editorial Page Models
# =============================================================================

class PageEntry(BaseModel):
    """One item inside an editorial page section."""

    type: str = Field(
        description="Item type: track, album, artist, playlist, mix, link (another page), "
        "external (web link) or text"
    )
    id: Optional[str] = Field(None, description="TIDAL ID, usable with the matching tools")
    title: str = Field(description="Item title or name")
    subtitle: Optional[str] = Field(None, description="Artist, creator or short description")
    path: Optional[str] = Field(None, description="Page path to pass to browse_page (links)")
    url: Optional[str] = Field(None, description="Web URL")


class PageSection(BaseModel):
    """A section (row) of an editorial page, with a preview of its items."""

    index: int = Field(description="Section index, usable with get_page_section")
    title: str = Field(description="Section title")
    item_count: int = Field(description="Number of items in this section on the page")
    more_path: Optional[str] = Field(
        None, description="Page path listing the full section; pass to browse_page"
    )
    items: List[PageEntry] = Field(description="Preview of the section items")


class PageView(BaseModel):
    """An editorial page (Home, Explore, a genre...) split into sections."""

    status: str = Field(description="Operation status (success/error)")
    page: str = Field(description="Page requested")
    title: str = Field(description="Page title")
    count: int = Field(description="Number of sections")
    sections: List[PageSection] = Field(description="Sections of the page")


class PageSectionItems(BaseModel):
    """All items of one editorial page section."""

    status: str = Field(description="Operation status (success/error)")
    page: str = Field(description="Page requested")
    section_index: int = Field(description="Index of the section")
    title: str = Field(description="Section title")
    more_path: Optional[str] = Field(
        None, description="Page path listing even more items; pass to browse_page"
    )
    total: int = Field(description="Number of items in the section")
    offset: int = Field(description="Offset of the first returned item")
    count: int = Field(description="Number of items returned")
    items: List[PageEntry] = Field(description="Section items")


# =============================================================================
# Recommendation & Analysis Models
# =============================================================================

class RecommendedTrack(Track):
    """A recommended track with the seeds that led to it."""

    seed_ids: List[str] = Field(description="Seed track IDs whose radio suggested this track")


class TrackRecommendations(BaseModel):
    """Tracks recommended from several seed tracks."""

    status: str = Field(description="Operation status (success/error)")
    seed_ids: List[str] = Field(description="Seed track IDs used")
    seeds_without_radio: List[str] = Field(description="Seeds for which TIDAL has no radio")
    excluded_count: int = Field(
        description="Distinct suggestions skipped because they are seeds or already in "
        "the excluded playlist"
    )
    count: int = Field(description="Number of tracks returned")
    tracks: List[RecommendedTrack] = Field(
        description="Recommended tracks, those suggested by the most seeds first"
    )


class ArtistShare(BaseModel):
    """How much of a playlist one artist represents."""

    artist: str = Field(description="Artist name")
    track_count: int = Field(description="Number of tracks by this artist")
    percent: float = Field(description="Share of the playlist tracks, in percent")


class DuplicateOccurrence(BaseModel):
    """One occurrence of a duplicated song in a playlist."""

    position: int = Field(
        description="0-based position in the playlist (usable with remove_tracks_from_playlist "
        "indices)"
    )
    track_id: str = Field(description="TIDAL track ID of this occurrence")
    album: str = Field(description="Album of this occurrence")
    version: Optional[str] = Field(None, description="Version label, if any")


class DuplicateGroup(BaseModel):
    """A song that appears more than once in a playlist."""

    title: str = Field(description="Track title")
    artist: str = Field(description="Primary artist name")
    occurrences: List[DuplicateOccurrence] = Field(description="Every occurrence of the song")


class PlaylistAnalysis(BaseModel):
    """Statistics about a playlist's content."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    track_count: int = Field(description="Number of tracks analyzed")
    truncated: bool = Field(description="True if the playlist was too long to analyze fully")
    total_duration_seconds: int = Field(description="Total duration in seconds")
    average_duration_seconds: int = Field(description="Average track duration in seconds")
    distinct_artists: int = Field(description="Number of distinct primary artists")
    top_artists: List[ArtistShare] = Field(description="Most represented artists")
    decades: Dict[str, int] = Field(
        description="Track count per decade of album release (reissues count at their "
        "reissue date)"
    )
    tracks_without_date: int = Field(description="Tracks with no known release date")
    explicit_tracks: int = Field(description="Tracks marked explicit")
    unavailable_tracks: int = Field(description="Tracks that can no longer be streamed")
    consecutive_same_artist: int = Field(
        description="Number of times two adjacent tracks share the same artist"
    )
    duplicate_count: int = Field(description="Number of songs present more than once")
    duplicates: List[DuplicateGroup] = Field(
        description="Songs present more than once (same title and artist, any version)"
    )


class ComparedTrack(BaseModel):
    """A song in a playlist comparison."""

    title: str = Field(description="Track title")
    artist: str = Field(description="Primary artist name")
    track_id_a: Optional[str] = Field(None, description="Track ID in playlist A, if present")
    track_id_b: Optional[str] = Field(None, description="Track ID in playlist B, if present")


class PlaylistComparison(BaseModel):
    """Songs shared by two playlists and songs unique to each."""

    status: str = Field(description="Operation status (success/error)")
    playlist_a_id: str = Field(description="ID of playlist A")
    playlist_a_name: str = Field(description="Name of playlist A")
    playlist_b_id: str = Field(description="ID of playlist B")
    playlist_b_name: str = Field(description="Name of playlist B")
    track_count_a: int = Field(description="Number of tracks in playlist A")
    track_count_b: int = Field(description="Number of tracks in playlist B")
    common_count: int = Field(description="Number of distinct songs in both playlists")
    only_in_a_count: int = Field(description="Number of distinct songs only in A")
    only_in_b_count: int = Field(description="Number of distinct songs only in B")
    lists_truncated: bool = Field(description="True if a list below was cut to max_listed")
    common: List[ComparedTrack] = Field(description="Songs in both playlists")
    only_in_a: List[ComparedTrack] = Field(description="Songs only in playlist A")
    only_in_b: List[ComparedTrack] = Field(description="Songs only in playlist B")


# =============================================================================
# Playlist Editing Results
# =============================================================================

class ClearPlaylistResult(BaseModel):
    """Result of emptying a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    tracks_removed: int = Field(description="Number of items removed")
    message: str = Field(description="Status message")


class MergePlaylistsResult(BaseModel):
    """Result of merging one playlist into another."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the target playlist")
    playlist_name: str = Field(description="Name of the target playlist")
    source_playlist_id: str = Field(description="ID of the source playlist")
    source_playlist_name: str = Field(description="Name of the source playlist")
    tracks_added: int = Field(description="Number of tracks added to the target")
    message: str = Field(description="Status message")


class MoveTracksResult(BaseModel):
    """Result of moving tracks inside a playlist."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    tracks_moved: int = Field(description="Number of tracks moved")
    position: int = Field(description="Target position used")
    message: str = Field(description="Status message")


class PlaylistVisibilityResult(BaseModel):
    """Result of changing a playlist's visibility."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    public: bool = Field(description="True if the playlist is now public")
    message: str = Field(description="Status message")


class AddByIsrcResult(BaseModel):
    """Result of adding tracks to a playlist by ISRC."""

    status: str = Field(description="Operation status (success/error)")
    playlist_id: str = Field(description="ID of the playlist")
    playlist_name: str = Field(description="Name of the playlist")
    tracks_added: int = Field(description="Number of tracks actually added")
    resolved: List[Track] = Field(description="Track chosen for each ISRC that was found")
    not_found: List[str] = Field(description="ISRCs with no matching track on TIDAL")
    message: str = Field(description="Status message")
