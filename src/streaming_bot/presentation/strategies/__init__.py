"""Estrategias de sitio. Cada sitio = una clase que implementa ISiteStrategy."""

from streaming_bot.presentation.strategies.amazon_music import AmazonMusicStrategy
from streaming_bot.presentation.strategies.apple_music import AppleMusicStrategy
from streaming_bot.presentation.strategies.deezer import DeezerStrategy
from streaming_bot.presentation.strategies.demo_todomvc import DemoTodoMVCStrategy
from streaming_bot.presentation.strategies.soundcloud import SoundcloudStrategy
from streaming_bot.presentation.strategies.tidal import TidalStrategy

__all__ = [
    "AmazonMusicStrategy",
    "AppleMusicStrategy",
    "DeezerStrategy",
    "DemoTodoMVCStrategy",
    "SoundcloudStrategy",
    "TidalStrategy",
]
