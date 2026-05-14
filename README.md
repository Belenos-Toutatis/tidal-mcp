# TIDAL MCP Server

A MCP (Model Context Protocol) server for TIDAL music streaming service. Clean API wrapper following official MCP best practices — thin wrappers around tidalapi methods with no custom business logic.

## Features

### 50 Tools

| Category | Tool | Description |
|----------|------|-------------|
| **Auth** | `login` | OAuth browser authentication |
| **Search** | `search_tracks` | Find tracks by name/artist |
| | `search_albums` | Find albums by name/artist |
| | `search_artists` | Find artists by name |
| | `search_playlists` | Find public playlists |
| **Favorites — Tracks** | `get_favorite_tracks` | Get liked tracks |
| | `add_track_to_favorites` | Like a track |
| | `remove_track_from_favorites` | Unlike a track |
| **Favorites — Albums** | `get_favorite_albums` | Get saved albums |
| | `add_album_to_favorites` | Save an album |
| | `remove_album_from_favorites` | Remove a saved album |
| **Favorites — Artists** | `get_favorite_artists` | Get followed artists |
| | `add_artist_to_favorites` | Follow an artist |
| | `remove_artist_from_favorites` | Unfollow an artist |
| **Favorites — Playlists** | `get_favorite_playlists` | Get saved playlists |
| | `add_playlist_to_favorites` | Save a playlist |
| | `remove_playlist_from_favorites` | Remove a saved playlist |
| **Favorites — Mixes** | `get_favorite_mixes` | Get saved mixes |
| | `add_mix_to_favorites` | Save a mix |
| | `remove_mix_from_favorites` | Remove a saved mix |
| **Playlists** | `get_user_playlists` | List your playlists |
| | `get_playlist_tracks` | Get tracks from a playlist |
| | `create_playlist` | Create a new playlist |
| | `add_tracks_to_playlist` | Add tracks to a playlist |
| | `remove_tracks_from_playlist` | Remove tracks from a playlist |
| | `update_playlist` | Update name/description |
| | `shuffle_playlist` | Shuffle tracks randomly |
| | `delete_playlist` | Delete a playlist |
| **Albums** | `get_album` | Get album details |
| | `get_album_tracks` | Get all tracks from an album |
| | `get_similar_albums` | Find similar albums |
| **Artists** | `get_artist` | Get artist details with bio |
| | `get_artist_albums` | Get artist discography |
| | `get_artist_top_tracks` | Get artist's popular tracks |
| | `get_similar_artists` | Find similar artists |
| **Radio** | `get_track_radio` | Similar tracks to a seed track |
| | `get_artist_radio` | Tracks in an artist's style |
| **Editorial** | `get_genres` | List all available genres |
| | `get_genre_tracks` | Top tracks for a genre |
| | `get_genre_albums` | Albums for a genre |
| | `get_genre_playlists` | Editorial playlists for a genre |
| | `get_mixes` | Your personalized mixes |
| | `get_mix_tracks` | Tracks inside a mix |
| **Lyrics** | `get_track_lyrics` | Get lyrics (text + LRC subtitles) |
| **Folders** | `get_folders` | List your playlist folders |
| | `get_folder_contents` | List playlists inside a folder |
| | `create_folder` | Create a new folder |
| | `rename_folder` | Rename a folder |
| | `delete_folder` | Delete a folder |
| | `move_playlist_to_folder` | Move a playlist into a folder |

## Installation

### Requirements
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Clone and enter directory
git clone https://github.com/Belenos-Toutatis/tidal-mcp
cd tidal-mcp

# Install with uv
uv sync

# Or with pip
pip install -e .
```

## Usage

### With Claude Desktop

Add to your Claude Desktop config:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tidal": {
      "command": "/path/to/uv",
      "args": [
        "--directory", "/path/to/tidal-mcp",
        "run", "tidal-mcp"
      ]
    }
  }
}
```

> **Note**: Use full path to `uv` (find with `which uv`)

### With MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run tidal-mcp
```

## Authentication

On first use, run the `login` tool (Claude will open your browser automatically).
To authenticate manually beforehand:

```bash
python authenticate.py
```

Sessions are persisted and reused across restarts.

## Example Workflows

### Discover and create a genre playlist

```
1. get_genres()                              → find genre paths
2. get_genre_albums("jazz", limit=20)        → browse albums
3. get_album_tracks(album_id)                → get tracks
4. create_playlist("Jazz 2025")              → create playlist
5. add_tracks_to_playlist(id, track_ids)     → fill it
6. shuffle_playlist(id)                      → randomize order
7. create_folder("Jazz")                     → organize
8. move_playlist_to_folder(id, folder_id)    → move into folder
```

### Build a radio-style playlist from a track

```
1. search_tracks("Daft Punk Get Lucky")      → find seed track
2. get_track_radio(track_id, limit=30)       → similar tracks
3. create_playlist("Get Lucky Radio")        → create playlist
4. add_tracks_to_playlist(id, track_ids)     → fill it
```

### Explore an artist's catalogue

```
1. search_artists("Gojira")                  → find artist
2. get_artist(artist_id)                     → bio + details
3. get_artist_albums(artist_id)              → discography
4. get_artist_top_tracks(artist_id)          → popular tracks
5. get_similar_artists(artist_id)            → discover related
```

### Manage your personalized mixes

```
1. get_mixes()                               → list mixes
2. get_mix_tracks(mix_id)                    → get tracks
3. add_tracks_to_playlist(playlist_id, ...)  → save to playlist
4. add_mix_to_favorites(mix_id)             → bookmark mix
```

## Project Structure

```
tidal-mcp/
├── pyproject.toml           # Project configuration
├── README.md                # This file
├── CLAUDE.md                # AI development guidance
└── src/
    └── tidal_mcp/
        ├── __init__.py      # Package init
        ├── models.py        # Pydantic response models
        └── server.py        # MCP server — 50 tools
```

## Dependencies

- `fastmcp>=2.12.0` — MCP protocol framework
- `tidalapi>=0.8.6` — TIDAL API client
- `anyio>=4.0.0` — Async utilities

## Troubleshooting

### Authentication fails
- Ensure tidalapi >= 0.8.6
- Delete `.tidal-sessions/` and re-authenticate

### Shuffle not visible in Tidal app
- Make sure the playlist sort is set to **Custom** (not Date/Artist/Album)

### Search returns no results
- Simplify the query (single artist or song name)

### 412 errors on playlist operations
- This is a Tidal ETag conflict — retry the operation

## License

MIT

## Credits

Built with [FastMCP](https://github.com/jlowin/fastmcp) and [tidalapi](https://github.com/tamland/python-tidal).
