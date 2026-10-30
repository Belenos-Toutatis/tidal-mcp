#!/usr/bin/env python3
"""
TIDAL MCP Server - Traditional MCP server following official best practices.

A clean API wrapper exposing TIDAL functionality through the Model Context Protocol.
No custom business logic - thin wrappers around tidalapi methods.
"""

import json
import re
import webbrowser
from collections import Counter
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import anyio
import tidalapi
import tidalapi.page
from tidalapi.exceptions import ObjectNotFound
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .robustness import apply_robustness, get_logger

from .models import (
    # Core entities
    Track,
    Album,
    Artist,
    Playlist,
    # List responses
    TrackList,
    AlbumList,
    ArtistList,
    PlaylistList,
    PlaylistTracks,
    AlbumTracks,
    # Detail responses
    ArtistDetails,
    AlbumDetails,
    RadioTracks,
    # Operation results
    AuthResult,
    CreatePlaylistResult,
    AddTracksResult,
    RemoveTracksResult,
    UpdatePlaylistResult,
    DeletePlaylistResult,
    AddToFavoritesResult,
    RemoveFromFavoritesResult,
    # Editorial / Discovery
    GenreInfo,
    GenreList,
    MixInfo,
    MixList,
    MixTracks,
    # Lyrics
    TrackLyrics,
    # Folders
    FolderInfo,
    FolderList,
    CreateFolderResult,
    MovedToFolderResult,
    RenameFolderResult,
    DeleteFolderResult,
    # Shuffle
    ShufflePlaylistResult,
    # Catalog details
    AudioQuality,
    TrackDetails,
    AudioQualityResult,
    AlbumReview,
    ImageUrls,
    # Users & favorites
    UserProfile,
    FavoriteCounts,
    # Editorial pages
    PageEntry,
    PageSection,
    PageView,
    PageSectionItems,
    # Recommendations & analysis
    RecommendedTrack,
    TrackRecommendations,
    ArtistShare,
    DuplicateOccurrence,
    DuplicateGroup,
    PlaylistAnalysis,
    ComparedTrack,
    PlaylistComparison,
    # Playlist editing
    ClearPlaylistResult,
    MergePlaylistsResult,
    MoveTracksResult,
    PlaylistVisibilityResult,
    AddByIsrcResult,
)


# =============================================================================
# Server Configuration
# =============================================================================

SERVER_NAME = "TIDAL MCP"
SERVER_INSTRUCTIONS = """MCP server for TIDAL music streaming service.

A traditional MCP server that exposes TIDAL API functionality as clean tool wrappers.

## Authentication
- Use 'login' tool first to authenticate via OAuth browser flow
- Session is persisted and reused across restarts

## Search Tools
- search_tracks: Find tracks by name, artist, or combination
- search_albums: Find albums by name or artist
- search_artists: Find artists by name
- search_playlists: Find public playlists

## Favorites
- get_favorite_tracks: Get your liked tracks
- get_favorite_albums: Get your saved albums
- get_favorite_artists: Get your followed artists
- add_track_to_favorites: Like a track
- remove_track_from_favorites: Unlike a track
- remove_album_from_favorites: Remove a saved album

## Playlist Management
- get_user_playlists: List your playlists
- get_playlist_tracks: Get tracks from a playlist
- create_playlist: Create a new playlist
- add_tracks_to_playlist: Add tracks to a playlist
- remove_tracks_from_playlist: Remove tracks from a playlist
- update_playlist: Update playlist name/description
- delete_playlist: Delete a playlist

## Content Browsing
- get_album_tracks: Get all tracks from an album
- get_album: Get detailed album information
- get_similar_albums: Find albums similar to a given album

## Artist Discovery
- get_artist: Get artist details with biography
- get_artist_albums: Get an artist's discography
- get_artist_top_tracks: Get an artist's most popular tracks
- get_similar_artists: Find artists similar to a given artist

## Recommendations
- get_track_radio: Get tracks similar to a seed track
- get_artist_radio: Get tracks based on an artist's style
- recommend_tracks: Combine several seed tracks, skipping a playlist's tracks

## Catalog Details
- get_track: Track details (ISRC, version, release date, quality)
- get_audio_quality: Lossless / Hi-Res / Dolby Atmos availability
- get_tracks_by_isrc: Every release of a recording
- get_albums_by_barcode: Album from a CD barcode
- get_album_review: Editorial album review
- get_artist_ep_singles / get_artist_appearances: Rest of a discography
- get_image_urls: Covers, artist photos, playlist and profile pictures

## Editorial Pages
- browse_page: Home, Explore, For You, genres, moods, Hi-Res... section by section
- get_page_section: All items of one section; follow 'path' / 'more_path' with browse_page

## Playlist Analysis & Editing
- analyze_playlist: Duration, top artists, decades, duplicates with positions
- compare_playlists: Shared and unique songs of two playlists
- clear_playlist, merge_playlists, move_playlist_tracks, set_playlist_visibility
- add_tracks_to_playlist_by_isrc, move_playlist_to_root

## Users
- get_user_profile, get_user_public_playlists: use a playlist's creator_id
- get_favorite_counts: Size of each favorites collection
"""

# Initialize MCP server
mcp = FastMCP(
    name=SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
)

# Session management
PROJECT_ROOT = Path(__file__).parent.parent.parent
SESSION_DIR = PROJECT_ROOT / ".tidal-sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = SESSION_DIR / "session.json"

# Global session instance (single-user design)
session = tidalapi.Session()


def _persist_session() -> None:
    """Save current OAuth tokens to disk. Used as the refresh callback."""
    try:
        session_data = {
            "token_type": {"data": session.token_type or "Bearer"},
            "session_id": {"data": session.session_id or ""},
            "access_token": {"data": session.access_token},
            "refresh_token": {"data": session.refresh_token},
            "is_pkce": {"data": session.is_pkce},
        }
        SESSION_FILE.write_text(json.dumps(session_data))
    except Exception as e:
        get_logger().warning(f"Could not write session file: {e}")


# Apply robustness layer: logging, rate limit, timeout, retry, token refresh.
# Must run after `session` is created, before any tool can be called.
apply_robustness(session, PROJECT_ROOT, save_session_callback=_persist_session)


# =============================================================================
# Authentication Helpers
# =============================================================================

async def ensure_authenticated() -> bool:
    """
    Check if user is authenticated with TIDAL.
    Automatically loads persisted session if available.
    """
    if await anyio.Path(SESSION_FILE).exists():
        try:
            async with await anyio.open_file(SESSION_FILE, "r") as f:
                content = await f.read()
                data = json.loads(content)

            # Load OAuth session
            result = await anyio.to_thread.run_sync(
                session.load_oauth_session,
                data["token_type"]["data"],
                data["access_token"]["data"],
                data["refresh_token"]["data"],
                None,  # expiry time
            )

            if result:
                is_valid = await anyio.to_thread.run_sync(session.check_login)
                if not is_valid:
                    await anyio.Path(SESSION_FILE).unlink()
                return is_valid
            return False
        except Exception:
            await anyio.Path(SESSION_FILE).unlink()
            return False

    return await anyio.to_thread.run_sync(session.check_login)


# =============================================================================
# Shared Helpers (extended tools)
# =============================================================================

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}
MAX_PLAYLIST_ITEMS = 2000
ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
WIMP_LINK_PATTERN = re.compile(r"\[wimpLink[^\]]*\](.*?)\[/wimpLink\]", re.DOTALL)

PAGE_PATHS = {
    "explore": "pages/explore",
    "for_you": "pages/for_you",
    "hires": "pages/hires",
    "genres": "pages/genre_page",
    "local_genres": "pages/genre_page_local",
    "moods": "pages/moods",
    "mixes": "pages/my_collection_my_mixes",
}

IMAGE_SIZES = {
    "album": [80, 160, 320, 640, 1280],
    "artist": [160, 320, 480, 750],
    "playlist": [160, 320, 480, 640, 750, 1080],
    "mix": [320, 640, 1500],
    "user": [100, 210, 600],
}
PLAYLIST_WIDE_SIZES = [(480, 320), (1080, 720)]


def _date_str(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d") if value else None


def _primary_artist(item) -> str:
    return item.artist.name if getattr(item, "artist", None) else "Unknown Artist"


def _creator_id(playlist) -> Optional[str]:
    # Editorial playlists carry a placeholder creator with id 0.
    creator_id = getattr(getattr(playlist, "creator", None), "id", None)
    return str(creator_id) if creator_id else None


def _track_model(t) -> Track:
    return Track(
        id=str(t.id),
        title=t.name,
        artist=_primary_artist(t),
        album=t.album.name if t.album else "Unknown Album",
        duration_seconds=t.duration or 0,
        url=f"https://tidal.com/browse/track/{t.id}",
    )


def _album_model(a) -> Album:
    return Album(
        id=str(a.id),
        title=a.name,
        artist=_primary_artist(a),
        release_date=_date_str(getattr(a, "release_date", None)),
        num_tracks=getattr(a, "num_tracks", 0) or 0,
        duration_seconds=getattr(a, "duration", 0) or 0,
        url=f"https://tidal.com/browse/album/{a.id}",
    )


def _playlist_model(p) -> Playlist:
    return Playlist(
        id=str(p.id),
        name=p.name,
        description=getattr(p, "description", "") or "",
        track_count=getattr(p, "num_tracks", 0) or 0,
        creator=getattr(getattr(p, "creator", None), "name", None),
        creator_id=_creator_id(p),
        url=f"https://tidal.com/browse/playlist/{p.id}",
    )


def _song_key(t) -> Tuple[str, str]:
    """Identity of a song across releases: TIDAL gives each release its own track ID."""
    return (t.name or "").strip().casefold(), _primary_artist(t).strip().casefold()


def _audio_quality(item) -> AudioQuality:
    tags = [str(tag) for tag in (getattr(item, "media_metadata_tags", None) or [])]
    modes = [str(mode) for mode in (getattr(item, "audio_modes", None) or [])]
    base = str(getattr(item, "audio_quality", "") or "") or None

    hi_res = "HIRES_LOSSLESS" in tags or base in ("HI_RES", "HI_RES_LOSSLESS")
    lossless = hi_res or "LOSSLESS" in tags or base == "LOSSLESS"
    dolby_atmos = "DOLBY_ATMOS" in tags or "DOLBY_ATMOS" in modes

    if hi_res:
        max_quality, summary = "HI_RES_LOSSLESS", "Hi-Res FLAC (24-bit, up to 192 kHz)"
    elif lossless:
        max_quality, summary = "LOSSLESS", "CD-quality FLAC (16-bit, 44.1 kHz)"
    else:
        max_quality, summary = base, "Lossy AAC (up to 320 kbps)"
    if dolby_atmos:
        summary += ", Dolby Atmos available"

    return AudioQuality(
        max_quality=max_quality,
        media_tags=tags,
        audio_modes=modes,
        lossless=lossless,
        hi_res=hi_res,
        dolby_atmos=dolby_atmos,
        summary=summary,
    )


def _normalize_isrc(isrc: str) -> str:
    code = isrc.strip().upper().replace("-", "")
    if not ISRC_PATTERN.match(code):
        raise ToolError(f"Invalid ISRC format: '{isrc}' (expected e.g. USQX91300108)")
    return code


def _lookup_isrc(code: str) -> list:
    """All TIDAL tracks for an ISRC, best candidate first (streamable, then most popular)."""
    # The v1 endpoint returns every release in one call; tidalapi's openapi lookup
    # needs one extra request per match and fails intermittently.
    tracks = session.request.map_request(
        "tracks", params={"isrc": code}, parse=session.parse_track
    )
    return sorted(tracks, key=lambda t: (not t.available, -(t.popularity or 0), t.id))


def _require_user_playlist(playlist, playlist_id: str):
    if not playlist:
        raise ToolError(f"Playlist with ID '{playlist_id}' not found")
    if not isinstance(playlist, tidalapi.UserPlaylist):
        raise ToolError(f"Playlist '{playlist.name}' is not one of your playlists and cannot be edited")
    return playlist


def _fetch_playlist_items(playlist) -> Tuple[list, bool]:
    """Every item (tracks and videos, in playlist order) up to MAX_PLAYLIST_ITEMS."""
    total = (getattr(playlist, "num_tracks", 0) or 0) + (getattr(playlist, "num_videos", 0) or 0)
    wanted = min(total, MAX_PLAYLIST_ITEMS)
    items: list = []
    while len(items) < wanted:
        batch = playlist.items(limit=100, offset=len(items))
        if not batch:
            break
        items.extend(batch)
    return items[:MAX_PLAYLIST_ITEMS], total > MAX_PLAYLIST_ITEMS


def _validate_user_id(user_id: str) -> str:
    user_id = user_id.strip()
    if not user_id.isdigit():
        raise ToolError(f"Invalid user ID: '{user_id}' (expected digits only)")
    return user_id


def _fetch_profile(user_id: str) -> dict:
    return session.request.request(
        "GET", f"profiles/{user_id}", base_url=session.config.api_v2_location
    ).json()


def _picture_url(picture_id: str, size: int) -> str:
    return session.config.image_url % (picture_id.replace("-", "/"), size, size)


def _normalize_page(page: str) -> str:
    key = page.strip()
    if key.lower() == "home":
        return "home"
    path = PAGE_PATHS.get(key.lower(), key).lstrip("/")
    # Home advertises its "view all" links under home/pages/..., which the API only serves at pages/...
    if path.startswith("home/pages/"):
        path = path[len("home/"):]
    if not path.startswith("pages/") or ".." in path:
        shortcuts = ", ".join(["home", *PAGE_PATHS])
        raise ToolError(
            f"Unknown page '{page}'. Use one of: {shortcuts}, or a path starting with "
            f"'pages/' returned by browse_page"
        )
    return path


def _load_page_sections(path: str) -> Tuple[str, list]:
    """Load an editorial page and parse its sections, skipping section types tidalapi cannot parse."""
    if path == "home":
        json_obj = session.request.request(
            "GET",
            "home/feed/static",
            base_url=session.config.api_v2_location,
            params={"deviceType": "BROWSER", "locale": session.locale, "platform": "WEB"},
        ).json()
    else:
        json_obj = session.request.request("GET", path, params={"deviceType": "BROWSER"}).json()

    if "rows" in json_obj:
        parse = tidalapi.page.PageCategory(session).parse
        modules = [row["modules"][0] for row in json_obj.get("rows") or [] if row.get("modules")]
    else:
        parse = tidalapi.page.PageCategoryV2(session).parse_item
        modules = json_obj.get("items") or []

    sections = []
    for module in modules:
        try:
            sections.append(parse(module))
        except (NotImplementedError, KeyError, TypeError) as e:
            get_logger().info(f"Skipping unsupported section on {path}: {e}")

    title = json_obj.get("title") or ("Home" if path == "home" else path)
    return title, sections


def _section_items(section) -> list:
    items = getattr(section, "items", None)
    # Header sections (e.g. a mix header) are the item themselves.
    return items if isinstance(items, list) else [section]


def _section_more_path(section) -> Optional[str]:
    api_path = getattr(getattr(section, "_more", None), "api_path", None)
    if api_path and api_path.startswith("home/pages/"):
        api_path = api_path[len("home/"):]
    return api_path


def _page_entry(item) -> Optional[PageEntry]:
    if item is None or isinstance(item, tidalapi.Video):
        return None
    if isinstance(item, tidalapi.Track):
        return PageEntry(
            type="track", id=str(item.id), title=item.name, subtitle=_primary_artist(item),
            url=f"https://tidal.com/browse/track/{item.id}",
        )
    if isinstance(item, tidalapi.Album):
        return PageEntry(
            type="album", id=str(item.id), title=item.name, subtitle=_primary_artist(item),
            url=f"https://tidal.com/browse/album/{item.id}",
        )
    if isinstance(item, tidalapi.Artist):
        return PageEntry(
            type="artist", id=str(item.id), title=item.name,
            url=f"https://tidal.com/browse/artist/{item.id}",
        )
    if isinstance(item, tidalapi.Playlist):
        return PageEntry(
            type="playlist", id=str(item.id), title=item.name,
            subtitle=getattr(getattr(item, "creator", None), "name", None),
            url=f"https://tidal.com/browse/playlist/{item.id}",
        )
    if isinstance(item, (tidalapi.Mix, tidalapi.MixV2)):
        return PageEntry(
            type="mix", id=str(item.id), title=item.title or "", subtitle=item.sub_title or None
        )
    if isinstance(item, tidalapi.page.PageLink):
        return PageEntry(type="link", title=item.title, path=item.api_path)
    if isinstance(item, tidalapi.page.PageItem):
        kind = (item.type or "").upper()
        # header is the banner label ("TIDAL EXCLUSIVE"...), the short headers name the item.
        title = " - ".join(x for x in (item.short_header, item.short_sub_header) if x) or item.header or ""
        subtitle = item.header or None
        if kind in ("ALBUM", "TRACK", "ARTIST", "PLAYLIST"):
            return PageEntry(
                type=kind.lower(), id=str(item.artifact_id), title=title, subtitle=subtitle,
                url=f"https://tidal.com/browse/{kind.lower()}/{item.artifact_id}",
            )
        if kind == "CATEGORY_PAGES":
            return PageEntry(type="link", title=title, subtitle=subtitle, path=str(item.artifact_id))
        if kind == "EXTURL":
            return PageEntry(type="external", title=title, subtitle=subtitle, url=str(item.artifact_id))
        return None
    if isinstance(item, str):
        return PageEntry(type="text", title=item)
    if isinstance(item, dict):
        title = item.get("title") or item.get("name") or ""
        url = item.get("url") or item.get("link")
        return PageEntry(type="external", title=str(title), url=url) if title or url else None
    return None


def _page_entries(section) -> List[PageEntry]:
    return [entry for entry in map(_page_entry, _section_items(section)) if entry]


# =============================================================================
# Tool 1: Authentication
# =============================================================================

@mcp.tool(
    annotations={
        "title": "Authenticate with TIDAL",
        "readOnlyHint": False,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
async def login() -> AuthResult:
    """
    Authenticate with TIDAL using OAuth browser flow.
    Opens browser automatically for secure login.
    Session is persisted for future use.
    """
    if await ensure_authenticated():
        return AuthResult(
            status="success",
            message="Already authenticated with TIDAL",
            authenticated=True,
        )

    try:
        # Start OAuth device code flow
        login_obj, future = await anyio.to_thread.run_sync(session.login_oauth)

        auth_url = login_obj.verification_uri_complete
        if not auth_url.startswith("http"):
            auth_url = "https://" + auth_url

        # Try to open browser automatically
        try:
            await anyio.to_thread.run_sync(webbrowser.open, auth_url)
        except Exception:
            pass

        # Wait for user to complete authentication (polls TIDAL's server)
        # This blocks until auth completes or the link expires (~5 minutes)
        await anyio.to_thread.run_sync(future.result)

        # Check if login succeeded
        if await anyio.to_thread.run_sync(session.check_login):
            # Save session for future use
            session_data = {
                "token_type": {"data": session.token_type or "Bearer"},
                "session_id": {"data": session.session_id or ""},
                "access_token": {"data": session.access_token},
                "refresh_token": {"data": session.refresh_token},
                "is_pkce": {"data": session.is_pkce},
            }
            async with await anyio.open_file(SESSION_FILE, "w") as f:
                await f.write(json.dumps(session_data))

            return AuthResult(
                status="success",
                message="Successfully authenticated with TIDAL",
                authenticated=True,
            )
        else:
            raise ToolError("Authentication failed - please try again")
    except ToolError:
        raise
    except Exception as e:
        error_msg = str(e)
        if "too long" in error_msg.lower() or "timeout" in error_msg.lower():
            raise ToolError(
                f"Authentication timed out. Please authenticate using the helper script:\n\n"
                f"  cd /home/ubuntu/code/personal/tidal/tidal-mcp && uv run python authenticate.py\n\n"
                f"After authenticating, all MCP tools will work automatically."
            )
        raise ToolError(f"Authentication error: {error_msg}")


# =============================================================================
# Tools 2-5: Search
# =============================================================================

@mcp.tool()
async def search_tracks(query: str, limit: int = 10) -> TrackList:
    """
    Search for tracks on TIDAL.

    Args:
        query: Search query - artist name, song title, or combination
        limit: Maximum results (1-50, default: 10)

    Returns:
        List of matching tracks with id, title, artist, album, duration, and URL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)
        results = await anyio.to_thread.run_sync(
            lambda: session.search(query, models=[tidalapi.Track], limit=limit)
        )

        tracks = []
        for track in results.get("tracks", []):
            tracks.append(
                Track(
                    id=str(track.id),
                    title=track.name,
                    artist=track.artist.name if track.artist else "Unknown Artist",
                    album=track.album.name if track.album else "Unknown Album",
                    duration_seconds=track.duration,
                    url=f"https://tidal.com/browse/track/{track.id}",
                )
            )

        return TrackList(status="success", query=query, count=len(tracks), tracks=tracks)
    except Exception as e:
        raise ToolError(f"Track search failed: {str(e)}")


@mcp.tool()
async def search_albums(query: str, limit: int = 10) -> AlbumList:
    """
    Search for albums on TIDAL.

    Args:
        query: Search query - album name, artist name, or combination
        limit: Maximum results (1-50, default: 10)

    Returns:
        List of matching albums with id, title, artist, release date, track count, and URL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)
        results = await anyio.to_thread.run_sync(
            lambda: session.search(query, models=[tidalapi.Album], limit=limit)
        )

        albums = []
        for album in results.get("albums", []):
            release_date = None
            if hasattr(album, "release_date") and album.release_date:
                release_date = str(album.release_date)

            albums.append(
                Album(
                    id=str(album.id),
                    title=album.name,
                    artist=album.artist.name if album.artist else "Unknown Artist",
                    release_date=release_date,
                    num_tracks=getattr(album, "num_tracks", 0),
                    duration_seconds=getattr(album, "duration", 0),
                    url=f"https://tidal.com/browse/album/{album.id}",
                )
            )

        return AlbumList(status="success", query=query, count=len(albums), albums=albums)
    except Exception as e:
        raise ToolError(f"Album search failed: {str(e)}")


@mcp.tool()
async def search_artists(query: str, limit: int = 10) -> ArtistList:
    """
    Search for artists on TIDAL.

    Args:
        query: Search query - artist name
        limit: Maximum results (1-50, default: 10)

    Returns:
        List of matching artists with id, name, and URL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)
        results = await anyio.to_thread.run_sync(
            lambda: session.search(query, models=[tidalapi.Artist], limit=limit)
        )

        artists = []
        for artist in results.get("artists", []):
            artists.append(
                Artist(
                    id=str(artist.id),
                    name=artist.name,
                    url=f"https://tidal.com/browse/artist/{artist.id}",
                )
            )

        return ArtistList(status="success", query=query, count=len(artists), artists=artists)
    except Exception as e:
        raise ToolError(f"Artist search failed: {str(e)}")


@mcp.tool()
async def search_playlists(query: str, limit: int = 10) -> PlaylistList:
    """
    Search for public playlists on TIDAL.

    Args:
        query: Search query - playlist name or theme
        limit: Maximum results (1-50, default: 10)

    Returns:
        List of matching playlists with id, name, description, track count, and URL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)
        results = await anyio.to_thread.run_sync(
            lambda: session.search(query, models=[tidalapi.Playlist], limit=limit)
        )

        playlists = []
        for playlist in results.get("playlists", []):
            creator_name = None
            if hasattr(playlist, "creator") and playlist.creator:
                creator_name = getattr(playlist.creator, "name", None)

            playlists.append(
                Playlist(
                    id=str(playlist.id),
                    name=playlist.name,
                    description=getattr(playlist, "description", "") or "",
                    track_count=getattr(playlist, "num_tracks", 0),
                    creator=creator_name,
                    creator_id=_creator_id(playlist),
                    url=f"https://tidal.com/browse/playlist/{playlist.id}",
                )
            )

        return PlaylistList(status="success", query=query, count=len(playlists), playlists=playlists)
    except Exception as e:
        raise ToolError(f"Playlist search failed: {str(e)}")


# =============================================================================
# Tools 6-7: Favorites
# =============================================================================

@mcp.tool()
async def get_favorite_tracks(limit: int = 50) -> TrackList:
    """
    Get user's favorite (liked) tracks from TIDAL.

    Args:
        limit: Maximum tracks to retrieve (default: 50)

    Returns:
        List of favorite tracks
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        favorites = await anyio.to_thread.run_sync(
            lambda: session.user.favorites.tracks(limit=limit)
        )

        tracks = []
        for track in favorites:
            tracks.append(
                Track(
                    id=str(track.id),
                    title=track.name,
                    artist=track.artist.name if track.artist else "Unknown Artist",
                    album=track.album.name if track.album else "Unknown Album",
                    duration_seconds=track.duration,
                    url=f"https://tidal.com/browse/track/{track.id}",
                )
            )

        return TrackList(status="success", count=len(tracks), tracks=tracks)
    except Exception as e:
        raise ToolError(f"Failed to get favorites: {str(e)}")


@mcp.tool()
async def add_track_to_favorites(track_id: str) -> AddToFavoritesResult:
    """
    Add a track to user's favorites (like a track).

    Args:
        track_id: ID of the track to add to favorites

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        track_id_int = int(track_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.add_track, track_id_int
        )

        return AddToFavoritesResult(
            status="success",
            item_id=track_id,
            item_type="track",
            message=f"Track {track_id} added to favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid track ID format: {track_id}")
    except Exception as e:
        raise ToolError(f"Failed to add track to favorites: {str(e)}")


# =============================================================================
# Tools 8-14: Playlist Management
# =============================================================================

@mcp.tool()
async def get_user_playlists(limit: int = 50) -> PlaylistList:
    """
    Get list of user's own playlists from TIDAL.

    Args:
        limit: Maximum playlists to return (default: 50)

    Returns:
        List of user's playlists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        all_playlists = await anyio.to_thread.run_sync(session.user.playlists)
        limited_playlists = all_playlists[:limit] if limit else all_playlists

        playlists = []
        for playlist in limited_playlists:
            playlists.append(
                Playlist(
                    id=str(playlist.id),
                    name=playlist.name,
                    description=getattr(playlist, "description", "") or "",
                    track_count=getattr(playlist, "num_tracks", 0),
                    creator=None,  # User's own playlists
                    url=f"https://tidal.com/browse/playlist/{playlist.id}",
                )
            )

        return PlaylistList(status="success", count=len(playlists), playlists=playlists)
    except Exception as e:
        raise ToolError(f"Failed to get playlists: {str(e)}")


@mcp.tool()
async def get_playlist_tracks(playlist_id: str, limit: int = 100) -> PlaylistTracks:
    """
    Get tracks from a specific playlist.

    Args:
        playlist_id: ID of the playlist
        limit: Maximum tracks to return (default: 100)

    Returns:
        List of tracks in the playlist
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        all_tracks = await anyio.to_thread.run_sync(playlist.tracks)
        limited_tracks = all_tracks[:limit] if limit else all_tracks

        tracks = []
        for track in limited_tracks:
            tracks.append(
                Track(
                    id=str(track.id),
                    title=track.name,
                    artist=track.artist.name if track.artist else "Unknown Artist",
                    album=track.album.name if track.album else "Unknown Album",
                    duration_seconds=track.duration,
                    url=f"https://tidal.com/browse/track/{track.id}",
                )
            )

        return PlaylistTracks(
            status="success",
            playlist_name=playlist.name,
            playlist_id=playlist_id,
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get playlist tracks: {str(e)}")


@mcp.tool()
async def create_playlist(name: str, description: str = "") -> CreatePlaylistResult:
    """
    Create a new playlist in user's TIDAL account.

    Args:
        name: Name for the playlist
        description: Optional description

    Returns:
        Created playlist details including ID and URL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(
            session.user.create_playlist, name, description
        )

        return CreatePlaylistResult(
            status="success",
            playlist=Playlist(
                id=str(playlist.id),
                name=playlist.name,
                description=playlist.description or "",
                track_count=0,
                creator=None,
                url=f"https://tidal.com/browse/playlist/{playlist.id}",
            ),
            message=f"Created playlist '{name}'",
        )
    except Exception as e:
        raise ToolError(f"Failed to create playlist: {str(e)}")


@mcp.tool()
async def add_tracks_to_playlist(playlist_id: str, track_ids: List[str]) -> AddTracksResult:
    """
    Add tracks to an existing playlist.

    Args:
        playlist_id: ID of the playlist
        track_ids: List of track IDs to add

    Returns:
        Success status and number of tracks added
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        track_ids_int = [int(tid) for tid in track_ids]
        added = await anyio.to_thread.run_sync(playlist.add, track_ids_int)
        skipped = len(track_ids) - len(added)

        return AddTracksResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            tracks_added=len(added),
            playlist_url=f"https://tidal.com/browse/playlist/{playlist_id}",
            message=f"Added {len(added)} tracks to playlist '{playlist.name}'"
            + (f" ({skipped} already present, skipped)" if skipped else ""),
        )
    except ValueError as e:
        raise ToolError(f"Invalid track ID format: {str(e)}")
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to add tracks: {str(e)}")


@mcp.tool()
async def remove_tracks_from_playlist(
    playlist_id: str, track_ids: Optional[List[str]] = None, indices: Optional[List[int]] = None
) -> RemoveTracksResult:
    """
    Remove tracks from a playlist by track ID or position index.

    Args:
        playlist_id: ID of the playlist
        track_ids: List of track IDs to remove (optional)
        indices: List of position indices to remove, 0-based (optional)
        Note: Provide either track_ids OR indices, not both

    Returns:
        Success status and number of tracks removed
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    if not track_ids and not indices:
        raise ToolError("Must provide either track_ids or indices to remove")

    if track_ids and indices:
        raise ToolError("Provide either track_ids or indices, not both")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        if indices:
            # Remove by index position
            await anyio.to_thread.run_sync(playlist.remove_by_indices, indices)
            removed_count = len(indices)
        else:
            # Remove by track ID
            track_ids_int = [int(tid) for tid in track_ids]
            await anyio.to_thread.run_sync(playlist.remove_by_id, track_ids_int)
            removed_count = len(track_ids)

        return RemoveTracksResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            tracks_removed=removed_count,
            message=f"Removed {removed_count} tracks from playlist '{playlist.name}'",
        )
    except ValueError as e:
        raise ToolError(f"Invalid ID format: {str(e)}")
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to remove tracks: {str(e)}")


@mcp.tool()
async def update_playlist(
    playlist_id: str, name: Optional[str] = None, description: Optional[str] = None
) -> UpdatePlaylistResult:
    """
    Update a playlist's name and/or description.

    Args:
        playlist_id: ID of the playlist to update
        name: New name for the playlist (optional)
        description: New description (optional)

    Returns:
        Updated playlist details
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    if not name and description is None:
        raise ToolError("Must provide at least name or description to update")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        # Update the playlist
        if name:
            await anyio.to_thread.run_sync(playlist.edit, name, description)
        elif description is not None:
            await anyio.to_thread.run_sync(playlist.edit, playlist.name, description)

        # Fetch updated playlist
        updated_playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)

        return UpdatePlaylistResult(
            status="success",
            playlist=Playlist(
                id=str(updated_playlist.id),
                name=updated_playlist.name,
                description=updated_playlist.description or "",
                track_count=getattr(updated_playlist, "num_tracks", 0),
                creator=None,
                url=f"https://tidal.com/browse/playlist/{playlist_id}",
            ),
            message=f"Updated playlist '{updated_playlist.name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to update playlist: {str(e)}")


@mcp.tool()
async def delete_playlist(playlist_id: str) -> DeletePlaylistResult:
    """
    Delete a playlist from user's account.

    Args:
        playlist_id: ID of the playlist to delete

    Returns:
        Confirmation of deletion
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        playlist_name = playlist.name
        await anyio.to_thread.run_sync(playlist.delete)

        return DeletePlaylistResult(
            status="success",
            playlist_id=playlist_id,
            message=f"Deleted playlist '{playlist_name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to delete playlist: {str(e)}")


# =============================================================================
# Tool 15: Content Browsing
# =============================================================================

@mcp.tool()
async def get_album_tracks(album_id: str) -> AlbumTracks:
    """
    Get all tracks from a specific album.

    Args:
        album_id: ID of the album

    Returns:
        List of tracks in the album with album metadata
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        album = await anyio.to_thread.run_sync(session.album, album_id)
        if not album:
            raise ToolError(f"Album with ID '{album_id}' not found")

        album_tracks = await anyio.to_thread.run_sync(album.tracks)

        tracks = []
        for track in album_tracks:
            tracks.append(
                Track(
                    id=str(track.id),
                    title=track.name,
                    artist=track.artist.name if track.artist else "Unknown Artist",
                    album=album.name,
                    duration_seconds=track.duration,
                    url=f"https://tidal.com/browse/track/{track.id}",
                )
            )

        return AlbumTracks(
            status="success",
            album_title=album.name,
            album_id=album_id,
            artist=album.artist.name if album.artist else "Unknown Artist",
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get album tracks: {str(e)}")


# =============================================================================
# Tools 16-17: Recommendations
# =============================================================================

@mcp.tool()
async def get_track_radio(track_id: str, limit: int = 20) -> RadioTracks:
    """
    Get tracks similar to a seed track (track radio).

    This returns TIDAL's native recommendations based on the specified track,
    useful for music discovery and creating "similar music" playlists.

    Args:
        track_id: ID of the seed track
        limit: Maximum tracks to return (default: 20, max: 100)

    Returns:
        List of similar tracks with seed track info
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 100)

        # Get the seed track first
        track = await anyio.to_thread.run_sync(session.track, track_id)
        if not track:
            raise ToolError(f"Track with ID '{track_id}' not found")

        seed_name = f"{track.name} by {track.artist.name if track.artist else 'Unknown Artist'}"

        # Get radio tracks
        radio_tracks = await anyio.to_thread.run_sync(
            lambda: track.get_track_radio(limit=limit)
        )

        tracks = []
        for t in radio_tracks:
            tracks.append(
                Track(
                    id=str(t.id),
                    title=t.name,
                    artist=t.artist.name if t.artist else "Unknown Artist",
                    album=t.album.name if t.album else "Unknown Album",
                    duration_seconds=t.duration,
                    url=f"https://tidal.com/browse/track/{t.id}",
                )
            )

        return RadioTracks(
            status="success",
            seed_id=track_id,
            seed_type="track",
            seed_name=seed_name,
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get track radio: {str(e)}")


@mcp.tool()
async def get_artist_radio(artist_id: str, limit: int = 20) -> RadioTracks:
    """
    Get tracks similar to an artist's style (artist radio).

    This returns TIDAL's native recommendations based on the specified artist,
    useful for discovering music in a similar style.

    Args:
        artist_id: ID of the seed artist
        limit: Maximum tracks to return (default: 20, max: 100)

    Returns:
        List of similar tracks with seed artist info
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 100)

        # Get the seed artist first
        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        # Get radio tracks
        radio_tracks = await anyio.to_thread.run_sync(
            lambda: artist.get_radio(limit=limit)
        )

        tracks = []
        for t in radio_tracks:
            tracks.append(
                Track(
                    id=str(t.id),
                    title=t.name,
                    artist=t.artist.name if t.artist else "Unknown Artist",
                    album=t.album.name if t.album else "Unknown Album",
                    duration_seconds=t.duration,
                    url=f"https://tidal.com/browse/track/{t.id}",
                )
            )

        return RadioTracks(
            status="success",
            seed_id=artist_id,
            seed_type="artist",
            seed_name=artist.name,
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get artist radio: {str(e)}")


# =============================================================================
# Tools 18-21: Artist Discovery
# =============================================================================

@mcp.tool()
async def get_artist(artist_id: str) -> ArtistDetails:
    """
    Get detailed information about an artist including biography.

    Args:
        artist_id: ID of the artist

    Returns:
        Artist details including name, URL, and biography
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        # Try to get biography
        bio = None
        try:
            bio = await anyio.to_thread.run_sync(artist.get_bio)
        except Exception:
            pass  # Bio may not be available for all artists

        return ArtistDetails(
            status="success",
            artist=Artist(
                id=str(artist.id),
                name=artist.name,
                url=f"https://tidal.com/browse/artist/{artist.id}",
            ),
            bio=bio,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get artist: {str(e)}")


@mcp.tool()
async def get_artist_albums(artist_id: str, limit: int = 20) -> AlbumList:
    """
    Get albums by an artist (discography).

    Args:
        artist_id: ID of the artist
        limit: Maximum albums to return (default: 20, max: 50)

    Returns:
        List of albums by the artist
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)

        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        artist_albums = await anyio.to_thread.run_sync(
            lambda: artist.get_albums(limit=limit)
        )

        albums = []
        for album in artist_albums:
            release_date = None
            if hasattr(album, "release_date") and album.release_date:
                release_date = str(album.release_date)

            albums.append(
                Album(
                    id=str(album.id),
                    title=album.name,
                    artist=album.artist.name if album.artist else artist.name,
                    release_date=release_date,
                    num_tracks=getattr(album, "num_tracks", 0),
                    duration_seconds=getattr(album, "duration", 0),
                    url=f"https://tidal.com/browse/album/{album.id}",
                )
            )

        return AlbumList(
            status="success",
            count=len(albums),
            albums=albums,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get artist albums: {str(e)}")


@mcp.tool()
async def get_artist_top_tracks(artist_id: str, limit: int = 10) -> TrackList:
    """
    Get an artist's most popular tracks.

    Args:
        artist_id: ID of the artist
        limit: Maximum tracks to return (default: 10, max: 50)

    Returns:
        List of the artist's top tracks
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)

        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        top_tracks = await anyio.to_thread.run_sync(
            lambda: artist.get_top_tracks(limit=limit)
        )

        tracks = []
        for track in top_tracks:
            tracks.append(
                Track(
                    id=str(track.id),
                    title=track.name,
                    artist=track.artist.name if track.artist else artist.name,
                    album=track.album.name if track.album else "Unknown Album",
                    duration_seconds=track.duration,
                    url=f"https://tidal.com/browse/track/{track.id}",
                )
            )

        return TrackList(
            status="success",
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get artist top tracks: {str(e)}")


@mcp.tool()
async def get_similar_artists(artist_id: str, limit: int = 10) -> ArtistList:
    """
    Get artists similar to the specified artist.

    Args:
        artist_id: ID of the seed artist
        limit: Maximum artists to return (default: 10, max: 50)

    Returns:
        List of similar artists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)

        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        similar = await anyio.to_thread.run_sync(artist.get_similar)
        limited_similar = similar[:limit] if similar else []

        artists = []
        for a in limited_similar:
            artists.append(
                Artist(
                    id=str(a.id),
                    name=a.name,
                    url=f"https://tidal.com/browse/artist/{a.id}",
                )
            )

        return ArtistList(
            status="success",
            count=len(artists),
            artists=artists,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get similar artists: {str(e)}")


# =============================================================================
# Tools 22-25: Extended Favorites
# =============================================================================

@mcp.tool()
async def add_album_to_favorites(album_id: str) -> AddToFavoritesResult:
    """
    Add an album to user's favorites (save an album).

    Args:
        album_id: ID of the album to add to favorites

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        album_id_int = int(album_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.add_album, album_id_int
        )

        return AddToFavoritesResult(
            status="success",
            item_id=album_id,
            item_type="album",
            message=f"Album {album_id} added to favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid album ID format: {album_id}")
    except Exception as e:
        raise ToolError(f"Failed to add album to favorites: {str(e)}")


@mcp.tool()
async def add_artist_to_favorites(artist_id: str) -> AddToFavoritesResult:
    """
    Follow an artist (add to favorite artists).

    Args:
        artist_id: ID of the artist to follow

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        artist_id_int = int(artist_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.add_artist, artist_id_int
        )

        return AddToFavoritesResult(
            status="success",
            item_id=artist_id,
            item_type="artist",
            message=f"Artist {artist_id} added to favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid artist ID format: {artist_id}")
    except Exception as e:
        raise ToolError(f"Failed to add artist to favorites: {str(e)}")


@mcp.tool()
async def remove_artist_from_favorites(artist_id: str) -> RemoveFromFavoritesResult:
    """
    Unfollow an artist (remove from favorite artists).

    Args:
        artist_id: ID of the artist to unfollow

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        artist_id_int = int(artist_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.remove_artist, artist_id_int
        )

        return RemoveFromFavoritesResult(
            status="success",
            item_id=artist_id,
            item_type="artist",
            message=f"Artist {artist_id} removed from favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid artist ID format: {artist_id}")
    except Exception as e:
        raise ToolError(f"Failed to remove artist from favorites: {str(e)}")


@mcp.tool()
async def get_favorite_albums(limit: int = 50) -> AlbumList:
    """
    Get user's favorite (saved) albums from TIDAL.

    Args:
        limit: Maximum albums to retrieve (default: 50)

    Returns:
        List of favorite albums
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        favorites = await anyio.to_thread.run_sync(
            lambda: session.user.favorites.albums(limit=limit)
        )

        albums = []
        for album in favorites:
            release_date = None
            if hasattr(album, "release_date") and album.release_date:
                release_date = str(album.release_date)

            albums.append(
                Album(
                    id=str(album.id),
                    title=album.name,
                    artist=album.artist.name if album.artist else "Unknown Artist",
                    release_date=release_date,
                    num_tracks=getattr(album, "num_tracks", 0),
                    duration_seconds=getattr(album, "duration", 0),
                    url=f"https://tidal.com/browse/album/{album.id}",
                )
            )

        return AlbumList(status="success", count=len(albums), albums=albums)
    except Exception as e:
        raise ToolError(f"Failed to get favorite albums: {str(e)}")


@mcp.tool()
async def get_favorite_artists(limit: int = 50) -> ArtistList:
    """
    Get user's favorite (followed) artists from TIDAL.

    Args:
        limit: Maximum artists to retrieve (default: 50)

    Returns:
        List of followed artists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        favorites = await anyio.to_thread.run_sync(
            lambda: session.user.favorites.artists(limit=limit)
        )

        artists = []
        for artist in favorites:
            artists.append(
                Artist(
                    id=str(artist.id),
                    name=artist.name,
                    url=f"https://tidal.com/browse/artist/{artist.id}",
                )
            )

        return ArtistList(status="success", count=len(artists), artists=artists)
    except Exception as e:
        raise ToolError(f"Failed to get favorite artists: {str(e)}")


@mcp.tool()
async def remove_track_from_favorites(track_id: str) -> RemoveFromFavoritesResult:
    """
    Remove a track from user's favorites (unlike a track).

    Args:
        track_id: ID of the track to remove from favorites

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        track_id_int = int(track_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.remove_track, track_id_int
        )

        return RemoveFromFavoritesResult(
            status="success",
            item_id=track_id,
            item_type="track",
            message=f"Track {track_id} removed from favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid track ID format: {track_id}")
    except Exception as e:
        raise ToolError(f"Failed to remove track from favorites: {str(e)}")


@mcp.tool()
async def remove_album_from_favorites(album_id: str) -> RemoveFromFavoritesResult:
    """
    Remove an album from user's favorites.

    Args:
        album_id: ID of the album to remove from favorites

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        album_id_int = int(album_id)
        await anyio.to_thread.run_sync(
            session.user.favorites.remove_album, album_id_int
        )

        return RemoveFromFavoritesResult(
            status="success",
            item_id=album_id,
            item_type="album",
            message=f"Album {album_id} removed from favorites",
        )
    except ValueError:
        raise ToolError(f"Invalid album ID format: {album_id}")
    except Exception as e:
        raise ToolError(f"Failed to remove album from favorites: {str(e)}")


# =============================================================================
# Tools 26-27: Album Details
# =============================================================================

@mcp.tool()
async def get_album(album_id: str) -> AlbumDetails:
    """
    Get detailed information about an album.

    Args:
        album_id: ID of the album

    Returns:
        Album details including title, artist, release date, and track count
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        album = await anyio.to_thread.run_sync(session.album, album_id)
        if not album:
            raise ToolError(f"Album with ID '{album_id}' not found")

        release_date = None
        if hasattr(album, "release_date") and album.release_date:
            release_date = str(album.release_date)

        return AlbumDetails(
            status="success",
            album=Album(
                id=str(album.id),
                title=album.name,
                artist=album.artist.name if album.artist else "Unknown Artist",
                release_date=release_date,
                num_tracks=getattr(album, "num_tracks", 0),
                duration_seconds=getattr(album, "duration", 0),
                url=f"https://tidal.com/browse/album/{album.id}",
            ),
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get album: {str(e)}")


@mcp.tool()
async def get_similar_albums(album_id: str, limit: int = 10) -> AlbumList:
    """
    Get albums similar to the specified album.

    Args:
        album_id: ID of the seed album
        limit: Maximum albums to return (default: 10, max: 50)

    Returns:
        List of similar albums
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 50)

        album = await anyio.to_thread.run_sync(session.album, album_id)
        if not album:
            raise ToolError(f"Album with ID '{album_id}' not found")

        similar = await anyio.to_thread.run_sync(album.similar)
        limited_similar = similar[:limit] if similar else []

        albums = []
        for a in limited_similar:
            release_date = None
            if hasattr(a, "release_date") and a.release_date:
                release_date = str(a.release_date)

            albums.append(
                Album(
                    id=str(a.id),
                    title=a.name,
                    artist=a.artist.name if a.artist else "Unknown Artist",
                    release_date=release_date,
                    num_tracks=getattr(a, "num_tracks", 0),
                    duration_seconds=getattr(a, "duration", 0),
                    url=f"https://tidal.com/browse/album/{a.id}",
                )
            )

        return AlbumList(
            status="success",
            count=len(albums),
            albums=albums,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get similar albums: {str(e)}")


# =============================================================================
# Editorial / Discovery Tools
# =============================================================================

async def _get_genre_by_path(path_or_name: str):
    """Find a Genre object by path or name (case-insensitive)."""
    genres = await anyio.to_thread.run_sync(session.genre.get_genres)
    for g in genres:
        if g.path.lower() == path_or_name.lower():
            return g
    for g in genres:
        if g.name.lower() == path_or_name.lower():
            return g
    available = ", ".join(f"{g.name} ({g.path})" for g in genres)
    raise ToolError(f"Genre '{path_or_name}' not found. Available genres: {available}")


@mcp.tool()
async def get_genres() -> GenreList:
    """
    List all music genres available on TIDAL.

    Returns:
        List of genres with name, path identifier, and available content types.
        Use the 'path' field in get_genre_tracks/albums/playlists tools.
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        genres = await anyio.to_thread.run_sync(session.genre.get_genres)

        genre_list = [
            GenreInfo(
                name=g.name,
                path=g.path,
                has_tracks=bool(g.tracks),
                has_albums=bool(g.albums),
                has_playlists=bool(g.playlists),
                has_artists=bool(g.artists),
            )
            for g in genres
        ]

        return GenreList(status="success", count=len(genre_list), genres=genre_list)
    except Exception as e:
        raise ToolError(f"Failed to get genres: {str(e)}")


@mcp.tool()
async def get_genre_tracks(genre_path: str, limit: int = 20) -> TrackList:
    """
    Get tracks from a specific TIDAL genre.

    Args:
        genre_path: Genre path from get_genres (e.g. 'rock', 'pop', 'jazz')
        limit: Maximum tracks to return (default: 20)

    Returns:
        List of tracks in the genre
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        genre = await _get_genre_by_path(genre_path)
        if not genre.tracks:
            raise ToolError(f"Genre '{genre.name}' has no tracks available")

        raw = await anyio.to_thread.run_sync(
            lambda: genre.items(tidalapi.Track)
        )
        limited = raw[:limit] if raw else []

        tracks = [
            Track(
                id=str(t.id),
                title=t.name,
                artist=t.artist.name if t.artist else "Unknown Artist",
                album=t.album.name if t.album else "Unknown Album",
                duration_seconds=t.duration,
                url=f"https://tidal.com/browse/track/{t.id}",
            )
            for t in limited
        ]

        return TrackList(status="success", count=len(tracks), tracks=tracks)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get genre tracks: {str(e)}")


@mcp.tool()
async def get_genre_albums(genre_path: str, limit: int = 20) -> AlbumList:
    """
    Get albums from a specific TIDAL genre.

    Args:
        genre_path: Genre path from get_genres (e.g. 'rock', 'pop', 'jazz')
        limit: Maximum albums to return (default: 20)

    Returns:
        List of albums in the genre
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        genre = await _get_genre_by_path(genre_path)
        if not genre.albums:
            raise ToolError(f"Genre '{genre.name}' has no albums available")

        raw = await anyio.to_thread.run_sync(
            lambda: genre.items(tidalapi.Album)
        )
        limited = raw[:limit] if raw else []

        albums = []
        for a in limited:
            release_date = None
            if hasattr(a, "release_date") and a.release_date:
                release_date = str(a.release_date)
            albums.append(
                Album(
                    id=str(a.id),
                    title=a.name,
                    artist=a.artist.name if a.artist else "Unknown Artist",
                    release_date=release_date,
                    num_tracks=getattr(a, "num_tracks", 0),
                    duration_seconds=getattr(a, "duration", 0),
                    url=f"https://tidal.com/browse/album/{a.id}",
                )
            )

        return AlbumList(status="success", count=len(albums), albums=albums)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get genre albums: {str(e)}")


@mcp.tool()
async def get_genre_playlists(genre_path: str, limit: int = 20) -> PlaylistList:
    """
    Get editorial playlists from a specific TIDAL genre.

    Args:
        genre_path: Genre path from get_genres (e.g. 'rock', 'pop', 'jazz')
        limit: Maximum playlists to return (default: 20)

    Returns:
        List of curated playlists for the genre
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        genre = await _get_genre_by_path(genre_path)
        if not genre.playlists:
            raise ToolError(f"Genre '{genre.name}' has no playlists available")

        raw = await anyio.to_thread.run_sync(
            lambda: genre.items(tidalapi.Playlist)
        )
        limited = raw[:limit] if raw else []

        playlists = []
        for p in limited:
            creator_name = None
            if hasattr(p, "creator") and p.creator:
                creator_name = getattr(p.creator, "name", None)
            playlists.append(
                Playlist(
                    id=str(p.id),
                    name=p.name,
                    description=getattr(p, "description", "") or "",
                    track_count=getattr(p, "num_tracks", 0),
                    creator=creator_name,
                    creator_id=_creator_id(p),
                    url=f"https://tidal.com/browse/playlist/{p.id}",
                )
            )

        return PlaylistList(status="success", count=len(playlists), playlists=playlists)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get genre playlists: {str(e)}")


@mcp.tool()
async def get_mixes() -> MixList:
    """
    Get user's personalized mixes from TIDAL.

    These are algorithmically curated mixes like 'My Daily Discovery',
    'My New Arrivals', and genre-specific mixes tailored to the user.

    Returns:
        List of personalized mixes with id, title, and description.
        Use mix id with get_mix_tracks to get the tracks.
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        mixes_page = await anyio.to_thread.run_sync(session.mixes)

        mixes = []
        for item in mixes_page:
            if hasattr(item, "id") and hasattr(item, "title"):
                mixes.append(
                    MixInfo(
                        id=item.id,
                        title=item.title,
                        sub_title=getattr(item, "sub_title", "") or "",
                    )
                )

        return MixList(status="success", count=len(mixes), mixes=mixes)
    except Exception as e:
        raise ToolError(f"Failed to get mixes: {str(e)}")


@mcp.tool()
async def get_mix_tracks(mix_id: str, limit: int = 50) -> MixTracks:
    """
    Get tracks from a specific TIDAL personalized mix.

    Args:
        mix_id: ID of the mix (from get_mixes)
        limit: Maximum tracks to return (default: 50)

    Returns:
        List of tracks in the mix
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        mix = await anyio.to_thread.run_sync(session.mix, mix_id)
        items = await anyio.to_thread.run_sync(mix.items)
        limited = items[:limit] if items else []

        tracks = []
        for item in limited:
            if not hasattr(item, "duration"):
                continue  # skip videos
            tracks.append(
                Track(
                    id=str(item.id),
                    title=item.name,
                    artist=item.artist.name if item.artist else "Unknown Artist",
                    album=item.album.name if item.album else "Unknown Album",
                    duration_seconds=item.duration,
                    url=f"https://tidal.com/browse/track/{item.id}",
                )
            )

        return MixTracks(
            status="success",
            mix_id=mix_id,
            mix_title=mix.title,
            count=len(tracks),
            tracks=tracks,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get mix tracks: {str(e)}")


# =============================================================================
# Lyrics
# =============================================================================

@mcp.tool()
async def get_track_lyrics(track_id: str) -> TrackLyrics:
    """
    Get lyrics for a track.

    Args:
        track_id: ID of the track

    Returns:
        Plain text lyrics and optionally timestamped LRC subtitles.
        Raises an error if no lyrics are available for this track.
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        track = await anyio.to_thread.run_sync(session.track, track_id)
        if not track:
            raise ToolError(f"Track with ID '{track_id}' not found")

        lyrics = await anyio.to_thread.run_sync(track.lyrics)

        return TrackLyrics(
            status="success",
            track_id=track_id,
            text=lyrics.text,
            subtitles=lyrics.subtitles or None,
            right_to_left=bool(lyrics.right_to_left),
        )
    except ToolError:
        raise
    except Exception as e:
        msg = str(e)
        if "no lyrics" in msg.lower() or "metadata" in msg.lower():
            raise ToolError(f"No lyrics available for track {track_id}")
        raise ToolError(f"Failed to get lyrics: {msg}")


# =============================================================================
# Favorite Playlists
# =============================================================================

@mcp.tool()
async def get_favorite_playlists(limit: int = 50) -> PlaylistList:
    """
    Get user's favorite (saved) playlists from TIDAL.

    Args:
        limit: Maximum playlists to retrieve (default: 50, max enforced by TIDAL: 50)

    Returns:
        List of saved playlists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(limit, 50)
        favorites = await anyio.to_thread.run_sync(
            lambda: session.user.favorites.playlists(limit=limit)
        )

        playlists = []
        for p in favorites:
            creator_name = None
            if hasattr(p, "creator") and p.creator:
                creator_name = getattr(p.creator, "name", None)
            playlists.append(
                Playlist(
                    id=str(p.id),
                    name=p.name,
                    description=getattr(p, "description", "") or "",
                    track_count=getattr(p, "num_tracks", 0),
                    creator=creator_name,
                    creator_id=_creator_id(p),
                    url=f"https://tidal.com/browse/playlist/{p.id}",
                )
            )

        return PlaylistList(status="success", count=len(playlists), playlists=playlists)
    except Exception as e:
        raise ToolError(f"Failed to get favorite playlists: {str(e)}")


@mcp.tool()
async def add_playlist_to_favorites(playlist_id: str) -> AddToFavoritesResult:
    """
    Save a playlist to user's favorites.

    Args:
        playlist_id: UUID of the playlist to save

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        await anyio.to_thread.run_sync(
            session.user.favorites.add_playlist, playlist_id
        )

        return AddToFavoritesResult(
            status="success",
            item_id=playlist_id,
            item_type="playlist",
            message=f"Playlist {playlist_id} added to favorites",
        )
    except Exception as e:
        raise ToolError(f"Failed to add playlist to favorites: {str(e)}")


@mcp.tool()
async def remove_playlist_from_favorites(playlist_id: str) -> RemoveFromFavoritesResult:
    """
    Remove a playlist from user's favorites.

    Args:
        playlist_id: UUID of the playlist to remove

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        await anyio.to_thread.run_sync(
            session.user.favorites.remove_playlist, playlist_id
        )

        return RemoveFromFavoritesResult(
            status="success",
            item_id=playlist_id,
            item_type="playlist",
            message=f"Playlist {playlist_id} removed from favorites",
        )
    except Exception as e:
        raise ToolError(f"Failed to remove playlist from favorites: {str(e)}")


# =============================================================================
# Favorite Mixes
# =============================================================================

@mcp.tool()
async def get_favorite_mixes(limit: int = 50) -> MixList:
    """
    Get user's favorite mixes & radios from TIDAL.

    Args:
        limit: Maximum mixes to retrieve (default: 50)

    Returns:
        List of saved mixes
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        favorites = await anyio.to_thread.run_sync(
            lambda: session.user.favorites.mixes(limit=limit)
        )

        mixes = [
            MixInfo(
                id=m.id,
                title=m.title or "",
                sub_title=getattr(m, "sub_title", "") or "",
            )
            for m in favorites
            if m.id
        ]

        return MixList(status="success", count=len(mixes), mixes=mixes)
    except Exception as e:
        raise ToolError(f"Failed to get favorite mixes: {str(e)}")


@mcp.tool()
async def add_mix_to_favorites(mix_id: str) -> AddToFavoritesResult:
    """
    Save a mix to user's favorites.

    Args:
        mix_id: ID of the mix to save (from get_mixes or get_artist_radio)

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        await anyio.to_thread.run_sync(
            session.user.favorites.add_mixes, mix_id
        )

        return AddToFavoritesResult(
            status="success",
            item_id=mix_id,
            item_type="mix",
            message=f"Mix {mix_id} added to favorites",
        )
    except Exception as e:
        raise ToolError(f"Failed to add mix to favorites: {str(e)}")


@mcp.tool()
async def remove_mix_from_favorites(mix_id: str) -> RemoveFromFavoritesResult:
    """
    Remove a mix from user's favorites.

    Args:
        mix_id: ID of the mix to remove

    Returns:
        Success status and confirmation
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        await anyio.to_thread.run_sync(
            session.user.favorites.remove_mixes, mix_id
        )

        return RemoveFromFavoritesResult(
            status="success",
            item_id=mix_id,
            item_type="mix",
            message=f"Mix {mix_id} removed from favorites",
        )
    except Exception as e:
        raise ToolError(f"Failed to remove mix from favorites: {str(e)}")


# =============================================================================
# Folder Contents & Management (rename / delete)
# =============================================================================

@mcp.tool()
async def get_folder_contents(folder_id: str, limit: int = 50) -> PlaylistList:
    """
    Get the playlists inside a specific folder.

    Args:
        folder_id: ID of the folder (from get_folders)
        limit: Maximum playlists to return (default: 50)

    Returns:
        List of playlists in the folder
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        folder = await anyio.to_thread.run_sync(session.folder, folder_id)

        items = await anyio.to_thread.run_sync(
            lambda: folder.items(limit=limit)
        )

        playlists = []
        for p in items:
            creator_name = None
            if hasattr(p, "creator") and p.creator:
                creator_name = getattr(p.creator, "name", None)
            playlists.append(
                Playlist(
                    id=str(p.id),
                    name=p.name,
                    description=getattr(p, "description", "") or "",
                    track_count=getattr(p, "num_tracks", 0),
                    creator=creator_name,
                    url=f"https://tidal.com/browse/playlist/{p.id}",
                )
            )

        return PlaylistList(
            status="success",
            count=len(playlists),
            playlists=playlists,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get folder contents: {str(e)}")


@mcp.tool()
async def rename_folder(folder_id: str, name: str) -> RenameFolderResult:
    """
    Rename a playlist folder.

    Args:
        folder_id: ID of the folder to rename (from get_folders)
        name: New name for the folder

    Returns:
        Confirmation with new folder name
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        folder = await anyio.to_thread.run_sync(session.folder, folder_id)
        await anyio.to_thread.run_sync(folder.rename, name)

        return RenameFolderResult(
            status="success",
            folder_id=folder_id,
            new_name=name,
            message=f"Folder renamed to '{name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to rename folder: {str(e)}")


@mcp.tool()
async def delete_folder(folder_id: str) -> DeleteFolderResult:
    """
    Delete a playlist folder (playlists inside are moved to root, not deleted).

    Args:
        folder_id: ID of the folder to delete (from get_folders)

    Returns:
        Confirmation of deletion
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        folder = await anyio.to_thread.run_sync(session.folder, folder_id)
        folder_name = folder.name or folder_id
        await anyio.to_thread.run_sync(folder.remove)

        return DeleteFolderResult(
            status="success",
            folder_id=folder_id,
            message=f"Folder '{folder_name}' deleted (playlists moved to root)",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to delete folder: {str(e)}")


# =============================================================================
# Playlist Shuffle
# =============================================================================

@mcp.tool()
async def shuffle_playlist(playlist_id: str) -> ShufflePlaylistResult:
    """
    Shuffle the tracks of a playlist randomly.

    Reads the current tracks, clears the playlist, then re-adds all
    tracks in a randomized order. The new order is persisted on Tidal.

    Args:
        playlist_id: ID of the playlist to shuffle

    Returns:
        Confirmation with number of tracks shuffled
    """
    import random

    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist '{playlist_id}' not found")

        # 1. Fetch current tracks
        tracks = await anyio.to_thread.run_sync(playlist.tracks)
        track_ids = [str(t.id) for t in tracks]
        n = len(track_ids)

        if n <= 1:
            return ShufflePlaylistResult(
                status="success",
                playlist_id=playlist_id,
                track_count=n,
                message="Nothing to shuffle (playlist has 0 or 1 track)",
            )

        # 2. Shuffle
        random.shuffle(track_ids)

        # 3. Clear playlist (uses remove_by_indices in chunks of 50)
        await anyio.to_thread.run_sync(playlist.clear)

        # 4. Re-add in shuffled order (single batch call at position 0)
        track_ids_int = [int(tid) for tid in track_ids]
        await anyio.to_thread.run_sync(
            lambda: playlist.add(track_ids_int, position=0)
        )

        return ShufflePlaylistResult(
            status="success",
            playlist_id=playlist_id,
            track_count=n,
            message=f"Playlist shuffled ({n} tracks reordered)",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to shuffle playlist: {str(e)}")


# =============================================================================
# Folder Management
# =============================================================================

@mcp.tool()
async def get_folders() -> FolderList:
    """
    List all playlist folders in the user's TIDAL collection.

    Returns:
        List of folders with id, name, and number of playlists inside.
        Use the folder id with move_playlist_to_folder or create_playlist_in_folder.
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        params = {
            "folderId": "root",
            "offset": 0,
            "limit": 50,
            "order": "NAME",
            "includeOnly": "FOLDER",
        }
        response = await anyio.to_thread.run_sync(
            lambda: session.request.request(
                "GET",
                "my-collection/playlists/folders",
                base_url=session.config.api_v2_location,
                params=params,
            )
        )
        items = response.json().get("items", [])

        folders = []
        for item in items:
            data = item.get("data", {})
            folder_id = data.get("id")
            name = item.get("name") or data.get("name", "")
            total = data.get("totalNumberOfItems", 0)
            if folder_id:
                folders.append(
                    FolderInfo(id=folder_id, name=name, total_items=total)
                )

        return FolderList(status="success", count=len(folders), folders=folders)
    except Exception as e:
        raise ToolError(f"Failed to get folders: {str(e)}")


@mcp.tool()
async def create_folder(name: str) -> CreateFolderResult:
    """
    Create a new playlist folder in the user's TIDAL collection.

    Args:
        name: Name of the folder to create

    Returns:
        Created folder details including id
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        folder = await anyio.to_thread.run_sync(
            session.user.create_folder, name
        )

        return CreateFolderResult(
            status="success",
            folder=FolderInfo(
                id=folder.id,
                name=folder.name or name,
                total_items=folder.total_number_of_items or 0,
            ),
            message=f"Folder '{name}' created",
        )
    except Exception as e:
        raise ToolError(f"Failed to create folder: {str(e)}")


@mcp.tool()
async def move_playlist_to_folder(playlist_id: str, folder_id: str) -> MovedToFolderResult:
    """
    Move a playlist into a folder.

    Args:
        playlist_id: UUID of the playlist to move
        folder_id: ID of the destination folder (from get_folders)

    Returns:
        Confirmation with folder name
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        folder = await anyio.to_thread.run_sync(
            session.folder, folder_id
        )

        await anyio.to_thread.run_sync(
            lambda: folder.add_items([playlist_id])
        )

        return MovedToFolderResult(
            status="success",
            playlist_id=playlist_id,
            folder_id=folder_id,
            folder_name=folder.name or folder_id,
            message=f"Playlist moved to folder '{folder.name}'",
        )
    except Exception as e:
        raise ToolError(f"Failed to move playlist to folder: {str(e)}")


# =============================================================================
# Catalog Details
# =============================================================================

@mcp.tool(annotations=READ_ONLY)
async def get_track(track_id: str) -> TrackDetails:
    """
    Get detailed information about a track, including ISRC and audio quality.

    Args:
        track_id: ID of the track

    Returns:
        Track details: version, ISRC, explicit flag, popularity, position on album,
        release date, copyright, availability and audio quality tiers
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        track = await anyio.to_thread.run_sync(session.track, track_id)
        if not track:
            raise ToolError(f"Track with ID '{track_id}' not found")

        release = getattr(track.album, "release_date", None) if track.album else None
        return TrackDetails(
            status="success",
            track=_track_model(track),
            version=track.version or None,
            isrc=getattr(track, "isrc", None),
            explicit=bool(track.explicit),
            popularity=track.popularity,
            track_number=track.track_num,
            volume_number=track.volume_num,
            release_date=_date_str(release or track.tidal_release_date),
            copyright=getattr(track, "copyright", None),
            available=bool(track.available),
            quality=_audio_quality(track),
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get track: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_audio_quality(item_type: Literal["track", "album"], item_id: str) -> AudioQualityResult:
    """
    Get the best audio quality TIDAL offers for a track or an album.

    Useful to pick the best version among several releases of the same music.
    TIDAL exposes quality tiers, not the exact sample rate: Hi-Res means 24-bit FLAC
    up to 192 kHz, Lossless means 16-bit / 44.1 kHz FLAC.

    Args:
        item_type: 'track' or 'album'
        item_id: ID of the track or album

    Returns:
        Quality tiers: lossless, Hi-Res, Dolby Atmos, plus a readable summary
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        loader = session.track if item_type == "track" else session.album
        item = await anyio.to_thread.run_sync(loader, item_id)
        if not item:
            raise ToolError(f"{item_type.capitalize()} with ID '{item_id}' not found")

        return AudioQualityResult(
            status="success",
            item_type=item_type,
            item_id=item_id,
            title=item.name,
            artist=_primary_artist(item),
            quality=_audio_quality(item),
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get audio quality: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_tracks_by_isrc(isrc: str) -> TrackList:
    """
    Find every TIDAL track for an ISRC (the unique code of a recording).

    One recording often appears on several releases (original album, compilations,
    reissues), each with its own track ID.

    Args:
        isrc: ISRC code, e.g. 'USQX91300108' (dashes allowed)

    Returns:
        Matching tracks, streamable and most popular first (usually the original release)
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    code = _normalize_isrc(isrc)
    try:
        matches = await anyio.to_thread.run_sync(_lookup_isrc, code)
        tracks = [_track_model(t) for t in matches]
        return TrackList(status="success", query=code, count=len(tracks), tracks=tracks)
    except Exception as e:
        raise ToolError(f"ISRC lookup failed: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_albums_by_barcode(barcode: str) -> AlbumList:
    """
    Find albums on TIDAL from the barcode (UPC/EAN) printed on a CD or record.

    Args:
        barcode: 8 to 14 digit barcode, e.g. '886443927087'

    Returns:
        Matching albums (empty list if TIDAL does not have this release)
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    code = barcode.strip().replace(" ", "").replace("-", "")
    if not code.isdigit() or not 8 <= len(code) <= 14:
        raise ToolError(f"Invalid barcode: '{barcode}' (expected 8 to 14 digits)")

    try:
        try:
            matches = await anyio.to_thread.run_sync(session.get_albums_by_barcode, code)
        except ObjectNotFound:
            matches = []
        albums = [_album_model(a) for a in matches]
        return AlbumList(status="success", query=code, count=len(albums), albums=albums)
    except Exception as e:
        raise ToolError(f"Barcode lookup failed: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_album_review(album_id: str) -> AlbumReview:
    """
    Get TIDAL's editorial review of an album.

    Args:
        album_id: ID of the album

    Returns:
        Review text (raises an error if the album has no review)
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        album = await anyio.to_thread.run_sync(session.album, album_id)
        if not album:
            raise ToolError(f"Album with ID '{album_id}' not found")

        try:
            raw = await anyio.to_thread.run_sync(album.review)
        except Exception:
            raise ToolError(f"No review available for album '{album.name}'")

        return AlbumReview(
            status="success",
            album_id=album_id,
            album_title=album.name,
            artist=_primary_artist(album),
            text=WIMP_LINK_PATTERN.sub(r"\1", raw).strip(),
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get album review: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_artist_ep_singles(artist_id: str, limit: int = 20) -> AlbumList:
    """
    Get an artist's EPs and singles (not included in get_artist_albums).

    Args:
        artist_id: ID of the artist
        limit: Maximum releases to return (default: 20, max: 100)

    Returns:
        List of EPs and singles
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 100)
        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        releases = await anyio.to_thread.run_sync(lambda: artist.get_ep_singles(limit=limit))
        albums = [_album_model(a) for a in releases]
        return AlbumList(status="success", count=len(albums), albums=albums)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get EPs and singles: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_artist_appearances(artist_id: str, limit: int = 20) -> AlbumList:
    """
    Get compilations and other artists' albums on which an artist appears.

    Args:
        artist_id: ID of the artist
        limit: Maximum albums to return (default: 20, max: 100)

    Returns:
        List of albums featuring the artist
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        limit = min(max(1, limit), 100)
        artist = await anyio.to_thread.run_sync(session.artist, artist_id)
        if not artist:
            raise ToolError(f"Artist with ID '{artist_id}' not found")

        releases = await anyio.to_thread.run_sync(lambda: artist.get_other(limit=limit))
        albums = [_album_model(a) for a in releases]
        return AlbumList(status="success", count=len(albums), albums=albums)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get artist appearances: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_image_urls(
    item_type: Literal["album", "artist", "playlist", "mix", "user"], item_id: str
) -> ImageUrls:
    """
    Get image URLs (cover, artist photo, playlist or mix artwork, profile picture).

    Args:
        item_type: 'album', 'artist', 'playlist', 'mix' or 'user'
        item_id: ID of the item

    Returns:
        Image URL for every size TIDAL serves, keyed by size (e.g. '1280x1280')
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    if item_type == "user":
        item_id = _validate_user_id(item_id)

    def collect() -> Tuple[str, Dict[str, str]]:
        sizes = IMAGE_SIZES[item_type]
        if item_type == "user":
            profile = _fetch_profile(item_id)
            picture = profile.get("picture")
            urls = {f"{s}x{s}": _picture_url(picture, s) for s in sizes} if picture else {}
            return profile.get("name") or item_id, urls

        loaders = {
            "album": session.album,
            "artist": session.artist,
            "playlist": session.playlist,
            "mix": session.mix,
        }
        item = loaders[item_type](item_id)
        urls = {}
        for s in sizes:
            try:
                urls[f"{s}x{s}"] = item.image(s)
            except (ValueError, AttributeError, TypeError):
                break  # no image for this item
        if item_type == "playlist":
            for width, height in PLAYLIST_WIDE_SIZES:
                try:
                    urls[f"{width}x{height}"] = item.wide_image(width, height)
                except (ValueError, AttributeError, TypeError):
                    break
        return getattr(item, "name", None) or getattr(item, "title", None) or item_id, urls

    try:
        name, urls = await anyio.to_thread.run_sync(collect)
        if not urls:
            raise ToolError(f"No image available for {item_type} '{name}'")
        return ImageUrls(status="success", item_type=item_type, item_id=item_id, name=name, urls=urls)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get images: {str(e)}")


# =============================================================================
# Other Users
# =============================================================================

@mcp.tool(annotations=READ_ONLY)
async def get_user_profile(user_id: str) -> UserProfile:
    """
    Get the public profile of a TIDAL user.

    Args:
        user_id: TIDAL user ID (the 'creator_id' field of a playlist)

    Returns:
        Display name, handle, follower counts and profile picture
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    user_id = _validate_user_id(user_id)
    try:
        profile = await anyio.to_thread.run_sync(_fetch_profile, user_id)
        picture = profile.get("picture")
        return UserProfile(
            status="success",
            id=str(profile.get("userId") or user_id),
            name=profile.get("name") or "",
            handle=profile.get("handle"),
            followers=profile.get("numberOfFollowers") or 0,
            follows=profile.get("numberOfFollows") or 0,
            profile_type=profile.get("profileType"),
            picture_url=_picture_url(picture, 600) if picture else None,
        )
    except Exception as e:
        raise ToolError(f"Failed to get user profile: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_user_public_playlists(user_id: str, limit: int = 50) -> PlaylistList:
    """
    Get the public playlists of a TIDAL user (works with your own user ID too).

    Args:
        user_id: TIDAL user ID (the 'creator_id' field of a playlist)
        limit: Maximum playlists to return (default: 50, max: 50)

    Returns:
        List of the user's public playlists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    user_id = _validate_user_id(user_id)
    limit = min(max(1, limit), 50)

    def fetch() -> list:
        json_obj = session.request.request(
            "GET",
            f"user-playlists/{user_id}/public",
            base_url=session.config.api_v2_location,
            params={"limit": limit, "offset": 0},
        ).json()
        items = [item["playlist"] for item in json_obj.get("items", []) if item.get("playlist")]
        return session.request.map_json({"items": items}, parse=session.playlist().parse_factory)

    try:
        raw = await anyio.to_thread.run_sync(fetch)
        playlists = [_playlist_model(p) for p in raw]
        return PlaylistList(status="success", count=len(playlists), playlists=playlists)
    except Exception as e:
        raise ToolError(f"Failed to get public playlists: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_favorite_counts() -> FavoriteCounts:
    """
    Count the items in each of your favorites collections.

    Returns:
        Number of favorite tracks, albums, artists and playlists
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        favorites = session.user.favorites
        tracks = await anyio.to_thread.run_sync(favorites.get_tracks_count)
        albums = await anyio.to_thread.run_sync(favorites.get_albums_count)
        artists = await anyio.to_thread.run_sync(favorites.get_artists_count)
        playlists = await anyio.to_thread.run_sync(favorites.get_playlists_count)
        return FavoriteCounts(
            status="success", tracks=tracks, albums=albums, artists=artists, playlists=playlists
        )
    except Exception as e:
        raise ToolError(f"Failed to count favorites: {str(e)}")


# =============================================================================
# Editorial Pages (Home, Explore, For You, genres, moods...)
# =============================================================================

@mcp.tool(annotations=READ_ONLY)
async def browse_page(page: str = "home", items_per_section: int = 5) -> PageView:
    """
    Browse a TIDAL editorial page, section by section, as in the TIDAL app.

    Pages: 'home' (personalized feed), 'explore', 'for_you', 'hires', 'genres',
    'local_genres', 'moods', 'mixes', or any page path returned by this tool
    (an item's 'path' for links, or a section's 'more_path' for its full list).

    Args:
        page: Page name or path (default: 'home')
        items_per_section: Items previewed per section (default: 5, max: 20, 0 for titles only)

    Returns:
        Page sections with their index, title, a preview of their items and more_path.
        Use get_page_section to list all items of one section.
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    path = _normalize_page(page)
    items_per_section = min(max(0, items_per_section), 20)
    try:
        title, raw_sections = await anyio.to_thread.run_sync(_load_page_sections, path)

        sections = []
        for index, raw in enumerate(raw_sections):
            entries = _page_entries(raw)
            if not entries:
                continue  # e.g. video-only sections
            sections.append(
                PageSection(
                    index=index,
                    title=getattr(raw, "title", None) or "",
                    item_count=len(entries),
                    more_path=_section_more_path(raw),
                    items=entries[:items_per_section],
                )
            )

        return PageView(status="success", page=path, title=title, count=len(sections), sections=sections)
    except Exception as e:
        raise ToolError(f"Failed to browse page: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def get_page_section(
    page: str, section_index: int, limit: int = 50, offset: int = 0
) -> PageSectionItems:
    """
    List the items of one section of an editorial page.

    A section only holds what the page displays (often 10 to 15 items). When the
    section has a more_path, pass it to browse_page to get the complete list.

    Args:
        page: Page name or path, as given to browse_page
        section_index: Section index from browse_page
        limit: Maximum items to return (default: 50, max: 100)
        offset: Index of the first item to return (default: 0)

    Returns:
        Section items (tracks, albums, artists, playlists, mixes or links to other pages)
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    path = _normalize_page(page)
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    try:
        _, raw_sections = await anyio.to_thread.run_sync(_load_page_sections, path)
        if not 0 <= section_index < len(raw_sections):
            raise ToolError(
                f"Page '{path}' has no section {section_index} (it has {len(raw_sections)})"
            )

        raw = raw_sections[section_index]
        entries = _page_entries(raw)
        selected = entries[offset:offset + limit]
        return PageSectionItems(
            status="success",
            page=path,
            section_index=section_index,
            title=getattr(raw, "title", None) or "",
            more_path=_section_more_path(raw),
            total=len(entries),
            offset=offset,
            count=len(selected),
            items=selected,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to get page section: {str(e)}")


# =============================================================================
# Multi-seed Recommendations
# =============================================================================

@mcp.tool(annotations=READ_ONLY)
async def recommend_tracks(
    seed_track_ids: List[str],
    limit: int = 30,
    exclude_playlist_id: Optional[str] = None,
    max_per_artist: int = 2,
) -> TrackRecommendations:
    """
    Recommend tracks from several seed tracks by combining their TIDAL radios.

    Tracks suggested by several seeds rank first, then the seeds' radios are
    interleaved. Seeds, duplicates (same title and artist) and tracks already in
    exclude_playlist_id are skipped.

    Args:
        seed_track_ids: 1 to 10 track IDs describing the wanted style
        limit: Maximum tracks to return (default: 30, max: 100)
        exclude_playlist_id: Playlist whose tracks must not be recommended (optional),
            typically the playlist being extended
        max_per_artist: Maximum tracks per artist (default: 2, 0 for no limit)

    Returns:
        Recommended tracks, each with the seed IDs that suggested it
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    seeds = list(dict.fromkeys(s.strip() for s in seed_track_ids if s.strip()))
    if not 1 <= len(seeds) <= 10:
        raise ToolError("Provide between 1 and 10 seed track IDs")
    limit = min(max(1, limit), 100)
    max_per_artist = max(0, max_per_artist)

    def compute():
        excluded_ids = set(seeds)
        excluded_keys = set()
        seed_tracks = {}
        for seed_id in seeds:
            track = session.track(seed_id)
            seed_tracks[seed_id] = track
            excluded_keys.add(_song_key(track))

        if exclude_playlist_id:
            playlist = session.playlist(exclude_playlist_id)
            items, _ = _fetch_playlist_items(playlist)
            for item in items:
                excluded_ids.add(str(item.id))
                if isinstance(item, tidalapi.Track):
                    excluded_keys.add(_song_key(item))

        candidates: Dict[Tuple[str, str], dict] = {}
        skipped = set()
        without_radio = []
        for seed_id in seeds:
            try:
                radio = seed_tracks[seed_id].get_track_radio(limit=100)
            except Exception:
                without_radio.append(seed_id)
                continue
            for rank, track in enumerate(radio):
                key = _song_key(track)
                if str(track.id) in excluded_ids or key in excluded_keys:
                    skipped.add(key)
                    continue
                candidate = candidates.setdefault(key, {"track": track, "seeds": [], "rank": rank})
                if seed_id not in candidate["seeds"]:
                    candidate["seeds"].append(seed_id)
                candidate["rank"] = min(candidate["rank"], rank)

        ordered = sorted(candidates.values(), key=lambda c: (-len(c["seeds"]), c["rank"]))
        per_artist: Counter = Counter()
        selected = []
        for candidate in ordered:
            artist = _primary_artist(candidate["track"]).casefold()
            if max_per_artist and per_artist[artist] >= max_per_artist:
                continue
            per_artist[artist] += 1
            selected.append(candidate)
            if len(selected) >= limit:
                break
        return selected, len(skipped), without_radio

    try:
        selected, excluded_count, without_radio = await anyio.to_thread.run_sync(compute)
        tracks = [
            RecommendedTrack(**_track_model(c["track"]).model_dump(), seed_ids=c["seeds"])
            for c in selected
        ]
        return TrackRecommendations(
            status="success",
            seed_ids=seeds,
            seeds_without_radio=without_radio,
            excluded_count=excluded_count,
            count=len(tracks),
            tracks=tracks,
        )
    except Exception as e:
        raise ToolError(f"Failed to recommend tracks: {str(e)}")


# =============================================================================
# Playlist Analysis
# =============================================================================

@mcp.tool(annotations=READ_ONLY)
async def analyze_playlist(playlist_id: str, top_artists: int = 10) -> PlaylistAnalysis:
    """
    Analyze a playlist: duration, dominant artists, decades, duplicates, sequencing.

    Duplicates are songs with the same title and artist, whatever the release or
    version; each occurrence gives its position, usable with remove_tracks_from_playlist.

    Args:
        playlist_id: ID of the playlist
        top_artists: Number of most represented artists to list (default: 10, max: 50)

    Returns:
        Playlist statistics and the list of duplicated songs
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    top_artists = min(max(1, top_artists), 50)
    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        if not playlist:
            raise ToolError(f"Playlist with ID '{playlist_id}' not found")

        items, truncated = await anyio.to_thread.run_sync(_fetch_playlist_items, playlist)
        tracks = [(pos, t) for pos, t in enumerate(items) if isinstance(t, tidalapi.Track)]

        artist_counts: Counter = Counter()
        decades: Counter = Counter()
        groups: Dict[Tuple[str, str], List[Tuple[int, object]]] = {}
        duration = explicit = unavailable = without_date = same_artist = 0
        previous_artist = None
        for pos, t in tracks:
            artist = _primary_artist(t)
            artist_counts[artist] += 1
            duration += t.duration or 0
            explicit += 1 if t.explicit else 0
            unavailable += 0 if t.available else 1
            release = getattr(t.album, "release_date", None) if t.album else None
            release = release or t.tidal_release_date
            if release:
                decades[f"{release.year // 10 * 10}s"] += 1
            else:
                without_date += 1
            if artist == previous_artist:
                same_artist += 1
            previous_artist = artist
            groups.setdefault(_song_key(t), []).append((pos, t))

        duplicates = [
            DuplicateGroup(
                title=occurrences[0][1].name,
                artist=_primary_artist(occurrences[0][1]),
                occurrences=[
                    DuplicateOccurrence(
                        position=pos,
                        track_id=str(t.id),
                        album=t.album.name if t.album else "Unknown Album",
                        version=t.version or None,
                    )
                    for pos, t in occurrences
                ],
            )
            for occurrences in groups.values()
            if len(occurrences) > 1
        ]
        duplicates.sort(key=lambda d: (-len(d.occurrences), d.occurrences[0].position))

        n = len(tracks)
        return PlaylistAnalysis(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            track_count=n,
            truncated=truncated,
            total_duration_seconds=duration,
            average_duration_seconds=duration // n if n else 0,
            distinct_artists=len(artist_counts),
            top_artists=[
                ArtistShare(artist=name, track_count=count, percent=round(100 * count / n, 1))
                for name, count in artist_counts.most_common(top_artists)
            ],
            decades=dict(sorted(decades.items())),
            tracks_without_date=without_date,
            explicit_tracks=explicit,
            unavailable_tracks=unavailable,
            consecutive_same_artist=same_artist,
            duplicate_count=len(duplicates),
            duplicates=duplicates,
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to analyze playlist: {str(e)}")


@mcp.tool(annotations=READ_ONLY)
async def compare_playlists(
    playlist_id_a: str, playlist_id_b: str, max_listed: int = 100
) -> PlaylistComparison:
    """
    Compare two playlists: songs in both, songs only in A, songs only in B.

    Songs are matched on title and artist, so two releases of the same song count
    as the same song.

    Args:
        playlist_id_a: ID of playlist A
        playlist_id_b: ID of playlist B
        max_listed: Maximum songs listed per category (default: 100, max: 500).
            Counts always cover every song.

    Returns:
        Counts and lists of shared and unique songs
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    max_listed = min(max(1, max_listed), 500)

    def load(pid: str):
        playlist = session.playlist(pid)
        if not playlist:
            raise ToolError(f"Playlist with ID '{pid}' not found")
        items, _ = _fetch_playlist_items(playlist)
        index: Dict[Tuple[str, str], object] = {}
        for item in items:
            if isinstance(item, tidalapi.Track):
                index.setdefault(_song_key(item), item)
        return playlist, len(items), index

    try:
        playlist_a, count_a, index_a = await anyio.to_thread.run_sync(load, playlist_id_a)
        playlist_b, count_b, index_b = await anyio.to_thread.run_sync(load, playlist_id_b)

        def entry(key) -> ComparedTrack:
            t = index_a.get(key) or index_b[key]
            return ComparedTrack(
                title=t.name,
                artist=_primary_artist(t),
                track_id_a=str(index_a[key].id) if key in index_a else None,
                track_id_b=str(index_b[key].id) if key in index_b else None,
            )

        common = [k for k in index_a if k in index_b]
        only_a = [k for k in index_a if k not in index_b]
        only_b = [k for k in index_b if k not in index_a]

        return PlaylistComparison(
            status="success",
            playlist_a_id=playlist_id_a,
            playlist_a_name=playlist_a.name,
            playlist_b_id=playlist_id_b,
            playlist_b_name=playlist_b.name,
            track_count_a=count_a,
            track_count_b=count_b,
            common_count=len(common),
            only_in_a_count=len(only_a),
            only_in_b_count=len(only_b),
            lists_truncated=max(len(common), len(only_a), len(only_b)) > max_listed,
            common=[entry(k) for k in common[:max_listed]],
            only_in_a=[entry(k) for k in only_a[:max_listed]],
            only_in_b=[entry(k) for k in only_b[:max_listed]],
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to compare playlists: {str(e)}")


# =============================================================================
# Playlist Editing (extended)
# =============================================================================

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
async def clear_playlist(playlist_id: str) -> ClearPlaylistResult:
    """
    Remove every track from one of your playlists (the playlist itself is kept).

    Args:
        playlist_id: ID of the playlist to empty

    Returns:
        Number of items removed
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        playlist = _require_user_playlist(playlist, playlist_id)

        count = (playlist.num_tracks or 0) + (getattr(playlist, "num_videos", 0) or 0)
        await anyio.to_thread.run_sync(playlist.clear)

        return ClearPlaylistResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            tracks_removed=count,
            message=f"Removed {count} items from playlist '{playlist.name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to clear playlist: {str(e)}")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
async def merge_playlists(
    playlist_id: str, source_playlist_id: str, allow_duplicates: bool = False
) -> MergePlaylistsResult:
    """
    Append all tracks of a source playlist to one of your playlists.

    The source playlist is left unchanged and can be anyone's playlist.

    Args:
        playlist_id: ID of your playlist receiving the tracks
        source_playlist_id: ID of the playlist to copy tracks from
        allow_duplicates: Add tracks already in the target (default: False)

    Returns:
        Number of tracks added
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        playlist = _require_user_playlist(playlist, playlist_id)
        source = await anyio.to_thread.run_sync(session.playlist, source_playlist_id)
        if not source:
            raise ToolError(f"Playlist with ID '{source_playlist_id}' not found")

        added = await anyio.to_thread.run_sync(
            lambda: playlist.merge(source_playlist_id, allow_duplicates=allow_duplicates)
        )

        return MergePlaylistsResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            source_playlist_id=source_playlist_id,
            source_playlist_name=source.name,
            tracks_added=len(added),
            message=f"Added {len(added)} tracks from '{source.name}' to '{playlist.name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to merge playlists: {str(e)}")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
async def move_playlist_tracks(playlist_id: str, indices: List[int], position: int) -> MoveTracksResult:
    """
    Move one or more tracks to a new position inside one of your playlists.

    Args:
        playlist_id: ID of the playlist
        indices: 0-based positions of the tracks to move (from get_playlist_tracks order)
        position: 0-based position where the tracks go; -1 moves them to the end

    Returns:
        Number of tracks moved and the position used
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    if not indices:
        raise ToolError("Provide at least one index to move")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        playlist = _require_user_playlist(playlist, playlist_id)

        size = (playlist.num_tracks or 0) + (getattr(playlist, "num_videos", 0) or 0)
        invalid = [i for i in indices if not 0 <= i < size]
        if invalid:
            raise ToolError(f"Indices out of range for a playlist of {size} items: {invalid}")
        if position >= size or position < 0:
            position = size

        await anyio.to_thread.run_sync(lambda: playlist.move_by_indices(sorted(set(indices)), position))

        moved = len(set(indices))
        return MoveTracksResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            tracks_moved=moved,
            position=position,
            message=f"Moved {moved} tracks to position {position} in '{playlist.name}'",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to move tracks: {str(e)}")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def set_playlist_visibility(playlist_id: str, public: bool) -> PlaylistVisibilityResult:
    """
    Make one of your playlists public (visible on your profile) or private.

    Args:
        playlist_id: ID of the playlist
        public: True to make it public, False to make it private

    Returns:
        New visibility of the playlist
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        playlist = _require_user_playlist(playlist, playlist_id)

        action = playlist.set_playlist_public if public else playlist.set_playlist_private
        await anyio.to_thread.run_sync(action)

        visibility = "public" if public else "private"
        return PlaylistVisibilityResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            public=public,
            message=f"Playlist '{playlist.name}' is now {visibility}",
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to change playlist visibility: {str(e)}")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
async def add_tracks_to_playlist_by_isrc(
    playlist_id: str, isrcs: List[str], allow_duplicates: bool = False
) -> AddByIsrcResult:
    """
    Add tracks to one of your playlists from their ISRC codes.

    For each ISRC, the streamable and most popular release is chosen (usually the
    original album rather than a compilation).

    Args:
        playlist_id: ID of the playlist
        isrcs: ISRC codes to add, in order
        allow_duplicates: Add tracks already in the playlist (default: False)

    Returns:
        Tracks chosen, number actually added, and ISRCs not found on TIDAL
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    if not isrcs:
        raise ToolError("Provide at least one ISRC")
    codes = [_normalize_isrc(code) for code in isrcs]

    try:
        playlist = await anyio.to_thread.run_sync(session.playlist, playlist_id)
        playlist = _require_user_playlist(playlist, playlist_id)

        resolved, not_found = [], []
        for code in codes:
            matches = await anyio.to_thread.run_sync(_lookup_isrc, code)
            if matches:
                resolved.append(matches[0])
            else:
                not_found.append(code)

        added: list = []
        if resolved:
            added = await anyio.to_thread.run_sync(
                lambda: playlist.add([str(t.id) for t in resolved], allow_duplicates=allow_duplicates)
            )

        return AddByIsrcResult(
            status="success",
            playlist_id=playlist_id,
            playlist_name=playlist.name,
            tracks_added=len(added),
            resolved=[_track_model(t) for t in resolved],
            not_found=not_found,
            message=f"Added {len(added)} tracks to '{playlist.name}'"
            + (f", {len(not_found)} ISRC not found" if not_found else ""),
        )
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to add tracks by ISRC: {str(e)}")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def move_playlist_to_root(playlist_id: str) -> MovedToFolderResult:
    """
    Take a playlist out of its folder and put it back at the root of your collection.

    Args:
        playlist_id: UUID of the playlist to move

    Returns:
        Confirmation of the move
    """
    if not await ensure_authenticated():
        raise ToolError("Not authenticated. Please run the 'login' tool first.")

    try:
        await anyio.to_thread.run_sync(
            lambda: session.folder().move_items_to_folder([playlist_id], folder="root")
        )

        return MovedToFolderResult(
            status="success",
            playlist_id=playlist_id,
            folder_id="root",
            folder_name="root",
            message="Playlist moved to the root of your collection",
        )
    except Exception as e:
        raise ToolError(f"Failed to move playlist to root: {str(e)}")


# =============================================================================
# Server Entry Point
# =============================================================================

def run_server() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_server()
