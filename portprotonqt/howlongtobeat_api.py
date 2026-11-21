import orjson
import time
from dataclasses import dataclass
from typing import Any
from threading import Thread
import requests
from portprotonqt.config import proxy_config
from portprotonqt.time_utils import format_playtime
from portprotonqt.logger import get_logger
from portprotonqt.config.cache import CacheManager
from PySide6.QtCore import QObject, Signal

logger = get_logger(__name__)

@dataclass
class GameEntry:
    """Game information from HowLongToBeat."""
    main_story: float | None = None
    main_extra: float | None = None
    completionist: float | None = None

@dataclass
class SearchConfig:
    """Search configuration."""
    token: str
    hp_key: str | None = None
    hp_val: str | None = None

class HTTPClient:
    """HTTP client for HowLongToBeat API."""
    BASE_URL = 'https://howlongtobeat.com/'
    SEARCH_URL = BASE_URL + "api/search/site"
    AUTH_URL = SEARCH_URL + "/init"

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Origin': self.BASE_URL.rstrip('/'),
            'referer': self.BASE_URL
        })
        proxy_settings = proxy_config.get_proxy()
        if proxy_settings:
            self.session.proxies.update(proxy_settings)

    def get_search_config(self) -> SearchConfig | None:
        try:
            response = self.session.get(
                self.AUTH_URL,
                params={"t": int(time.time() * 1000)},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else type(exc).__name__
            logger.warning("HLTB initialization failed: %s", status)
            return None
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            logger.warning("HLTB initialization returned no token")
            return None
        hp_key, hp_val = data.get("hpKey"), data.get("hpVal")
        if isinstance(hp_key, str) and hp_key and isinstance(hp_val, str) and hp_val:
            return SearchConfig(token, hp_key, hp_val)
        return SearchConfig(token)

    def search_games(self, game_name: str, page: int = 1, config: SearchConfig | None = None) -> str | None:
        if not config:
            config = self.get_search_config()
        if not config:
            return None
        for retry in range(2):
            payload = self._build_search_payload(game_name, page, config)
            headers = {
                'content-type': 'application/json',
                'x-auth-token': config.token
            }
            if config.hp_key and config.hp_val:
                headers.update({'x-hp-key': config.hp_key, 'x-hp-val': config.hp_val})
            try:
                response = self.session.post(
                    self.SEARCH_URL,
                    headers=headers,
                    data=orjson.dumps(payload),
                    timeout=self.timeout
                )
            except requests.RequestException:
                return None
            if response.status_code == 200:
                return response.text
            if response.status_code != 403 or retry:
                return None
            config = self.get_search_config()
            if not config:
                return None
        return None

    def _build_search_payload(self, game_name: str, page: int, config: SearchConfig) -> dict[str, Any]:
        payload = {
            'searchType': "games",
            'searchTerms': game_name.split(),
            'searchPage': page,
            'size': 1,  # Limit to 1 result
            'searchOptions': {
                'games': {
                    'userId': 0,
                    'platform': "",
                    'sortCategory': "popular",
                    'rangeCategory': "main",
                    'rangeTime': {'min': None, 'max': None},
                    'gameplay': {
                        'perspective': "",
                        'flow': "",
                        'genre': "",
                        "difficulty": ""
                    },
                    'year': "",
                    'modifier': ""
                },
                'users': {'sortCategory': "postcount"},
                'lists': {'sortCategory': "follows"},
                'filter': "",
                'sort': 0,
                'randomizer': 0
            },
            'useCache': True
        }
        if config.hp_key and config.hp_val:
            payload[config.hp_key] = config.hp_val
        return payload

class ResultParser:
    """Search results parser."""
    def parse_results(self, json_response: str) -> list[GameEntry]:
        try:
            data = orjson.loads(json_response)
            games = []
            if data.get("data"):
                game_data = data["data"][0]
                games.append(self._parse_game_entry(game_data))
            return games
        except (orjson.JSONDecodeError, KeyError, IndexError):
            return []

    def _parse_game_entry(self, game_data: dict[str, Any]) -> GameEntry:
        game = GameEntry()
        time_fields = [
            ("comp_main", "main_story"),
            ("comp_plus", "main_extra"),
            ("comp_100", "completionist")
        ]
        all_zero = all(game_data.get(json_field, 0) == 0 for json_field, _ in time_fields)
        for json_field, attr_name in time_fields:
            if json_field in game_data:
                time_seconds = game_data[json_field]
                time_hours = None if all_zero else round(time_seconds / 3600, 2)
                setattr(game, attr_name, time_hours)
        return game


class HowLongToBeat(QObject):
    """Main class for HowLongToBeat API."""
    searchCompleted = Signal(list)

    def __init__(self, minimum_similarity: float = 0.4, timeout: int = 60, parent=None):
        super().__init__(parent)
        self.minimum_similarity = minimum_similarity
        self.http_client = HTTPClient(timeout)
        self.cache_manager = CacheManager()

    def _load_from_cache(self, game_name: str) -> str | None:
        """Try to load data from cache if it exists."""
        return self.cache_manager.load_text(f"hltb_{game_name}")

    def _save_to_cache(self, game_name: str, json_response: str):
        """Save data to cache, storing only first game times."""
        try:
            data = orjson.loads(json_response)
            if data.get("data"):
                first_game = data["data"][0]
                simplified_data = {
                    "data": [{
                        "comp_main": first_game.get("comp_main", 0),
                        "comp_plus": first_game.get("comp_plus", 0),
                        "comp_100": first_game.get("comp_100", 0)
                    }]
                }
                self.cache_manager.save_json(f"hltb_{game_name}", simplified_data)
        except (orjson.JSONDecodeError, IndexError):
            pass

    def search(self, game_name: str, case_sensitive: bool = True) -> list[GameEntry] | None:
        if not game_name or not game_name.strip():
            return None
        # Check cache
        cached_response = self._load_from_cache(game_name)
        if cached_response:
            try:
                parser = ResultParser()
                return parser.parse_results(cached_response)
            except orjson.JSONDecodeError:
                pass
        # If not in cache, make request
        json_response = self.http_client.search_games(game_name)
        if not json_response:
            return None
        # Save only first game to cache
        self._save_to_cache(game_name, json_response)
        parser = ResultParser()
        return parser.parse_results(json_response)

    def format_game_time(self, game_entry: GameEntry, time_field: str = "main_story") -> str | None:
        time_value = getattr(game_entry, time_field, None)
        if time_value is None:
            return None
        time_seconds = int(time_value * 3600)
        return format_playtime(time_seconds)

    def search_with_callback(self, game_name: str, case_sensitive: bool = True):
        """Search for game in background thread and emit signal with results."""
        def search_thread():
            try:
                results = self.search(game_name, case_sensitive)
                self.searchCompleted.emit(results if results else [])
            except Exception as e:
                logger.error("Error in search_with_callback: %s", e)
                self.searchCompleted.emit([])

        thread = Thread(target=search_thread)
        thread.daemon = True
        thread.start()
